"""A supremum or infimum is judged by the type it is taken in (#152). The probe records each
application of an order operation in a statement with its type: its head constant after
reducible unfolding and the lattice structure Lean finds on it. A supremum in a complete lattice
(collections of sets, an extended number line) always exists and gets no warning; one in the
reals keeps the real-number warning; one in a type with no lattice structure Lean finds is
unresolved, never given the real-number explanation.

The synthetic project tests/fixtures/carriers declares the order operations at the root, as an
order library does, with no library imported; the probe must read it on every supported Lean."""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean
from prooflens.assess import TOTALISED, totalised
from prooflens.probe import lean_session, parse_records

SRC = ROOT / "tests" / "fixtures" / "carriers"
SPECS = ["join", "extended", "real", "alias", "both", "sets", "plain", "poly"]
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
    assert all(not r["errors"] for r in recs.values())

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


def test_a_record_without_types_is_unresolved_not_real():
    rec = {"name": "P.s", "consts": ["iSup", "HDiv.hDiv"]}
    w = warnings(rec)
    assert "unresolved" in w["iSup"] and "ℝ" not in w["iSup"]
    assert w["HDiv.hDiv"] == f"{TOTALISED['HDiv.hDiv']} (HDiv.hDiv occurs in P.s)"
    # A walk that stopped before reaching the operation leaves it unresolved too.
    rec = {"name": "P.s", "consts": ["iSup"], "order_ops": {"occurrences": [], "complete": False}}
    assert "too large" in warnings(rec)["iSup"]
    # Every occurrence in a complete lattice: nothing to warn about.
    rec["order_ops"] = {"complete": True, "occurrences": [
        {"const": "iSup", "carrier": "ENNReal", "carrier_head": "ENNReal", "lattice": "complete"}]}
    assert warnings(rec) == {}
    # Another conditionally complete type: a default value, named with its type.
    rec["order_ops"]["occurrences"].append(
        {"const": "iSup", "carrier": "NNReal", "carrier_head": "NNReal", "lattice": "conditional"})
    assert warnings(rec)["iSup"].startswith("a supremum in NNReal is a default value")
