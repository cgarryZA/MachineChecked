"""What changed between two releases of the full assessment, and which evidence that reopens.

A release is a stored evidence record (`evidence.py`). The comparison reads two of them and
reports, claim by claim:

- the paper: whether the claim's passage is unchanged, moved, changed, changed only in its
  context (a further passage of its pin, or the definition of a notation macro it uses), removed
  or new, from the digests each build recorded; a removed claim whose text another claim now has
  is offered as a match, never applied;
- the Lean: for each clause, whether its proposition, each project definition in its closure and
  each of its proofs changed, with the statement text of both builds;
- the evidence: for each review the assessment counted in the earlier build, whether the later
  build still counts it, and if not, the exact dependency that changed and the question a new
  reading must answer;
- each build's status, side by side.

Nothing here assesses: every state is the one `assess.py` recorded in that build. A change can
only reopen evidence; a review is never carried to another declaration or another claim.
"""

from __future__ import annotations

from .assess import match_anchor

SCHEMA = "prooflens/changes@1"
TEXT_CHARS = 4000

# Paper-side classes of a claim, in the order the report lists them.
CLASSES = ("changed", "context-changed", "removed", "ambiguous", "new", "unknown", "moved",
           "unchanged")
# What became of a piece of evidence.
OUTCOMES = ("reopened", "dropped", "replaced", "newly-current", "kept", "open")
CURRENT = ("reviewed", "author-reviewed")


def _cut(text: str | None) -> dict | None:
    if text is None:
        return None
    out = {"text": text[:TEXT_CHARS]}
    if len(text) > TEXT_CHARS:
        out["truncated"] = True
    return out


class Version:
    """One release's evidence, read for the comparison."""

    def __init__(self, record: dict, release: str):
        self.id, self.release = record["id"], release
        self.created = record.get("created")
        body = record["body"]
        self.body = body
        self.claims = {c["id"]: c for c in body["inventory"]["claims"]}
        self.assessed = {c["id"]: c for c in body["assessment"]["claims"]}
        self.lean = body.get("lean") or {}
        self.tex = body.get("tex") or {}

    def identity(self) -> dict:
        prov = self.body["provenance"]
        project = prov.get("project") or {}
        return {"release": self.release, "evidence": self.id, "created": self.created,
                "project": {k: project.get(k) for k in ("commit", "dirty")},
                "lean_inputs_sha256": prov.get("lean_inputs_sha256"),
                "lean": (prov.get("lean") or {}).get("lean"),
                "papers": {pid: {k: p.get(k) for k in ("revision", "mode", "pdf_sha256",
                                                        "paper_version", "published")
                                 if p.get(k) is not None}
                           for pid, p in (prov.get("papers") or {}).items()}}

    # -- the paper --------------------------------------------------------------------------

    def passage(self, cid: str) -> dict | None:
        """What this build recorded of the claim's passage: its place, the digest of its text
        as found (`sha256`), of its own passage alone (`passage`), its further passages and
        notation, and its pin in the inventory. None for a claim this build has not."""
        c = self.claims.get(cid)
        if c is None:
            return None
        t = self.tex.get(c["paper"]) or {}
        out = {"location": c.get("location"), "pin": c.get("source_sha256"),
               "pin_scheme": c.get("source_hash_scheme"),
               "pin_lines": c.get("source_line_sha256"),
               "pin_parts": [{"location": q.get("location"), "sha256": q.get("sha256"),
                              **({"macro": q["macro"]} if q.get("macro") else {})}
                             for q in c.get("source_parts") or []],
               "sha256": None}
        region = (t.get("regions") or {}).get(cid)
        if region and not region.get("error"):
            out.update(sha256=region.get("sha256"),
                       passage=region.get("passage_sha256") or region.get("sha256"),
                       bounds={k: region.get(k) for k in ("file", "start_line", "end_line",
                                                          "start_column", "end_column")},
                       parts=[{"location": f"{p.get('file')}:{p.get('start_line')}",
                               "sha256": p.get("sha256"),
                               **({"macro": p["macro"]} if p.get("macro") else {})}
                              for p in region.get("parts") or []],
                       notation=[{"macro": m.get("macro"), "sha256": m.get("sha256")}
                                 for m in region.get("notation") or []])
        elif region and region.get("error"):
            out["error"] = region["error"]
        elif t.get("mode") == "latex":
            a = match_anchor(c, t.get("anchors") or [])
            if a and a.get("source_sha256"):
                out.update(sha256=a["source_sha256"], passage=a["source_sha256"],
                           bounds={"file": a.get("file"), "start_line": a.get("line")},
                           parts=[], notation=[])
                if a.get("statement"):
                    out["text"] = _cut(a["statement"])
        elif t.get("mode"):
            out["error"] = "the paper is read from its PDF: no source digest to compare"
        parts = (t.get("part_text") or {}).get(cid)
        if parts:
            out["part_text"] = [{"location": f"{p.get('file')}:{p.get('start_line')}",
                                 **({"macro": p["macro"]} if p.get("macro") else {}),
                                 **(_cut(p.get("text")) or {})} for p in parts]
        out["matches_pin"] = bool(out["sha256"] and out["sha256"] == out["pin"])
        return out

    # -- the Lean ---------------------------------------------------------------------------

    def decl(self, name: str | None) -> dict | None:
        """A declaration as this build found it: its fingerprints, the digest of its authored
        source (which covers a theorem's proof), and its statement text. None when the probe
        found no declaration under the name."""
        if not name:
            return None
        spec = (self.lean.get("specs") or {}).get(name)
        rec = (self.lean.get("decls") or {}).get(name)
        found = [r for r in (spec, rec) if r and r.get("fingerprint")]
        if not found:
            return None
        src = (rec or {}).get("lean_source") or {}
        return {"fingerprint": found[0]["fingerprint"],
                "legacy_hash": found[0].get("legacy_hash"),
                "source_sha256": src.get("sha256"),
                "kind": (rec or {}).get("kind") or ("proposition" if spec else None),
                **(_cut(statement_text(name, spec, rec)) or {})}

    def closure(self, cl: dict) -> list[str]:
        """The project definitions a clause's meaning depends on: its proposition's closure, or
        a definition claim's definitions and their closures."""
        specs, defs = self.lean.get("specs") or {}, self.lean.get("defs") or {}
        if cl.get("spec"):
            names = (specs.get(cl["spec"]) or {}).get("closure") or []
        else:
            names = list(cl.get("defs") or [])
            for d in cl.get("defs") or []:
                names += (defs.get(d) or {}).get("closure") or []
        return [n for n in dict.fromkeys(names) if n not in specs]


