"""Step 2 lists the operations Lean totalises in a locked statement (#702): each operation, the
sub-term where it is applied and what Lean gives it outside its domain, as the assessment's
totalisation warnings read them from the Lean alone. What carries a judgement (a dismissal,
whether the hypotheses are found to supply the operation's conditions, the warning's state, the
other findings) waits for step 3. The site is the synthetic one of
`test_review_withholds_outcome.py`, on each of its surfaces; nothing here builds Lean."""

import json

import pytest

import test_review_withholds_outcome as wo
from prooflens import compare as cmp
from test_review_withholds_outcome import FIXED_UNIT, UNIT, step, surface  # noqa: F401

DISMISSAL = "AUTHOR-DISMISSAL: n is positive wherever 1 / n is taken."
WITNESS_NOTE = "WITNESS-WARNING: no witness shows the hypotheses can hold."
CONDITION = "MeasureTheory.Integrable X P"


def occurrence(op, rule, at, text, **more):
    return {"operation": op, "type": "ℝ", "type_head": "Real", "structure": "field",
            "state": "applies", "rule": rule, "at": [at],
            "subterms": [{"at": at, "text": text,
                          "within": {"id": 2, "name": "h1", "kind": "hypothesis"}}], **more}


def warning(k, op, message, spec, occ=None, **more):
    return {"tier": "warning", "code": "totalised" if op else "witness",
            "subject": f"S:prop:p#{k}", "message": f"{message} ({op} occurs in {spec})"
            if op else message, "trigger": op, "fingerprint": f"fp-{op}", "signal": "normal",
            **({"occurrences": [occ], "at": occ["at"][0], "statement_fingerprint": "fp"}
               if occ else {}),
            "id": f"{'totalised' if op else 'witness'}:S:prop:p#{k}:{op}", **more}


INTEGRAL = "the Bochner integral is 0 for a non-integrable function"
DIVISION = "division: x / 0 = 0 in Lean's fields and ℕ"
SQRT = "√x = 0 for x < 0"
FINDINGS = [
    # Resolved: the hypotheses supply the integral's condition.
    warning(0, "MeasureTheory.integral", INTEGRAL, wo.SPEC,
            occurrence("MeasureTheory.integral", INTEGRAL, "1.0", "∫ ω, X ω ∂P",
                       conditions=[{"condition": "integrable", "state": "established",
                                    "by": "hypothesis", "premise": "hX",
                                    "statement": CONDITION}],
                       condition_state="established"), resolved=True),
    # Dismissed by the author.
    warning(0, "HDiv.hDiv", DIVISION, wo.SPEC,
            occurrence("HDiv.hDiv", DIVISION, "1.1", "1 / n"),
            dismissed={"rationale": DISMISSAL, "by": "author"}, signal="low"),
    # One per operation: not read application by application.
    warning(1, "Real.sqrt", SQRT, wo.FIXED_SPEC),
    # Another kind of finding, which is not shown before the verdict.
    warning(1, None, WITNESS_NOTE, wo.FIXED_SPEC, dismissed={"rationale": DISMISSAL,
                                                             "by": "author"}),
]
# What steps 1 and 2 never show of these findings.
JUDGED = (DISMISSAL, WITNESS_NOTE, CONDITION, '"resolved"', '"dismissed"', '"conditions"',
          '"condition_state"', '"state": "established"', '"signal"')
# What step 2 shows of each unit, in JSON.
SHOWN = {UNIT: [{"operation": "MeasureTheory.integral",
                 "message": f"{INTEGRAL} (MeasureTheory.integral occurs in {wo.SPEC})",
                 "type": "ℝ", "at": ["1.0"],
                 "subterms": [{"at": "1.0", "text": "∫ ω, X ω ∂P",
                               "within": {"id": 2, "name": "h1", "kind": "hypothesis"}}]},
                {"operation": "HDiv.hDiv",
                 "message": f"{DIVISION} (HDiv.hDiv occurs in {wo.SPEC})", "type": "ℝ",
                 "at": ["1.1"],
                 "subterms": [{"at": "1.1", "text": "1 / n",
                               "within": {"id": 2, "name": "h1", "kind": "hypothesis"}}]}],
         FIXED_UNIT: [{"operation": "Real.sqrt",
                       "message": f"{SQRT} (Real.sqrt occurs in {wo.FIXED_SPEC})"}]}
