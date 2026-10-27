"""The presentation manifest, derived from one evidence record.

`index.json` lists the papers and claims; `claims/<file>.json` holds one claim with everything
its passport shows. Nothing here decides a status: statuses and findings are copied from the
assessment in the evidence, and the evidence ladder is a fixed reading of the clause checks.
"""

from __future__ import annotations

import re
from collections import Counter

from . import steps
from .assess import line_location, match_anchor, unread
from .source_regions import matches as source_matches
from .util import content_id, sha256_text
from .status import fields, STATUSES, source_evidence

SCHEMA = "prooflens/manifest@1"


def claim_file(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", cid) + "-" + sha256_text(cid)[:8] + ".json"


def status_class(status: str) -> str:
    """Coarse colour for CLI summaries; reader logic uses status_code."""
    return next((v["class"] for v in STATUSES.values() if v["label"] == status), "unspecified")


def top_of(anchor: dict) -> tuple[int, float]:
    """Page and top of a located claim: a line height above the baseline of its first line when
    that is recorded, else the position where the environment opened."""
    if anchor.get("head"):
        return anchor["head"][0], round(anchor["head"][2] - 11, 2)
    return anchor["begin"][0], anchor["begin"][2]


def index_anchor(anchor: dict | None, kind: str) -> dict | None:
    """A located claim's place as the index lists it (for the contents and the margin): its
    page and top, where it ends on that page, and the page it ends on."""
    if not anchor or not anchor.get("begin"):
        return None
    page, y0 = top_of({**anchor, "kind": kind})
    end = anchor.get("end")
    return {"kind": kind, "page": page, "y0": y0,
            "y1": end[2] if end and end[0] == anchor["begin"][0] else None,
            "page_end": end[0] if end else None}


def clause_evidence(cl: dict, anchor: dict | None, mode: str | None, src_ok: bool | None,
                    paper: dict | None = None) -> dict:
    """The rungs of the evidence ladder of one clause, each with its own state."""
    ch = cl.get("checks", {})
    proof = ch.get("accept") or ch.get("refute")
    rungs = [{"dimension": "formal", "state": cl["state"]}]
    if cl["state"] != "unchecked" and not (cl.get("defs") and not cl.get("spec")):
        spec = ch.get("spec")
        rungs.append({"dimension": "locked-statement",
                      "state": "none" if not cl.get("spec") else
                      ("pass" if spec and spec["ok"] else "fail"),
                      "detail": cl.get("spec") or "no proposition written"})
        if proof is None:
            rungs.append({"dimension": "exact-statement", "state": "none", "detail": "no proof"})
        else:
            type_errs = [e for e in proof["errors"] if not e.startswith("axioms=")]
            rungs.append({"dimension": "exact-statement",
                          "state": "pass" if not type_errs and not proof["sorry"] else "fail",
                          "detail": ("a theorem has exactly the negation as its type"
                                     if ch.get("refute") else
                                     "a theorem has exactly this proposition as its type")
                                    if not type_errs and not proof["sorry"] else
                                    "the exact-type or proof-completeness check failed",
                          "errors": proof["errors"]})
            rungs.append({"dimension": "axioms", "state": "pass" if not any(
                e.startswith("axioms=") for e in proof["errors"]) and not proof["sorry"]
                else "fail", "detail": ", ".join(proof["axioms"]) or "none"})
        w = ch.get("witness")
        rungs.append({"dimension": "witness",
                      "state": "n/a" if w is None else ("pass" if w["ok"] else "open"),
                      "detail": cl.get("witness") or ("not needed" if w is None else "missing")})
        regs = cl.get("regimes", [])
        rungs.append({"dimension": "regimes",
                      "state": "n/a" if not regs else
                      ("pass" if all(r["discharged"] for r in regs) else "open"),
                      "detail": f"{sum(r['discharged'] for r in regs)}/{len(regs)} covered"
                      if regs else "none declared"})
    result = {r.pop("dimension"): r for r in rungs}
    result["review"] = {"state": cl.get("review", "unknown")}
    result["replay"] = ch.get("replay") or {"state": "not-run"}
    result["source"] = source_evidence(anchor, mode, src_ok, paper)
    return result


def symbol_links(display: dict | None, cid: str, tex: str | None, lean: dict,
                 excerpt: dict | None = None) -> list[dict]:
    """The claim's symbol links, each as its author recorded it and whether it is stale, with why
    (`stale_because`, codes of `symbols.STALE`): the statement it points into has another
    fingerprint now, the claim's printed text changed, or the Lean object it names is no longer
    the one it was made on. A link made on a typeset excerpt (`pins.excerpt`) is also stale when
    that excerpt, or the macros and references it is typeset with, changed or can no longer be
    typeset. Display only (docs/SYMBOL_LINKS.md)."""
    from .symbols import spec_of, stale_reasons
    ready = excerpt if excerpt and excerpt.get("ready") else None
    out = []
    for ln in (display or {}).get("symbols", []):
        if ln.get("claim") != cid:
            continue
        target = ln.get("lean") or {}
        # A claim's proposition, or the definition of a claim that only defines.
        spec = spec_of(lean, target.get("decl"))
        pins = ln.get("pins") or {}
        if "excerpt" in pins:
            moved = (ready is None or pins["excerpt"] != ready.get("fingerprint")
                     or pins.get("source") != sha256_text(ready.get("text") or ""))
        else:
            moved = not tex or pins.get("source") != sha256_text(tex)
        why = stale_reasons(spec, target, pins,
                            ("excerpt" if "excerpt" in pins else "source") if moved else None)
        out.append({"symbol": ln.get("symbol") or {}, "lean": target, "by": ln.get("by"),
                    "stale": bool(why), "stale_because": why})
    return out


def build(evidence: dict, release: str, display: dict | None = None
          ) -> tuple[dict, dict[str, dict]]:
    """The presentation manifest of `evidence`. `display` (the project's display overlay) gives
    per claim a TeX `title_tex` and a printed `number` to show in place of the inventory's; it
    changes what is shown, not what is assessed."""
    body = evidence["body"]
    shown = (display or {}).get("claims", {})
    clause_tex = {n: v["title_tex"] for n, v in (display or {}).get("clauses", {}).items()
                  if v.get("title_tex")}
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
                       "note": prov.get("note", ""),
                       **{k: prov[k] for k in ("published", "published_note", "source_commit",
                                               "paper_version") if prov.get(k)}})

    store = decl_records(body, lean)
    keys = {n: record_key(r) for n, r in store.items()}
    index_claims, chunks, summary = [], {}, {}
    inv_by_id = {c["id"]: c for c in inv}
    for c in inv:
        a = assessed[c["id"]]
        if "status_code" not in a:
            raise ValueError("Old assessment: rebuild the audit with the current MachineChecked version")
        status = fields(a["status_code"])
        t = tex.get(c["paper"], {})
        unit = steps.unit_of(c, (t.get("regions") or {}).get(c["id"]))
        anchor = match_anchor(c, t.get("anchors", [])) if t.get("mode") in ("latex", "pdf") \
            else None
        src_ok = None
        if anchor and t.get("mode") == "pdf":
            # Found by its heading in the PDF: where it ends is estimated.
            anchor = {**anchor, "kind": "approximate"}
        elif anchor:
            # (The inventory's source hash is of the LaTeX statement; a PDF's extracted text
            # cannot be compared with it.)
            anchor = {**anchor, "kind": "exact"}
            if c.get("source_sha256") and anchor.get("source_sha256"):
                src_ok = anchor["source_sha256"] == c["source_sha256"]
        elif line_location(c) is not None and t.get("mode") == "latex":
            la = (t.get("line_anchors") or {}).get(c["location"])
            if la and la.get("kind") == "ambiguous":
                path, _, line = c["location"].rpartition(":")
                anchor = {"kind": "ambiguous", "file": path, "line": int(line),
                          "pages": la["pages"]}
            elif la and la.get("kind", "approximate") == "approximate":
                path, _, line = c["location"].rpartition(":")
                anchor = {"kind": "approximate", "file": path, "line": int(line),
                          "begin": [la["page"], 0, la["y0"]], "end": [la["page"], 0, la["y1"]]}
        if line_location(c) is not None and t.get("mode") == "latex":
            src_ok = source_matches(c, t)
        manual = (t.get("manual_anchors") or {}).get(c["id"])
        if manual:
            anchor = {**(anchor or {}), "kind": "manual", "note": manual.get("note", ""),
                      "by": manual.get("by", ""), "head": None,
                      "begin": [manual["page"], 0, manual["y0"]],
                      "end": [manual["page"], 0, manual["y1"]]}
        # The title the paper prints (`\\begin{theorem}[Efficiency]`), as TeX; the inventory's
        # own description is kept as `title` and shown only as such.
        heading = (anchor or {}).get("title") if (anchor or {}).get("kind") == "exact" else None
        over = shown.get(c["id"], {})
        number = over.get("number") or c.get("number", "")
        description = over["title_tex"] if "title_tex" in over else c.get("title", "")
        fs = by_subject.get(c["id"], [])
        counts = Counter(f["tier"] for f in fs if not (f.get("dismissed") or f.get("resolved")))
        summary.setdefault(c["paper"], Counter())[a["status"]] += 1
        fname = claim_file(c["id"])
        # The printed statement: an environment's body, or the passage of a claim located by
        # line, each read from the file that holds it (display only).
        statement = (anchor or {}).get("statement") or \
            (t.get("region_text") or {}).get(c["id"])
        index_claims.append({
            "id": c["id"], "paper": c["paper"], "number": number,
            "title": description, "heading": heading, "kind": c.get("kind", ""),
            "scope": c["scope"], "unit": unit, "parent": c.get("parent"), **status,
            "anchor": {"kind": anchor["kind"], "page": top_of(anchor)[0], "y0": top_of(anchor)[1],
                       "y1": anchor["end"][2] if anchor.get("end") and
                       anchor["end"][0] == anchor["begin"][0] else None,
                       "page_end": anchor["end"][0] if anchor.get("end") else None}
            if anchor and anchor.get("begin") else None,
            "unplaced": anchor.get("kind") if anchor and not anchor.get("begin") else None,
            "counts": dict(counts), "file": fname})
        clauses = []
        for cl in a["clauses"]:
            spec = lean.get("specs", {}).get(cl.get("spec") or "")
            if unread(spec):
                # The probe found no proposition under the name: there is no statement to show.
                spec = None
            proofs = {}
            for kind in ("accept", "refute"):
                if cl.get(kind):
                    proofs[kind] = lean.get("proofs", {}).get(f"{kind}:{cl[kind]}:{cl['spec']}")
            wit = lean.get("proofs", {}).get(f"witness:{cl.get('witness')}:") \
                if cl.get("witness") else None
            clauses.append({**cl, "label": clause_tex.get(cl["name"], cl["name"]),
                            "corrects_label": clause_tex.get(cl.get("corrects") or "",
                                                             cl.get("corrects")),
                            "statement": {
                "binders": spec.get("binders", []), "conclusion": spec.get("conclusion"),
                "tree": spec.get("tree"),
                "exact": spec.get("exact") or (spec.get("decl") or lean.get("decls", {}).get(cl["spec"]) or {}).get("value"),
                "axioms": spec.get("axioms", []), "closure": spec.get("closure", []),
                "direct": spec.get("direct", []), "legacy_hash": spec.get("legacy_hash"),
                "fingerprint": spec.get("fingerprint"),
                "decl": lean.get("decls", {}).get(cl["spec"])} if spec else None,
                "proofs": proofs, "witness_record": wit,
                "evidence": clause_evidence(cl, anchor, t.get("mode"), src_ok, t)})
        index_claims[-1]["evidence_summary"] = [
            {k: cl["evidence"][k] for k in ("formal", "review") if k in cl["evidence"]}
            for cl in clauses]
        names = set()
        for cl in clauses:
            st = cl.get("statement") or {}
            names.update(st.get("closure", []))
            names.update(cl.get("defs", []))
            names.update((cl.get("def_reviews") or {}).keys())
            names.update(e["name"] for e in cl.get("witness_defs") or [])
            names.update(e["name"] for e in cl.get("witness_candidates") or [])
            # A definition's review belongs to the definition (shared store); the clause keeps
            # its state and reviewer.
            cl["def_reviews"] = {n: {"state": r["state"],
                                     "by": [x["by"] for x in r.get("current", [])],
                                     "kind": [x["kind"] for x in r.get("current", [])],
                                     **({"rests_on": r["rests_on"]} if r.get("rests_on")
                                        else {})}
                                 for n, r in (cl.get("def_reviews") or {}).items()}
            if st:
                st.pop("decl", None)
        step = None
        if unit != "statement":
            par = inv_by_id.get(c.get("parent") or "")
            step, more = steps.full_block(
                c, {"id": par["id"], "number": shown.get(par["id"], {}).get("number")
                    or par.get("number", ""), "title": par.get("title", ""), "heading": None,
                    "file": claim_file(par["id"])} if par else None,
                lean, a.get("step_review"), unit)
            names.update(more)
            names.update(l["name"] for l in step["links"] + (step["route"] or {}).get(
                "links", []))
        decls = {n: keys[n] for n in sorted(names) if n in keys}
        chunks[fname] = {
            "schema": SCHEMA, "release": release, "id": c["id"], "paper": c["paper"],
            "number": number, "number_note": over.get("number_note"), "title": description,
            "heading": heading,
            "kind": c.get("kind", ""), "scope": c["scope"], "scope_note": c.get("scope_note", ""),
            "scope_reviewed": c.get("scope_reviewed"), "location": c.get("location"),
            "source_sha256": c.get("source_sha256"), **status, "anchor": anchor, "source_matches": src_ok,
            "source_evidence": source_evidence(anchor, t.get("mode"), src_ok, t),
            "statement_tex": statement,
            # The passage the reader typesets, when it can be typeset faithfully (display only).
            "excerpt": (t.get("excerpts") or {}).get(c["id"]),
            # Every passage of a pin that lists several, in order (display only).
            **({"source_parts": t["part_text"][c["id"]]}
               if (t.get("part_text") or {}).get(c["id"]) else {}),
            "blockers": [shown_names(b, clause_tex) for b in a.get("blockers", [])],
            "clauses": clauses, "decls": decls, "findings": fs,
            "symbols": symbol_links(display, c["id"], statement, lean,
                                    (t.get("excerpts") or {}).get(c["id"])),
            "unit": unit, "parent": c.get("parent"),
            **({"step": step} if step else {})}
        if step and (t.get("step_text") or {}).get(c["id"]):
            # A proof step's printed text and its context in the proof, from the snapshot,
            # with where the context was cut when it was.
            chunks[fname]["statement_tex"] = chunks[fname]["statement_tex"] or \
                t["step_text"][c["id"]]["text"]
            chunks[fname]["context_tex"] = t["step_text"][c["id"]]["context"]
            cut = steps.context_cut(t["step_text"][c["id"]])
            if cut:
                chunks[fname]["context_cut"] = cut

    steps.attach_parents(index_claims, chunks)
    prov = body["provenance"]
    index = {"schema": SCHEMA, "release": release, "evidence": evidence["id"],
             "created": evidence["created"], "project": prov["project"],
             "lean": prov.get("lean"), "tool": prov["tool"], "papers": papers,
             "summary": {p: dict(s) for p, s in summary.items()},
             "units": steps.unit_counts(index_claims),
             "classes": {st: status_class(st) for s in summary.values() for st in s},
             "gates": body["assessment"].get("gates", {}),
             "findings": {"total": dict(Counter(f["tier"] for f in findings
                                                if not (f.get("dismissed")
                                                        or f.get("resolved")))),
                          "general": [f for f in findings
                                      if f["subject"].split("#")[0] not in
                                      {c["id"] for c in inv}]},
             "claims": index_claims}
    index["search"] = "data/search.json"
    return index, chunks, {keys[n]: r for n, r in store.items()}