def statement_text(name: str, spec: dict | None, rec: dict | None) -> str | None:
    """The statement of a declaration as the probe printed it: a proposition's exact statement;
    a definition's type and its equations (or its value); a theorem's type."""
    if spec and (spec.get("exact") or {}).get("text"):
        return spec["exact"]["text"]
    if not rec:
        return None
    sig = (rec.get("signature") or {}).get("text")
    head = f"{name} : {sig}" if sig else name
    if rec.get("equations"):
        return "\n".join([head] + [(e.get("statement") or {}).get("text", "")
                                   for e in rec["equations"]])
    if rec.get("kind") == "def" and (rec.get("value") or {}).get("text"):
        return f"{head} :=\n{rec['value']['text']}"
    return head


def decl_change(old: dict | None, new: dict | None) -> str:
    """How a declaration changed between two builds: `unchanged`, `statement` (its fingerprint,
    which erases proofs, changed), `proof` (the same statement, another authored source),
    `removed`, `new` or `absent`."""
    if old is None and new is None:
        return "absent"
    if old is None:
        return "new"
    if new is None:
        return "removed"
    if old["fingerprint"] != new["fingerprint"]:
        return "statement"
    if old.get("source_sha256") and new.get("source_sha256") and \
            old["source_sha256"] != new["source_sha256"]:
        return "proof"
    return "unchanged"


def _decl_entry(name: str, old: Version, new: Version) -> dict:
    """A declaration's change, with both builds' records when it changed (the fingerprint alone
    when it did not)."""
    a, b = old.decl(name), new.decl(name)
    change = decl_change(a, b)
    if change == "unchanged":
        return {"name": name, "change": change, "fingerprint": b["fingerprint"]}
    return {"name": name, "change": change, "from": a, "to": b}


# -- the paper side ------------------------------------------------------------------------------

def _parts_changes(a: dict, b: dict) -> list[dict]:
    """The further passages and notation definitions of a pin that differ between two builds."""
    out = []
    pa, pb = a.get("parts") or [], b.get("parts") or []
    if len(pa) == len(pb):
        for i, (x, y) in enumerate(zip(pa, pb)):
            if x.get("sha256") != y.get("sha256"):
                out.append({"what": "macro definition" if x.get("macro") else "passage",
                            "part": i + 1, "from": x, "to": y, "change": "changed"})
    else:
        shas = {p.get("sha256") for p in pb}
        out += [{"what": "passage", "from": x, "to": None, "change": "removed"}
                for x in pa if x.get("sha256") not in shas]
        shas = {p.get("sha256") for p in pa}
        out += [{"what": "passage", "from": None, "to": y, "change": "added"}
                for y in pb if y.get("sha256") not in shas]
    na = {m["macro"]: m for m in a.get("notation") or []}
    nb = {m["macro"]: m for m in b.get("notation") or []}
    for m in sorted(set(na) | set(nb)):
        if (na.get(m) or {}).get("sha256") != (nb.get(m) or {}).get("sha256"):
            out.append({"what": "notation", "macro": m, "from": na.get(m), "to": nb.get(m),
                        "change": "changed" if m in na and m in nb else
                        "removed" if m in na else "added"})
    return out


def pin_change(a: dict | None, b: dict | None) -> dict | None:
    """How the inventory's pin of a claim changed between two builds (a passage read again and
    pinned): whether its own passage's pin changed, and which further passages' pins did."""
    if not a or not b or a.get("pin") == b.get("pin"):
        return None
    parts = _parts_changes({"parts": a.get("pin_parts")}, {"parts": b.get("pin_parts")})
    own = a.get("pin_lines") != b.get("pin_lines") or not (a.get("pin_parts")
                                                           or b.get("pin_parts"))
    return {"from": a.get("pin"), "to": b.get("pin"), "passage": own, "context": parts}


def paper_class(a: dict | None, b: dict | None) -> tuple[str, str, list[dict]]:
    """The class of a claim's passage between two builds, why, and the context changes."""
    if a is None:
        return "new", "the claim is not in the earlier inventory", []
    if b is None:
        return "removed", "the claim is not in the later inventory", []
    if not a.get("sha256") or not b.get("sha256"):
        which = "earlier" if not a.get("sha256") else "later"
        why = (a if which == "earlier" else b).get("error") or "its passage was not located"
        return "unknown", f"the {which} build has no digest of its passage: {why}", []
    if a.get("passage") != b.get("passage"):
        return "changed", "the text of its passage changed", _parts_changes(a, b)
    ctx = _parts_changes(a, b)
    if ctx or a["sha256"] != b["sha256"]:
        return ("context-changed", "its own passage is unchanged; the context its pin covers "
                "changed", ctx)
    if a.get("bounds") != b.get("bounds") or a.get("location") != b.get("location"):
        return "moved", "the same text at another place", []
    return "unchanged", "the same text at the same place", []


