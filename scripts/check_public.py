#!/usr/bin/env python3
"""Refuse to publish material that belongs to private repositories.

    check_public.py --denylist FILE [--private-source DIR ...] [--range REV_RANGE]

Every line of FILE (blank lines and `#` comments aside) is a case-insensitive term that must not
occur in this repository's tracked files, nor, with --range, in the diffs and messages of the
commits of REV_RANGE (e.g. origin/main..HEAD, the commits about to be pushed). With
--private-source, every substantial line (30 characters or more, comments and imports aside) of
the `.lean` and `.tex` files under DIR must not occur there either: the mathematics of a private
project cannot be published even under another name. The denylist and the private sources are
kept outside this public repository. Exit status 1 lists every occurrence; 2 means the check
could not run (it then has not cleared anything).
"""

import argparse
import subprocess
import sys
from pathlib import Path


def terms(path: Path) -> list[str]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        t = line.strip()
        if t and not t.startswith("#"):
            out.append(t)
    return out


SKIP = ("--", "/-", "%", "import ", "open ", "namespace ", "end ", "section", "variable",
        "set_option", "\\usepackage", "\\newtheorem", "\\documentclass", "\\begin{document}",
        "\\theoremstyle")


def private_lines(dirs: list[str]) -> set[str]:
    out = set()
    for d in dirs:
        for f in Path(d).rglob("*"):
            if f.suffix not in (".lean", ".tex") or ".lake" in f.parts:
                continue
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                t = line.strip()
                if len(t) >= 30 and not t.startswith(SKIP):
                    out.add(t)
    return out


def git(args: list[str], cwd=None) -> str:
    """A git command's output, decoded as UTF-8 whatever the system's code page (git writes
    UTF-8; Windows would otherwise decode it as cp1252 and fail on the first other byte)."""
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8",
                       errors="replace")
    # `git grep` exits 1 when it finds nothing.
    if r.returncode != 0 and not (args[0] == "grep" and r.returncode == 1):
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return r.stdout


def main():
    try:
        check()
    except SystemExit:
        raise
    except Exception as e:  # a crash must never read as either answer
        print(f"check_public: could not run: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)


def check():
    p = argparse.ArgumentParser()
    p.add_argument("--denylist", required=True)
    p.add_argument("--private-source", action="append", default=[])
    p.add_argument("--range")
    a = p.parse_args()
    root = Path(git(["rev-parse", "--show-toplevel"]).strip())
    hits = []
    for t in terms(Path(a.denylist)):
        out = git(["grep", "-n", "-I", "-i", "-F", t, "--", ".", ":!web/package-lock.json"],
                  cwd=root)
        hits += [f"tree: {l}" for l in out.splitlines()]
        if a.range:
            for what, args in (("diff", ["log", "-p", "--format=", a.range]),
                               ("message", ["log", "--format=%h %B", a.range])):
                out = git(args, cwd=root)
                hits += [f"{what}: {t!r} in {l.strip()[:120]}" for l in out.splitlines()
                         if t.lower() in l.lower()]
    if a.private_source:
        lines = private_lines(a.private_source)
        files = git(["ls-files"], cwd=root).splitlines()
        hay = {f: (root / f).read_text(encoding="utf-8", errors="replace") for f in files
               if (root / f).is_file() and f != "web/package-lock.json"}
        if a.range:
            hay["(commits to push)"] = git(["log", "-p", "--format=%B", a.range], cwd=root)
        for where, text in hay.items():
            for line in lines:
                if line in text:
                    hits.append(f"private source line in {where}: {line[:100]}")
    for h in hits:
        print(h)
    if hits:
        print(f"{len(hits)} occurrence(s) of private terms: not publishable")
        sys.exit(1)
    print("no private terms")


if __name__ == "__main__":
    main()
