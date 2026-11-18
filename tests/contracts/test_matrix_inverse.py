"""#621: Mathlib's inverse of a square matrix is the nonsingular inverse, `0` when the
determinant is not a unit (`Matrix.nonsing_inv_apply_not_isUnit`). The totalisation finding
states that value, and asks that the statement use only invertible matrices, instead of calling
it unresolved. An inverse whose type is still not read stays unresolved."""

from prooflens.assess import _division_warning, totalised_findings


def record(carrier, head):
    return {"name": "Toy.PaperSpec.t", "consts": ["Inv.inv"], "fingerprint": "pl-fp-v1:t",
            "order_ops": {"complete": True, "occurrences": [
                {"const": "Inv.inv", "carrier": carrier, "carrier_head": head,
                 "at": ["/1/0"]}]}}


def test_a_matrix_inverse_states_its_value():
    rec = record("Matrix (Fin 2) (Fin 2) Real", "Matrix")
    for lean in (True, False):
        message = _division_warning("Inv.inv", rec["name"], rec["order_ops"], lean)
        assert message.startswith("inverse of a square matrix: A⁻¹ = 0 when det A is not a unit;"
                                  " check that the statement uses only invertible matrices")
        assert "unresolved" not in message
    (item,) = totalised_findings(rec, rec["name"], {})
    assert (item["occurrence"]["state"], item["occurrence"]["rule"]) == (
        "applies", "inverse of a square matrix: A⁻¹ = 0 when det A is not a unit; check that "
                   "the statement uses only invertible matrices")


def test_an_inverse_of_another_type_is_still_unresolved():
    rec = record("Foo.Thing", "Foo.Thing")
    message = _division_warning("Inv.inv", rec["name"], rec["order_ops"])
    assert "so what 0⁻¹ gives is unresolved" in message
