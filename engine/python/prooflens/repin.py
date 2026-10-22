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
    DISPLAYS, ENV, SCHEMES, RegionError, advice_message, changed_line, definition_part,
    extract, location, part_claim, pin as pin_of, region_advice, same_revision, source_file,
    tex_sources, theorem_names, write_plan,
)

LABEL = re.compile(r"\\label\s*\{([^{}]*)\}")
COMMENT = re.compile(r"(?<!\\)%.*")
CONTEXT = 2  # lines on each side compared for a change of the passage's surroundings
SKIP = {".git", ".lake", ".machinechecked", ".prooflens"}

# The classes of a claim, in the order the plan lists them. Only `unchanged` and `moved`
# claims are repinned; `ambiguous` and `not-handled` claims prevent a write. `unpinned` claims
# have no source pin to move.
CLASSES = ("unchanged", "moved", "changed", "removed", "not-found", "ambiguous",
           "not-handled", "pending-review", "unpinned")


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


BEGIN = re.compile(r"\\(begin|end)\s*\{([A-Za-z][A-Za-z0-9*_.-]*)\}")


def own_labels(body: str) -> list[str]:
    """The labels of an environment's body outside the environments nested in it (an equation's
    label inside a theorem is the equation's)."""
    out, depth = [], 0
    for line in body.split("\n"):
        live = COMMENT.sub("", line)
        tokens = sorted([(m.start(), "env", m) for m in BEGIN.finditer(live)]
                        + [(m.start(), "label", m) for m in LABEL.finditer(live)],
                       key=lambda t: t[0])
        for _, what, m in tokens:
            if what == "label":
                if depth == 0:
                    out.append(m.group(1))
            else:
                depth = max(0, depth + (1 if m.group(1) == "begin" else -1))
    return out


@dataclasses.dataclass(frozen=True)
class Statement:
    """A theorem-like environment of a snapshot, hashed as the compiled paper's anchors are
    (`tex.statement_at`): its body, whitespace normalised."""
    file: str
    line: int
    env: str
    labels: tuple[str, ...]
    sha256: str | None
    hidden: bool


def statements(root: Path, files: dict[str, str], kind: str | None) -> list[Statement]:
    """Every environment of `kind` (any environment other than a display, without one) in the
    snapshot."""
    from .tex import statement_at
    from .util import norm_ws, sha256_text
    out = []
    for name, text in files.items():
        dead = dead_ranges(text)
        offset = 0
        for k, line in enumerate(text.split("\n"), start=1):
            for m in BEGIN.finditer(COMMENT.sub("", line)):
                env = m.group(2)
                if m.group(1) != "begin" or env.rstrip("*") in DISPLAYS or \
                        (kind and env.rstrip("*").lower() != kind.lower()):
                    continue
                body = statement_at(root / name, k, env)
                if body is None:
                    continue
                hidden = any(a <= offset + m.start() < b for a, b in dead)
                out.append(Statement(name, k, env, tuple(own_labels(body)),
                                     sha256_text(norm_ws(body)), hidden))
            offset += len(line) + 1
    return out


def _names_of(claim: dict) -> set[str]:
    """The labels by which the compiled paper's anchors find a claim (`assess.match_anchor`)."""
    cid, pid = claim["id"], claim["paper"]
    out = {cid}
    if claim.get("label"):
        out.add(claim["label"])
    if cid.startswith(pid + ":"):
        out.add(cid[len(pid) + 1:])
    return out


