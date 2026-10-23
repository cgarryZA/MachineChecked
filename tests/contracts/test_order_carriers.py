"""A supremum or infimum is judged by the type it is taken in (#152), and so are a division, an
inverse, an integral and a sum (#233). The probe records each
application of an order operation in a statement with its type: its head constant after
reducible unfolding and the lattice structure Lean finds on it. A supremum in a complete lattice
(collections of sets, an extended number line) always exists and gets no warning; one in the
reals keeps the real-number warning; one in a type with no lattice structure Lean finds is
unresolved, never given the real-number explanation. Division rounds in ℕ, gives 0 in a field
and ∞ in the extended number line, and has no exceptional case in a group; an integral of
functions into a type with one element and a sum on the extended number line get no warning.

The synthetic project tests/fixtures/carriers declares the order operations at the root, as an
order library does, with no library imported; the probe must read it on every supported Lean."""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean
from types import SimpleNamespace

from prooflens.assess import TOTALISED, Assessor, occurrences, totalised
from prooflens.probe import lean_session, parse_records

SRC = ROOT / "tests" / "fixtures" / "carriers"
SPECS = ["join", "extended", "real", "alias", "both", "sets", "plain", "poly", "deep",
         "divNat", "divField", "divExtended", "divGroup", "divPlain", "divPoly", "integrals",
         "integralUnit", "sumExtended", "sumReal", "roots", "two", "twoMixed", "twoMoved",
         "supBounded", "supUnbounded", "supOther", "supLater", "supQuantified", "supConditional",
         "supEmpty", "supRefuted", "infAndSet", "integrable", "integrableOn", "finite",
         "finiteAE"]
REAL = TOTALISED["iSup"]


def probe(root):
    query = {"scope_roots": ["Carriers"], "spec_prefix": "Carriers.Spec",
             "accept_prefix": "Carriers.Acceptance",
             "allowed_axioms": ["propext", "Classical.choice", "Quot.sound"],
             "requests": [{"kind": "spec", "name": f"Carriers.Spec.{s}"} for s in SPECS]}
    res = lean_session(root, ["Carriers"], query, parse_records, work=root / ".work")
    return {n.rsplit(".", 1)[1]: r for n, r in res["specs"].items()}


def warnings(rec):
    return dict(totalised(rec, rec["name"]))


