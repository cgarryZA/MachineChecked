"""The semantic summary of an audit (`prooflens/semantic-summary@1`).

One summary, computed here from the records a build or a published audit carries, says per
paper what semantic work is recorded: how many claims there are, in explicit units; how far
each set of readings says the Lean states them (the coverage relation) and, as a separate
dimension, how that is supported (the evidence basis); the reviews, with their currency and
provenance; and the kinds of difference and open question recorded. The reader's Overview,
`check`, `build` and the sites that list audits show these counts as computed here.

It is computed from records only: it makes no verdict, score or percentage, and adds no count
to another. Each claim is counted once in each distribution of a set of readings. Nothing here
is an input to a status; the formal status counts are kept beside it with their own meaning.

Units. A claim is a statement (a numbered result, a definition, a remark), a notation record (a
statement whose kind is `notation`) or a proof step (a proof equation or a proof passage); every
count names its unit. A claim's declarations are the Lean declarations that state it: its links
(zero configuration, and a proof step's links), or its clauses' propositions and definitions (a
full assessment). A declaration linked twice to one claim counts once.

Sets of readings. `audit` holds the audit's own readings: the coverage the links file records
with a claim's links, or the inventory with a proof step's. `review:<reviewer>` holds one
reviewer's latest report of each claim, with the coverage it records with its verdict.
`workspace:<id>` holds one published workspace's submitted findings in force that record a
coverage of the whole statement; a finding on a clause or a requirement is not a reading of the
whole statement, and a claim with only those is counted as `clauses_only`. Each reviewer and
each workspace is a set of its own, never combined with another.
"""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from .util import content_id, write_json

SCHEMA = "prooflens/semantic-summary@1"
VOCABULARY = json.loads(files("prooflens").joinpath("data/semantic.json").read_text())

UNITS = ("statements", "notation", "proof_steps")
RELATIONS = ("full", "partial", "changed", "related", "unresolved")
COVERAGE_KEYS = RELATIONS + ("not_recorded", "stale", "clauses_only", "not_assessed")
BASIS_KEYS = ("direct", "reviewed_composition", "checked_bridge", "unspecified")
CURRENCY_KEYS = ("current", "unchecked", "unpinned", "stale")
REVIEW_KEYS = ("independent", "author", "informed", "stale", "unchecked", "none")
STEP_REVIEW_KEYS = ("holds", "gap", "false", "undetermined", "stale", "unreviewed")
FINDING_KEYS = ("open-question", "quantitative-difference", "input-restriction",
                "representation", "other-difference", "printed-step")
AUDIT = "audit"

# The features of a recorded difference (`estimates.FEATURES`), by finding category.
QUANTITATIVE = ("constant dependence", "derivative order", "norm", "power", "weight",
                "index offset")
INPUT = ("domain", "additional assumption", "lost case")
# Review verdicts (`review_cli.VERDICTS`) by finding category.
OTHER_VERDICTS = ("broader", "narrower", "mismatched", "vacuous", "refutation not valid")
REVIEWER_KEYS = ("id", "kind", "name", "model", "identity", "same_family_as_author")


def unit_of(row: dict, chunk: dict) -> str:
    """The unit a claim is counted in: `statements`, `notation` or `proof_steps`."""
    if (chunk.get("unit") or row.get("unit") or "statement") != "statement":
        return "proof_steps"
    return "notation" if (chunk.get("kind") or row.get("kind")) == "notation" else "statements"


def declarations(chunk: dict) -> list[str]:
    """The declarations that state a claim, each once."""
    step = chunk.get("step")
    if isinstance(step, dict):
        links = step.get("links") or []
    elif isinstance(chunk.get("links"), list):
        links = chunk["links"]
    else:
        links = [{"name": n} for cl in chunk.get("clauses") or []
                 for n in [cl.get("spec"), *(cl.get("defs") or [])]]
    return sorted({l.get("name") for l in links
                   if isinstance(l, dict) and isinstance(l.get("name"), str) and l["name"]})


