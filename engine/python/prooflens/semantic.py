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

Findings in force. Every submitted finding in force of the auditors' workspaces (on the whole
statement, a clause or a requirement) is counted once, by whether it is current for this build,
due for review (a part it rests on changed since it was submitted) or not known to be current
(`finding_currency`). A finding that a version map kept to the build's release judges is in the
state that map gives it, as the Changes view shows it. A published audit counts the findings it
publishes, as the export checked them (and the maps it publishes, `revisions`); a build counts
those of the workspaces in its working directory, against its own site data
(`workspace_findings`).

Clause readings. A workspace's latest submitted finding in force on each clause or requirement
of a claim, with a coverage, is a reading of that part (`clause_readings`), counted apart from
the readings of the whole statement: per set and unit, how many claims have a part read so
(`clause_coverage`). Each names the declaration of the comparison it concerns, when the records
say: the clause's proposition, or what the requirement is aligned with.

Withheld. A published audit says what its publication settings withhold: per paper, which of
the paper's text, its Lean and its review texts are not published (`withheld`), and on a
reading, the parts of it the export left out (a question's words), so that the reader says
"withheld" where it would otherwise show nothing.
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
# A finding in force by its currency: `current`, `due` for review (a workspace record's `stale`),
# `unchecked` (not known to be current).
FINDING_STATES = ("current", "due", "unchecked")
AUDIT = "audit"
# A part of a claim read by a workspace: its coverage, or out of date.
CLAUSE_KEYS = RELATIONS + ("stale",)
# What a paper's publication settings may withhold (`config.Publish`).
WITHHOLDS = ("source_text", "lean", "reviews")

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
                                   question=_text(f.get("question")),
                                   withheld=_withheld(f))
        elif found:
            out[sid] = {"set": sid, "coverage": None, "basis": None, "currency": None,
                        "count": "clauses_only", "clauses": len(found),
                        **{k: v for k, v in (("by", by), ("provenance", sets[sid]["mode"]))
                           if v is not None}}
    return out, sets


def _withheld(f: dict) -> list[str] | None:
    """The parts of a reading a published finding records as withheld by its paper's
    publication settings (`published_work`): its question's words."""
    gone = f.get("withheld") if isinstance(f.get("withheld"), list) else []
    out = [k for k in ("question",) if k in gone]
    return out or None


def _part_decl(f: dict, chunk: dict, rd: dict) -> str | None:
    """The declaration of the comparison a finding on a part of a claim concerns: the target of
    an alignment of the requirement it names, else the proposition (or first definition) of the
    clause it names; None when the records do not say."""
    if f.get("requirement"):
        for a in rd.get("alignments") or []:
            if isinstance(a, dict) and f["requirement"] in (a.get("requirements") or []):
                for t in a.get("lean") or []:
                    if isinstance(t, dict) and isinstance(t.get("decl"), str):
                        return t["decl"]
    if f.get("clause"):
        for cl in chunk.get("clauses") or []:
            if isinstance(cl, dict) and cl.get("name") == f["clause"]:
                name = cl.get("spec") or next(iter(cl.get("defs") or []), None)
                return name if isinstance(name, str) else None
    return None


def clause_readings(chunk: dict, work: dict | None) -> list[dict]:
    """Each published workspace's readings of parts of a claim: per clause or requirement its
    findings name, the latest submitted finding in force with a coverage. Each is `{set, clause
    or requirement, coverage, basis, currency, count, decl}`: `count` is its coverage, or
    `stale` when what it rests on changed; `decl` the declaration of the comparison it concerns
    (`_part_decl`), or null."""
    out = []
    for rd in (work or {}).get("readings") or []:
        if not isinstance(rd, dict) or not isinstance(rd.get("workspace"), str):
            continue
        sid = f"workspace:{rd['workspace']}"
        latest: dict[tuple, dict] = {}
        for f in sorted((f for f in rd.get("findings") or [] if isinstance(f, dict)
                         and f.get("in_force") and f.get("coverage") in RELATIONS
                         and not _statement_level(f)),
                        key=lambda f: str(f.get("submitted_at") or "")):
            latest[("requirement", f["requirement"]) if f.get("requirement")
                   else ("clause", f["clause"])] = f
        for (kind, name), f in sorted(latest.items()):
            state = (f.get("currency") or {}).get("state")
            currency = state if state in ("current", "stale") else "unchecked"
            basis, _ = _basis(f, True)
            out.append({"set": sid, kind: name, "coverage": f["coverage"], "basis": basis,
                        "currency": currency,
                        "count": "stale" if currency == "stale" else f["coverage"],
                        "decl": _part_decl(f, chunk, rd)})
    return out