def statement_entry(claim: dict, old_root: Path, new_root: Path, old_files, new_files,
                    old_rev: str) -> tuple[dict, Statement | None]:
    """The plan entry of a claim pinned by its environment (a `location` without a line and the
    hash of its environment's body), and its environment in the new snapshot when it is placed.
    The environment is found by its own label, as the compiled paper finds it; a claim the
    compiled paper finds only by its printed number cannot be placed without compiling."""
    entry = {"claim": claim["id"], "from": claim.get("location"), "pin": "environment"}
    names = _names_of(claim)
    kind = claim.get("kind")
    old = [s for s in statements(old_root, old_files, kind) if names & set(s.labels)]
    if not old:
        entry.update({"class": "not-handled", "reason": (
            "no environment" + (f" {kind}" if kind else "") + " at the original revision "
            "carries its label; the compiled paper finds it by its printed number, which this "
            "command does not compute: place it by hand")})
        return entry, None
    if len(old) > 1:
        entry.update({"class": "not-handled", "candidates": [f"{s.file}:{s.line}" for s in old],
                      "reason": "several environments carry its label at the original revision"})
        return entry, None
    if old[0].sha256 != claim.get("source_sha256"):
        raise RegionError(f"{claim['id']}: its environment at the original revision {old_rev} "
                          "differs from its pin; the baseline is not the reviewed text")
    entry["from_region"] = {"file": old[0].file, "start_line": old[0].line}
    new_all = statements(new_root, new_files, kind)
    new = [s for s in new_all if names & set(s.labels)]
    if len(new) > 1:
        entry.update({"class": "ambiguous", "reason": f"its label occurs {len(new)} times",
                      "candidates": [f"{s.file}:{s.line}" for s in new]})
        return entry, None
    if new and new[0].hidden:
        entry.update({"class": "ambiguous", "candidates": [f"{new[0].file}:{new[0].line}"],
                      "reason": "its label occurs only where the paper may not print it"})
        return entry, None
    if new:
        target = new[0]
        entry["to"] = target.file
        entry["to_region"] = {"file": target.file, "start_line": target.line}
        if target.sha256 == claim.get("source_sha256"):
            entry["class"] = "unchanged" if target.file == old[0].file else "moved"
        else:
            entry["class"] = "changed"
            old_body = _body(old_root, old[0])
            new_body = _body(new_root, target)
            entry["diff"] = list(difflib.unified_diff(
                old_body, new_body, lineterm="",
                fromfile=f"{old[0].file}:{old[0].line} at {old_rev}",
                tofile=f"{target.file}:{target.line}"))
        return entry, target
    same = [s for s in new_all if s.sha256 == claim.get("source_sha256") and not s.hidden]
    if len(same) == 1:
        entry.update({"class": "ambiguous", "candidates": [f"{same[0].file}:{same[0].line}"],
                      "reason": "its label is not in the new revision, and one environment "
                                "has its text under another label: confirm it by hand"})
    else:
        entry.update({"class": "removed", "reason": "its label "
                      + ", ".join(sorted(names & set(old[0].labels)))
                      + " is not in the new revision"})
    return entry, None


def _body(root: Path, s: Statement) -> list[str]:
    from .tex import statement_at
    return (statement_at(root / s.file, s.line, s.env) or "").split("\n")



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


class LineDiff:
    """The line diff of two versions of one file, as blocks of unchanged and changed lines,
    mapping a line of the old version (1-based) to the new version."""

    def __init__(self, old: str, new: str):
        self.new_lines = new.split("\n")
        self.ops = difflib.SequenceMatcher(None, old.split("\n"), self.new_lines,
                                           autojunk=False).get_opcodes()

    def _block(self, line: int):
        for op in self.ops:
            if op[1] < line <= op[2]:
                return op
        return None

    def same(self, line: int) -> int | None:
        """The new line of an old line that lies in an unchanged block, else None."""
        op = self._block(line)
        return op[3] + line - op[1] if op and op[0] == "equal" else None

    def _mapped(self, line: int, first: bool) -> int | None:
        op = self._block(line)
        if op is None:
            return None
        tag, i1, i2, j1, j2 = op
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            return j1 + line - i1
        # A rewritten block of another length, or removed lines: its whole replacement, which
        # is empty for removed lines.
        return j1 + 1 if first else j2

    def first(self, line: int) -> int | None:
        """The new line a passage that started at old `line` starts at."""
        return self._mapped(line, True)

    def last(self, line: int) -> int | None:
        """The new line a passage that ended at old `line` ends at."""
        return self._mapped(line, False)


FLAGGED = ("cuts-environment", "spans-section")


