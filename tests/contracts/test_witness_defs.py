"""#191: the project declarations in the closure of a witness's statement that no proposition's
closure includes are listed, while they lack a current review, as advice that changes no status;
`require_witness_def_reviews` makes their reviews required, which can only lower a status. A
definition claim lists the witness-only declarations that use a definition it maps. A
declaration whose type is a proposition is a proof: it carries no data, so it cannot fix the
instance a witness exhibits, and it is not listed (#243)."""

import copy
import subprocess
from types import SimpleNamespace

import pytest

from conftest import needs_lean
from prooflens import probe
from prooflens.assess import Assessor
from prooflens.reviews import Review


def decl(name, uses=(), fp=None):
    return {"name": name, "fingerprint": fp or f"fp-{name}", "uses": list(uses)}


# A synthetic statement "for every positive rate r, decay r n ≤ 1", its proof, and a witness
# whose instance is the abbreviation `S.paperModel`, used by no proposition.
LEAN = {
    "specs": {"S.rate_bound": {"fingerprint": "fp-spec", "errors": [], "binders": [
        {"role": "hypothesis", "name": "h", "type": {"text": "0 < r"}}],
        "closure": ["S.decay"], "consts": []}},
    "proofs": {
        "accept:S.rate_bound_proof:S.rate_bound": {"errors": [], "sorry": False, "axioms": []},
        "witness:S.rate_bound_hypotheses:": {"errors": [], "sorry": False, "axioms": [],
                                             "closure": ["S.Model", "S.Model.r", "S.decay",
                                                         "S.paperModel"]}},
    "decls": {n: decl(n, u) for n, u in (
        ("S.decay", ()), ("S.Model", ()), ("S.Model.r", ("S.Model",)),
        ("S.paperModel", ("S.Model",)), ("S.rate_bound", ("S.decay",)))},
    "defs": {"S.Model": {"closure": []}},
    "layering": []}

FORMAL = {"id": "P:rate", "paper": "P", "scope": "formal", "scope_reviewed": True,
          "clauses": [{"name": "main", "spec": "S.rate_bound", "accept": "S.rate_bound_proof",
                       "witness": "S.rate_bound_hypotheses"}]}
MODEL = {"id": "P:model", "paper": "P", "scope": "definition", "scope_reviewed": True,
         "clauses": [{"name": "main", "defs": ["S.Model"]}]}


def review(target, name, h):
    return Review(target, name, h, "reader", "human", "self-declared", "r.md", 1, "Read.")


REVIEWED = [review("spec", "S.rate_bound", "fp-spec"), review("def", "S.decay", "fp-S.decay"),
            review("def", "S.Model", "fp-S.Model")]


def run(reviews=REVIEWED, claims=(FORMAL, MODEL), dismissals=(), lean=LEAN, **cfg):
    config = SimpleNamespace(statement_authors=[], papers=[], lean_root=None, **cfg)
    out = Assessor(config, {"claims": list(claims)}, lean, {}, list(reviews),
                   list(dismissals)).run()
    return {c["id"]: c for c in out["claims"]}, out["findings"]


def test_unreviewed_witness_only_declarations_are_listed_as_advice():
    claims, findings = run()
    rate = claims["P:rate"]
    assert rate["status_code"] == "formal.accepted"
    # S.decay is in the proposition's closure, S.Model is a definition claim's: neither is listed.
    assert rate["clauses"][0]["witness_defs"] == [
        {"name": "S.Model.r", "witnesses": ["S.rate_bound_hypotheses"], "state": "pending"},
        {"name": "S.paperModel", "witnesses": ["S.rate_bound_hypotheses"], "state": "pending"}]
    found = [f for f in findings if f["code"] == "witness-def-review"]
    assert [(f["tier"], f["subject"], f["trigger"]) for f in found] == [
        ("warning", "P:rate#0", "S.rate_bound_hypotheses")] * 2
    assert "S.paperModel, which is in no proposition's definitions and has no review" in \
        found[1]["message"]
    # A current review takes a declaration off the list.
    claims, _ = run(REVIEWED + [review("def", "S.paperModel", "fp-S.paperModel")])
    assert [e["name"] for e in claims["P:rate"]["clauses"][0]["witness_defs"]] == ["S.Model.r"]
    # A review of an earlier version is listed as out of date.
    claims, findings = run(REVIEWED + [review("def", "S.paperModel", "old")])
    assert claims["P:rate"]["clauses"][0]["witness_defs"][1]["state"] == "stale"


