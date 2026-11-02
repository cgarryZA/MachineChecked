"""The review queue: what a reviewer can review, in a suggested order.

A unit of review is a locked proposition (`spec`), a definition its meaning depends on (`def`), in
the zero-configuration view a confirmed link between a claim and a declaration (`link`), or, in
both, a proof step (`step`: an equation or passage of a printed proof, reviewed as printed whether
or not any Lean is linked to it). Each unit carries the fingerprints it would be reviewed at, the
digests of the paper passages a review of it reads, by claim (`source_sha256`,
`review_sources.py`), its current review state, the author's review (shown to the reviewer only
after their own verdict) and why it sits where it does in the order. A unit is reviewed once per
fingerprint, however many claims depend on it.

The order is a suggestion: less effort first, with a preference for units that many claims depend
on. Reviewing a definition settles that definition only; no claim is approved by it. Once the
units are built, `prioritise` puts first the units whose evidence changed since the last release
and those whose Lean another claim's proof uses, from the build's own records, and says why each
comes where it does (see "The investigation order" below).

A unit also says what reviewing it shows of other units (`reveals`): the Lean of the definitions
a statement uses (its phase 2), and the author's review it shares with other units (its phase 3,
when one review section ends with several markers). A reviewer who has seen a unit's material
before writing their reading of it is no longer blind to it. The order puts a revealed unit
before the one that reveals it where it can; when two units reveal each other (a joint review)
one of them cannot be blind, and the report of the later one records it.
"""

from __future__ import annotations

import copy
import math
import re

SCHEMA = "prooflens/review-queue@1"


def section_of(number: str) -> str:
    """The section a claim sits in, from its printed number: `Theorem 3.1`, `(4.2)`, `§8.1.3` and
    `App A.3` give `3`, `4`, `8` and `A`."""
    m = re.search(r"(?:App(?:endix)?\.?\s*|§\s*|\(|\b)([A-Z]|\d+)(?=[.\d)])", number or "")
    if m:
        return m.group(1)
    m = re.search(r"\b([A-Z]|\d+)\b", number or "")
    return m.group(1) if m else "—"


def _text(seg) -> str:
    return (seg or {}).get("text", "") if isinstance(seg, dict) else str(seg or "")


def _effort_spec(st: dict, unreviewed: int) -> float:
    binders = len(st.get("binders") or [])
    size = len(_text(st.get("conclusion"))) + sum(len(_text(b.get("type")))
                                                 for b in st.get("binders") or [])
    return binders + size / 200 + unreviewed / 4


def _effort_def(rec: dict) -> float:
    return 1 + len(_text(rec.get("signature"))) / 150 + (2 if rec.get("value") else 0)


def _size(effort: float) -> str:
    return "Short" if effort < 4 else "Medium" if effort < 10 else "Long"


def _author_text(review: dict | None) -> list[dict]:
    return [{"by": r.get("by"), "text": r.get("text", ""), "file": r.get("file"),
             "line": r.get("line")} for r in (review or {}).get("current", [])]


def _author_groups(units: list[dict]) -> dict[str, list[str]]:
    """For each unit, the other units whose author review is the same review (same file and
    text): one section closed by several markers."""
    by: dict[tuple, list[str]] = {}
    for u in units:
        for r in u.get("author_review") or []:
            if (r.get("text") or "").strip():
                by.setdefault((r.get("file"), r["text"]), []).append(u["id"])
    out: dict[str, list[str]] = {}
    for ids in by.values():
        for i in ids:
            out.setdefault(i, [])
            out[i] += [j for j in ids if j != i and j not in out[i]]
    return out


def reveal_order(units: list[dict]) -> list[dict]:
    """`units` (already in their suggested order) reordered so that a unit another one reveals
    comes first, keeping the suggested order otherwise. A unit revealing each other (a joint
    review) cannot both come first; such pairs keep their suggested order."""
    pos = {u["id"]: i for i, u in enumerate(units)}
    before: dict[str, set] = {u["id"]: set() for u in units}
    for u in units:
        r = u.get("reveals") or {}
        for v in set(r.get("lean", [])) | set(r.get("author", [])):
            back = units[pos[v]].get("reveals") or {} if v in pos else {}
            if v in pos and u["id"] not in set(back.get("lean", [])) | set(back.get("author", [])):
                before[u["id"]].add(v)
    out, done = [], set()
    pending = list(units)
    while pending:
        # The first unit in suggested order whose revealed units are all placed; if none (a
        # cycle the pairs above did not catch), the first one.
        nxt = next((u for u in pending if before[u["id"]] <= done), pending[0])
        pending.remove(nxt)
        out.append(nxt)
        done.add(nxt["id"])
    return out


