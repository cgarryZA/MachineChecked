"""The paper version map: each claim of one revision of a paper matched to the next (#120).

Two revisions of a paper each have an inventory and a manuscript snapshot. The map reads each
earlier claim's passage as the earlier revision prints it, finds it in the later revision with
the repinning planner's matcher (`repin.repin_plan`: its exact text where the paper prints it,
else its label), and pairs it with the later inventory's claim pinned there. Each earlier claim
is classified:

- `unchanged`: the same text, at the same place, under the same number;
- `moved`: the same text at another place or under another number (`renumbered`);
- `context-changed`: the same text, and something it is read with changed: a further passage
  or macro definition of its pin, the definition of a macro it uses, the prose that opens its
  section (a standing assumption), or a claim it refers to or whose definitions its Lean uses;
- `changed`: its label leads to a passage with other text, or the later inventory pins other
  bounds around its text;
- `removed`: nothing in the later revision answers it: its text and label are not there, or
  the later inventory has no claim where they are;
- `ambiguous`: several candidates, or only proposals: its text or label occurs twice, two
  earlier claims lead to one later claim, or a later claim shares only its number, its id or
  the line diff of its file. A renumbering proposes a match; it never shows that two passages
  say the same;
- `unknown`: its passage cannot be read in the earlier revision.

A later claim that no earlier claim is matched to is `new`. A maintainer resolves an ambiguous
claim explicitly (`resolve`); the map records the resolution as theirs, with the candidates.

Each side keeps its own facts: where its passage is, the digest of its text, whether its
inventory's pin matches that text, and, from its own release, the status and the reviews its
build recorded. The map is derived and display only: it changes no status and carries no review
over. Its `numbers` give the paper-number check (`numbering.resolve`) the counterpart in the
later revision of each number of the earlier one.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Callable

from . import repin
from .requirements import REF, section_opening
from .source_regions import (
    RegionError, definition_part, definitions, extract, location, part_claim, pin, tex_sources,
    used_macros,
)

SCHEMA = "prooflens/version-map@1"
# The classes of an entry, in the order the map lists them.
CLASSES = ("changed", "context-changed", "removed", "ambiguous", "new", "unknown", "moved",
           "unchanged")
# A referenced claim whose own passage is not shown unchanged: a context change for the claims
# that rely on it.
UNSETTLED = ("changed", "context-changed", "removed", "ambiguous", "unknown")


class MapError(ValueError):
    pass


@dataclasses.dataclass
class Side:
    """One revision of the paper: its inventory's claims of the paper and its manuscript
    snapshot, with what its own release recorded when there is one."""
    claims: list[dict]
    root: Path
    revision: str
    numbers: dict[str, str] = dataclasses.field(default_factory=dict)
    facts: Callable[[str], dict | None] | None = None
    # claim id -> {definition claim id: [the definitions of it its Lean relies on]}
    uses: dict[str, dict[str, list[str]]] = dataclasses.field(default_factory=dict)
    identity: dict = dataclasses.field(default_factory=dict)

    def number(self, claim: dict) -> str | None:
        return self.numbers.get(claim["id"]) or claim.get("number")


class _Snapshot:
    """A revision's files, read once."""

    def __init__(self, root: Path):
        self.root = root
        self.files = repin.tex_files(root)
        self.sources = tex_sources(root)
        self.defs = definitions(self.sources)
        self._statements: dict = {}
        self._macros: dict = {}

    def statements(self, kind: str | None):
        if kind not in self._statements:
            self._statements[kind] = repin.statements(self.root, self.files, kind)
        return self._statements[kind]

    def lines(self, file: str) -> list[str]:
        return (self.files.get(file) or self.sources.get(file) or "").split("\n")

    def macro(self, name: str) -> dict | None:
        """The definitions of a macro in this revision, with their places and text, or None."""
        if name not in self._macros:
            out = None
            where = self.defs.get(name) or []
            try:
                texts = [extract(self.root, part_claim(definition_part(self.sources, name, f, ln)))
                         .text for f, ln in where]
            except (RegionError, OSError, UnicodeError):
                texts = None
            if where and texts is not None:
                joined = "\n".join(texts)
                out = {"defined": [f"{f}:{ln}" for f, ln in where],
                       "sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
                       "text": joined}
            self._macros[name] = out
        return self._macros[name]


def _env_end(snap: _Snapshot, file: str, line: int, env: str) -> int:
    """The line of the `\\end` that closes the environment `env` opening on `line` of `file`."""
    from .tex import matching_end
    text = snap.files.get(file) or ""
    offset = sum(len(x) + 1 for x in text.split("\n")[:line - 1])
    m = re.compile(r"\\begin\s*\{" + re.escape(env) + r"\}").search(text, offset)
    if m is None:
        return line
    return text.count("\n", 0, matching_end(text, m.end(), env)) + 1