def proposed_bounds(claim: dict, region, new_root: Path, old_files: dict[str, str],
                    new_files: dict[str, str], old_rev: str, new_rev: str,
                    theorems) -> dict:
    """Bounds for a span whose text changed, from the line diff of its file: its first and last
    lines mapped through the unchanged blocks of the diff (a line in a rewritten block maps to
    the whole of the block's replacement), blank and comment-only lines trimmed from the ends.
    Columns are kept when the line they bound is unchanged. Advice only: the result carries the
    passage's text diff at those bounds and its region advice, and `flagged` names the advice
    that makes the bounds doubtful (an environment cut, a heading crossed)."""
    if region.file not in new_files or region.file not in old_files:
        return {"reason": f"{region.file} is not in the new revision"}
    diff = LineDiff(old_files[region.file], new_files[region.file])
    a, b = diff.first(region.start_line), diff.last(region.end_line)
    lines = diff.new_lines
    while a is not None and b is not None and a <= b and not COMMENT.sub("", lines[a - 1]).strip():
        a += 1
    while a is not None and b is not None and a <= b and not COMMENT.sub("", lines[b - 1]).strip():
        b -= 1
    if a is None or b is None or a > b:
        return {"reason": "every line of the passage was removed or blanked"}
    old = claim.get("source_region") or {}
    span = {"end_line": b}
    kept = []
    if "start_column" in old and diff.same(region.start_line) == a:
        span["start_column"] = old["start_column"]
        kept.append("start_column")
    if "end_column" in old and diff.same(region.end_line) == b:
        span["end_column"] = old["end_column"]
        kept.append("end_column")
    out = {"location": f"{region.file}:{a}", "source_region": span}
    if ({"start_column", "end_column"} & set(old)) - set(kept):
        out["columns"] = ("the line a column bounded changed; the proposal takes the whole "
                          "line")
    c = {**claim, "location": out["location"], "source_region": span}
    try:
        new = extract(new_root, c)
    except (RegionError, OSError, UnicodeError) as error:
        return {**out, "reason": f"the proposed bounds are not a passage: {error}"}
    out["where"] = changed_line({**claim, "source_line_sha256": region.line_sha256},
                                new.record())
    out["diff"] = list(difflib.unified_diff(
        list(region.lines), list(new.lines), lineterm="",
        fromfile=f"{region.file}:{region.start_line} at {old_rev}",
        tofile=f"{new.file}:{new.start_line} at {new_rev}"))
    notes = region_advice(new_root, new, theorems)
    if notes:
        rec = new.record()
        out["advice"] = [{**n, "message": advice_message(claim["id"], rec, n)} for n in notes]
    flagged = [n["kind"] for n in notes if n["kind"] in FLAGGED]
    if flagged:
        out["flagged"] = flagged
    return out


# A line reference in a note: `lines 120–122`, `line 4`, `ll. 3-5`, optionally `of FILE.tex`
# (or `in FILE.tex`), or `FILE.tex:120-122`.
_RANGE = r"(?P<{a}>\d+)(?:\s*(?:--|-|–|—|to)\s*(?P<{b}>\d+))?"
LINE_REF = re.compile(
    r"(?P<path>[\w./-]+\.tex):" + _RANGE.format(a="pa", b="pb")
    + r"|\b(?:[Ll]ines?|ll?\.)\s*" + _RANGE.format(a="a", b="b")
    + r"(?:\s+(?:of|in)\s+(?P<file>[\w./-]+\.tex))?")


