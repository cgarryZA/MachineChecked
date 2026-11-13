"""A printed claim beside a proved correction or special case of it (#656, #684), and a
refutation whose counterexample lies outside the paper's standing assumptions (#653): each has a
status of its own, never "accepted" and never "refuted as printed", with the reason under the
label; the inventory's clause relations are checked."""

import pytest

from prooflens.assess import OUTSIDE, Assessor, status_reason
from prooflens.status import fields


def clause(name="main", state="open", review="reviewed", **extra):
    return {"name": name, "state": state, "review": review, "spec": f"Toy.{name}",
            "accept_ok": state == "proved", "refute_ok": state in ("refuted", "refuted-outside"),
            **extra}


def code(*clauses):
    return Assessor.claim_code({"scope": "formal"}, list(clauses))


@pytest.mark.parametrize("printed", ["open", "refuted-outside"])
@pytest.mark.parametrize("review,suffix", [("pending", ""), ("author-reviewed", ".author-reviewed"),
                                           ("reviewed", ".reviewed")])
def test_a_proved_correction_leaves_the_printed_claim_open(printed, review, suffix):
    c = code(clause(state=printed), clause("fixed", "proved", review, corrects="main"))
    assert c == "formal.open.corrected" + suffix
    f = fields(c)
    assert f["class"] == "open" and "accepted" not in f["status"]
    assert f["status"].startswith("formal: open as printed; corrected statement proved")


def test_a_special_case_says_the_printed_claim_is_not_refuted():
    c = code(clause(), clause("special", "proved", restricts="main"))
    assert c == "formal.open.restricted.reviewed"
    assert fields(c)["status"] == "formal: open as printed; special case proved and reviewed"
    from prooflens.status import STATUSES
    assert "not refuted" in STATUSES[c]["explanation"]


def test_a_refutation_outside_the_assumptions_is_not_refuted_as_printed():
    assert code(clause(state="refuted-outside")) == "formal.open"
    assert code(clause(state="refuted")) == "formal.refuted"
    # A correction of a clause refuted as printed reads as before.
    assert code(clause(state="refuted"), clause("fixed", "proved", corrects="main")) == \
        "formal.refuted.corrected"


def test_some_clauses_proved_is_told_apart_from_none():
    assert code(clause(), clause("other", "proved")) == "formal.open.partial"
    assert code(clause(), clause("other")) == "formal.open"
    # A correction of one open clause, while another original is open with nothing for it.
    assert code(clause(), clause("other"), clause("fixed", "proved", corrects="main")) == \
        "formal.open.partial"


def test_the_reason_under_the_label():
    why = status_reason([clause(state="refuted-outside", reason="the filtration is not complete"),
                         clause("fixed", "proved", corrects="main", reason="adds 0 < x")])
    assert why == [
        "“main” is refuted only by a counterexample outside the paper's standing assumptions: "
        "the filtration is not complete",
        "“fixed” corrects “main”: adds 0 < x", "1 of 2 clauses proved"]
    assert status_reason([clause("special", "proved", restricts="main"), clause()])[0] == \
        "“special” is a special case of “main”, which is not refuted"
    # Nothing to say for a claim whose label says it all.
    assert status_reason([clause(state="proved")]) == []
    assert status_reason([clause(state="refuted"), clause("fixed", "proved", corrects="main")]) \
        == []


def test_clause_relations_are_checked():
    a = Assessor.__new__(Assessor)
    a.findings = []
    a.clause_relation_checks({"id": "T:thm:1", "clauses": [
        {"name": "main", "refute": "Toy.no", "refute_scope": OUTSIDE},
        {"name": "both", "corrects": "main", "restricts": "main"},
        {"name": "lost", "restricts": "gone"},
        {"name": "scoped", "refute_scope": OUTSIDE},
        {"name": "odd", "refute": "Toy.no2", "refute_scope": "somewhere"}]})
    msgs = [f["message"] for f in a.findings]
    assert {f["code"] for f in a.findings} == {"clause-relation"} and len(msgs) == 4
    assert any("both corrects and restricts" in m for m in msgs)
    assert any("'gone', which is not an original clause" in m for m in msgs)
    assert any("scope but no refutation" in m for m in msgs)
    assert any("'somewhere' is not" in m for m in msgs)


@pytest.mark.parametrize("kind", ["added-hypothesis", "partial", "negation"])
def test_a_correction_kind_never_changes_the_status(kind):
    for printed in ("open", "refuted", "refuted-outside"):
        plain = code(clause(state=printed), clause("fixed", "proved", corrects="main"))
        assert code(clause(state=printed),
                    clause("fixed", "proved", corrects="main", kind=kind)) == plain


def test_a_correction_kind_is_shown_in_the_reason():
    why = status_reason([clause(state="refuted"),
                         clause("fixed", "proved", corrects="main", kind="negation")])
    assert len(why) == 1 and why[0].startswith("“fixed” corrects “main” with its true part and "
                                               "the negation of its false part")
    assert "for every instance" in why[0] and "not a narrowing" in why[0]
    assert status_reason([clause(), clause("fixed", "proved", corrects="main",
                                           kind="added-hypothesis", reason="adds 0 < x")])[0] == \
        "“fixed” corrects “main” with an added hypothesis: adds 0 < x"
    # An unproved correction says nothing.
    assert status_reason([clause(), clause("fixed", corrects="main", kind="partial")]) == []


def test_a_correction_kind_is_checked():
    a = Assessor.__new__(Assessor)
    a.findings = []
    a.clause_relation_checks({"id": "T:thm:1", "clauses": [
        {"name": "main"},
        {"name": "ok", "corrects": "main", "kind": "negation"},
        {"name": "alone", "kind": "partial"},
        {"name": "odd", "corrects": "main", "kind": "weaker"}]})
    msgs = [f["message"] for f in a.findings]
    assert len(msgs) == 2
    assert any("'alone' gives a correction's kind but corrects no clause" in m for m in msgs)
    assert any("kind 'weaker' is not one of" in m for m in msgs)


def test_a_refuted_variant_is_not_refuted_as_printed():
    """#655: the clause refuted is a second printing; the clause "as printed" is open."""
    c = code(clause("as printed"), clause("second edition", "refuted"))
    assert c == "formal.variant-refuted.open"
    assert fields(c)["status"] == "a printed variant refuted; other clauses open"
    assert status_reason([clause("as printed"), clause("second edition", "refuted")]) == [
        "“second edition” refuted; “as printed” open"]
    # Without a clause named "as printed", the first original states the claim as printed.
    assert code(clause("first", "refuted"), clause("second")) == "formal.refuted.open"


def test_a_clause_says_what_it_is_expected_to_be():
    """#650: an expectation is shown under the status until a proof settles it."""
    why = status_reason([clause(expect="refute", expect_reason="C cannot be uniform in W"),
                         clause("other", expect="undecided")])
    assert why == ["“main” is expected to be refuted: C cannot be uniform in W",
                   "“other”: whether it holds is undecided"]
    assert status_reason([clause(state="refuted", expect="refute")]) == []
    a = Assessor.__new__(Assessor)
    a.findings = []
    a.clause_relation_checks({"id": "T:thm:1", "clauses": [{"name": "main", "expect": "maybe"}]})
    assert [f["code"] for f in a.findings] == ["clause-relation"]
