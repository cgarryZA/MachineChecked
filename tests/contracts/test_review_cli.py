"""The review protocol from the command line (#51): each step refuses to run out of order, and
the exported report is one `review promote` accepts unchanged."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr
from prooflens.review_cli import correspondence, issue_draft, report

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
    # The coverage is recorded with the verdict, and agrees with it.
    assert "does not agree with the verdict 'faithful'" in refused(
        capsys, "decide", UNIT, "faithful", str(comparison), "--coverage", "unresolved")
    run(capsys, "decide", UNIT, "faithful", str(comparison), "--coverage", "full",
        "--basis", "direct")
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
    assert r["correspondence"] == {"coverage": "full", "basis": "direct"}
    (_, _, why), = pr.plan(cfg, reports)
    assert not why, why


@needs_lean
@needs_tex
def test_a_review_after_importing_an_informed_investigation_is_not_blind(toy, tmp_path,
                                                                         monkeypatch, capsys):
    """#252: an informed investigation made in another copy of the project and imported here is
    what its reviewer had seen. Their report lists it and `review promote` refuses it without
    --allow-revealed; another reviewer's report of the same unit is blind."""
    _, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    saved = tmp_path / "work.json"
    cli.main(["workspace", "open", "--mode", "informed", *WHO])
    cli.main(["workspace", "export", "--out", str(saved), *WHO])
    shutil.rmtree(cfg.out_dir / "review-work")
    cli.main(["workspace", "import", str(saved), *WHO])
    wid = json.loads(saved.read_text())["id"]
    reading, comparison, none = (tmp_path / n for n in ("reading.md", "comparison.md", "none.md"))
    reading.write_text("T_n is the sum 0 + 1 + ... + n, defined for every natural number n.")
    comparison.write_text("The recursion adds n + 1 to T_n; T_0 = 0. It is the paper's sum.")
    none.write_text("none")
    capsys.readouterr()
    reports = {}
    for who in (WHO, ["--as", "human:Other-Referee"]):
        def step(*args):
            cli.main(["review", *args, *who])
            return capsys.readouterr().out
        seen = "will not be blind" in step("read", UNIT)
        assert seen == (who == WHO)
        step("lock", UNIT, str(reading))
        step("show", UNIT)
        step("decide", UNIT, "faithful", str(comparison))
        step("author", UNIT)
        step("submit", UNIT, str(none))
        out = tmp_path / f"reports-{len(reports)}.json"
        step("export", "--out", str(out))
        reports[who[1]], = pr.load_reports([out])
    mine, theirs = reports[WHO[1]], reports["human:Other-Referee"]
    assert {(s["unit"], s["what"]) for s in mine["reading"]["revealed_by"]} == {
        (f"workspace {wid} (informed investigation)", "Lean"),
        (f"workspace {wid} (informed investigation)", "author's review")}
    assert theirs["reading"]["revealed_by"] == []
    (_, _, why), = pr.plan(cfg, [mine])
    assert any("not blind" in w for w in why), why
    (_, _, why), = pr.plan(cfg, [mine], allow_revealed=True)
    assert not why, why
    (_, _, why), = pr.plan(cfg, [theirs])
    assert not why, why


def test_a_reviewer_must_be_named(toy, monkeypatch, capsys):
    monkeypatch.chdir(toy)
    monkeypatch.delenv("MACHINECHECKED_REVIEWER", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "next"])
    assert e.value.code == 2 and "human:NAME or llm:MODEL" in capsys.readouterr().err


DRAFTS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "review"
                     / "issue-drafts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", DRAFTS["cases"], ids=lambda c: c["verdict"])
def test_issue_drafts_are_those_the_reader_writes(case):
    """The command line writes the drafts of tests/fixtures/review/issue-drafts.json, which
    web/tests/review.test.mjs checks the reader writes too."""
    assert issue_draft(DRAFTS["unit"], case["verdict"], case["detail"]) == case["draft"]


COVER = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "review"
                    / "report-coverage.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", COVER["cases"], ids=lambda c: c["name"])