def note_references(note: str, own: str | None, old_files: dict[str, str],
                    new_files: dict[str, str], diffs: dict) -> tuple[list[dict], str]:
    """Each line reference of a note with what the new revision does with its lines, and the
    note with the references whose lines only moved rewritten to their new numbers. A reference
    without a file names the claim's own file (`own`). Classes: `unchanged` (the same numbers),
    `moved` (every line in an unchanged block of the diff, still adjacent), `changed` (some of
    its lines changed or were removed: `changed_lines`), `unread` (a file that is not in both
    revisions, or a line outside it)."""
    refs, edits = [], []
    for m in LINE_REF.finditer(note):
        file = m.group("path") or m.group("file") or own
        ga, gb = ("pa", "pb") if m.group("path") else ("a", "b")
        a = int(m.group(ga))
        b = int(m.group(gb)) if m.group(gb) else a
        ref = {"text": m.group(0), "file": file, "lines": [a, b]}
        refs.append(ref)
        if not file or file not in old_files or file not in new_files:
            ref.update({"class": "unread", "reason": (
                f"{file} is not in both revisions" if file
                else "it names no file, and the claim has none to read it in")})
            continue
        if file not in diffs:
            diffs[file] = LineDiff(old_files[file], new_files[file])
        diff = diffs[file]
        if not 1 <= a <= b <= old_files[file].count("\n") + 1:
            ref.update({"class": "unread", "reason": f"not lines of {file}"})
            continue
        mapped = [diff.same(k) for k in range(a, b + 1)]
        if None in mapped:
            ref.update({"class": "changed", "changed_lines": [
                k for k, n in zip(range(a, b + 1), mapped) if n is None]})
            continue
        if mapped[-1] - mapped[0] != b - a:
            ref.update({"class": "changed", "changed_lines": [],
                        "reason": "lines were inserted between its lines"})
            continue
        ref["to"] = [mapped[0], mapped[-1]]
        if mapped[0] == a:
            ref["class"] = "unchanged"
            continue
        ref["class"] = "moved"
        edits.append((m.span(ga), mapped[0]))
        if m.group(gb):
            edits.append((m.span(gb), mapped[-1]))
    out = note
    for (i, j), n in sorted(edits, reverse=True):
        out = out[:i] + str(n) + out[j:]
    return refs, out


