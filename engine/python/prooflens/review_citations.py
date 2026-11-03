"""Declarations and files that review text cites (#178).

A review often justifies its reading by citing a lemma (`Foo.bar_eq_span`) or a file. Every
backticked token of a review file that looks like a Lean name (no spaces, and an `_` or a `.`)
is resolved by the probe against the environment: the project, its dependencies and Lean's own
library (`names` request). A name resolves when a declaration, namespace or module has it, or
has it as its last components; one the environment lacks is looked up in the Lean sources of the
project and its Lake packages, which hold the modules the probe did not load (#221). A
backticked token that looks like a path (one with a file extension, or a folder ending in `/`)
resolves when a file or folder of the project or of its Lake packages ends with it. What does not resolve is a finding of the `warning` tier (code
`review-citation`), with its file and line; `review_citations_strict = true` makes it a
violation. Fenced code blocks, the `Review by` lines promotion writes, reviewers' names and
tokens matching `review_citations_ignore` (mathematical notation such as `x_i`) are skipped, and
so is review text that records the removal of a declaration, which must name it (#270): an
archived marker (`<!-- archived at … -->`), a removal record (a paragraph or list item that opens
with a bold lead-in saying that something was removed or retired, `**Clauses removed.**`), and a
name followed by such a note (`` `Foo.old` (removed at rev2) ``).

A citation belongs to the block of review text that the next marker closes (#510), named `at` by
that marker's kind, declaration and hash (`spec-review: Foo.spec <hash>`, the same for a retired
marker; ` (2)` and on for a later marker with the same head in the file), or `end of file` when
no marker follows. Each block that cites a token nothing resolves is one warning, with every line
of the block that cites it. A dismissal names one block: it holds while the warning at its `at`
has its `fingerprint`, which covers the lines that cite the token, so a new citation of the
token in the block, or one in another block, is warned about again.
"""

from __future__ import annotations

import bisect
import hashlib
import os
import re
from pathlib import Path

from .reviews import ANY, HEADING, PROMOTED, review_files
from .source_names import SourceNames, last

# Mathematical notation written in code spans: a symbol of one letter (perhaps primed) with a
# subscript or a field (`x_i`, `C_rel`, `X'_T`, `μ.law`), or of two letters with a short
# subscript (`ab_n`).
DEFAULT_IGNORE = [r"^[^\W\d_]['′]*[._]", r"^[^\W\d_]{2}_[^\W_]{1,6}$"]

CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
NAME_PART = r"[^\W\d][\w'!?₀-₉]*"
NAME = re.compile(rf"{NAME_PART}(?:\.{NAME_PART})*")
EXTENSIONS = (".lean", ".tex", ".md", ".json", ".toml", ".yaml", ".yml", ".py", ".sty", ".bib",
              ".txt", ".pdf", ".sh", ".cfg")

