"""#658: a clause proved from other propositions (`accept_from`). The theorem's type is exactly
the clause's proposition assuming them; the clause reads "proved assuming" (never proved or
accepted, and never passing the release gate) until each assumed proposition is the proposition
of a proved clause, and then reads proved. A cycle of such proofs is a violation."""

import json
import shutil
from types import SimpleNamespace

import pytest

from conftest import build, edit, findings, needs_lean
from prooflens import probe
from prooflens.assess import Assessor
from prooflens.reviews import Review
from prooflens.status import STATUSES


def proof(errors=()):
    return {"errors": list(errors), "sorry": False, "axioms": []}


def spec(name):
    return {"fingerprint": f"fp-{name}", "errors": [], "binders": [], "closure": [], "consts": []}


SPECS = ["S.lem1", "S.lem2", "S.lem3"]


def lean(proofs):
    return {"specs": {s: spec(s) for s in SPECS},
            "decls": {s: {"name": s, "fingerprint": f"fp-{s}", "uses": []} for s in SPECS},
            "proofs": proofs, "defs": {}, "layering": []}


def claim(cid, s, **clause):
    return {"id": f"P:{cid}", "paper": "P", "scope": "formal", "scope_reviewed": True,
            "clauses": [{"name": "main", "spec": s, **clause}]}


def assumes(thm, *names):
    return {"accept_from": {"theorem": thm, "assumes": list(names)}}


def key(thm, s, *names):
    return probe.proof_key("accept-from", thm, s, list(names))


REVIEWS = [Review("spec", s, f"fp-{s}", "reader", "human", "self-declared", "r.md", 1, "Read.")
           for s in SPECS]


def run(claims, proofs):
    cfg = SimpleNamespace(statement_authors=[], lean_root=None,
                          papers=[SimpleNamespace(id="P")])
    out = Assessor(cfg, {"claims": claims}, lean(proofs), {}, REVIEWS, []).run()
    return {c["id"]: c for c in out["claims"]}, out["findings"], out["gates"]["P"]


LEM1 = claim("lem1", "S.lem1")
LEM2 = claim("lem2", "S.lem2", **assumes("S.lem2_of_lem1", "S.lem1"))


def test_a_clause_proved_from_an_unproved_claim_reads_proved_assuming():
    claims, found, gate = run([LEM1, LEM2], {key("S.lem2_of_lem1", "S.lem2", "S.lem1"): proof()})
    lem2 = claims["P:lem2"]
    assert lem2["status_code"] == "formal.proved-assuming"
    assert STATUSES["formal.proved-assuming"]["class"] == "open"
    assert lem2["clauses"][0]["state"] == "proved-assuming"
    assert not lem2["clauses"][0].get("accept_ok")
    assert lem2["clauses"][0]["assumes"] == [
        {"spec": "S.lem1", "claims": ["P:lem1"], "proved": False}]
    assert lem2["status_reason"] == [
        "“main” is proved assuming S.lem1 (stated by P:lem1), not yet proved"]
    assert any("assuming results not yet proved: S.lem1" in b for b in lem2["blockers"])
    assert claims["P:lem1"]["status_code"] == "formal.open"
    assert not gate["release"]["pass"]
    assert "P:lem2: formal: proved assuming results not yet proved" in gate["release"]["reasons"]
    assert not [f for f in found if f["tier"] == "violation"]


def test_it_reads_proved_once_every_assumed_proposition_is_proved():
    lem1 = claim("lem1", "S.lem1", accept="S.lem1_proof")
    claims, found, _ = run([LEM2, lem1], {
        key("S.lem2_of_lem1", "S.lem2", "S.lem1"): proof(),
        "accept:S.lem1_proof:S.lem1": proof()})
    lem2 = claims["P:lem2"]
    assert lem2["clauses"][0]["state"] == "proved"
    assert lem2["status_code"] == "formal.accepted"
    assert lem2["status_reason"] == ["“main” is proved from S.lem1 (stated by P:lem1), each proved"]


def test_a_chain_resolves_and_a_failing_assumption_does_not():
    lem3 = claim("lem3", "S.lem3", **assumes("S.lem3_of_lem2", "S.lem2"))
    proofs = {key("S.lem2_of_lem1", "S.lem2", "S.lem1"): proof(),
              key("S.lem3_of_lem2", "S.lem3", "S.lem2"): proof(),
              "accept:S.lem1_proof:S.lem1": proof()}
    lem1 = claim("lem1", "S.lem1", accept="S.lem1_proof")
    claims, _, _ = run([lem3, LEM2, lem1], proofs)
    assert claims["P:lem3"]["clauses"][0]["state"] == "proved"
    # A proof of lem1 that fails a check (a disallowed axiom) proves nothing it is assumed by.
    proofs["accept:S.lem1_proof:S.lem1"] = proof(["axioms=[S.ax]"])
    claims, _, _ = run([lem3, LEM2, lem1], proofs)
    assert claims["P:lem2"]["status_code"] == "formal.proved-assuming"
    assert claims["P:lem3"]["status_code"] == "formal.proved-assuming"


def test_a_theorem_of_another_type_is_a_violation_and_proves_nothing():
    claims, found, _ = run([LEM1, LEM2], {
        key("S.lem2_of_lem1", "S.lem2", "S.lem1"): proof(["type-not-assuming-spec"])})
    assert claims["P:lem2"]["status_code"] == "formal.open"
    assert [f["code"] for f in found if f["tier"] == "violation"] == [
        "accept-from-type-not-assuming-spec"]
    assert any("its proof fails a check: type-not-assuming-spec" in b
               for b in claims["P:lem2"]["blockers"])