def printed(snap: _Snapshot, claim: dict) -> dict:
    """A claim's passage as a revision prints it: a region at its location (with the further
    passages of its pin), or the environment that carries its label. `error` says why it
    cannot be read."""
    try:
        loc = location(claim)
    except RegionError as error:
        return {"error": str(error)}
    if loc is not None:
        try:
            p = pin(snap.root, claim)
        except (RegionError, OSError, UnicodeError) as error:
            return {"error": str(error)}
        r = p.main
        return {"kind": "region", "pin": p, "bounds": repin._bounds(r),
                "location": f"{r.file}:{r.start_line}", "sha256": p.sha256,
                "passage": r.sha256, "text": r.text, "lines": list(r.lines),
                "matches": _pinned(claim, p.sha256, p.scheme)}
    if not str(claim.get("location") or "").strip():
        return {"error": "it has no source location"}
    names = repin._names_of(claim)
    found = [s for s in snap.statements(claim.get("kind")) if names & set(s.labels)]
    if len(found) != 1:
        kind = claim.get("kind") or "statement"
        return {"error": f"{len(found)} {kind} environments carry its label" if found else
                f"no {kind} environment carries its label; the compiled paper finds it by its "
                "printed number, which this map does not compute"}
    s = found[0]
    body = repin._body(snap.root, s)
    return {"kind": "environment", "statement": s,
            "bounds": {"file": s.file, "start_line": s.line,
                       "end_line": _env_end(snap, s.file, s.line, s.env)},
            "location": f"{s.file}:{s.line}", "sha256": s.sha256, "passage": s.sha256,
            "text": "\n".join(body), "lines": body,
            "matches": _pinned(claim, s.sha256, None)}


def _pinned(claim: dict, sha: str, scheme: str | None) -> str:
    """Whether the inventory's pin of a claim is the text the revision prints."""
    if not claim.get("source_sha256"):
        return "none"
    same = claim["source_sha256"] == sha and claim.get("source_hash_scheme") == scheme
    return "matches" if same else "differs"


def _as_printed(claim: dict, p: dict) -> dict:
    """The claim pinned to the text its revision prints, without a revision of its own, so that
    the repinning planner compares the printed text whatever the inventory's pin."""
    c = deepcopy(claim)
    c.pop("commit", None)
    if p["kind"] == "region":
        pn = p["pin"]
        c.update(source_hash_scheme=pn.scheme, source_sha256=pn.sha256,
                 source_line_sha256=pn.main.line_sha256)
        if pn.parts:
            c["source_parts"] = [{**part, "sha256": r.sha256, "line_sha256": r.line_sha256}
                                 for part, r in pn.parts]
    else:
        c.pop("source_hash_scheme", None)
        c["source_sha256"] = p["sha256"]
    return c


def _key(kind: str, bounds: dict) -> tuple:
    if kind == "environment":
        return ("environment", bounds.get("file"), bounds.get("start_line"))
    return ("region",) + tuple(bounds.get(k) for k in ("file", "start_line", "end_line",
                                                        "start_column", "end_column"))


def _side_record(side: Side, claim: dict, p: dict) -> dict:
    out = {"claim": claim["id"], "number": side.number(claim), "kind": claim.get("kind"),
           "label": claim.get("label"), "scope": claim.get("scope")}
    if p.get("error"):
        out["error"] = p["error"]
    else:
        out.update(location=p["location"], bounds=p["bounds"], sha256=p["passage"],
                   **({"pin_sha256": p["sha256"]} if p["sha256"] != p["passage"] else {}),
                   pin=p["matches"])
    if side.facts is not None:
        out["recorded"] = side.facts(claim["id"])
    return out


def _diff(a: list[str], b: list[str], old: str, new: str) -> list[str]:
    return list(difflib.unified_diff(list(a), list(b), lineterm="", fromfile=old, tofile=new))


def _same_number(x: str | None, y: str | None) -> bool:
    return " ".join(str(x or "").split()) == " ".join(str(y or "").split())


# -- the comparison ------------------------------------------------------------------------------

