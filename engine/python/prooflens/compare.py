"""The comparison of a claim with its Lean, as one JSON document (`machinechecked compare`), and
targeted queries about the declarations it involves.

A comparison packet is read from a build's site data (`<work dir>/site/data/`, written by
`view`, `build` and the full assessment): the claim's complete printed passage with its source
and how it was obtained, every linked declaration's complete statement, the definitions those
statements use, and, at the informed stage, what people have recorded about the correspondence.
It reuses the records the reader shows; it runs no Lean and changes no file.

A packet is filtered by stage before it is returned. `read` holds the paper only: the passage,
with the paper's `\\lean{...}` tags removed, since they name declarations. `compare` adds the
formal material and its mechanical structure: statements, binders, definitions, Lean's checks.
`informed` adds prior interpretations: correspondence notes, review reports and markers, symbol
links, statuses and the assessment's findings, and, when a workspace is named, its auditor's
requirements of the claim with the passages that govern them and their alignment with Lean. Independent review uses `read` before its
reading is locked and `compare` before its verdict; any other use is an informed investigation.

What a build does not hold is said, not implied: a section the stage withholds is listed in
`retrieval.withheld`, content not extracted yet in `retrieval.unavailable` (with the issue that
owns it), and a list cut by `limit` gives the cursor that continues it. Passages and linked
statements are never cut; a proof step's context in the proof is kept to its first 20000
characters, and a passage whose context was cut says where.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

PACKET_SCHEMA = "machinechecked/compare@1"
QUERY_SCHEMA = "machinechecked/query@1"
STAGES = ("read", "compare", "informed")

# What each stage shows, cumulatively.
CONTAINS = {"read": ["paper"], "compare": ["paper", "Lean"],
            "informed": ["paper", "Lean", "prior interpretations"]}

# Content the packet's shape provides for but the engine does not extract yet, by owner issue.
NOT_EXTRACTED = [
    {"what": "standing assumptions and definitions the passage refers to", "owner": "#69"},
    {"what": "definitions expanded at their actual arguments", "owner": "#97"},
    {"what": "properties carried by the types of the objects", "owner": "#98"},
    {"what": "typed facts inside proofs", "owner": "#145",
     "request": "`compare --query proof-facts NAME` reads one proof on request"},
]

# The constants Lean generates for a declaration (equations, matchers, auxiliary proofs).
GENERATED = re.compile(r"_.*|match_\d+|proof_\d+|eq_\d+|eq_def|eq_unfold")

# The paper's tags that name Lean declarations (prooflens.sty, and the blueprint's).
LEAN_TAGS = re.compile(r"\\(?:lean|leanok|mathlibok|notready)\b\*?(?:\s*\{[^{}]*\})?")

# The PDF extraction keeps this many characters of a statement (`pdfclaims.py`).
PDF_TEXT_CHARS = 4000


class CompareError(RuntimeError):
    """A request that cannot be answered from this build, with what it might have meant."""

    def __init__(self, message: str, kind: str = "unknown", candidates: list | None = None):
        super().__init__(message)
        self.kind = kind
        self.candidates = candidates or []

    def to_json(self) -> dict:
        return {"kind": self.kind, "message": str(self), "candidates": self.candidates}


def _text(seg) -> str:
    return (seg or {}).get("text", "") if isinstance(seg, dict) else str(seg or "")


def _generated(name: str, owner: str) -> bool:
    rest = name[len(owner) + 1:] if name.startswith(owner + ".") else ""
    return bool(rest) and all(GENERATED.fullmatch(c) for c in rest.split("."))


class Site:
    """The claims, declaration records and review queue of one build's site data."""

    def __init__(self, data_dir: Path):
        self.data = Path(data_dir)
        p = self.data / "index.json"
        if not p.exists():
            raise CompareError("no build here: run `machinechecked view` or `machinechecked "
                               "build` first", "no-build")
        self.index = json.loads(p.read_text(encoding="utf-8"))
        self.claims = list(self.index.get("claims") or [])
        self._by_id = {c["id"]: c for c in self.claims}
        self._chunks: dict[str, dict | None] = {}
        self._store: dict[str, dict] | None = None

    def snapshot(self) -> dict:
        """What this build is: its release and evidence, the project's commit and each paper's
        revision and PDF checksum."""
        proj = self.index.get("project") or {}
        return {"release": self.index.get("release"), "evidence": self.index.get("evidence"),
                "mode": self.index.get("mode") or "full",
                "project": {k: proj.get(k) for k in ("name", "commit", "repository")
                            if proj.get(k) is not None},
                "papers": [{k: p.get(k) for k in ("id", "title", "revision", "pdf_sha256")
                            if p.get(k) is not None}
                           for p in self.index.get("papers") or []]}

    def chunk(self, cid: str) -> dict | None:
        """A claim's full record."""
        if cid not in self._chunks:
            meta = self._by_id.get(cid)
            p = meta and self.data / "claims" / meta["file"]
            self._chunks[cid] = (json.loads(p.read_text(encoding="utf-8"))
                                 if p and p.exists() else None)
        return self._chunks[cid]

    def resolve_claim(self, query: str) -> str:
        """The id of the claim `query` names: its id, its key within the paper (`thm:main`) or
        its printed number (`Theorem 2.1`)."""
        q = str(query or "").strip()
        if q in self._by_id:
            return q
        norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().lower()
        for match in (lambda c: c["id"].split(":", 1)[-1] == q,
                      lambda c: norm(c.get("number")) == norm(q)):
            found = [c["id"] for c in self.claims if match(c)]
            if len(found) == 1:
                return found[0]
            if found:
                raise CompareError(f"{q!r} names {len(found)} claims; give its id", "ambiguous",
                                   found)
        near = difflib.get_close_matches(q, [c["id"] for c in self.claims], n=5, cutoff=0.3)
        raise CompareError(f"no claim {q!r} in release {self.index.get('release')}",
                           "unknown-claim", near)

    def store(self) -> dict[str, dict]:
        """Every declaration record of the build, by name."""
        if self._store is None:
            self._store = {}
            for p in sorted((self.data / "decls").glob("*.json")):
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if rec.get("name"):
                    self._store.setdefault(rec["name"], {**rec, "_key": p.stem})
        return self._store

    def script_owners(self) -> dict[str, str]:
        """The declaration each tactic-default script of the store belongs to: the one whose
        type has the default (`targets.script_owners`)."""
        if not hasattr(self, "_scripts"):
            from .targets import script_owners
            self._scripts = script_owners(self.store().values())
        return self._scripts

    def generated(self, name: str, owner: str) -> bool:
        """Whether `name` is a constant Lean generated for `owner`: by its name (`_generated`),
        or, for the tactic script of a tactic default, by the records, whatever its name."""
        return _generated(name, owner) or self.script_owners().get(name) == owner

    def queue(self) -> dict | None:
        p = self.data / "review-queue.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def lean_index(self) -> list[dict]:
        p = self.data / "lean-index.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        except ValueError:
            return []

    def retrieval(self):
        """The build's content index of every project declaration (`retrieval.py`), or None
        when the build has none (no Lean was read, or a build before it existed)."""
        if not hasattr(self, "_retrieval"):
            from .retrieval import Retrieval
            p = self.data / "retrieval.json"
            try:
                self._retrieval = Retrieval.from_export(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, KeyError):
                self._retrieval = None
        return self._retrieval

    def numbering(self) -> dict | None:
        """The project's references to the paper's numbers (`numbering.py`)."""
        p = self.data / "numbering.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        except ValueError:
            return None


