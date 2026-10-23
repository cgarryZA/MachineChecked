"""Bounded manuscript regions and fingerprints, independent of their PDF placement.

Hash the original text, not a whitespace-normalised rendering: a newline can terminate a TeX
comment. The scanner recognises literal environments and explicit spans, not arbitrary TeX.
"""

from __future__ import annotations

import argparse
import bisect
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEME = "tex-region-v1"
DISPLAYS = {"equation", "align", "gather", "multline", "eqnarray", "flalign", "alignat"}
ENV = re.compile(r"\\(begin|end)\s*\{([A-Za-z][A-Za-z0-9*_.-]*)\}")
COMMAND = re.compile(r"\\[A-Za-z@]+|\\.", re.S)


class RegionError(ValueError):
    pass


def location(claim: dict) -> tuple[str, int] | None:
    path, _, line = (claim.get("location") or "").rpartition(":")
    if not path or not line.isdigit():
        return None
    if int(line) < 1:
        raise RegionError("source line must be positive")
    return path, int(line)


def source_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise RegionError("source path leaves the manuscript snapshot")
    return path


def environments(text: str, start: int):
    """Literal begin/end tokens outside comments, escaped backslashes and inline verbatim."""
    i = start
    while i < len(text):
        if text[i] == "%":
            end = text.find("\n", i)
            i = end + 1 if end >= 0 else len(text)
        elif text[i] == "\\":
            env = ENV.match(text, i)
            if env:
                yield env.group(1), env.group(2), env.start(), env.end()
                i = env.end()
                continue
            cmd = COMMAND.match(text, i)
            if not cmd:
                i += 1
                continue
            i = cmd.end()
            if cmd.group() == r"\verb":
                if i < len(text) and text[i] == "*":
                    i += 1
                if i >= len(text) or text[i].isspace():
                    raise RegionError("invalid inline verbatim delimiter")
                end = text.find(text[i], i + 1)
                if end < 0 or "\n" in text[i:end]:
                    raise RegionError("unterminated inline verbatim")
                i = end + 1
        else:
            i += 1


@dataclass(frozen=True)
class Region:
    file: str
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    kind: str
    text: str
    lines: tuple[str, ...] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def line_sha256(self) -> list[str]:
        """One digest per source line the passage spans (the whole line, raw, without its line
        terminator), so that a change can be located, a passage that only moved can be told
        from a changed one, and any checker can verify the pins from the file's lines alone."""
        return [hashlib.sha256(line.encode("utf-8")).hexdigest() for line in self.lines]

    def record(self) -> dict:
        # The evidence needs bounds and digests, not an additional public copy of the text.
        return {"file": self.file, "start_line": self.start_line, "end_line": self.end_line,
                "start_column": self.start_column, "end_column": self.end_column,
                "kind": self.kind, "scheme": SCHEME, "sha256": self.sha256,
                "line_sha256": self.line_sha256}


def positive(value, name: str) -> int:
    if type(value) is not int or value < 1:
        raise RegionError(f"{name} must be a positive integer")
    return value


def _span(lines: list[str], first: int, last: int) -> tuple[str, ...]:
    return tuple(l.rstrip("\r\n") for l in lines[first - 1:last])


def extract(root: Path, claim: dict) -> Region:
    loc = location(claim)
    if loc is None:
        raise RegionError("a source region needs a file:line location")
    name, line = loc
    text = source_file(root, name).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise RegionError("source line is outside the file")
    starts = [0]
    for part in lines:
        starts.append(starts[-1] + len(part))
    first = lines[line - 1].rstrip("\r\n")
    span = claim.get("source_region")
    if span is not None:
        if not isinstance(span, dict) or set(span) - {"end_line", "start_column", "end_column"}:
            raise RegionError("source_region needs end_line and optional column bounds")
        end_line = positive(span.get("end_line"), "end_line")
        if not line <= end_line <= len(lines):
            raise RegionError("source end line is before the start or outside the file")
        last = lines[end_line - 1].rstrip("\r\n")
        start_col = positive(span.get("start_column", 1), "start_column")
        end_col = positive(span.get("end_column", len(last) + 1), "end_column")
        if start_col > len(first) + 1 or end_col > len(last) + 1:
            raise RegionError("source column is outside the line")
        start = starts[line - 1] + start_col - 1
        end = starts[end_line - 1] + end_col - 1
        if start >= end or not text[start:end].strip():
            raise RegionError("source region is empty or reversed")
        return Region(name, line, end_line, start_col, end_col, "span", text[start:end],
                      _span(lines, line, end_line))
    start = starts[line - 1] + len(first) - len(first.lstrip())
    opening = ENV.match(text, start)
    if opening and opening.group(1) == "begin" and opening.group(2).rstrip("*") in DISPLAYS:
        stack = []
        for op, env, _, end in environments(text, start):
            if op == "begin":
                stack.append(env)
            elif not stack or stack.pop() != env:
                raise RegionError("mismatched source environment")
            if not stack:
                end_line = text.count("\n", 0, end) + 1
                end_column = end - (text.rfind("\n", 0, end) + 1) + 1
                return Region(name, line, end_line, start - starts[line - 1] + 1,
                              end_column, "environment", text[start:end],
                              _span(lines, line, end_line))
        raise RegionError("source environment has no matching end")
    if first.lstrip().startswith(r"\begin"):
        raise RegionError("unsupported or malformed environment; select an explicit source region")
    if not first.strip() or first.lstrip().startswith("%"):
        raise RegionError("source line is blank or a comment; select the actual passage")
    return Region(name, line, line, 1, len(first) + 1, "line", first, (first,))