def shown_names(text: str, clause_tex: dict[str, str]) -> str:
    """`text` with the clause names it quotes in their displayed (TeX) form."""
    for n in sorted(clause_tex, key=len, reverse=True):
        if n in text:
            text = text.replace(n, clause_tex[n])
    return text


def search_index(index: dict, chunks: dict) -> dict:
    """What the reader searches: every claim (number, title, id, status, printed statement, Lean
    names of its clauses) and every declaration (with the claims whose closure holds it)."""
    claims, decls = [], {}
    for c in index["claims"]:
        ch = chunks[c["file"]]
        lean = [n for cl in ch["clauses"] for n in (cl.get("spec"), cl.get("accept"),
                                                    cl.get("refute"), *cl.get("defs", [])) if n]
        lean += [l["name"] for l in ch.get("links", []) if l.get("name")]
        claims.append({"id": c["id"], "paper": c["paper"], "number": c.get("number", ""),
                       "title": c.get("title", ""), "heading": c.get("heading"),
                       "status": c["status"], "status_code": c["status_code"],
                       "statement": ch.get("statement_tex") or (ch.get("excerpt") or {}).get("text")
                       or "", "lean": lean})
        for n in ch.get("decls", {}):
            decls.setdefault(n, []).append(c["id"])
    return {"claims": claims, "decls": [{"name": n, "claims": ids} for n, ids in
                                        sorted(decls.items())]}


