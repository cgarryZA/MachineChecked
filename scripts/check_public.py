#!/usr/bin/env python3
"""Refuse to publish material that belongs to private repositories.

    check_public.py --denylist FILE [--range REV_RANGE]

Every line of FILE (blank lines and `#` comments aside) is a case-insensitive term that must not
occur in this repository's tracked files, nor, with --range, in the diffs and messages of the
commits of REV_RANGE (e.g. origin/main..HEAD, the commits about to be pushed). The denylist itself
is kept outside this public repository, in the private repository it protects. Exit status 1
lists every occurrence.
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--denylist", required=True)
    p.add_argument("--range")
    a = p.parse_args()
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                               text=True, check=True).stdout.strip())
    hits = []
    for t in terms(Path(a.denylist)):
        r = subprocess.run(["git", "grep", "-n", "-I", "-i", "-F", t, "--", ".",
                            ":!web/package-lock.json"], cwd=root, capture_output=True, text=True)
        hits += [f"tree: {l}" for l in r.stdout.splitlines()]
        if a.range:
            for what, args in (("diff", ["log", "-p", "--format=", a.range]),
                               ("message", ["log", "--format=%h %B", a.range])):
                r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
                if r.returncode != 0:
                    sys.exit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
                out = r.stdout
                hits += [f"{what}: {t!r} in {l.strip()[:120]}" for l in out.splitlines()
                         if t.lower() in l.lower()]
    for h in hits:
        print(h)
    if hits:
        print(f"{len(hits)} occurrence(s) of private terms: not publishable")
        sys.exit(1)
    print("no private terms")


if __name__ == "__main__":
    main()
