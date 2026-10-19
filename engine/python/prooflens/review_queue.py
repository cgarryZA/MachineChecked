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
on. Reviewing a definition settles that definition only; no claim is approved by it.

A unit also says what reviewing it shows of other units (`reveals`): the Lean of the definitions
a statement uses (its phase 2), and the author's review it shares with other units (its phase 3,
when one review section ends with several markers). A reviewer who has seen a unit's material
before writing their reading of it is no longer blind to it. The order puts a revealed unit
before the one that reveals it where it can; when two units reveal each other (a joint review)
one of them cannot be blind, and the report of the later one records it.
"""

from __future__ import annotations

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
            "paper": c["paper"], "papers": [c["paper"]], "section": section_of(c["number"]),
            "claims": [{"id": c["id"], "number": c["number"], "title": c["title"],
                        "file": c["file"], "status": c["status"]}],
            "state": ch.get("review_state") or "pending", "author_review": [],
            "effort": effort, "order": effort, "reason": f"{_size(effort)} statement"})
    units.sort(key=lambda u: (u["state"] == "reviewed", u["order"], u["id"]))
    return {"schema": SCHEMA, "release": index["release"], "mode": "simple", "authors": [],
            "units": with_steps(units, step_units(index, chunks)), "needs_statement": []}
