"""After the verdict, a review says when the proposition just judged is refuted by a clause of its
claim (#685): `review author` (text and JSON) and the exported report name the theorem the author
gives as proving its negation, and say what that means for the proposition, in one line; the
report's text block too. Before the verdict nothing of it is shown
(`test_review_withholds_outcome.py`). The site is that test's synthetic full assessment; nothing
here builds Lean."""

import json

import pytest

from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from test_review_withholds_outcome import (FIXED_UNIT, REFUTE, TEXTS, UNIT, WHO, withheld,
                                           write_spec_site)

LINE = (f"This proposition is refuted by {REFUTE}: Lean checks that it proves the negation, so "
        "no proof of the proposition can follow.")


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_spec_site(tmp_path)
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    for name, text in TEXTS.items():
        (tmp_path / name).write_text(text)
    return work


def step(capsys, *args):
    cli.main(["review", *args, *WHO])
    return capsys.readouterr().out


def test_the_author_s_step_and_the_report_say_the_proposition_is_refuted(work, tmp_path,
                                                                        capsys):
    step(capsys, "read", UNIT)
    step(capsys, "lock", UNIT, str(tmp_path / "reading.md"))
    before = step(capsys, "show", UNIT) + step(capsys, "show", UNIT, "--json")
    withheld(before)
    assert "is refuted by" not in before
    step(capsys, "decide", UNIT, "faithful", str(tmp_path / "comparison.md"))
    text = step(capsys, "author", UNIT)
    assert text.rstrip().endswith(LINE)
    pk = json.loads(step(capsys, "author", UNIT, "--json"))
    assert pk["interpretations"]["refuted_by"] == [
        {"claim": "S:prop:p", "clause": 1, "theorem": REFUTE, "checked": True, "line": LINE}]
    step(capsys, "submit", UNIT, str(tmp_path / "none.md"))
    (r,) = rc.Session(work, rc.parse_reviewer(WHO[1])).work["reports"]
    assert r["verdict"]["value"] == "faithful"
    assert r["refuted_by"] == pk["interpretations"]["refuted_by"]
    assert f"Refuted: {LINE}" in pr.report_text(r)


def test_a_proposition_no_clause_refutes_says_nothing_of_it(work, tmp_path, capsys):
    step(capsys, "read", FIXED_UNIT)
    step(capsys, "lock", FIXED_UNIT, str(tmp_path / "reading.md"))
    step(capsys, "show", FIXED_UNIT)
    step(capsys, "decide", FIXED_UNIT, "faithful to the correction",
         str(tmp_path / "comparison.md"))
    assert "is refuted by" not in step(capsys, "author", FIXED_UNIT)
    assert json.loads(step(capsys, "author", FIXED_UNIT, "--json"))["interpretations"][
        "refuted_by"] == []
    step(capsys, "submit", FIXED_UNIT, str(tmp_path / "none.md"))
    (r,) = rc.Session(work, rc.parse_reviewer(WHO[1])).work["reports"]
    assert "refuted_by" not in r and "Refuted:" not in pr.report_text(r)


def test_a_refutation_lean_does_not_check_is_named_as_the_author_s_only():
    clause = {"name": "as printed", "spec": "S.p", "refute": "S.p_false",
              "checks": {"refute": {"ok": False, "errors": ["type mismatch"]}}}
    r = rq.refutation_of("S:prop:p", clause, [clause])
    assert r == {"claim": "S:prop:p", "clause": 1, "theorem": "S.p_false", "checked": False,
                 "errors": ["type mismatch"], "line": (
                     "The author names S.p_false as refuting this proposition, and Lean does not "
                     "check it (type mismatch).")}