def assurance_queue(index: dict, chunks: dict, store: dict, authors: list[str]) -> dict:
    """The queue of a full assessment: every locked proposition with a statement, and every
    definition in their closures."""
    paper_of = {c["id"]: c["paper"] for c in index["claims"]}
    by_name = {r["name"]: r for r in store.values()}
    keys = {r["name"]: k for k, r in store.items()}
    used_by: dict[str, set] = {}
    specs: dict[str, dict] = {}
    unspecified = []
    for c in index["claims"]:
        ch = chunks[c["file"]]
        if c["class"] == "unspecified":
            unspecified.append({"id": c["id"], "paper": c["paper"], "number": c["number"]})
        for n in ch.get("decls", {}):
            used_by.setdefault(n, set()).add(c["id"])
        for cl in ch.get("clauses", []):
            st = cl.get("statement")
            if not cl.get("spec") or not st:
                continue
            u = specs.setdefault(cl["spec"], {
                "id": "spec:" + cl["spec"], "kind": "spec", "name": cl["spec"],
                "paper": c["paper"], "papers": [c["paper"]],
                "section": section_of(c["number"]), "claims": [], "clauses": [],
                "legacy_hash": st.get("legacy_hash"), "fingerprint": st.get("fingerprint"),
                "source_sha256": (cl.get("spec_review") or {}).get("source_sha256") or {},
                "state": (cl.get("spec_review") or {}).get("state", "pending"),
                "author_review": _author_text(cl.get("spec_review")),
                "witness": cl.get("witness"), "refute": cl.get("refute"),
                "closure": list(st.get("closure") or []),
                "unreviewed": sum(1 for r in (cl.get("def_reviews") or {}).values()
                                  if r["state"] != "reviewed"),
                "effort": 0.0})
            u["claims"].append({"id": c["id"], "number": c["number"], "title": c["title"],
                                "file": c["file"], "status": c["status"]})
            u["clauses"].append(cl["name"])
            u["effort"] = round(_effort_spec(st, u["unreviewed"]), 2)
    units = list(specs.values())
    for u in units:
        u["reason"] = (f"{_size(u['effort'])} statement"
                       + (f"; its meaning uses {u['unreviewed']} definition(s) not yet "
                          "independently reviewed" if u["unreviewed"] else ""))
    for name, rec in sorted(by_name.items()):
        if rec.get("review") is None:
            continue
        users = sorted(used_by.get(name, ()))
        effort = round(_effort_def(rec), 2)
        units.append({
            "id": "def:" + name, "kind": "def", "name": name, "key": keys.get(name),
            "paper": None, "papers": sorted({paper_of[i] for i in users}),
            "section": rec.get("module", "").rsplit(".", 1)[0] or "—",
            "claims": [{"id": i} for i in users], "legacy_hash": rec.get("legacy_hash"),
            "fingerprint": rec.get("fingerprint"),
            "source_sha256": rec["review"].get("source_sha256") or {},
            "state": rec["review"]["state"],
            "author_review": _author_text(rec["review"]), "effort": effort,
            "reason": f"{_size(effort)} definition; used by {len(users)} claim(s)"})
    for u in units:
        u["order"] = round(u["effort"] - math.log2(1 + len(u["claims"])), 3)
    ids = {u["id"] for u in units}
    shared = _author_groups(units)
    for u in units:
        u["reveals"] = {"lean": sorted({"def:" + n for n in u.pop("closure", [])} & ids - {u["id"]}),
                        "author": sorted(shared.get(u["id"], []))}
    units.sort(key=lambda u: (u["state"] == "reviewed", u["order"], u["id"]))
    units = reveal_order([u for u in units if u["state"] != "reviewed"]) + \
        [u for u in units if u["state"] == "reviewed"]
    return {"schema": SCHEMA, "release": index["release"], "mode": "assurance",
            "authors": sorted(authors), "units": with_steps(units, step_units(index, chunks)),
            "needs_statement": unspecified}


def with_steps(units: list[dict], steps: list[dict]) -> list[dict]:
    """The queue's units with the proof steps after the other open units, and every reviewed
    unit last."""
    return ([u for u in units if u["state"] != "reviewed"]
            + [u for u in steps if u["state"] != "reviewed"]
            + [u for u in units if u["state"] == "reviewed"]
            + [u for u in steps if u["state"] == "reviewed"])


def step_units(index: dict, chunks: dict) -> list[dict]:
    """One unit per proof step: is the printed step valid, and what does the Lean linked to it
    (if any) state? Its fingerprints are those of its source text (`source`) and of the linked
    declarations, so a report is made at, and current for, exactly that text. The parent's scope
    decision and coverage play no part: a step no report covers is pending."""
    units = []
    for c in index["claims"]:
        ch = chunks[c["file"]]
        st = ch.get("step")
        if not st:
            continue
        links = st.get("links") or []
        route = (st.get("route") or {}).get("links") or []
        parent = st.get("parent") or {}
        fps = {"source": ch.get("source_sha256")}
        fps.update({l["name"]: l.get("fingerprint") for l in links + route})
        units.append({
            "id": "step:" + c["id"], "kind": "step", "unit": st.get("unit"), "key": ch.get("key"),
            "name": c["number"] or c["id"], "lean": [l["name"] for l in links],
            "route": [l["name"] for l in route], "fingerprints": fps,
            "source_sha256": {c["id"]: ch["source_sha256"]} if ch.get("source_sha256") else {},
            "parent": {k: parent.get(k) for k in ("id", "number")} if parent else None,
            "paper": c["paper"], "papers": [c["paper"]],
            "section": section_of(parent.get("number") or c["number"]),
            "claims": [{"id": c["id"], "number": c["number"], "title": c["title"],
                        "file": c["file"], "status": c["status"]}],
            "state": "reviewed" if (st.get("review") or {}).get("state") not in
            ("unreviewed", "stale", None) else "pending",
            "author_review": [], "reveals": {"lean": [], "author": []},
            "effort": 1.0, "order": 1.0,
            "reason": ("Proof step of " + parent["number"] if parent.get("number")
                       else "Proof step") + ("; no Lean is linked to it" if not links else "")})
    units.sort(key=lambda u: (u["state"] == "reviewed", u["id"]))
    return units


def simple_queue(index: dict, chunks: dict) -> dict:
    """The queue of the zero-configuration view: every claim with links, reviewed as one unit
    (do these declarations say what the claim says?)."""
    units = []
    for c in index["claims"]:
        ch = chunks[c["file"]]
        links = ch.get("links") or []
        if not links or ch.get("step"):
            # A proof step's links are compared in its own unit (`step_units`).
            continue
        size = sum(len(_text((l.get("statement") or {}).get("conclusion"))) +
                   sum(len(_text(b.get("type"))) for b in (l.get("statement") or {})
                       .get("binders", [])) for l in links)
        effort = round(1 + size / 200, 2)
        units.append({
            "id": "link:" + ch["key"], "kind": "link", "key": ch["key"],
            "name": ", ".join(l["name"] for l in links), "lean": [l["name"] for l in links],
            "fingerprints": {l["name"]: l.get("fingerprint") for l in links},
            # The passage shown, which the report pins: a change to it reopens the review.
            "source_sha256": {c["id"]: ch["source_sha256"]} if ch.get("source_sha256") else {},
            "paper": c["paper"], "papers": [c["paper"]], "section": section_of(c["number"]),
            "claims": [{"id": c["id"], "number": c["number"], "title": c["title"],
                        "file": c["file"], "status": c["status"]}],
            "state": ch.get("review_state") or "pending", "author_review": [],
            "effort": effort, "order": effort, "reason": f"{_size(effort)} statement"})
    units.sort(key=lambda u: (u["state"] == "reviewed", u["order"], u["id"]))
    return {"schema": SCHEMA, "release": index["release"], "mode": "simple", "authors": [],
            "units": with_steps(units, step_units(index, chunks)), "needs_statement": []}