# -- the paper ---------------------------------------------------------------------------------

def context_cut_reason(cut: dict) -> str:
    """Where a proof step's context in the proof was cut (`steps.cut_text`), in words."""
    if not cut.get("line"):
        # Evidence written before cuts were recorded does not say where.
        return f"its context in the proof keeps only its first {cut.get('kept')} characters"
    return (f"its context in the proof is cut at {cut.get('file')}:{cut['line']}, after the "
            f"first {cut.get('kept')} of its {cut.get('chars')} characters (it runs to line "
            f"{cut.get('end_line')})")


def passage(ch: dict, stage: str) -> dict:
    """A claim's printed passage, complete, with where it is and how it was obtained. A passage
    the build does not hold is `available: false`, with its source reference. Where the text
    comes from (`quality`) and how precisely it is placed (`source.position`) are separate
    facts: a paper read from its PDF gives text extracted from the PDF; a LaTeX paper gives its
    source text, placed exactly by its anchor or approximately (a proof step located by its
    line). A proof step's context in the proof that the build holds only in part makes the
    passage `complete: false`, with where it was cut (`context_cut`)."""
    anchor = ch.get("anchor") or {}
    approx = anchor.get("kind") in ("approximate", "pdf")
    from_pdf = ((ch.get("source_evidence") or {}).get("state") == "pdf-only"
                or anchor.get("kind") == "pdf")
    text = ch.get("statement_tex")
    quality = "text extracted from the PDF" if from_pdf else "LaTeX source"
    if not text and anchor.get("statement"):
        # Only an anchor found in the PDF keeps its text apart from `statement_tex`.
        text, quality = anchor["statement"], "text extracted from the PDF"
    begin, end = anchor.get("begin") or [None], anchor.get("end") or [None]
    source = {"file": anchor.get("file") or ch.get("location"), "line": anchor.get("line"),
              "label": anchor.get("label"), "page": begin[0], "page_end": end[0],
              "position": "approximate" if approx else "exact" if anchor else None,
              "sha256": ch.get("source_sha256") or anchor.get("source_sha256")}
    out = {"claim": ch["id"], "number": ch.get("number"), "heading": ch.get("heading"),
           "source": {k: v for k, v in source.items() if v is not None}}
    st = ch.get("step")
    if st:
        # A proof step is read in its proof: what the proof has fixed before it, and how it
        # is used after it. Its question is whether the printed step holds.
        par = st.get("parent") or {}
        out["step"] = {"unit": st.get("unit"),
                       "parent": {k: par.get(k) for k in ("id", "number") if par.get(k)},
                       "question": "Does the printed step hold, in its context?"}
        if ch.get("context_tex"):
            out["context"] = ch["context_tex"]
            if ch.get("context_cut"):
                out["context_cut"] = ch["context_cut"]
    parts = [{k: p.get(k) for k in ("file", "start_line", "end_line", "macro", "text")
              if p.get(k) is not None} for p in ch.get("source_parts") or []]
    if not text and parts:
        # A pin of several passages holds each one's source text, the claim's own first.
        text, quality = parts[0]["text"], "LaTeX source"
    if not text:
        return {**out, "available": False, "text": None,
                "reason": "the build holds no printed text for this claim; read it in the paper "
                          "at the source given"}
    cuts = []
    if quality.startswith("text extracted") and len(text) >= PDF_TEXT_CHARS:
        cuts.append(f"the PDF extraction keeps the first {PDF_TEXT_CHARS} characters of a "
                    "statement")
    if out.get("context_cut"):
        cuts.append(context_cut_reason(out["context_cut"]))
    complete = not cuts
    removed = []
    if stage == "read" and LEAN_TAGS.search(text):
        text = re.sub(r"[ \t]{2,}", " ", LEAN_TAGS.sub("", text)).strip()
        removed.append("the paper's \\lean{...} tags, which name Lean declarations")
    out.update(available=True, text=text, quality=quality, complete=complete)
    if parts:
        if stage == "read":
            for part in parts:
                if LEAN_TAGS.search(part["text"]):
                    part["text"] = re.sub(r"[ \t]{2,}", " ",
                                          LEAN_TAGS.sub("", part["text"])).strip()
                    if not removed:
                        removed.append("the paper's \\lean{...} tags, which name Lean "
                                       "declarations")
        out["parts"] = parts
    if not complete:
        out["reason"] = "; ".join(cuts) + "; read the rest in the paper at the source given"
    if removed:
        out["removed"] = removed
    return out


# -- the Lean ----------------------------------------------------------------------------------

def _statement(st: dict | None) -> dict | None:
    """A statement in full: its exact text, its binders and conclusion with their expression
    identifiers, and the whole of it as one tree (`tree`), with where each variable stands."""
    if not st:
        return None
    exact = st.get("exact")
    return {"text": _text(exact) if exact else None, "exact": exact,
            "binders": [{k: b.get(k) for k in ("id", "name", "role", "binder", "supplies", "type")
                         if b.get(k) is not None} for b in st.get("binders") or []],
            "conclusion": st.get("conclusion"), "tree": st.get("tree"),
            "closure": list(st.get("closure") or []), "fingerprint": st.get("fingerprint")}