def repin_plan(inventory: dict, paper: str, old_root: Path, new_root: Path, old_rev: str,
               new_rev: str, accept=(), rewrite_notes: bool = False) -> tuple[dict, dict]:
    """The inventory with the paper's claims moved from `old_rev` (snapshot `old_root`) to
    `new_rev` (snapshot `new_root`), and the report of what happened to each claim. Raises
    RegionError, before matching anything, if a claim does not match its pin at `old_rev`.

    A changed or not-found span is given bounds proposed from the line diff (`proposed`); the
    claims in `accept` take them (their digests and revision kept), and a claim in `accept`
    without usable proposed bounds is refused. The line references of the claims' scope notes
    are listed under `notes`; with `rewrite_notes`, those whose lines only moved take their new
    numbers."""
    accept = set(accept)
    result = deepcopy(inventory)
    claims = [c for c in result["claims"] if c["paper"] == paper]
    if not claims:
        raise RegionError(f"no claims for paper {paper}")
    paper_pin = (inventory.get("papers") or {}).get(paper, {}).get("commit")
    old_files, new_files = tex_files(old_root), tex_files(new_root)
    entries, plans = [], []
    theorems = None  # the new snapshot's theorem-like environments, read when first needed
    # Verify every claim at the original revision before relocating any of them.
    for claim in claims:
        if location(claim) is None and not claim.get("source_sha256"):
            entries.append({"claim": claim["id"], "class": "unpinned",
                            "from": claim.get("location"),
                            "reason": "it has no source pin to move"})
            continue
        pin = claim.get("commit") or paper_pin
        if pin and not same_revision(str(pin).removeprefix("arxiv:"), old_rev):
            entries.append({"claim": claim["id"], "class": "pending-review",
                            "from": claim.get("location"),
                            "reason": f"its source pin is of revision {pin}, not {old_rev}: "
                                      "review the passage and pin it again first"})
            continue
        if location(claim) is None:
            if not claim.get("location") or claim.get("source_hash_scheme") is not None:
                entries.append({"claim": claim["id"], "class": "not-handled",
                                "from": claim.get("location"),
                                "reason": "its source pin has neither a line nor a file of an "
                                          "environment; pin it by hand"})
                continue
            entry, target = statement_entry(claim, old_root, new_root, old_files, new_files,
                                            old_rev)
            entries.append(entry)
            _apply_statement(claim, entry, target, paper_pin, old_rev, new_rev)
            continue
        if claim.get("source_hash_scheme") not in SCHEMES:
            raise RegionError(f"{claim['id']}: pin its source region at the original revision "
                              "first (python -m prooflens.source_regions)")
        try:
            full = pin_of(old_root, claim)
        except (RegionError, OSError, UnicodeError) as error:
            raise RegionError(f"{claim['id']}: at the original revision: {error}") from None
        region = full.main
        if full.sha256 != claim.get("source_sha256"):
            raise RegionError(f"{claim['id']}: its passage at the original revision {old_rev} "
                              "differs from its pin; the baseline is not the reviewed text")
        if claim.get("source_line_sha256") not in (None, region.line_sha256):
            raise RegionError(f"{claim['id']}: its line pins differ from its passage at the "
                              f"original revision {old_rev}")
        plans.append((claim, region, full))

    new_defs = None
    for claim, region, full in plans:
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
        if target is None and entry["class"] in ("changed", "not-found") \
                and region.kind == "span":
            if theorems is None:
                theorems = theorem_names(tex_sources(new_root))
            entry["proposed"] = proposed_bounds(claim, region, new_root, old_files, new_files,
                                                old_rev, new_rev, theorems)
        if target is not None:
            placed, new = target
            entry["to"] = placed["location"]
            entry["to_region"] = _bounds(new)
            # Where the region at the new revision may not hold the claim's text (advice only).
            if theorems is None:
                theorems = theorem_names(tex_sources(new_root))
            notes = region_advice(new_root, new, theorems)
            if notes:
                rec = new.record()
                entry["advice"] = [{**a, "message": advice_message(claim["id"], rec, a)}
                                   for a in notes]
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
        parts = None
        if full.parts:
            if new_defs is None:
                new_defs = tex_sources(new_root)
            parts = _with_parts(entry, full, new_root, new_files, new_defs)
        entries.append(entry)
        _apply(claim, entry, region, target, paper_pin, old_rev, new_rev)
        if parts is not None and entry["class"] != "ambiguous":
            claim["source_parts"] = parts
        if claim["id"] in accept:
            _accept(claim, entry)
            accept.discard(claim["id"])
    if accept:
        raise RegionError(", ".join(sorted(accept)) + ": no bounds are proposed for "
                          + ("it" if len(accept) == 1 else "them")
                          + " (only a changed or not-found span of this paper has them)")
    notes = _notes(inventory, result, paper, entries, old_files, new_files, rewrite_notes)

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
              "blocking": [e["claim"] for e in entries
                           if e["class"] in ("ambiguous", "not-handled")],
              "advice": [e["claim"] for e in entries if e.get("advice")],
              "proposed": [e["claim"] for e in entries
                           if (e.get("proposed") or {}).get("diff") is not None],
              "notes": notes}
    return result, report


def _accept(claim: dict, entry: dict) -> None:
    """Give a claim of the planned inventory its proposed bounds, keeping its digests and the
    revision they were made at, so the source check goes on reporting it until it is reviewed
    and pinned again."""
    p = entry.get("proposed")
    why = None
    if entry["class"] not in ("changed", "not-found") or not p:
        why = f"it is {entry['class']}, and no bounds are proposed for it"
    elif "reason" in p:
        why = p["reason"]
    elif p.get("flagged"):
        why = "they " + " and ".join({"cuts-environment": "cut an environment",
                                      "spans-section": "cross a heading"}[k]
                                     for k in p["flagged"]) + "; set them by hand"
    if why:
        raise RegionError(f"{claim['id']}: its proposed bounds cannot be taken: {why}")
    claim["location"] = p["location"]
    claim["source_region"] = p["source_region"]
    p["accepted"] = True