def compare(paper: str, old: Side, new: Side, resolve=()) -> dict:
    """The version map of `paper` from revision `old` to revision `new`. `resolve` lists the
    maintainer's matches, `(earlier claim id, later claim id)`: each takes an earlier claim no
    passage or label matched to a later claim nothing else is matched to."""
    sa, sb = _Snapshot(old.root), _Snapshot(new.root)
    ca = {c["id"]: c for c in old.claims if c["paper"] == paper}
    cb = {c["id"]: c for c in new.claims if c["paper"] == paper}
    pa = {cid: printed(sa, c) for cid, c in ca.items()}
    pb = {cid: printed(sb, c) for cid, c in cb.items()}

    readable = [_as_printed(ca[cid], p) for cid, p in pa.items() if not p.get("error")]
    plan = {}
    new_passages = []
    if readable:
        try:
            _, report = repin.repin_plan({"claims": readable}, paper, old.root, new.root,
                                         old.revision, new.revision)
        except RegionError as error:
            raise MapError(f"the repinning planner could not compare the revisions: {error}") \
                from None
        plan = {e["claim"]: e for e in report["claims"]}
        new_passages = report.get("new_passages") or []

    places: dict[tuple, list[str]] = {}
    for cid, p in pb.items():
        if not p.get("error"):
            places.setdefault(_key(p["kind"], p["bounds"]), []).append(cid)

    def at(kind, bounds):
        return places.get(_key(kind, bounds), [])

    def overlapping(file, first, last):
        return [cid for cid, p in pb.items() if not p.get("error")
                and p["bounds"]["file"] == file
                and p["bounds"]["start_line"] <= last and first <= p["bounds"]["end_line"]]

    def span_of(kind, bounds, env=None):
        last = bounds.get("end_line")
        if last is None and env:
            last = _env_end(sb, bounds["file"], bounds["start_line"], env)
        return bounds["file"], bounds["start_line"], last or bounds["start_line"]

    entries: dict[str, dict] = {}
    for cid, claim in ca.items():
        p = pa[cid]
        e = {"from": _side_record(old, claim, p), "to": None, "by": [], "candidates": []}
        entries[cid] = e
        if p.get("error"):
            e.update(cls="unknown", reason=f"its passage cannot be read in the earlier revision: "
                     f"{p['error']}")
            continue
        r = plan[cid]
        e["plan"] = r
        env = p["statement"].env if p["kind"] == "environment" else None
        own = "context_changed" in r or r["class"] in ("unchanged", "moved")
        target = r.get("to_region")
        if r["class"] == "ambiguous":
            # Each place its text or label occurs, and the later claims pinned across it.
            locs = r.get("candidates") or []
            basis = "text" if "text" in str(r.get("reason")) else "label"
            e.update(cls="ambiguous", reason=r.get("reason"), printed_at=locs)
            for loc in locs:
                file, _, line = loc.rpartition(":")
                for b in overlapping(file, int(line), int(line)) if line.isdigit() else []:
                    if all(x["claim"] != b for x in e["candidates"]):
                        e["candidates"].append({"claim": b, "by": [basis]})
            continue
        if target is not None:
            # Its text (or, for a changed passage, its label) is at one place of the later
            # revision: the later claim pinned there, else the one pinned across it.
            basis = "text" if own else "label"
            here = at(p["kind"], target)
            near = [] if here else overlapping(*span_of(p["kind"], target, env))
            if len(here) == 1:
                e.update(match=here[0], by=[basis], own=own)
            elif len(near) == 1:
                b = near[0]
                e.update(match=b, by=[basis, "overlap"],
                         own=own and pb[b]["passage"] == p["passage"])
            elif here or near:
                e.update(cls="ambiguous", printed_at=[r.get("to")],
                         reason=f"{len(here or near)} claims of the later inventory are pinned "
                         + ("at" if here else "across") + " its passage")
                e["candidates"] = [{"claim": b, "by": [basis] + ([] if here else ["overlap"])}
                                   for b in here or near]
            else:
                e.update(cls="removed", printed_at=[r.get("to")],
                         reason=f"its {basis} is printed at {r.get('to')} in the later "
                         "revision, and the later inventory has no claim there")
            continue
        # Neither its text nor its label leads to one passage: what the line diff proposes.
        e.update(cls="removed", reason=r.get("reason") or "no passage of the later revision has "
                 "its text")
        prop = r.get("proposed") or {}
        if prop.get("location") and "reason" not in prop:
            try:
                region = extract(new.root, {"location": prop["location"],
                                            "source_region": prop["source_region"]})
                e["candidates"] = [{"claim": b, "by": ["line-diff"]} for b in overlapping(
                    region.file, region.start_line, region.end_line)]
            except (RegionError, OSError, UnicodeError):
                pass

    # A later claim two earlier claims lead to is matched to neither.
    claimed: dict[str, list[str]] = {}
    for cid, e in entries.items():
        if e.get("match"):
            claimed.setdefault(e["match"], []).append(cid)
    for b, cids in claimed.items():
        if len(cids) > 1:
            for cid in cids:
                e = entries[cid]
                e.update(cls="ambiguous", reason=f"{len(cids)} earlier claims ("
                         + ", ".join(cids) + f") lead to the later claim {b}")
                e["candidates"] = [{"claim": b, "by": e.pop("by")}]
                e["by"] = []
                e.pop("match")
                e.pop("own", None)
    matched = {e["match"] for e in entries.values() if e.get("match")}

    # What proposes a match for the others: a later claim with its number or its id.
    for cid, e in entries.items():
        if e.get("match"):
            continue
        number = old.number(ca[cid])
        for b, c in cb.items():
            if b in matched:
                continue
            why = (["number"] if number and _same_number(number, new.number(c)) else []) + \
                (["id"] if b == cid else [])
            if not why:
                continue
            row = next((x for x in e["candidates"] if x["claim"] == b), None)
            if row is None:
                e["candidates"].append({"claim": b, "by": why})
            else:
                row["by"] += [w for w in why if w not in row["by"]]
        e["candidates"] = [x for x in e["candidates"] if x["claim"] not in matched]
        if e["candidates"] and e["cls"] == "removed":
            e["cls"] = "ambiguous"
            e["reason"] += ("; " + _proposal_words(e["candidates"])
                            + ": a proposed match, to resolve by hand")

    for old_id, new_id in resolve:
        _resolve(entries, ca, cb, pa, pb, old_id, new_id, matched)

    # The class of each match from its own text, place and number; then its context.
    for cid, e in entries.items():
        b = e.get("match")
        if b is None:
            continue
        p, q = pa[cid], pb[b]
        e["to"] = _side_record(new, cb[b], q)
        x, y = old.number(ca[cid]), new.number(cb[b])
        e["renumbered"] = bool(x and y) and not _same_number(x, y)
        if not e["own"]:
            e["cls"] = "changed"
            e["reason"] = _changed_words(e)
            e["change"] = _own_change(e, p, q, old, new)
            continue
        same_place = (p["kind"] == q["kind"] and _key(p["kind"], p["bounds"])
                      == _key(q["kind"], q["bounds"]))
        e["moved"] = not same_place
        e["cls"] = "moved" if (e["renumbered"] or not same_place) else "unchanged"
        e["reason"] = ("the same text" + (" at another place" if not same_place else "")
                       + (f", now {y}" if e["renumbered"] else "")
                       + ("" if not same_place or e["renumbered"] else " at the same place"))
        if e.get("plan", {}).get("context_changed"):
            e["surroundings_changed"] = True
    for cid, e in entries.items():
        if e.get("match"):
            e["context"] = _context(e, pa[cid], pb[e["match"]], sa, sb)
    # Claims it refers to, or whose definitions its Lean relies on, as each one now stands.
    standing = {cid: e["cls"] if not (e.get("context") and e["cls"] in ("moved", "unchanged"))
                else "context-changed" for cid, e in entries.items()}
    labels = _labels(ca, pa)
    earlier = {e["match"]: cid for cid, e in entries.items() if e.get("match")}
    for cid, e in entries.items():
        if e.get("match"):
            e["context"] += _relied_on(cid, e, pa[cid], labels, standing, earlier, old, new, ca)
            if e["context"] and e["cls"] in ("moved", "unchanged"):
                e["cls"] = "context-changed"
                e["reason"] += "; " + "; ".join(dict.fromkeys(_context_words(x)
                                                              for x in e["context"]))

    rows = []
    for cid, e in entries.items():
        rows.append(_row(e))
    candidate_for: dict[str, list[str]] = {}
    for cid, e in entries.items():
        for x in e["candidates"]:
            candidate_for.setdefault(x["claim"], []).append(cid)
    taken = {e["match"] for e in entries.values() if e.get("match")}
    for b, c in cb.items():
        if b in taken:
            continue
        row = {"class": "new", "reason": "no earlier claim is matched to it", "from": None,
               "to": _side_record(new, c, pb[b])}
        if b in candidate_for:
            row["candidate_for"] = candidate_for[b]
            row["reason"] += "; it is a candidate for " + ", ".join(candidate_for[b])
        rows.append(row)
    order = {k: i for i, k in enumerate(CLASSES)}
    rows.sort(key=lambda r: (order[r["class"]], (r["from"] or r["to"])["claim"]))
    doc = {"schema": SCHEMA, "paper": paper, "from": old.identity or {"revision": old.revision},
           "to": new.identity or {"revision": new.revision},
           "counts": {k: n for k in CLASSES if (n := sum(r["class"] == k for r in rows))},
           "claims": rows, "new_passages": new_passages,
           "note": ("Each side's facts are those its own revision and release recorded. A match "
                    "changes no status and carries no review over; a proposed match (by number, "
                    "id or line diff) is not a match until a maintainer resolves it.")}
    doc["numbers"] = numbers(doc)
    return doc