LINES = {UNIT: [f"Operations Lean totalises in {wo.SPEC}, read from the Lean:",
                f"  MeasureTheory.integral at `∫ ω, X ω ∂P`: {INTEGRAL}",
                f"  HDiv.hDiv at `1 / n`: {DIVISION}"],
         FIXED_UNIT: [f"Operations Lean totalises in {wo.FIXED_SPEC}, read from the Lean:",
                      f"  Real.sqrt: {SQRT}"]}


def with_findings(tmp):
    data = ORIGINAL(tmp)
    f = data / "claims" / "S_prop_p.json"
    ch = json.loads(f.read_text())
    ch["findings"] = FINDINGS
    f.write_text(json.dumps(ch))
    return data


ORIGINAL = wo.write_spec_site


@pytest.fixture(autouse=True)
def findings(monkeypatch):
    """The synthetic site, with totalisation warnings on both locked statements."""
    monkeypatch.setattr(wo, "write_spec_site", with_findings)


def nothing_judged(text: str) -> None:
    for x in JUDGED:
        assert x not in text, f"{x!r} is shown before the verdict"


def test_step_2_lists_the_totalised_operations_and_nothing_judged_of_them(surface, capsys):
    texts, snap = surface
    for uid in (UNIT, FIXED_UNIT):
        for text in (step(capsys, "read", uid, "--json", *snap).out,
                     step(capsys, "read", uid, *snap).out):
            nothing_judged(text)
            assert "occurs in" not in text and "totalises" not in text
        step(capsys, "lock", uid, str(texts / "reading.md"), *snap)
        pk = json.loads(step(capsys, "show", uid, "--json", *snap).out)
        text = step(capsys, "show", uid, *snap).out
        nothing_judged(json.dumps(pk, ensure_ascii=False))
        nothing_judged(text)
        wo.withheld(json.dumps(pk, ensure_ascii=False))
        wo.withheld(text)
        (d,) = pk["lean"]["declarations"]
        assert d["totalised"] == SHOWN[uid]
        assert "\n".join(LINES[uid]) in text
        assert ("Whether the hypotheses exclude these cases is for your comparison; the "
                "assessment's judgement of them comes after your verdict.") in text
        step(capsys, "decide", uid, "faithful to the correction" if uid == FIXED_UNIT
             else "faithful", str(texts / "comparison.md"), *snap)
        # After the verdict, the assessment's findings with their dismissals.
        after = step(capsys, "author", uid, "--json", *snap).out
        assert DISMISSAL in after and json.loads(after)["lean"]["declarations"][0][
            "totalised"] == SHOWN[uid]


def test_a_claim_packet_before_the_verdict_lists_them_by_clause(tmp_path):
    site = cmp.Site(wo.write_spec_site(tmp_path))
    pk = cmp.claim_packet(site, "Proposition 1", "compare")
    nothing_judged(json.dumps(pk, ensure_ascii=False))
    nothing_judged(cmp.packet_text(pk))
    assert [d.get("totalised") for d in pk["lean"]["declarations"]] == [SHOWN[UNIT],
                                                                        SHOWN[FIXED_UNIT]]
    assert "lean" not in cmp.claim_packet(site, "Proposition 1", "read")


def test_a_statement_with_no_totalised_operation_lists_none(tmp_path, monkeypatch):
    monkeypatch.setattr(wo, "write_spec_site", ORIGINAL)
    site = cmp.Site(wo.write_spec_site(tmp_path))
    pk = cmp.claim_packet(site, "Proposition 1", "compare")
    assert all("totalised" not in d for d in pk["lean"]["declarations"])
    assert "totalises" not in cmp.packet_text(pk)