def _notes(inventory: dict, result: dict, paper: str, entries: list[dict],
           old_files: dict[str, str], new_files: dict[str, str], rewrite: bool) -> list[dict]:
    """The line references of the paper's claims' scope notes (`note_references`), for every
    claim whose pin is of the original revision; with `rewrite`, the planned inventory's notes
    take the new numbers of the references whose lines only moved."""
    skip = {e["claim"] for e in entries if e["class"] == "pending-review"}
    planned = {c["id"]: c for c in result["claims"] if c["paper"] == paper}
    diffs, out = {}, []
    for claim in inventory["claims"]:
        note = claim.get("scope_note")
        if claim["paper"] != paper or claim["id"] in skip or not isinstance(note, str):
            continue
        try:
            loc = location(claim)
        except RegionError:
            loc = None
        own = loc[0] if loc else claim.get("location") if \
            str(claim.get("location") or "").endswith(".tex") else None
        refs, rewritten = note_references(note, own, old_files, new_files, diffs)
        if not refs:
            continue
        row = {"claim": claim["id"], "references": refs}
        if rewritten != note:
            row["rewritten"] = rewritten
            if rewrite:
                planned[claim["id"]]["scope_note"] = rewritten
        out.append(row)
    return out


def repin_excerpts(display: dict, claim_ids: set[str], old_root: Path, new_root: Path,
                   old_rev: str, new_rev: str) -> tuple[dict, list[dict]]:
    """The display overlay with the excerpt selectors of `claim_ids` moved to `new_rev`, and a
    report entry for each. A selector by label is read again at the next build and is only
    checked here. A selector by location moves when its passage occurs exactly once, with the
    same text, where the paper prints it; any other is pinned to `old_rev`, so that it selects
    nothing at the new revision until it is chosen again. Excerpts are display only: nothing
    here touches the inventory."""
    result = deepcopy(display)
    old_files, new_files = tex_files(old_root), tex_files(new_root)
    entries = []
    for cid, shown in sorted((result.get("claims") or {}).items()):
        sel = shown.get("excerpt") if isinstance(shown, dict) else None
        if cid not in claim_ids or not isinstance(sel, dict):
            continue
        entry = {"claim": cid, "selector": deepcopy(sel)}
        if "label" in sel:
            where = [f"{f}:{ln}" for f, text in new_files.items() for n, ln in labels(text)
                     if n == sel["label"]]
            entry["class"] = "follows-label" if len(where) == 1 else "label-not-unique"
            entry["candidates"] = where
            if len(where) != 1:
                entry["reason"] = (f"the label {sel['label']} occurs {len(where)} times in the "
                                   "new revision: the claim will be shown from the PDF")
            entries.append(entry)
            continue
        pin = sel.get("revision")
        if pin is not None and not same_revision(str(pin), old_rev):
            entry.update({"class": "stale", "reason": f"it was selected at revision {pin}"})
            entries.append(entry)
            continue
        span = {k: v for k, v in sel.items() if k not in ("location", "revision")}
        here = {"location": sel.get("location"), **({"source_region": span} if span else {})}
        try:
            region = extract(old_root, here)
        except (RegionError, OSError, UnicodeError) as error:
            entry.update({"class": "stale", "reason": f"at the original revision: {error}"})
            entries.append(entry)
            continue
        found = [(c, r) for c, r, hidden in exact_matches(new_root, new_files, here, region)
                 if not hidden]
        if len(found) == 1:
            placed, new = found[0]
            moved = {"location": placed["location"], **placed.get("source_region", {})}
            if pin is not None:
                moved["revision"] = new_rev
            shown["excerpt"] = moved
            entry.update({"class": "unchanged" if moved == sel else "moved", "to": moved,
                          "context_changed": _context(old_files, region) != _context(new_files, new)})
        else:
            shown["excerpt"] = {**sel, "revision": sel.get("revision") or old_rev}
            entry.update({"class": "invalidated", "to": shown["excerpt"], "reason": (
                f"its text occurs {len(found)} times where the new revision prints it" if found
                else "its text is not in the new revision") + "; select the passage again"})
        entries.append(entry)
    return result, entries


def _as_part(placed: dict, part: dict) -> dict:
    """A part placed elsewhere, in the form of the inventory: its digests and role kept."""
    out = {"location": placed["location"], **(placed.get("source_region") or {})}
    for k in ("macro", "sha256", "line_sha256"):
        if k in part:
            out[k] = part[k]
    return out


