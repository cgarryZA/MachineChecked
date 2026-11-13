"""A correction of a printed clause can be reviewed and promoted (#639): reviewed against the
printed passage, its honest verdict is "faithful to the correction", offered only for a
correction or a special case, and the correction it claims is shown with the Lean. Nothing here
builds Lean."""

import json

import pytest

from prooflens import promote as pr
from prooflens import review_cli as rc
from test_compare import write_site

UNIT = "link:thm:t0"
WHO = "human:Correction-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."


def work_with(tmp_path, correction):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text())
    if correction:
        q["units"][0]["correction"] = correction
    (data / "review-queue.json").write_text(json.dumps(q))
    return data.parent.parent


def compared(work):
    s = rc.Session(work, rc.parse_reviewer(WHO))
    s.read(UNIT)
    s.lock(UNIT, READING)
    return s


def test_the_verdict_is_offered_only_for_a_correction(tmp_path):
    s = compared(work_with(tmp_path, None))
    s.show(UNIT)
    with pytest.raises(rc.ReviewError) as e:
        s.decide(UNIT, "faithful to the correction", "Item by item.")
    assert e.value.kind == "invalid" and "only to a correction" in str(e.value)


def test_a_correction_is_reviewed_against_the_passage_and_the_correction(tmp_path):
    s = compared(work_with(tmp_path, {"relation": "corrects", "of": "as printed",
                                      "reason": "adds that the coefficients are adapted"}))
    text = s.show(UNIT)
    assert "This proposition is a correction of the printed clause “as printed”" in text
    # The reason is the author's: shown with the author's review, not with the Lean.
    assert "adapted" not in text
    assert "reason" not in s.show(UNIT, as_json=True)["unit"]["correction"]
    s.decide(UNIT, "faithful to the correction", "The printed claim with the added hypothesis.")
    assert s.work["drafts"][UNIT]["verdict"] == "faithful to the correction"
    assert s.packet(s.unit(UNIT), "informed")["unit"]["correction"]["reason"] == \
        "adds that the coefficients are adapted"


def body_with(clause):
    return {"inventory": {"claims": [{"id": "T:thm:1", "clauses": [
        {"name": "as printed", "spec": "Toy.thm"}, clause]}]}}


def test_promotion_accepts_it_only_for_a_correcting_clause():
    u = {"kind": "spec", "name": "Toy.thm_fixed"}
    assert pr.corrects_a_clause(body_with({"name": "fixed", "spec": "Toy.thm_fixed",
                                           "corrects": "as printed"}), u)
    assert pr.corrects_a_clause(body_with({"name": "special", "spec": "Toy.thm_fixed",
                                           "restricts": "as printed"}), u)
    assert not pr.corrects_a_clause(body_with({"name": "other", "spec": "Toy.thm_fixed"}), u)
    assert not pr.corrects_a_clause(body_with({"name": "fixed", "spec": "Toy.thm_fixed",
                                               "corrects": "as printed"}),
                                    {"kind": "def", "name": "Toy.thm_fixed"})
    assert "faithful to the correction" in pr.ACCEPTABLE