def _link(l: dict, role: str) -> dict:
    out = {"id": f"decl:{l['name']}", "name": l["name"], "role": role,
           "kind": l.get("kind"), "module": l.get("module"), "path": l.get("path"),
           "range": l.get("range"), "fingerprint": l.get("fingerprint"),
           "linked_by": l.get("source"), "doc": l.get("doc"),
           "statement": _statement(l.get("statement")),
           "lean": {"axioms": l.get("axioms"), "sorry": l.get("sorry"),
                    "errors": l.get("errors") or []}}
    if role == "candidate" and l.get("why"):
        out["why"] = l["why"]
    if out["statement"] is None:
        out["unavailable"] = "Lean did not check this declaration in this build, so its " \
                             "statement is not known"
    return out


def _step_decls(ch: dict) -> list[dict]:
    """A proof step's Lean: the declarations linked as establishing it, then those of the
    different formal route used instead (which do not state it)."""
    st = ch.get("step") or {}
    return [_link(l, "establishes the step") for l in st.get("links") or []] + \
        [_link(l, "formal route used instead") for l in (st.get("route") or {}).get("links") or []]


def _clause(cl: dict) -> dict:
    proofs = cl.get("proofs") or {}
    return {"id": f"decl:{cl.get('spec')}", "name": cl.get("spec"), "clause": cl.get("name"),
            "label": cl.get("label"), "role": "locked statement",
            "accept": cl.get("accept"), "refute": cl.get("refute"),
            "corrects": cl.get("corrects"), "witness": cl.get("witness"),
            "statement": _statement(cl.get("statement")),
            "proofs": {k: {x: v.get(x) for x in ("name", "module", "range", "axioms", "sorry",
                                                  "errors") if x in v}
                       for k, v in proofs.items() if isinstance(v, dict)},
            "lean": cl.get("checks")}


def _definition(rec: dict, stage: str) -> dict:
    out = {"id": f"def:{rec['name']}", "name": rec["name"], "kind": rec.get("kind"),
           "module": rec.get("module"), "range": rec.get("range"), "doc": rec.get("doc"),
           "fingerprint": rec.get("fingerprint"),
           "signature": _text(rec.get("signature")) or None,
           "value": _text(rec.get("value")) or None, "uses": list(rec.get("uses") or []),
           "expansion": "generic",
           "note": "the definition as declared; its expansion at the arguments a statement "
                   "applies it to is not extracted yet (#97)"}
    if stage == "informed" and rec.get("review") is not None:
        out["review"] = rec["review"]
    return out


def _definitions(site: Site, ch_list: list[dict], names: list[str], stage: str,
                 owners: tuple = ()) -> list[dict]:
    """The records of `names` (each statement's closure), in order, each with the constants
    Lean generated for it."""
    store = site.store()
    keys = {}
    for ch in ch_list:
        keys.update(ch.get("decls") or {})
    out, seen = [], set()
    for n in names:
        if n in seen:
            continue
        seen.add(n)
        rec = store.get(n)
        if rec is None and n in keys:
            p = site.data / "decls" / f"{keys[n]}.json"
            rec = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if rec is None:
            out.append({"id": f"def:{n}", "name": n, "available": False,
                        "reason": "this build holds no record of it"})
            continue
        d = _definition(rec, stage)
        d["generated_for"] = next((m for m in [*owners, *names]
                                   if m != n and site.generated(n, m)), None)
        out.append(d)
    return out


def _page(items: list[dict], limit: int | None, after: str | None) -> tuple[list[dict], dict]:
    start = 0
    if after:
        ids = [x["id"] for x in items]
        if after not in ids:
            raise CompareError(f"cursor {after!r} is not an item of this list", "bad-cursor")
        start = ids.index(after) + 1
    part = items[start:start + limit] if limit else items[start:]
    more = start + len(part) < len(items)
    return part, {"total": len(items), "returned": len(part), "complete": not more and not start,
                  "after": after, "next": part[-1]["id"] if more and part else None}


# -- packets -----------------------------------------------------------------------------------

def _informed(ch: dict) -> dict:
    """What people and the assessment have recorded about a claim."""
    return {"claim": ch["id"],
            "correspondence": ch.get("correspondence"), "reviews": ch.get("reviews") or [],
            "symbols": ch.get("symbols") or [],
            "clause_reviews": [{"clause": cl.get("name"), "spec": cl.get("spec"),
                                "spec_review": cl.get("spec_review"),
                                "def_reviews": cl.get("def_reviews")}
                               for cl in ch.get("clauses") or []],
            "assessment": {k: ch.get(k) for k in ("status", "status_code", "class", "blockers",
                                                   "findings", "scope", "scope_note",
                                                   "source_evidence", "source_matches")},
            **({"step": {k: (ch["step"] or {}).get(k) for k in ("correspondence", "route",
                                                                 "review")}}
               if ch.get("step") else {})}


def _withheld(stage: str) -> list[dict]:
    out = []
    if stage == "read":
        out.append({"section": "lean", "reason": "the Lean is shown after the reading is locked"})
    if stage in ("read", "compare"):
        out.append({"section": "interpretations", "reason": "correspondence notes, reviews, "
                    "symbol links, statuses and recorded requirements are shown after the "
                    "verdict"})
    return out


def _head(site: Site, stage: str, request: dict) -> dict:
    if stage not in STAGES:
        raise CompareError(f"stage {stage!r} is not one of {', '.join(STAGES)}", "bad-stage")
    return {"schema": PACKET_SCHEMA, "request": request, "snapshot": site.snapshot(),
            "stage": stage, "contains": CONTAINS[stage]}


def _claim_ref(ch: dict) -> dict:
    return {k: ch.get(k) for k in ("id", "key", "paper", "number", "kind", "heading")
            if ch.get(k) is not None}


# Content a packet leaves to a targeted query, because it runs Lean.
ON_REQUEST = [{"what": "where each declaration is used, each application's arguments and the "
                       "source of each premise", "query": "uses"},
              {"what": "how each main result uses a linked declaration, and which claims' Lean "
                       "uses it", "query": "impact"}]


def _retrieval(stage: str, sections: list[str], page: dict | None, extra: list | None = None):
    return {"included": sections, "withheld": _withheld(stage),
            "unavailable": ([] if stage == "read" else NOT_EXTRACTED) + (extra or []),
            "on_request": [] if stage == "read" else ON_REQUEST,
            "definitions": page}


