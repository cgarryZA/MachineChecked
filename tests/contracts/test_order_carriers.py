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
from prooflens.assess import TOTALISED, totalised
from prooflens.probe import lean_session, parse_records

SRC = ROOT / "tests" / "fixtures" / "carriers"
SPECS = ["join", "extended", "real", "alias", "both", "sets", "plain", "poly", "deep",
         "divNat", "divField", "divExtended", "divGroup", "divPlain", "divPoly", "integrals",
         "integralUnit", "sumExtended", "sumReal", "roots"]
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