def _with_parts(entry: dict, full, new_root: Path, new_files: dict[str, str],
                sources: dict[str, str]) -> list[dict]:
    """Classify each further passage of a pin as the claim's own passage is (by its exact
    text; a macro definition that changed is found by the macro's name), record them under
    the entry's `parts`, and give the claim its class over all its passages: repinned only
    when every passage is found unchanged. Returns the parts as the inventory should hold
    them: placed where found, with their digests unchanged."""
    out, rows = [], []
    for part, region in full.parts:
        row = {"part": part["location"], **({"macro": part["macro"]} if part.get("macro")
                                            else {})}
        exact = exact_matches(new_root, new_files, {"id": entry["claim"], **part_claim(part)},
                              region)
        placed = None
        if len(exact) > 1:
            row.update({"class": "ambiguous", "reason": f"its text occurs {len(exact)} times",
                        "candidates": [c["location"] for c, _, _ in exact]})
        elif exact and exact[0][2]:
            row.update({"class": "ambiguous", "candidates": [exact[0][0]["location"]],
                        "reason": "its text occurs only where the paper may not print it"})
        elif exact:
            placed = _as_part(exact[0][0], part)
            same = all(placed.get(k) == part.get(k) for k in ("location", "end_line",
                                                              "start_column", "end_column"))
            row["class"] = "unchanged" if same else "moved"
        elif part.get("macro"):
            try:
                found = definition_part(sources, part["macro"])
                placed = {**found, **{k: part[k] for k in ("sha256", "line_sha256")
                                      if k in part}}
                row.update({"class": "changed", "reason": "its definition has another text"})
            except RegionError as error:
                row.update({"class": "ambiguous" if "defined" in str(error) else "removed",
                            "reason": str(error)})
        else:
            row.update({"class": "not-found", "reason": "no passage has its text"})
        if placed is not None:
            row["to"] = placed["location"]
        rows.append(row)
        out.append(placed or part)
    entry["parts"] = rows
    classes = {r["class"] for r in rows}
    if entry["class"] == "ambiguous" or "ambiguous" in classes:
        entry["class"] = "ambiguous"
        entry.setdefault("reason", "a further passage of its pin is ambiguous")
    elif entry["class"] in ("unchanged", "moved") and classes - {"unchanged", "moved"}:
        entry["class"] = "changed"
        first = next(r for r in rows if r["class"] not in ("unchanged", "moved"))
        entry["where"] = (f"part {rows.index(first) + 1} ({first['part']}) of its pin: "
                          + first.get("reason", first["class"]))
    elif entry["class"] == "unchanged" and "moved" in classes:
        entry["class"] = "moved"
    return out


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


