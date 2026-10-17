"""The statement structure the probe exports for display (#46), on the synthetic project
tests/fixtures/structure: each occurrence of a statement's variable names the binder that
introduced it, and a conjunctive conclusion carries its logical shape. Display only: the
binders, their roles and the fingerprints are what they were."""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import build_view

SRC = ROOT / "tests" / "fixtures" / "structure"


def statement(root):
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    (claim,) = view["body"]["claims"]
    link = next(l for l in claim["links"] if l["name"] == "Shape.layout")
    return link["record"]


def var_refs(pp):
    return [(s["t"], s["var"]) for s in pp.get("segments", []) if "var" in s]


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_variables_and_logic_are_exported(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(SRC, root)
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    rec = statement(root)
    b = rec["binders"]
    assert [x["name"] for x in b if x["role"] != "instance"] == \
        ["E", "j", "hj", "k", "hjk", "x", "C", "n"]
    assert [x["role"] for x in b] == ["forall", "instance", "forall", "hypothesis", "forall",
                                      "hypothesis", "forall", "exists", "forall"]
    # Each occurrence names its binder by position: `Inhabited E` is about E (0), `1 ≤ j` about
    # j (2), `j ≤ k` about j and k (2, 4).
    assert var_refs(b[1]["type"]) == [("E", 0)]
    assert var_refs(b[3]["type"]) == [("j", 2)]
    assert var_refs(b[5]["type"]) == [("j", 2), ("k", 4)]
    logic = rec["conclusion"]["logic"]
    assert logic["op"] == "and" and len(logic["args"]) == 2
    assert var_refs(logic["args"][0]["leaf"]) == [("x", 6), ("C", 7)]
    assert rec["conclusion"]["text"] == "x ≤ C ∧ n + x ≤ n + C"
    # Each sub-term is a range of the segments, outer before inner (#59).
    concl = rec["conclusion"]
    shown = ["".join(s["t"] for s in concl["segments"][t["from"]:t["to"]]) for t in concl["terms"]]
    assert shown == ["x ≤ C ∧ n + x ≤ n + C", "x ≤ C", "n + x ≤ n + C", "n + x", "n + C"]
