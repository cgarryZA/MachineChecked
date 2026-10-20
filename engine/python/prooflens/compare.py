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
links, statuses and the assessment's findings. Independent review uses `read` before its
reading is locked and `compare` before its verdict; any other use is an informed investigation.

What a build does not hold is said, not implied: a section the stage withholds is listed in
`retrieval.withheld`, content not extracted yet in `retrieval.unavailable` (with the issue that
owns it), and a list cut by `limit` gives the cursor that continues it. Passages and linked
statements are never cut.
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
    {"what": "uses of the declarations and the source of each premise", "owner": "#144"},
    {"what": "typed facts inside proofs", "owner": "#145"},
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

    def queue(self) -> dict | None:
        p = self.data / "review-queue.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def lean_index(self) -> list[dict]:
        p = self.data / "lean-index.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        except ValueError:
            return []


# -- the paper ---------------------------------------------------------------------------------

def passage(ch: dict, stage: str) -> dict:
    """A claim's printed passage, complete, with where it is and how it was obtained. A passage
    the build does not hold is `available: false`, with its source reference."""
    anchor = ch.get("anchor") or {}
    approx = anchor.get("kind") in ("approximate", "pdf")
    text = ch.get("statement_tex")
    quality = "LaTeX source"
    if not text and anchor.get("statement"):
        text, quality = anchor["statement"], "text extracted from the PDF"
    elif text and approx:
        quality = "text extracted from the PDF"
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
    if not text:
        return {**out, "available": False, "text": None,
                "reason": "the build holds no printed text for this claim; read it in the paper "
                          "at the source given"}
    complete = not (quality.startswith("text extracted") and len(text) >= PDF_TEXT_CHARS)
    removed = []
    if stage == "read" and LEAN_TAGS.search(text):
        text = re.sub(r"[ \t]{2,}", " ", LEAN_TAGS.sub("", text)).strip()
        removed.append("the paper's \\lean{...} tags, which name Lean declarations")
    out.update(available=True, text=text, quality=quality, complete=complete)
    if not complete:
        out["reason"] = (f"the PDF extraction keeps the first {PDF_TEXT_CHARS} characters of a "
                         "statement; read the rest in the paper at the source given")
    if removed:
        out["removed"] = removed
    return out


# -- the Lean ----------------------------------------------------------------------------------

def _statement(st: dict | None) -> dict | None:
    """A statement in full: its exact text, and its binders and conclusion with their
    expression identifiers."""
    if not st:
        return None
    exact = st.get("exact")
    return {"text": _text(exact) if exact else None, "exact": exact,
            "binders": [{k: b.get(k) for k in ("id", "name", "role", "binder", "supplies", "type")
                         if b.get(k) is not None} for b in st.get("binders") or []],
            "conclusion": st.get("conclusion"), "closure": list(st.get("closure") or []),
            "fingerprint": st.get("fingerprint")}


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
                                   if m != n and _generated(n, m)), None)
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
                    "symbol links and statuses are shown after the verdict"})
    return out


def _head(site: Site, stage: str, request: dict) -> dict:
    if stage not in STAGES:
        raise CompareError(f"stage {stage!r} is not one of {', '.join(STAGES)}", "bad-stage")
    return {"schema": PACKET_SCHEMA, "request": request, "snapshot": site.snapshot(),
            "stage": stage, "contains": CONTAINS[stage]}


def _claim_ref(ch: dict) -> dict:
    return {k: ch.get(k) for k in ("id", "key", "paper", "number", "kind", "heading")
            if ch.get(k) is not None}


def _retrieval(stage: str, sections: list[str], page: dict | None, extra: list | None = None):
    return {"included": sections, "withheld": _withheld(stage),
            "unavailable": ([] if stage == "read" else NOT_EXTRACTED) + (extra or []),
            "definitions": page}


def claim_packet(site: Site, claim: str, stage: str = "informed", limit: int | None = None,
                 after: str | None = None) -> dict:
    """The comparison packet of one claim: its passage, its linked declarations (and, from
    the compare stage, unconfirmed suggestions as candidates) and the definitions they use."""
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
        out["lean"] = {"declarations": decls, "candidates": cands, "definitions": defs}
        sections.append("lean")
        if not decls:
            out["lean"]["note"] = ("no Lean is linked to this step: review the printed step "
                                   "itself" if ch.get("step") else
                                   "no declaration is linked to this claim")
    if stage == "informed":
        out["interpretations"] = _informed(ch)
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
                names = sorted(m for m in site.store() if _generated(m, rec["name"]))
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
    # The build's index of every project declaration holds a preview of each type: a match
    # there is a candidate whose full statement `dependencies` (or `inspect`) gives.
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
    "dependencies": "what a declaration's statement and proof use (runs `inspect`)",
    "uses": "where a declaration is applied, and the source of each premise",
    "proof-facts": "a typed fact inside a selected proof",
    "composition": "a multi-result argument and the identifications it needs",
    "impact": "which main result uses a declaration",
}
NOT_YET = {"uses": "#144", "proof-facts": "#145", "composition": "#147", "impact": "#112"}


def query(site: Site, op: str, target: str, limit: int | None = None, after: str | None = None,
          root: Path | None = None, log=None) -> dict:
    """One targeted query: `{op, context, target, results, provenance, retrieval}`. An
    operation the engine does not extract yet answers `available: false` with its owner."""
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
        names = [target] + sorted(m for m in store if _generated(m, target))
        results = _definitions(site, [], names, "compare")
        prov = "the build's declaration records"
    elif op == "mentions":
        results = _mentions(site, target)
        prov = "the statements of the build, and its index of the project"
    else:
        if root is None:
            raise CompareError("`dependencies` needs the Lean project", "no-project")
        from .deps import inspect
        res = inspect(root, target, None, log=log)
        results = [res]
        prov = "Lean (inspect), cached until a Lean input changes"
    part, page = _page(results, limit, after)
    return {**out, "available": True, "results": part, "provenance": prov, "retrieval": page}


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
    if p.get("step"):
        par = p["step"].get("parent") or {}
        body = (f"A step of the proof of {par.get('number') or par.get('id') or 'its result'}"
                f" ({par.get('id') or 'no parent recorded'}). {p['step']['question']}\n" + body)
        if p.get("context"):
            body += "\nIts context in the proof:\n" + p["context"]
    return body


def statement_lines(d: dict) -> list[str]:
    """A declaration for the terminal: its binders and conclusion, then its exact text."""
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


def packet_text(pk: dict) -> str:
    """A packet for the terminal."""
    out = [passage_text(p) for p in pk["paper"]["passages"]]
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
