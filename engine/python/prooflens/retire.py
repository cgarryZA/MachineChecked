"""Retire the readings review markers record of passages that no longer state or name their
declaration (`machinechecked inventory retire`).

A marker records `source=<claim>@<digest>` for each passage its reviewer read beside the
declaration (`review_sources.py`). When the inventory moves a clause to another claim (a claim
split in two, a passage moved to a new entry), the markers of the clause's proposition still
record the old claim's passage. That entry is no reading of a passage that uses the declaration
now, so it is retired: removed, never rewritten to the new claim, and nothing is added. A marker
left with no reading records `source=none`, so that it is not read as a marker written before
readings were recorded; the claims that now use the declaration read as unread until someone
reads their passages.

With `--markers`, the plan also lists the markers whose declaration no claim uses any more: a
proposition no clause states, or a definition no claim names that is in no closure of the last
build's Lean results. With `--write` those are retired
whole: the marker stays in its file, with its review text, as `<!-- retired spec-review: ...
-->`, which records no review (`reviews.RETIRED`). Step markers are left alone.

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
    longer uses its declaration) and, with `markers`, the markers to retire whole (`markers`),
    with the markers left because the last build cannot show them unused (`left`)."""
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
            elif r.name not in used:
                whole.append({**row, "reason": f"no claim names {r.name} and no closure of the "
                                               "last build holds it"})
                continue
        stale = sorted(cid for cid in (r.source or {}) if cid not in users)
        if stale:
            known = {c["id"] for c in inventory.get("claims", [])}
            readings.append({**row, "retire": stale,
                             "keep": sorted(set(r.source) - set(stale)),
                             "reasons": {cid: (f"{cid} no longer "
                                               + ("states" if r.target == "spec" else "names")
                                               + f" {r.name}") if cid in known
                                         else f"{cid} is not in the inventory" for cid in stale}})
    return {"readings": readings, "markers": whole, "left": left}


def apply(root: Path, result: dict) -> None:
    """Remove each retired reading from its marker, and mark each retired marker, in place."""
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
                if not row["keep"]:
                    text = re.sub(r"\s*-->\Z", " source=none -->", text)
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
    from .util import read_json
    try:
        cfg = load(args.config)
        inventory = json.loads(cfg.inventory.read_text(encoding="utf-8"))
        reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
        lean = None
        rels = ev.releases(cfg.out_dir) if args.markers else []
        if rels:
            lean = ev.load(cfg.out_dir, read_json(rels[-1])["evidence"])["body"].get("lean")
        result = plan(inventory, reviews, lean, args.markers)
        if args.write:
            apply(cfg.root, result)
        print(json.dumps({"applied": args.write, **result}, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"retire: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