def clause_facts(facts: dict, chunk: dict, work: dict | None) -> None:
    """Add to a claim's facts its clause readings (`clause_readings`), when it has any."""
    parts = clause_readings(chunk, work)
    if parts:
        facts["clause_readings"] = parts


def clause_counts(papers: dict, index: dict, facts: dict[str, dict], order: list[str]) -> None:
    """Per paper, set and unit, how many claims have a part read under each of `CLAUSE_KEYS`
    (`clause_coverage`): a claim with several parts read so is counted once, and a claim may be
    counted under several keys, so these are never added. Absent when no claim has a part read."""
    for row in index.get("claims") or []:
        f = facts[row["id"]]
        parts = f.get("clause_readings") or []
        if not parts:
            continue
        table = papers[row["paper"]].setdefault(
            "clause_coverage", {s: {u: _zeros(CLAUSE_KEYS) for u in UNITS} for s in order})
        for s in order:
            for k in sorted({x["count"] for x in parts if x["set"] == s}):
                table[s][f["unit"]][k] += 1


def withhold(summary: dict, facts: dict[str, dict], withheld: dict[str, list[str]]) -> None:
    """Record in a published summary what each paper's publication settings withhold
    (`withheld`: `source_text`, `lean`, `reviews`), and compute its digest again."""
    for pid, what in (withheld or {}).items():
        what = [k for k in WITHHOLDS if k in (what or [])]
        if what and pid in summary["papers"]:
            summary["papers"][pid]["withheld"] = what
    summary["digest"] = content_id({"summary": {k: v for k, v in summary.items()
                                                if k not in ("audit", "digest")},
                                    "claims": facts})


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
    review and the published workspace findings in force. A difference recorded as resolved
    counts as a difference while its resolution does not hold as published."""
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
            if outcome == "resolved" and (d.get("partial") or (d.get("bridge_check") or {})
                                          .get("state", "checked") != "checked"):
                # Its resolution does not hold as published: a checked bridge not checked at
                # export, or conditions it leaves open (`published_work._difference`).
                outcome = "difference"
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


def finding_state(currency: str | None) -> str:
    """A finding in force by its currency (`FINDING_STATES`): `current` only when its currency
    is; `due` for review when a part it rests on changed (`stale`); otherwise not known to be
    current (`unchecked`)."""
    return {"current": "current", "stale": "due"}.get(currency, "unchecked")


# A version map's judgement of a finding (`reopen.STATES`) as a state of `FINDING_STATES`, and
# which of two judgements is the less current.
MAP_STATE = {"reopened": "due", "unchecked": "unchecked", "current": "current"}
RANK = {"due": 0, "unchecked": 1, "current": 2}


def _judge(out: dict[str, str], fid, state) -> None:
    """Record a map's judgement `state` of the finding `fid` in `out`, keeping the less current
    when another map judged it too."""
    s = MAP_STATE.get(state, "unchecked")
    if fid not in out or RANK[s] < RANK[out[fid]]:
        out[fid] = s


def published_findings(work: dict | None, release: str | None = None) -> list[str]:
    """The state of each submitted finding in force of a claim's published workspace records
    (`prooflens/published-work@1`): the state a version map kept to the published `release`
    gives it (`revisions`), as the Changes view shows it, when one judges it; otherwise its
    currency as the export checked it."""
    out = []
    for rd in (work or {}).get("readings") or []:
        if not isinstance(rd, dict):
            continue
        judged: dict[str, str] = {}
        for rev in rd.get("revisions") or []:
            to = ((rev or {}).get("map") or {}).get("to") or {}
            if release is not None and to.get("release") == release:
                for f in rev.get("findings") or []:
                    if isinstance(f, dict):
                        _judge(judged, f.get("id"), f.get("state"))
        out += [judged.get(f.get("id")) or finding_state((f.get("currency") or {}).get("state"))
                for f in rd.get("findings") or [] if isinstance(f, dict) and f.get("in_force")]
    return out


def finding_currency(states: list[str]) -> dict[str, int]:
    """How many of a claim's findings in force are in each state."""
    return {k: sum(1 for s in states if s == k) for k in FINDING_STATES}