def test_a_cycle_is_a_violation():
    lem1 = claim("lem1", "S.lem1", **assumes("S.lem1_of_lem2", "S.lem2"))
    claims, found, _ = run([lem1, LEM2], {
        key("S.lem2_of_lem1", "S.lem2", "S.lem1"): proof(),
        key("S.lem1_of_lem2", "S.lem1", "S.lem2"): proof()})
    assert {c["status_code"] for c in claims.values()} == {"formal.proved-assuming"}
    cycles = [f for f in found if f["code"] == "accept-from-cycle"]
    assert [f["subject"] for f in cycles] == ["P:lem1#0", "P:lem2#0"]
    assert "S.lem1 → S.lem2 → S.lem1" in cycles[0]["message"]


def test_an_assumption_no_claim_states_is_named():
    lem2 = claim("lem2", "S.lem2", **assumes("S.lem2_of_bound", "S.Bound"))
    claims, _, _ = run([lem2], {key("S.lem2_of_bound", "S.lem2", "S.Bound"): proof()})
    assert claims["P:lem2"]["status_reason"] == [
        "“main” is proved assuming S.Bound (which no claim states), not yet proved"]


def test_the_probe_is_asked_for_the_proof_with_its_assumptions():
    reqs = probe.requests_from_inventory({"claims": [LEM2]})
    assert {"kind": "accept-from", "name": "S.lem2_of_lem1", "spec": "S.lem2",
            "assumes": ["S.lem1"]} in reqs


# The toy paper's Corollary 2.5 proved from Theorem 2.2, in the curried form and from a
# conjunction, and a theorem whose type assumes something else.
PROOFS = """
theorem cor_of_triangle : PaperSpec.thm_triangle → PaperSpec.cor_even_triangle := by
  intro h n
  have e := h (4 * n)
  have m : 4 * n * (4 * n + 1) = 4 * (n * (4 * n + 1)) := Nat.mul_assoc 4 n (4 * n + 1)
  exact ⟨n * (4 * n + 1), by omega⟩

theorem cor_of_both : PaperSpec.thm_even_add ∧ PaperSpec.thm_triangle →
    PaperSpec.cor_even_triangle := fun h => cor_of_triangle h.2

theorem cor_of_wrong : PaperSpec.thm_bound → PaperSpec.cor_even_triangle :=
  fun _ => cor_of_triangle thm_triangle

end Toy.Acceptance"""


def set_clause(root, cid, **fields):
    path = root / "claims.json"
    inv = json.loads(path.read_text(encoding="utf-8"))
    cl = next(c for c in inv["claims"] if c["id"] == cid)["clauses"][0]
    for k, v in fields.items():
        if v is None:
            cl.pop(k, None)
        else:
            cl[k] = v
    path.write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8")


@needs_lean
def test_the_probe_checks_the_type_and_the_status_follows_the_assumed_claim(toy):
    edit(toy / "lean" / "Toy" / "Acceptance.lean", "end Toy.Acceptance", PROOFS)
    cor = "T:cor:even-triangle"
    set_clause(toy, cor, accept_from={"theorem": "Toy.Acceptance.cor_of_triangle",
                                      "assumes": ["Toy.PaperSpec.thm_triangle"]})
    # Theorem 2.2 with its proof removed: the corollary is proved assuming it.
    set_clause(toy, "T:thm:triangle", accept=None)
    index, body, _ = build(toy)
    codes = {c["id"]: c["status_code"] for c in index["claims"]}
    assert codes[cor] == "formal.proved-assuming"
    assert not findings(body, subject=cor, code="accept-from-type-not-assuming-spec")
    assert not findings(body, subject=cor, code="accept-from-missing")
    # With its proof: the corollary is proved (its proposition has no review in the toy paper).
    set_clause(toy, "T:thm:triangle", accept="Toy.Acceptance.thm_triangle")
    index, body, _ = build(toy)
    row = next(c for c in index["claims"] if c["id"] == cor)
    assert row["status_code"] in ("formal.review-pending", "formal.author-reviewed",
                                  "formal.accepted")
    # From a conjunction of the assumed propositions, in order.
    set_clause(toy, cor, accept_from={"theorem": "Toy.Acceptance.cor_of_both",
                                      "assumes": ["Toy.PaperSpec.thm_even_add",
                                                  "Toy.PaperSpec.thm_triangle"]})
    index, body, _ = build(toy)
    assert next(c for c in index["claims"] if c["id"] == cor)["status_code"] == \
        row["status_code"]
    # In the other order, or assuming another proposition than the theorem does: not this type.
    for thm, names in (("cor_of_both", ["Toy.PaperSpec.thm_triangle",
                                        "Toy.PaperSpec.thm_even_add"]),
                       ("cor_of_wrong", ["Toy.PaperSpec.thm_triangle"])):
        set_clause(toy, cor, accept_from={"theorem": f"Toy.Acceptance.{thm}", "assumes": names})
        index, body, _ = build(toy)
        assert next(c for c in index["claims"] if c["id"] == cor)["status_code"] == "formal.open"
        assert findings(body, subject=cor, code="accept-from-type-not-assuming-spec")
