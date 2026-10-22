"""#191: the project declarations in the closure of a witness's statement that no proposition's
closure includes are listed, while they lack a current review, as advice that changes no status;
`require_witness_def_reviews` makes their reviews required, which can only lower a status. A
definition claim lists the witness-only declarations that use a definition it maps."""

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


def run(reviews=REVIEWED, claims=(FORMAL, MODEL), dismissals=(), **cfg):
    config = SimpleNamespace(statement_authors=[], papers=[], lean_root=None, **cfg)
    out = Assessor(config, {"claims": list(claims)}, LEAN, {}, list(reviews),
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


def test_a_definition_claim_lists_witness_only_declarations_that_use_its_definitions():
    claims, _ = run()
    assert claims["P:model"]["clauses"][0]["witness_candidates"] == [
        {"name": "S.Model.r", "uses": ["S.Model"], "witnesses": ["S.rate_bound_hypotheses"]},
        {"name": "S.paperModel", "uses": ["S.Model"], "witnesses": ["S.rate_bound_hypotheses"]}]
    assert claims["P:model"]["status_code"] == "definition.reviewed"