def _proposal_words(cands: list[dict]) -> str:
    words = {"line-diff": "the line diff of its file", "number": "its number", "id": "its id"}
    return "; ".join(f"{x['claim']} has " + " and ".join(words.get(b, b) for b in x["by"])
                     for x in cands)


def _changed_words(e: dict) -> str:
    if "maintainer" in e["by"]:
        return "matched by the maintainer; its text differs"
    if "overlap" in e["by"]:
        return "the later inventory pins other bounds around its passage"
    return "its label leads to a passage with other text"


def _own_change(e: dict, p: dict, q: dict, old: Side, new: Side) -> dict:
    """The exact change of a passage: where it first differs, and the diff of the two texts."""
    r = e.get("plan") or {}
    out = {}
    if r.get("where") and "label" in e["by"] and "overlap" not in e["by"]:
        out["where"] = r["where"]
    out["diff"] = _diff(p["lines"], q["lines"], f"{p['location']} at {old.revision}",
                        f"{q['location']} at {new.revision}")
    return out


def _resolve(entries, ca, cb, pa, pb, old_id, new_id, matched) -> None:
    if old_id not in ca:
        raise MapError(f"--match {old_id}={new_id}: the earlier inventory has no claim {old_id}")
    if new_id not in cb:
        raise MapError(f"--match {old_id}={new_id}: the later inventory has no claim {new_id}")
    e = entries[old_id]
    if e.get("match"):
        raise MapError(f"--match {old_id}={new_id}: {old_id} is already matched to "
                       f"{e['match']} by its {e['by'][0]}; a resolution takes only an "
                       "unmatched claim")
    if new_id in matched:
        other = next(c for c, x in entries.items() if x.get("match") == new_id)
        raise MapError(f"--match {old_id}={new_id}: {new_id} is already matched to {other}")
    if pa[old_id].get("error") or pb[new_id].get("error"):
        raise MapError(f"--match {old_id}={new_id}: a passage cannot be read: "
                       + (pa[old_id].get("error") or pb[new_id].get("error")))
    cand = next((x for x in e["candidates"] if x["claim"] == new_id), None)
    e["resolved"] = {"by": "maintainer", "was": e["cls"], "reason": e.get("reason"),
                     "candidates": e["candidates"]}
    e.update(match=new_id, by=["maintainer"] + (cand["by"] if cand else []), candidates=[],
             own=pa[old_id]["passage"] == pb[new_id]["passage"])
    matched.add(new_id)
    # The claim it took is no longer a candidate for another; their classes stand.
    for x in entries.values():
        x["candidates"] = [c for c in x["candidates"] if c["claim"] != new_id]


