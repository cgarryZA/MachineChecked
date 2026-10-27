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

Earlier versions wrote a marker left with no reading as `source=none`, which other marker
parsers reject and which no longer says what was read. With `--markers`, the plan lists each
such marker. Its readings are recovered from the Git history of its review file, as the
version before the commit that wrote `source=none` records them (`Recovery`), and the marker
is then treated as this version treats a marker with those readings: retired whole with them
(`markers`, with `recovered`), or, for a definition no claim names, given them back
(`repairs`). When the history does not show them (no repository, a shallow clone, several
candidates), or when a recovered reading applies again, the marker is left for the maintainer
(`left`), with why: a reading is never guessed.

The plan is printed as JSON; files change only with `--write`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .review_sources import _git, attribute, parse as parse_source, reading_claims
from .reviews import MARKER, load_reviews

# The attribute an earlier `retire` wrote in place of a marker's last readings.
NONE_ATTR = re.compile(r"(?<=\s)source=none(?=\s|-->)")


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


class Recovery:
    """The readings a review marker recorded before an earlier `retire` replaced them with
    `source=none`, from the Git history of its review file."""

    STEPS = 50

    def __init__(self, root: Path):
        self.root = Path(root)
        top = _git(self.root, "rev-parse", "--show-toplevel")
        self.top = Path(top.strip()) if top else None

    def _blame(self, rev: str | None, path: str, line: int) -> tuple[str, str, int] | None:
        """The commit that wrote line `line` of `path` at `rev` (the working tree for None),
        with the file's path and the line's number in that commit."""
        out = _git(self.top, "blame", "--porcelain", "-w", "-M", "-C", "-L", f"{line},{line}",
                   *([rev] if rev else []), "--", path)
        m = re.match(r"([0-9a-f]{40}) (\d+) \d+", out or "")
        if m is None:
            return None
        name = re.search(r"^filename (.+)$", out, re.M)
        return m.group(1), name.group(1) if name else path, int(m.group(2))

    def __call__(self, r) -> tuple[dict | None, str | None, str]:
        """`(readings, commit, why)`: the readings the marker `r` had and the commit whose
        version of its review file records them; or None, None and why the history does not
        show them."""
        if self.top is None:
            return None, None, "the project is not in a Git repository"
        try:
            path = (self.root / r.file).resolve().relative_to(self.top.resolve()).as_posix()
        except ValueError:
            return None, None, "its review file is outside the project's Git repository"
        rev, line = None, r.line
        for _ in range(self.STEPS):
            got = self._blame(rev, path, line)
            if got is None:
                return None, None, "Git has no history of that line of its review file"
            sha, path, _ = got
            # A line not yet committed: the version before it is the last commit's.
            rev = "HEAD" if set(sha) == {"0"} else f"{sha}^"
            text = _git(self.top, "show", f"{rev}:{path}")
            if text is None:
                # The commit that wrote it created the file, or the clone is shallow there.
                return None, None, (f"the history holds no version of its review file before "
                                    f"{sha[:12]}" if rev != "HEAD" else
                                    "the last commit has no version of its review file")
            found = []
            for m in MARKER.finditer(text):
                attrs = dict(a.split("=", 1) for a in m.group(4).split()
                             if not a.startswith("source="))
                if (m.group(1), m.group(2), m.group(3), attrs.get("by", "unknown")) == \
                        (r.target, r.name, r.hash, r.by):
                    found.append((text.count("\n", 0, m.start()) + 1,
                                  parse_source(m.group(4))))
            readings = {tuple(sorted(src.items())) for _, src in found if src}
            if len(readings) == 1:
                return dict(readings.pop()), (_git(self.top, "rev-parse", rev) or "").strip(), ""
            if len(readings) > 1:
                return None, None, (f"the version before {sha[:12]} has several markers of "
                                    f"{r.name} at its hash by {r.by}, with other readings")
            nones = [ln for ln, src in found if src == {}]
            if len(nones) != 1:
                return None, None, (f"the version before {sha[:12]} records no reading for it"
                                    if rev != "HEAD" else
                                    "the last commit records no reading for it")
            # Still `source=none` there: follow that line further back.
            line = nones[0]
        return None, None, "no version of it in the history records a reading"


