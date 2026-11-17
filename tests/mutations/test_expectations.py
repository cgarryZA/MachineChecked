"""What an author expects of a clause (#650): a clause expected to be refuted has its missing
refutation as the open obligation, a proof of the other kind is flagged, and the expectation is
shown under the status. No status changes."""

import json

from conftest import build, findings, needs_lean, needs_tex, status


@needs_lean
@needs_tex
def test_an_expectation_names_the_obligation_and_a_contradicting_proof(toy):
    inv = json.loads((toy / "claims.json").read_text())
    by = {c["id"]: c for c in inv["claims"]}
    # A proved clause wrongly expected to be refuted, and an unproved one expected to be.
    by["T:thm:triangle"]["clauses"][0]["expect"] = "refute"
    by["T:cor:even-triangle"]["clauses"][0].update(expect="refute",
                                                   expect_reason="no witness exists for n = 0")
    (toy / "claims.json").write_text(json.dumps(inv))
    index, body, _ = build(toy)

    w = findings(body, "expectation-contradicted", "T:thm:triangle")
    assert w and w[0]["tier"] == "warning" and "proposition is proved" in w[0]["message"]
    o = findings(body, "expected-refutation", "T:cor:even-triangle")
    assert o and o[0]["tier"] == "obligation"
    c = next(c for c in body["assessment"]["claims"] if c["id"] == "T:cor:even-triangle")
    assert c["status_reason"] == [
        "“statement” is expected to be refuted: no witness exists for n = 0"]
    assert status(index, "T:cor:even-triangle") == "formal: open"
