"""Retire the readings review markers record of passages that no longer state or name their
declaration (`machinechecked inventory retire`).

A marker records `source=<claim>@<digest>` for each passage its reviewer read beside the
declaration (`review_sources.py`). When the inventory moves a clause to another claim (a claim
split in two, a passage moved to a new entry), the markers of the clause's proposition still
record the old claim's passage. That entry is no reading of a passage that uses the declaration
now, so it is retired: removed, never rewritten to the new claim, and nothing is added. A marker
none of whose readings still applies is retired whole instead, with its readings as recorded
(below): it records a reading of passages that no longer use its declaration, and the claims
that now use it read as unread until someone reads their passages. A definition's marker is the
exception: when no claim names the definition, its review reads no passage (a closure may still
count it), so its readings are inert and the marker is left as it is.

With `--markers`, the plan also lists the markers whose declaration no claim uses any more: a
proposition no clause states, or a definition no claim names that is in no closure of the last
build's Lean results. With `--write` the markers to retire whole stay in their file, with their
review text and attributes, as `<!-- retired spec-review: ... -->`, which records no review
(`reviews.RETIRED`). Step markers are left alone.

The plan is printed as JSON; files change only with `--write`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .review_sources import reading_claims
from .reviews import MARKER, load_reviews


def _closure_names(lean: dict) -> set[str]:
    """Every declaration a closure of the Lean results holds."""
    out = set()
    for part in ("specs", "defs", "proofs"):
        for rec in (lean.get(part) or {}).values():
            out.update((rec or {}).get("closure") or [])
    return out


def plan(inventory: dict, reviews: list, lean: dict | None, markers: bool) -> dict:
    """The readings to retire (`readings`: per marker, the claims whose recorded passage no
    longer uses its declaration, and the readings it keeps), the markers to retire whole
    (`markers`: those none of whose readings still applies and, with `markers`, those whose
    declaration no claim uses), and the markers left as they are, with why (`left`)."""
    names = {d for c in inventory.get("claims", []) for cl in c.get("clauses") or []
             for d in [cl.get("spec"), *(cl.get("defs") or [])] if d}
    used = _closure_names(lean) | names if lean is not None else None
    readings, whole, left = [], [], []
    for r in reviews:
        if r.target == "step":
            continue
        row = {"file": r.file, "line": r.line, "target": r.target, "name": r.name,
               "hash": r.hash, "by": r.by}
        users = {c["id"] for c in reading_claims(inventory, r.target, r.name)}
        if markers and not users:
            if r.target == "spec":
                whole.append({**row, "reason": f"no clause states {r.name}"})
                continue
            if used is None:
                left.append({**row, "reason": "no claim names it, and there is no build to show "
                                              "whether a closure uses it"})
                continue
            if r.name not in used:
                whole.append({**row, "reason": f"no claim names {r.name} and no closure of the "
                                               "last build holds it"})
                continue
        stale = sorted(cid for cid in (r.source or {}) if cid not in users)
        if not stale:
            continue
        verb = "states" if r.target == "spec" else "names"
        known = {c["id"] for c in inventory.get("claims", [])}
        reasons = {cid: f"{cid} no longer {verb} {r.name}" if cid in known
                   else f"{cid} is not in the inventory" for cid in stale}
        keep = sorted(set(r.source) - set(stale))
        if keep:
            readings.append({**row, "retire": stale, "keep": keep, "reasons": reasons})
        elif users or r.target == "spec":
            # Every reading it records is of a passage that no longer uses its declaration:
            # the marker records no reading that applies, and keeps the ones it made.
            whole.append({**row, "reason": f"no passage it read still {verb} {r.name}",
                          "reasons": reasons})
        else:
            left.append({**row, "reason": f"no claim names {r.name}: its review reads no "
                                          "passage, so the readings it records are inert"})
    return {"readings": readings, "markers": whole, "left": left}


def apply(root: Path, result: dict) -> None:
    """Remove each retired reading from its marker, and mark each retired marker, in place. A
    marker is never left without a reading: one with none left is retired whole (`plan`)."""
    by_file: dict[str, list[tuple[str, dict]]] = {}
    for row in result["readings"]:
        by_file.setdefault(row["file"], []).append(("reading", row))
    for row in result["markers"]:
        by_file.setdefault(row["file"], []).append(("marker", row))
    for rel, rows in by_file.items():
        path = root / rel
        txt = path.read_text(encoding="utf-8")
        starts = [0] + [i + 1 for i, ch in enumerate(txt) if ch == "\n"]
        edits = []
        for kind, row in rows:
            line = row["line"] - 1
            end = starts[line + 1] if line + 1 < len(starts) else len(txt)
            m = next((m for m in MARKER.finditer(txt, starts[line]) if m.start() < end
                      and m.group(1) == row["target"] and m.group(2) == row["name"]
                      and m.group(3) == row["hash"]), None)
            if m is None or any(e[0] == m.start() for e in edits):
                raise RuntimeError(f"{rel}:{row['line']}: the marker of {row['name']} is not "
                                   "there; rerun without --write")
            text = m.group()
            if kind == "marker":
                text = re.sub(r"\A<!--\s*", "<!-- retired ", text)
            else:
                for cid in row["retire"]:
                    text, n = re.subn(r"\s+source=" + re.escape(cid)
                                      + r"@[0-9a-f]{64}(?=\s|-->)", "", text)
                    if n != 1:
                        raise RuntimeError(f"{rel}:{row['line']}: the reading of {cid} is not "
                                           "there; rerun without --write")
            edits.append((m.start(), m.end(), text))
        for s0, e0, text in sorted(edits, reverse=True):
            txt = txt[:s0] + text + txt[e0:]
        path.write_text(txt, encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Retire the readings review markers record of passages that no longer "
                    "use their declaration; with --markers, also the markers whose declaration "
                    "no claim uses")
    parser.add_argument("--config", required=True)
    parser.add_argument("--markers", action="store_true",
                        help="also retire whole the markers whose declaration no claim uses")
    parser.add_argument("--write", action="store_true",
                        help="apply the plan (default: print it only)")
    args = parser.parse_args(argv)
    from .config import load
    from . import evidence as ev
    try:
        cfg = load(args.config)
        inventory = json.loads(cfg.inventory.read_text(encoding="utf-8"))
        reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
        lean = None
        last = ev.latest(cfg.out_dir) if args.markers else None
        if last is not None:
            lean = ev.load(cfg.out_dir, last["evidence"])["body"].get("lean")
        result = plan(inventory, reviews, lean, args.markers)
        if args.write:
            apply(cfg.root, result)
        print(json.dumps({"applied": args.write, **result}, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"retire: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