def claim_packet(site: Site, claim: str, stage: str = "informed", limit: int | None = None,
                 after: str | None = None, reading: dict | None = None) -> dict:
    """The comparison packet of one claim: its passage, its linked declarations (and, from
    the compare stage, unconfirmed suggestions as candidates) and the definitions they use.
    `reading` is a workspace's reading of the claim (`requirements.reading`, with that
    workspace's `compositions`), included at the informed stage only."""
    cid = site.resolve_claim(claim)
    ch = site.chunk(cid)
    if ch is None:
        raise CompareError(f"{cid}: its record is missing from this build", "no-record")
    out = _head(site, stage, {"claim": claim, "stage": stage, "limit": limit, "after": after})
    out["claim"] = _claim_ref(ch)
    out["paper"] = {"passages": [passage(ch, stage)]}
    sections = ["paper"]
    page = None
    if stage != "read":
        decls = _step_decls(ch) if ch.get("step") else \
            [_link(l, "link") for l in ch.get("links") or []]
        decls += [_clause(cl) for cl in ch.get("clauses") or [] if cl.get("statement")]
        cands = [_link(s, "candidate") for s in ch.get("suggestions") or []]
        names = [n for d in decls for n in ((d.get("statement") or {}).get("closure") or [])]
        names += [n for n in (ch.get("decls") or {}) if n not in names]
        defs, page = _page(_definitions(site, [ch], names, stage), limit, after)
        out["lean"] = {"declarations": decls, "candidates": cands, "definitions": defs,
                       "references": ch.get("references") or []}
        num = site.numbering()
        if num and num.get("pattern"):
            out["lean"]["numbering"] = num["pattern"]
        sections.append("lean")
        if not decls:
            out["lean"]["note"] = ("no Lean is linked to this step: review the printed step "
                                   "itself" if ch.get("step") else
                                   "no declaration is linked to this claim")
    if stage == "informed":
        out["interpretations"] = _informed(ch)
        if reading is not None:
            reading = dict(reading)
            out["interpretations"]["compositions"] = reading.pop("compositions", [])
            out["interpretations"]["requirements"] = reading
        sections.append("interpretations")
    out["retrieval"] = _retrieval(stage, sections, page)
    return out


def unit_packet(site: Site, unit: dict, stage: str) -> dict:
    """The packet of one review unit at a stage of the protocol: the passages of every claim
    of the unit, and from the compare stage the unit's own Lean (a claim's confirmed links, a
    locked statement, or a definition) with the definitions it uses."""
    chunks = [site.chunk(c["id"]) for c in unit.get("claims") or []]
    out = _head(site, stage, {"unit": unit["id"], "stage": stage})
    # The unit's declaration names are Lean: not part of the read stage.
    keys = ("id", "kind", "unit", "parent", "papers") if stage == "read" else \
        ("id", "kind", "unit", "parent", "name", "lean", "route", "papers")
    out["unit"] = {k: unit.get(k) for k in keys if unit.get(k) is not None}
    missing = [c["id"] for c, ch in zip(unit.get("claims") or [], chunks) if ch is None]
    chunks = [ch for ch in chunks if ch is not None]
    out["claims"] = [_claim_ref(ch) for ch in chunks]
    out["paper"] = {"passages": [passage(ch, stage) for ch in chunks],
                    "complete": not missing, "missing": missing}
    if unit["kind"] == "def":
        out["paper"]["note"] = (f"a definition used by {len(unit.get('claims') or [])} claim(s); "
                                "every one of their passages is included")
    sections = ["paper"]
    page = None
    extra = []
    if stage != "read":
        decls, names = [], []
        if unit["kind"] == "step":
            for ch in chunks[:1]:
                decls += _step_decls(ch)
        elif unit["kind"] == "link":
            want = unit.get("lean") or []
            for ch in chunks:
                for l in ch.get("links") or []:
                    if l["name"] in want and not any(d["name"] == l["name"] for d in decls):
                        decls.append(_link(l, "link"))
        elif unit["kind"] == "spec":
            cl = next((x for ch in chunks for x in ch.get("clauses") or []
                       if x.get("spec") == unit["name"]), None)
            if cl:
                decls.append(_clause(cl))
        else:
            rec = site.store().get(unit["name"])
            if rec:
                decls.append({**_definition(rec, stage), "role": "definition under review"})
                names = sorted(m for m in site.store() if site.generated(m, rec["name"]))
                names += [n for n in rec.get("uses") or [] if n not in names]
        for d in decls:
            names += [n for n in (d.get("statement") or {}).get("closure") or []
                      if n not in names]
        if not decls and unit["kind"] == "step":
            out["note"] = "no Lean is linked to this step: review the printed step itself"
        elif not decls:
            extra.append({"what": f"the Lean of {unit['id']}", "owner": None,
                          "reason": "this build holds no statement for it"})
        defs = _definitions(site, chunks, names, stage,
                            (unit["name"],) if unit["kind"] == "def" else ())
        out["lean"] = {"declarations": decls, "definitions": defs}
        page = {"total": len(defs), "returned": len(defs), "complete": True, "after": None,
                "next": None}
        sections.append("lean")
    if stage == "informed":
        out["interpretations"] = {"author_review": unit.get("author_review") or [],
                                  "claims": [_informed(ch) for ch in chunks]}
        sections.append("interpretations")
    out["retrieval"] = _retrieval(stage, sections, page, extra)
    return out


# -- targeted queries --------------------------------------------------------------------------

