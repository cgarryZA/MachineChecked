"""The presentation manifest, derived from one evidence record.

`index.json` lists the papers and claims; `claims/<file>.json` holds one claim with everything
its passport shows. Nothing here decides a status: statuses and findings are copied from the
assessment in the evidence, and the evidence ladder is a fixed reading of the clause checks.
"""

from __future__ import annotations

import re
from collections import Counter

from .assess import match_anchor
from .util import content_id, sha256_text

SCHEMA = "prooflens/manifest@0"


def claim_file(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", cid) + "-" + sha256_text(cid)[:8] + ".json"


def status_class(status: str) -> str:
    """A coarse class for colouring; the status text is always shown verbatim beside it."""
    if status in ("formal: accepted", "definition: reviewed"):
        return "accepted"
    if status.startswith("formal: proved") or status == "definition: author-reviewed":
        return "proved"
    if status.startswith("refuted"):
        return "refuted"
    if status in ("formal: open", "definition: review pending"):
        return "open"
    if status.endswith("malformed"):
        return "malformed"
    if status.startswith("out of scope"):
        return "out-of-scope"
    return "unspecified"


def top_of(anchor: dict) -> tuple[int, float]:
    """Page and top of a located claim: a line height above the baseline of its first line when
    that is recorded, else the position where the environment opened."""
    if anchor.get("head"):
        return anchor["head"][0], round(anchor["head"][2] - 11, 2)
    return anchor["begin"][0], anchor["begin"][2]


def ladder(cl: dict, anchor: dict | None, mode: str | None, src_ok: bool | None) -> list[dict]:
    """The rungs of the evidence ladder of one clause, each with its own state."""
    ch = cl.get("checks", {})
    proof = ch.get("accept") or ch.get("refute")
    rungs = []
    if cl["state"] == "unchecked":
        rungs.append({"rung": "Lean", "state": "none",
                      "detail": "the Lean project was not checked in this build"})
    elif cl.get("defs") and not cl.get("spec"):
        rungs.append({"rung": "stated", "state": "pass" if cl["state"] == "stated" else "fail",
                      "detail": ", ".join(cl["defs"])})
    else:
        spec = ch.get("spec")
        rungs.append({"rung": "locked statement",
                      "state": "none" if not cl.get("spec") else
                      ("pass" if spec and spec["ok"] else "fail"),
                      "detail": cl.get("spec") or "no proposition written"})
        if proof is None:
            rungs.append({"rung": "exact statement", "state": "none", "detail": "no proof"})
        else:
            type_errs = [e for e in proof["errors"] if not e.startswith("axioms=")]
            rungs.append({"rung": "exact statement",
                          "state": "pass" if not type_errs and not proof["sorry"] else "fail",
                          "detail": ("a theorem has exactly the negation as its type"
                                     if ch.get("refute") else
                                     "a theorem has exactly this proposition as its type"),
                          "errors": proof["errors"]})
            rungs.append({"rung": "axioms", "state": "pass" if not any(
                e.startswith("axioms=") for e in proof["errors"]) and not proof["sorry"]
                else "fail", "detail": ", ".join(proof["axioms"]) or "none"})
            rp = ch.get("replay") or {"state": "not-run", "detail": "no Comparator log"}
            rungs.append({"rung": "kernel replay", "state": rp["state"], "detail": rp["detail"]})
        w = ch.get("witness")
        rungs.append({"rung": "witness",
                      "state": "n/a" if w is None else ("pass" if w["ok"] else "open"),
                      "detail": cl.get("witness") or ("not needed" if w is None else "missing")})
        regs = cl.get("regimes", [])
        rungs.append({"rung": "regimes",
                      "state": "n/a" if not regs else
                      ("pass" if all(r["discharged"] for r in regs) else "open"),
                      "detail": f"{sum(r['discharged'] for r in regs)}/{len(regs)} covered"
                      if regs else "none declared"})
    rev = cl.get("review", "unknown")
    kinds = sorted({r["kind"] for r in (cl.get("spec_review") or {}).get("current", [])})
    rungs.append({"rung": "review",
                  "state": {"reviewed": "pass", "author-reviewed": "author",
                            "pending": "open"}.get(rev, "none"),
                  "detail": rev + (f" ({', '.join(kinds)})" if kinds else "")})
    rungs.append({"rung": "source",
                  "state": "pdf-only" if mode == "pdf" else
                  ("none" if anchor is None else ("pass" if src_ok is not False else "fail")),
                  "detail": "PDF only: statement not hashed from source" if mode == "pdf" else
                  ("not located in the compiled paper" if anchor is None else
                   f"{anchor['file']}:{anchor['line']}")})
    return rungs


def build(evidence: dict, release: str) -> tuple[dict, dict[str, dict]]:
    body = evidence["body"]
    inv = body["inventory"]["claims"]
    lean = body.get("lean") or {}
    tex = body.get("tex") or {}
    assessed = {c["id"]: c for c in body["assessment"]["claims"]}
    findings = body["assessment"]["findings"]
    by_subject: dict[str, list] = {}
    for f in findings:
        by_subject.setdefault(f["subject"].split("#")[0], []).append(f)

    papers = []
    for pid, prov in body["provenance"]["papers"].items():
        t = tex.get(pid, {})
        papers.append({"id": pid, "title": prov.get("title", pid), "mode": prov["mode"],
                       "revision": prov.get("revision"), "root": prov.get("root"),
                       "pdf": f"papers/{pid}.pdf" if prov.get("pdf_sha256") else None,
                       "pdf_sha256": prov.get("pdf_sha256"), "page_size": t.get("page_size"),
                       "note": prov.get("note", "")})

    store = decl_records(body, lean)
    keys = {n: record_key(r) for n, r in store.items()}
    index_claims, chunks, summary = [], {}, {}
    for c in inv:
        a = assessed[c["id"]]
        t = tex.get(c["paper"], {})
        anchor = match_anchor(c, t.get("anchors", [])) if t.get("mode") == "latex" else None
        src_ok = None
        if anchor and c.get("source_sha256") and anchor.get("source_sha256"):
            src_ok = anchor["source_sha256"] == c["source_sha256"]
        fs = by_subject.get(c["id"], [])
        counts = Counter(f["tier"] for f in fs if not f.get("dismissed"))
        summary.setdefault(c["paper"], Counter())[a["status"]] += 1
        fname = claim_file(c["id"])
        index_claims.append({
            "id": c["id"], "paper": c["paper"], "number": c.get("number", ""),
            "title": c.get("title", ""), "kind": c.get("kind", ""), "scope": c["scope"],
            "status": a["status"], "class": status_class(a["status"]),
            "anchor": {"page": top_of(anchor)[0], "y0": top_of(anchor)[1],
                       "y1": anchor["end"][2] if anchor.get("end") and
                       anchor["end"][0] == anchor["begin"][0] else None,
                       "page_end": anchor["end"][0] if anchor.get("end") else None}
            if anchor and anchor.get("begin") else None,
            "counts": dict(counts), "file": fname})
        clauses = []
        for cl in a["clauses"]:
            spec = lean.get("specs", {}).get(cl.get("spec") or "")
            proofs = {}
            for kind in ("accept", "refute"):
                if cl.get(kind):
                    proofs[kind] = lean.get("proofs", {}).get(f"{kind}:{cl[kind]}:{cl['spec']}")
            wit = lean.get("proofs", {}).get(f"witness:{cl.get('witness')}:") \
                if cl.get("witness") else None
            clauses.append({**cl, "statement": {
                "binders": spec.get("binders", []), "conclusion": spec.get("conclusion"),
                "axioms": spec.get("axioms", []), "closure": spec.get("closure", []),
                "direct": spec.get("direct", []), "legacy_hash": spec.get("legacy_hash"),
                "fingerprint": spec.get("fingerprint"),
                "decl": lean.get("decls", {}).get(cl["spec"])} if spec else None,
                "proofs": proofs, "witness_record": wit,
                "ladder": ladder(cl, anchor, t.get("mode"), src_ok)})
        names = set()
        for cl in clauses:
            st = cl.get("statement") or {}
            names.update(st.get("closure", []))
            names.update(cl.get("defs", []))
            names.update((cl.get("def_reviews") or {}).keys())
            # A definition's review belongs to the definition (shared store); the clause keeps
            # its state and reviewer.
            cl["def_reviews"] = {n: {"state": r["state"],
                                     "by": [x["by"] for x in r.get("current", [])],
                                     "kind": [x["kind"] for x in r.get("current", [])]}
                                 for n, r in (cl.get("def_reviews") or {}).items()}
            if st:
                st.pop("decl", None)
        decls = {n: keys[n] for n in sorted(names) if n in keys}
        chunks[fname] = {
            "schema": SCHEMA, "release": release, "id": c["id"], "paper": c["paper"],
            "number": c.get("number", ""), "title": c.get("title", ""), "kind": c.get("kind", ""),
            "scope": c["scope"], "scope_note": c.get("scope_note", ""),
            "scope_reviewed": c.get("scope_reviewed"), "location": c.get("location"),
            "source_sha256": c.get("source_sha256"), "status": a["status"],
            "class": status_class(a["status"]), "anchor": anchor, "source_matches": src_ok,
            "statement_tex": (anchor or {}).get("statement"),
            "blockers": a.get("blockers", []),
            "clauses": clauses, "decls": decls, "findings": fs}

    prov = body["provenance"]
    index = {"schema": SCHEMA, "release": release, "evidence": evidence["id"],
             "created": evidence["created"], "project": prov["project"],
             "lean": prov.get("lean"), "tool": prov["tool"], "papers": papers,
             "summary": {p: dict(s) for p, s in summary.items()},
             "classes": {st: status_class(st) for s in summary.values() for st in s},
             "gates": body["assessment"].get("gates", {}),
             "findings": {"total": dict(Counter(f["tier"] for f in findings
                                                if not f.get("dismissed"))),
                          "general": [f for f in findings
                                      if f["subject"].split("#")[0] not in
                                      {c["id"] for c in inv}]},
             "claims": index_claims}
    return index, chunks, {keys[n]: r for n, r in store.items()}


def record_key(record: dict) -> str:
    """The key of a declaration record: the first 24 hex digits of the SHA-256 of its canonical
    JSON. The record holds the declaration's name, kind and fingerprint, so different
    declarations never share a key, and a record never changes under its key."""
    return content_id(record)[:24]


def decl_records(body: dict, lean: dict) -> dict[str, dict]:
    """Every declaration once, with its current review."""
    reviews: dict[str, dict] = {}
    for c in body["assessment"]["claims"]:
        for cl in c["clauses"]:
            for n, r in (cl.get("def_reviews") or {}).items():
                reviews.setdefault(n, r)
    return {n: {**d, "review": reviews.get(n)} for n, d in lean.get("decls", {}).items()}