def _apply_statement(claim: dict, entry: dict, target, paper_pin, old_rev: str,
                     new_rev: str):
    """Update one environment-pinned claim in the planned inventory, as `_apply` does a
    line-pinned one: its location is the file of its environment."""
    if entry["class"] in ("ambiguous", "not-handled"):
        return
    if target is not None:
        claim["location"] = target.file
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
    parser.add_argument("--from-source", help="the manuscript at the original revision: a "
                        "folder, or git:REV for the configured folder as committed at REV of "
                        "its repository (default: the configured source)")
    parser.add_argument("--from-rev", help="the paper revision --from-source (or a configured "
                        "folder) holds (default: the inventory's papers.PAPER.commit)")
    parser.add_argument("--to-source", help="the manuscript at the new revision --to: a folder, "
                        "or git:REV as above (default: the configured source at --to; for a "
                        "configured folder, that folder)")
    parser.add_argument("--write", action="store_true",
                        help="apply the plan (default: print it only)")
    parser.add_argument("--accept-bounds", action="append", default=[], metavar="CLAIM",
                        help="give CLAIM, a changed or not-found span, the bounds the plan "
                        "proposes from the line diff (its digests are kept); repeatable")
    parser.add_argument("--rewrite-notes", action="store_true",
                        help="give the line references of scope notes whose lines only moved "
                        "their new numbers")
    args = parser.parse_args(argv)
    from .config import load
    from .source_regions import REVISION, baseline, folder
    from .sources import SourceError, acquire
    try:
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        src = paper.source
        vendored = "path" in src
        key = "rev" if "git" in src or (vendored and "rev" in src) else \
            "arxiv" if "arxiv" in src else None
        old_value = str(src.get(key, "")) if key else None
        before = cfg.inventory.read_bytes()
        before_cfg = cfg.path.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-repin-") as temp:
            try:
                old_dir, old_rev = baseline(cfg, paper, inventory,
                                            Path(temp) / "original" / paper.id,
                                            args.from_source, args.from_rev)
            except SourceError as error:
                raise RegionError(
                    f"the original revision {old_value or args.from_rev or ''} cannot be read "
                    f"({error}). The claims are compared with the text they were pinned at; "
                    "restore access to that revision, as no other baseline is used") from None
            to_source = args.to_source
            if to_source is None and vendored:
                to_source = str((cfg.root / paper.source["path"]).resolve())
            if to_source is not None:
                if not REVISION.fullmatch(args.to):
                    raise RegionError(f"--to {args.to!r} is not a commit or a versioned arXiv "
                                      "identifier")
                new_dir = folder(cfg, paper, to_source, Path(temp) / "target" / paper.id)
                new_rev = args.to.removeprefix("arxiv:")
            else:
                target = dataclasses.replace(paper, source={**paper.source, key: args.to})
                try:
                    new = acquire(cfg, target, Path(temp) / "target" / paper.id)
                except SourceError as error:
                    raise RegionError(f"the new revision {args.to} cannot be read ({error})") \
                        from None
                if new.mode != "latex" or not new.revision:
                    raise RegionError("repinning needs pinned LaTeX source snapshots")
                new_dir, new_rev = new.dir, new.revision
            result, report = repin_plan(inventory, paper.id, old_dir, new_dir, old_rev,
                                        new_rev, args.accept_bounds, args.rewrite_notes)
            if vendored:
                # A folder has no revision of its own: the inventory records the one it holds.
                pins = result.setdefault("papers", {}).setdefault(paper.id, {})
                pins["commit"] = _pin(pins.get("commit") or old_rev, old_rev, new_rev)
            before_display = display = new_display = None
            if cfg.display and cfg.display.exists():
                before_display = cfg.display.read_bytes()
                display = json.loads(before_display)
                ids = {c["id"] for c in inventory["claims"] if c["paper"] == paper.id}
                new_display, report["excerpts"] = repin_excerpts(
                    display, ids, old_dir, new_dir, old_rev, new_rev)
        links = {}
        if cfg.symbols and cfg.symbols.exists():
            for link in json.loads(cfg.symbols.read_text(encoding="utf-8")).get("links", []):
                links[link.get("claim")] = links.get(link.get("claim"), 0) + 1
        for e in report["claims"]:
            if links.get(e["claim"]) and (e["class"] not in ("unchanged", "moved")
                                          or e.get("context_changed")):
                e["symbol_links"] = links[e["claim"]]
        new_value = new_rev if key == "rev" else args.to
        written = False
        if args.write:
            if report["blocking"]:
                kinds = {e["claim"]: e["class"] for e in report["claims"]}
                parts = [f"{what} " + ", ".join(c for c in report["blocking"] if kinds[c] == k)
                         for k, what in (("ambiguous", "ambiguous claims"),
                                         ("not-handled", "claims it cannot place"))
                         if any(kinds[c] == k for c in report["blocking"])]
                parser.exit(2, "repin: nothing written: " + "; ".join(parts)
                            + "; resolve them first\n")
            config_text = None
            if key is not None and new_value != old_value:
                config_text = retarget_config(before_cfg.decode("utf-8"), paper.id, key,
                                              old_value, new_value)
            if cfg.path.read_bytes() != before_cfg:
                raise RegionError("the configuration changed while planning; nothing written")
            if before_display is not None and cfg.display.read_bytes() != before_display:
                raise RegionError("the display overlay changed while planning; nothing written")
            if result != inventory:
                write_plan(cfg.inventory, before, result)
                written = True
            if new_display is not None and new_display != display:
                _replace(cfg.display, before_display,
                         json.dumps(new_display, indent=2, ensure_ascii=False) + "\n")
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