def record_key(record: dict) -> str:
    """The key of a declaration record: the first 24 hex digits of the SHA-256 of its canonical
    JSON. The record holds the declaration's name, kind and fingerprint, so different
    declarations never share a key, and a record never changes under its key."""
    return content_id(record)[:24]


EXPANSION_REF = ("at", "id", "name", "key")

# A declaration's record lists at most this many of its equations; the others are stored in
# pages of as many (`split_expansions`).
EQUATIONS_INLINE = 64


def is_expansion_ref(x) -> bool:
    """Whether `x` is a reference to a part stored on its own (`split_expansions`): an
    expansion, or a page of a declaration's equations."""
    return isinstance(x, dict) and "key" in x and set(x) <= set(EXPANSION_REF)


def fingerprints(store: dict[str, dict]) -> dict[str, str]:
    """The fingerprint of each declaration of `store` by name, for `split_expansions`; a name
    the store gives two fingerprints (two projects' declarations on one paper page) has none."""
    seen: dict[str, set] = {}
    for r in store.values():
        if isinstance(r, dict) and r.get("name") and r.get("fingerprint"):
            seen.setdefault(r["name"], set()).add(r["fingerprint"])
    return {n: next(iter(fs)) for n, fs in seen.items() if len(fs) == 1}


def _stored(part: dict, out: dict[str, dict]) -> str:
    key = record_key(part)
    out[key] = part
    return key


