"""CI's test shards: `pytest --shard I/N` runs the I-th of N disjoint parts of the collected tests.

Whole test files are dealt out, longest first, each to the part with the least expected time so
far, so that a file's module-scoped fixtures are built in one part only. A file's expected time is
its measured time in `durations.json`; a file that `durations.json` does not list is counted at
the mean time per test of the files it lists. The split depends only on the collected tests and
that file, so every shard computes the same split, and each collected test is in exactly one part.

`--shard-times PATH` writes the time each test file took (setup, call and teardown) to PATH as
JSON. Run this module on every shard's file from one CI run to rewrite `durations.json`:

    gh run download RUN_ID -p 'test-times-*'
    python tests/shards.py test-times-*/test-times.json
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import pytest

DURATIONS = Path(__file__).with_name("durations.json")


def file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def parse(spec: str) -> tuple[int, int]:
    """`I/N` as (I, N), with 1 <= I <= N."""
    try:
        i, n = (int(x) for x in spec.split("/"))
    except ValueError:
        raise pytest.UsageError(f"--shard takes I/N, such as 1/4, not {spec!r}") from None
    if not 1 <= i <= n:
        raise pytest.UsageError(f"--shard {spec}: I must be between 1 and N")
    return i, n


def split(counts: dict[str, int], times: dict[str, float], n: int) -> list[tuple[list[str], float]]:
    """Deal the files (with their numbers of tests) into n parts; each part's files and their
    expected seconds."""
    known = [f for f in counts if f in times]
    tests = sum(counts[f] for f in known)
    per_test = sum(times[f] for f in known) / tests if tests else 1.0
    cost = {f: times[f] if f in times else per_test * counts[f] for f in counts}
    parts: list[tuple[list[str], float]] = [([], 0.0) for _ in range(n)]
    for f in sorted(counts, key=lambda f: (-cost[f], f)):
        k = min(range(n), key=lambda k: (parts[k][1], k))
        parts[k] = (parts[k][0] + [f], parts[k][1] + cost[f])
    return parts


class Shards:
    """The pytest plugin behind `--shard` and `--shard-times`."""

    def __init__(self, config):
        self.spec = config.getoption("shard")
        if self.spec:
            parse(self.spec)
        self.out = config.getoption("shard_times")
        self.times: dict[str, float] = defaultdict(float)
        self.summary = ""
        self.start = time.monotonic()

    def pytest_collection_modifyitems(self, config, items):
        if not self.spec:
            return
        i, n = parse(self.spec)
        times = json.loads(DURATIONS.read_text()) if DURATIONS.exists() else {}
        files, expected = split(Counter(file_of(it.nodeid) for it in items), times, n)[i - 1]
        mine = set(files)
        keep = [it for it in items if file_of(it.nodeid) in mine]
        drop = [it for it in items if file_of(it.nodeid) not in mine]
        if drop:
            config.hook.pytest_deselected(items=drop)
        items[:] = keep
        self.summary = (f"shard {i}/{n}: {len(keep)} of {len(keep) + len(drop)} tests in "
                        f"{len(files)} files, expected {expected / 60:.1f} min")

    def pytest_runtest_logreport(self, report):
        self.times[file_of(report.nodeid)] += report.duration

    def pytest_sessionfinish(self, session):
        if self.out:
            Path(self.out).write_text(json.dumps(
                {f: round(t, 1) for f, t in sorted(self.times.items())}, indent=1) + "\n")

    def pytest_terminal_summary(self, terminalreporter):
        if self.summary:
            terminalreporter.write_line(
                f"{self.summary}, took {(time.monotonic() - self.start) / 60:.1f} min")


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    merged: dict[str, float] = {}
    for p in paths:
        for f, t in json.loads(Path(p).read_text()).items():
            if f in merged:
                raise SystemExit(f"{f} is in two of the files given: pass one CI run's shards")
            merged[f] = t
    DURATIONS.write_text(json.dumps(dict(sorted(merged.items())), indent=1) + "\n")
    print(f"wrote {DURATIONS} ({len(merged)} files, {sum(merged.values()) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