def test_the_advice_can_be_dismissed_until_the_declaration_changes():
    d = {"code": "witness-def-review", "subject": "S.paperModel",
         "trigger": "S.rate_bound_hypotheses", "fingerprint": "fp-S.paperModel",
         "rationale": "the paper's instance", "by": "reader"}
    _, findings = run(dismissals=[d])
    (f,) = [f for f in findings if f["code"] == "witness-def-review"
            and "S.paperModel" in f["message"]]
    assert f["dismissed"]["rationale"] == "the paper's instance"
    _, findings = run(dismissals=[{**d, "fingerprint": "older"}])
    (f,) = [f for f in findings if f["code"] == "witness-def-review"
            and "S.paperModel" in f["message"]]
    assert f.get("dismissal_stale") and "dismissed" not in f


def test_the_option_requires_their_reviews_and_only_lowers_a_status():
    claims, findings = run(require_witness_def_reviews=True)
    rate = claims["P:rate"]
    assert rate["status_code"] == "formal.review-pending"
    assert rate["clauses"][0]["witness_defs"] == []
    assert not [f for f in findings if f["code"] == "witness-def-review"]
    pending = sorted(f["trigger"] for f in findings if f["code"] == "def-review")
    assert pending == ["S.Model.r", "S.paperModel"]
    every = REVIEWED + [review("def", "S.paperModel", "fp-S.paperModel"),
                        review("def", "S.Model.r", "fp-S.Model.r")]
    assert run(every, require_witness_def_reviews=True)[0]["P:rate"]["status_code"] == \
        "formal.accepted"
    # Without the option, no review of a witness-only declaration changes a status.
    for reviews in (REVIEWED, every):
        assert run(reviews)[0]["P:rate"]["status_code"] == "formal.accepted"


def with_decls(kinds: dict[str, tuple[str, object]]) -> dict:
    """LEAN with more declarations in the witness's closure, each with the probe's `kind` and
    `proposition` (left out for `"absent"`, as in a record of an earlier probe)."""
    lean = copy.deepcopy(LEAN)
    lean["proofs"]["witness:S.rate_bound_hypotheses:"]["closure"] += list(kinds)
    for n, (kind, prop) in kinds.items():
        lean["decls"][n] = {**decl(n), "kind": kind,
                            **({} if prop == "absent" else {"proposition": prop})}
    return lean


# The witness's closure for the instance `S.paperModel` of a structure with a proof field: the
# auxiliary proof Lean generates for that field, a theorem about the instance, a `Prop`-valued
# instance (`Fact (2 ≠ 0)`) and the constructor of that `Prop` class are proofs. A definition
# whose value is a structure instance with a data field, and the class (a predicate), are not.
PROOFS = {"S.paperModel._proof_1": ("theorem", True), "S.paperModel_r": ("theorem", True),
          "S.instFactTwoNeZero": ("def", True), "S.Fact.mk": ("ctor", True)}
DATA = {"S.halfModel": ("def", False), "S.Fact": ("inductive", False)}


def test_proofs_in_a_witness_closure_are_not_listed():
    lean = with_decls({**PROOFS, **DATA})
    claims, findings = run(lean=lean)
    listed = [e["name"] for e in claims["P:rate"]["clauses"][0]["witness_defs"]]
    assert listed == ["S.Fact", "S.Model.r", "S.halfModel", "S.paperModel"]
    warned = [f for f in findings if f["code"] == "witness-def-review"]
    assert len(warned) == 4 and not any(p in f["message"] for p in PROOFS for f in warned)
    assert claims["P:rate"]["status_code"] == "formal.accepted"
    # Required by the configuration, only the declarations that carry data need a review.
    claims, findings = run(lean=lean, require_witness_def_reviews=True)
    assert sorted(f["trigger"] for f in findings if f["code"] == "def-review") == listed
    every = REVIEWED + [review("def", n, f"fp-{n}") for n in listed]
    assert run(every, lean=lean, require_witness_def_reviews=True)[0]["P:rate"][
        "status_code"] == "formal.accepted"
    # A proof that uses a definition claim's definition is no candidate for its mapping.
    lean["decls"]["S.paperModel_r"]["uses"] = ["S.Model"]
    candidates = run(lean=lean)[0]["P:model"]["clauses"][0]["witness_candidates"]
    assert "S.paperModel_r" not in [c["name"] for c in candidates]


def test_a_record_without_the_probes_answer_counts_only_a_theorem_as_a_proof():
    # A stored record of an earlier probe has no `proposition`: a theorem is a proof, any other
    # declaration is listed. A declaration whose answer is unknown (null) is listed.
    lean = with_decls({"S.paperModel_r": ("theorem", "absent"),
                       "S.instFactTwoNeZero": ("def", "absent"), "S.Fact.mk": ("ctor", "absent"),
                       "S.unknown": ("def", None)})
    listed = [e["name"] for e in run(lean=lean)[0]["P:rate"]["clauses"][0]["witness_defs"]]
    assert listed == ["S.Fact.mk", "S.Model.r", "S.instFactTwoNeZero", "S.paperModel",
                      "S.unknown"]


