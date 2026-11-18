"""#762: "formal: open" says a proposition is written and a proof is missing. A formal claim none
of whose clauses names a proposition (each has `spec: null`, or names definitions only) has none,
so it reads "formal: unspecified", as a claim with no clauses does; a claim with at least one
clause that names a proposition reads as before."""

from types import SimpleNamespace

import pytest

from prooflens.assess import Assessor
from prooflens.probe import proof_key
from prooflens.status import fields


def clause(name="main", spec="Toy.main", state=None, **extra):
    state = state or ("open" if spec else "unspecified")
    return {"name": name, "spec": spec, "state": state, "review": "pending",
            "accept_ok": state == "proved", "refute_ok": state == "refuted", **extra}


def code(*clauses):
    return Assessor.claim_code({"scope": "formal"}, list(clauses))


@pytest.mark.parametrize("clauses", [
    [clause(spec=None)],
    [clause("first", None), clause("second", None)],
    [clause(spec=None, state="stated", defs=["Toy.D"])],
    [clause("first", None), clause("second", None, state="stated", defs=["Toy.D"])],
])
def test_no_clause_names_a_proposition(clauses):
    assert code(*clauses) == "formal.unspecified" == code()
    assert fields(code(*clauses))["class"] == "unspecified"


def test_a_claim_with_a_proposition_reads_as_before():
    assert code(clause()) == "formal.open"
    assert code(clause(), clause("other", None)) == "formal.open"
    assert code(clause(state="proved"), clause("other", None)) == "formal.open.partial"
    assert code(clause(state="proved")) == "formal.review-pending"
    # A printed clause with no proposition beside a proved correction of it that names one.
    assert code(clause(spec=None), clause("fixed", "Toy.fixed", "proved", corrects="main")) == \
        "formal.open.corrected"
    # Corrections without an original clause are malformed, with or without a proposition.
    assert code(clause("fixed", None, corrects="main")) == "formal.malformed"


LEAN = {"specs": {"S.a": {"fingerprint": "fp-S.a", "errors": [], "binders": [], "closure": [],
                          "consts": []}},
        "decls": {n: {"name": n, "fingerprint": f"fp-{n}", "uses": []} for n in ("S.a", "D.x")},
        "proofs": {proof_key("accept", "S.a_proof", "S.a"): {"errors": [], "sorry": False,
                                                              "axioms": []}},
        "defs": {"D.x": {"closure": []}}, "layering": []}


def claim(cid, *clauses):
    return {"id": f"P:{cid}", "paper": "P", "kind": "theorem", "scope": "formal",
            "scope_reviewed": True, "clauses": list(clauses)}


def test_the_assessment_reads_it_unspecified_and_says_why():
    claims = [claim("none", {"name": "statement", "spec": None}),
              claim("two", {"name": "a", "spec": None}, {"name": "b"}),
              claim("defs", {"name": "statement", "spec": None, "defs": ["D.x"]}),
              claim("open", {"name": "statement", "spec": "S.a"}),
              claim("mixed", {"name": "statement", "spec": "S.a", "accept": "S.a_proof"},
                    {"name": "b", "spec": None})]
    cfg = SimpleNamespace(statement_authors=[], lean_root=None,
                          papers=[SimpleNamespace(id="P")])
    got = {c["id"]: c for c in Assessor(cfg, {"claims": claims}, LEAN, {}, [], []).run()["claims"]}
    assert {cid: c["status_code"] for cid, c in got.items()} == {
        "P:none": "formal.unspecified", "P:two": "formal.unspecified",
        "P:defs": "formal.unspecified", "P:open": "formal.open", "P:mixed": "formal.open.partial"}
    assert got["P:none"]["status"] == "formal: unspecified"
    # Its reasons name the missing proposition, also for a clause that names definitions only.
    assert got["P:none"]["blockers"][0] == "no Lean proposition has been written"
    assert got["P:two"]["blockers"][0] == "no Lean proposition has been written (all 2 clauses)"
    assert got["P:defs"]["blockers"][0] == "no Lean proposition has been written"