# Commands that carry no text of a claim: a label, a heading, the start of the appendix.
SECTIONING = r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?"
_STRUCTURE = re.compile(r"\\label\s*\{[^{}]*\}|" + SECTIONING
                        + r"\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}|\\appendix\b")
_SECTION = re.compile(SECTIONING + r"(?![A-Za-z])|\\appendix\b")
# A line after which a new sentence starts: one that ends a sentence, or a line of LaTeX
# structure (an environment's begin or end, a display's end, an item, a heading).
_ENDS = re.compile(r"[.!?][\s'\")\]}$]*$")
_BOUNDARY = re.compile(r"^\s*(?:\\(?:begin|end|item|label|\]|\[|par\b|noindent|medskip|"
                       r"bigskip|smallskip|appendix|part|chapter|section|subsection|"
                       r"subsubsection|paragraph|subparagraph)|\$\$)"
                       r"|(?:\\end\s*\{[^{}]*\}|\\\]|\$\$|\\\\)\s*$")


def _code(line: str) -> str:
    """A source line without its comment."""
    return re.sub(r"(?<!\\)%.*", "", line)


def _blank(line: str) -> bool:
    return not _code(line).strip()


def _bare(line: str) -> bool:
    """Whether a line holds nothing of a claim's text: only labels, headings, comments."""
    return not _STRUCTURE.sub("", _code(line)).strip()


def _paragraph(lines: list[str], first: int, last: int) -> tuple[int, int]:
    """The paragraph around lines `first`..`last` (1-based): out to the nearest blank line or
    line of structure on each side."""
    a, b = first, last
    while a > 1 and not _blank(lines[a - 2]) and not _BOUNDARY.search(_code(lines[a - 2])):
        a -= 1
    while b < len(lines) and not _blank(lines[b]) and not _BOUNDARY.search(_code(lines[b])):
        b += 1
    return a, b


def advice(lines: list[str], region: Region, theorems=()) -> list[dict]:
    """Where a line-located region may not hold the claim's text (#180): a region of only a
    label or heading (`label-only`, naming the paragraph that follows), a region that begins
    or ends inside a sentence (`starts-mid-sentence`, `ends-mid-sentence`, naming the
    paragraph around it), one that runs into another section (`spans-section`), and one that
    holds the `\\begin` or the `\\end` of a display, proof or theorem-like environment without
    the other (`cuts-environment`, naming the environments and the bounds that contain them
    whole or leave them out). `theorems` are the theorem-like environment names of the
    snapshot. Each is advice: the region is what the inventory pins, and a reviewer decides its
    extent. A display environment and a region bounded inside a line are judged on their lines
    only for a heading after their first line."""
    first, last = region.start_line, region.end_line
    body = lines[first - 1:last]
    out = []

    def where(a: int, b: int) -> dict:
        return {"file": region.file, "line": a, "end_line": b}

    if all(_bare(l) for l in body):
        a = last + 1
        while a <= len(lines) and (_blank(lines[a - 1]) or _bare(lines[a - 1])):
            a += 1
        if a <= len(lines) and not _SECTION.search(_code(lines[a - 1])):
            b = _paragraph(lines, a, a)[1]
            out.append({"kind": "label-only", "suggested": where(a, b)})
        else:
            out.append({"kind": "label-only"})
        return out
    for i, l in enumerate(body[1:], first + 1):
        if _SECTION.search(_code(l)):
            out.append({"kind": "spans-section", "at": i})
            break
    whole = region.kind in ("line", "span") and region.start_column == 1 and \
        region.end_column == len(lines[last - 1].rstrip("\r\n")) + 1
    if not whole:
        return out
    cut = _cuts(lines, region.file, first, last, set(theorems))
    if cut:
        out.append(cut)
    para = where(*_paragraph(lines, first, last))
    prev = lines[first - 2] if first > 1 else ""
    if not _blank(prev) and not _BOUNDARY.search(_code(prev)) \
            and not _ENDS.search(_code(prev).rstrip()):
        out.append({"kind": "starts-mid-sentence", "suggested": para})
    after = lines[last] if last < len(lines) else ""
    end = _code(body[-1]).rstrip()
    if not _blank(after) and not _BOUNDARY.search(_code(after)) and \
            not _BOUNDARY.search(end) and not _ENDS.search(end):
        out.append({"kind": "ends-mid-sentence", "suggested": para})
    return out