def test_a_definition_claim_lists_witness_only_declarations_that_use_its_definitions():
    claims, _ = run()
    assert claims["P:model"]["clauses"][0]["witness_candidates"] == [
        {"name": "S.Model.r", "uses": ["S.Model"], "witnesses": ["S.rate_bound_hypotheses"]},
        {"name": "S.paperModel", "uses": ["S.Model"], "witnesses": ["S.rate_bound_hypotheses"]}]
    assert claims["P:model"]["status_code"] == "definition.reviewed"


# A synthetic project for the probe: a structure with a proof field, the paper's instance of it,
# a `Prop` class with an instance, a definition that needs that instance, and a theorem about the
# instance; a proposition about the structure, its proof and a witness that uses all of them.
WIT = {
    "lakefile.toml": 'name = "wit"\ndefaultTargets = ["Wit"]\n\n[[lean_lib]]\nname = "Wit"\n',
    "Wit.lean": "import Wit.Defs\nimport Wit.Spec\nimport Wit.Acceptance\n",
    "Wit/Defs.lean": """namespace Wit

/-- A proposition held as a class, as `Fact` is in Mathlib. -/
class Fact (p : Prop) : Prop where
  out : p

/-- A positive number. -/
structure Pos where
  val : Nat
  pos : 0 < val

/-- The paper's example. -/
def three : Pos := ⟨3, by decide⟩

instance two_ne_zero : Fact (2 ≠ 0) := ⟨by decide⟩

/-- The positive number `n`, for `n` known to be nonzero. -/
def ofFact (n : Nat) [Fact (n ≠ 0)] : Pos := ⟨n, Nat.pos_of_ne_zero Fact.out⟩

theorem three_val : three.val = 3 := rfl

end Wit
""",
    "Wit/Spec.lean": """import Wit.Defs

namespace Wit.Spec

/-- Every positive number is at least one. -/
def pos_ge_one : Prop := ∀ p : Wit.Pos, 1 ≤ p.val

end Wit.Spec
""",
    "Wit/Acceptance.lean": """import Wit.Spec

namespace Wit.Acceptance

theorem pos_ge_one : Wit.Spec.pos_ge_one := fun p => p.pos

/-- The paper's example, with its value, and the number two. -/
theorem pos_ge_one_hypotheses :
    ∃ q : {p : Wit.Pos // p.val = 3}, q = ⟨Wit.three, Wit.three_val⟩ ∧ (Wit.ofFact 2).val = 2 :=
  ⟨_, rfl, rfl⟩

end Wit.Acceptance
"""}
WIT_CLAIM = {"id": "P:pos", "paper": "P", "scope": "formal", "scope_reviewed": True,
             "clauses": [{"name": "main", "spec": "Wit.Spec.pos_ge_one",
                          "accept": "Wit.Acceptance.pos_ge_one",
                          "witness": "Wit.Acceptance.pos_ge_one_hypotheses"}]}


@needs_lean
@pytest.mark.parametrize("toolchain", ["leanprover/lean4:v4.32.0", "leanprover/lean4:v4.24.0"])
def test_the_probe_reports_which_declarations_of_a_witness_closure_are_proofs(tmp_path,
                                                                              toolchain):
    """As Lean elaborates them: the theorem, the `Prop`-valued instance and the constructor of the
    `Prop` class are propositions and are not listed; the instance, the definition that needs
    the `Prop` instance and the class are listed."""
    if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                      text=True).stdout.find(toolchain) < 0:
        pytest.skip(f"{toolchain} is not installed")
    root = tmp_path / "wit"
    for path, text in WIT.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    (root / "lean-toolchain").write_text(toolchain + "\n")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    query = {"scope_roots": ["Wit"], "spec_prefix": "Wit.Spec", "accept_prefix": "Wit.Acceptance",
             "allowed_axioms": ["propext", "Classical.choice", "Quot.sound"],
             "requests": probe.requests_from_inventory({"claims": [WIT_CLAIM]})}
    lean = probe.lean_session(root, ["Wit"], query, probe.parse_records)
    w = lean["proofs"]["witness:Wit.Acceptance.pos_ge_one_hypotheses:"]
    assert w["errors"] == []
    prop = {n: lean["decls"][n]["proposition"] for n in w["closure"]}
    assert {n for n, p in prop.items() if p is True} == \
        {"Wit.three_val", "Wit.two_ne_zero", "Wit.Fact.mk"}, prop
    assert {n for n, p in prop.items() if p is False} == \
        {"Wit.Fact", "Wit.Pos", "Wit.Pos.mk", "Wit.Pos.val", "Wit.ofFact", "Wit.three"}, prop
    claims, findings = run(reviews=[], claims=[WIT_CLAIM], lean=lean)
    assert [e["name"] for e in claims["P:pos"]["clauses"][0]["witness_defs"]] == \
        ["Wit.Fact", "Wit.ofFact", "Wit.three"]
    assert len([f for f in findings if f["code"] == "witness-def-review"]) == 3