def split_expansions(obj, out: dict[str, dict], pins: dict[str, str] | None = None):
    """`obj` with what the reader fetches only when it is opened put in `out` under its key
    (`record_key`) and replaced by a reference to it:

    - each definition expanded at an application (an entry of a printed term's `expansions`),
      by `{at, id, name, key}`, its own nested expansions replaced in turn. With `pins` (the
      declarations' fingerprints by name, `fingerprints`), an expansion records the fingerprint
      of the definition it expands (`fingerprint`), so that its key changes whenever the
      definition does, not only when what it prints does;
    - a declaration's equations after the first `EQUATIONS_INLINE` (`equations`, listed with
      `equation_names`), in pages of as many, `{definition, equations}`, by `equations_more`:
      `{name, key}` for each page, in order, `name` the theorem of its first equation.

    A claim file thus carries only the references, and a part that recurs in several statements
    is stored once. Display only: no status reads an expansion or an equation."""
    if isinstance(obj, list):
        return [split_expansions(v, out, pins) for v in obj]
    if not isinstance(obj, dict):
        return obj
    res = {}
    for k, v in obj.items():
        if k == "expansions" and isinstance(v, list):
            refs = []
            for x in v:
                if is_expansion_ref(x) or not isinstance(x, dict):
                    refs.append(x)
                    continue
                full = split_expansions(x, out, pins)
                if pins and "fingerprint" not in full and pins.get(full.get("name")):
                    full["fingerprint"] = pins[full["name"]]
                refs.append({"at": full.get("at"), "id": full.get("id"),
                             "name": full.get("name"), "key": _stored(full, out)})
            res[k] = refs
        else:
            res[k] = split_expansions(v, out, pins)
    eqs = res.get("equations")
    if "equation_names" in res and isinstance(eqs, list) and len(eqs) > EQUATIONS_INLINE:
        n = EQUATIONS_INLINE
        pages = [eqs[i:i + n] for i in range(n, len(eqs), n)]
        res["equations"] = eqs[:n]
        res["equations_more"] = list(res.get("equations_more") or []) + [
            {"name": p[0].get("name"), "key": _stored({"definition": res.get("name"),
                                                       "equations": p}, out)}
            for p in pages]
    return res


def expansion_keys(obj) -> set[str]:
    """The keys of the parts stored on their own that `obj` refers to (expansions and pages of
    equations), not those they refer to."""
    found: set[str] = set()
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if is_expansion_ref(o):
                found.add(o["key"])
            else:
                stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return found


def decl_records(body: dict, lean: dict) -> dict[str, dict]:
    """Every declaration once, with its current review."""
    reviews: dict[str, dict] = {}
    for c in body["assessment"]["claims"]:
        for cl in c["clauses"]:
            for n, r in (cl.get("def_reviews") or {}).items():
                reviews.setdefault(n, r)
    return {n: {**d, "review": reviews.get(n)} for n, d in lean.get("decls", {}).items()}
