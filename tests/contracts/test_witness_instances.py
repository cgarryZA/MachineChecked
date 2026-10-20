"""#173: a proposition whose only hypotheses are instances of standard classes over its own
variables is reported apart from the witness obligation; any other hypothesis keeps it, and
the obligation names the binders that need a witness. Neither changes a status."""

from types import SimpleNamespace

from prooflens.assess import Assessor


def binder(role, name, text):
    return {"role": role, "name": name, "type": {"text": text}}


# A synthetic proposition about the squared distance to zero in an L² space.
INSTANCES = [binder("forall", "Ω", "Type u"), binder("instance", "inst✝", "MeasurableSpace Ω"),
             binder("forall", "P", "MeasureTheory.Measure Ω"),
             binder("instance", "inst✝¹", "MeasureTheory.IsProbabilityMeasure P"),
             binder("forall", "F", "Type v"), binder("instance", "inst✝²", "NormedAddCommGroup F"),
             binder("instance", "inst✝³", "InnerProductSpace ℝ F"),
             binder("forall", "N", "ℕ"), binder("instance", "inst✝⁴", "NeZero N")]


def assess(binders, witness=None, **cfg):
    clause = {"name": "main", "spec": "S.spec", "accept": "S.accept"}
    if witness:
        clause["witness"] = witness
    inv = {"claims": [{"id": "P:a", "paper": "P", "scope": "formal", "scope_reviewed": True,
                       "clauses": [clause]}]}
    lean = {"specs": {"S.spec": {"fingerprint": "fp", "errors": [], "closure": [],
                                 "binders": binders, "consts": []}},
            "proofs": {"accept:S.accept:S.spec": {"errors": [], "sorry": False, "axioms": []},
                       "witness:S.wit:": {"errors": [], "sorry": False, "axioms": []}},
            "decls": {}, "defs": {}, "layering": []}
    config = SimpleNamespace(statement_authors=[], papers=[], lean_root=None, **cfg)
    out = Assessor(config, inv, lean, {}, [], []).run()
    return out["claims"][0], [f for f in out["findings"]
                              if f["code"] in ("witness", "witness-instances")]


def test_instance_only_hypotheses_are_a_low_signal_warning():
    claim, found = assess(INSTANCES)
    assert [f["code"] for f in found] == ["witness-instances"]
    f = found[0]
    assert f["tier"] == "warning" and f["signal"] == "low"
    assert "MeasureTheory.IsProbabilityMeasure" in f["message"] and "NeZero" in f["message"]
    # The status is the same as with the obligation.
    assert claim["status_code"] == assess(INSTANCES + [binder("hypothesis", "h", "0 < N")])[0][
        "status_code"]


def test_a_premise_or_an_unlisted_class_keeps_the_obligation_and_names_its_binder():
    for extra, shown in ((binder("hypothesis", "hN", "1 < N"), "hN : 1 < N"),
                         (binder("instance", "inst✝⁵", "Fact (1 < N)"), "[Fact (1 < N)]"),
                         (binder("instance", "inst✝⁵", "NeZero 0"), "[NeZero 0]"),
                         (binder("instance", "inst✝⁵", "Toy.MyClass F"), "[Toy.MyClass F]")):
        _, found = assess(INSTANCES + [extra])
        assert [f["code"] for f in found] == ["witness"], extra
        assert found[0]["tier"] == "obligation"
        assert shown in found[0]["message"] and found[0]["binders"] == [shown]


def test_an_instance_on_a_variable_bound_after_it_is_not_treated_as_inhabited():
    # The argument is not a variable bound before the instance: it may be a constant.
    _, found = assess([binder("instance", "inst✝", "NeZero k"), binder("forall", "k", "ℕ")])
    assert [f["code"] for f in found] == ["witness"]


def test_the_project_sets_the_classes_treated_as_inhabited():
    _, found = assess(INSTANCES, inhabited_classes=[])
    assert [f["code"] for f in found] == ["witness"]
    _, found = assess([binder("forall", "F", "Type"), binder("instance", "i", "Toy.MyClass F")],
                      inhabited_classes=["Toy.MyClass"])
    assert [f["code"] for f in found] == ["witness-instances"]


def test_a_witness_or_no_hypothesis_needs_nothing():
    assert assess(INSTANCES + [binder("hypothesis", "h", "0 < N")], witness="S.wit")[1] == []
    assert assess([binder("forall", "n", "ℕ")])[1] == []
