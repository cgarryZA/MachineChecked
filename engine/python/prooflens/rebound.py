"""Change the bounds of claims' source regions at the paper revision they are pinned at
(docs/SOURCE_REGIONS.md, "Changing a region's bounds"), or pin claims whose passage changed at a
new revision of the paper ("Pinning a changed passage at the new revision").

A pin is replaced only at its own revision: the snapshot must be the revision the claim was
pinned at, and the claim's present pin must match it there, so that the new digests are of the
same manuscript. With `--repin` the snapshot is instead the revision the inventory now records
for the paper, and the claim's pin is of another revision: its text here becomes the pinned
text, and the claim records this revision. The new bounds are refused when they start or end on
a blank or comment-only line, and, unless allowed, when they run across a sectioning command.
The new digests are computed as `source_regions` computes them, and the plan gives the advice a
build gives at the new bounds. A new passage is a new text: the claim's scope decision is marked
as needing a new reading, and every review marker that recorded the old digest reads the claim
as changed.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .repin import _names_of, _pin, statements, tex_files
from .source_regions import (
    MACRO, SCHEMES, RegionError, advice_message, changed_line, definition_part, definitions,
    held_passages, location, pin, pinned_elsewhere, region_advice, same_revision, source_file,
    tex_sources, theorem_names, unpinned_macros, write_plan,
)

COMMENT = re.compile(r"(?<!\\)%.*")
SECTION = re.compile(r"\\(?:part|chapter|section|subsection|subsubsection)\*?\s*[\[{]"
                     r"|\\appendix(?![A-Za-z@])")
LINES = re.compile(r"(\d+)(?:-(\d+))?")


def parse_lines(spec: str) -> tuple[int, int | None]:
    """`A` (the passage starting on line A, as a line or a display) or `A-B` (lines A to B)."""
    m = LINES.fullmatch(spec.strip())
    if not m:
        raise RegionError(f"--lines {spec!r}: give A or A-B, with line numbers")
    start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else None
    if start < 1 or (end is not None and end < start):
        raise RegionError(f"--lines {spec!r}: the lines are reversed or not positive")
    return start, end


def _ends(region) -> tuple[str, str]:
    """The first and last line of a passage, as selected (within its columns)."""
    lines = region.text.split("\n")
    return lines[0], lines[-1]


def _bounds(region) -> dict:
    first, last = _ends(region)
    return {"file": region.file, "start_line": region.start_line, "end_line": region.end_line,
            "start_column": region.start_column, "end_column": region.end_column,
            "kind": region.kind, "first": first, "last": last}


def _verified(root: Path, claim: dict, revision: str):
    """The claim's present pin at `revision` (None for a legacy line hash), after checking
    that it matches there."""
    if location(claim) is None:
        raise RegionError(f"{claim['id']}: it is not pinned by line; a region is given by a "
                          "file:line location")
    scheme = claim.get("source_hash_scheme")
    if scheme in SCHEMES:
        try:
            p = pin(root, claim)
        except RegionError as error:
            raise RegionError(f"{claim['id']}: at {revision}: {error}") from None
        if p.sha256 != claim.get("source_sha256"):
            raise RegionError(f"{claim['id']}: its passage at {revision} differs from its pin; "
                              "the snapshot is not the text it was pinned to")
        return p
    if scheme is not None:
        raise RegionError(f"{claim['id']}: unknown source hash scheme {scheme!r}")
    name, line = location(claim)
    original = source_file(root, name).read_text(encoding="utf-8").split("\n")[line - 1]
    legacy = hashlib.sha256(" ".join(original.split()).encode("utf-8")).hexdigest()
    if claim.get("source_sha256") != legacy:
        raise RegionError(f"{claim['id']}: its legacy line hash does not match {revision}")
    return None


def parse_part(spec: str) -> dict:
    """`FILE:A` or `FILE:A-B`: a further passage of a pin."""
    name, _, lines = spec.rpartition(":")
    if not name:
        raise RegionError(f"--also {spec!r}: give FILE:A or FILE:A-B")
    start, end = parse_lines(lines)
    return {"location": f"{name}:{start}", **({"end_line": end} if end else {})}


def parse_macro(spec: str) -> dict:
    """`\\name`, or `\\name@FILE:LINE` for one of several definitions."""
    name, _, at = spec.partition("@")
    if not MACRO.fullmatch(name):
        raise RegionError(f"--macro {spec!r}: give a control sequence such as \\name")
    if not at:
        return {"macro": name}
    file, _, line = at.rpartition(":")
    if not file or not line.isdigit():
        raise RegionError(f"--macro {spec!r}: give NAME@FILE:LINE")
    return {"macro": name, "file": file, "line": int(line)}


def _check(cid: str, region, what: str, across_sections: bool, sections: bool = True):
    first, last = _ends(region)
    for which, text in (("start", first), ("end", last)):
        if not text.strip() or text.lstrip().startswith("%"):
            raise RegionError(f"{cid}: {what}: the {which} line is blank or comment-only; "
                              "select the passage itself")
    crossing = [region.start_line + i for i, ln in enumerate(region.text.split("\n"))
                if i and SECTION.search(COMMENT.sub("", ln))]
    if sections and crossing and not across_sections:
        raise RegionError(f"{cid}: {what}: they cross a sectioning command (line "
                          f"{crossing[0]} of {region.file}); pass --across-sections if the "
                          "passage does")


def _legacy(line: str) -> str:
    """The legacy opening-line hash of a line: its whitespace collapsed."""
    return hashlib.sha256(" ".join(line.split()).encode("utf-8")).hexdigest()


def _same_text(claim: dict, new) -> bool:
    """Whether a claim's pin, of another revision, holds the text `new` pins there: the same
    digest under the same scheme, or a legacy hash of the one line `new` is."""
    scheme = claim.get("source_hash_scheme")
    if scheme is None:
        return not new.parts and new.main.kind == "line" and \
            claim.get("source_sha256") == _legacy(new.main.text)
    return scheme == new.scheme and claim.get("source_sha256") == new.sha256


def _recorded(claim: dict, revision: str) -> dict:
    """A claim's bounds as the inventory records them, and the revision its pin is of (whose
    text the snapshot does not hold)."""
    name, line = location(claim)
    span = claim.get("source_region") or {}
    out = {"file": name, "start_line": line, **span, "revision": revision}
    if claim.get("source_parts"):
        out["parts"] = [p["location"] for p in claim["source_parts"]]
    return out


def _commit(claim: dict, papers_pin, revision: str) -> str:
    """The revision a claim pinned at `revision` records: the paper's own pin, which names it,
    else `revision` in the form of the claim's present pin."""
    return str(papers_pin) if papers_pin else _pin(claim.get("commit"), revision, revision)


