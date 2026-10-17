"""The review protocol from the command line (#51): each step refuses to run out of order, and
the exported report is one `review promote` accepts unchanged."""

import json

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr

UNIT = "def:Toy.triangle"
WHO = ["--as", "human:Test-Referee"]


def run(capsys, *args):
    cli.main(["review", *args, *WHO])
    return capsys.readouterr().out


def refused(capsys, *args):
    with pytest.raises(SystemExit) as e:
        cli.main(["review", *args, *WHO])
    assert e.value.code == 2
    return capsys.readouterr().err


@needs_lean
@needs_tex
def test_a_unit_from_the_queue_to_a_promotable_report(toy, tmp_path, monkeypatch, capsys):
    _, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    reading, comparison, none = (tmp_path / n for n in ("reading.md", "comparison.md", "none.md"))
    reading.write_text("T_n is the sum 0 + 1 + ... + n, defined for every natural number n.")
    comparison.write_text("The recursion adds n + 1 to T_n; T_0 = 0. It is the paper's sum.")
    none.write_text("none")

    assert run(capsys, "next").strip()
    # Nothing past step 1 before the reading is locked.
    assert "lock your reading first" in refused(capsys, "show", UNIT)
    assert "needs step 'compare'" in refused(capsys, "decide", UNIT, "faithful", str(comparison))
    step1 = run(capsys, "read", UNIT)
    assert "T:def:even" in step1 and "type :" not in step1 and "value:" not in step1
    run(capsys, "lock", UNIT, str(reading))
    assert "Toy.triangle" in run(capsys, "show", UNIT)
    assert "needs step 'author'" in refused(capsys, "author", UNIT)
    assert "needs --detail" in refused(capsys, "decide", UNIT, "broader", str(comparison))
    run(capsys, "decide", UNIT, "faithful", str(comparison))
    assert "read the author's review first" in refused(capsys, "submit", UNIT, str(none))
    run(capsys, "author", UNIT)
    run(capsys, "submit", UNIT, str(none))
    assert "1 report(s)" in run(capsys, "status")

    out = tmp_path / "reports.json"
    run(capsys, "export", "--out", str(out))
    reports = pr.load_reports([out])
    assert [r["unit"]["id"] for r in reports] == [UNIT]
    r = reports[0]
    assert r["reading"]["locked_at"] <= r["comparison"]["decided_at"] <= \
        r["author_review"]["shown_at"] <= r["submitted_at"]
    (_, _, why), = pr.plan(cfg, reports)
    assert not why, why


def test_a_reviewer_must_be_named(toy, monkeypatch, capsys):
    monkeypatch.chdir(toy)
    monkeypatch.delenv("MACHINECHECKED_REVIEWER", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "next"])
    assert e.value.code == 2 and "human:NAME or llm:MODEL" in capsys.readouterr().err