@needs_lean
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_each_supremum_is_judged_by_its_type(tmp_path, toolchain):
    root = tmp_path / "carriers"
    shutil.copytree(SRC, root)
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    recs = probe(root)
    assert {s: r["errors"] for s, r in recs.items() if r["errors"]} == {}

    occ = recs["join"]["order_ops"]
    assert occ["complete"] and {(o["const"], o["carrier"], o["carrier_head"], o["lattice"])
                                for o in occ["occurrences"]} == \
        {("iSup", "MeasurableSpace Ω", "MeasurableSpace", "complete")}

    # A join of collections of sets, and a supremum on the extended number line: no
    # real-number warning. Converting the extended value to a number keeps its own warning.
    assert warnings(recs["join"]) == {}
    w = warnings(recs["extended"])
    assert set(w) == {"ENNReal.toReal"} and "∞.toReal = 0" in w["ENNReal.toReal"]

    # The reals, directly or under an abbreviation, keep the real-number rule.
    for s in ("real", "alias"):
        assert warnings(recs[s]) == {"iSup": f"{REAL} (iSup occurs in Carriers.Spec.{s})"}

    # A join and a real supremum in one statement: only the numeric warning.
    assert warnings(recs["both"]) == {"iSup": f"{REAL} (iSup occurs in Carriers.Spec.both)"}
    # Its occurrences say which supremum the warning is about, each at its own place.
    occ = occurrences(recs["both"], "iSup")
    assert sorted((o["type"], o["structure"], o["state"], o["rule"]) for o in occ) == [
        ("MeasurableSpace Ω", "complete-lattice", "none", None),
        ("Real", "conditionally-complete-lattice", "applies", REAL)]
    assert all(len(o["at"]) == 2 for o in occ) and len({a for o in occ for a in o["at"]}) == 4

    # The supremum of a set, and nested infima over a bounded index, are read in the reals.
    w = warnings(recs["sets"])
    assert w["SupSet.sSup"].startswith(TOTALISED["SupSet.sSup"])
    assert w["iInf"].startswith(TOTALISED["iInf"])

    # A type with no lattice structure, or one the statement quantifies over: unresolved.
    for s, ty in (("plain", "Plain"), ("poly", "α")):
        (msg,) = warnings(recs[s]).values()
        assert "unresolved" in msg and f"({ty})" in msg and "ℝ" not in msg

    # A type whose lattice search does not end: the search fails on its own, the type is
    # unresolved, and the statement's other supremum is still read in the reals.
    ops = {o["carrier"]: o["lattice"] for o in recs["deep"]["order_ops"]["occurrences"]}
    assert ops == {"Deep 0": "unknown", "Real": "conditional"}
    (msg,) = warnings(recs["deep"]).values()
    assert msg.startswith(REAL) and "(Deep 0)" in msg and "unresolved" in msg

    # Division in ℕ, in a field and on the extended number line: three different rules.
    div = {s: warnings(recs[s])["HDiv.hDiv"] for s in ("divNat", "divField", "divExtended")}
    assert div["divNat"].startswith("division in ℕ rounds down and n / 0 = 0")
    assert div["divField"].startswith("division in Real: x / 0 = 0")
    assert div["divExtended"].startswith("division in ℝ≥0∞: x / 0 = ∞")
    assert warnings(recs["divField"])["Inv.inv"].startswith("inverse in Real: 0⁻¹ = 0")
    # In a group, neither division nor inverse has an exceptional case.
    assert {(o["const"], o["algebra"]) for o in recs["divGroup"]["order_ops"]["occurrences"]} == \
        {("HDiv.hDiv", "group"), ("Inv.inv", "group")}
    assert warnings(recs["divGroup"]) == {}
    assert {o["structure"] for o in occurrences(recs["divGroup"], "HDiv.hDiv")} == {"group"}
    # A type with no group structure, or one the statement quantifies over: unresolved.
    for s, ty in (("divPlain", "Plain"), ("divPoly", "α")):
        msg = warnings(recs[s])["HDiv.hDiv"]
        assert "unresolved" in msg and f"({ty})" in msg and "x / 0 = 0" not in msg

    # An integral keeps its warning unless every function is into a type with one element.
    occ = recs["integrals"]["order_ops"]["occurrences"]
    assert {(o["carrier"], o["subsingleton"]) for o in occ
            if o["const"] == "MeasureTheory.integral"} == {("Real", False), ("Unit", True)}
    assert set(warnings(recs["integrals"])) == {"MeasureTheory.integral"}
    assert warnings(recs["integralUnit"]) == {}
    # A sum on the extended number line needs no warning; one on the number line does.
    assert warnings(recs["sumExtended"]) == {}
    assert warnings(recs["sumReal"]) == {
        "tsum": f"{TOTALISED['tsum']} (tsum occurs in Carriers.Spec.sumReal)"}
    # A root keeps its rule; its occurrences, applied or as a function, are read in the reals.
    assert {(o["const"], o["carrier"]) for o in recs["roots"]["order_ops"]["occurrences"]} == \
        {("Real.sqrt", "Real")}
    assert set(warnings(recs["roots"])) == {"Real.sqrt"}

    each_occurrence_has_its_own_finding(recs)
    side_conditions(recs)


def assess(rec, dismissals, fp="fp-1"):
    """The totalisation warnings of `rec` as the clause `T:x#0` of the statement `P.s` with
    fingerprint `fp`, under `dismissals`."""
    a = Assessor(SimpleNamespace(statement_authors=[]), {}, {"decls": {}}, {}, [], dismissals)
    a.totalised_warnings("T:x#0", "P.s", {**rec, "fingerprint": fp})
    return a.findings


def dismissal(f, **kw):
    return {"code": "totalised", "subject": "P.s", "trigger": f["trigger"], "at": f["at"],
            "fingerprint": f["fingerprint"], "rationale": "bounded", "by": "auditor", **kw}


