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
# the auditors' workspaces (`workspace_signals`), or in the paper's order. Each reads records
# only and starts no Lean; none changes a unit's state, a status or a marker, and the steps of
# each unit keep their locks. A signal's words name the paper's claims, never a Lean
# declaration: a reviewer reads them before the Lean is shown.

# The signals that order the units, strongest first. A unit's place is set by its strongest one;
# being used in another claim's proof (`proof use`) comes next, then the queue's own order.
TIERS = ("reopened", "changed", "open question", "difference", "hint")
RELEVANCE = "proof use"
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


def _add(found: list[dict], kind: str, text: str, claims=(), questions=()) -> None:
    """Add a signal to `found`, once per text, keeping the claims and questions it came from."""
    s = next((x for x in found if x["kind"] == kind and x["text"] == text), None)
    if s is None:
        s = {"kind": kind, "text": text, "claims": []}
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


def workspace_signals(units: list[dict], workspaces: list[dict], site=None
                      ) -> tuple[dict[str, list[dict]], list[str]]:
    """What the auditors' workspaces record as still open for each open unit's claims: an open
    obligation of a composition, a requirement no step of it establishes, a finding that is
    unresolved or covers part of the claim, an open question (`open question`); a difference
    that is not resolved, or a finding that the Lean states the claim differently (`difference`);
    a hypothesis of an aligned Lean statement that no requirement is aligned with and no
    difference settles (`hint`). A difference resolved or found to be none, and a hint a
    difference settles, give no words: the workspace keeps their explanation. A definition takes
    no words from its claims' records. `site` (the build's claims) gives the statements of the
    hints. Returns the signals by unit and the claims whose records they come from: those are
    prior interpretations."""
    from . import composition as cp
    from . import estimates as est
    from .workspace import current_findings
    per: dict[str, list[tuple[str, str]]] = {}

    def add(cid, kind, text):
        if cid and (kind, text) not in per.setdefault(cid, []):
            per[cid].append((kind, text))

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
    out: dict[str, list[dict]] = {}
    drawn: list[str] = []
    for u in units:
        if u["state"] == "reviewed" or u["kind"] == "def":
            continue
        for c in u.get("claims") or []:
            for kind, text in per.get(c["id"], []):
                _add(out.setdefault(u["id"], []), kind, text, [c["id"]])
                if c["id"] not in drawn:
                    drawn.append(c["id"])
    return out, drawn


def _tier(u: dict) -> str | None:
    """A unit's strongest signal of `TIERS`, or None."""
    kinds = [s["kind"] for s in u["priority"]["signals"] if s["kind"] in TIERS]
    return min(kinds, key=TIERS.index) if kinds else None


def _rank(u: dict) -> tuple[int, bool]:
    t = _tier(u)
    return (TIERS.index(t) if t else len(TIERS),
            not any(s["kind"] == RELEVANCE for s in u["priority"]["signals"]))


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
    kinds = TIERS + (RELEVANCE,)
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
    then units used in another claim's proof, then the queue's order; with no signal at all, the
    queue's order and reasons stand. `document`: by the place in `claims` (the paper's claims, in
    order) of the unit's first claim, then the queue's order. Either way a unit that another
    reveals comes just before it (`_revealed_first`) and says so, and each unit's `reason` says
    why it comes where it does."""
    pos = {u["id"]: i for i, u in enumerate(units)}
    out = []
    for u in units:
        p = _priority(u)
        for s in signals.get(u["id"]) or []:
            _add(p["signals"], s["kind"], s["text"], s.get("claims") or (),
                 s.get("questions") or ())
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
    numbers = _numbers(units)
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