# -- the context a passage is read with ----------------------------------------------------------

def _context(e: dict, p: dict, q: dict, sa: _Snapshot, sb: _Snapshot) -> list[dict]:
    """What the passage is read with that changed: the further passages of its pin, the
    definitions of the macros it uses, and the prose that opens its section."""
    out = []
    for i, row in enumerate((e.get("plan") or {}).get("parts") or [], start=1):
        if row["class"] not in ("unchanged", "moved"):
            out.append({"what": "macro definition" if row.get("macro") else "passage",
                        "part": i, **({"macro": row["macro"]} if row.get("macro") else {}),
                        "change": row["class"], "reason": row.get("reason"),
                        "from": {"location": row["part"]},
                        "to": {"location": row["to"]} if row.get("to") else None})
    pinned = {part.get("macro") for part, _ in (p["pin"].parts if p["kind"] == "region" else ())}
    texts_a = [p["text"]] + ([r.text for part, r in p["pin"].parts if not part.get("macro")]
                             if p["kind"] == "region" else [])
    texts_b = [q["text"]] + ([r.text for part, r in q["pin"].parts if not part.get("macro")]
                             if q["kind"] == "region" else [])
    used = set().union(*(used_macros(t) for t in texts_a + texts_b)) - pinned
    for name in sorted(used):
        x, y = sa.macro(name), sb.macro(name)
        if (x or {}).get("sha256") == (y or {}).get("sha256"):
            continue
        out.append({"what": "macro", "macro": name,
                    "change": "changed" if x and y else "removed" if x else "added",
                    "from": {k: x[k] for k in ("defined", "sha256")} if x else None,
                    "to": {k: y[k] for k in ("defined", "sha256")} if y else None,
                    "diff": _diff((x or {}).get("text", "").split("\n") if x else [],
                                  (y or {}).get("text", "").split("\n") if y else [],
                                  "earlier definition", "later definition")})
    oa, ob = _opening(sa, p), _opening(sb, q)
    if (oa or {}).get("text") != (ob or {}).get("text"):
        out.append({"what": "standing assumption",
                    "section": (ob or oa or {}).get("section"),
                    "change": "changed" if oa and ob else "removed" if oa else "added",
                    "from": {k: oa[k] for k in ("location", "section")} if oa else None,
                    "to": {k: ob[k] for k in ("location", "section")} if ob else None,
                    "diff": _diff(oa["lines"] if oa else [], ob["lines"] if ob else [],
                                  "earlier opening of the section",
                                  "later opening of the section")})
    return out


def _opening(snap: _Snapshot, p: dict) -> dict | None:
    """The prose that opens the section of a passage (`requirements.section_opening`)."""
    file, first = p["bounds"]["file"], p["bounds"]["start_line"]
    lines = snap.lines(file)
    found = section_opening(lines, first)
    if found is None:
        return None
    a, b, title = found
    return {"location": f"{file}:{a}", "section": title, "lines": lines[a - 1:b],
            "text": "\n".join(lines[a - 1:b])}


def _labels(ca: dict, pa: dict) -> dict[str, str]:
    """The earlier revision's labels, each with the claim it belongs to: a claim's own label
    and id, and the labels its printed passage carries."""
    out = {}
    for cid, c in ca.items():
        names = set(repin._names_of(c))
        if not pa[cid].get("error"):
            names |= {n for n, _ in repin.labels(pa[cid]["text"])}
        for n in names:
            out.setdefault(n, cid)
    return out


def _relied_on(cid: str, e: dict, p: dict, labels: dict, standing: dict, earlier: dict,
               old: Side, new: Side, ca: dict) -> list[dict]:
    """The claims this one relies on whose own passage is not shown unchanged: those its
    passage refers to (`\\ref`), and the definition claims of the definitions its Lean relies
    on in either build (a later definition claim stands for the earlier claim matched to it,
    `earlier`). One level: what relies on this claim is not reopened through it."""
    found: dict[str, dict] = {}
    for lab in dict.fromkeys(REF.findall(p["text"])):
        other = labels.get(lab)
        if other and other != cid:
            found.setdefault(other, {"via": [], "label": lab})["via"].append("reference")
    for side, mine in ((old, old.uses.get(cid)), (new, new.uses.get(e["match"]))):
        for d, names in (mine or {}).items():
            d_old = d if side is old else earlier.get(d)
            if d_old is None or d_old == cid:
                continue
            row = found.setdefault(d_old, {"via": []})
            if "lean" not in row["via"]:
                row["via"].append("lean")
            row.setdefault("names", [])
            row["names"] += [n for n in names if n not in row["names"]]
    out = []
    for other, row in found.items():
        cls = standing.get(other)
        if cls not in UNSETTLED:
            continue
        c = ca.get(other) or {}
        out.append({"what": "definition" if c.get("kind") == "definition" else "reference",
                    "claim": other, "number": old.number(c) if c else None,
                    "change": cls, "via": row["via"],
                    **({"label": row["label"]} if row.get("label") else {}),
                    **({"names": row["names"]} if row.get("names") else {})})
    return out