def each_occurrence_has_its_own_finding(recs):
    # Two suprema on the number line: two warnings, each about one application, with its own
    # position and fingerprint.
    two = assess(recs["two"], [])
    assert len(two) == 2 and len({f["id"] for f in two}) == 2
    assert all(f["id"] == f"totalised:T:x#0:iSup@{f['at']}" and len(f["occurrences"]) == 1
               and f["occurrences"][0]["at"][0] == f["at"] and f["statement_fingerprint"] == "fp-1"
               for f in two)
    assert len({f["fingerprint"] for f in two}) == 2
    assert all(f["fingerprint"].startswith("pl-occ-v1:") for f in two)
    first, second = sorted(two, key=lambda f: f["at"])

    # Dismissing one leaves the other open.
    fs = {f["at"]: f for f in assess(recs["two"], [dismissal(first)])}
    assert fs[first["at"]]["dismissed"] == {"rationale": "bounded", "by": "auditor"}
    assert not fs[second["at"]].get("dismissed") and not fs[second["at"]].get("dismissal_stale")

    # The second family's values change type: only the second application's dismissal lapses,
    # although the statement changed.
    both = [dismissal(first), dismissal(second)]
    mixed = {f["at"]: f for f in assess(recs["twoMixed"], both, fp="fp-2")}
    assert set(mixed) == {first["at"], second["at"]}
    assert mixed[first["at"]].get("dismissed") and not mixed[first["at"]].get("dismissal_stale")
    assert not mixed[second["at"]].get("dismissed") and mixed[second["at"]]["dismissal_stale"]

    # A conjunct added before them moves both applications: each dismissal follows its own.
    moved = assess(recs["twoMoved"], both, fp="fp-3")
    assert {f["at"] for f in moved}.isdisjoint({first["at"], second["at"]})
    assert all(f.get("dismissed") and not f.get("dismissal_stale") for f in moved)
    assert {f["fingerprint"] for f in moved} == {first["fingerprint"], second["fingerprint"]}

    # A dismissal of the old form (the operation in the statement, without `at`) still dismisses
    # every application of the operation while the statement is unchanged, and says so; once
    # the statement changes it lapses for all of them.
    old = [{"code": "totalised", "subject": "P.s", "trigger": "iSup", "fingerprint": "fp-1",
            "rationale": "bounded", "by": "auditor"}]
    assert all(f["dismissed"] == {"rationale": "bounded", "by": "auditor", "form": "statement"}
               for f in assess(recs["two"], old))
    assert all(not f.get("dismissed") and f["dismissal_stale"]
               for f in assess(recs["two"], old, fp="fp-2"))


def test_a_record_without_types_is_unresolved_not_real():
    rec = {"name": "P.s", "consts": ["iSup", "HDiv.hDiv"]}
    w = warnings(rec)
    assert "unresolved" in w["iSup"] and "ℝ" not in w["iSup"]
    assert "unresolved" in w["HDiv.hDiv"] and "x / 0 = 0" not in w["HDiv.hDiv"]
    # A walk that stopped before reaching the operation leaves it unresolved too.
    rec = {"name": "P.s", "consts": ["iSup"], "order_ops": {"occurrences": [], "complete": False}}
    assert "too large" in warnings(rec)["iSup"]
    # One that read some applications before it stopped still leaves the rest unresolved: a
    # join it read does not silence a supremum it did not reach.
    rec["order_ops"]["occurrences"] = [
        {"const": "iSup", "carrier": "ENNReal", "carrier_head": "ENNReal", "lattice": "complete"}]
    assert "too large" in warnings(rec)["iSup"]
    # Every occurrence in a complete lattice: nothing to warn about.
    rec["order_ops"] = {"complete": True, "occurrences": [
        {"const": "iSup", "carrier": "ENNReal", "carrier_head": "ENNReal", "lattice": "complete"}]}
    assert warnings(rec) == {}
    # Another conditionally complete type: a default value, named with its type.
    rec["order_ops"]["occurrences"].append(
        {"const": "iSup", "carrier": "NNReal", "carrier_head": "NNReal", "lattice": "conditional"})
    assert warnings(rec)["iSup"].startswith("a supremum in NNReal is a default value")


def test_division_and_exemptions_from_recorded_types():
    def rec(*occ, complete=True, consts=None):
        return {"name": "P.s", "consts": consts or sorted({o["const"] for o in occ}),
                "order_ops": {"complete": complete, "occurrences": list(occ)}}
    real = {"const": "HDiv.hDiv", "carrier": "ℝ", "carrier_head": "Real",
            "algebra": "group-with-zero"}
    nat = {"const": "HDiv.hDiv", "carrier": "ℕ", "carrier_head": "Nat", "algebra": "unknown"}
    # Two types in one statement: both rules, once each.
    msg = warnings(rec(real, nat, real))["HDiv.hDiv"]
    assert msg == "division in ℝ: x / 0 = 0; division in ℕ rounds down and n / 0 = 0 " \
        "(HDiv.hDiv occurs in P.s)"
    # A group division the walk read does not silence one it did not reach.
    grp = {"const": "HDiv.hDiv", "carrier": "G", "carrier_head": "G", "algebra": "group"}
    assert warnings(rec(grp)) == {}
    assert "too large" in warnings(rec(grp, complete=False))["HDiv.hDiv"]
    # Used without being read: unresolved, not the field rule.
    msg = warnings(rec(consts=["Inv.inv"]))["Inv.inv"]
    assert "unresolved" in msg and "0⁻¹ = 0" not in msg
    # An integral is exempt only when every application was read in a type with one element.
    unit = {"const": "MeasureTheory.integral", "carrier": "Unit", "carrier_head": "Unit",
            "subsingleton": True}
    assert warnings(rec(unit)) == {}
    for r in (rec(unit, complete=False), rec(consts=["MeasureTheory.integral"]),
              {"name": "P.s", "consts": ["MeasureTheory.integral"]}):
        assert warnings(r) == {"MeasureTheory.integral":
                               f"{TOTALISED['MeasureTheory.integral']} "
                               "(MeasureTheory.integral occurs in P.s)"}


