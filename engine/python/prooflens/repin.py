"""Move an inventory's line-located claims from the paper revision they were pinned at to a new
revision (docs/SOURCE_REGIONS.md, "Moving to a new revision of the paper").

Each claim's passage is first verified at its original revision. It is then looked for in the
new snapshot by its exact text: a passage found exactly once, with the same digest, is
repinned (new location and bounds, the same digests). Every other claim is classified and
reported. A passage whose text changed keeps the digests and the revision it was pinned at, so
the source check goes on reporting it until it is reviewed again: a repin never accepts new
text. Two equally good places are reported as ambiguous, never chosen between.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import dataclasses
import difflib
import json
import os
from pathlib import Path
import re
import tempfile

from .source_regions import (
    ENV, SCHEME, RegionError, changed_line, extract, location, same_revision, source_file,
    write_plan,
)

LABEL = re.compile(r"\\label\s*\{([^{}]*)\}")
COMMENT = re.compile(r"(?<!\\)%.*")
CONTEXT = 2  # lines on each side compared for a change of the passage's surroundings
SKIP = {".git", ".lake", ".machinechecked", ".prooflens"}

# The classes of a claim, in the order the plan lists them. Only `unchanged` and `moved`
# claims are repinned; `ambiguous` claims prevent a write.
CLASSES = ("unchanged", "moved", "changed", "removed", "not-found", "ambiguous",
           "pending-review")


def tex_files(root: Path) -> dict[str, str]:
    """The text of every `.tex` file of a snapshot, by its path relative to the snapshot."""
    out = {}
    for path in sorted(root.rglob("*.tex")):
        rel = path.relative_to(root)
        if SKIP & set(rel.parts):
            continue
        try:
            out[rel.as_posix()] = source_file(root, rel.as_posix()).read_text(encoding="utf-8")
        except (RegionError, OSError, UnicodeError):
            continue
    return out


def labels(text: str, first_line: int = 1) -> list[tuple[str, int]]:
    """The `\\label`s of `text` outside comments, with their line numbers."""
    out = []
    for i, line in enumerate(text.split("\n")):
        out += [(m.group(1), first_line + i) for m in LABEL.finditer(COMMENT.sub("", line))]
    return out


DEAD = re.compile(r"\\(iffalse|else|fi|if[A-Za-z@]*)(?![A-Za-z@])|"
                  r"\\(begin|end)\s*\{comment\}")


def dead_ranges(text: str) -> list[tuple[int, int]]:
    """Character ranges the paper may not print: `\\iffalse` blocks (to their `\\else` or
    `\\fi`) and `comment` environments; line comments are told apart by `in_comment`. An
    unterminated block runs to the end of the file, so text after it counts as not printed."""
    out, start, depth, offset = [], None, 0, 0
    for line in text.split("\n"):
        live = COMMENT.sub("", line)
        for m in DEAD.finditer(live):
            word = m.group(1) or ("begin-comment" if m.group(2) == "begin" else "end-comment")
            if start is None:
                if word in ("iffalse", "begin-comment"):
                    start, depth, kind = offset + m.start(), 1, word
            elif kind == "begin-comment":
                if word == "end-comment":
                    out.append((start, offset + m.end()))
                    start = None
            elif word.startswith("if"):
                depth += 1
            elif word == "fi" or (word == "else" and depth == 1):
                depth -= word == "fi"
                if word == "else" or depth == 0:
                    out.append((start, offset + m.end()))
                    start, depth = None, 0
        offset += len(line) + 1
    if start is not None:
        out.append((start, len(text)))
    return out


def in_comment(text: str, index: int) -> bool:
    """Whether the character at `index` is inside a `%` comment of its line."""
    head = text[text.rfind("\n", 0, index) + 1:index]
    return COMMENT.search(head) is not None


def _position(text: str, index: int) -> tuple[int, int]:
    """The 1-based line and column of a character offset."""
    return text.count("\n", 0, index) + 1, index - (text.rfind("\n", 0, index) + 1) + 1


def _placed(claim: dict, region, name: str, text: str, start: int) -> dict:
    """`claim` with its passage placed at `start` of file `name`, its bounds in the same form."""
    c = deepcopy(claim)
    line, col = _position(text, start)
    c["location"] = f"{name}:{line}"
    if region.kind != "span":
        c.pop("source_region", None)
        return c
    end_line, end_col = _position(text, start + len(region.text))
    last = text.split("\n")[end_line - 1]
    old = claim.get("source_region") or {}
    span = {"end_line": end_line}
    if "start_column" in old or col != 1:
        span["start_column"] = col
    if "end_column" in old or end_col != len(last) + 1:
        span["end_column"] = end_col
    c["source_region"] = span
    return c


def exact_matches(root: Path, files: dict[str, str], claim: dict, region) -> list:
    """Every place in the snapshot where the claim's passage occurs with the same text, bounds
    form and kind, as (claim placed there, region there, whether the paper may not print it)."""
    out = []
    for name, text in files.items():
        dead = dead_ranges(text)
        i = text.find(region.text)
        while i >= 0:
            c = _placed(claim, region, name, text, i)
            try:
                r = extract(root, c)
            except (RegionError, OSError, UnicodeError):
                r = None
            if r is not None and r.kind == region.kind and r.sha256 == region.sha256:
                hidden = in_comment(text, i) or any(a <= i < b for a, b in dead)
                out.append((c, r, hidden))
            i = text.find(region.text, i + 1)
    return out


def _by_label(root: Path, files: dict[str, str], claim: dict, region, label: str, name: str,
              line: int):
    """The passage of the claim's kind that holds `label`, found at `name:line` in the new
    snapshot: (claim placed there, region there) for one such passage, else (None, the
    reason)."""
    if region.kind == "line":
        if label not in {n for n, _ in labels(region.text)}:
            return None, f"its line does not hold the label {label}"
        c = deepcopy(claim)
        c["location"] = f"{name}:{line}"
        try:
            return (c, extract(root, c)), None
        except (RegionError, OSError, UnicodeError) as error:
            return None, f"the line holding its label is not a passage: {error}"
    if region.kind == "span":
        return None, ("its bounds cannot be told from its label alone; select the passage "
                      "by hand")
    env = ENV.match(region.text).group(2)
    opener = re.compile(r"\s*\\begin\s*\{" + re.escape(env) + r"\}")
    found, errors = [], []
    for k, ln in enumerate(files[name].split("\n"), start=1):
        if not opener.match(ln) or k > line:
            continue
        c = deepcopy(claim)
        c["location"] = f"{name}:{k}"
        c.pop("source_region", None)
        try:
            r = extract(root, c)
        except (RegionError, OSError, UnicodeError) as error:
            errors.append(f"{name}:{k}: {error}")
            continue
        if r.start_line <= line <= r.end_line:
            found.append((c, r))
    if len(found) == 1:
        return found[0], None
    if found:
        return None, "several " + env + " environments hold its label"
    return None, (f"no complete {env} environment holds its label"
                  + (f" ({'; '.join(errors)})" if errors else ""))


def _context(files: dict[str, str], region) -> tuple[list[str], list[str]]:
    lines = files.get(region.file, "").split("\n")
    before = lines[max(0, region.start_line - 1 - CONTEXT):region.start_line - 1]
    return before, lines[region.end_line:region.end_line + CONTEXT]


def _pin(old_pin: str | None, old_rev: str, new_rev: str) -> str:
    """The new revision in the form of the old pin: abbreviated to the same length, with the
    same `arxiv:` prefix."""
    if not old_pin:
        return new_rev
    prefix = "arxiv:" if str(old_pin).startswith("arxiv:") else ""
    bare = str(old_pin).removeprefix("arxiv:")
    if re.fullmatch(r"[0-9a-f]{7,39}", bare) and re.fullmatch(r"[0-9a-f]{40}", new_rev):
        return prefix + new_rev[:len(bare)]
    return prefix + new_rev


def _bounds(region) -> dict:
    return {"file": region.file, "start_line": region.start_line, "end_line": region.end_line,
            "start_column": region.start_column, "end_column": region.end_column}


def repin_plan(inventory: dict, paper: str, old_root: Path, new_root: Path, old_rev: str,
               new_rev: str) -> tuple[dict, dict]:
    """The inventory with the paper's claims moved from `old_rev` (snapshot `old_root`) to
    `new_rev` (snapshot `new_root`), and the report of what happened to each claim. Raises
    RegionError, before matching anything, if a claim does not match its pin at `old_rev`."""
    result = deepcopy(inventory)
    claims = [c for c in result["claims"] if c["paper"] == paper]
    if not claims:
        raise RegionError(f"no claims for paper {paper}")
    paper_pin = (inventory.get("papers") or {}).get(paper, {}).get("commit")
    old_files, new_files = tex_files(old_root), tex_files(new_root)
    entries, plans = [], []
    # Verify every claim at the original revision before relocating any of them.
    for claim in claims:
        if location(claim) is None:
            continue
        pin = claim.get("commit") or paper_pin
        if pin and not same_revision(str(pin).removeprefix("arxiv:"), old_rev):
            entries.append({"claim": claim["id"], "class": "pending-review",
                            "from": claim["location"],
                            "reason": f"its source pin is of revision {pin}, not {old_rev}: "
                                      "review the passage and pin it again first"})
            continue
        if claim.get("source_hash_scheme") != SCHEME:
            raise RegionError(f"{claim['id']}: pin its source region at the original revision "
                              "first (python -m prooflens.source_regions)")
        try:
            region = extract(old_root, claim)
        except (RegionError, OSError, UnicodeError) as error:
            raise RegionError(f"{claim['id']}: at the original revision: {error}") from None
        if region.sha256 != claim.get("source_sha256"):
            raise RegionError(f"{claim['id']}: its passage at the original revision {old_rev} "
                              "differs from its pin; the baseline is not the reviewed text")
        if claim.get("source_line_sha256") not in (None, region.line_sha256):
            raise RegionError(f"{claim['id']}: its line pins differ from its passage at the "
                              f"original revision {old_rev}")
        plans.append((claim, region))

    for claim, region in plans:
        entry = {"claim": claim["id"], "from": claim["location"], "from_region": _bounds(region)}
        names = {name for name, _ in labels(region.text)} | (
            {claim["label"]} if claim.get("label") else set())
        where = {n: [(f, ln) for f, text in new_files.items() for m, ln in labels(text)
                     if m == n] for n in sorted(names)}
        repeated = {n: w for n, w in where.items() if len(w) > 1}
        exact = exact_matches(new_root, new_files, claim, region)
        target = None
        if repeated:
            entry.update({"class": "ambiguous", "reason": "; ".join(
                f"label {n} occurs {len(w)} times" for n, w in repeated.items()),
                "candidates": [f"{f}:{ln}" for w in repeated.values() for f, ln in w]})
        elif len(exact) > 1:
            entry.update({"class": "ambiguous",
                          "reason": f"its text occurs {len(exact)} times",
                          "candidates": [c["location"] for c, _, _ in exact]})
        elif exact and exact[0][2]:
            entry.update({"class": "ambiguous", "candidates": [exact[0][0]["location"]],
                          "reason": "its text occurs only where the paper may not print it "
                                    "(a comment, \\iffalse or a comment environment)"})
        elif exact:
            target = exact[0][:2]
            same = (target[0]["location"] == claim["location"]
                    and target[0].get("source_region") == claim.get("source_region"))
            entry["class"] = "unchanged" if same else "moved"
            if target[1].file != region.file:
                entry["note"] = (f"it is now in {target[1].file}; check that the paper still "
                                 "reads that file")
        else:
            found = [(n, *w[0]) for n, w in where.items() if w]
            if not names:
                entry.update({"class": "not-found", "reason": "no passage has its text, and it "
                              "has no label by which a changed version could be found"})
            elif not found:
                entry.update({"class": "removed", "reason": "no passage has its text, and its "
                              "label " + ", ".join(sorted(names)) + " is not in the new revision"})
            else:
                located = [_by_label(new_root, new_files, claim, region, n, f, ln)
                           for n, f, ln in found]
                targets = {(t[0]["location"], json.dumps(t[0].get("source_region"))): t
                           for t, _ in located if t}
                entry["class"] = "changed"
                if len(targets) == 1 and all(t for t, _ in located):
                    target = next(iter(targets.values()))
                elif len(targets) > 1:
                    entry.update({"class": "ambiguous",
                                  "reason": "its labels lead to different passages",
                                  "candidates": [k[0] for k in targets]})
                else:
                    entry["reason"] = next(why for _, why in located if why)
                    entry["candidates"] = [f"{f}:{ln}" for _, f, ln in found]
        if target is not None:
            placed, new = target
            entry["to"] = placed["location"]
            entry["to_region"] = _bounds(new)
            if entry["class"] == "changed":
                pins = {**claim, "source_line_sha256": region.line_sha256}
                entry["where"] = changed_line(pins, new.record())
                entry["diff"] = list(difflib.unified_diff(
                    list(region.lines), list(new.lines), lineterm="",
                    fromfile=f"{region.file}:{region.start_line} at {old_rev}",
                    tofile=f"{new.file}:{new.start_line} at {new_rev}"))
            else:
                # The audited text is the same; the text beside it, which an excerpt or a
                # symbol link may rest on, need not be.
                entry["context_changed"] = (_context(old_files, region)
                                            != _context(new_files, new))
        entries.append(entry)
        _apply(claim, entry, region, target, paper_pin, old_rev, new_rev)

    pins = result.get("papers", {}).get(paper)
    if pins and pins.get("commit") and same_revision(
            str(pins["commit"]).removeprefix("arxiv:"), old_rev):
        pins["commit"] = _pin(pins["commit"], old_rev, new_rev)
    old_labels = {n for text in old_files.values() for n, _ in labels(text)}
    new = sorted({(f"{f}:{ln}", n) for f, text in new_files.items()
                  for n, ln in labels(text) if n not in old_labels})
    order = {c: i for i, c in enumerate(CLASSES)}
    entries.sort(key=lambda e: order[e["class"]])
    report = {"paper": paper, "from": old_rev, "to": new_rev,
              "counts": {c: sum(e["class"] == c for e in entries) for c in CLASSES
                         if any(e["class"] == c for e in entries)},
              "claims": entries,
              "new_passages": [{"location": loc, "label": n} for loc, n in new],
              "blocking": [e["claim"] for e in entries if e["class"] == "ambiguous"]}
    return result, report


def _apply(claim: dict, entry: dict, region, target, paper_pin, old_rev: str, new_rev: str):
    """Update one claim in the planned inventory. A repinned claim takes its new place and
    revision; any other claim keeps its digests and the revision they were made at (and takes
    its new place when a changed passage was found unambiguously)."""
    if entry["class"] == "ambiguous":
        return
    if claim.get("source_line_sha256") is None:
        # Verified against the original revision above.
        claim["source_line_sha256"] = region.line_sha256
    if target is not None:
        claim["location"] = target[0]["location"]
        if "source_region" in target[0]:
            claim["source_region"] = target[0]["source_region"]
    if entry["class"] in ("unchanged", "moved"):
        if claim.get("commit"):
            claim["commit"] = _pin(claim["commit"], old_rev, new_rev)
    else:
        claim["commit"] = claim.get("commit") or paper_pin or old_rev


def retarget_config(text: str, paper_id: str, key: str, old: str, new: str) -> str:
    """The configuration with the paper's pinned source revision changed from `old` to `new`,
    refusing unless exactly that one value changes."""
    import tomllib
    quoted = [q + old + q for q in ('"', "'") if (q + old + q) in text]
    if len(quoted) != 1 or text.count(quoted[0]) != 1:
        raise RegionError(f"the configuration names {old!r} other than once; set the paper's "
                          f"source {key} to {new!r} by hand")
    out = text.replace(quoted[0], quoted[0][0] + new + quoted[0][0])
    before, after = tomllib.loads(text), tomllib.loads(out)
    for p in before.get("paper", []):
        if p.get("id") == paper_id:
            p["source"][key] = new
    if before != after:
        raise RegionError(f"{old!r} is not only the paper's source {key}; set it by hand")
    return out


def _replace(path: Path, before: bytes, data: str) -> None:
    """Atomically replace a file that has not changed since it was read."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".repin-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        if path.read_bytes() != before:
            raise RegionError(f"{path.name} changed while planning; nothing more was written")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Move an inventory's claims to a new revision of the paper")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--to", required=True, help="the new revision: a Git commit, or a "
                        "versioned arXiv identifier")
    parser.add_argument("--write", action="store_true",
                        help="apply the plan (default: print it only)")
    args = parser.parse_args(argv)
    from .config import load
    from .sources import SourceError, acquire
    try:
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        key = "rev" if "git" in paper.source else "arxiv" if "arxiv" in paper.source else None
        if key is None:
            raise RegionError("repinning needs a pinned Git or arXiv source, not a working "
                              "folder")
        old_value = str(paper.source.get(key, ""))
        if key == "rev" and not re.fullmatch(r"[0-9a-f]{40}", old_value):
            raise RegionError("repinning needs the original full Git commit, not a branch or "
                              "tag")
        before = cfg.inventory.read_bytes()
        before_cfg = cfg.path.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-repin-") as temp:
            try:
                old = acquire(cfg, paper, Path(temp) / "original" / paper.id)
            except SourceError as error:
                raise RegionError(
                    f"the original revision {old_value} cannot be read ({error}). The claims "
                    "are compared with the text they were pinned at; restore access to that "
                    "revision, as no other baseline is used") from None
            target = dataclasses.replace(paper, source={**paper.source, key: args.to})
            try:
                new = acquire(cfg, target, Path(temp) / "target" / paper.id)
            except SourceError as error:
                raise RegionError(f"the new revision {args.to} cannot be read ({error})") \
                    from None
            if old.mode != "latex" or new.mode != "latex" or not old.revision \
                    or not new.revision:
                raise RegionError("repinning needs pinned LaTeX source snapshots")
            result, report = repin_plan(inventory, paper.id, old.dir, new.dir, old.revision,
                                        new.revision)
        links = {}
        if cfg.symbols and cfg.symbols.exists():
            for link in json.loads(cfg.symbols.read_text(encoding="utf-8")).get("links", []):
                links[link.get("claim")] = links.get(link.get("claim"), 0) + 1
        for e in report["claims"]:
            if links.get(e["claim"]) and (e["class"] not in ("unchanged", "moved")
                                          or e.get("context_changed")):
                e["symbol_links"] = links[e["claim"]]
        new_value = new.revision if key == "rev" else args.to
        written = False
        if args.write:
            if report["blocking"]:
                parser.exit(2, "repin: nothing written: ambiguous claims "
                            + ", ".join(report["blocking"]) + "; resolve them first\n")
            config_text = None
            if new_value != old_value:
                config_text = retarget_config(before_cfg.decode("utf-8"), paper.id, key,
                                              old_value, new_value)
            if cfg.path.read_bytes() != before_cfg:
                raise RegionError("the configuration changed while planning; nothing written")
            if result != inventory:
                write_plan(cfg.inventory, before, result)
                written = True
            if config_text is not None:
                _replace(cfg.path, before_cfg, config_text)
                written = True
        print(json.dumps({"applied": args.write, "written": written, **report}, indent=2,
                         ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"repin: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