# Review text that records the removal of a declaration. An archived marker is an HTML comment
# that may span lines. A removal record opens with a bold lead-in and runs to the end of its
# paragraph, with a list directly under it, or of its list item, with the items nested in it. A
# note follows the cited name.
ARCHIVED = re.compile(r"<!--\s*archived\s+at\b.*?-->", re.S | re.I)
ITEM = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s")
LEAD = re.compile(r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(\*\*|__)(.+?)\1")
REMOVED = re.compile(r"\b(?:removed|retired)\b", re.I)
NOTE = re.compile(r"\s*\((?:removed|retired)\b", re.I)


def classify(token: str) -> str | None:
    """`path` for a token that looks like a file path, `name` for one that looks like a Lean
    name, None for anything else (prose, an expression, notation)."""
    t = token.strip()
    if not t or any(ch.isspace() for ch in t):
        return None
    if t.lower().endswith(EXTENSIONS) or ("/" in t and t.endswith("/")):
        return "path" if re.fullmatch(r"[A-Za-z0-9_./@+-]+", t) and not t.startswith(
            ("http", "/")) else None
    if "/" in t:
        return None
    if ("_" in t or "." in t) and NAME.fullmatch(t):
        return "name"
    return None


def reviewer(m: re.Match) -> str | None:
    """The reviewer a marker matched by `ANY` names (its `by` attribute), or None: its
    attributes are group 4 of a live marker and group 8 of a retired one, and a marker may have
    none."""
    attrs = (m.group(4) if m.group(1) else m.group(8)) or ""
    return dict(a.split("=", 1) for a in attrs.split() if "=" in a).get("by")


END = "end of file"


def markers(text: str) -> list[tuple[int, str, dict]]:
    """The markers of a review file's text, in order: where each starts, the name of the block
    of text it closes (`at`), and its declaration, line and whether it is retired. The name is the
    marker's kind, declaration and hash, which retiring the marker or adding attributes to it
    leaves as they are; a later marker with the same kind, declaration and hash in the file has
    ` (2)`, ` (3)`, … after it."""
    out, seen = [], {}
    for m in ANY.finditer(text):
        live = m.group(1) is not None
        kind, name, h = m.group(1, 2, 3) if live else m.group(5, 6, 7)
        head = f"{kind}-review: {name} {h}"
        seen[head] = seen.get(head, 0) + 1
        at = head if seen[head] == 1 else f"{head} ({seen[head]})"
        out.append((m.start(), at, {"name": name, "retired": not live,
                                    "line": text.count("\n", 0, m.start()) + 1}))
    return out


def without_markers(line: str) -> tuple[str, list[tuple[int, int]]]:
    """The line with its markers removed, and for each marker removed, where it was in the
    result and its length."""
    parts, cuts, last, at = [], [], 0, 0
    for m in ANY.finditer(line):
        parts.append(line[last:m.start()])
        at += m.start() - last
        cuts.append((at, m.end() - m.start()))
        last = m.end()
    parts.append(line[last:])
    return "".join(parts), cuts


def citations(files: list[Path], root: Path, ignore: list[str] | None = None) -> list[dict]:
    """Every name and path cited in backticks by the review files `files`, with the file (as
    relative to `root`), line and block (`at`, and the `marker` that closes it, None at the end
    of the file), in file order."""
    pats = [re.compile(p) for p in (DEFAULT_IGNORE if ignore is None else ignore)]
    out = []
    for f in review_files(files):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        # An archived marker is blanked out, keeping its line breaks so that lines keep their
        # numbers.
        text = ARCHIVED.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)
        reviewers = {by for m in ANY.finditer(text) if (by := reviewer(m))}
        rel = f.resolve().relative_to(root.resolve()).as_posix() \
            if f.resolve().is_relative_to(root.resolve()) else f.name
        marks = markers(text)
        starts = [m[0] for m in marks]
        lines = text.split("\n")
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line) + 1)
        # In a removal record: -1 when it is a paragraph, the indentation of its list item
        # when it is one, None outside.
        fence, removal = False, None
        for i, line in enumerate(lines, 1):
            if line.lstrip().startswith(("```", "~~~")):
                fence, removal = not fence, None
                continue
            if fence or PROMOTED.match(line):
                continue
            item = ITEM.match(line)
            if not line.strip() or HEADING.match(line) or ANY.search(line) or (
                    item and removal is not None and len(item.group(1)) <= removal):
                removal = None
            lead = LEAD.match(line)
            if lead and REMOVED.search(lead.group(2)):
                removal = len(item.group(1)) if item else -1
            if removal is not None:
                continue
            bare, cuts = without_markers(line)
            for m in CODE.finditer(bare):
                tok = m.group(1).strip()
                kind = classify(tok)
                if kind is None or tok in reviewers or any(p.search(tok) for p in pats) \
                        or NOTE.match(bare, m.end()):
                    continue
                # The first marker after the citation closes its block.
                col = m.start() + sum(n for at, n in cuts if at <= m.start())
                k = bisect.bisect_left(starts, offsets[i - 1] + col)
                at, marker = (marks[k][1], marks[k][2]) if k < len(marks) else (END, None)
                out.append({"file": rel, "line": i, "token": tok, "kind": kind, "at": at,
                            "marker": marker, "text": line.strip()})
    return out


def names_request(cites: list[dict]) -> dict | None:
    """The probe request that resolves the cited names, or None when there are none."""
    names = sorted({c["token"] for c in cites if c["kind"] == "name"})
    return {"kind": "names", "name": "", "names": names} if names else None


SKIP = {".git", ".machinechecked", ".prooflens", "build", "node_modules", "__pycache__"}


def project_paths(roots: list[Path]) -> set[str]:
    """Every file and folder under `roots` (the project, and the Lake packages it depends on),
    as paths relative to its root, without version control and build output."""
    out: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP]
            rel = Path(dirpath).relative_to(root).as_posix()
            pre = "" if rel == "." else rel + "/"
            if pre:
                out.add(pre)
            out.update(pre + f for f in files)
    return out


def path_exists(token: str, paths: set[str]) -> bool:
    """Whether a cited path is a file or folder of the project: one whose path relative to the
    project, or to some folder of it (a library's root, a package, the review's folder), is the
    token."""
    return token in paths or any(p.endswith("/" + token) for p in paths)