def repairs(result: dict, inventory: dict, reviews: list, recover) -> dict:
    """The plan `result` (`plan`, with `--markers`) with each marker an earlier version left as
    `source=none` listed with its repair. With the readings `recover` finds, the marker is what
    this version makes of a marker that records them: retired whole when none of them applies
    (in `markers`, with `recovered`), or, for a definition no claim names, whose review reads
    no passage, given them back (`repairs`). A marker whose readings the history does not show,
    or one of whose readings applies again, is left for the maintainer (`left`), never guessed;
    one retired whole for its declaration alone is retired as it is when they are not shown."""
    out = {**result, "markers": list(result["markers"]), "left": list(result["left"]),
           "repairs": []}
    whole = {(m["file"], m["line"]): m for m in out["markers"]}
    for r in reviews:
        if r.target == "step" or r.source != {}:
            continue
        got, commit, why = recover(r)
        found = {"recovered": got, "commit": commit} if got else {"unrecovered": why}
        if (r.file, r.line) in whole:
            whole[(r.file, r.line)].update(found)
            continue
        out["left"] = [x for x in out["left"] if (x["file"], x["line"]) != (r.file, r.line)]
        row = {"file": r.file, "line": r.line, "target": r.target, "name": r.name,
               "hash": r.hash, "by": r.by}
        verb = "states" if r.target == "spec" else "names"
        users = {c["id"] for c in reading_claims(inventory, r.target, r.name)}
        if not got:
            out["left"].append({**row, **found, "reason": f"it records `source=none`, which other "
                                f"checkers reject, and {why}: retire it or record a new "
                                "reading by hand"})
        elif set(got) & users:
            again = ", ".join(sorted(set(got) & users))
            out["left"].append({**row, **found, "reason": f"it records `source=none`, and "
                                f"its readings in the history include {again}, which {verb} "
                                f"{r.name} now: decide by hand whether that reading holds"})
        elif users or r.target == "spec":
            out["markers"].append({**row, **found, "reason": f"it records `source=none`: no "
                                   f"passage it read still {verb} {r.name}"})
        else:
            out["repairs"].append({**row, **found, "reason": f"no claim names {r.name}: its "
                                   "review reads no passage, and it is given back the readings "
                                   "it had, which are inert"})
    return out


def apply(root: Path, result: dict) -> None:
    """Remove each retired reading from its marker, and mark each retired marker, in place. A
    marker is never left without a reading: one with none left is retired whole (`plan`). A
    marker an earlier version left as `source=none` gets back the readings recovered for it
    (`repairs`), in place of that attribute."""
    by_file: dict[str, list[tuple[str, dict]]] = {}
    for row in result["readings"]:
        by_file.setdefault(row["file"], []).append(("reading", row))
    for row in result["markers"]:
        by_file.setdefault(row["file"], []).append(("marker", row))
    for row in result.get("repairs") or []:
        by_file.setdefault(row["file"], []).append(("repair", row))
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
            if row.get("recovered"):
                # The readings an earlier `retire` replaced with `source=none`.
                text, n = NONE_ATTR.subn(attribute(row["recovered"]), text)
                if n != 1:
                    raise RuntimeError(f"{rel}:{row['line']}: the marker of {row['name']} "
                                       "does not record `source=none`; rerun without --write")
            if kind == "marker":
                text = re.sub(r"\A<!--\s*", "<!-- retired ", text)
            elif kind == "reading":
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
                        help="also retire whole the markers whose declaration no claim uses, "
                             "and repair from the history those an earlier version left as "
                             "source=none")
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
        if args.markers:
            result = repairs(result, inventory, reviews, Recovery(cfg.root))
        if args.write:
            apply(cfg.root, result)
        print(json.dumps({"applied": args.write, **result}, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"retire: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