# Environments whose extent is part of what a claim states: displays and proofs; with them, the
# theorem-like environments a snapshot declares (`\newtheorem`).
_CUTTABLE = {*DISPLAYS, "displaymath", "proof"}
_NEWTHEOREM = re.compile(r"\\newtheorem\*?\s*\{([A-Za-z@]+)\}")


def theorem_names(files: dict[str, str]) -> set[str]:
    """The environment names declared with `\\newtheorem` in a snapshot's TeX files."""
    return {m.group(1) for text in files.values() for m in _NEWTHEOREM.finditer(_strip(text))}


def _strip(text: str) -> str:
    return "\n".join(_code(l) for l in text.splitlines())


def _cuts(lines: list[str], file: str, first: int, last: int, theorems: set[str]) -> dict | None:
    """`cuts-environment` advice for lines `first`..`last` (1-based) of `file` when they hold
    the `\\begin` or the `\\end` of a display, proof or theorem-like environment without the
    other: each such environment with its lines, the smallest whole-line region that contains
    the region and every environment it cuts (`suggested`), and the largest one inside the
    region that holds none of their `\\begin`/`\\end` lines (`without`, absent when nothing of
    the text is left)."""
    if not any(ENV.search(_code(l)) for l in lines[first - 1:last]):
        return None
    text = "".join(l.rstrip("\r\n") + "\n" for l in lines)
    starts = [0]
    for l in lines:
        starts.append(starts[-1] + len(l.rstrip("\r\n")) + 1)
    pairs, stack = [], []
    try:
        for op, env, start, _ in environments(text, 0):
            line = bisect.bisect_right(starts, start)
            if op == "begin":
                stack.append((env, line))
            elif stack and stack[-1][0] == env:
                name, b = stack.pop()
                pairs.append((name, b, line))
            else:
                return None  # the file itself is unbalanced: there is no extent to suggest
    except RegionError:
        return None
    kinds = _CUTTABLE | theorems

    def cuts(a: int, b: int):
        return [(n, x, y) for n, x, y in pairs if n.rstrip("*") in kinds
                and (a <= x <= b) != (a <= y <= b)]

    found = cuts(first, last)
    if not found:
        return None
    a, b = first, last
    while more := cuts(a, b):
        a, b = min([a] + [x for _, x, _ in more]), max([b] + [y for _, _, y in more])
    lo = max([first] + [y + 1 for _, x, y in found if x < first <= y])
    hi = min([last] + [x - 1 for _, x, y in found if x <= last < y])
    out = {"kind": "cuts-environment",
           "environments": [{"name": n, "line": x, "end_line": y} for n, x, y in found],
           "suggested": {"file": file, "line": a, "end_line": b}}
    if lo <= hi and not cuts(lo, hi) and not all(_bare(l) for l in lines[lo - 1:hi]):
        out["without"] = {"file": file, "line": lo, "end_line": hi}
    return out


def advice_message(claim_id: str, region: dict, a: dict) -> str:
    """What an advice says, for a finding or the repin plan."""
    at = f"{region.get('file')}:{region.get('start_line')}"
    if region.get("end_line", region.get("start_line")) != region.get("start_line"):
        at += f"-{region.get('end_line')}"
    if a["kind"] == "cuts-environment":
        envs = " and ".join(f"the {e['name']} at lines {e['line']}-{e['end_line']}"
                            for e in a["environments"])
        s, w = a["suggested"], a.get("without")
        hint = (f"; pin lines {s['line']}-{s['end_line']} of {s['file']} to contain "
                f"{'it' if len(a['environments']) == 1 else 'them'} whole (location "
                f"{s['file']}:{s['line']} with source_region end_line {s['end_line']})")
        if w:
            hint += (f", or lines {w['line']}-{w['end_line']} to leave "
                     f"{'it' if len(a['environments']) == 1 else 'them'} out (location "
                     f"{w['file']}:{w['line']} with source_region end_line {w['end_line']})")
        return (f"the source region of {claim_id} at {at} holds the \\begin or the \\end of "
                f"{envs} without the other, so a change to its own text may reopen nothing "
                f"and a change to the other text reopens it{hint}")
    s = a.get("suggested")
    hint = (f"; pin lines {s['line']}-{s['end_line']} of {s['file']} instead (location "
            f"{s['file']}:{s['line']} with source_region end_line {s['end_line']})"
            if s else "")
    what = {"label-only": "holds only a label or heading, so it pins none of the claim's text",
            "starts-mid-sentence": "begins inside a sentence that starts before it",
            "ends-mid-sentence": "ends inside a sentence that continues after it",
            "spans-section": f"runs past a heading on line {a.get('at')} into another "
                             "section"}[a["kind"]]
    return f"the source region of {claim_id} at {at} {what}{hint}"