# -- the investigation order ------------------------------------------------------------------
#
# `prioritise` reorders the open units of a built queue by what the build's records say about
# them: the comparison with the previous release (`changes.py`) and the reverse references of
# the Lean (`uses.site_index`). `arrange` does the same for the command line with the records of
# the auditors' workspaces (`workspace_signals`, `main_result_signals`), or in the paper's order.
# Each reads records only and starts no Lean; none changes a unit's state, a status or a marker,
# and the steps of each unit keep their locks. A signal's words name the paper's claims, never a
# Lean declaration: a reviewer reads them before the Lean is shown.

# The signals that order the units, strongest first. A unit's place is set by its strongest one;
# being a saved main result or used by one (`main result`) comes next, then being used in another
# claim's proof (`proof use`), then the queue's own order. A finding of a workspace that a change
# reopened (`reopened finding`) comes first; only the informed order reads it.
TIERS = ("reopened finding", "reopened", "changed", "out of date", "open question", "difference",
         "hint")
MAIN = "main result"
RELEVANCE = "proof use"
# The signals read from the auditors' workspaces: prior interpretations, which only the informed
# order reads.
WORKSPACE_KINDS = ("reopened finding", "out of date", "open question", "difference", "hint", MAIN)
# How a main result's terms use a unit's Lean, strongest first.
MAIN_USES = ("proof", "definition", "statement")
ORDERS = ("priority", "document", "informed")
ORDER_NOTE = ("The order suggests what to review next. It changes no status and no review; "
              "where a record is missing, the queue's order stands.")
TRACE_DEPTH = 6  # how far a use is followed through other declarations
NAMED = 3        # claims a reason names before "and N more"


def _priority(u: dict) -> dict:
    """A copy of a unit's priority record: the reason the queue gave it (`base`) and its
    signals."""
    p = u.get("priority") or {}
    return {"base": p.get("base", u.get("reason", "")),
            "signals": copy.deepcopy(p.get("signals") or [])}


def _label(cid: str, numbers: dict) -> str:
    return numbers.get(cid) or cid


def _list(items: list[str]) -> str:
    items = list(dict.fromkeys(items))
    if len(items) > NAMED:
        return ", ".join(items[:NAMED]) + f" and {len(items) - NAMED} more"
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _numbers(units: list[dict], extra: dict | None = None) -> dict[str, str]:
    out = dict(extra or {})
    for u in units:
        for c in u.get("claims") or []:
            if c.get("number"):
                out.setdefault(c["id"], c["number"])
    return out


def _add(found: list[dict], kind: str, text: str, claims=(), questions=(), **more) -> None:
    """Add a signal to `found`, once per text, keeping the claims and questions it came from
    (and `more` fields, such as how a main result uses the unit: `use`)."""
    s = next((x for x in found if x["kind"] == kind and x["text"] == text), None)
    if s is None:
        s = {"kind": kind, "text": text, "claims": [], **more}
        found.append(s)
    s["claims"] += [c for c in dict.fromkeys(claims) if c and c not in s["claims"]]
    for q in questions:
        if q and q not in s.setdefault("questions", []):
            s["questions"].append(q)


def _cause(e: dict, u: dict, numbers: dict) -> str:
    """Why a review stopped counting, in words that name claims and not the Lean: from an
    evidence entry of the comparison (`changes.review_outcome`)."""
    out = []
    for d in e.get("because") or []:
        dep = d.get("dependency")
        if dep == "lean":
            own = d.get("name") == u.get("name")
            if not d.get("now"):
                out.append("its Lean declaration is not in this build" if own else
                           "a declaration it depends on is not in this build")
            elif own:
                out.append("this definition's Lean changed" if u["kind"] == "def" else
                           "its Lean statement changed")
            else:
                out.append("a declaration it depends on changed")
        elif dep == "paper":
            lab = _label(d.get("claim") or "", numbers)
            ch = d.get("change")
            if d.get("detail"):
                out.append(f"the paper no longer prints the pinned passage of {lab}")
            elif ch == "context-changed":
                out.append(f"the context of {lab}'s passage changed")
            elif ch == "repinned":
                out.append(f"the passage of {lab} was pinned again")
            elif ch == "context-repinned":
                out.append(f"the context of {lab}'s passage was pinned again")
            else:
                out.append(f"the passage of {lab} changed")
        elif dep == "review":
            out.append("no review of it is recorded now")
        else:
            out.append(d.get("detail") or "its last review is not current")
    return "; ".join(dict.fromkeys(out)) or "its last review is not current"