def _submitted(spaces) -> bool:
    return any(r.get("kind") == "finding" and r.get("state") == "submitted"
               for _, ws in spaces for r in (ws.get("records") or {}).values())


def has_findings(work_dir: Path | None) -> bool:
    """Whether a workspace in `work_dir` has a submitted finding."""
    from . import workspace as wsp
    return work_dir is not None and _submitted(wsp.list_all(work_dir))


def workspace_findings(work_dir: Path | None, data: Path,
                       root: Path | None = None) -> dict[str, list[str]]:
    """Per claim of the build whose site data is `data`, the state of each submitted finding in
    force that the workspaces in `work_dir` record: the findings an export of this build would
    publish (`published_work.accepted`). A finding that a version map the workspace keeps to
    this build's release judges is in the state that map gives it, as the Changes view shows it
    (`reopen.for_site`: due for review when the revision or this build changed a part it rests
    on); any other is checked against this build as `workspace show` checks it
    (`workspace.currency`). Lean is not asked: a fact inside a proof is read from the facts store
    of the project at `root`, and is not known to be current when it is not there. A finding on
    a claim this build does not have is not counted, as an export does not publish it."""
    from . import workspace as wsp
    spaces = wsp.list_all(work_dir) if work_dir is not None else []
    if not _submitted(spaces):
        return {}
    from .published_work import accepted
    from .targets import Snapshot, TargetError
    try:
        snap = Snapshot(data)
    except TargetError:
        return {}
    claims = {c["id"] for c in snap.claims}
    out: dict[str, list[str]] = {}
    for _, ws in spaces:
        kept = {rid: r for rid, r in accepted(ws).items() if r.get("claim") in claims}
        if not any(r.get("kind") == "finding" for r in kept.values()):
            continue
        cur = wsp.currency({"records": kept}, snap, root, check_facts=False)
        judged = _judged_by_maps(ws, kept, snap, root)
        for f in wsp.current_findings({"records": kept}):
            out.setdefault(f["claim"], []).append(
                judged.get(f["id"]) or finding_state((cur.get(f["id"]) or {}).get("state")))
    return out


def _judged_by_maps(ws: dict, kept: dict, snap, root: Path | None) -> dict[str, str]:
    """The state (`FINDING_STATES`) that the version maps `ws` keeps to the release of `snap`
    give each finding of `kept` they judge; when two judge one, the less current state."""
    if not ws.get("version_maps"):
        return {}
    from .reopen import for_site
    out: dict[str, str] = {}
    try:
        doc = for_site({"id": ws.get("id"), "records": kept,
                        "version_maps": ws["version_maps"]}, snap, root)
    except (KeyError, TypeError, ValueError):
        # A kept map that cannot be read judges nothing, so no finding is known to be current.
        return {r["id"]: "unchecked" for r in kept.values() if r.get("kind") == "finding"}
    for m in doc.get("maps") or []:
        for f in m.get("findings") or []:
            _judge(out, f.get("id"), f.get("state"))
    return out