def _mentions(site: Site, name: str) -> list[dict]:
    """Declarations of the build whose statement mentions the constant `name`."""
    found: dict[str, dict] = {}

    def refs(seg) -> set:
        return {s.get("ref") for s in (seg or {}).get("segments") or [] if isinstance(s, dict)}

    for meta in site.claims:
        ch = site.chunk(meta["id"]) or {}
        for l in (ch.get("links") or []) + (ch.get("suggestions") or []):
            st = l.get("statement") or {}
            if name in refs(st.get("exact")) and l["name"] != name:
                found.setdefault(l["name"], {"id": f"decl:{l['name']}", "name": l["name"],
                                             "module": l.get("module"),
                                             "statement": _text(st.get("exact")),
                                             "complete": True, "claims": []})
                found[l["name"]]["claims"].append(ch["id"])
        for cl in ch.get("clauses") or []:
            st = cl.get("statement") or {}
            if cl.get("spec") and name in refs(st.get("exact")):
                found.setdefault(cl["spec"], {"id": f"decl:{cl['spec']}", "name": cl["spec"],
                                              "statement": _text(st.get("exact")),
                                              "complete": True, "claims": []})
                found[cl["spec"]]["claims"].append(ch["id"])
    for n, rec in site.store().items():
        if n not in found and n != name and name in refs(rec.get("signature")):
            found[n] = {"id": f"decl:{n}", "name": n, "module": rec.get("module"),
                        "statement": _text(rec.get("signature")), "complete": True,
                        "claims": []}
    # The build's content index holds every project declaration's complete statement and the
    # constants it mentions.
    ret = site.retrieval()
    if ret is not None:
        for d in ret.docs:
            n = d["name"]
            if n not in found and n != name and name in (d.get("uses") or []):
                found[n] = {"id": f"decl:{n}", "name": n, "module": d.get("module"),
                            "statement": d.get("type") or "", "complete": True, "claims": []}
        return sorted(found.values(), key=lambda r: r["name"])
    # An older build's index holds a preview of each type: a match there is a candidate whose
    # full statement `dependencies` (or `inspect`) gives.
    pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"(?![\w])")
    short = name.rsplit(".", 1)[-1]
    spat = re.compile(r"(?<![\w.])" + re.escape(short) + r"(?![\w])")
    for d in site.lean_index():
        n = d.get("name")
        if not n or n in found or n == name:
            continue
        ty = d.get("type") or ""
        if pat.search(ty) or spat.search(ty):
            found[n] = {"id": f"decl:{n}", "name": n, "module": d.get("module"),
                        "statement": ty, "complete": len(ty) < 300, "claims": [],
                        "note": "a preview of the type, from the build's index of the project"}
    return sorted(found.values(), key=lambda r: r["name"])


QUERIES = {
    "definition": "a declaration's record: its type, its value or body, and the constants Lean "
                  "generated for it",
    "mentions": "the declarations whose statement mentions a constant",
    "search": "the project's declarations whose complete statements best match a claim's printed "
              "statement, a Lean expression or words, with the reasons for each",
    "dependencies": "what a declaration's statement and proof use (runs `inspect`)",
    "uses": "where a declaration is applied, and the source of each premise",
    "proof-facts": "the typed facts inside a declaration's proof, each with its assumptions and "
                   "cases (Lean reads the proof once; the answer is cached)",
    "composition": "the auditors' compositions for a claim: the steps, the results each rests "
                   "on, substitutions, identifications, obligations and any Lean bridge",
    "impact": "how each main result uses a declaration (the path from its proof or its "
              "statement, and the applications at the end), and which claims' Lean uses it",
}
# Queries the engine does not answer yet, by owner issue.
NOT_YET: dict[str, str] = {}


def linked_claims(site: Site) -> dict[str, list[str]]:
    """The claims each declaration is linked to in this build (confirmed links and locked
    statements, not suggestions)."""
    out: dict[str, list[str]] = {}
    for meta in site.claims:
        ch = site.chunk(meta["id"]) or {}
        names = [l["name"] for l in ch.get("links") or []]
        names += [n for cl in ch.get("clauses") or [] for n in (cl.get("spec"), cl.get("accept"))
                  if n]
        for n in dict.fromkeys(names):
            out.setdefault(n, []).append(ch.get("id") or meta["id"])
    return out


def mark_claims(doc: dict, claims: dict[str, list[str]]) -> dict:
    """A uses document with the claims each user, further caller and caller is linked to."""
    if not doc.get("ok"):
        return doc
    for key in ("users", "further"):
        for u in doc.get(key) or []:
            if u["name"] in claims:
                u["claims"] = claims[u["name"]]
    for a in doc.get("applications") or []:
        if a["caller"] in claims:
            a["caller_claims"] = claims[a["caller"]]
    doc["linked_users"] = sorted({u["name"] for k in ("users", "further")
                                  for u in doc.get(k) or [] if u["name"] in claims})
    return doc


def query(site: Site, op: str, target: str, limit: int | None = None, after: str | None = None,
          root: Path | None = None, log=None, match: str | None = None,
          workspace: str | None = None, main: list[str] | None = None,
          every_library: bool = False) -> dict:
    """One targeted query: `{op, context, target, results, provenance, retrieval}`. An
    operation the engine does not extract yet answers `available: false` with its owner.
    `search` with `every_library` searches every library of the project, also those the
    build's index leaves out.
    `proof-facts` answers with the facts inside the target's proof (ranked against `match` when
    given), and the declaration, locals, cases and source-only lines in `subject`.
    `composition` answers with the compositions recorded for the target claim in the
    workspaces of the build's working directory (or in `workspace`): prior interpretations,
    which an independent review reads only after its verdict. `impact` traces the target from
    the main results named in `main` (declarations or claims), else from those saved in a
    workspace of the working directory (in `workspace`, when named), else from the declarations
    linked to the paper's theorems (`impact.py`)."""
    if op not in QUERIES:
        raise CompareError(f"no query {op!r}; the queries are: {', '.join(QUERIES)}", "bad-query")
    out = {"schema": QUERY_SCHEMA, "op": op, "target": target, "limit": limit, "after": after,
           "context": site.snapshot()}
    if op in NOT_YET:
        return {**out, "available": False, "results": [],
                "reason": f"{QUERIES[op]}: not extracted yet ({NOT_YET[op]})"}
    if op == "definition":
        store = site.store()
        rec = store.get(target)
        if rec is None:
            raise CompareError(f"{target}: this build holds no record of it; `dependencies` "
                               "asks Lean", "unknown-declaration",
                               difflib.get_close_matches(target, list(store), n=5, cutoff=0.5))
        names = [target] + sorted(m for m in store if site.generated(m, target))
        results = _definitions(site, [], names, "compare")
        prov = "the build's declaration records"
    elif op == "mentions":
        results = _mentions(site, target)
        prov = "the statements of the build, and its index of the project"
    elif op == "uses":
        if root is None:
            raise CompareError("`uses` needs the Lean project", "no-project")
        from .uses import uses
        results = [mark_claims(uses(root, target, None, log=log), linked_claims(site))]
        prov = "Lean (the elaborated terms of the project), cached until a Lean input changes"
    elif op == "impact":
        results = [_impact(site, root, target, main, log, workspace)]
        prov = ("Lean (the references of the project's declarations and the applications of the "
                "target, from its elaborated terms), cached until a Lean input changes")
    elif op == "search":
        if every_library and root is None:
            raise CompareError("searching every library needs the Lean project", "no-project")
        return {**out, **search(site, target, limit, after, root if every_library else None,
                                log)}
    elif op == "composition":
        from . import composition as cp
        from .targets import Snapshot, TargetError
        from .workspace import WorkspaceError
        cid = site.resolve_claim(target)
        try:
            results = cp.query(site.data.parent.parent, Snapshot(site.data), cid, root,
                               workspace)
        except (WorkspaceError, TargetError) as e:
            raise CompareError(str(e), "unknown-workspace") from None
        out["subject"] = {"claim": cid, "contains": ["prior interpretations"],
                          "note": "an auditor's composition is a reading: its basis is the "
                                  "auditor's argument unless a bridge is checked, and it changes "
                                  "no status"}
        prov = ("the workspaces of the working directory; a bridge's check from the facts store "
                "(`workspace show` asks Lean again)")
    elif op == "proof-facts":
        if root is None:
            raise CompareError("`proof-facts` needs the Lean project", "no-project")
        from .proof_facts import rank
        doc = _proof_facts(root, target, log)
        results = rank(doc["facts"], match) if match else doc["facts"]
        out["subject"] = {k: doc.get(k) for k in ("declaration", "proof", "locals", "scopes",
                                                   "source_only", "note", "cache")}
        if match:
            out["match"] = {"query": match, "candidates": len(results),
                            "of": len(doc["facts"]),
                            "note": "ranked by shared symbols; a candidate is not a claim that "
                                    "one bound gives another"}
        prov = ("Lean (the declaration's elaborated proof), kept in the facts store until a "
                "module it was read from changes")
    else:
        if root is None:
            raise CompareError("`dependencies` needs the Lean project", "no-project")
        from .deps import inspect
        res = inspect(root, target, None, log=log)
        results = [res]
        prov = "Lean (inspect), cached until a Lean input changes"
    part, page = _page(results, limit, after)
    return {**out, "available": True, "results": part, "provenance": prov, "retrieval": page}