def change_signals(units: list[dict], changes: dict) -> dict[str, list[dict]]:
    """What changed since the previous release in what each open unit's review reads, from the
    comparison of the two releases (`changes.compare`). A review the comparison reopened gives
    `reopened`, with its cause and the question a new reading answers. A unit with no review to
    reopen gives `changed` when its Lean statement, a definition that statement uses, its
    definition, or a passage it is read against changed. A proof that changed alone gives
    nothing: a review of a statement does not read its proof. Nor does a definition of which
    only the authored source changed (an edit of a tactic or of a proof inside it), since its
    statement and value are the same."""
    by_claim = {c["claim"]: c for c in changes.get("claims") or []}
    decls = {d["name"]: d.get("change") for d in changes.get("declarations") or []}
    numbers = _numbers(units, {c["claim"]: c["number"] for c in changes.get("claims") or []
                               if c.get("number")})
    out: dict[str, list[dict]] = {}
    for u in units:
        if u["state"] == "reviewed":
            continue
        kind, cids = u["kind"], [c["id"] for c in u.get("claims") or []]
        found: list[dict] = []
        for cid in cids:
            for e in (by_claim.get(cid) or {}).get("evidence") or []:
                if e.get("outcome") != "reopened" or e.get("target") != kind or \
                        e.get("name") != (cid if kind == "step" else u.get("name")):
                    continue
                _add(found, "reopened",
                     f"reopened since the last release: {_cause(e, u, numbers)}", [cid],
                     [e.get("question")])
        if not found:
            what: list[tuple[str, str]] = []
            for cid in cids if kind == "spec" else []:
                for row in (by_claim.get(cid) or {}).get("lean") or []:
                    prop = row.get("proposition") or {}
                    if prop.get("name") != u.get("name"):
                        continue
                    if prop.get("change") in ("statement", "renamed"):
                        what.append(("its Lean statement", cid))
                    # A definition whose authored source alone changed (`proof`: the same
                    # statement and value) changes nothing the statement says.
                    if any(d.get("change") in ("statement", "new", "removed")
                           for d in row.get("definitions") or []):
                        what.append(("a definition its Lean statement uses", cid))
            if kind == "def" and decls.get(u.get("name")) == "statement":
                what.append(("this definition's Lean", ""))
            # A definition is read against the passages of the claims that name it.
            read = list(u.get("source_sha256") or {}) if kind == "def" else cids
            for cid in read:
                cls = ((by_claim.get(cid) or {}).get("paper_change") or {}).get("class")
                lab = _label(cid, numbers)
                if cls == "changed":
                    what.append((f"the passage of {lab}", cid))
                elif cls == "context-changed":
                    what.append((f"the context of {lab}'s passage", cid))
            for w, cid in what:
                _add(found, "changed", f"changed since the last release: {w}", [cid])
        if found:
            out[u["id"]] = found
    return out


def proof_use_signals(units: list[dict], uses: dict) -> dict[str, list[dict]]:
    """Which other claims' Lean proofs use each open unit's Lean, from the build's reverse
    references (`uses.site_index`): a declaration linked to the unit is used in the proof of a
    declaration linked to another claim, directly or through other declarations (followed
    `TRACE_DEPTH` steps). A use found is a fact about Lean terms; finding none says nothing, so
    it gives no words."""
    users: dict[str, dict[str, set]] = {}
    for name, entries in ((uses or {}).get("by_name") or {}).items():
        for e in entries:
            for x in e.get("users") or []:
                users.setdefault(name, {}).setdefault(x["name"], set()).update(x.get("refs") or [])
    linked: dict[str, list[str]] = {}
    for u in units:
        if u["kind"] in ("link", "step"):
            for n in (u.get("lean") or []) + (u.get("route") or []):
                for c in u.get("claims") or []:
                    if c["id"] not in linked.setdefault(n, []):
                        linked[n].append(c["id"])
    numbers = _numbers(units)
    out: dict[str, list[dict]] = {}
    for u in units:
        if u["state"] == "reviewed" or u["kind"] not in ("link", "step"):
            continue
        mine = list(dict.fromkeys((u.get("lean") or []) + (u.get("route") or [])))
        own = {c["id"] for c in u.get("claims") or []}
        found: list[str] = []
        seen, frontier = set(mine), mine
        for _ in range(TRACE_DEPTH):
            nxt = []
            for n in frontier:
                for user in sorted(users.get(n, {})):
                    if "proof" in users[n][user]:
                        found += [c for c in linked.get(user, [])
                                  if c not in own and c not in found]
                    if user not in seen:
                        seen.add(user)
                        nxt.append(user)
            frontier = nxt
        if found:
            out[u["id"]] = [{"kind": RELEVANCE, "claims": found, "text": (
                "used in the proof of " if len(found) == 1 else "used in the proofs of ")
                + _list([_label(c, numbers) for c in found])}]
    return out


def workspace_signals(units: list[dict], workspaces: list[dict], site=None, root=None
                      ) -> tuple[dict[str, list[dict]], list[str]]:
    """What the auditors' workspaces record as still open for each open unit's claims: a finding
    in force that a change reopened, with the question a new reading answers (`reopened
    finding`, `finding_signals`); a requirement, an alignment or a counterexample that is out of
    date (`out of date`, `record_signals`); an open obligation of a composition, a requirement
    no step of it establishes, a finding that is unresolved, covers part of the claim or is not
    known to be current, a candidate or incomplete counterexample, an open question (`open
    question`); a difference that is not resolved, a finding that the Lean states the claim
    differently, an admissible counterexample (`difference`); a hypothesis of an aligned Lean
    statement that no requirement is aligned with and no difference settles, a passage proposed
    and not yet accepted, a counterexample of numeric samples only (`hint`). A difference
    resolved or found to be none, and a hint a difference settles, give no words: the workspace
    keeps their explanation. A definition takes no words from its claims' records. `site`, the
    build's site data (`targets.Snapshot`), gives the statements of the hints and what the
    records are checked against, with `root`, the Lean project, for what Lean read before (no
    Lean runs); without it, only what the records say of themselves is read. Returns the signals
    by unit and the claims whose records they come from: those are prior interpretations."""
    from . import composition as cp
    from . import estimates as est
    from .workspace import current_findings
    per: dict[str, list[tuple[str, str, list]]] = {}
    numbers = _numbers(units)

    def add(cid, kind, text, questions=()):
        if not cid:
            return
        rows = per.setdefault(cid, [])
        row = next((r for r in rows if r[0] == kind and r[1] == text), None)
        if row is None:
            rows.append((kind, text, list(dict.fromkeys(q for q in questions if q))))
        else:
            row[2].extend(q for q in questions if q and q not in row[2])

    for ws in workspaces:
        recs = [r for r in (ws.get("records") or {}).values() if isinstance(r, dict)]
        in_force = {f["id"] for f in current_findings(ws)}
        for r in recs:
            cid, kind = r.get("claim"), r.get("kind")
            if kind == "composition":
                g = cp.gaps(r, ws)
                for o in r.get("obligations") or []:
                    if o.get("id") in g["open"]:
                        add(cid, "open question", "an open obligation is recorded: "
                            + cp.OBLIGATION_WORDS.get(o.get("kind"), "an obligation"))
                if g["requirements"] and g["uncovered"]:
                    add(cid, "open question", "a recorded composition leaves a requirement "
                        "that no step establishes")
            elif kind == "finding" and r["id"] in in_force:
                d = r.get("difference") or {}
                if r.get("coverage") == "unresolved":
                    add(cid, "open question", "a recorded finding leaves an open question")
                elif r.get("coverage") == "partial":
                    add(cid, "open question", "a recorded finding covers part of the claim")
                if d.get("outcome") in ("open", "difference"):
                    add(cid, "difference", f"a recorded difference ({d.get('feature')})"
                        + (", not yet decided" if d["outcome"] == "open" else ""))
                elif r.get("coverage") == "changed":
                    add(cid, "difference", "a recorded finding says the Lean states it "
                        "differently")
            elif kind == "question" and r.get("state") == "open":
                add(cid, "open question", "an open question is recorded")
        for cid in sorted({r["claim"] for r in recs if r.get("kind") == "alignment"}):
            hs, _ = est.hints([r for r in recs if r.get("claim") == cid], site, cid)
            n = sum(1 for h in hs if not h.get("settled_by"))
            if n:
                add(cid, "hint", "a hypothesis of its Lean statement is aligned with no "
                    "requirement" if n == 1 else f"{n} hypotheses of its Lean statement are "
                    "aligned with no requirement")
        if hasattr(site, "digests"):
            from .workspace import currency
            cur = currency(ws, site, root)
            judged = map_judgments(ws, site, root)
            finding_signals(ws, cur, judged, numbers, add)
            record_signals(ws, cur, judged, numbers, add)
    out: dict[str, list[dict]] = {}
    drawn: list[str] = []
    for u in units:
        if u["state"] == "reviewed" or u["kind"] == "def":
            continue
        for c in u.get("claims") or []:
            for kind, text, questions in per.get(c["id"], []):
                _add(out.setdefault(u["id"], []), kind, text, [c["id"]], questions)
                if c["id"] not in drawn:
                    drawn.append(c["id"])
    return out, drawn