# -- the evidence --------------------------------------------------------------------------------

def _marker(r: dict | None) -> dict | None:
    """The review marker a review state counted, if any."""
    if not r or r.get("state") not in CURRENT or not r.get("current"):
        return None
    m = r["current"][0]
    return {k: m.get(k) for k in ("by", "kind", "provenance", "file", "line", "hash", "source")}


def _same_marker(x: dict, y: dict) -> bool:
    return all(x.get(k) == y.get(k) for k in ("by", "file", "hash", "source"))


def _reads(e: dict, cid: str) -> bool:
    """Whether the review of an evidence entry may have read the claim's passage: a step's own
    review, a marker that records a digest of it, or one that records no digests."""
    if e["target"] == "step":
        return True
    m = e["to"].get("marker")
    src = ((e["from"].get("marker") if m == "same" else m) or {}).get("source")
    return src is None or cid in src


def _label(v: Version, cid: str | None) -> str:
    c = v.claims.get(cid or "")
    if c is None:
        return cid or "its claim"
    return f"{c['number']} ({cid})" if c.get("number") else cid


WHY = {
    "source-unread": "its last review did not read this claim's passage",
    "source-unrecorded": "its last review was made before source pins were recorded, and the "
                         "history cannot show the passage unchanged since",
    "source-notation-unrecorded": "its last review did not record the definitions of the "
                                  "notation macros the passage uses",
    "no-reading": "its review marker records no reading (no review text precedes it)",
}


def _because(target: str, name: str, old_r: dict, new_r: dict, cid: str, old: Version,
             new: Version, paper: dict[str, dict], defines: bool = False
             ) -> tuple[list[dict], str]:
    """The dependency that stops a review counting in the later build, and the question a new
    reading answers. `defines`: the claim is a definition the declaration states."""
    what = "state" if target == "spec" else "define" if defines else "match"
    label = _label(new, cid)
    why = new_r.get("why") or ("declaration" if new_r.get("state") == "stale" else None)
    marker = _marker(old_r) or {}
    if new_r.get("state") == "pending" and not new_r.get("stale"):
        return ([{"dependency": "review", "detail": "the later build has no review of it"}],
                f"Read {label} against {name}: no review is recorded.")
    if why == "declaration":
        b = new.decl(name)
        dep = {"dependency": "lean", "name": name, "was": marker.get("hash"),
               "now": (b or {}).get("fingerprint"), "from": old.decl(name), "to": b}
        if b is None:
            dep["detail"] = "the later build has no declaration under this name"
            return [dep], (f"{name} is not in the later build: which declaration, if any, "
                           f"now {what}s {label}? A review is not moved to another declaration.")
        if target == "spec":
            return [dep], (f"Does {name} still state {label} as the paper prints it, now that "
                           "its statement has changed?")
        if defines:
            return [dep], (f"Does {name} still define what {label} prints, now that its "
                           "definition has changed?")
        return [dep], (f"Does {name} still mean what {label} needs, now that its definition "
                       "has changed?")
    if why == "source-changed":
        sc = new_r.get("source_claim") or cid
        dep = {"dependency": "paper", "claim": sc,
               "was": (marker.get("source") or {}).get(sc),
               "now": (new_r.get("source_sha256") or {}).get(sc), **_paper_dependency(paper, sc)}
        where = _context_words(dep)
        if where:
            return [dep], (f"Does {name} still {what} {_label(new, sc)} under its changed "
                           f"context ({where})?")
        return [dep], f"Does {name} still {what} the changed text of {_label(new, sc)}?"
    if why == "source-unpinned":
        # The later build's manuscript no longer matches the claim's pin: the reading is unread
        # until the passage is pinned again and read at the new pin.
        sc = new_r.get("source_claim") or cid
        later = (paper.get(sc) or {}).get("to")
        dep = {"dependency": "paper", "claim": sc,
               "was": (marker.get("source") or {}).get(sc),
               "now": later.get("sha256") if isinstance(later, dict) else None,
               "detail": "the manuscript no longer matches the claim's pin",
               **_paper_dependency(paper, sc)}
        return [dep], (f"Pin {_label(new, sc)} again at the text the paper now prints, then: "
                       f"does {name} still {what} it?")
    detail = WHY.get(why, "its last review is not current")
    sc = new_r.get("source_claim")
    return ([{"dependency": "record", "reason": why, "claim": sc, "detail": detail}],
            f"Read {_label(new, sc or cid)} against {name} again: {detail}.")


def _paper_dependency(paper: dict[str, dict], cid: str) -> dict:
    """What changed of a claim's passage, for a review that read it: the change between the
    two builds' texts, or, when the passage was pinned again between them, the change of its
    pin. `context` lists further passages or notation that changed while its own passage did
    not."""
    p = paper.get(cid) or {}
    rp = p.get("repinned")
    if p.get("class") in ("changed", "context-changed") or not rp:
        return {"change": p.get("class"),
                "context": (p.get("context") or []) if p.get("class") == "context-changed"
                else []}
    return {"change": "repinned" if rp["passage"] or not rp["context"] else
            "context-repinned", "context": [] if rp["passage"] else rp["context"]}


def _context_words(dep: dict) -> str:
    return ", ".join(c.get("macro") or ((c.get("to") or c.get("from") or {}).get("location")
                                        or "") for c in dep.get("context") or [])


