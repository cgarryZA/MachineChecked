"""Change the bounds of claims' source regions at the paper revision they are pinned at
(docs/SOURCE_REGIONS.md, "Changing a region's bounds").

A pin is replaced only at its own revision: the snapshot must be the revision the claim was
pinned at, and the claim's present pin must match it there, so that the new digests are of the
same manuscript. The new bounds are refused when they start or end on a blank or comment-only
line, and, unless allowed, when they run across a sectioning command. The new digests are
computed as `source_regions` computes them. A new passage is a new text: the claim's scope
decision is marked as needing a new reading, and every review marker that recorded the old
digest reads the claim as changed.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import tempfile

from .source_regions import (
    SCHEME, RegionError, extract, location, same_revision, source_file, write_plan,
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
    """The claim's present passage at `revision`, after checking that its pin matches it."""
    if location(claim) is None:
        raise RegionError(f"{claim['id']}: it is not pinned by line; a region is given by a "
                          "file:line location")
    scheme = claim.get("source_hash_scheme")
    if scheme == SCHEME:
        region = extract(root, claim)
        if region.sha256 != claim.get("source_sha256"):
            raise RegionError(f"{claim['id']}: its passage at {revision} differs from its pin; "
                              "the snapshot is not the text it was pinned to")
        return region
    if scheme is not None:
        raise RegionError(f"{claim['id']}: unknown source hash scheme {scheme!r}")
    name, line = location(claim)
    original = source_file(root, name).read_text(encoding="utf-8").split("\n")[line - 1]
    legacy = hashlib.sha256(" ".join(original.split()).encode("utf-8")).hexdigest()
    if claim.get("source_sha256") != legacy:
        raise RegionError(f"{claim['id']}: its legacy line hash does not match {revision}")
    return None


def rebound_plan(inventory: dict, paper: str, root: Path, revision: str,
                 requests: list[dict], across_sections: bool = False) -> tuple[dict, list]:
    """The inventory with each requested claim's region set to its new bounds at `revision`,
    and one change record per claim. `requests` holds `claim`, `start`, `end` (None: the
    passage that starts there), and optional `file`, `start_column`, `end_column`. Raises
    RegionError, writing nothing, when any request is refused."""
    result = deepcopy(inventory)
    by_id = {c["id"]: c for c in result["claims"] if c["paper"] == paper}
    papers_pin = ((inventory.get("papers") or {}).get(paper) or {}).get("commit")
    changes, seen = [], set()
    for req in requests:
        cid = req["claim"]
        if cid not in by_id:
            raise RegionError(f"{cid}: no claim of paper {paper} has this id")
        if cid in seen:
            raise RegionError(f"{cid}: given twice")
        seen.add(cid)
        claim = by_id[cid]
        pin = claim.get("commit") or papers_pin
        if not pin or not same_revision(str(pin).removeprefix("arxiv:"), revision):
            raise RegionError(f"{cid}: it is pinned at revision {pin}, not {revision}; change "
                              "its bounds at the revision it is pinned at")
        old = _verified(root, claim, revision)
        name = req.get("file") or location(claim)[0]
        new_claim = {**claim, "location": f"{name}:{req['start']}"}
        new_claim.pop("source_region", None)
        if req.get("end") is not None or req.get("start_column") or req.get("end_column"):
            span = {"end_line": req["end"] if req.get("end") is not None else req["start"]}
            for k in ("start_column", "end_column"):
                if req.get(k):
                    span[k] = req[k]
            new_claim["source_region"] = span
        try:
            region = extract(root, new_claim)
        except (RegionError, OSError, UnicodeError) as error:
            raise RegionError(f"{cid}: the new bounds: {error}") from None
        first, last = _ends(region)
        for which, text in (("start", first), ("end", last)):
            if not text.strip() or text.lstrip().startswith("%"):
                raise RegionError(f"{cid}: the new bounds {which} on a blank or comment-only "
                                  "line; select the passage itself")
        crossing = [region.start_line + i for i, ln in enumerate(region.text.split("\n"))
                    if i and SECTION.search(COMMENT.sub("", ln))]
        if crossing and not across_sections:
            raise RegionError(f"{cid}: the new bounds run across a sectioning command (line "
                              f"{crossing[0]} of {region.file}); pass --across-sections if "
                              "the passage does")
        if old is None:
            line = source_file(root, location(claim)[0]).read_text(
                encoding="utf-8").split("\n")[location(claim)[1] - 1]
            was = {"file": location(claim)[0], "start_line": location(claim)[1],
                   "end_line": location(claim)[1], "kind": "legacy line hash", "first": line,
                   "last": line}
        entry = {"claim": cid, "old": _bounds(old) if old else was,
                 "new": _bounds(region), "old_sha256": claim.get("source_sha256"),
                 "sha256": region.sha256}
        if old is not None and region.sha256 == old.sha256 and \
                new_claim["location"] == claim["location"] and \
                new_claim.get("source_region") == claim.get("source_region"):
            entry["unchanged"] = True
            changes.append(entry)
            continue
        same = region.sha256 == old.sha256 if old is not None else (
            region.kind == "line" and new_claim["location"] == claim["location"])
        claim["location"] = new_claim["location"]
        if "source_region" in new_claim:
            claim["source_region"] = new_claim["source_region"]
        else:
            claim.pop("source_region", None)
        claim.update(source_hash_scheme=SCHEME, source_sha256=region.sha256,
                     source_line_sha256=region.line_sha256)
        if not same:
            # A different passage: the scope decision was taken on other text.
            entry["scope_reviewed"] = {"before": claim.get("scope_reviewed"), "after": False}
            claim["scope_reviewed"] = False
        changes.append(entry)
    return result, changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Change the bounds of claims' source regions at their pinned revision")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--claim", action="append", required=True,
                        help="a claim id (repeat, with one --lines each)")
    parser.add_argument("--lines", action="append", required=True,
                        help="the new bounds: A-B (lines A to B, inclusive), or A (the line or "
                        "display that starts on line A)")
    parser.add_argument("--file", help="the file of the new bounds (one claim only; default: "
                        "the claim's file)")
    parser.add_argument("--start-column", type=int, help="1-based column the passage starts at "
                        "(one claim only)")
    parser.add_argument("--end-column", type=int, help="1-based column the passage ends before "
                        "(one claim only)")
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
        if len(args.claim) != len(args.lines):
            raise RegionError("give one --lines for each --claim")
        if len(args.claim) > 1 and (args.file or args.start_column or args.end_column):
            raise RegionError("--file and the columns apply to one claim at a time")
        requests = []
        for cid, spec in zip(args.claim, args.lines):
            start, end = parse_lines(spec)
            requests.append({"claim": cid, "start": start, "end": end, "file": args.file,
                             "start_column": args.start_column, "end_column": args.end_column})
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        before = cfg.inventory.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-rebound-") as temp:
            root, revision = baseline(cfg, paper, inventory, Path(temp) / paper.id,
                                      args.source, args.rev)
            result, changes = rebound_plan(inventory, paper.id, root, revision, requests,
                                           args.across_sections)
        written = False
        if args.write and result != inventory:
            write_plan(cfg.inventory, before, result)
            written = True
        print(json.dumps({"applied": args.write, "written": written, "paper": paper.id,
                          "revision": revision, "changes": changes}, indent=2,
                         ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"rebound: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