def region_advice(root: Path, region: Region, theorems=None) -> list[dict]:
    """`advice` for a region of the snapshot at `root`; `theorems` are the snapshot's
    theorem-like environment names (`theorem_names`), read from it when not given."""
    try:
        text = source_file(root, region.file).read_text(encoding="utf-8")
    except (RegionError, OSError, UnicodeError):
        return []
    if theorems is None:
        theorems = theorem_names(tex_sources(root))
    return advice(text.splitlines(), region, theorems)


# -- pins of several passages (#185) and of macro definitions (#183) -----------------------------

MULTI = "tex-regions-v1"
SCHEMES = (SCHEME, MULTI)
PART_BOUNDS = ("end_line", "start_column", "end_column")
PART_KEYS = {"location", *PART_BOUNDS, "macro", "sha256", "line_sha256"}
MACRO = re.compile(r"\\[A-Za-z@]+")
DEFINITION = re.compile(
    r"\\(?:(?:re|provide)?newcommand|DeclareMathOperator|DeclareRobustCommand)\*?\s*\{?\s*"
    r"(\\[A-Za-z@]+)|\\(?:[gex]?def|let)\s*(\\[A-Za-z@]+)")


def part_claim(part: dict) -> dict:
    """A further passage of a pin in the form `extract` reads: a location and its bounds."""
    span = {k: part[k] for k in PART_BOUNDS if k in part}
    return {"location": part.get("location"), **({"source_region": span} if span else {})}


def parts_of(claim: dict) -> list[dict]:
    """The further passages a claim's pin lists (`source_parts`), checked for form."""
    parts = claim.get("source_parts")
    if parts is None:
        return []
    if not isinstance(parts, list) or not parts:
        raise RegionError("source_parts must be a non-empty list")
    for i, part in enumerate(parts, start=1):
        if not isinstance(part, dict) or set(part) - PART_KEYS or "location" not in part:
            raise RegionError(f"source part {i} needs a location, optional bounds, an optional "
                              "macro, and its digests")
        if location(part) is None:
            raise RegionError(f"source part {i} needs a file:line location")
        if "macro" in part and not (isinstance(part["macro"], str)
                                    and MACRO.fullmatch(part["macro"])):
            raise RegionError(f"source part {i}: macro must be a control sequence such as "
                              "\\name")
    return parts


def role(part: dict) -> str:
    return f"macro {part['macro']}" if part.get("macro") else "passage"