def search(site: Site, target: str, limit: int | None = None, after: str | None = None,
           every_library: Path | None = None, log=None) -> dict:
    """The content search (`retrieval.Retrieval.search`) the reader and the suggestions use. A
    target naming a claim searches with its printed statement, over declarations of its sort;
    any other target is the query itself. Nothing recorded by people (links, rejections, notes)
    enters the search or its results. It searches the build's content index; with
    `every_library` (the Lean project), the index of every built module instead, from the
    facts store, extracting what it does not hold (a paper's build leaves out the libraries
    formalization.yaml maps only to other papers)."""
    from .retrieval import paper_quantifiers
    if every_library is not None:
        ret, scope = _every_library(every_library, log)
    else:
        ret, scope = site.retrieval(), _build_scope(site)
    if ret is None:
        return {"available": False, "results": [],
                "reason": "this build has no content index of the project's declarations; "
                          "`machinechecked view` or `build` with the project built writes one"}
    try:
        cid = site.resolve_claim(target)
    except CompareError:
        cid = None
    kinds, order, subject = None, None, {"text": target}
    if cid:
        ch = site.chunk(cid) or {}
        text = " ".join(x for x in (ch.get("title"), ch.get("statement_tex")
                                    or (ch.get("anchor") or {}).get("statement")) if x)
        definition = ch.get("scope") == "definition"
        kinds = (lambda k: k != "theorem") if definition else (lambda k: k == "theorem")
        order = paper_quantifiers(text)
        subject = {"claim": cid, "text": text,
                   "kinds": "definitions" if definition else "theorems"}
    else:
        text = target
    try:
        res = ret.search(text, kinds=kinds, limit=limit or 20, after=after, paper_order=order)
    except ValueError as e:
        raise CompareError(str(e), "bad-cursor") from None
    for r in res["results"]:
        r["id"] = f"decl:{r['name']}"
    content = "complete statements, docstrings, names and the definitions each statement uses"
    prov = f"the build's content index ({content}); no Lean session" if every_library is None \
        else f"the index of every built module ({content}), from the facts store; Lean " \
             "indexes what it does not hold"
    return {"available": True, "subject": subject, "results": res["results"],
            "query": res["query"], "scope": {"declarations": len(ret), **scope},
            "provenance": prov, "retrieval": res["page"]}


def _build_scope(site: Site) -> dict:
    """What the build's content index covers: every built module, unless the build left out
    the libraries formalization.yaml maps only to other papers (`simple.index_scope`)."""
    left = site.index.get("index_scope") or {}
    if not left.get("left_out"):
        return {"what": "every user-facing declaration of the project's built modules, linked "
                        "or not"}
    return {"what": "every user-facing declaration of the built modules this paper's build "
                    "indexes, linked or not",
            "left_out": left["left_out"],
            "note": f"{left.get('modules')} built module(s) of {', '.join(left['left_out'])}, "
                    "which formalization.yaml maps only to other papers, are not in this "
                    "build's index; --all-libraries searches every library"}


def _every_library(root: Path, log) -> tuple:
    """The content index of every built module of the project, and what it covers."""
    from .retrieval import Retrieval
    from .simple import ViewError, project_index
    try:
        full, failed = project_index(root, log=log)
    except ViewError as e:
        raise CompareError(str(e), "no-project") from None
    scope = {"what": "every user-facing declaration of the project's built modules, linked or "
                     "not, whatever paper maps them"}
    if failed:
        scope["note"] = (f"{len(failed)} built module(s) could not be loaded and are not "
                         f"searched: {', '.join(sorted(failed)[:5])}"
                         + ("…" if len(failed) > 5 else ""))
    return Retrieval.build(full), scope


def _impact(site: Site, root: Path | None, target: str, main: list[str] | None, log,
            workspace: str | None = None) -> dict:
    """The impact document of `target` (`impact.impact`), or the reason there is none, as a
    refusal."""
    if root is None:
        raise CompareError("`impact` needs the Lean project", "no-project")
    from .impact import impact
    from .simple import ViewError
    saved = None if main else saved_main_results(site, workspace, root)
    try:
        return impact(site, root, target, main, log, saved)
    except ViewError as e:
        raise CompareError(str(e), "no-project") from None


