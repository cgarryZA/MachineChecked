"""The review queue: what a reviewer can review, in a suggested order.

A unit of review is a locked proposition (`spec`), a definition its meaning depends on (`def`), or,
in the zero-configuration view, a confirmed link between a claim and a declaration (`link`). Each
unit carries the fingerprints it would be reviewed at, its current review state, the author's
review (shown to the reviewer only after their own verdict) and why it sits where it does in the
order. A unit is reviewed once per fingerprint, however many claims depend on it.

The order is a suggestion: less effort first, with a preference for units that many claims depend
on. Reviewing a definition settles that definition only; no claim is approved by it.
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
                "state": (cl.get("spec_review") or {}).get("state", "pending"),
                "author_review": _author_text(cl.get("spec_review")),
                "witness": cl.get("witness"), "refute": cl.get("refute"),
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
            "fingerprint": rec.get("fingerprint"), "state": rec["review"]["state"],
            "author_review": _author_text(rec["review"]), "effort": effort,
            "reason": f"{_size(effort)} definition; used by {len(users)} claim(s)"})
    for u in units:
        u["order"] = round(u["effort"] - math.log2(1 + len(u["claims"])), 3)
    units.sort(key=lambda u: (u["state"] == "reviewed", u["order"], u["id"]))
    return {"schema": SCHEMA, "release": index["release"], "mode": "assurance",
            "authors": sorted(authors), "units": units, "needs_statement": unspecified}


def simple_queue(index: dict, chunks: dict) -> dict:
    """The queue of the zero-configuration view: every claim with links, reviewed as one unit
    (do these declarations say what the claim says?)."""
    units = []
    for c in index["claims"]:
        ch = chunks[c["file"]]
        links = ch.get("links") or []
        if not links:
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
            "units": units, "needs_statement": []}
