"""CI's test shards (tests/shards.py): disjoint parts whose union is the suite."""

from __future__ import annotations

import subprocess
import sys

import shards
from conftest import ROOT


def test_whole_files_are_dealt_longest_first_to_the_least_loaded_part():
    counts = {"a.py": 3, "b.py": 1, "c.py": 2, "d.py": 5}
    times = {"a.py": 100.0, "b.py": 60.0, "c.py": 50.0}
    # d.py is not listed: its 5 tests count at the listed files' mean, 210 s / 6 tests.
    assert shards.split(counts, times, 2) == [(["d.py"], 175.0), (["a.py", "b.py", "c.py"], 210.0)]
    assert shards.split(counts, {}, 3) == [(["d.py"], 5.0), (["a.py"], 3.0), (["c.py", "b.py"], 3.0)]


def test_file_times_are_fitted_across_runners_of_different_speeds():
    # Two runs of two shards each; the first and last runners are twice as slow as the others.
    reports = [{"a.py": 20.0, "b.py": 40.0}, {"c.py": 30.0}, {"a.py": 10.0}, {"b.py": 40.0, "c.py": 60.0}]
    fitted = shards.fit(reports)
    assert {f: round(t, 6) for f, t in fitted.items()} == {"a.py": 15.0, "b.py": 30.0, "c.py": 45.0}
    # One run: each file keeps its time.
    assert shards.fit(reports[:2]) == {"a.py": 20.0, "b.py": 40.0, "c.py": 30.0}


def collected(*args: str) -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                          *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if "::" in line]


def test_the_shards_of_the_suite_hold_each_of_its_tests_once():
    whole = collected()
    parts = [collected("--shard", f"{i}/4") for i in range(1, 5)]
    assert all(parts)
    assert sorted(t for part in parts for t in part) == sorted(whole)
