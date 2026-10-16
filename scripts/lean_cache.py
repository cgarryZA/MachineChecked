#!/usr/bin/env python3
"""Save and restore a Lean project's build output as GitHub release assets: the arguments of
the former script, kept for setup scripts that call it. The code is `prooflens.cache`
(`machinechecked cache --help`), which documents what is saved and checked.

    lean_cache.py save    PROJECT [--target T ...] [--pin-file F] [--out DIR]
    lean_cache.py publish PROJECT REPO [--out DIR]
    lean_cache.py restore PROJECT REPO [--build]
"""

import argparse
import sys
from pathlib import Path

# The engine beside this script, so it runs from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine" / "python"))
from prooflens import cache  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("project")
    s.add_argument("--target", action="append", default=[])
    s.add_argument("--pin-file")
    s.add_argument("--out", default=".lean-cache")
    u = sub.add_parser("publish")
    u.add_argument("project")
    u.add_argument("repo")
    u.add_argument("--out", default=".lean-cache")
    r = sub.add_parser("restore")
    r.add_argument("project")
    r.add_argument("repo")
    r.add_argument("--build", action="store_true")
    a = p.parse_args()
    project = Path(a.project).resolve()
    try:
        if a.cmd == "save":
            cache.save(project, Path(a.out).resolve(), a.target, a.pin_file)
        elif a.cmd == "publish":
            cache.publish(project, Path(a.out).resolve(), a.repo)
        else:
            cache.restore(project, a.repo, build=a.build)
    except cache.CacheError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