def _text(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _basis(cor: dict, checked: bool) -> tuple[str | None, str | None]:
    """The basis a reading is counted with, and the one it was recorded as when that differs.
    A checked bridge counts as one only when `checked` (Lean checks it now, as the engine read
    it); otherwise it counts as the reviewer's composition."""
    basis = cor.get("basis") if cor.get("basis") in BASIS_KEYS[:3] else None
    recorded = cor.get("recorded_basis") if cor.get("recorded_basis") in BASIS_KEYS[:3] else None
    if basis == "checked_bridge" and not checked:
        return "reviewed_composition", "checked_bridge"
    return basis, recorded


def _assessment(set_id: str, coverage, basis, recorded, currency: str, **more) -> dict:
    count = "stale" if currency == "stale" else coverage if coverage in RELATIONS \
        else "not_recorded"
    out = {"set": set_id, "coverage": coverage if coverage in RELATIONS else None,
           "basis": basis if count in RELATIONS else None, "currency": currency, "count": count}
    if recorded and recorded != basis:
        out["recorded_basis"] = recorded
    out.update({k: v for k, v in more.items() if v is not None})
    return out


def audit_reading(chunk: dict) -> dict | None:
    """The audit's own reading of a claim: the coverage its links record (`correspondence`),
    or a proof step's (`step.correspondence`). A note with no coverage is no reading. A reading
    records no version of what it read, so it is `unpinned`, except a checked bridge, which is
    pinned: current while Lean checks it and its target and passage are those the auditor read,
    stale when they are not."""
    cor = chunk.get("correspondence") or (chunk.get("step") or {}).get("correspondence")
    if not isinstance(cor, dict) or cor.get("coverage") not in RELATIONS:
        return None
    bridge = cor.get("bridge") if isinstance(cor.get("bridge"), dict) else {}
    state = bridge.get("state") if cor.get("basis") == "checked_bridge" else None
    basis, recorded = _basis(cor, state in ("checked", "stale"))
    currency = {"checked": "current", "stale": "stale"}.get(state, "unpinned")
    return _assessment(AUDIT, cor["coverage"], basis, recorded, currency,
                       by=_text(cor.get("by")), question=_text(cor.get("question")))


def _latest(reports: list[dict]) -> dict[str, dict]:
    """Each reviewer's latest report (by `submitted_at`), by reviewer id."""
    out: dict[str, dict] = {}
    for r in sorted((r for r in reports if isinstance(r, dict)),
                    key=lambda r: str(r.get("submitted_at") or "")):
        rid = str((r.get("reviewer") or {}).get("id") or "unknown")
        out[rid] = r
    return out


def _provenance(r: dict) -> str:
    """`independent` when the report records that nothing of the Lean or the author's review
    had been shown to its reviewer before the reading was locked; `informed` otherwise,
    including a report that does not record it."""
    return "independent" if r.get("revealed") == [] else "informed"


def report_readings(chunk: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    """Per reviewer, the reading of their latest report of a statement (the coverage it records
    with its verdict, `correspondence`), and the reviewer's descriptor, by set id. A report that
    records no coverage is a review with no coverage recorded."""
    if (chunk.get("unit") or "statement") != "statement":
        return {}, {}
    out, sets = {}, {}
    for rid, r in _latest(chunk.get("reviews") or []).items():
        sid = f"review:{rid}"
        cor = r.get("correspondence") if isinstance(r.get("correspondence"), dict) else {}
        bridge = cor.get("bridge") if isinstance(cor.get("bridge"), dict) else {}
        basis, recorded = _basis(cor, bridge.get("state") == "checked")
        currency = {True: "current", False: "stale"}.get(r.get("current"), "unchecked")
        rv = r.get("reviewer") or {}
        out[sid] = _assessment(sid, cor.get("coverage"), basis, recorded, currency,
                               by=_text(rv.get("name")) or _text(rv.get("id")),
                               provenance=_provenance(r),
                               verdict=_text((r.get("verdict") or {}).get("value")),
                               question=_text(cor.get("question")))
        sets[sid] = {"id": sid, "kind": "review",
                     "reviewer": {k: rv[k] for k in REVIEWER_KEYS if rv.get(k) is not None}}
    return out, sets


def _statement_level(f: dict) -> bool:
    return not f.get("clause") and not f.get("requirement")


def work_readings(work: dict | None) -> tuple[dict[str, dict], dict[str, dict]]:
    """Per published workspace (`prooflens/published-work@1`), the reading of a claim: its
    latest submitted finding in force that records a coverage of the whole statement; with
    only findings on clauses or requirements, `clauses_only`. The basis is as the export
    published it: a checked bridge only while it was checked at export."""
    out, sets = {}, {}
    for rd in (work or {}).get("readings") or []:
        if not isinstance(rd, dict) or not isinstance(rd.get("workspace"), str):
            continue
        sid = f"workspace:{rd['workspace']}"
        found = [f for f in rd.get("findings") or [] if isinstance(f, dict)
                 and f.get("in_force") and f.get("coverage") in RELATIONS]
        whole = sorted((f for f in found if _statement_level(f)),
                       key=lambda f: str(f.get("submitted_at") or ""))
        rv = rd.get("reviewer") or {}
        sets[sid] = {"id": sid, "kind": "workspace", "workspace": rd["workspace"],
                     "mode": rd.get("mode") if rd.get("mode") in ("independent", "informed")
                     else None,
                     "reviewer": {k: rv[k] for k in REVIEWER_KEYS if rv.get(k) is not None}}
        by = _text(rv.get("name")) or _text(rv.get("id"))
        if whole:
            f = whole[-1]
            state = (f.get("currency") or {}).get("state")
            basis, recorded = _basis(f, True)
            out[sid] = _assessment(sid, f["coverage"], basis, recorded,
                                   state if state in ("current", "stale") else "unchecked",
                                   by=by, provenance=sets[sid]["mode"],
                                   question=_text(f.get("question")))
        elif found:
            out[sid] = {"set": sid, "coverage": None, "basis": None, "currency": None,
                        "count": "clauses_only", "clauses": len(found), "by": by,
                        "provenance": sets[sid]["mode"]}
    return out, sets


def review_state(chunk: dict, unit: str) -> str:
    """The review of a claim, in one word: for a proof step, its review as printed
    (`step.review.state`); for a statement, whether a current review of everything it needs is
    recorded, and with what provenance (`REVIEW_KEYS`). A full assessment reads it from its
    clauses' review states, zero configuration from each reviewer's latest report."""
    if unit == "proof_steps":
        state = ((chunk.get("step") or {}).get("review") or {}).get("state")
        return state if state in STEP_REVIEW_KEYS else "unreviewed"
    if isinstance(chunk.get("reviews"), list):
        latest = list(_latest(chunk["reviews"]).values())
        current = [r for r in latest if r.get("current") is True]
        if current:
            return "independent" if any(_provenance(r) == "independent" for r in current) \
                else "informed"
        if any(r.get("current") is False for r in latest):
            return "stale"
        return "unchecked" if latest else "none"
    states = []
    stale = False
    for cl in chunk.get("clauses") or []:
        states.append(cl.get("review") or ((cl.get("evidence") or {}).get("review") or {})
                      .get("state"))
        stale |= (cl.get("spec_review") or {}).get("state") == "stale" or any(
            (r or {}).get("state") == "stale" for r in (cl.get("def_reviews") or {}).values())
    if not states:
        return "none"
    if all(s in ("reviewed", "author-reviewed") for s in states):
        return "author" if "author-reviewed" in states else "independent"
    if stale:
        return "stale"
    return "unchecked" if "unknown" in states else "none"


def finding_categories(chunk: dict, readings: list[dict], work: dict | None) -> list[str]:
    """The kinds of difference and open question recorded for a claim (`FINDING_KEYS`), from
    readings that are not out of date, each reviewer's latest report that is not, a proof step's
    review and the published workspace findings in force."""
    found = set()
    for a in readings:
        if a.get("count") == "unresolved":
            found.add("open-question")
    for r in _latest(chunk.get("reviews") or []).values():
        if r.get("current") is False:
            continue
        v = (r.get("verdict") or {}).get("value")
        if v == "cannot determine":
            found.add("open-question")
        elif v == "faithful with representation choices":
            found.add("representation")
        elif v in OTHER_VERDICTS:
            found.add("other-difference")
    step = ((chunk.get("step") or {}).get("review") or {}).get("state")
    if step in ("false", "gap"):
        found.add("printed-step")
    elif step == "undetermined":
        found.add("open-question")
    for rd in (work or {}).get("readings") or []:
        for f in (rd or {}).get("findings") or []:
            if not isinstance(f, dict) or not f.get("in_force") or \
                    (f.get("currency") or {}).get("state") == "stale":
                continue
            d = f.get("difference") if isinstance(f.get("difference"), dict) else {}
            feature, outcome = d.get("feature"), d.get("outcome")
            if outcome == "open":
                found.add("open-question")
            elif feature == "representation" and outcome in ("difference", "resolved"):
                found.add("representation")
            elif outcome == "difference":
                found.add("quantitative-difference" if feature in QUANTITATIVE else
                          "input-restriction" if feature in INPUT else "other-difference")
            v = (f.get("verdict") or {}).get("value") if isinstance(f.get("verdict"), dict) \
                else f.get("verdict")
            if v in ("false as printed", "holds, with a gap in the argument"):
                found.add("printed-step")
            elif v == "cannot determine":
                found.add("open-question")
    return [k for k in FINDING_KEYS if k in found]


def claim_facts(row: dict, chunk: dict, work: dict | None = None) -> tuple[dict, dict]:
    """What the summary records of one claim (its index row's `semantic`), and the descriptors
    of the sets of readings it appears in."""
    unit = unit_of(row, chunk)
    readings, sets = {}, {}
    own = audit_reading(chunk)
    if own:
        readings[AUDIT] = own
    for got, more in (report_readings(chunk), work_readings(work)):
        readings.update(got)
        sets.update(more)
    listed = [readings[k] for k in sorted(readings, key=lambda k: (k != AUDIT, k))]
    return {"unit": unit, "declarations": len(declarations(chunk)), "readings": listed,
            "review": review_state(chunk, unit),
            "findings": finding_categories(chunk, listed, work)}, sets


def _zeros(keys) -> dict[str, int]:
    return {k: 0 for k in keys}


def _block(sets: list[str]) -> dict:
    return {
        "inventory": {u: {"records": 0, "linked": 0, "links": 0, "declarations": 0}
                      for u in UNITS} | {"proof_equations": 0, "proof_passages": 0},
        "formal": {u: {} for u in UNITS},
        "coverage": {s: {u: _zeros(COVERAGE_KEYS) for u in UNITS} for s in sets},
        "basis": {s: {u: _zeros(BASIS_KEYS) for u in UNITS} for s in sets},
        "currency": {s: {u: _zeros(CURRENCY_KEYS) for u in UNITS} for s in sets},
        "review": {"statements": _zeros(REVIEW_KEYS), "notation": _zeros(REVIEW_KEYS),
                   "proof_steps": _zeros(STEP_REVIEW_KEYS)},
        "findings": {u: _zeros(FINDING_KEYS) for u in UNITS}}


def summarise(index: dict, chunks: dict[str, dict], works: dict[str, dict] | None = None,
              author: str | None = None) -> tuple[dict, dict[str, dict]]:
    """The summary of `index` (its claims, with their records `chunks` by file and the published
    workspace records `works` by claim id), and each claim's facts, by claim id."""
    works = works or {}
    facts, sets, names = {}, {}, {}
    for row in index.get("claims") or []:
        chunk = chunks.get(row.get("file")) or {}
        f, more = claim_facts(row, chunk, works.get(row["id"]))
        facts[row["id"]] = f
        sets.update(more)
        names[row["id"]] = declarations(chunk)
    by = sorted({a["by"] for f in facts.values() for a in f["readings"]
                 if a["set"] == AUDIT and a.get("by")})
    order = [AUDIT] + sorted(k for k in sets if k.startswith("review:")) + \
        sorted(k for k in sets if k.startswith("workspace:"))
    papers = {}
    linked: dict[tuple[str, str], set[str]] = {}
    for row in index.get("claims") or []:
        f = facts[row["id"]]
        unit = f["unit"]
        p = papers.setdefault(row["paper"], _block(order))
        inv = p["inventory"][unit]
        inv["records"] += 1
        inv["linked"] += bool(f["declarations"])
        inv["links"] += f["declarations"]
        linked.setdefault((row["paper"], unit), set()).update(names[row["id"]])
        if unit == "proof_steps":
            kind = (chunks.get(row.get("file")) or {}).get("unit") or row.get("unit")
            p["inventory"]["proof_passages" if kind == "proof-passage" else "proof_equations"] += 1
        code = row.get("status_code") or "unknown"
        p["formal"][unit][code] = p["formal"][unit].get(code, 0) + 1
        mine = {a["set"]: a for a in f["readings"]}
        for s in order:
            a = mine.get(s)
            p["coverage"][s][unit][a["count"] if a else "not_assessed"] += 1
            if a and a["count"] in RELATIONS:
                p["basis"][s][unit][a["basis"] or "unspecified"] += 1
            if a and a.get("currency"):
                p["currency"][s][unit][a["currency"]] += 1
        p["review"][unit][f["review"]] += 1
        for k in f["findings"]:
            p["findings"][unit][k] += 1
    for (pid, unit), decls in linked.items():
        papers[pid]["inventory"][unit]["declarations"] = len(decls)
    shown = {p["id"]: p for p in index.get("papers") or []}
    for pid, p in papers.items():
        ver = (shown.get(pid) or {}).get("paper_version") or {}
        p["revision"] = (shown.get(pid) or {}).get("revision")
        p["paper_version"] = ver.get("id") if isinstance(ver, dict) else None
    project = index.get("project") or {}
    out = {"schema": SCHEMA,
           "audit": {"author": author, "release": index.get("release"),
                     "evidence": index.get("evidence"),
                     "project": {"repository": project.get("repository"),
                                 "commit": project.get("commit")}},
           "selected": AUDIT,
           "sets": [{"id": AUDIT, "kind": "audit", "by": by}] + [sets[k] for k in order[1:]],
           "papers": papers}
    out["digest"] = content_id({"summary": out, "claims": facts})
    return out, facts


def apply(index: dict, chunks: dict[str, dict], works: dict[str, dict] | None = None,
          author: str | None = None) -> dict:
    """Set the index's `semantic` summary and each claim row's `semantic` facts; returns the
    summary."""
    summary, facts = summarise(index, chunks, works, author)
    for row in index.get("claims") or []:
        row["semantic"] = facts[row["id"]]
    index["semantic"] = summary
    return summary


def of_view(body: dict, root: Path | None = None) -> tuple[dict, dict[str, dict]]:
    """The summary of a zero-configuration view, and each claim's facts, as the site
    `simple.write_view_site` writes would give them, without writing it (for `check`): the same
    claims, with the records the summary reads. `root` is the Lean project, for its repository."""
    from . import simple, steps
    rows, chunks = [], {}
    for c in body["claims"]:
        unit = steps.unit_of(c)
        links = [{"name": l["name"]} for l in c.get("links") or []]
        chunk = {"unit": unit, "kind": c.get("kind", ""), "links": links,
                 "correspondence": c.get("correspondence"), "reviews": c.get("reviews", []),
                 "clauses": []}
        if steps.is_step(c):
            chunk["step"] = {"links": links, "correspondence": c.get("correspondence"),
                             "review": steps.review(c.get("step_reports", []),
                                                    c.get("source_sha256"))}
        rows.append({"id": c["id"], "paper": c["paper"], "file": c["id"], "unit": unit,
                     "kind": c.get("kind", ""), "status_code": c["status_code"]})
        chunks[c["id"]] = chunk
    index = {"release": simple.view_release(body), "evidence": content_id(body),
             "project": {"commit": body.get("commit"),
                         **simple.source_info(root, body["project"]["libs"])},
             "papers": [{"id": c, "revision": body.get("commit"), **simple._paper_version(body)}
                        for c in sorted({c["paper"] for c in body["claims"]})],
             "claims": rows}
    return summarise(index, chunks, author=body.get("author"))


def refresh(data: Path, author: str | None = None) -> dict:
    """Compute the summary again over the reader data at `data` as it is written (its index, the
    claim records and the workspace records they name), and write it into `data/index.json`. A
    published audit's summary is thus computed from exactly the records it publishes."""
    path = data / "index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    chunks, works = {}, {}
    for row in index.get("claims") or []:
        f = data / "claims" / row["file"]
        chunk = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        chunks[row["file"]] = chunk
        w = chunk.get("work")
        wf = data / w if isinstance(w, str) and w.startswith("work/") and \
            ".." not in Path(w).parts else None
        if wf is not None and wf.is_file():
            doc = json.loads(wf.read_text(encoding="utf-8"))
            if doc.get("schema") == "prooflens/published-work@1" and doc.get("claim") == row["id"]:
                works[row["id"]] = doc
    summary = apply(index, chunks, works,
                    author if author is not None else (index.get("semantic") or {})
                    .get("audit", {}).get("author"))
    write_json(path, index, indent=None)
    return summary


# -- words for the terminal ---------------------------------------------------------------------

def _n(n: int, unit: str) -> str:
    w = VOCABULARY["units"][unit]
    return f"{n} {w['one'] if n == 1 else w['many']}"


def _counts(table: dict[str, int], words: dict) -> str:
    return "; ".join(f"{words[k]['label'][0].lower() + words[k]['label'][1:]} ({n})"
                     for k, n in table.items() if n)


def text(summary: dict | None) -> list[str]:
    """A short account of the summary for `check` and `build`: per paper and unit, how many
    claims there are and how many are linked, and the coverage and basis of the audit's own
    readings, the reviews and the findings recorded. Plain counts, each with its unit."""
    if not summary:
        return []
    v = VOCABULARY
    lines = []
    others = [s for s in summary.get("sets") or [] if s["id"] != AUDIT]
    for pid, p in (summary.get("papers") or {}).items():
        lines.append(f"semantic summary of paper {pid} (the audit's readings):")
        inv = p["inventory"]
        for u in UNITS:
            row = inv[u]
            if not row["records"]:
                continue
            decls = row["declarations"]
            lines.append(f"  {_n(row['records'], u)}, {row['linked']} linked"
                         + (f" to {decls} declaration{'' if decls == 1 else 's'}"
                            if decls else ""))
            lines.append("    correspondence: " + _counts(p["coverage"][AUDIT][u], v["coverage"]))
            basis = _counts(p["basis"][AUDIT][u], v["basis"])
            if basis:
                lines.append("    basis: " + basis)
            words = v["step_review"] if u == "proof_steps" else v["review"]
            lines.append("    reviews: " + _counts(p["review"][u], words))
            found = _counts(p["findings"][u], v["findings"])
            if found:
                lines.append("    findings: " + found)
    if others:
        lines.append(f"  {len(others)} further set{'' if len(others) == 1 else 's'} of readings "
                     "(one per reviewer and per workspace) "
                     f"{'is' if len(others) == 1 else 'are'} counted apart: see "
                     "`check --json` or the reader's Overview")
    return lines