def claim_facts(row: dict, chunk: dict, work: dict | None = None,
                found: list[str] | None = None, release: str | None = None
                ) -> tuple[dict, dict]:
    """What the summary records of one claim (its index row's `semantic`), and the descriptors
    of the sets of readings it appears in. `found` is the state of each finding in force of the
    claim when they come from the working directory's workspaces (`workspace_findings`);
    otherwise they are the published ones `work` holds, judged for `release`."""
    unit = unit_of(row, chunk)
    readings, sets = {}, {}
    own = audit_reading(chunk)
    if own:
        readings[AUDIT] = own
    for got, more in (report_readings(chunk), work_readings(work)):
        readings.update(got)
        sets.update(more)
    listed = [readings[k] for k in sorted(readings, key=lambda k: (k != AUDIT, k))]
    out = {"unit": unit, "declarations": len(declarations(chunk)), "readings": listed,
           "review": review_state(chunk, unit),
           "findings": finding_categories(chunk, listed, work)}
    states = (found or []) + published_findings(work, release)
    if states:
        out["finding_currency"] = finding_currency(states)
    return out, sets


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
        "findings": {u: _zeros(FINDING_KEYS) for u in UNITS},
        "finding_currency": {u: _zeros(FINDING_STATES) for u in UNITS}}


def summarise(index: dict, chunks: dict[str, dict], works: dict[str, dict] | None = None,
              author: str | None = None, found: dict[str, list[str]] | None = None
              ) -> tuple[dict, dict[str, dict]]:
    """The summary of `index` (its claims, with their records `chunks` by file and the published
    workspace records `works` by claim id), and each claim's facts, by claim id. `found` holds,
    by claim id, the state of each finding in force of the working directory's workspaces
    (`workspace_findings`), for a build that publishes none."""
    works, found = works or {}, found or {}
    facts, sets, names = {}, {}, {}
    for row in index.get("claims") or []:
        chunk = chunks.get(row.get("file")) or {}
        f, more = claim_facts(row, chunk, works.get(row["id"]), found.get(row["id"]),
                              index.get("release"))
        facts[row["id"]] = f
        sets.update(more)
        names[row["id"]] = declarations(chunk)
        clause_facts(f, chunk, works.get(row["id"]))
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
        for k, n in (f.get("finding_currency") or {}).items():
            p["finding_currency"][unit][k] += n
    for (pid, unit), decls in linked.items():
        papers[pid]["inventory"][unit]["declarations"] = len(decls)
    clause_counts(papers, index, facts, order)
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
    # The digest is of what the summary counts, not of the audit's identity: two builds of the
    # same records have the same digest, and a change to a reading changes it.
    out["digest"] = content_id({"summary": {k: v for k, v in out.items() if k != "audit"},
                                "claims": facts})
    return out, facts


def apply(index: dict, chunks: dict[str, dict], works: dict[str, dict] | None = None,
          author: str | None = None, found: dict[str, list[str]] | None = None) -> dict:
    """Set the index's `semantic` summary and each claim row's `semantic` facts; returns the
    summary."""
    summary, facts = summarise(index, chunks, works, author, found)
    for row in index.get("claims") or []:
        row["semantic"] = facts[row["id"]]
    index["semantic"] = summary
    return summary


def of_view(body: dict, root: Path | None = None,
            found: dict[str, list[str]] | None = None) -> tuple[dict, dict[str, dict]]:
    """The summary of a zero-configuration view, and each claim's facts, as the site
    `simple.write_view_site` writes would give them, without writing it (for `check`): the same
    claims, with the records the summary reads. `root` is the Lean project, for its repository;
    `found`, the findings in force of the working directory's workspaces
    (`workspace_findings`)."""
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
        rows.append({"id": c["id"], "paper": c.get("paper", "P"), "file": c["id"],
                     "unit": unit, "kind": c.get("kind", ""), "status_code": c["status_code"]})
        chunks[c["id"]] = chunk
    index = {"release": simple.view_release(body), "evidence": content_id(body),
             "project": {"commit": body.get("commit"),
                         **simple.source_info(root, (body.get("project") or {}).get("libs")
                                              or [])},
             "papers": [{"id": p, "revision": body.get("commit"), **simple._paper_version(body)}
                        for p in sorted({r["paper"] for r in rows})],
             "claims": rows}
    return summarise(index, chunks, author=body.get("author"), found=found)