def _context_words(x: dict) -> str:
    if x["what"] == "macro":
        return f"the definition of {x['macro']} {x['change']}"
    if x["what"] == "standing assumption":
        return f"the prose opening its section {x['change']}"
    if x["what"] in ("passage", "macro definition"):
        return f"part {x['part']} of its pin {x['change']}"
    what = "the definition" if x["what"] == "definition" else "the claim"
    return f"{what} it relies on, {x.get('number') or x['claim']}, is {x['change']}"


def _row(e: dict) -> dict:
    out = {"class": e["cls"], "reason": e.get("reason"), "from": e["from"], "to": e["to"],
           "by": e["by"]}
    for k in ("renumbered", "moved", "surroundings_changed", "change", "printed_at",
              "resolved"):
        if e.get(k) not in (None, False, [], {}):
            out[k] = e[k]
    if e.get("context"):
        out["context"] = e["context"]
    if e["candidates"]:
        out["candidates"] = e["candidates"]
    plan = e.get("plan") or {}
    if plan.get("proposed") and e["cls"] in ("removed", "ambiguous"):
        out["proposed"] = {k: v for k, v in plan["proposed"].items() if k != "advice"}
    return out


# -- the numbers ---------------------------------------------------------------------------------

def numbers(doc: dict) -> list[dict]:
    """For each earlier claim with a number, its counterparts' numbers in the later revision:
    one for a match, every candidate's for an ambiguous claim, none for a removed one, with the
    class and basis of the match. `numbering.resolve` reads these."""
    later = {r["to"]["claim"]: r["to"] for r in doc["claims"] if r.get("to")}
    out = []
    for r in doc["claims"]:
        a = r.get("from")
        if not a or not a.get("number"):
            continue
        if r.get("to"):
            new = [r["to"]["number"]] if r["to"].get("number") else []
            claims = [r["to"]["claim"]]
        else:
            claims = [x["claim"] for x in r.get("candidates") or []]
            new = list(dict.fromkeys(later[c]["number"] for c in claims
                                     if c in later and later[c].get("number")))
        if not new and r["class"] != "removed":
            # A match or candidates without a number say nothing about the number.
            continue
        out.append({"old": a["number"], "new": new,
                    "match": {"class": r["class"], "by": r.get("by") or [],
                              "from": a["claim"], "to": claims}})
    return out


def numbering_map(doc: dict) -> dict:
    """The map in the form `numbering.analyse` and `numbering.resolve` read."""
    return {"source": {"schema": SCHEMA, "paper": doc["paper"],
                       "from": {k: doc["from"].get(k) for k in ("release", "revision")
                                if doc["from"].get(k)},
                       "to": {k: doc["to"].get(k) for k in ("release", "revision")
                              if doc["to"].get(k)}},
            "entries": doc["numbers"]}


# -- two releases ----------------------------------------------------------------------------------

def release_facts(v, cid: str) -> dict | None:
    """What a release's build recorded of a claim: its status and the review of each of its
    statements and definitions (and of a proof step), each as that build counted it."""
    from .changes import _marker
    a = v.assessed.get(cid)
    if a is None:
        return None
    reviews = []
    for cl in a.get("clauses") or []:
        rows = ([("spec", cl["spec"], cl.get("spec_review"))] if cl.get("spec") else []) + \
            [("def", d, r) for d, r in (cl.get("def_reviews") or {}).items()]
        for target, name, r in rows:
            m = _marker(r) or {}
            reviews.append({"target": target, "name": name, "clause": cl.get("name"),
                            "state": (r or {}).get("state"),
                            **({"by": m["by"], "kind": m.get("kind")} if m else {})})
    step = a.get("step_review")
    if step:
        f = step.get("finding") or {}
        reviews.append({"target": "step", "name": cid, "state": step.get("state"),
                        **({"by": f["reviewer"]["id"]} if f.get("reviewer") else {})})
    passage = v.passage(cid) or {}
    return {"status": a.get("status"), "status_code": a.get("status_code"),
            "source_matches_pin": passage.get("matches_pin"), "reviews": reviews}


def printed_numbers(claims: list[dict], anchors: list[dict]) -> dict[str, str]:
    """Each claim's number as the compiled paper prints it, from the environment that carries
    its label; a claim the compiled paper finds otherwise keeps the inventory's number."""
    out = {}
    for c in claims:
        names = repin._names_of(c)
        a = next((a for a in anchors if a.get("label") and a["label"] in names), None)
        if a and a.get("number") and a.get("env"):
            env = a["env"].rstrip("*")
            n = f"({a['number']})" if env in repin.DISPLAYS else a["number"]
            out[c["id"]] = f"{env.capitalize()} {n}"
    return out


