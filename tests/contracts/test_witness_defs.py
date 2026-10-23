"""#191: the project declarations in the closure of a witness's statement that no proposition's
closure includes are listed, while they lack a current review, as advice that changes no status;
`require_witness_def_reviews` makes their reviews required, which can only lower a status. A
definition claim lists the witness-only declarations that use a definition it maps. A
declaration whose type is a proposition is a proof: it carries no data, so it cannot fix the
instance a witness exhibits, and it is not listed (#243). The tactic script Lean stores for a
tactic default gives only a proof: it needs no review in a proposition's closure, a definition
claim's or a witness's (#325)."""

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


def with_scripts(auto_param=True) -> dict:
    """LEAN where a structure in each closure has a field with a tactic default, whose script
    Lean stores as a definition reached through the constructor's type (`…._autoParam`); the
    witness's closure also has a definition with a binder's tactic default (`S.half._auto_1`).
    The probe says which declarations are such scripts (`auto_param`; left out for `None`, as in
    a record of an earlier probe)."""
    lean = copy.deepcopy(LEAN)
    more = {"specs": ("S.Rate", "S.Rate.mk", "S.Rate.pos._autoParam"),
            "defs": ("S.Model.mk", "S.Model.ok._autoParam"),
            "witness": ("S.Pair", "S.Pair.mk", "S.Pair.pos._autoParam", "S.half",
                        "S.half._auto_1")}
    lean["specs"]["S.rate_bound"]["closure"] += more["specs"]
    lean["defs"]["S.Model"]["closure"] += more["defs"]
    lean["proofs"]["witness:S.rate_bound_hypotheses:"]["closure"] += more["witness"]
    for n in sum(more.values(), ()):
        script = "_auto" in n
        lean["decls"][n] = {**decl(n), "kind": "ctor" if n.endswith(".mk") else "def",
                            "proposition": False,
                            **({} if auto_param is None else {"auto_param": script})}
    return lean


SCRIPTS = {"S.Rate.pos._autoParam", "S.Model.ok._autoParam", "S.Pair.pos._autoParam",
           "S.half._auto_1"}


def test_the_tactic_script_of_a_tactic_default_needs_no_review():
    """#325: a field or binder with a tactic default (`pos : 0 < val := by decide`) makes Lean
    store the tactic as a definition. Running it gives a proof of what the field states, so it
    is left out of the definitions a proposition or a definition claim needs reviewed and out of
    the witness-only declarations."""
    lean = with_scripts()
    claims, findings = run(lean=lean)
    rate, model = claims["P:rate"]["clauses"][0], claims["P:model"]["clauses"][0]
    assert sorted(rate["def_reviews"]) == ["S.Rate", "S.Rate.mk", "S.decay"]
    assert sorted(model["def_reviews"]) == ["S.Model", "S.Model.mk"]
    assert [e["name"] for e in rate["witness_defs"]] == [
        "S.Model.r", "S.Pair", "S.Pair.mk", "S.half", "S.paperModel"]
    assert not [f for f in findings if any(s in f["message"] for s in SCRIPTS)]
    every = REVIEWED + [review("def", n, f"fp-{n}") for n in ("S.Rate", "S.Rate.mk",
                                                              "S.Model.mk")]
    claims, _ = run(every, lean=lean)
    assert claims["P:rate"]["status_code"] == "formal.accepted"
    assert claims["P:model"]["status_code"] == "definition.reviewed"
    # Required by the configuration, the witness's declarations other than the scripts.
    claims, findings = run(every, lean=lean, require_witness_def_reviews=True)
    assert sorted(f["trigger"] for f in findings if f["code"] == "def-review") == [
        "S.Model.r", "S.Pair", "S.Pair.mk", "S.half", "S.paperModel"]


