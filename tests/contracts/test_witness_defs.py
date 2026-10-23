"""#191: the project declarations in the closure of a witness's statement that no proposition's
closure includes are listed, while they lack a current review, as advice that changes no status;
`require_witness_def_reviews` makes their reviews required, which can only lower a status. A
definition claim lists the witness-only declarations that use a definition it maps. A
declaration whose type is a proposition is a proof: it carries no data, so it cannot fix the
instance a witness exhibits, and it is not listed (#243)."""

import copy
from types import SimpleNamespace

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
