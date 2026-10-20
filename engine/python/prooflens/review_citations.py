"""Declarations and files that review text cites (#178).

A review often justifies its reading by citing a lemma (`Foo.bar_eq_span`) or a file. Every
backticked token of a review file that looks like a Lean name (no spaces, and an `_` or a `.`)
is resolved by the probe against the environment: the project, its dependencies and Lean's own
library (`names` request). A name resolves when a declaration, namespace or module has it, or
has it as its last components. A backticked token that looks like a path is resolved against
the files of the project. What does not resolve is a finding of the `warning` tier (code
`review-citation`), with its file and line; `review_citations_strict = true` makes it a
violation. Fenced code blocks, the `Review by` lines promotion writes, reviewers' names and
tokens matching `review_citations_ignore` (mathematical notation such as `x_i`) are skipped.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .reviews import MARKER, PROMOTED, review_files

# Mathematical notation written in code spans: a symbol of one or two characters with a short
# subscript (`x_i`, `C_rel`, `T_n`).
DEFAULT_IGNORE = [r"^[^\W\d_]{1,2}_[^\W_]{1,6}$"]

CODE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
NAME_PART = r"[^\W\d][\w'!?₀-₉]*"
NAME = re.compile(rf"{NAME_PART}(?:\.{NAME_PART})*")
EXTENSIONS = (".lean", ".tex", ".md", ".json", ".toml", ".yaml", ".yml", ".py", ".sty", ".bib",
              ".txt", ".pdf", ".sh", ".cfg")


def classify(token: str) -> str | None:
    """`path` for a token that looks like a file path, `name` for one that looks like a Lean
    name, None for anything else (prose, an expression, notation)."""
    t = token.strip()
    if not t or any(ch.isspace() for ch in t):
        return None
    if "/" in t or t.lower().endswith(EXTENSIONS):
        return "path" if re.fullmatch(r"[\w./@+-]+", t) and not t.startswith(("http", "/")) \
            else None
    if ("_" in t or "." in t) and NAME.fullmatch(t):
        return "name"
    return None


def citations(files: list[Path], root: Path, ignore: list[str] | None = None) -> list[dict]:
    """Every name and path cited in backticks by the review files `files`, with the file (as
    relative to `root`) and line, in file order."""
    pats = [re.compile(p) for p in (DEFAULT_IGNORE if ignore is None else ignore)]
    out = []
    for f in review_files(files):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        reviewers = {dict(a.split("=", 1) for a in m.group(4).split() if "=" in a).get("by")
                     for m in MARKER.finditer(text)}
        rel = f.resolve().relative_to(root.resolve()).as_posix() \
            if f.resolve().is_relative_to(root.resolve()) else f.name
        fence = False
        for i, line in enumerate(text.split("\n"), 1):
            if line.lstrip().startswith(("```", "~~~")):
                fence = not fence
                continue
            if fence or PROMOTED.match(line):
                continue
            for m in CODE.finditer(MARKER.sub("", line)):
                tok = m.group(1).strip()
                kind = classify(tok)
                if kind is None or tok in reviewers or any(p.search(tok) for p in pats):
                    continue
                out.append({"file": rel, "line": i, "token": tok, "kind": kind,
                            "base": f.parent})
    return out


def names_request(cites: list[dict]) -> dict | None:
    """The probe request that resolves the cited names, or None when there are none."""
    names = sorted({c["token"] for c in cites if c["kind"] == "name"})
    return {"kind": "names", "name": "", "names": names} if names else None


def path_exists(token: str, bases: list[Path]) -> bool:
    """Whether a cited path names a file or folder under one of `bases`."""
    t = token.rstrip("/")
    for b in bases:
        try:
            p = (b / t).resolve()
        except (OSError, ValueError):
            continue
        if p.exists():
            return True
    return False


def unresolved(cites: list[dict], names: dict | None, bases: list[Path]) -> list[dict]:
    """The citations nothing resolves: a name the probe checked and found nowhere, a path that
    is no file of the project. A name the stored probe records did not check (a review edited
    since, assessed with `--reuse-lean` or `reassess`) is not reported."""
    checked = set((names or {}).get("checked", []))
    missing = set((names or {}).get("unresolved", []))
    out = []
    for c in cites:
        if c["kind"] == "name":
            if c["token"] in checked and c["token"] in missing:
                out.append(c)
        elif not path_exists(c["token"], [c["base"], *bases]):
            out.append(c)
    return out


def message(c: dict) -> str:
    what = ("no declaration of the project, its dependencies or Lean" if c["kind"] == "name"
            else "no file of the project")
    return f"{c['file']}:{c['line']}: the review cites {c['token']}, which is {what}"


def fingerprint(c: dict) -> str:
    """What a dismissal of a citation is tied to: the review file and the cited token."""
    key = "\n".join((c["file"], c["token"]))
    return "pl-cite-v1:" + hashlib.sha256(key.encode()).hexdigest()