def change_words(changes: list[dict], numbers: dict) -> str:
    """What changed in what a workspace record rests on (`workspace.currency`), in words that
    name the paper's claims and never the Lean: a reviewer reads them before the Lean is
    shown."""
    out = []
    for ch in changes:
        cid = ch.get("passage") or ch.get("claim")
        if ch.get("record") or ch.get("counterexample"):
            out.append(ch.get("reason") or "a record it rests on changed")
        elif ch.get("fragment"):
            out.append("a passage it names is no longer accepted")
        elif ch.get("region"):
            out.append("a passage of the paper it reads changed" if ch.get("now")
                       else "the paper no longer has a passage it reads")
        elif cid:
            label = _label(cid, numbers)
            out.append(f"{label} is not in this build" if "now" in ch and ch["now"] is None
                       else f"the paper no longer prints the pinned passage of {label}"
                       if ch.get("reason") else f"the passage of {label} changed")
        else:
            out.append("the Lean it rests on changed")
    return "; ".join(dict.fromkeys(out)) or "what it rests on changed"


def _counted(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def _without_lean(part: dict) -> dict:
    """A part of a finding the version map reopened (`reopen.py`), its change worded without the
    declarations through which the finding relies on it, for a question a reviewer reads before
    the Lean is shown."""
    from .version_map import _context_words
    ch = dict(part.get("change") or {})
    ctx = [{k: v for k, v in x.items() if k != "through"} for x in ch.get("context") or []]
    if ctx:
        ch["context"] = ctx
        if ch.get("class") == "context-changed":
            ch["reason"] = "; ".join(dict.fromkeys(_context_words(x) for x in ctx))
    return {**part, "change": ch}


def _map_words(row: dict, f: dict, numbers: dict) -> tuple[list[str], list[str]]:
    """What a version map says reopened a finding (`reopen.reopen`'s row for it), in words that
    name claims only, and the question a new reading answers about each part."""
    from . import dependencies as dp
    from . import reopen as ro
    words, questions = [], []
    for part in row.get("paper") or []:
        if part.get("state") != "reopened":
            continue
        dep = part.get("dependency") or {}
        cls = (part.get("change") or {}).get("class")
        if dep.get("dependency") == dp.CONTEXT and dep.get("region"):
            words.append("a passage it reads as context changed in the revision")
        else:
            side = part.get("later") or part.get("earlier") or {}
            cid = side.get("claim") or f.get("claim")
            label = side.get("number") or _label(cid, numbers)
            words.append(f"{label} is not in the later revision" if cls == "removed" else
                         f"the context of {label}'s passage changed in the revision"
                         if cls == "context-changed" else
                         f"the passage of {label} changed in the revision")
        questions.append(ro._question(f, _without_lean(part), dep))
    build = row.get("build") or {}
    if build.get("state") == "stale":
        w = change_words(build.get("changes") or [], numbers)
        words.append(w)
        questions.append(f"Does {ro._what(f)} still hold now that {w}?")
    return words, questions


def map_judgments(ws: dict, snap, root=None) -> dict:
    """What the version maps the workspace `ws` keeps to the release of the build `snap` say of
    its records (`reopen.reopen`): each finding in force that rests on the paper (`findings`, by
    id) and each passage attached to a requirement (`passages`, by id), and the papers they map
    (`papers`). A map to another release says nothing here."""
    from . import reopen as ro
    release = snap.index.get("release")
    out: dict = {"papers": set(), "findings": {}, "passages": {}}
    for doc in ws.get("version_maps") or []:
        if (doc.get("to") or {}).get("release") != release:
            continue
        try:
            got = ro.reopen(doc, ws, snap, root)
        except ro.MapError:
            continue
        out["papers"].add(got["paper"])
        for row in got["findings"]:
            out["findings"].setdefault(row["id"], row)
        for row in got["passages"]:
            out["passages"].setdefault(row["id"], row)
    return out


def finding_signals(ws: dict, cur: dict, judged: dict, numbers: dict, add) -> None:
    """The findings in force of the workspace `ws` that are not current against the build, by
    claim (`add(claim, kind, text, questions)`). A finding that a version map the workspace
    keeps to this release judges (`judged`, `map_judgments`) reads as the map says; any other
    as its currency (`cur`, `workspace.currency`) says. A reopened one is due for review
    (`reopened finding`), with the question a new reading answers about each part that changed;
    one that is not known to be current is a hint."""
    from . import reopen as ro
    from .workspace import current_findings
    rows = judged.get("findings") or {}
    due: dict[str, tuple[int, list[str], list[str]]] = {}
    unknown: dict[str, int] = {}
    for f in sorted(current_findings(ws), key=lambda r: r["id"]):
        cid = f.get("claim")
        row = rows.get(f["id"])
        state = row["state"] if row is not None else (cur.get(f["id"]) or {}).get("state")
        if state == "reopened" and row is not None:
            words, questions = _map_words(row, f, numbers)
        elif state == "stale":
            w = change_words((cur.get(f["id"]) or {}).get("changes") or [], numbers)
            words, questions = [w], [f"Does {ro._what(f)} still hold now that {w}?"]
        else:
            if state == "unchecked":
                unknown[cid] = unknown.get(cid, 0) + 1
            continue
        n, said, asked = due.get(cid, (0, [], []))
        due[cid] = (n + 1, said + words, asked + questions)
    for cid, (n, words, questions) in due.items():
        add(cid, "reopened finding",
            _counted(n, "a recorded finding is", "{n} recorded findings are")
            + " due for review: " + "; ".join(dict.fromkeys(words)), questions)
    for cid, n in unknown.items():
        add(cid, "hint", _counted(n, "a recorded finding is", "{n} recorded findings are")
            + " not known to be current")


def _paper_change(ch: dict) -> bool:
    """Whether a change of a record's currency is one of the paper's text."""
    return bool(ch.get("region") or ch.get("passage")
                or (ch.get("claim") and not ch.get("record")))


def record_signals(ws: dict, cur: dict, judged: dict, numbers: dict, add) -> None:
    """The requirements, alignments and counterexamples of the workspace `ws` that are out of
    date against the build (`cur`, `workspace.currency`): a requirement whose accepted passages
    changed, an alignment whose Lean or passages changed, a counterexample whose reading,
    governing passages or evidence changed (`out of date`). For a paper that a version map the
    workspace keeps to this release follows (`judged`, `map_judgments`), the map says whether
    a passage changed: one it finds moved is the same text. Also what each counterexample that
    is current shows of its reading (`estimates.analyse`): admissible (`difference`), a
    candidate or incomplete (`open question`), numeric samples only (`hint`); and the passages
    proposed as governing a requirement and not yet accepted (`hint`). By claim, as
    `add(claim, kind, text)`."""
    from . import estimates as est
    papers = judged.get("papers") or set()
    passages = judged.get("passages") or {}
    by: dict[str, list[dict]] = {}
    for r in (ws.get("records") or {}).values():
        if isinstance(r, dict) and r.get("claim"):
            by.setdefault(r["claim"], []).append(r)
    for cid, rs in by.items():
        found: dict[tuple[str, str, str], list[str]] = {}
        mapped = cid.split(":", 1)[0] in papers

        def note(kind, one, many, words=""):
            found.setdefault((kind, one, many), []).append(words)

        def governing(lids, roles=None):
            return [f for f in rs if f.get("kind") == "fragment" and f.get("requirement") in lids
                    and (f.get("state") or "accepted") == "accepted"
                    and (roles is None or f.get("role") not in roles)]

        def changed(changes, fragments) -> str:
            """What changed, with the paper's side as the map says when it follows the paper."""
            if mapped:
                changes = [c for c in changes if not _paper_change(c)]
            words = [change_words(changes, numbers)] if changes else []
            if mapped and any((passages.get(f["id"]) or {}).get("state") == "reopened"
                              for f in fragments):
                words.append("a passage that governs it changed in the revision")
            return "; ".join(words)

        for r in sorted(rs, key=lambda r: r.get("id") or ""):
            kind = r.get("kind")
            if kind == "requirement":
                frs = governing({r.get("local_id")})
                said = changed([c for f in frs for c in (cur.get(f["id"]) or {}).get("changes")
                                or []], frs)
                if said:
                    note("out of date", "a recorded requirement is out of date",
                         "{n} recorded requirements are out of date", said)
            elif kind == "alignment":
                frs = [f for f in rs if f.get("id") in (r.get("fragments") or [])]
                said = changed((cur.get(r["id"]) or {}).get("changes") or [], frs)
                if said:
                    note("out of date", "a recorded alignment with the Lean is out of date",
                         "{n} recorded alignments with the Lean are out of date", said)
            elif kind == "counterexample":
                ob = est.obligation(rs, r.get("requirement"), tuple(r.get("reading") or ()))
                frs = governing(set((ob or {}).get("involved") or ()), ("later use",))
                said = changed((cur.get(r["id"]) or {}).get("changes") or [], frs)
                if said:
                    note("out of date", "a recorded counterexample is out of date",
                         "{n} recorded counterexamples are out of date", said)
                    continue
                standing = est.analyse(r, ob)["standing"]
                if standing == "admissible counterexample":
                    note("difference", "an admissible counterexample to a reading is recorded",
                         "{n} admissible counterexamples to readings are recorded")
                elif standing == "candidate":
                    note("open question", "a candidate counterexample is recorded, not yet "
                         "shown admissible", "{n} candidate counterexamples are recorded, not "
                         "yet shown admissible")
                elif standing == "incomplete":
                    note("open question", "an incomplete counterexample is recorded",
                         "{n} incomplete counterexamples are recorded")
                elif standing == "illustration":
                    note("hint", "a counterexample of numeric samples only is recorded",
                         "{n} counterexamples of numeric samples only are recorded")
            elif kind == "fragment" and r.get("state") == "proposed":
                note("hint", "a passage proposed as governing a requirement is not yet accepted",
                     "{n} passages proposed as governing requirements are not yet accepted")
        for (kind, one, many), words in found.items():
            said = "; ".join(dict.fromkeys(w for w in words if w))
            add(cid, kind, _counted(len(words), one, many) + (f": {said}" if said else ""))


def _tier(u: dict) -> str | None:
    """A unit's strongest signal of `TIERS`, or None."""
    kinds = [s["kind"] for s in u["priority"]["signals"] if s["kind"] in TIERS]
    return min(kinds, key=TIERS.index) if kinds else None


def _rank(u: dict) -> tuple[int, bool, bool]:
    t = _tier(u)
    kinds = {s["kind"] for s in u["priority"]["signals"]}
    return (TIERS.index(t) if t else len(TIERS), MAIN not in kinds, RELEVANCE not in kinds)


def _main_uses(start: list[str], users: dict[str, dict[str, set]], mains: set[str]
               ) -> dict[str, str]:
    """The main declarations (`mains`) whose terms refer to one of `start`, directly or through
    other declarations (followed `TRACE_DEPTH` steps), each with how its last reference is made,
    the strongest of `MAIN_USES` over every path."""
    best: dict[str, str] = {}
    seen, frontier = set(start), list(start)
    for _ in range(TRACE_DEPTH):
        nxt = []
        for n in frontier:
            for user in sorted(users.get(n, {})):
                refs = users[n][user]
                if user in mains:
                    how = "proof" if "proof" in refs else "definition" if refs - {"statement"} \
                        else "statement"
                    if user not in best or MAIN_USES.index(how) < MAIN_USES.index(best[user]):
                        best[user] = how
                if user not in seen:
                    seen.add(user)
                    nxt.append(user)
        frontier = nxt
    return best


def main_result_signals(units: list[dict], selections: list[dict], uses: dict | None, chunk
                        ) -> tuple[dict[str, list[dict]], list[str]]:
    """What the main-result selections the auditors' workspaces save (`workspace main`) say of
    each open unit: that it is a saved main result (`use` `itself`: one of its claims is
    selected, or a declaration selected is one it states), or that a saved main result uses its
    Lean, in its proof, its definition or its statement (`use`), directly or through other
    declarations, from the build's reverse references (`uses`, `uses.site_index`; None when the
    build has none, and then only the first is read). A claim selected stands for its linked
    Lean (`impact.root_names`); `chunk` gives a claim's record. A use found is a fact about Lean
    terms, and finding none says nothing. Returns the signals by unit and the claims they draw
    on: the selection is an auditor's, a prior interpretation."""
    from .impact import root_names
    claims_of: dict[str, list[str]] = {}   # a main declaration, and the claims it stands for
    selected: set[str] = set()              # the claims selected
    named_decls: set[str] = set()           # the declarations selected by their names
    for sel in selections:
        for e in sel.get("selected") or []:
            if e.get("claim"):
                ch = chunk(e["claim"])
                if ch is None:
                    continue
                selected.add(e["claim"])
                for n in root_names(ch):
                    if e["claim"] not in claims_of.setdefault(n, []):
                        claims_of[n].append(e["claim"])
            elif e.get("decl"):
                named_decls.add(e["decl"])
                claims_of.setdefault(e["decl"], [])
    users: dict[str, dict[str, set]] = {}
    for name, entries in ((uses or {}).get("by_name") or {}).items():
        for e in entries:
            for x in e.get("users") or []:
                users.setdefault(name, {}).setdefault(x["name"], set()).update(x.get("refs") or [])

    def states(u):
        """The declarations that state a unit's claims: a link's, or a locked proposition."""
        return list(dict.fromkeys(u.get("lean") or [])) if u["kind"] == "link" else \
            [u["name"]] if u["kind"] == "spec" else []

    stated: dict[str, list[str]] = {}       # a declaration, and the claims that it states
    for u in units:
        for n in states(u):
            for c in u.get("claims") or []:
                if c["id"] not in stated.setdefault(n, []):
                    stated[n].append(c["id"])
    numbers = _numbers(units)
    out: dict[str, list[dict]] = {}
    drawn: list[str] = []
    for u in units:
        if u["state"] == "reviewed" or u["kind"] == "def":
            continue
        own = [c["id"] for c in u.get("claims") or []]
        mine = states(u)
        found: list[dict] = []
        if selected & set(own) or named_decls & set(mine):
            _add(found, MAIN, "a saved main result", own, use="itself")
        traced = list(dict.fromkeys(mine + list(u.get("lean") or []) + list(u.get("route") or [])))
        best = _main_uses(traced, users, set(claims_of) - set(traced)) if users else {}
        for how in MAIN_USES:
            named, unnamed = [], False
            for m, h in best.items():
                if h != how:
                    continue
                names = [c for c in claims_of[m] or stated.get(m, []) if c not in own]
                named += [c for c in names if c not in named]
                unnamed |= not (claims_of[m] or stated.get(m))
            if named:
                _add(found, MAIN, (f"used in the {how} of " if len(named) == 1 else
                                   f"used in the {how}s of ")
                     + _list([_label(c, numbers) for c in named])
                     + (", a saved main result" if len(named) == 1 else ", saved main results"),
                     named, use=how)
            elif unnamed:
                _add(found, MAIN, f"used in the {how} of a saved main result", (), use=how)
        if found:
            out[u["id"]] = found
            for c in own + [c for s in found for c in s["claims"]]:
                if c not in drawn:
                    drawn.append(c)
    return out, drawn


def _fold_proof_use(p: dict, numbers: dict) -> None:
    """A main-result signal of a use in a proof says what the proof-use signal says of the
    same claims, and more: those claims leave the proof-use signal, which goes when none is
    left."""
    shown = {c for s in p["signals"] if s["kind"] == MAIN and s.get("use") == "proof"
             for c in s["claims"]}
    if not shown:
        return
    for s in [s for s in p["signals"] if s["kind"] == RELEVANCE]:
        rest = [c for c in s["claims"] if c not in shown]
        if not rest:
            p["signals"].remove(s)
        elif rest != s["claims"]:
            s.update(claims=rest, text=("used in the proof of " if len(rest) == 1 else
                                        "used in the proofs of ")
                     + _list([_label(c, numbers) for c in rest]))


def _revealed_first(units: list[dict]) -> list[dict]:
    """`units` (in their order) with the units each one reveals placed just before it, theirs
    before them, so that a unit is not held behind later ones while what it reveals waits
    (`reveal_order` holds it back instead). Units that reveal each other keep their order."""
    pos = {u["id"]: i for i, u in enumerate(units)}
    by = {u["id"]: u for u in units}

    def shows(u):
        r = u.get("reveals") or {}
        return set(r.get("lean") or []) | set(r.get("author") or [])

    out, done, open_ = [], set(), set()

    def place(u):
        if u["id"] in done or u["id"] in open_:
            return
        open_.add(u["id"])
        for v in sorted((v for v in shows(u) if v in by and u["id"] not in shows(by[v])),
                        key=pos.get):
            place(by[v])
        open_.discard(u["id"])
        done.add(u["id"])
        out.append(u)

    for u in units:
        place(u)
    return out


def _unit_label(v: dict, numbers: dict) -> str:
    if v["kind"] == "def" or not v.get("claims"):
        return "another definition" if v["kind"] == "def" else "another unit"
    return _list([_label(c["id"], numbers) for c in v["claims"]])


def _reason(u: dict, ahead: list[dict], numbers: dict, by: str) -> str:
    """The reason a unit comes where it does: in the paper's order (for `document`), its
    signals, strongest first, the units it comes before because their review shows it, then the
    reason the queue gave it."""
    p = u["priority"]
    kinds = TIERS + (MAIN, RELEVANCE)
    parts = ["in the paper's order"] if by == "document" else []
    parts += [s["text"] for s in sorted(p["signals"], key=lambda s: kinds.index(s["kind"])
                                        if s["kind"] in kinds else len(kinds))]
    for what, key in (("its Lean", "lean"), ("its author's review", "author")):
        later = [v for v in ahead if u["id"] in ((v.get("reveals") or {}).get(key) or [])]
        if later:
            names = _list([_unit_label(v, numbers) for v in later])
            parts.append(f"comes before the review of {names}, which shows {what}")
    if not parts:
        return p["base"]
    base = p["base"][:1].lower() + p["base"][1:]
    text = "; ".join(parts + ([base] if base else []))
    return text[:1].upper() + text[1:]


def arrange(units: list[dict], signals: dict[str, list[dict]], by: str = "priority",
            claims: list[dict] | None = None) -> list[dict]:
    """Copies of `units` (open units, in the queue's order) with `signals` added to the signals
    each already has, in the order `by` gives. `priority`: by the strongest signal (`TIERS`),
    then saved main results and units they use, then units used in another claim's proof, then
    the queue's order; with no signal at all, the queue's order and reasons stand. `document`:
    by the place in `claims` (the paper's claims, in order) of the unit's first claim, then the
    queue's order. Either way a unit that another reveals comes just before it
    (`_revealed_first`) and says so, and each unit's `reason` says why it comes where it does."""
    pos = {u["id"]: i for i, u in enumerate(units)}
    numbers = _numbers(units)
    out = []
    for u in units:
        p = _priority(u)
        for s in signals.get(u["id"]) or []:
            _add(p["signals"], s["kind"], s["text"], s.get("claims") or (),
                 s.get("questions") or (), **({"use": s["use"]} if "use" in s else {}))
        _fold_proof_use(p, numbers)
        out.append({**u, "priority": p})
    if by == "document":
        at = {c["id"]: i for i, c in enumerate(claims or [])}
        ranked = sorted(out, key=lambda u: (min((at.get(c["id"], len(at)) for c in
                                                 u.get("claims") or []), default=len(at)),
                                            pos[u["id"]]))
    elif any(u["priority"]["signals"] for u in out):
        ranked = sorted(out, key=lambda u: (_rank(u), pos[u["id"]]))
    else:
        for u in out:
            u["reason"] = u["priority"]["base"]
            u["priority"]["tier"] = None
        return out
    final = _revealed_first(ranked)
    rank = {u["id"]: i for i, u in enumerate(ranked)}
    placed = {u["id"]: i for i, u in enumerate(final)}
    for u in final:
        ahead = [v for v in ranked[:rank[u["id"]]] if placed[v["id"]] > placed[u["id"]]]
        u["priority"]["tier"] = _tier(u)
        u["reason"] = _reason(u, ahead, numbers, by)
    return final


def prioritise(queue: dict, changes: dict | None = None, uses: dict | None = None,
               unbuilt: int = 0, claims: list[dict] | None = None) -> dict:
    """The queue with its open units in investigation order (`arrange`), from the build's
    records: `changes`, the comparison with the previous release (`changes.compare`), and
    `uses`, the reverse references of the Lean (`uses.site_index`), with `unbuilt` the number of
    the project's modules not built, whose uses are not traced. Reviewed units stay last, as
    they were. `order` says which records were read and why any was not. With `claims` (the
    paper's claims, in order), `orders` also holds the open units in the paper's order with
    their reasons, as `review status --order document` gives them, for the reader."""
    signals: dict[str, list[dict]] = {}
    for got in (change_signals(queue["units"], changes) if changes else {},
                proof_use_signals(queue["units"], uses) if uses else {}):
        for k, v in got.items():
            signals.setdefault(k, []).extend(v)
    units = arrange([u for u in queue["units"] if u["state"] != "reviewed"], signals)
    units += [{**u, "priority": {**_priority(u), "tier": None}} for u in queue["units"]
              if u["state"] == "reviewed"]
    full = queue.get("mode") != "simple"
    record = {
        "changes": {"state": "read", "from": (changes.get("from") or {}).get("release"),
                    "to": (changes.get("to") or {}).get("release")} if changes else
        {"state": "not available", "why": "no earlier release with other evidence to compare "
         "with" if full else "the zero-configuration view keeps no earlier release"},
        RELEVANCE: ({"state": "incomplete", "why": f"{unbuilt} module(s) of the project are "
                     "not built: uses in them are not traced"} if unbuilt else {"state": "read"})
        if uses else {"state": "not available", "why": "the full assessment extracts no "
                      "reverse references" if full else "this build extracted no reverse "
                      "references"}}
    out = {**queue, "units": units,
           "order": {"by": "priority" if signals else "effort", "signals": record,
                     "note": ORDER_NOTE}}
    if claims is not None:
        opened = [u for u in units if u["state"] != "reviewed"]
        out["orders"] = {"document": [{"id": u["id"], "reason": u["reason"]}
                                      for u in arrange(opened, {}, "document", claims)]}
    return out