def saved_main_results(site: Site, workspace: str | None, root: Path | None) -> dict | None:
    """The main results saved in the workspace named, else in the one workspace of the build's
    working directory that saves any, with what this build lacks of them (`problems`); None when
    no workspace saves any, and `{workspace, selected: None}` when the one named saves none.
    Several workspaces saving main results, and none named, is refused with their ids."""
    from . import workspace as wsp
    from .targets import Snapshot
    try:
        found = wsp.main_result_selections(site.data.parent.parent, workspace)
    except wsp.WorkspaceError as e:
        raise CompareError(str(e), "unknown-workspace") from None
    if not found:
        return {"workspace": workspace, "selected": None} if workspace else None
    if len(found) > 1:
        raise CompareError("several workspaces save main results ("
                           + ", ".join(f"{s['workspace']} by {s['by']}" for s in found)
                           + "): choose one with --workspace ID, or name the main results with "
                             "--main", "ambiguous", [s["workspace"] for s in found])
    (s,) = found
    return {**s, "problems": wsp.main_results_problems(s, Snapshot(site.data), root)}


def _proof_facts(root: Path, target: str, log) -> dict:
    """The facts inside `target`'s proof, or the reason there are none, as a refusal. `target`
    is a declaration name, optionally `Module:Name` when several modules declare the name."""
    from .proof_facts import extract
    from .simple import ViewError
    module, _, name = target.rpartition(":") if ":" in target else (None, "", target)
    try:
        doc = extract(root, name, module or None, log=log)
    except ViewError as e:
        raise CompareError(str(e), "no-project") from None
    if not doc["ok"]:
        raise CompareError(f"{name}: {doc['status']}" + (f" ({', '.join(doc['modules'])})"
                                                         if doc.get("modules") else "")
                           + (f": {doc['reason']}" if doc.get("reason") else ""),
                           doc["status"].replace(" ", "-"), doc.get("modules") or [])
    return doc


# -- text --------------------------------------------------------------------------------------

def passage_text(p: dict) -> str:
    """A passage for the terminal, with its source."""
    src = p.get("source") or {}
    where = ", ".join(x for x in (
        f"{src['file']}:{src['line']}" if src.get("file") and src.get("line") else src.get("file"),
        f"page {src['page']}" if src.get("page") else None) if x)
    head = (p.get("number") or p["claim"]) + (f" ({p['heading']})" if p.get("heading") else "")
    head += f"  [{p['claim']}]"
    if not p.get("available"):
        return f"{head}\nUNAVAILABLE: {p['reason']}" + (f" ({where})" if where else "")
    how = p["quality"] + (", approximate position" if src.get("position") == "approximate"
                          else "")
    body = f"{head}\n{p['text']}\n  ({how}" + (f"; {where}" if where else "") + ")"
    if not p.get("complete"):
        body += f"\n  INCOMPLETE: {p['reason']}"
    for k, part in enumerate(p.get("parts") or [], start=1):
        if k == 1:
            continue
        what = f"the definition of {part['macro']}" if part.get("macro") else "also pinned"
        body += (f"\n-- part {k} of its pin, {what} ({part['file']}:{part['start_line']}"
                 f"-{part['end_line']}):\n{part['text']}")
    if p.get("step"):
        par = p["step"].get("parent") or {}
        body = (f"A step of the proof of {par.get('number') or par.get('id') or 'its result'}"
                f" ({par.get('id') or 'no parent recorded'}). {p['step']['question']}\n" + body)
        if p.get("context"):
            body += "\nIts context in the proof:\n" + p["context"]
    return body


def search_text(out: dict) -> str:
    """A content search for the terminal: each result with its reasons and complete statement."""
    sub = out.get("subject") or {}
    head = (f"Declarations ({sub.get('kinds')}) matching {sub['claim']}" if sub.get("claim")
            else f"Declarations matching {sub.get('text')!r}")
    lines = [f"{head}, among {out['scope']['declarations']} declarations of the project:"]
    if out["scope"].get("note"):
        lines.append(f"({out['scope']['note']})")
    for r in out["results"]:
        lines.append(f"\n{r['name']}  ({r.get('kind')}, {r.get('module')})")
        for x in r["reasons"]:
            lines.append(f"  - {x['text']}")
        lines.append(f"  {r['statement']}")
    if not out["results"]:
        lines.append("(nothing in the project shares a term with it)")
    if out["retrieval"]["next"]:
        lines.append(f"\n(more: --after {out['retrieval']['next']})")
    return "\n".join(lines)


def statement_lines(d: dict) -> list[str]:
    """A declaration for the terminal: its binders and conclusion, then its exact text. An
    `inspect` answer (the result of the `dependencies` query) is shown by
    `dependencies_lines`."""
    if d.get("schema"):
        from .deps import SCHEMA as INSPECT_SCHEMA
        if d["schema"] == INSPECT_SCHEMA:
            return dependencies_lines(d)
    st = d.get("statement")
    name = d.get("name")
    if st is None:
        if d.get("signature"):
            out = [f"{name}  ({d.get('kind')})", f"  type : {d['signature']}"]
            if d.get("value"):
                out.append(f"  value: {d['value']}")
            return out
        return [f"{name}: {d.get('unavailable') or 'no statement in this build'}"]
    lines = [name]
    for b in st["binders"]:
        role = {"forall": "for all", "exists": "there is", "hypothesis": "assume",
                "instance": "instance"}.get(b.get("role"), b.get("role"))
        lines.append(f"  {role:9} {b.get('name')} : {_text(b.get('type'))}")
    lines.append(f"  {'then' if st['binders'] else '':9} {_text(st.get('conclusion'))}")
    if st.get("text"):
        lines.append(f"  exact: {st['text']}")
    if d.get("witness"):
        lines.append(f"\nWitness: {d['witness']}")
    return lines