def review_outcome(target: str, name: str, old_r: dict | None, new_r: dict | None, cid: str,
                   old: Version, new: Version, paper: dict[str, dict],
                   defines: bool = False) -> dict:
    """What became of the review of `name` (a `spec` or a `def`) for claim `cid` between two
    builds, from the states each build's assessment recorded."""
    a, b = _marker(old_r), _marker(new_r)
    out = {"target": target, "name": name,
           "from": {"state": (old_r or {}).get("state"), "marker": a},
           "to": {"state": (new_r or {}).get("state"), "marker": b}}
    if a and new_r is None:
        out["outcome"] = "dropped"
        out["because"] = [{"dependency": "lean", "name": name, "detail": (
            "the later build no longer depends on it for this claim")}]
    elif a and b:
        out["outcome"] = "kept" if _same_marker(a, b) else "replaced"
        if out["outcome"] == "kept":
            # One marker, counted by both builds.
            out["to"]["marker"] = "same"
    elif a:
        out["outcome"] = "reopened"
        out["because"], out["question"] = _because(target, name, old_r, new_r, cid, old, new,
                                                   paper, defines)
    elif b:
        out["outcome"] = "newly-current"
    else:
        out["outcome"] = "open"
    return out


def _clauses(v: Version, cid: str) -> dict[str, dict]:
    return {cl["name"]: cl for cl in (v.assessed.get(cid) or {}).get("clauses") or []}


def clause_changes(cid: str, old: Version, new: Version, paper: dict[str, dict]
                   ) -> tuple[list[dict], list[dict]]:
    """For each clause of the claim in either build: the Lean changes, and the outcome of each
    of its reviews."""
    ca, cb = _clauses(old, cid), _clauses(new, cid)
    lean, evidence = [], []
    for name in list(dict.fromkeys(list(ca) + list(cb))):
        x, y = ca.get(name), cb.get(name)
        row = {"clause": name, "in": "both" if x and y else "earlier" if x else "later"}
        spec_a, spec_b = (x or {}).get("spec"), (y or {}).get("spec")
        if spec_a or spec_b:
            if spec_a == spec_b:
                row["proposition"] = _decl_entry(spec_a, old, new)
            else:
                row["proposition"] = {"name": spec_b, "renamed_from": spec_a,
                                      "change": "renamed", "from": old.decl(spec_a),
                                      "to": new.decl(spec_b)}
        defs_a = old.closure(x) if x else []
        defs_b = new.closure(y) if y else []
        defs = [_decl_entry(d, old, new) for d in dict.fromkeys(defs_a + defs_b)]
        row["definitions"] = [d for d in defs if d["change"] != "unchanged"]
        row["definitions_unchanged"] = sum(d["change"] == "unchanged" for d in defs)
        proofs = []
        for kind in ("accept", "refute", "witness"):
            pa, pb = (x or {}).get(kind), (y or {}).get(kind)
            if not (pa or pb):
                continue
            e = _decl_entry(pb or pa, old, new) if pa == pb else {
                "name": pb, "renamed_from": pa, "change": "renamed", "from": old.decl(pa),
                "to": new.decl(pb)}
            e["role"] = kind
            e["check"] = {"from": (x or {}).get(kind + "_ok"), "to": (y or {}).get(kind + "_ok")}
            proofs.append(e)
        row["proofs"] = proofs
        lean.append(row)
        reviews = []
        if spec_a == spec_b and spec_a:
            reviews.append(("spec", spec_a, (x or {}).get("spec_review"),
                            (y or {}).get("spec_review") if y else None))
        else:
            if spec_a:
                reviews.append(("spec", spec_a, (x or {}).get("spec_review"), None))
            if spec_b:
                reviews.append(("spec", spec_b, None, (y or {}).get("spec_review")))
        da, db = (x or {}).get("def_reviews") or {}, (y or {}).get("def_reviews") or {}
        for d in dict.fromkeys(list(da) + list(db)):
            reviews.append(("def", d, da.get(d), db.get(d)))
        named = set((x or {}).get("defs") or []) | set((y or {}).get("defs") or [])
        for target, n, ra, rb in reviews:
            e = review_outcome(target, n, ra, rb, cid, old, new, paper,
                               target == "def" and n in named)
            e["clause"] = name
            # A review that stands although something else of its clause changed: say what it
            # does not depend on (a proof is never read by a review of a statement).
            if e["outcome"] == "kept":
                through = [f"the proof {p['name']} ({p['role']})" for p in proofs
                           if p["change"] == "proof"]
                if through:
                    e["kept_through"] = through
            evidence.append(e)
    return lean, evidence


def step_outcome(cid: str, old: Version, new: Version, paper: dict[str, dict]) -> dict | None:
    """What became of a proof step's own review."""
    ra = (old.assessed.get(cid) or {}).get("step_review")
    rb = (new.assessed.get(cid) or {}).get("step_review")
    if not ra and not rb:
        return None
    fa, fb = (ra or {}).get("finding"), (rb or {}).get("finding")
    out = {"target": "step", "name": cid, "from": {"state": (ra or {}).get("state")},
           "to": {"state": (rb or {}).get("state")}}
    if fa and fb:
        same = all(fa.get(k) == fb.get(k) for k in ("file", "line", "source_sha256"))
        out["outcome"] = "kept" if same else "replaced"
    elif fa:
        out["outcome"] = "reopened" if rb else "dropped"
        dep = {"dependency": "paper", "claim": cid, "was": fa.get("source_sha256"),
               "now": (new.claims.get(cid) or {}).get("source_sha256"),
               **_paper_dependency(paper, cid)}
        out["because"] = [dep]
        where = _context_words(dep)
        out["question"] = None if not rb else (
            f"Does the step {_label(new, cid)} still hold under its changed context ({where})?"
            if where else f"Does the step {_label(new, cid)} still hold as now printed?")
    elif fb:
        out["outcome"] = "newly-current"
    else:
        out["outcome"] = "open"
    return out