def lean_uses(v, claims: list[dict]) -> dict[str, dict[str, list[str]]]:
    """For each claim, the definition claims whose definitions are in the meaning of its
    clauses in this build (`changes.Version.closure`), with those definitions."""
    named: dict[str, list[str]] = {}
    for c in claims:
        for cl in c.get("clauses") or []:
            for d in cl.get("defs") or []:
                named.setdefault(d, []).append(c["id"])
    out: dict[str, dict[str, list[str]]] = {}
    for c in claims:
        for cl in c.get("clauses") or []:
            if not cl.get("spec"):
                continue
            for name in v.closure(cl):
                for d in named.get(name, []):
                    if d != c["id"]:
                        rows = out.setdefault(c["id"], {}).setdefault(d, [])
                        if name not in rows:
                            rows.append(name)
    return out


def verify(v, paper: str, snap_root: Path) -> tuple[int, list[str]]:
    """Check that a manuscript holds the text a release recorded: for each claim of the paper,
    the digest of its passage there against the one its build recorded (a region's, or the
    environment's anchor's). Returns how many were checked and the claims that differ."""
    from .assess import match_anchor
    snap = _Snapshot(snap_root)
    tex = v.tex.get(paper) or {}
    regions, anchors = tex.get("regions") or {}, tex.get("anchors") or []
    checked, differ = 0, []
    for c in v.claims.values():
        if c["paper"] != paper:
            continue
        rec = regions.get(c["id"])
        if rec is not None:
            if rec.get("error") or not rec.get("sha256"):
                continue
            want = rec["sha256"]
        else:
            a = match_anchor(c, anchors) if location(c) is None else None
            if not a or not a.get("source_sha256"):
                continue
            want = a["source_sha256"]
        checked += 1
        got = printed(snap, c)
        if got.get("error") or got["sha256"] != want:
            differ.append(c["id"])
    return checked, differ


def between(cfg, paper_id: str | None = None, old_release: str | None = None,
            new_release: str | None = None, old_source: str | None = None,
            new_source: str | None = None, resolve=()) -> dict:
    """The version map of a paper between two releases of the full assessment (by default the
    latest and the one before it), from the manuscript of each release's revision: a folder or
    `git:REV` given for it, else its Git or arXiv source at the revision the release recorded,
    else the configured folder. A manuscript that does not hold the text its release recorded
    is refused. The later release's references to paper numbers that disagree with its paper
    (`content.py`) are given with the counterpart the map names (`references`)."""
    import tempfile
    from . import changes as chg
    paper = _paper(cfg, paper_id)
    old_name, old_rec, new_name, new_rec = chg.records(cfg.out_dir, old_release, new_release)
    vo, vn = chg.Version(old_rec, old_name), chg.Version(new_rec, new_name)
    with tempfile.TemporaryDirectory(prefix="machinechecked-version-map-") as temp:
        sides = []
        for v, given, where in ((vo, old_source, "from"), (vn, new_source, "to")):
            root, how = _manuscript(cfg, paper, v, given, Path(temp) / where, where)
            n, differ = verify(v, paper.id, root)
            if differ:
                raise MapError(
                    f"the manuscript {how} does not hold the text release {v.release} recorded "
                    f"for {len(differ)} of {n} claims (such as {differ[0]}): pass --{where}-source "
                    f"DIR (or git:REV) with the manuscript release {v.release} was built from")
            prov = ((v.body.get("provenance") or {}).get("papers") or {}).get(paper.id) or {}
            claims = [c for c in v.claims.values() if c["paper"] == paper.id]
            tex = v.tex.get(paper.id) or {}
            rev = prov.get("revision")
            identity = {"release": v.release, "evidence": v.id, "revision": rev,
                        "paper_version": (prov.get("paper_version") or {}).get("id"),
                        "manuscript": how, "checked": n}
            sides.append(Side(claims, root,
                              f"{v.release}" + (f" (revision {rev[:12]})" if rev else ""),
                              numbers=printed_numbers(claims, tex.get("anchors") or []),
                              facts=lambda cid, v=v: release_facts(v, cid),
                              uses=lean_uses(v, claims), identity=identity))
        doc = compare(paper.id, sides[0], sides[1], resolve)
    doc["references"] = later_references(cfg, vn, paper.id, doc)
    return doc


def _paper(cfg, paper_id: str | None):
    if paper_id:
        return cfg.paper(paper_id)
    if len(cfg.papers) != 1:
        raise MapError("the configuration has several papers: name one with --paper ("
                       + ", ".join(p.id for p in cfg.papers) + ")")
    return cfg.papers[0]