def conds(rec, c):
    """Each recorded application of `c` in `rec`: its conditions' states, and their state
    together."""
    return [({d["condition"]: d["state"] for d in o.get("conditions", [])},
             o.get("condition_state")) for o in occurrences(rec, c)]


def side_conditions(recs):
    # A real supremum with a correctly scoped bound is established, by the premise, and the
    # index type's nonemptiness by Lean's instance; the warning is resolved, nothing else.
    (o,) = occurrences(recs["supBounded"], "iSup")
    assert o["condition_state"] == "established"
    bound = next(d for d in o["conditions"] if d["condition"] == "bounded-above")
    assert bound["by"] == "premise" and bound["statement"] == "BddAbove (Set.range f)"
    (f,) = assess(recs["supBounded"], [])
    assert f["resolved"] is True and not f.get("dismissed") and f["tier"] == "warning"
    # With no bound, or a bound for another family, or one that needs a further hypothesis:
    # unresolved, never refuted, and the warning stays open.
    for s in ("supUnbounded", "supOther", "supConditional"):
        assert conds(recs[s], "iSup") == [({"bounded-above": "unresolved",
                                            "nonempty-index": "established"}, "unresolved")]
        assert not any(f.get("resolved") for f in assess(recs[s], []))
    # A later premise of the same statement, and a quantified premise specialised to the
    # family, establish it too.
    for s in ("supLater", "supQuantified"):
        assert conds(recs[s], "iSup")[0][1] == "established"
    # An index type that may be empty leaves nonemptiness unresolved.
    assert conds(recs["supEmpty"], "iSup") == [({"bounded-above": "established",
                                                 "nonempty-index": "unresolved"}, "unresolved")]
    # A premise that the family is unbounded refutes the condition, with that premise.
    (o,) = occurrences(recs["supRefuted"], "iSup")
    assert o["condition_state"] == "refuted" and o["conditions"][0]["statement"].startswith("¬")
    # An infimum needs a lower bound; the supremum of a set a bound and nonemptiness of the set,
    # here from one premise's conjuncts.
    assert conds(recs["infAndSet"], "iInf")[0][1] == "established"
    assert conds(recs["infAndSet"], "SupSet.sSup") == [
        ({"bounded-above": "established", "nonempty-set": "established"}, "established")]

    # `Integrable f μ` establishes `∫ f ∂μ` and not `∫ g ∂μ` or `∫ f ∂ν`.
    assert sorted(st for _, st in conds(recs["integrable"], "MeasureTheory.integral")) == [
        "established", "unresolved", "unresolved"]
    found = assess(recs["integrable"], [])
    assert len(found) == 3 and sum(bool(f.get("resolved")) for f in found) == 1
    # Integrability on a set establishes the integral for the restricted measure.
    assert conds(recs["integrableOn"], "MeasureTheory.integral")[0][1] == "established"

    # `x ≠ ⊤` establishes the finiteness of `x.toReal` and not of `y.toReal`; a value taken
    # from the nonnegative numbers is finite by its form. Finiteness almost everywhere does not
    # establish finiteness at a point.
    states = sorted(st for _, st in conds(recs["finite"], "ENNReal.toReal"))
    assert states == ["established", "established", "unresolved"]
    assert {o["type"] for o in occurrences(recs["finite"], "ENNReal.toReal")} == {"ENNReal"}
    assert conds(recs["finiteAE"], "ENNReal.toReal") == [({"finite": "unresolved"},
                                                          "unresolved")]

    # A resolved warning changes nothing but itself: its message is the rule's, as before.
    (f,) = assess(recs["supBounded"], [])
    assert f["message"] == f"{REAL} (iSup occurs in P.s)"
