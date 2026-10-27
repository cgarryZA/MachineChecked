"""The statement structure the probe exports for display (#46, #67), on the synthetic project
tests/fixtures/structure: the whole proposition as one tree, from which the binders that open it
and its conclusion are read; each occurrence of a statement's variable names the binder that
introduced it. Display only: the binders, their roles and the fingerprints are what they were."""

import importlib.util
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import manifest as mf
from prooflens import objects, simple, symbols
from prooflens.simple import build_view

SRC = ROOT / "tests" / "fixtures" / "structure"


def statement(root, name="Shape.layout"):
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    return next(l["record"] for c in view["body"]["claims"] for l in c["links"]
                if l["name"] == name)


def shape(rec):
    """The part of a statement's tree under the binders that open it."""
    n = rec["tree"]
    for _ in rec["binders"]:
        [n] = n["args"]
    return n


def spine(rec):
    """The binders that open a statement, as nodes of its tree, each with its role."""
    out, n = [], rec["tree"]
    for _ in rec["binders"]:
        out.append({**n, "role": n["op"]})
        [n] = n["args"]
    return out


def nodes(n):
    """Every node of a tree, hypotheses' own trees included."""
    out, stack = [], [n]
    while stack:
        m = stack.pop()
        if m:
            out.append(m)
            stack += [m.get("logic"), *m.get("args", [])]
    return out


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
    # The binders that open the statement are the first nodes of its tree, in order, and the
    # conclusion's shape is the part under them.
    assert [(n["role"], n["var"], n["id"], n["type"]) for n in spine(rec)] == \
        [(x["role"], i, x["id"], x["type"]) for i, x in enumerate(b)]
    assert "logic" not in rec["conclusion"], "the shape is in the tree, once"
    logic = shape(rec)
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
    left, right = shape(rec)["args"]
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
    neg, alt = shape(rec)["args"]
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
        for n in nodes(rec["tree"]):
            for pp in (n.get("leaf"), n.get("type")):
                if pp:
                    tree.update(texts(pp))
        assert tree and all(exact.get(i) == t for i, t in tree.items()), (name, tree, exact)
    left, right = shape(statement(root, "Shape.witnesses"))["args"]
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
def test_each_binder_stands_in_its_scope(tmp_path, toolchain):
    """The whole proposition is one tree (#67): each binder, whether it opens the statement or
    stands inside its conclusion or one of its hypotheses, is a node with where it stands
    (`scope`, decided by the nearest negation, alternative, equivalence, premise or hypothesis
    around it), the connectives around it (`within`) and the objects it may depend on
    (`after`). Each variable has a number of its own, so two of the same name resolve to their
    own occurrences, and every printed part has the identity it has in the exact Lean."""
    root = build_copy(tmp_path, toolchain)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    rec = {l["name"]: l["record"] for c in view["body"]["claims"] for l in c["links"]}

    # ∀ x, ∃ y, ∀ z: given x, the statement establishes y, then the bound holds for every z.
    alt = rec["Shape.alternating"]
    assert [(n["role"], n["name"], n["scope"], n["after"]) for n in spine(alt)] == \
        [("forall", "x", "given", []), ("exists", "y", "produced", [0]),
         ("forall", "z", "given", [0, 1])]
    assert var_refs(shape(alt)["leaf"]) == [("x", 0), ("z", 2), ("y", 1), ("z", 2)]

    # An assumption containing a conditional existence claim: its x and y belong to it, numbered
    # apart from the statement's own y, which the statement establishes.
    cond = rec["Shape.conditional"]
    sp = spine(cond)
    assert [(n["role"], n["name"]) for n in sp] == [
        ("forall", "A"), ("forall", "B"), ("hypothesis", "h"), ("forall", "a"),
        ("hypothesis", "ha"), ("exists", "y")]
    y = sp[5]
    assert (y["scope"], y["var"], y["after"]) == ("produced", 5, [0, 1, 3])
    assert "logic" not in sp[4], "a hypothesis without a shape has no tree of its own"
    every = sp[2]["logic"]
    assert (every["op"], every["name"], every["scope"], every["within"], every["after"]) == \
        ("forall", "x", "assumed", ["assume"], [0, 1])
    [imp] = every["args"]
    assert imp["op"] == "implies" and imp["args"][0]["leaf"]["text"] == "A x"
    inner = imp["args"][1]
    assert (inner["op"], inner["name"], inner["scope"], inner["within"], inner["after"]) == \
        ("exists", "y", "assumed", ["assume", "then"], [0, 1, every["var"]])
    assert (every["var"], inner["var"]) == (6, 7), "numbered after the statement's own variables"
    assert inner["id"] != y["id"] and inner["type"]["id"] != y["type"]["id"]
    assert var_refs(inner["args"][0]["leaf"]) == [("B", 1), ("x", 6), ("y", 7)]
    assert var_refs(shape(cond)["leaf"]) == [("B", 1), ("a", 3), ("y", 5)]

    # Established under a premise, inside one side of an equivalence, inside one alternative.
    pre = rec["Shape.premised"]
    imp, rest = shape(pre)["args"]
    iff, alt2 = rest["args"]
    under = imp["args"][1]
    assert (imp["op"], imp["args"][0]["leaf"]["text"]) == ("implies", "P")
    assert (under["op"], under["name"], under["scope"], under["within"]) == \
        ("exists", "x", "produced", ["and", "then"])
    side = iff["args"][1]
    assert (iff["op"], side["op"], side["scope"], side["within"]) == \
        ("iff", "exists", "equivalent", ["and", "and", "iff"])
    branch = alt2["args"][0]
    assert (alt2["op"], branch["op"], branch["name"], branch["scope"]) == \
        ("or", "exists", "x", "alternative")
    assert under["var"] != branch["var"]

    # One witness whose type names its domain, codomain and scalars, with both properties; each
    # assumption's Φ is a variable of its own.
    one = rec["Shape.one_map"]
    sp = spine(one)
    phi = sp[-1]
    assert (phi["role"], phi["name"], phi["type"]["text"], phi["scope"], phi["var"]) == \
        ("exists", "Φ", "G →[Nat] H", "produced", 7)
    a, b = shape(one)["args"]
    assert var_refs(a["leaf"]) == [("A", 3), ("Φ", 7)]
    assert var_refs(b["leaf"]) == [("B", 4), ("Φ", 7)]
    assumed = [sp[i]["logic"] for i in (5, 6)]
    assert [(n["op"], n["name"], n["scope"]) for n in assumed] == [("forall", "Φ", "assumed")] * 2
    assert len({phi["var"], *(n["var"] for n in assumed)}) == 3

    # Every part of every tree, the hypotheses' own trees included, has the text its identity
    # has in the exact Lean (but for the parentheses the exact Lean puts around an argument; a
    # type the exact Lean prints once for several binders, `(A B : T)`, is there under the
    # first), and the numbers of the variables are distinct.
    for name in ("Shape.alternating", "Shape.conditional", "Shape.premised", "Shape.one_map",
                 "Shape.assumed"):
        r = rec[name]
        exact, leaves, types, numbers = texts(r["exact"]), {}, {}, []
        for n in nodes(r["tree"]):
            if n.get("leaf"):
                leaves.update(texts(n["leaf"]))
            if n.get("type"):
                types.update(texts(n["type"]))
            if n.get("op") in ("forall", "exists", "hypothesis", "instance"):
                numbers.append(n["var"])
        assert leaves and all(bare(exact.get(i, "")) == bare(t) for i, t in leaves.items()), \
            (name, leaves, exact)
        assert all(bare(exact[i]) == bare(t) for i, t in types.items() if i in exact), \
            (name, types, exact)
        assert len(numbers) == len(set(numbers)), (name, numbers)


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

    # More equations than a record lists: Lean derives all seventy; the record the reader loads
    # keeps the first 64 and refers to a page of its own with the others, which it fetches.
    v = statement(root, "Shape.Digit.val")["decl"]
    names = [f"Shape.Digit.val.eq_{i}" for i in range(1, 71)]
    assert v["defined_by"] == "equations" and v["equations_omitted"] == 0
    assert [e["name"] for e in v["equations"]] == names == v["equation_names"]
    parts = {}
    kept = mf.split_expansions(v, parts)
    assert [e["name"] for e in kept["equations"]] == names[:64]
    [page] = kept["equations_more"]
    assert page["name"] == names[64] and parts[page["key"]] == \
        {"definition": "Shape.Digit.val", "equations": v["equations"][64:]}


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
    b = spine(statement(root, "Shape.supplied"))
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
    assert "properties" not in h and "logic" not in h
    # Properties are on the nodes of the tree, not repeated in the binders.
    assert all("properties" not in x for x in statement(root, "Shape.supplied")["binders"])
    # An assumed existence: the solution and its properties stay inside the assumption.
    rec = statement(root, "Shape.assumed")
    h = spine(rec)[0]
    assert h["role"] == "hypothesis" and "properties" not in h
    [obj] = [n for n in nodes(h["logic"]) if n.get("op") == "exists"]
    assert (obj["op"], obj["name"], obj["scope"], obj["within"]) == \
        ("exists", "s", "assumed", ["assume", "then"])
    assert props(obj)[0] == ("start", "s.path 0 = d")
    out = spine(rec)[1]
    assert (out["role"], out["type"]["text"]) == ("exists", "Shape.Solution 0")
    assert props(out)[0] == ("start", "s.path 0 = 0")
    # An established existence: the solution is a witness, under the condition on d.
    b = spine(statement(root, "Shape.produced"))
    assert [(x["role"], x["name"], x["scope"]) for x in b] == \
        [("forall", "d", "given"), ("hypothesis", "h1", "given"), ("exists", "s", "produced")]
    assert props(b[2])[1] == ("le_bound", "∀ (n : Nat), s.path n ≤ s.bound")
    # A subtype carries its predicate.
    [p] = spine(statement(root, "Shape.positive"))
    assert props(p) == [("property", "0 < p.val")] and props(p, "data") == [("val", "Nat")]
    # A class instance is an input carrying its law and its data (inherited from Inhabited);
    # `Subsingleton T` in the conclusion stays the proposition it is, and the existence part
    # keeps its witness.
    rec = statement(root, "Shape.single")
    inst = spine(rec)[1]
    assert (inst["role"], inst["supplies"]) == ("instance", "data")
    assert props(inst) == [("uniq", "∀ (a : T), a = default")]
    assert [(p["field"], p["declared_in"]) for p in inst["properties"] if p["kind"] == "data"] == \
        [("default", "Inhabited")]
    sub, ex = shape(rec)["args"]
    assert sub["leaf"]["text"] == "Subsingleton T"
    assert ex["op"] == "exists" and "properties" not in ex
    # A supplied measure space carries its data and its laws; that it is a probability space is
    # an additional assumption, which states what its field says.
    ms, prob = spine(statement(root, "Shape.probability"))[1:]
    assert (ms["role"], ms["supplies"], prob["role"], prob["supplies"]) == \
        ("instance", "data", "instance", "proposition")
    assert [f for f, _ in props(ms, "data")] == ["measurable", "measure"]
    assert [f for f, _ in props(ms)] == ["measurable_compl", "measure_empty"]
    assert props(prob) == [("measure_univ", "(Shape.MeasureData.measure fun (x : Ω) => True) = 1")]
    # The same field of two objects of one type: each is specialised to its own object, with an
    # identity under that object's, which names it and only it (#73).
    rec = statement(root, "Shape.two_solutions")
    s, t = spine(rec)[1:]
    ss, ts = (next(p for p in o["properties"] if p["field"] == "start") for o in (s, t))
    assert (ss["type"]["text"], ts["type"]["text"]) == ("s.path 0 = d", "t.path 0 = d")
    assert ss["type"]["id"] == s["id"] + "#start:/" and ts["type"]["id"] == t["id"] + "#start:/"
    assert [symbols.term_by_id(rec, p["type"]["id"]) for p in (ss, ts)] == \
        ["s.path 0 = d", "t.path 0 = d"]
    for p in (ss, ts):
        assert all(symbols.term_by_id(rec, i) == t for i, t in texts(p["type"]).items())
    # A conjunction or an equivalence assumed is not a structure to list.
    assert all("properties" not in x for x in spine(statement(root, "Shape.both")))
    # Inside a negation, the solution is the negated claim's: its properties are on its node.
    neg = shape(statement(root, "Shape.none_large"))
    assert neg["op"] == "not" and neg["args"][0]["op"] == "exists"
    assert props(neg["args"][0])[0] == ("start", "s.path 0 = 0")
    # Objects whose type carries no proposition get nothing: a number, a type, a datum.
    assert all("properties" not in x for x in spine(statement(root)))

    # Each property says why it holds of its object (`basis`), which of the statement's
    # variables its statement mentions (`depends`) and the parent projections it comes through
    # (`via`).
    s = next(x for x in spine(statement(root, "Shape.supplied")) if x["name"] == "s")
    assert {p["basis"] for p in s["properties"]} == {"type"}
    start = next(p for p in s["properties"] if p["field"] == "start")
    assert (start["via"], start["depends"]) == (["Shape.Solution.toBase"], [0, 1])
    prob = spine(statement(root, "Shape.probability"))[2]
    assert [p["basis"] for p in prob["properties"]] == ["premise"]
    # An inherited field with parameters and nested quantifiers is specialised to the object and
    # keeps every variable it mentions.
    s = spine(statement(root, "Shape.scaled"))[2]
    scale = next(p for p in s["properties"] if p["field"] == "scale")
    assert scale["type"]["text"] == \
        "∀ (k : Nat), ∃ (m : Nat), ∀ (n : Nat), k ≤ n → s.g n ≤ m * w k + d"
    assert (scale["declared_in"], scale["inherited"], scale["via"], scale["depends"]) == \
        ("Shape.Scaled", True, ["Shape.ScaledStart.toScaled"], [0, 1, 2])
    assert {("d", 0), ("w", 1), ("s", 2)} <= set(var_refs(scale["type"]))
    # A field inherited along two paths is one field, from the structure that declares it; a
    # parent whose fields are copied (it shares one with the first) is still their origin.
    [b] = spine(statement(root, "Shape.both_pos"))
    assert [p["field"] for p in b["properties"]] == ["x0", "pos", "l", "r", "r_le"]
    by = {p["field"]: p for p in b["properties"]}
    assert (by["pos"]["declared_in"], by["pos"]["via"]) == \
        ("Shape.Anchor", ["Shape.Both.toLeft", "Shape.Left.toAnchor"])
    assert (by["r_le"]["declared_in"], by["r_le"]["projection"]) == \
        ("Shape.Right", "Shape.Right.r_le")

    # A structure that extends the abstract one shows exactly the fields it adds, each stated
    # of an object `self`; the abstract one has only its own.
    con = statement(root, "Shape.Concrete")["decl"]
    v = objects.structure_view(con)
    assert v["declares"] == ["N", "support", "p", "periodic"]
    assert v["inherits"] == [{"parent": "Shape.Profile", "fields": ["f", "C", "bound"]}]
    fields = {f["field"]: f for f in v["fields"]}
    assert (fields["support"]["kind"], fields["support"]["type"]["text"],
            fields["support"]["type"]["id"]) == \
        ("proposition", "∀ (n : Nat), self.N ≤ n → self.f n = 0", "self#support:/")
    assert fields["N"]["kind"] == "data"
    prof = objects.structure_view(statement(root, "Shape.Profile")["decl"])
    assert (prof["declares"], prof["inherits"], prof["parents"]) == (["f", "C", "bound"], [], [])
    # A construction's value carries those fields, established by the definition; a helper that
    # accepts the structure has them as properties of its input, apart from its hypothesis.
    build = statement(root, "Shape.build")["decl"]
    sup = next(p for p in build["result_properties"] if p["field"] == "support")
    assert (sup["basis"], sup["term"], sup["type"]["text"]) == \
        ("definition", "(Shape.build N).support",
         "∀ (n : Nat), (Shape.build N).N ≤ n → (Shape.build N).f n = 0")
    assert ("N", 0) in var_refs(sup["type"])
    # A projection constructs nothing: the parent projection's value carries its argument's
    # fields, which it does not establish.
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    proj = view["body"]["decls"]["Shape.Concrete.toProfile"]
    assert "result_properties" not in proj and "result_properties_error" not in proj
    c, n = objects.objects(statement(root, "Shape.vanishes"), "Shape.vanishes")
    assert (c["name"], c["position"]) == ("c", "given")
    assert [(p["basis"], p.get("field")) for p in c["properties"]] == [
        ("type", "bound"), ("type", "support"), ("type", "periodic"), ("premise", None),
        ("conclusion", None)]
    assert c["properties"][3]["statement"] == "c.N ≤ n"

    # The three statement forms keep their roles, by where the solution stands.
    [_, s] = objects.objects(statement(root, "Shape.supplied"), "Shape.supplied")
    assert (s["position"], [p["basis"] for p in s["properties"]]) == \
        ("given", ["type", "type", "premise", "conclusion"])
    objs = objects.objects(statement(root, "Shape.assumed"), "Shape.assumed")
    assert [(o["name"], o["position"]) for o in objs] == \
        [("s", "produced"), ("d", "assumed"), ("s", "assumed")]
    assert [p["basis"] for p in objs[2]["properties"]] == ["type", "type", "premise"]
    produced = objects.objects(statement(root, "Shape.produced"), "Shape.produced")
    assert [(o["name"], o["position"]) for o in produced] == [("d", "given"), ("s", "produced")]
    assert [(p["basis"], p.get("definition")) for p in produced[1]["properties"]
            if p["basis"] != "type"] == [("conclusion", None), ("definition", "Shape.Good")]
    # The measure space: structure supplied on Ω, and an additional assumption about it.
    omega = objects.objects(statement(root, "Shape.probability"), "Shape.probability")[0]
    assert [i["type"] for i in omega["instances"]] == ["Shape.MeasureData Ω"]
    assert [(p["basis"], p["statement"]) for p in omega["properties"]][0] == \
        ("premise", "Shape.IsProbability Ω")


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_definitions_expand_at_their_arguments(tmp_path, toolchain, monkeypatch):
    """An application of a project definition inside a statement carries the definition at its
    actual arguments (#97), substituted and type-checked by Lean: the body at those arguments,
    with parameters not yet supplied kept and the definition's bound variables renamed apart, or
    the equations that apply, specialised, with their case conditions and theorem names. Two
    applications with different arguments are different expansions. What Lean generates is
    neither expanded nor suggested."""
    root = build_copy(tmp_path, toolchain)
    # Every candidate the suggestions for the definition of a digit's value weigh, not only the
    # three shown, and the index they are drawn from.
    considered = {}
    suggest = simple.suggest

    def every(claim, index, limit=3, ctx=None):
        if claim["id"] == "P:def:digit":
            considered["index"] = [d["name"] for d in index]
            considered["offered"] = [s["name"] for s in suggest(claim, index, len(index), ctx)]
        return suggest(claim, index, limit, ctx)

    monkeypatch.setattr(simple, "suggest", every)
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
    # Every equation is compared with the application, not only those a record lists: here the
    # seventieth applies.
    [val] = expansions(rec["Shape.last_digit"]["conclusion"]).values()
    assert val["name"] == "Shape.Digit.val" and val["equations_omitted"] == 0
    [eq] = val["equations"]
    assert eq["name"] == "Shape.Digit.val.eq_70" and eq["params"] == []
    assert len(val["equations_not_applying"]) == 69

    # A definition Lean generates is not expanded (#412): the constructor index `ctorIdx` of a
    # hypothesis has no expansion, and the project's `Digit.val` beside it has one.
    idx = rec["Shape.last_index"]
    hyp = idx["binders"][-1]
    assert hyp["type"]["text"] == "t.ctorIdx = 69" and "expansions" not in hyp["type"]
    assert [x["name"] for x in expansions(idx["conclusion"]).values()] == ["Shape.Digit.val"]

    # Nor is one suggested (#411). Under `Digit` the index holds the project's `Digit.val`, the
    # definition's link, and what Lean generates: the recursors, the constructor index, each
    # constructor's eliminator (`Digit.d69.elim`) and size lemma. None of those is offered for
    # the definition, among all its candidates, and the content index that serves suggestions
    # and the reader's search holds none of them.
    digit = next(c for c in view["body"]["claims"] if c["id"] == "P:def:digit")
    assert [l["name"] for l in digit["links"]] == ["Shape.Digit.val"]
    made = {n for n in considered["index"] if n.startswith("Shape.Digit.")} - {"Shape.Digit.val"}
    assert {"Shape.Digit.casesOn", "Shape.Digit.ctorIdx", "Shape.Digit.d69.elim"} <= made, made
    assert considered["offered"] and not made & set(considered["offered"]), considered["offered"]
    assert not made & {s["name"] for s in digit["suggestions"]}
    assert not made & {d["name"] for d in view["retrieval"].docs}

    # A private definition is the project's own (#426). Lean stores it under a name of its own
    # (`_private.<module>.0.<name>`) and prints it with a mark (`✝`) outside its module. It is
    # expanded where a statement applies it, by its body or by its equations; its record says
    # what it is; the declaration that uses it lists it; and the statement's closure, whose
    # definitions the reviews cover, holds it. What Lean generates for it is not expanded.
    hidden = "_private.Shape.Expand.0.Shape."
    mh = rec["Shape.margin_half"]
    assert mh["conclusion"]["text"] == "Shape.half✝ (k + 2) < Shape.margin✝ k + k"
    xs = {x["name"]: x for x in mh["conclusion"]["expansions"]}
    assert sorted(xs) == [hidden + "half", hidden + "margin"]
    assert xs[hidden + "margin"]["defined_by"] == "body"
    assert xs[hidden + "margin"]["body"]["text"] == "k + 2"
    [eq] = xs[hidden + "half"]["equations"]
    assert eq["name"] == hidden + "half.eq_3"
    assert xs[hidden + "half"]["equations_not_applying"] == [hidden + "half.eq_1", hidden + "half.eq_2"]
    assert sorted(mh["decl"]["uses"]) == [hidden + "half", hidden + "margin"]
    assert {hidden + "half", hidden + "margin", hidden + "half.match_1"} <= set(mh["closure"])
    decls = view["body"]["decls"]
    assert decls[hidden + "margin"]["defined_by"] == "body"
    assert decls[hidden + "half"]["defined_by"] == "equations"
    assert "defined_by" not in decls[hidden + "half.match_1"]


def make_structure():
    """`web/tests/fixtures/make_structure.py`, which makes the reader's copy of this fixture's
    data."""
    spec = importlib.util.spec_from_file_location(
        "make_structure", ROOT / "web" / "tests" / "fixtures" / "make_structure.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@needs_lean
@needs_tex
def test_the_readers_copy_of_the_data_is_current(tmp_path):
    """The reader's browser tests read this fixture's site data from a committed copy
    (`web/tests/fixtures/structure/data`). It is the data `make_structure.py` makes from the
    fixture now, apart from the time of the build (#427): a change to the fixture, or to what the
    engine writes for it, fails here until the copy is made again."""
    make = make_structure()
    work = make.copy_fixture(tmp_path / "structure")
    subprocess.run(["lake", "build"], cwd=work, check=True, capture_output=True, timeout=900)
    made = tmp_path / "data"
    make.write_data(work, made)
    assert make.differences(made, make.OUT) == [], \
        "run `python3 web/tests/fixtures/make_structure.py` and commit web/tests/fixtures/structure"