def unresolved(cites: list[dict], names: dict | None, roots: list[Path]) -> list[dict]:
    """The citations nothing resolves: a name the probe checked and found nowhere, a path that
    is no file of the project. A name the stored probe records did not check (a review edited
    since, assessed with `--reuse-lean` or `reassess`) is not reported."""
    checked = set((names or {}).get("checked", []))
    missing = set((names or {}).get("unresolved", []))
    paths = project_paths(roots) if any(c["kind"] == "path" for c in cites) else set()
    out = []
    for c in cites:
        if c["kind"] == "name":
            if c["token"] in checked and c["token"] in missing:
                out.append(c)
        elif not path_exists(c["token"], paths):
            out.append(c)
    # A name the probe's environment lacks may be declared by a module it did not load (#221).
    missing_names = {c["token"] for c in out if c["kind"] == "name"}
    if missing_names:
        src = SourceNames(roots, {last(t) for t in missing_names})
        out = [c for c in out if c["kind"] != "name" or not src.known_suffix(c["token"])]
    return out


def blocks(cites: list[dict]) -> list[dict]:
    """One warning for each review file, token and block among `cites`, in the order of their
    first citation: the first `line`, every line of the block that cites the token (`lines`),
    and the `fingerprint` a dismissal of it records."""
    out, by = [], {}
    for c in cites:
        key = (c["file"], c["token"], c["at"])
        if key not in by:
            by[key] = {**{k: c[k] for k in ("file", "token", "kind", "line", "at", "marker")},
                       "lines": [], "texts": []}
            out.append(by[key])
        if c["line"] not in by[key]["lines"]:
            by[key]["lines"].append(c["line"])
            by[key]["texts"].append(c["text"])
    for w in out:
        w["fingerprint"] = fingerprint(w)
    return out


def message(w: dict) -> str:
    what = ("no declaration of the project, its dependencies or Lean" if w["kind"] == "name"
            else "no file of the project")
    m = w["marker"]
    block = "no marker follows" if m is None else \
        f"before the {'retired ' if m['retired'] else ''}marker of {m['name']} at line {m['line']}"
    lines = ", ".join(str(n) for n in w["lines"])
    return f"{w['file']}:{lines} ({block}): the review cites {w['token']}, which is {what}"


def fingerprint(w: dict) -> str:
    """What a dismissal of a warning is tied to, with the warning's `at`: the review file, the
    cited token and the text of each line of the block that cites it. Another citation of the
    token in the block, or an edit of a line that cites it, changes it; moving the block does
    not."""
    key = "\n".join((w["file"], w["token"], *w["texts"]))
    return "pl-cite-v2:" + hashlib.sha256(key.encode()).hexdigest()


def file_fingerprint(file: str, token: str) -> str:
    """The fingerprint of a dismissal written before dismissals named a block: the review file
    and the cited token."""
    return "pl-cite-v1:" + hashlib.sha256("\n".join((file, token)).encode()).hexdigest()


def dismiss(found: list[dict], dismissals: list[dict]) -> None:
    """Mark the citation warnings `found` (each with `subject`, `trigger`, `at` and
    `fingerprint`, in file order) that a dismissal covers as `dismissed`, and those it no longer
    covers as `dismissal_stale`.

    A dismissal with `at` covers the warning at `at` while that warning has its fingerprint. When
    the fingerprint differs, or the block is gone and exactly one warning of the token in the
    file has the fingerprint (its marker changed), that warning is marked stale; no other is. A
    dismissal without `at` (written before dismissals named a block) covers the first block that
    cites the token in the file, where the warning it was given for was reported, while its
    fingerprint is the file and token's (`dismissed.form`: `file`); every other block of the
    token in the file, which it used to cover, is marked stale."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for f in found:
        groups.setdefault((f["subject"], f["trigger"]), []).append(f)
    for (subj, tok), fs in groups.items():
        ds = [d for d in dismissals if d.get("code") == "review-citation"
              and d.get("subject") == subj and d.get("trigger") == tok]
        named = [d for d in ds if "at" in d]
        legacy = [d for d in ds if "at" not in d]
        here = {f["at"] for f in fs}
        for k, f in enumerate(fs):
            hit = next((d for d in named if d["at"] == f["at"]
                        and d.get("fingerprint") == f["fingerprint"]), None)
            if hit is None and k == 0:
                hit = next((d for d in legacy
                            if d.get("fingerprint") == file_fingerprint(subj, tok)), None)
            if hit is not None:
                f["dismissed"] = {"rationale": hit.get("rationale", ""), "by": hit.get("by", "")}
                if "at" not in hit:
                    f["dismissed"]["form"] = "file"
                continue
            moved = sum(g["fingerprint"] == f["fingerprint"] for g in fs) == 1 and any(
                d["at"] not in here and d.get("fingerprint") == f["fingerprint"] for d in named)
            if legacy or moved or any(d["at"] == f["at"] for d in named):
                f["dismissal_stale"] = True
