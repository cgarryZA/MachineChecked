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


def statement(root, name="Shape.layout"):
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    return next(l["record"] for c in view["body"]["claims"] for l in c["links"]
                if l["name"] == name)


def texts(pp):
    """Each selectable sub-term's text, by its identity."""
    return {t["id"]: "".join(s["t"] for s in pp["segments"][t["from"]:t["to"]])
            for t in pp.get("terms", [])}


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
    assert rec["exact"]["text"], "the complete expression is emitted by Lean"
    assert "∃" in rec["exact"]["text"] and "∀" in rec["exact"]["text"]
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
    # A "there is" inside the conclusion shows its witness's type, and each witness is a
    # variable of its own: the two `x` of sibling parts are different variables, and the one
    # `x` of `x j = j ∧ j ≤ x j` is the same in both of its parts (#67).
    rec = statement(root, "Shape.witnesses")
    assert rec["conclusion"]["text"] == \
        "(∃ (x : Nat → Nat), x j = j ∧ j ≤ x j) ∧ ∃ (x : Bool), x = true"
    left, right = rec["conclusion"]["logic"]["args"]
    assert (left["op"], left["name"], left["type"]["text"], left["var"]) == \
        ("exists", "x", "Nat → Nat", 1)
    assert (right["op"], right["name"], right["type"]["text"], right["var"]) == \
        ("exists", "x", "Bool", 2)
    a, b = left["args"][0]["args"]
    assert var_refs(a["leaf"]) == [("x", 1), ("j", 0), ("j", 0)]
    assert var_refs(b["leaf"]) == [("j", 0), ("x", 1), ("j", 0)]
    assert var_refs(right["args"][0]["leaf"]) == [("x", 2)]
    assert rec["exact"]["text"].startswith("∀ (j : Nat), (∃ (x : Nat → Nat)")
    # Negation, implication and "for every" inside a part keep their scope; an instance says
    # whether it supplies data or a proposition (#67).
    assert [x.get("supplies") for x in statement(root)["binders"]
            if x["role"] == "instance"] == ["data"]
    rec = statement(root, "Shape.shapes")
    assert [(x["role"], x["supplies"]) for x in rec["binders"]] == \
        [("forall", "data"), ("instance", "proposition")]
    neg, alt = rec["conclusion"]["logic"]["args"]
    assert neg["op"] == "not" and neg["args"][0]["op"] == "exists"
    assert neg["args"][0]["type"]["text"] == "Nat"
    assert alt["op"] == "or"
    every, cond = alt["args"]
    assert (every["op"], every["name"], every["type"]["text"]) == ("forall", "n", "Nat")
    assert cond["op"] == "implies" and cond["args"][0]["leaf"]["text"] == "1 = 1"
    assert cond["args"][1]["op"] == "exists" and cond["args"][1]["name"] == "m"
    numbers = [neg["args"][0]["var"], every["var"], cond["args"][1]["var"]]
    assert len(set(numbers)) == 3 and min(numbers) == len(rec["binders"])
    # Each sub-term has an identity: its position in the whole proposition, independent of
    # how the statement is printed or split. The same sub-term has the same identity in the
    # readable parts and in the exact proposition, identities are unique, and the two `x` of
    # sibling parts are bound at different places (#73).
    for name in ("Shape.layout", "Shape.witnesses", "Shape.shapes"):
        rec = statement(root, name)
        exact = texts(rec["exact"])
        assert len(exact) == len(rec["exact"]["terms"]), "identities are unique"
        tree = {}
        for b in rec["binders"]:
            tree.update(texts(b["type"]))
        stack = [rec["conclusion"].get("logic") or {"leaf": rec["conclusion"]}]
        while stack:
            n = stack.pop()
            for pp in (n.get("leaf"), n.get("type")):
                if pp:
                    tree.update(texts(pp))
            stack += n.get("args", [])
        assert tree and all(exact.get(i) == t for i, t in tree.items()), (name, tree, exact)
    left, right = statement(root, "Shape.witnesses")["conclusion"]["logic"]["args"]
    assert left["id"] != right["id"] and left["type"]["id"] != right["type"]["id"]