# -- the comparison ------------------------------------------------------------------------------

def compare(old_record: dict, old_release: str, new_record: dict, new_release: str) -> dict:
    """The changes from release `old_release` (evidence `old_record`) to `new_release`."""
    old, new = Version(old_record, old_release), Version(new_record, new_release)
    ids = list(dict.fromkeys(list(old.claims) + list(new.claims)))
    paper = {}
    for cid in ids:
        a, b = old.passage(cid), new.passage(cid)
        cls, why, ctx = paper_class(a, b)
        paper[cid] = {"class": cls, "reason": why, "context": ctx,
                      **({"repinned": rp} if (rp := pin_change(a, b)) else {}),
                      # An unchanged passage is described once, as the later build has it.
                      "from": a if cls != "unchanged" else "same", "to": b}
    # A removed claim whose passage another, new claim now has: a proposed match only.
    by_text: dict[str, list[str]] = {}
    for cid in ids:
        b = paper[cid]["to"]
        if paper[cid]["class"] == "new" and b and b.get("passage"):
            by_text.setdefault(b["passage"], []).append(cid)
    for cid in ids:
        p = paper[cid]
        if p["class"] != "removed" or not (p["from"] or {}).get("passage"):
            continue
        cands = by_text.get(p["from"]["passage"]) or []
        if len(cands) == 1:
            p["proposed"] = cands[0]
            p["reason"] += (f"; claim {cands[0]} now has its text: a proposed match, which "
                            "carries no evidence over")
        elif cands:
            p["class"] = "ambiguous"
            p["candidates"] = cands
            p["reason"] = (f"the claim is not in the later inventory, and {len(cands)} new "
                           "claims have its text: resolve the match by hand")
    claims = []
    for cid in ids:
        c = new.claims.get(cid) or old.claims[cid]
        lean, evidence = clause_changes(cid, old, new, paper)
        step = step_outcome(cid, old, new, paper)
        if step:
            evidence.append(step)
        sa, sb = old.assessed.get(cid), new.assessed.get(cid)
        p = paper[cid]
        later = p["to"] if isinstance(p["to"], dict) else {}
        if p["class"] == "unknown" and later.get("pin"):
            p["pin"] = ("the later build has no digest of the passage: no review of it can be "
                        "shown to read the text the paper now prints")
            caveat = "counted against its pin; the later build could not compare the text"
        elif p["class"] not in ("removed", "new", "ambiguous") and later.get("pin") and \
                not later.get("matches_pin"):
            p["pin"] = ("the inventory still pins the earlier text: the source check reports "
                        "the difference, and the reviews that read the passage count as unread "
                        "until it is pinned again and read at the new pin")
            # The assessment reopens the reviews that read the passage; one that a build still
            # counted was assessed before that rule.
            caveat = ("counted against the pinned earlier text by a build that did not reopen "
                      "it; the paper now prints another")
        else:
            caveat = None
        if caveat:
            for e in evidence:
                if e["outcome"] in ("kept", "replaced", "newly-current") and (
                        p["class"] == "unknown" or _reads(e, cid)):
                    e["caveat"] = caveat
        lean_changed = any(
            (r.get("proposition") or {}).get("change", "unchanged") not in ("unchanged",
                                                                            "absent")
            or r["definitions"]
            or any(q["change"] not in ("unchanged", "absent") for q in r["proofs"])
            or r["in"] != "both" for r in lean)
        claims.append({
            "claim": cid, "paper": c["paper"], "number": c.get("number"),
            "kind": c.get("kind"), "scope": c.get("scope"),
            "status": {"from": {k: sa.get(k) for k in ("status", "status_code")} if sa else None,
                       "to": {k: sb.get(k) for k in ("status", "status_code")} if sb else None},
            "paper_change": p, "lean_changed": lean_changed, "lean": lean,
            "evidence": evidence,
            "due": [e for e in evidence if e["outcome"] in ("reopened", "dropped")] != []})
    order = {k: i for i, k in enumerate(CLASSES)}
    claims.sort(key=lambda r: (not r["due"], order[r["paper_change"]["class"]],
                               not r["lean_changed"], r["claim"]))
    decls = _declaration_changes(old, new)
    ia, ib = old.identity(), new.identity()
    outcomes = [e["outcome"] for c in claims for e in c["evidence"]]
    return {
        "schema": SCHEMA, "from": ia, "to": ib,
        "paper_changed": {pid: ia["papers"].get(pid) != ib["papers"].get(pid)
                          for pid in dict.fromkeys(list(ia["papers"]) + list(ib["papers"]))},
        "lean_changed": ia["lean_inputs_sha256"] != ib["lean_inputs_sha256"]
        or ia["project"] != ib["project"],
        "counts": {"claims": {k: n for k in CLASSES
                              if (n := sum(c["paper_change"]["class"] == k for c in claims))},
                   "evidence": {k: n for k in OUTCOMES if (n := outcomes.count(k))},
                   "declarations": {k: n for k in ("statement", "proof", "removed", "new")
                                    if (n := sum(d["change"] == k for d in decls))},
                   "status_changed": sum((c["status"]["from"] or {}).get("status_code")
                                         != (c["status"]["to"] or {}).get("status_code")
                                         for c in claims)},
        "claims": claims, "declarations": decls,
        "note": ("Each status is the one its own build computed; this comparison changes none. "
                 "A reopened review needs a new reading at the later revision; the earlier "
                 "reading stays in the review files as it was.")}