def dependencies_lines(doc: dict) -> list[str]:
    """An `inspect` answer for the terminal, naming everything its JSON names: the
    declaration's statement and Lean's checks, the project declarations its statement and its
    proof (or body) use, the constants outside the project they use, and every project
    declaration they reach (the packages outside it are summed up, as `inspect` does). A
    declaration Lean did not find is shown with Lean's answer and its reason."""
    name = doc.get("name")
    if not doc.get("ok"):
        where = ", ".join(doc.get("modules") or [])
        out = [f"{name}: {doc.get('status')}" + (f" ({where})" if where else "")
               + (f": {doc['reason']}" if doc.get("reason") else "")]
        if doc.get("status") == "ambiguous":
            out.append(f"  name its module with `machinechecked inspect {name} --module MODULE`")
        return out
    d = doc["declaration"]
    vk = doc.get("value_kind") or "none"
    line = (d.get("range") or {}).get("line")
    out = [f"{d['name']}  ({d['kind']}, {d['file']}" + (f":{line}" if line else "") + ")",
           f"  statement: {d['statement']}",
           f"  axioms: {', '.join(d.get('axioms') or []) or 'none'}"
           + ("  (uses sorry)" if d.get("sorry") else "")]
    ext = doc.get("external_dependencies") or {}
    out.append(f"  statement uses (this project): "
               f"{', '.join(doc.get('statement_dependencies') or []) or 'nothing'}")
    if vk == "none":
        out.append("  it has no proof or body")
    else:
        out.append(f"  {vk} uses (this project): "
                   f"{', '.join(doc.get('proof_dependencies') or []) or 'nothing'}")
    out.append(f"  statement uses (outside this project): "
               f"{', '.join(ext.get('statement') or []) or 'nothing'}")
    if vk != "none":
        out.append(f"  {vk} uses (outside this project): "
                   f"{', '.join(ext.get('proof') or []) or 'nothing'}")
    c = doc.get("closure") or {}
    outside = c.get("external") or {}
    packages = list((outside.get("by_package") or {}).items())
    by = ", ".join(f"{k} {v}" for k, v in packages[:5]) + (", …" if len(packages) > 5 else "")
    out.append(f"  reaches {c.get('declarations', 0)} declaration(s) of this project (deepest "
               f"{c.get('deepest', 0)} step(s)), and {outside.get('constants', 0)} constant(s) "
               "outside it" + (f": {by}" if by else ""))
    for m in c.get("members") or []:
        out.append(f"    {m['depth']:>3}  {m['name']}  ({m['kind']}, {m['module']})")
    if c.get("generated"):
        out.append(f"  ({c['generated']} constant(s) Lean generated were followed, not listed)")
    if doc.get("note"):
        out.append(f"  {doc['note']}")
    if (doc.get("cache") or {}).get("hit"):
        out.append("  (from the cache: no Lean input changed)")
    return out


def proof_facts_text(q: dict) -> str:
    """A `proof-facts` answer for the terminal: the exported statement, then each fact with
    what it needs, the cases it lies in and where the source states it."""
    sub = q.get("subject") or {}
    d = sub.get("declaration") or {}
    line = (d.get("range") or {}).get("line")
    out = [f"{d.get('name')}  ({d.get('kind')}, {d.get('file')}" + (f":{line}" if line else "")
           + f"; {d.get('basis')})", f"  statement: {_text(d.get('statement'))}"]
    m = q.get("match")
    total = q["retrieval"]["total"]
    out.append(f"  {total} fact(s) inside its proof" + (f" share symbols with {m['query']!r} "
               f"(of {m['of']})" if m else "") + ", each established inside this proof under "
               "its context:")
    locals_ = {l["id"]: l for l in sub.get("locals") or []}
    for f in q["results"]:
        src = f.get("source") or {}
        where = f"{src.get('file')}:{src.get('line')}" if src.get("line") else ""
        if src.get("located") == "the declaration only":
            where += " (the declaration; this fact's line is not known)"
        label = f.get("name") if f["kind"] != "application" else f.get("head")
        out.append(f"  {f['id']:4} {f['what']}: " + (f"{label} : " if label else "")
                   + _text(f.get("type")) + (f"   [{where}]" if where else ""))
        hyps = [a for a in f.get("assumptions") or [] if a.get("role") == "hypothesis"]
        if hyps:
            out.append("         assuming " + "; ".join(f"{a['name']} : {a['type']}"
                                                         for a in hyps))
        for c in f.get("cases") or []:
            out.append(f"         {c}")
        for p in f.get("premises") or []:
            by = locals_.get(p.get("supplied_by") or "")
            out.append(f"         needs {p['name']} : {_text(p.get('type'))}"
                       + (f", supplied by {by['name']}" if by else ", supplied by a proof term"))
        if f.get("used_by"):
            out.append("         used by " + ", ".join(f["used_by"]))
        if f.get("match"):
            out.append("         shares " + " ".join(f["match"]["shared"]))
    for o in sub.get("source_only") or []:
        out.append(f"  source only, line {o['source']['line']}: {o['text']}  ({o['note']})")
    proof = sub.get("proof") or {}
    if not proof.get("complete", True):
        out.append("  INCOMPLETE: " + "; ".join(proof.get("cut") or []))
    if proof.get("auxiliary"):
        out.append("  not entered: " + ", ".join(proof["auxiliary"])
                   + " (lemmas Lean generated for parts of the proof; ask about each by name)")
    if q["retrieval"].get("next"):
        out.append(f"  (more: --after {q['retrieval']['next']})")
    out.append(f"  {sub.get('note')}")
    if (sub.get("cache") or {}).get("hit"):
        out.append("  (from the cache: no Lean input changed)")
    return "\n".join(out)


def packet_text(pk: dict) -> str:
    """A packet for the terminal."""
    out = [passage_text(p) for p in pk["paper"]["passages"]]
    rd = (pk.get("interpretations") or {}).get("requirements")
    if rd:
        from .requirements import lines
        head = f"Requirements recorded in workspace {rd.get('workspace')} by {rd.get('reviewer')}"
        out.append("\n".join([head] + lines(rd)))
    comps = (pk.get("interpretations") or {}).get("compositions") or []
    if comps:
        from .composition import lines as composition_lines
        out.append("\n".join(["Compositions recorded in that workspace"]
                              + [x for c in comps for x in composition_lines(c)]))
    if pk["paper"].get("note"):
        out.insert(0, pk["paper"]["note"])
    lean = pk.get("lean")
    if lean is not None:
        for d in lean["declarations"]:
            head = {"establishes the step": "Lean linked as establishing this step:\n",
                    "formal route used instead": "The different formal route used instead "
                    "(it does not state the step):\n"}.get(d.get("role"), "")
            out.append(head + "\n".join(statement_lines(d)))
        for d in lean.get("candidates") or []:
            out.append("candidate (not confirmed): " + "\n".join(statement_lines(d)))
        for d in lean["definitions"]:
            if d.get("available") is False:
                out.append(f"{d['name']}: ({d['reason']})")
            elif not d.get("generated_for"):
                out.append("\n".join(statement_lines(d)))
        if not lean["declarations"]:
            out.append("No Lean is linked to this step: assess the printed step itself."
                       if pk.get("note", "").startswith("no Lean is linked to this step")
                       else "(this build holds no statement for it)")
    for w in pk["retrieval"]["withheld"]:
        out.append(f"(not shown at this stage: {w['section']}; {w['reason']})")
    return "\n\n".join(out)