def _repin_environment(claim: dict, req: dict, root: Path, files: dict[str, str],
                       revision: str, rev_pin: str, commit: str, moving: bool) -> dict:
    """Pin a claim located by its environment (a file without a line, and the digest of the
    environment's body) at `revision`: the environment of its kind that carries its own label,
    hashed as the compiled paper's anchors hash it. A claim the compiled paper finds only by
    its printed number is refused, since numbers are computed by compiling. A claim already
    pinned at `revision` (not `moving`) must match it there, and is left as it is."""
    cid = claim["id"]
    if any(req.get(k) for k in ("start", "file", "start_column", "end_column")) or \
            req.get("parts") is not None:
        raise RegionError(f"{cid}: it is pinned by its environment, whose bounds are the "
                          "environment's own; give it no --lines, --file, columns or further "
                          "passages")
    if not claim.get("location") or claim.get("source_hash_scheme") is not None:
        raise RegionError(f"{cid}: its source pin has neither a line nor a file of an "
                          "environment; pin it by hand")
    kind = claim.get("kind")
    what = "environment" + (f" {kind}" if kind else "")
    found = [s for s in statements(root, files, kind) if _names_of(claim) & set(s.labels)]
    if not found:
        raise RegionError(f"{cid}: no {what} at {revision} carries its label; the compiled "
                          "paper finds it by its printed number, which this command does not "
                          "compute: pin it by hand")
    if len(found) > 1:
        raise RegionError(f"{cid}: its label is carried by {len(found)} environments at "
                          f"{revision} (" + ", ".join(f"{s.file}:{s.line}" for s in found)
                          + ")")
    s = found[0]
    if s.hidden:
        raise RegionError(f"{cid}: its label occurs only where the paper may not print it "
                          f"({s.file}:{s.line})")
    entry = {"claim": cid, "pin": "environment",
             "old": {"file": claim["location"], "revision": rev_pin},
             "new": {"file": s.file, "start_line": s.line, "environment": s.env},
             "old_sha256": claim.get("source_sha256"), "sha256": s.sha256}
    if not moving:
        if s.sha256 != claim.get("source_sha256") or s.file != claim["location"]:
            raise RegionError(f"{cid}: its environment at {revision} differs from its pin; the "
                              "snapshot is not the text it was pinned to")
        entry["unchanged"] = True
        return entry
    if not claim.get("source_sha256"):
        raise RegionError(f"{cid}: it has no source pin to move")
    entry["commit"] = {"before": claim.get("commit"), "after": commit}
    claim["location"] = s.file
    claim["commit"] = commit
    if s.sha256 != claim.get("source_sha256"):
        claim["source_sha256"] = s.sha256
        entry["scope_reviewed"] = {"before": claim.get("scope_reviewed"), "after": False}
        claim["scope_reviewed"] = False
    return entry