def _declaration_changes(old: Version, new: Version) -> list[dict]:
    """Every project declaration whose statement or proof changed, or that one build has and
    the other has not, with the claims that depend on it in either build."""
    names = set((old.lean.get("decls") or {})) | set((new.lean.get("decls") or {}))
    users: dict[str, set[str]] = {}
    for v in (new, old):
        for cid, a in v.assessed.items():
            for cl in a.get("clauses") or []:
                for n in [cl.get(k) for k in ("spec", "accept", "refute", "witness")] + \
                        v.closure(cl):
                    if n:
                        users.setdefault(n, set()).add(cid)
    out = []
    for n in sorted(names):
        e = _decl_entry(n, old, new)
        if e["change"] in ("unchanged", "absent"):
            continue
        e["claims"] = sorted(users.get(n, ()))
        out.append(e)
    return out


def workspace_due(view: dict, wid: str) -> dict:
    """The records of a workspace (`workspace.view` against the later release's site) that are
    not current: `stale`, with the changes their currency names, or `unchecked`, which the build
    cannot check and are never taken as current. Every kind is listed: evidence, findings,
    questions, counterexamples, compositions, and the claim's reading (requirements, the
    fragments of the paper that govern them or are proposed for them, and alignments). A
    superseded finding and a removed fragment stay as they were and are not listed."""
    rows = []

    def add(r, cid):
        cur = r.get("currency") or {"state": "unchecked", "changes": []}
        if cur.get("state") == "current":
            return
        rows.append({"id": r["id"], "kind": r["kind"], "claim": cid,
                     "state": cur.get("state"), "changes": cur.get("changes") or [],
                     "pinned_release": (r.get("pins") or {}).get("release"),
                     **({"submitted": True} if r.get("state") == "submitted" else {}),
                     **({"proposed": True} if r.get("state") == "proposed" else {})})

    for cid, c in sorted((view.get("claims") or {}).items()):
        for group in ("evidence", "findings", "questions", "counterexamples"):
            for r in c.get(group) or []:
                if group == "findings" and not r.get("in_force", True):
                    continue
                add(r, cid)
        rd = c.get("reading") or {}
        for req in rd.get("requirements") or []:
            add(req, cid)
            for part in ("governing", "later_uses", "proposed"):
                for f in (req.get("fragments") or {}).get(part) or []:
                    add(f, cid)
        for al in rd.get("alignments") or []:
            add(al, cid)
        for comp in c.get("compositions") or []:
            cur = comp.get("currency") or {}
            if cur.get("state") and cur.get("state") != "current":
                rows.append({"id": comp.get("id"), "kind": "composition", "claim": cid,
                             "state": cur.get("state"), "changes": cur.get("changes") or []})
    return {"workspace": wid, "records": rows,
            "note": "A stale record keeps what it was recorded against until it is checked "
                    "again and re-pinned; an unchecked one is not known to be current."}


def due(doc: dict) -> list[dict]:
    """The reopened evidence of a comparison, one entry per review, with its claim."""
    return [{"claim": c["claim"], "number": c["number"], **e}
            for c in doc["claims"] for e in c["evidence"]
            if e["outcome"] in ("reopened", "dropped")]


# -- reading releases ------------------------------------------------------------------------------

def previous_release(out_dir, release: str) -> str | None:
    """The latest release before `release` whose evidence differs from it."""
    from . import evidence as ev
    from .util import read_json
    rels = [read_json(p) for p in ev.releases(out_dir)]
    names = [r["release"] for r in rels]
    if release not in names:
        return None
    mine = rels[names.index(release)]["evidence"]
    for r in reversed(rels[:names.index(release)]):
        if r["evidence"] != mine:
            return r["release"]
    return None


def between(out_dir, old_release: str | None = None, new_release: str | None = None) -> dict:
    """The comparison of two named releases of `out_dir`: by default the latest and the one
    before it."""
    from . import evidence as ev
    from .util import read_json
    rels = ev.releases(out_dir)
    if not rels:
        raise ChangesError("no release: run `machinechecked build` first")
    new_release = new_release or read_json(rels[-1])["release"]
    old_release = old_release or previous_release(out_dir, new_release)
    if old_release is None:
        raise ChangesError(f"release {new_release} has no earlier release with other evidence "
                           "to compare with")
    recs = {}
    for name in (old_release, new_release):
        path = out_dir / "releases" / f"{name}.json"
        if not path.exists():
            raise ChangesError(f"no release {name}: the releases are "
                               + ", ".join(read_json(p)["release"] for p in rels))
        recs[name] = ev.load(out_dir, read_json(path)["evidence"])
    return compare(recs[old_release], old_release, recs[new_release], new_release)


class ChangesError(RuntimeError):
    pass