def refresh(data: Path, author: str | None = None,
            withheld: dict[str, list[str]] | None = None) -> dict:
    """Compute the summary again over the reader data at `data` as it is written (its index, the
    claim records and the workspace records they name), and write it into `data/index.json`. A
    published audit's summary is thus computed from exactly the records it publishes. `withheld`
    names, per paper, what its publication settings withhold (`withhold`)."""
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
    if withheld:
        withhold(summary, {r["id"]: r["semantic"] for r in index.get("claims") or []}, withheld)
    write_json(path, index, indent=None)
    return summary


# -- the words for a reading -------------------------------------------------------------------
#
# A reading's coverage and basis have one set of words, `data/semantic.json`'s: the terminal, the
# reader (`web/src/lib/coverage.js`) and this summary all take them from there.

def label(dimension: str, key) -> str | None:
    """The words for `key` of `dimension` (`coverage`, `basis`, `bridge`, ...), or None for a
    value the vocabulary does not name."""
    row = (VOCABULARY.get(dimension) or {}).get(key) if isinstance(key, str) else None
    return row["label"] if row else None


def in_text(words: str | None) -> str | None:
    """Words as they read inside a sentence: the first letter in lower case."""
    return words[0].lower() + words[1:] if words else words


def basis_words(basis, bridge: str | None = None) -> str | None:
    """The words for a basis. A checked bridge whose state (`bridge`) is `stale` or `unchecked`
    reads as that state; with no state given, it reads as recorded."""
    if basis == "checked_bridge" and bridge in ("stale", "unchecked"):
        return label("bridge", bridge)
    return label("basis", basis) if basis in BASIS_KEYS[:3] else None


def reading_words(coverage, basis=None, bridge: str | None = None) -> str | None:
    """A reading's coverage and basis in words: "Part of the claim, in one Lean statement". None
    for a coverage the vocabulary does not name."""
    head = label("coverage", coverage) if coverage in RELATIONS else None
    how = basis_words(basis, bridge)
    return f"{head}, {in_text(how)}" if head and how else head


# -- words for the terminal ---------------------------------------------------------------------

def _n(n: int, unit: str) -> str:
    w = VOCABULARY["units"][unit]
    return f"{n} {w['one'] if n == 1 else w['many']}"


def _counts(table: dict[str, int], words: dict) -> str:
    return "; ".join(f"{in_text(words[k]['label'])} ({n})" for k, n in table.items() if n)


def currency_text(table: dict[str, int] | None) -> str | None:
    """The findings in force of one unit by their currency, counted in findings: "findings in
    force: 3 current; 1 due for review"; None when there are none."""
    words, table = VOCABULARY["finding_currency"], table or {}
    parts = [f"{table[k]} {in_text(words[k]['label'])}" for k in FINDING_STATES
             if isinstance(table.get(k), int) and table[k] > 0]
    return "findings in force: " + "; ".join(parts) if parts else None


def text(summary: dict | None) -> list[str]:
    """A short account of the summary for `check` and `build`: per paper and unit, how many
    claims there are and how many are linked, and the coverage and basis of the audit's own
    readings, the reviews, the findings recorded and the findings in force by their currency.
    Plain counts, each with its unit."""
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
            line = currency_text((p.get("finding_currency") or {}).get(u))
            if line:
                lines.append("    " + line)
    if others:
        lines.append(f"  {len(others)} further set{'' if len(others) == 1 else 's'} of readings "
                     "(one per reviewer and per workspace) "
                     f"{'is' if len(others) == 1 else 'are'} counted apart: see "
                     "`check --json` or the reader's Overview")
    return lines