def test_a_record_without_the_probes_answer_is_reviewed_like_a_definition():
    claims, findings = run(REVIEWED + [review("def", n, f"fp-{n}")
                                       for n in ("S.Rate", "S.Rate.mk", "S.Model.mk")],
                           lean=with_scripts(auto_param=None))
    assert "S.Rate.pos._autoParam" in claims["P:rate"]["clauses"][0]["def_reviews"]
    assert claims["P:rate"]["status_code"] == "formal.review-pending"
    assert "S.Pair.pos._autoParam" in [
        e["name"] for e in claims["P:rate"]["clauses"][0]["witness_defs"]]


# A synthetic project for the probe: a structure with a proof field, the paper's instance of it,
# a `Prop` class with an instance, a definition that needs that instance, a theorem about the
# instance and a function of `Fin 3`; a proposition about the structure, its proof, and a witness
# that uses all of them and whose statement has proofs Lean makes auxiliary (`_proof_1`).
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

/-- A number below three, read off. -/
def pick (x : Fin 3) : Nat := x.val

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

/-- The paper's example, with its value, the number two, and a number below three. -/
theorem pos_ge_one_hypotheses :
    ∃ q : {p : Wit.Pos // p.val = 3}, q = ⟨Wit.three, Wit.three_val⟩ ∧ (Wit.ofFact 2).val = 2 ∧
      Wit.pick ⟨1, by omega⟩ = Wit.pick ⟨1, by decide⟩ :=
  ⟨_, rfl, rfl, rfl⟩

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
    """As Lean elaborates them: the auxiliary proof of the witness's statement, the theorem, the
    `Prop`-valued instance and the constructor of the `Prop` class are propositions and are not
    listed; the instance, the definitions that use the `Prop` instance and `Fin 3`, and the class
    are listed."""
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
    aux = {n for n in prop if n.startswith("Wit.Acceptance.pos_ge_one_hypotheses._proof_")}
    assert aux and {n for n, p in prop.items() if p is True} == \
        {"Wit.three_val", "Wit.two_ne_zero", "Wit.Fact.mk"} | aux, prop
    assert {n for n, p in prop.items() if p is False} == \
        {"Wit.Fact", "Wit.Pos", "Wit.Pos.mk", "Wit.Pos.val", "Wit.ofFact", "Wit.pick",
         "Wit.three"}, prop
    claims, findings = run(reviews=[], claims=[WIT_CLAIM], lean=lean)
    assert [e["name"] for e in claims["P:pos"]["clauses"][0]["witness_defs"]] == \
        ["Wit.Fact", "Wit.ofFact", "Wit.pick", "Wit.three"]
    assert len([f for f in findings if f["code"] == "witness-def-review"]) == 4


# A synthetic project for the tactic defaults of #325: two structures whose proof fields have
# tactic defaults, and a definition whose proof binder has one. The proposition uses one of the
# structures and the definition; the witness uses the other structure only.
AUTO = {
    "lakefile.toml": 'name = "auto"\ndefaultTargets = ["Auto"]\n\n[[lean_lib]]\nname = "Auto"\n',
    "Auto.lean": "import Auto.Defs\nimport Auto.Spec\nimport Auto.Acceptance\n",
    "Auto/Defs.lean": """namespace Auto

/-- A number below ten. -/
structure Small where
  val : Nat
  lt : val < 10 := by decide

/-- Half of a positive number. -/
def half (n : Nat) (_h : 0 < n := by omega) : Nat := n / 2

/-- A positive number. -/
structure Pos where
  val : Nat
  pos : 0 < val := by decide

/-- The paper's example. -/
def three : Pos := { val := 3 }

end Auto
""",
    "Auto/Spec.lean": """import Auto.Defs

namespace Auto.Spec

/-- Half of one more than a number below ten is at most that number plus one. -/
def half_le : Prop := ∀ s : Auto.Small, Auto.half (s.val + 1) ≤ s.val + 1

end Auto.Spec
""",
    "Auto/Acceptance.lean": """import Auto.Spec

namespace Auto.Acceptance

theorem half_le : Auto.Spec.half_le := fun _ => Nat.div_le_self _ _

/-- The paper's example. -/
theorem half_le_hypotheses : ∃ p : Auto.Pos, p = Auto.three := ⟨_, rfl⟩

end Auto.Acceptance
"""}
AUTO_CLAIM = {"id": "P:half", "paper": "P", "scope": "formal", "scope_reviewed": True,
              "clauses": [{"name": "main", "spec": "Auto.Spec.half_le",
                           "accept": "Auto.Acceptance.half_le",
                           "witness": "Auto.Acceptance.half_le_hypotheses"}]}


@needs_lean
@pytest.mark.parametrize("toolchain", ["leanprover/lean4:v4.32.0", "leanprover/lean4:v4.24.0"])
def test_the_probe_reports_the_tactic_scripts_of_tactic_defaults(tmp_path, toolchain):
    """As Lean elaborates them: the scripts of the fields' tactic defaults (`…._autoParam`) and
    of the binder's are in the closures of the proposition and of the witness, the probe says
    they are scripts, and none of them needs a review or is listed."""
    if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                      text=True).stdout.find(toolchain) < 0:
        pytest.skip(f"{toolchain} is not installed")
    root = tmp_path / "auto"
    for path, text in AUTO.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    (root / "lean-toolchain").write_text(toolchain + "\n")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    query = {"scope_roots": ["Auto"], "spec_prefix": "Auto.Spec",
             "accept_prefix": "Auto.Acceptance",
             "allowed_axioms": ["propext", "Classical.choice", "Quot.sound"],
             "requests": probe.requests_from_inventory({"claims": [AUTO_CLAIM]})}
    lean = probe.lean_session(root, ["Auto"], query, probe.parse_records)
    spec = lean["specs"]["Auto.Spec.half_le"]
    w = lean["proofs"]["witness:Auto.Acceptance.half_le_hypotheses:"]
    assert spec["errors"] == [] and w["errors"] == []
    flag = {n: lean["decls"][n]["auto_param"] for n in spec["closure"] + w["closure"]}
    scripts = {n for n, a in flag.items() if a is True}
    # The binder's script is `Auto.half._auto_1` on Lean 4.32, a name with macro scopes on 4.24.
    fields = {"Auto.Small.lt._autoParam", "Auto.Pos.pos._autoParam"}
    binder = scripts - fields
    assert fields <= scripts and len(binder) == 1, flag
    assert set(spec["closure"]) == {"Auto.Small", "Auto.Small.mk", "Auto.Small.val",
                                    "Auto.Small.lt._autoParam", "Auto.half"} | binder
    assert set(w["closure"]) == {"Auto.Pos", "Auto.Pos.mk", "Auto.Pos.pos._autoParam",
                                 "Auto.three"}
    assert {n for n, a in flag.items() if a is False} == set(flag) - scripts
    claims, findings = run(reviews=[], claims=[AUTO_CLAIM], lean=lean)
    cl = claims["P:half"]["clauses"][0]
    assert sorted(cl["def_reviews"]) == ["Auto.Small", "Auto.Small.mk", "Auto.Small.val",
                                         "Auto.half"]
    assert [e["name"] for e in cl["witness_defs"]] == ["Auto.Pos", "Auto.Pos.mk", "Auto.three"]
    assert not [f for f in findings
                if f.get("trigger") in scripts or any(s in f["message"] for s in scripts)]
    # Reviews of the proposition and of the definitions it uses accept the claim.
    reviews = [review("spec", "Auto.Spec.half_le", spec["fingerprint"])] + [
        review("def", n, lean["decls"][n]["fingerprint"]) for n in cl["def_reviews"]]
    claims, _ = run(reviews=reviews, claims=[AUTO_CLAIM], lean=lean)
    assert claims["P:half"]["status_code"] == "formal.accepted"