def with_texts(doc: dict, old_record: dict, new_record: dict, old_dir=None, new_dir=None
               ) -> dict:
    """The comparison with the text of each changed passage, read from the manuscript folders
    of the two revisions. A passage's text is added only when the folder holds exactly the text
    the build recorded (the same digest); otherwise the entry says the folder differs."""
    from pathlib import Path
    from .source_regions import RegionError, location, pin
    for c in doc["claims"]:
        p = c["paper_change"]
        if p["class"] in ("unchanged", "new", "removed"):
            continue
        for side, record, folder in (("from", old_record, old_dir), ("to", new_record, new_dir)):
            here = p.get(side)
            claim = next((x for x in record["body"]["inventory"]["claims"]
                          if x["id"] == c["claim"]), None)
            if folder is None or not here or claim is None or location(claim) is None:
                continue
            try:
                got = pin(Path(folder), claim)
            except (RegionError, OSError, UnicodeError) as e:
                here["text_error"] = str(e)
                continue
            if got.sha256 != here.get("sha256"):
                here["text_error"] = ("the folder does not hold the text this build recorded "
                                      "(another digest)")
                continue
            here["text"] = _cut(got.main.text)
            here["part_text"] = [{"location": f"{r.file}:{r.start_line}",
                                  **({"macro": part["macro"]} if part.get("macro") else {}),
                                  **(_cut(r.text) or {})}
                                 for part, r in [({}, got.main), *got.parts]]
    return doc


# -- for publication -------------------------------------------------------------------------------

def public(doc: dict, papers: dict, lean_ok: bool, reviews_ok: bool,
           paper: str | None = None) -> dict:
    """The comparison with only what the papers' `publish` settings allow: a paper's claims
    (with `paper`, that paper's alone), its passages' places and text only with its source text,
    the Lean statements only with the Lean, the review markers' files and lines only with the
    reviews."""
    import copy
    out = copy.deepcopy(doc)
    out["claims"] = [c for c in out["claims"] if paper is None or c["paper"] == paper]
    kept = {c["claim"] for c in out["claims"]}
    for c in out["claims"]:
        pub = papers.get(c["paper"])
        if pub is None or not pub.source_text:
            for side in ("from", "to"):
                s = c["paper_change"].get(side)
                if isinstance(s, dict):
                    for k in ("location", "bounds", "text", "part_text", "text_error"):
                        s.pop(k, None)
                    for q in s.get("parts") or []:
                        q.pop("location", None)
            for ctx in c["paper_change"].get("context") or []:
                for side in ("from", "to"):
                    if ctx.get(side):
                        ctx[side].pop("location", None)
        _strip(c, lean_ok, reviews_ok)
    for c in out["claims"]:
        if c["paper_change"].get("proposed") not in (None, *kept):
            c["paper_change"].pop("proposed")
        if c["paper_change"].get("candidates"):
            c["paper_change"]["candidates"] = [x for x in c["paper_change"]["candidates"]
                                               if x in kept]
    names = {n for c in out["claims"] for n in _names(c)}
    out["declarations"] = [d for d in out["declarations"]
                           if paper is None or d["name"] in names]
    for d in out["declarations"]:
        d["claims"] = [x for x in d["claims"] if x in kept]
        _strip(d, lean_ok, reviews_ok)
    for pid in list(out["from"]["papers"]) + list(out["to"]["papers"]):
        if paper is not None and pid != paper:
            out["from"]["papers"].pop(pid, None)
            out["to"]["papers"].pop(pid, None)
            out["paper_changed"].pop(pid, None)
    return out


def _names(c: dict) -> set[str]:
    out = set()
    for r in c["lean"]:
        for e in [r.get("proposition") or {}] + r["definitions"] + r["proofs"]:
            out |= {e.get("name"), e.get("renamed_from")} - {None}
    return out


def _strip(obj, lean_ok: bool, reviews_ok: bool):
    """Remove the Lean texts (without the Lean) and the review markers' places (without the
    reviews) wherever they occur."""
    if isinstance(obj, dict):
        if not lean_ok and "fingerprint" in obj:
            obj.pop("text", None)
            obj.pop("truncated", None)
        if not reviews_ok and "by" in obj and "hash" in obj:
            obj.pop("file", None)
            obj.pop("line", None)
        for v in obj.values():
            _strip(v, lean_ok, reviews_ok)
    elif isinstance(obj, list):
        for v in obj:
            _strip(v, lean_ok, reviews_ok)


# -- text ------------------------------------------------------------------------------------------