def _manuscript(cfg, paper, v, given: str | None, dest: Path, where: str) -> tuple[Path, str]:
    """The manuscript of a release's revision of the paper, and how it was obtained."""
    from .source_regions import folder
    from .sources import SourceError, acquire
    tex = v.tex.get(paper.id) or {}
    if tex.get("mode") == "pdf":
        raise MapError(f"release {v.release} read paper {paper.id} from its PDF: there is no "
                       "manuscript to compare")
    if given:
        return folder(cfg, paper, given, dest), given
    src = paper.source
    if "path" in src:
        return folder(cfg, paper, str((cfg.root / src["path"]).resolve()), dest), \
            f"the configured folder {src['path']}"
    rev = (((v.body.get("provenance") or {}).get("papers") or {}).get(paper.id) or {}) \
        .get("revision")
    if not rev:
        raise MapError(f"release {v.release} recorded no revision of paper {paper.id}: pass "
                       f"--{where}-source DIR")
    key = "rev" if "git" in src else "arxiv"
    try:
        snap = acquire(cfg, dataclasses.replace(paper, source={**src, key: rev}), dest)
    except SourceError as error:
        raise MapError(f"the revision {rev} of paper {paper.id} cannot be read ({error}): pass "
                       f"--{where}-source DIR") from None
    if snap.mode != "latex":
        raise MapError(f"the revision {rev} of paper {paper.id} holds no LaTeX source")
    return snap.dir, f"revision {rev}"


def later_references(cfg, vn, paper: str, doc: dict) -> dict | None:
    """The later release's references to paper numbers that disagree with its paper, each with
    the counterpart the map gives the number in the earlier revision (`numbering.resolve`).
    None when the later build has no paper-number check (no Lean was built)."""
    from . import content as cm
    from . import numbering as nb
    found = cm.load(cfg.out_dir, vn.id, vn.body)
    num = (found or {}).get("numbering")
    if not num:
        return None
    if num.get("papers"):
        num = nb.paper_view(num, paper)
    refs = [deepcopy(o) for o in num.get("references") or [] if nb.suspect(o)]
    _, inv = cm.paper_inventory(paper, vn.tex, list(vn.claims.values()), {})
    nb.resolve(refs, numbering_map(doc), inv["statements"])
    return {"references": refs,
            "resolved": sum(1 for o in refs if (o.get("current") or {}).get("reference")),
            "ambiguous": sum(1 for o in refs if (o.get("current") or {}).get("ambiguous")),
            "none": sum(1 for o in refs if (o.get("current") or {}).get("none"))}


# -- text ------------------------------------------------------------------------------------------

BY_WORDS = {"text": "its text", "label": "its label", "overlap": "the bounds pinned across it",
            "maintainer": "the maintainer", "line-diff": "the line diff of its file",
            "number": "its number", "id": "its id"}


def _side_words(s: dict) -> str:
    rec = s.get("recorded") or {}
    status = f"; status {rec['status']}" if rec.get("status") else ""
    head = f"{s.get('number') or s['claim']} ({s['claim']})"
    if s.get("error"):
        return f"{head}: {s['error']}{status}"
    pin = {"differs": ", its pin is of other text", "none": ", not pinned"}.get(s.get("pin"), "")
    return f"{head} at {s.get('location')}{pin}{status}"


def _revision_words(side: dict) -> str:
    rev = f"revision {side.get('revision') or 'not recorded'}"
    return f"release {side['release']} ({rev})" if side.get("release") else rev


def text(doc: dict, everything: bool = False) -> str:
    """The map as lines for a terminal: the revisions, the counts, then each claim that is not
    unchanged (every claim with `everything`), and the paper references it resolves."""
    lines = [f"paper {doc['paper']}: version map from {_revision_words(doc['from'])} to "
             f"{_revision_words(doc['to'])}",
             "claims: " + ", ".join(f"{n} {k}" for k, n in doc["counts"].items())]
    for r in doc["claims"]:
        if r["class"] == "unchanged" and not everything:
            continue
        lines.append("")
        head = (r["from"] or r["to"])
        by = (" (by " + " and ".join(BY_WORDS.get(x, x) for x in r["by"]) + ")") \
            if r.get("by") else ""
        lines.append(f"{head.get('number') or head['claim']} ({head['claim']}): {r['class']}"
                     f"{by}: {r['reason']}")
        if r["from"]:
            lines.append(f"  earlier: {_side_words(r['from'])}")
        if r["to"]:
            lines.append(f"  later:   {_side_words(r['to'])}")
        for x in r.get("candidates") or []:
            lines.append(f"  candidate: {x['claim']} (by "
                         + " and ".join(BY_WORDS.get(y, y) for y in x["by"]) + ")")
        if r.get("resolved"):
            lines.append(f"  resolved by the maintainer; it was {r['resolved']['was']}")
        if r.get("surroundings_changed"):
            lines.append("  note: the lines beside its passage changed")
        for x in r.get("context") or []:
            lines.append(f"  context: {_context_words(x)}")
            lines += ["    " + ln for ln in x.get("diff") or []]
        ch = r.get("change") or {}
        if ch:
            lines.append("  its passage: " + (ch.get("where") or "the text changed"))
            lines += ["    " + ln for ln in ch.get("diff") or []]
    refs = doc.get("references")
    if refs and refs["references"]:
        lines.append("")
        lines.append("paper references of the Lean that disagree with the later revision:")
        from .numbering import message
        for o in refs["references"]:
            lines.append(f"  {message(o)}")
    lines.append("")
    lines.append(doc["note"])
    return "\n".join(lines)