def test_a_report_records_coverage_as_the_reader_does(case):
    """The command line records, or refuses, the coverage of
    tests/fixtures/review/report-coverage.json as web/tests/review.test.mjs checks the reader
    does: the coverage agrees with the verdict, and the basis is recorded separately."""
    cor, why = correspondence(COVER["units"][case["unit"]], case["verdict"], case["given"])
    assert bool(why) == bool(case.get("refused")), why
    if not case.get("refused"):
        assert cor == case["correspondence"]


def test_a_report_without_coverage_promotes_as_before_and_unresolved_never_does():
    """An older report has no coverage: nothing about it changes, and nothing is guessed from its
    verdict. A report whose coverage is unresolved is refused as an open question, whatever its
    verdict, and never as a defect."""
    unit = {"id": "spec:A.b", "kind": "spec", "name": "A.b", "lean": ["A.b"], "claims": []}
    old = {"unit": unit, "verdict": {"group": "cannot", "value": "cannot determine"}}
    assert pr.coverage_refusals(old) == [] and pr.coverage_text(old) is None
    assert pr.coverage_refusals({**old, "correspondence": None}) == []
    odd = {"unit": unit, "verdict": {"group": "matches", "value": "faithful"},
           "correspondence": {"coverage": "unresolved"}}
    why = pr.coverage_refusals(odd)
    assert any("does not agree with the verdict" in w for w in why)
    assert any("unresolved: an open question records no review, and no defect" in w for w in why)
    assert not any("defect" in w and "no defect" not in w for w in why)
    assert pr.coverage_refusals({**odd, "correspondence": "full"}) == [
        "the report's coverage is not a record the review protocol writes"]
    ok = {**odd, "correspondence": {"coverage": "full", "basis": "reviewed_composition",
                                    "argument": "Chain the two bounds."}}
    assert pr.coverage_refusals(ok) == []
    assert pr.coverage_text(ok) == "every clause, by an argument combining Lean results"
    from prooflens.promote import report_text
    r = {**ok, "unit": {**unit, "claims": ["T:x"]}, "pins": {"fingerprint": "f"},
         "reviewer": {"id": "human:A", "kind": "human"}, "submitted_at": "t",
         "reading": {"text": "r", "locked_at": "t"},
         "comparison": {"text": "c", "decided_at": "t"},
         "verdict": {"value": "faithful", "detail": ""},
         "author_review": {"shown_at": "t", "disagreements": "none"}}
    text = report_text(r, {"legacy_hash": "0" * 32})
    assert ("Coverage (recorded with the verdict): every clause, by an argument combining Lean "
            "results") in text and "Argument: Chain the two bounds." in text
    assert "Coverage" not in report_text({k: v for k, v in r.items() if k != "correspondence"},
                                         {"legacy_hash": "0" * 32})


def test_an_open_question_s_draft_says_what_would_decide_it():
    unit = {**DRAFTS["unit"], "kind": "statement"}
    d = issue_draft(unit, "cannot determine", "Is n allowed to be 0?",
                    {"coverage": "unresolved", "would_decide": "The paper's Section 1."})
    assert d["kind"] == "unresolved question"
    assert d["body"].endswith("\n\n**Would decide it.** The paper's Section 1.")


def test_cannot_determine_is_an_open_question_not_a_defect():
    """A reviewer who cannot decide leaves an open question: the report's issue draft says so,
    keeps the question, and never calls it a defect."""
    unit = {**DRAFTS["unit"], "kind": "statement"}
    draft = {"reading": "r" * 20, "locked_at": "2026-01-01T00:00:00Z", "comparison": "c",
             "decided_at": "2026-01-01T00:01:00Z", "group": "cannot",
             "verdict": "cannot determine", "detail": "Is n allowed to be 0?",
             "author_shown_at": "2026-01-01T00:02:00Z"}
    r = report({"release": "v1", "papers": []}, unit, draft, {"id": "human:A"}, "none")
    d = r["issue_draft"]
    assert d["kind"] == "unresolved question"
    assert "defect" not in json.dumps(d) and "Is n allowed to be 0?" in d["body"]
    assert r["verdict"] == {"group": "cannot", "value": "cannot determine",
                            "detail": "Is n allowed to be 0?"}
    # No coverage was recorded, and none is read from the verdict.
    assert r["correspondence"] is None
