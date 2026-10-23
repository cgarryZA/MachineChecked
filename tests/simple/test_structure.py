"""The statement structure the probe exports for display (#46), on the synthetic project
tests/fixtures/structure: each occurrence of a statement's variable names the binder that
introduced it, and a conjunctive conclusion carries its logical shape. Display only: the
binders, their roles and the fingerprints are what they were."""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import symbols
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
    # Each occurrence of a variable has an identity of its own beside the variable's number, the
    # same in the readable parts and in the exact Lean, apart from the other x's (#73).
    xs = [x for leaf in (a["leaf"], b["leaf"]) for x in leaf["segments"] if x.get("var") == 1]
    assert [x["t"] for x in xs] == ["x", "x"] and len({x["at"] for x in xs}) == 2
    exact_at = {x["at"]: x["t"] for x in rec["exact"]["segments"] if "at" in x}
    assert all(exact_at.get(x["at"]) == "x" for x in xs), (xs, exact_at)
    other = [x["at"] for x in right["args"][0]["leaf"]["segments"] if x.get("var") == 2]
    assert other and not set(other) & {x["at"] for x in xs}
    assert [symbols.term_by_id(rec, x["at"]) for x in xs] == ["x", "x"]
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


def build_copy(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(SRC, root)
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_definitions_are_exported_as_written(tmp_path, toolchain):
    """A linked definition carries what it says (#97): its parameters in their order, with how
    each is written, and its body with the witness's type; a definition by recursion carries
    the equation theorems Lean derives for it, each with its exact statement; both carry their
    authored source. Sub-terms of the body have the identities they have in the value."""
    root = build_copy(tmp_path, toolchain)
    d = statement(root, "Shape.MultipleAbove")["decl"]
    assert d["defined_by"] == "body"
    assert [(p["name"], p["binder"], p["type"]["text"]) for p in d["params"]] == \
        [("b", "explicit", "Nat"), ("m", "implicit", "Nat"), ("n", "explicit", "Nat")]
    assert d["body"]["text"] == "∃ (q : Nat), b ≤ q ∧ n = m * q"
    assert d["result"]["text"] == "Prop"
    # The body's variables are the parameters, by position.
    assert ("m", 1) in var_refs(d["body"]) and ("n", 2) in var_refs(d["body"])
    body, value = texts(d["body"]), texts(d["value"])
    assert body and all(value.get(i) == t for i, t in body.items())
    assert [e["name"] for e in d["equations"]] == ["Shape.MultipleAbove.eq_1"]
    assert d["lean_source"]["text"].splitlines()[-1].startswith("def MultipleAbove (b : Nat)")
    assert d["lean_source"]["file"] == "Shape/Main.lean"

    f = statement(root, "Shape.fib")["decl"]
    assert f["defined_by"] == "equations" and f["equations_omitted"] == 0
    assert [e["name"] for e in f["equations"]] == \
        ["Shape.fib.eq_1", "Shape.fib.eq_2", "Shape.fib.eq_3"]
    e1, e2, e3 = f["equations"]
    assert e1["statement"]["text"] == "Shape.fib 0 = 0" and e1["params"] == []
    assert e2["statement"]["text"] == "Shape.fib 1 = 1"
    assert e3["statement"]["text"].startswith("∀ (n : Nat), Shape.fib ")
    assert [p["name"] for p in e3["params"]] == ["n"]
    assert e3["statement"]["text"].endswith(e3["equation"]["text"])
    # An equation's sub-terms are named by its theorem, the same in both of its views.
    eq, whole = texts(e3["equation"]), texts(e3["statement"])
    assert eq and all(i.startswith("Shape.fib.eq_3:") and whole.get(i) == t
                      for i, t in eq.items())
    # ... and a link or an alignment can name them by that identity (#73).
    assert all(symbols.term_by_id({"definition": f}, i) == t for i, t in eq.items())
    assert "| n + 2 => fib n + fib (n + 1)" in f["lean_source"]["text"]
    assert "body" not in f, "the compiled recursion is only the value"


def props(o, kind="proposition"):
    return [(p["field"], p["type"]["text"]) for p in o.get("properties", []) if p["kind"] == kind]


def expansions(pp):
    """The expansions of a printed expression, by the text of the application each expands."""
    out = {}
    for x in pp.get("expansions", []):
        t = next((t for t in pp["terms"] if t["id"] == x["at"]), None)
        text = "".join(s["t"] for s in pp["segments"][t["from"]:t["to"]]) if t else x["name"]
        out[bare(text)] = x
    return out


def bare(s):
    """`s` without parentheses that enclose all of it."""
    if not (s.startswith("(") and s.endswith(")")):
        return s
    depth = 0
    for i, c in enumerate(s):
        depth += (c == "(") - (c == ")")
        if depth == 0 and i < len(s) - 1:
            return s
    return s[1:-1]


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_properties_carried_by_types(tmp_path, toolchain):
    """An object whose type is a subtype, structure or class carries that type's fields,
    specialised to the object, each once with where it comes from (#98); where the object
    stands decides whether they are given, inside an assumption, or established."""
    root = build_copy(tmp_path, toolchain)
    # A supplied solution: its proof fields (one inherited) apply to s; its data is listed as
    # data; the extra hypothesis stays a hypothesis of its own.
    b = statement(root, "Shape.supplied")["binders"]
    s = next(x for x in b if x["name"] == "s")
    assert s["role"] == "forall"
    assert props(s) == [("start", "s.path 0 = d"), ("le_bound", "∀ (n : Nat), s.path n ≤ s.bound")]
    assert [f for f, _ in props(s, "data")] == ["path", "bound"]
    start = next(p for p in s["properties"] if p["field"] == "start")
    assert (start["structure"], start["declared_in"], start["inherited"], start["projection"]) == \
        ("Shape.Solution", "Shape.Base", True, "Shape.Base.start")
    assert start["type"]["id"] == s["id"] + "#start:/"
    assert ("s", 1) in var_refs(start["type"]) and ("d", 0) in var_refs(start["type"])
    h = next(x for x in b if x["name"] == "h")
    assert h["role"] == "hypothesis" and h["type"]["text"] == "s.bound ≤ 5"
    assert "properties" not in h and "objects" not in h
    # An assumed existence: the solution and its properties stay inside the assumption.
    rec = statement(root, "Shape.assumed")
    h = rec["binders"][0]
    assert h["role"] == "hypothesis" and "properties" not in h
    [obj] = h["objects"]
    assert (obj["op"], obj["name"], obj["scope"]) == ("exists", "s", ["forall", "then"])
    assert props(obj)[0] == ("start", "s.path 0 = d")
    out = rec["binders"][1]
    assert (out["role"], out["type"]["text"]) == ("exists", "Shape.Solution 0")
    assert props(out)[0] == ("start", "s.path 0 = 0")
    # An established existence: the solution is a witness, under the condition on d.
    b = statement(root, "Shape.produced")["binders"]
    assert [(x["role"], x["name"]) for x in b] == \
        [("forall", "d"), ("hypothesis", "h1"), ("exists", "s")]
    assert props(b[2])[1] == ("le_bound", "∀ (n : Nat), s.path n ≤ s.bound")
    # A subtype carries its predicate.
    [p] = statement(root, "Shape.positive")["binders"]
    assert props(p) == [("property", "0 < p.val")] and props(p, "data") == [("val", "Nat")]
    # A class instance is an input carrying its law and its data (inherited from Inhabited);
    # `Subsingleton T` in the conclusion stays the proposition it is, and the existence part
    # keeps its witness.
    rec = statement(root, "Shape.single")
    inst = rec["binders"][1]
    assert (inst["role"], inst["supplies"]) == ("instance", "data")
    assert props(inst) == [("uniq", "∀ (a : T), a = default")]
    assert [(p["field"], p["declared_in"]) for p in inst["properties"] if p["kind"] == "data"] == \
        [("default", "Inhabited")]
    sub, ex = rec["conclusion"]["logic"]["args"]
    assert sub["leaf"]["text"] == "Subsingleton T"
    assert ex["op"] == "exists" and "properties" not in ex
    # A supplied measure space carries its data and its laws; that it is a probability space is
    # an additional assumption, which states what its field says.
    ms, prob = statement(root, "Shape.probability")["binders"][1:]
    assert (ms["role"], ms["supplies"], prob["role"], prob["supplies"]) == \
        ("instance", "data", "instance", "proposition")
    assert [f for f, _ in props(ms, "data")] == ["measurable", "measure"]
    assert [f for f, _ in props(ms)] == ["measurable_compl", "measure_empty"]
    assert props(prob) == [("measure_univ", "(Shape.MeasureData.measure fun (x : Ω) => True) = 1")]
    # The same field of two objects of one type: each is specialised to its own object, with an
    # identity under that object's, which names it and only it (#73).
    rec = statement(root, "Shape.two_solutions")
    s, t = rec["binders"][1:]
    ss, ts = (next(p for p in o["properties"] if p["field"] == "start") for o in (s, t))
    assert (ss["type"]["text"], ts["type"]["text"]) == ("s.path 0 = d", "t.path 0 = d")
    assert ss["type"]["id"] == s["id"] + "#start:/" and ts["type"]["id"] == t["id"] + "#start:/"
    assert [symbols.term_by_id(rec, p["type"]["id"]) for p in (ss, ts)] == \
        ["s.path 0 = d", "t.path 0 = d"]
    for p in (ss, ts):
        assert all(symbols.term_by_id(rec, i) == t for i, t in texts(p["type"]).items())
    # A conjunction or an equivalence assumed is not a structure to list.
    assert all("properties" not in x for x in statement(root, "Shape.both")["binders"])
    # Inside a negation, the solution is the negated claim's: its properties are on its node.
    neg = statement(root, "Shape.none_large")["conclusion"]["logic"]
    assert neg["op"] == "not" and neg["args"][0]["op"] == "exists"
    assert props(neg["args"][0])[0] == ("start", "s.path 0 = 0")
    # Objects whose type carries no proposition get nothing: a number, a type, a datum.
    assert all("properties" not in x for x in statement(root)["binders"])


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_definitions_expand_at_their_arguments(tmp_path, toolchain):
    """An application of a project definition inside a statement carries the definition at its
    actual arguments (#97), substituted and type-checked by Lean: the body at those arguments,
    with parameters not yet supplied kept and the definition's bound variables renamed apart, or
    the equations that apply, specialised, with their case conditions and theorem names. Two
    applications with different arguments are different expansions."""
    root = build_copy(tmp_path, toolchain)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    rec = {l["name"]: l["record"] for c in view["body"]["claims"] for l in c["links"]}

    jet = rec["Shape.jet_lower"]
    hyp = expansions(jet["binders"][-1]["type"])["Shape.JetBound f S (n + 5) C"]
    concl = expansions(jet["conclusion"])["Shape.JetBound f S (n + 4) C"]
    assert hyp["checked"] and hyp["defined_by"] == "body" and hyp["params"] == []
    assert [(a["name"], a["value"]["text"]) for a in hyp["args"]] == \
        [("f", "f"), ("S", "S"), ("k", "n + 5"), ("C", "C")]
    assert hyp["body"]["text"] == "∀ (j : Nat), j ≤ n + 5 → ∀ (x : Nat), S x → f j x ≤ C"
    assert concl["body"]["text"] == "∀ (j : Nat), j ≤ n + 4 → ∀ (x : Nat), S x → f j x ≤ C"
    assert hyp["id"] != concl["id"] and hyp["at"] != concl["at"]
    # The arguments are the statement's own variables.
    assert ("n", 2) in var_refs(hyp["body"])

    # Implicit and instance arguments keep their order and how they are written; a partial
    # application keeps the parameter it still needs.
    every = rec["Shape.every_below"]
    xs = expansions(every["binders"][-1]["type"])
    part = xs["Shape.AllBelow 7"]
    assert [(a["name"], a["binder"], a["value"]["text"]) for a in part["args"]] == \
        [("α", "implicit", "Nat"), ("", "instance", "instLENat"), ("bound", "explicit", "7"),
         ("n", "implicit", "2")]
    assert [(p["name"], p["type"]["text"]) for p in part["params"]] == [("v", "Fin 2 → Nat")]
    assert part["body"]["text"] == "∀ (i : Fin 2), v i ≤ 7"
    # The definition it is passed to expands with it applied, and that expands in turn.
    outer = xs["Shape.Every (Shape.AllBelow 7) vs"]
    assert outer["body"]["text"] == "∀ (v : Fin 2 → Nat), v ∈ vs → Shape.AllBelow 7 v"
    inner = expansions(outer["body"])["Shape.AllBelow 7 v"]
    assert inner["body"]["text"] == "∀ (i : Fin 2), v i ≤ 7" and inner["params"] == []
    # A bound variable of the definition does not capture the statement's own `i`.
    below = expansions(rec["Shape.below_succ"]["binders"][-1]["type"])["Shape.AllBelow i v"]
    assert below["body"]["text"] == "∀ (i_1 : Fin 3), v i_1 ≤ i"

    # By equations: the one that applies, specialised, with its theorem and case condition.
    steps = expansions(rec["Shape.steps_pos"]["conclusion"])["Shape.steps (k + 3)"]
    assert steps["defined_by"] == "equations" and steps["equations_omitted"] == 0
    [eq] = steps["equations"]
    assert eq["name"] == "Shape.steps.eq_1" and eq["params"] == []
    assert eq["statement"]["text"] == \
        "Shape.steps (k + 3) = if h : k + 3 = 0 then 0 else Shape.steps (k + 3 - 1) + 1"
    # Its left side is the application being expanded; only the right side's applications are.
    assert list(expansions(eq["equation"])) == ["Shape.steps (k + 3 - 1)"]
    pick = expansions(rec["Shape.pick_at"]["conclusion"])["Shape.pick (k + 1) 0"]
    [eq] = pick["equations"]
    assert eq["name"] == "Shape.pick.eq_2"
    assert [(p["proposition"], p["type"]["text"]) for p in eq["params"]] == \
        [(True, "k + 1 = 0 → False")]
    assert eq["equation"]["text"] == "Shape.pick (k + 1) 0 = 1"
    assert pick["equations_not_applying"] == ["Shape.pick.eq_1", "Shape.pick.eq_3"]