def rebound_plan(inventory: dict, paper: str, root: Path, revision: str,
                 requests: list[dict], across_sections: bool = False, repin: bool = False,
                 notation=()) -> tuple[dict, list]:
    """The inventory with each requested claim's region set to its new bounds at `revision`,
    and one change record per claim. `requests` holds `claim`, `start`, `end` (None: the
    passage that starts there), optional `file`, `start_column`, `end_column`, and `parts`:
    None keeps the further passages the pin lists, a list replaces them (`[]` removes them);
    each is a `location` with an optional `end_line`, or a `macro` (with an optional `file`
    and `line`) whose definition is pinned. Raises RegionError, writing nothing, when any
    request is refused.

    With `repin`, `revision` must be the one the inventory records for the paper, and a claim
    whose pin is of another revision is pinned at `revision` and records it (`commit`); one
    already pinned at `revision` is verified there, as without `repin`. A request whose `start`
    is None keeps the claim's present bounds; a claim pinned by its environment is found by its
    label. The text a moving claim has here need not be the text it was pinned to: the digests
    are of the text here, and when they differ the claim's scope decision reopens, as for any
    new bounds.

    Each record carries the advice a build gives at the new bounds: `advice`, where the region
    may not hold the claim's text, and `macros`, the macros its passages use that the
    manuscript defines outside them, other than the `notation` macros and those whose
    definitions another claim's pin holds (`pinned_elsewhere`, naming the claims)."""
    result = deepcopy(inventory)
    by_id = {c["id"]: c for c in result["claims"] if c["paper"] == paper}
    papers_pin = ((inventory.get("papers") or {}).get(paper) or {}).get("commit")
    if repin and papers_pin and not same_revision(str(papers_pin).removeprefix("arxiv:"),
                                                  revision):
        raise RegionError(f"the paper is pinned at revision {papers_pin} "
                          f"(papers.{paper}.commit), not {revision}; pin its claims at the "
                          "paper's revision (move the inventory with `machinechecked inventory "
                          "repin` first)")
    changes, seen, sources, files = [], set(), None, None
    defs = theorems = held = None
    for req in requests:
        cid = req["claim"]
        if cid not in by_id:
            raise RegionError(f"{cid}: no claim of paper {paper} has this id")
        if cid in seen:
            raise RegionError(f"{cid}: given twice")
        seen.add(cid)
        claim = by_id[cid]
        rev_pin = claim.get("commit") or papers_pin
        if not rev_pin:
            raise RegionError(f"{cid}: it records no paper revision; record the one it was "
                              f"pinned at (its commit, or papers.{paper}.commit) first")
        # A claim pinned at another revision moves to this one; with `repin`, one already pinned
        # here (a second run of the same command) is verified here as for any new bounds.
        moving = not same_revision(str(rev_pin).removeprefix("arxiv:"), revision)
        if moving and not repin:
            raise RegionError(f"{cid}: it is pinned at revision {rev_pin}, not {revision}; "
                              "change its bounds at the revision it is pinned at, or pin it "
                              "at this one with --repin")
        if repin and location(claim) is None:
            if files is None:
                files = tex_files(root)
            changes.append(_repin_environment(claim, req, root, files, revision, rev_pin,
                                              _commit(claim, papers_pin, revision), moving))
            continue
        if moving:
            if not claim.get("source_sha256"):
                raise RegionError(f"{cid}: it has no source pin to move")
            if claim.get("source_hash_scheme") not in (None, *SCHEMES):
                raise RegionError(f"{cid}: unknown source hash scheme "
                                  f"{claim['source_hash_scheme']!r}")
        old = None if moving else _verified(root, claim, revision)
        if req.get("start") is None:
            if not repin:
                raise RegionError(f"{cid}: no bounds given")
            new_claim = dict(claim)   # its present place and bounds
        else:
            name = req.get("file") or location(claim)[0]
            new_claim = {**claim, "location": f"{name}:{req['start']}"}
            new_claim.pop("source_region", None)
            if req.get("end") is not None or req.get("start_column") or req.get("end_column"):
                span = {"end_line": req["end"] if req.get("end") is not None else req["start"]}
                for k in ("start_column", "end_column"):
                    if req.get(k):
                        span[k] = req[k]
                new_claim["source_region"] = span
        if sources is None:
            sources = tex_sources(root)
            defs, theorems = definitions(sources), theorem_names(sources)
        wanted = req.get("parts")
        if wanted is None:
            wanted = [{k: v for k, v in p.items() if k not in ("sha256", "line_sha256")}
                      for p in claim.get("source_parts") or []]
        parts = []
        for want in wanted:
            if "location" in want and not (moving and want.get("macro")):
                parts.append({k: want[k] for k in ("location", "end_line", "start_column",
                                                   "end_column", "macro") if k in want})
            else:
                # A macro part kept at a new revision is delimited again there, from the
                # definition on its line: the definition's text, and so its extent, may differ.
                at = location(want) if "location" in want else (want.get("file"),
                                                                 want.get("line"))
                try:
                    parts.append(definition_part(sources, want["macro"], *at))
                except RegionError as error:
                    raise RegionError(f"{cid}: {error}") from None
        new_claim.pop("source_parts", None)
        new_claim.pop("source_hash_scheme", None)
        if parts:
            new_claim["source_parts"] = parts
        try:
            new = pin(root, new_claim)
        except (RegionError, OSError, UnicodeError) as error:
            raise RegionError(f"{cid}: the new bounds: {error}") from None
        _check(cid, new.main, "the new bounds", across_sections)
        for i, (part, region) in enumerate(new.parts, start=1):
            _check(cid, region, f"the bounds of part {i}", across_sections,
                   sections=not part.get("macro"))
        if moving:
            was = _recorded(claim, rev_pin)
        elif old is None:
            line = source_file(root, location(claim)[0]).read_text(
                encoding="utf-8").split("\n")[location(claim)[1] - 1]
            was = {"file": location(claim)[0], "start_line": location(claim)[1],
                   "end_line": location(claim)[1], "kind": "legacy line hash", "first": line,
                   "last": line}
        else:
            was = _bounds(old.main)
            if old.parts:
                was["parts"] = [{**_bounds(r), **({"macro": p["macro"]} if p.get("macro")
                                                 else {})} for p, r in old.parts]
        now = _bounds(new.main)
        if new.parts:
            now["parts"] = [{**_bounds(r), **({"macro": p["macro"]} if p.get("macro")
                                             else {})} for p, r in new.parts]
        entry = {"claim": cid, "old": was, "new": now, "old_sha256": claim.get("source_sha256"),
                 "sha256": new.sha256}
        notes = region_advice(root, new.main, theorems)
        if notes:
            rec = new.main.record()
            entry["advice"] = [{**n, "message": advice_message(cid, rec, n)} for n in notes]
        macros = [m for m in unpinned_macros(new, defs) if m["macro"] not in notation]
        if macros:
            if held is None:
                held = held_passages(inventory["claims"], paper, root)
            elsewhere, macros = pinned_elsewhere(cid, macros, held, root, sources, defs)
            if elsewhere:
                entry["pinned_elsewhere"] = elsewhere
        if macros:
            entry["macros"] = macros
        stored = [{**p, "sha256": r.sha256, "line_sha256": r.line_sha256}
                  for p, r in new.parts]
        if moving:
            same = _same_text(claim, new)
            if not same and (where := changed_line(claim, new.record())):
                entry["where"] = where
            commit = _commit(claim, papers_pin, revision)
            entry["commit"] = {"before": claim.get("commit"), "after": commit}
            claim["commit"] = commit
        elif old is not None and new.sha256 == old.sha256 and \
                new_claim["location"] == claim["location"] and \
                new_claim.get("source_region") == claim.get("source_region") and \
                stored == (claim.get("source_parts") or []):
            entry["unchanged"] = True
            changes.append(entry)
            continue
        else:
            same = new.sha256 == old.sha256 if old is not None else (
                not new.parts and new.main.kind == "line"
                and new_claim["location"] == claim["location"])
        claim["location"] = new_claim["location"]
        if "source_region" in new_claim:
            claim["source_region"] = new_claim["source_region"]
        else:
            claim.pop("source_region", None)
        claim.update(source_hash_scheme=new.scheme, source_sha256=new.sha256,
                     source_line_sha256=new.main.line_sha256)
        if stored:
            claim["source_parts"] = stored
        else:
            claim.pop("source_parts", None)
        if not same:
            # A different text: the scope decision was taken on other text.
            entry["scope_reviewed"] = {"before": claim.get("scope_reviewed"), "after": False}
            claim["scope_reviewed"] = False
        changes.append(entry)
    return result, changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Change the bounds of claims' source regions at their pinned revision, or "
        "pin them at the paper's new revision (--repin)")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--claim", action="append", required=True,
                        help="a claim id (repeat, with one --lines each)")
    parser.add_argument("--lines", action="append",
                        help="the new bounds: A-B (lines A to B, inclusive), or A (the line or "
                        "display that starts on line A); with --repin, leave it out to keep the "
                        "claims' present bounds")
    parser.add_argument("--repin", action="store_true",
                        help="pin claims whose pin is of an earlier revision at the revision "
                        "the inventory now records for the paper (after `inventory repin`): "
                        "their text there becomes the pinned text, and when it differs their "
                        "scope decision and the reviews that read them reopen")
    parser.add_argument("--file", help="the file of the new bounds (one claim only; default: "
                        "the claim's file)")
    parser.add_argument("--start-column", type=int, help="1-based column the passage starts at "
                        "(one claim only)")
    parser.add_argument("--end-column", type=int, help="1-based column the passage ends before "
                        "(one claim only)")
    parser.add_argument("--also", action="append", metavar="FILE:A-B",
                        help="a further passage the claim asserts (repeat; one claim only). "
                        "With --also or --macro the pin lists exactly these")
    parser.add_argument("--macro", action="append", metavar="NAME[@FILE:LINE]",
                        help="pin the definition of a macro the passage uses (repeat; one "
                        "claim only)")
    parser.add_argument("--single", action="store_true",
                        help="remove the further passages the pin lists")
    parser.add_argument("--across-sections", action="store_true",
                        help="allow bounds that run across a sectioning command")
    parser.add_argument("--source", help="the manuscript at the pinned revision: a folder, or "
                        "git:REV (default: the configured source)")
    parser.add_argument("--rev", help="the paper revision --source (or a configured folder) "
                        "holds (default: the inventory's papers.PAPER.commit)")
    parser.add_argument("--write", action="store_true",
                        help="apply the plan (default: print it only)")
    args = parser.parse_args(argv)
    from .config import load
    from .source_regions import baseline
    try:
        lines = args.lines or []
        if (lines or not args.repin) and len(args.claim) != len(lines):
            raise RegionError("give one --lines for each --claim"
                              + (", or none to keep their present bounds" if args.repin else ""))
        if not lines and (args.file or args.start_column or args.end_column):
            raise RegionError("--file and the columns are part of new bounds: give --lines")
        if len(args.claim) > 1 and (args.file or args.start_column or args.end_column
                                    or args.also or args.macro or args.single):
            raise RegionError("--file, the columns, --also, --macro and --single apply to one "
                              "claim at a time")
        if args.single and (args.also or args.macro):
            raise RegionError("--single removes the further passages; --also and --macro "
                              "list them")
        parts = None
        if args.also or args.macro or args.single:
            parts = [parse_part(x) for x in args.also or []] + \
                [parse_macro(x) for x in args.macro or []]
        requests = []
        for cid, spec in zip(args.claim, lines or [None] * len(args.claim)):
            start, end = parse_lines(spec) if spec is not None else (None, None)
            requests.append({"claim": cid, "start": start, "end": end, "file": args.file,
                             "start_column": args.start_column, "end_column": args.end_column,
                             "parts": parts})
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        before = cfg.inventory.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-rebound-") as temp:
            root, revision = baseline(cfg, paper, inventory, Path(temp) / paper.id,
                                      args.source, args.rev)
            result, changes = rebound_plan(inventory, paper.id, root, revision, requests,
                                           args.across_sections, args.repin,
                                           getattr(paper, "notation_macros", ()))
        written = False
        if args.write and result != inventory:
            write_plan(cfg.inventory, before, result)
            written = True
        print(json.dumps({"applied": args.write, "written": written, "paper": paper.id,
                          "revision": revision, "repin": args.repin, "changes": changes},
                         indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"rebound: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