def text(doc: dict, everything: bool = False) -> str:
    """The comparison as lines for a terminal: the identities, the counts, then each claim with
    a change or reopened evidence (every claim with `everything`)."""
    a, b = doc["from"], doc["to"]
    lines = [f"from release {a['release']} to {b['release']}"]
    for pid in sorted(set(a["papers"]) | set(b["papers"])):
        ra = (a["papers"].get(pid) or {}).get("revision") or "not recorded"
        rb = (b["papers"].get(pid) or {}).get("revision") or "not recorded"
        lines.append(f"  paper {pid}: revision {ra} -> {rb}"
                     + ("" if doc["paper_changed"].get(pid) else " (unchanged)"))
    ca = a["project"].get("commit") or "not recorded"
    cb = b["project"].get("commit") or "not recorded"
    lines.append(f"  Lean project: {ca[:12]} -> {cb[:12]}"
                 + ("" if doc["lean_changed"] else " (Lean inputs unchanged)"))
    counts = doc["counts"]
    lines.append("claims: " + ", ".join(f"{n} {k}" for k, n in counts["claims"].items()))
    lines.append("evidence: " + (", ".join(f"{n} {k}" for k, n in counts["evidence"].items())
                                 or "none recorded"))
    if counts["declarations"]:
        lines.append("declarations changed: " + ", ".join(
            f"{n} {'in their ' + k if k in ('statement', 'proof') else k}"
            for k, n in counts["declarations"].items()))
    for c in doc["claims"]:
        p = c["paper_change"]
        quiet = p["class"] == "unchanged" and not c["lean_changed"] and not c["due"] and \
            all(e["outcome"] in ("kept", "open") for e in c["evidence"])
        if quiet and not everything:
            continue
        lines.append("")
        lines.append(f"{c['number'] or c['claim']} ({c['claim']}): paper {p['class']}: "
                     f"{p['reason']}")
        sa, sb = (c["status"]["from"] or {}).get("status"), (c["status"]["to"] or {}).get("status")
        lines.append(f"  status: earlier build {sa or '-'}; later build {sb or '-'}")
        if p.get("pin"):
            lines.append(f"  note: {p['pin']}")
        for ctx in p.get("context") or []:
            where = ctx.get("macro") or ((ctx.get("to") or ctx.get("from") or {})
                                          .get("location") or "")
            lines.append(f"  context: {ctx['what']} {where} {ctx['change']}")
        for word, where, t in shown_texts(p):
            lines.append(f"  {word} {where}:")
            lines += ["    " + ln for ln in t.splitlines()]
        for r in c["lean"]:
            for e in [r.get("proposition")] + r["definitions"] + r["proofs"]:
                if not e or e["change"] in ("unchanged", "absent"):
                    continue
                lines.append(f"  Lean ({r['clause']}): {e['name']}: {CHANGE_WORDS[e['change']]}")
                if e["change"] in ("statement", "renamed"):
                    for side, word in (("from", "was"), ("to", "now")):
                        t = (e.get(side) or {}).get("text")
                        if t:
                            lines.append(f"    {word}: " + t.replace("\n", "\n         "))
        for e in c["evidence"]:
            if e["outcome"] in ("open",) and not everything:
                continue
            who = ((e["from"].get("marker") or e["to"].get("marker") or {}).get("by"))
            lines.append(f"  review of {e['name']}" + (f" by {who}" if who else "")
                         + f": {OUTCOME_WORDS[e['outcome']]}")
            for d in e.get("because") or []:
                lines.append("    because: " + _dependency_words(d))
            if e.get("question"):
                lines.append(f"    question: {e['question']}")
            if e.get("caveat"):
                lines.append(f"    note: {e['caveat']}")
            for t in e.get("kept_through") or []:
                lines.append(f"    stands through a change of {t}, which it does not read")
    if doc.get("workspace"):
        lines.append("")
        lines += workspace_lines(doc["workspace"])
    lines.append("")
    lines.append(doc["note"])
    return "\n".join(lines)


def workspace_lines(due: dict) -> list[str]:
    """The records of a workspace that are not current (`workspace_due`), for a terminal."""
    rows = due.get("records") or []
    out = [f"workspace {due['workspace']}: "
           + (f"{len(rows)} record(s) not current" if rows else "every record is current")]
    for r in rows:
        out.append(f"  {r['kind']} {r['id']} ({r['claim']}): {r['state']}"
                   + (", submitted" if r.get("submitted") else "")
                   + (", proposed" if r.get("proposed") else ""))
        for words in dict.fromkeys(_record_change_words(ch) for ch in r.get("changes") or []):
            out.append("    because: " + words)
    if rows:
        out.append("  " + due["note"])
    return out


def _record_change_words(ch: dict) -> str:
    """One change a workspace record's currency names (`workspace.currency`), in words."""
    if ch.get("reason"):
        return ch["reason"]
    if ch.get("decl"):
        return f"{ch['decl']} changed" if ch.get("now") else f"{ch['decl']} is not in the build"
    if ch.get("region"):
        return f"the paper's text at {ch['region']} changed" if ch.get("now") else \
            f"the paper has no text at {ch['region']}"
    what = ch.get("passage") or ch.get("claim")
    if what:
        return f"the passage of {what} changed" if ch.get("now") else \
            f"{what} is not in the build"
    return "changed since it was recorded"


def shown_texts(p: dict) -> list[tuple[str, str, str]]:
    """The texts that show a passage change, as (`earlier`/`later`, what, text): for a change of
    context, the further passages that changed; otherwise the claim's own passage."""
    if p["class"] in ("unchanged", "moved"):
        return []
    out = []
    places = {(c.get(k) or {}).get("location") for c in p.get("context") or []
              for k in ("from", "to")} - {None}
    for side, word in (("from", "earlier"), ("to", "later")):
        here = p.get(side)
        if not isinstance(here, dict):
            continue
        if p["class"] == "context-changed":
            parts = here.get("part_text") or []
            out += [(word, f"context ({q['location']})", q["text"]) for q in parts[1:]
                    if q.get("location") in places and q.get("text")]
        elif (here.get("text") or {}).get("text"):
            out.append((word, "text", here["text"]["text"]))
    return out


CHANGE_WORDS = {"statement": "its statement changed", "proof": "only its proof changed",
                "removed": "not in the later build", "new": "new in the later build",
                "renamed": "another declaration in the later build"}
OUTCOME_WORDS = {"reopened": "due for review", "dropped": "no longer applies to this claim",
                 "replaced": "a new reading in the later build", "newly-current":
                 "current in the later build only", "kept": "still current", "open":
                 "not current in either build"}


def _dependency_words(d: dict) -> str:
    if d["dependency"] == "lean":
        return f"{d['name']} changed" if d.get("now") else \
            f"{d['name']}: {d.get('detail', 'not in the later build')}"
    if d["dependency"] == "paper":
        out = f"the passage of {d['claim']} changed"
        if d.get("context"):
            out = f"the context of {d['claim']}'s passage changed ({_context_words(d)})"
        return out + (f" ({(d.get('was') or '')[:12]} -> {(d.get('now') or '')[:12]})"
                      if d.get("was") or d.get("now") else "") + (
            f"; {d['detail']}" if d.get("detail") else "")
    return d.get("detail", "")