def composite(main_sha: str, parts: list[tuple[dict, str]]) -> str:
    """The digest of a pin of several passages: of the scheme, then each passage's role and
    digest in order, the claim's own passage first. It depends on the text only, not on where
    the passages are."""
    text = MULTI + "\n" + f"passage {main_sha}\n" + "".join(
        f"{role(p)} {sha}\n" for p, sha in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def defines(text: str, name: str) -> bool:
    """Whether `text` defines the macro `name` (outside comments)."""
    live = "\n".join(COMMENT_LINE.sub("", ln) for ln in text.split("\n"))
    return any(name in (m.group(1), m.group(2)) for m in DEFINITION.finditer(live))


COMMENT_LINE = re.compile(r"(?<!\\)%.*")


@dataclass(frozen=True)
class Pin:
    """A claim's pinned text: its own passage and the further passages its pin lists."""
    main: Region
    parts: tuple[tuple[dict, Region], ...] = ()

    @property
    def scheme(self) -> str:
        return MULTI if self.parts else SCHEME

    @property
    def sha256(self) -> str:
        if not self.parts:
            return self.main.sha256
        return composite(self.main.sha256, [(p, r.sha256) for p, r in self.parts])

    def record(self) -> dict:
        rec = self.main.record()
        if self.parts:
            rec.update(scheme=MULTI, sha256=self.sha256, passage_sha256=self.main.sha256,
                       parts=[{**r.record(), **({"macro": p["macro"]} if p.get("macro")
                                                else {})} for p, r in self.parts])
        return rec


def pin(root: Path, claim: dict) -> Pin:
    """The passages of a claim's pin in the snapshot at `root`. A pin that lists further
    passages has the scheme `tex-regions-v1`; a part that pins a macro must define it."""
    parts = parts_of(claim)
    scheme = claim.get("source_hash_scheme")
    if parts and scheme not in (None, MULTI):
        raise RegionError(f"a pin with source_parts has the scheme {MULTI}, not {scheme}")
    if scheme == MULTI and not parts:
        raise RegionError(f"the scheme {MULTI} needs source_parts")
    main = extract(root, claim)
    out = []
    for i, part in enumerate(parts, start=1):
        try:
            region = extract(root, part_claim(part))
        except RegionError as error:
            raise RegionError(f"source part {i} ({part['location']}): {error}") from None
        if part.get("macro") and not defines(region.text, part["macro"]):
            raise RegionError(f"source part {i} ({part['location']}) does not define "
                              f"{part['macro']}")
        out.append((part, region))
    return Pin(main, tuple(out))


def tex_sources(root: Path) -> dict[str, str]:
    """The text of every TeX file of a snapshot (`.tex`, `.sty`, `.cls`), by relative path."""
    out = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.suffix not in (".tex", ".sty", ".cls") or not path.is_file() or \
                {".git", ".lake", ".machinechecked", ".prooflens"} & set(rel.parts):
            continue
        try:
            out[rel.as_posix()] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
    return out


def definitions(files: dict[str, str]) -> dict[str, list[tuple[str, int]]]:
    """Where the snapshot defines each macro: name to (file, line) of every definition."""
    out: dict[str, list[tuple[str, int]]] = {}
    for name, text in files.items():
        for k, line in enumerate(text.split("\n"), start=1):
            for m in DEFINITION.finditer(COMMENT_LINE.sub("", line)):
                out.setdefault(m.group(1) or m.group(2), []).append((name, k))
    return out


def definition_part(files: dict[str, str], name: str, file: str | None = None,
                    line: int | None = None) -> dict:
    """The part pinning the definition of macro `name`: its only definition in the snapshot,
    or the one at `file:line`, from its first line through the line that closes its body."""
    where = [(f, ln) for f, ln in definitions(files).get(name, [])
             if (file is None or f == file) and (line is None or ln == line)]
    if not where:
        raise RegionError(f"no definition of {name}"
                          + (f" at {file}:{line}" if file else " in the manuscript"))
    if len(where) > 1:
        raise RegionError(f"{name} is defined {len(where)} times ("
                          + ", ".join(f"{f}:{ln}" for f, ln in where)
                          + "); name the one to pin as NAME@FILE:LINE")
    f, ln = where[0]
    text = files[f]
    offset = sum(len(x) + 1 for x in text.split("\n")[:ln - 1])
    line_text = text.split("\n")[ln - 1]
    m = next(m for m in DEFINITION.finditer(COMMENT_LINE.sub("", line_text))
             if name in (m.group(1), m.group(2)))
    end = _definition_end(text, offset + m.end())
    end_line = text.count("\n", 0, end) + 1
    return {"location": f"{f}:{ln}", **({"end_line": end_line} if end_line > ln else {}),
            "macro": name}


def _definition_end(text: str, i: int) -> int:
    """The index just past the body of a definition whose name ends at `i`: past an optional
    closing brace of the name, its argument specification and its braced body."""
    while i < len(text) and text[i] in " \t}":
        i += 1
    while i < len(text) and text[i] != "{":
        if text[i] == "\\" or text[i] == "\n" and text[i + 1:i + 2] == "\n":
            # \let, or a body that is not braced: the definition ends on its line.
            return text.find("\n", i) if "\n" in text[i:] else len(text)
        i += 1
    depth = 0
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            nl = text.find("\n", i)
            i = nl if nl >= 0 else len(text)
            continue
        depth += (c == "{") - (c == "}")
        i += 1
        if depth == 0:
            return i
    return len(text)


def used_macros(text: str) -> set[str]:
    return {m.group() for ln in text.split("\n")
            for m in MACRO.finditer(COMMENT_LINE.sub("", ln))}


def unpinned_macros(p: Pin, defs: dict[str, list[tuple[str, int]]]) -> list[dict]:
    """The macros the pinned passages use that the snapshot defines outside them, without a
    part pinning a definition: each with where it is defined."""
    passages = [p.main] + [r for part, r in p.parts if not part.get("macro")]
    pinned = {part["macro"] for part, _ in p.parts if part.get("macro")}
    inside = {(r.file, ln) for r in [p.main] + [r for _, r in p.parts]
              for ln in range(r.start_line, r.end_line + 1)}
    used = set().union(*(used_macros(r.text) for r in passages))
    out = []
    for name in sorted(used - pinned):
        where = defs.get(name) or []
        outside = [w for w in where if w not in inside]
        if outside and len(outside) == len(where):
            out.append({"macro": name, "defined": [f"{f}:{ln}" for f, ln in outside]})
    return out


NOTATION = "tex-notation-v1"


def macro_name(name: str) -> str:
    """A macro named in the configuration, as a control sequence: `R` or `\\R` is `\\R`."""
    name = name.strip()
    name = name if name.startswith("\\") else "\\" + name
    if not MACRO.fullmatch(name):
        raise RegionError(f"notation macro {name!r} is not a control sequence such as \\R")
    return name


def notation_digests(root: Path, files: dict[str, str], defs: dict[str, list[tuple[str, int]]],
                     names) -> dict[str, dict]:
    """The digest of the definition of each listed notation macro the snapshot defines: of the
    scheme, then the digest of each of its definitions in file order (each from its first line
    through the line that closes its body), so a move keeps it and a change to any definition
    changes it. A macro whose definitions cannot be delimited has none."""
    out = {}
    for name in names:
        where = defs.get(name) or []
        if not where:
            continue
        try:
            shas = [extract(root, part_claim(definition_part(files, name, f, ln))).sha256
                    for f, ln in where]
        except RegionError:
            continue
        text = NOTATION + "\n" + "".join(f"definition {sha}\n" for sha in shas)
        out[name] = {"macro": name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     "defined": [f"{f}:{ln}" for f, ln in where]}
    return out


def collect(inventory: dict, paper: str, root: Path, notation=()) -> dict:
    """One record per claim, including extraction errors; shared start lines do not collide.
    A record also names the macros its passages use that the snapshot defines elsewhere and
    the pin leaves out: the listed notation macros (`notation`, each with the digest of its
    definitions), and the others (`macros`). Names in `notation` are control sequences. A
    record carries `advice` when its region may not hold the claim's text."""
    out = {}
    defs = files = None
    listed = set(notation)
    digests: dict[str, dict] | None = None
    for claim in inventory["claims"]:
        if claim["paper"] != paper:
            continue
        try:
            if location(claim) is None:
                continue
            p = pin(root, claim)
            rec = p.record()
            if defs is None:
                files = tex_sources(root)
                defs = definitions(files)
            outside = unpinned_macros(p, defs)
            if listed and digests is None and any(m["macro"] in listed for m in outside):
                digests = notation_digests(root, files, defs, sorted(listed))
            hashed = [digests[m["macro"]] for m in outside if m["macro"] in (digests or {})]
            macros = [m for m in outside if m["macro"] not in (digests or {})]
            if macros:
                rec["macros"] = macros
            if hashed:
                rec["notation"] = hashed
            adv = region_advice(root, p.main, theorem_names(files))
            if adv:
                rec["advice"] = adv
            out[claim["id"]] = rec
        except (RegionError, OSError, UnicodeError) as error:
            out[claim["id"]] = {"scheme": claim.get("source_hash_scheme") or SCHEME,
                                "error": str(error)}
    return out


def part_texts(inventory: dict, paper: str, root: Path) -> dict[str, list[dict]]:
    """For each claim of `paper` whose pin lists further passages, every passage in order, the
    claim's own first: its file, lines, role and text, for the reader and the review packet
    (published only with the source text). Display only."""
    out = {}
    for claim in inventory["claims"]:
        if claim["paper"] != paper or not claim.get("source_parts") or location(claim) is None:
            continue
        try:
            p = pin(root, claim)
        except (RegionError, OSError, UnicodeError):
            continue
        out[claim["id"]] = [
            {"file": r.file, "start_line": r.start_line, "end_line": r.end_line,
             **({"macro": part["macro"]} if part.get("macro") else {}), "text": r.text}
            for part, r in [({}, p.main), *p.parts]]
    return out


def region_texts(inventory: dict, paper: str, root: Path, regions: dict) -> dict[str, str]:
    """For each claim of `paper` located by line whose region was read (`regions`, from
    `collect`): the text of its own passage, read from the file of the snapshot that holds it,
    as the claim's printed statement for the reader, the search and the review packet
    (published only with the source text). Display only."""
    out = {}
    for claim in inventory["claims"]:
        if claim["paper"] != paper or (regions.get(claim["id"]) or {}).get("error"):
            continue
        try:
            if location(claim) is None:
                continue
            out[claim["id"]] = extract(root, claim).text
        except (RegionError, OSError, UnicodeError):
            continue
    return out


def matches(claim: dict, tex: dict) -> bool:
    rec = (tex.get("regions") or {}).get(claim["id"], {})
    return bool(claim.get("source_sha256") and not rec.get("error")
                and claim.get("source_hash_scheme") in SCHEMES
                and claim.get("source_hash_scheme") == rec.get("scheme")
                and claim["source_sha256"] == rec.get("sha256"))


def same_revision(pin: str, revision: str) -> bool:
    """Whether an inventory's pin names the snapshot's revision: the same value, or an
    abbreviated commit hash (at least 7 hexadecimal digits) of it."""
    return pin == revision or bool(re.fullmatch(r"[0-9a-f]{7,40}", pin)
                                   and re.fullmatch(r"[0-9a-f]{40}", revision)
                                   and revision.startswith(pin))


def _changed_lines(old, new, file: str, start: int, what: str) -> str | None:
    if not old or not new:
        return None
    for i, (a, b) in enumerate(zip(old, new)):
        if a != b:
            return f"line {i + 1} of {what} (line {start + i} of {file}) changed"
    if len(old) != len(new):
        return (f"{what} has {len(new)} lines, not {len(old)}: lines were "
                + ("added" if len(new) > len(old) else "removed") + " at its end")
    return None


def changed_line(claim: dict, rec: dict) -> str | None:
    """Where a pin differs from its passages, from the digests both sides keep: the first
    changed line of the claim's passage, by its place in the passage and in the file, or a
    change in its length; else the first further passage that changed, and where."""
    if not rec.get("start_line"):
        return None
    main = _changed_lines(claim.get("source_line_sha256"), rec.get("line_sha256"),
                          rec["file"], rec["start_line"], "the passage")
    if main:
        return main
    old, new = claim.get("source_parts") or [], rec.get("parts") or []
    if len(old) != len(new):
        return f"the pin lists {len(old)} further passages, the evidence {len(new)}"
    for i, (a, b) in enumerate(zip(old, new), start=1):
        if a.get("sha256") != b.get("sha256"):
            what = f"part {i}" + (f" (the definition of {b['macro']})" if b.get("macro") else "")
            at = _changed_lines(a.get("line_sha256"), b.get("line_sha256"), b["file"],
                                b["start_line"], what)
            return at or f"{what}, at {b['file']}:{b['start_line']}, changed"
    if old and rec.get("passage_sha256") and claim.get("source_sha256") != rec.get("sha256"):
        return "the passage changed"
    return None


def migration_plan(inventory: dict, paper: str, root: Path, revision: str) -> tuple[dict, list]:
    """Rehash only the original frozen snapshot; never edit a review or a paper revision."""
    result = deepcopy(inventory)
    changes = []
    for claim in result["claims"]:
        if claim["paper"] != paper or location(claim) is None:
            continue
        rev_pin = claim.get("commit") or inventory.get("papers", {}).get(paper, {}).get("commit")
        if not rev_pin or not same_revision(str(rev_pin).removeprefix("arxiv:"), revision):
            raise RegionError(f"{claim['id']}: original paper revision must match {revision}")
        scheme = claim.get("source_hash_scheme")
        if scheme not in (None, *SCHEMES):
            raise RegionError(f"{claim['id']}: unknown source hash scheme {scheme!r}")
        if scheme is None and claim.get("source_parts"):
            raise RegionError(f"{claim['id']}: a legacy line hash with source_parts; pin its "
                              "passages with `machinechecked inventory rebound`")
        try:
            p = pin(root, claim)
        except RegionError as error:
            raise RegionError(f"{claim['id']}: {error}") from None
        region = p.main
        expected = claim.get("source_sha256")
        if scheme in SCHEMES:
            if expected != p.sha256:
                raise RegionError(f"{claim['id']}: region differs from its frozen hash")
            if claim.get("source_line_sha256") != region.line_sha256:
                # The same passage: add the line digests it was pinned without.
                claim["source_line_sha256"] = region.line_sha256
                changes.append({"claim": claim["id"], "old_sha256": expected,
                                "lines_added": True, **p.record()})
            continue
        name, line = location(claim)
        original = source_file(root, name).read_text(encoding="utf-8").split("\n")[line - 1]
        legacy = hashlib.sha256(" ".join(original.split()).encode("utf-8")).hexdigest()
        if not expected or expected != legacy:
            raise RegionError(f"{claim['id']}: legacy hash does not match the original snapshot")
        claim.update(source_sha256=region.sha256, source_hash_scheme=SCHEME,
                     source_line_sha256=region.line_sha256)
        changes.append({"claim": claim["id"], "old_sha256": expected, **region.record()})
    if not any(c["paper"] == paper for c in inventory["claims"]):
        raise RegionError(f"no claims for paper {paper}")
    return result, changes


def _indent(raw: bytes) -> int:
    """The indentation of a JSON file, so that a rewrite changes only the fields it updates."""
    m = re.search(rb"\n( +)\S", raw)
    return len(m.group(1)) if m else 2


def write_plan(path: Path, before: bytes, result: dict) -> None:
    """Atomically replace the inventory only if it is still the one that was planned, in its
    own indentation."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".source-regions-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=_indent(before))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        if path.read_bytes() != before:
            raise RegionError("inventory changed while planning; rerun without --write")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


REVISION = re.compile(r"(?:arxiv:)?(?:[0-9a-f]{7,40}|[A-Za-z0-9./-]+v\d+)")


def folder(cfg, paper, spec: str, dest: Path) -> Path:
    """A copy, at `dest`, of the manuscript named by `spec`: a folder, or `git:REV`, the folder
    the configuration reads the paper from (`source = { path = ... }`) as committed at revision
    REV of the repository that holds it."""
    import dataclasses
    import io
    import subprocess
    import tarfile
    from .sources import acquire
    if spec.startswith("git:"):
        rev = spec[len("git:"):]
        if "path" not in paper.source:
            raise RegionError(f"{spec}: git:REV names a revision of the folder the paper is "
                              "read from, and this paper's source is not a folder")
        base = (cfg.root / paper.source["path"]).resolve()
        top = subprocess.run(["git", "-C", str(base), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True)
        if top.returncode != 0:
            raise RegionError(f"{spec}: {base} is not in a Git repository")
        rel = base.relative_to(Path(top.stdout.strip()).resolve()).as_posix()
        tree = f"{rev}:{rel}" if rel != "." else f"{rev}:"
        arch = subprocess.run(["git", "-C", top.stdout.strip(), "archive", "--format=tar",
                               tree], capture_output=True)
        if arch.returncode != 0:
            raise RegionError(f"{spec}: the folder {rel} cannot be read at revision {rev}: "
                              + arch.stderr.decode(errors="replace").strip())
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(arch.stdout)) as t:
            t.extractall(dest, filter="data")
        return dest
    path = Path(spec).resolve()
    if not path.is_dir():
        raise RegionError(f"{spec} is not a folder")
    snap = acquire(cfg, dataclasses.replace(paper, source={"path": str(path)}), dest)
    if snap.mode != "latex":
        raise RegionError(f"{spec} holds no LaTeX source")
    return snap.dir


def baseline(cfg, paper, inventory: dict, dest: Path, source: str | None = None,
             rev: str | None = None) -> tuple[Path, str]:
    """The manuscript at the revision the inventory was pinned at, and that revision.

    A Git or arXiv source is acquired at the configuration's pin. A folder (`source`, or a
    configuration that reads the paper from a folder, as a manuscript vendored into the
    project) has no revision of its own: it is the revision `rev`, else the one the
    configuration records for the folder (`source = { path = ..., rev = ... }`), else the one
    the inventory records under `papers`. Either way the claims' pins are verified against the snapshot
    before anything is planned, so a folder that does not hold that revision is refused."""
    from .sources import acquire
    recorded = ((inventory.get("papers") or {}).get(paper.id) or {}).get("commit")
    if source is None and "path" in paper.source:
        source = str((cfg.root / paper.source["path"]).resolve())
    if source is not None:
        revision = rev or (paper.source.get("rev") if "path" in paper.source else None) \
            or recorded
        if not revision:
            raise RegionError(
                f"the revision of {source} is not recorded: pass --rev REV, or record it as "
                f"papers.{paper.id}.commit in the inventory")
        if not REVISION.fullmatch(str(revision)):
            raise RegionError(f"{revision!r} is not a commit or a versioned arXiv identifier")
        return folder(cfg, paper, source, dest), str(revision).removeprefix("arxiv:")
    if rev is not None:
        raise RegionError("--rev names the revision of a folder given with --source")
    if "git" in paper.source:
        if not re.fullmatch(r"[0-9a-f]{40}", str(paper.source.get("rev", ""))):
            raise RegionError("the original revision must be a full Git commit, not a branch "
                              "or tag")
    snap = acquire(cfg, paper, dest)
    if not snap.revision or snap.mode != "latex":
        raise RegionError("needs a pinned LaTeX source snapshot")
    return snap.dir, snap.revision


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hash source regions at their original pinned revision")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--source", help="the manuscript at its pinned revision: a folder, or "
                        "git:REV for the configured folder as committed at REV (default: the "
                        "configured source)")
    parser.add_argument("--rev", help="the paper revision --source (or a configured folder) "
                        "holds (default: the inventory's papers.PAPER.commit)")
    parser.add_argument("--write", action="store_true", help="apply the verified plan (default: dry run)")
    args = parser.parse_args(argv)
    from .config import load
    try:
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        before = cfg.inventory.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-source-regions-") as temp:
            root, revision = baseline(cfg, paper, inventory, Path(temp) / paper.id,
                                      args.source, args.rev)
            result, changes = migration_plan(inventory, paper.id, root, revision)
        if args.write and changes:
            write_plan(cfg.inventory, before, result)
        print(json.dumps({"applied": args.write, "paper": paper.id, "changes": changes}, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"source regions: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
