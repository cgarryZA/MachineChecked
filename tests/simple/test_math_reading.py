"""Statements read as mathematics (#70), on the synthetic project tests/fixtures/structure and the
toy paper: the probe reads each printed expression as the notions Lean elaborated (`math`), each
node at the identity of the sub-term it renders, and the engine arranges the statement into rows
with their roles and origins (`readable`). Display only: the fingerprints are those of the
statement, not of its reading.

`Shape.Analysis` declares stand-ins under Mathlib's names (real numbers, measures, almost
everywhere, `Lp`, Euclidean spaces, linear isometries), with the explicit arguments Mathlib's
have, so that the probe reads them as it reads Mathlib's."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, build, needs_lean, needs_tex
from prooflens import simple, symbols
from prooflens.readable import readable
from prooflens.simple import build_view

SRC = ROOT / "tests" / "fixtures" / "structure"


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


def walk(m):
    """Every node of a `math` tree."""
    if isinstance(m, dict):
        if "k" in m:
            yield m
        for v in m.values():
            yield from walk(v)
    elif isinstance(m, list):
        for v in m:
            yield from walk(v)


def printed(st):
    """Every printed expression of a statement whose identity a row may name: binders' types,
    leaves and the properties objects' types carry."""
    out = []
    for n in symbols.nodes(st):
        for k in ("type", "leaf"):
            if isinstance(n.get(k), dict):
                out.append(n[k])
        out += [p["type"] for p in n.get("properties") or [] if isinstance(p.get("type"), dict)]
    return out


def by_id(st):
    return {pp["id"]: pp for pp in printed(st) if pp.get("id")}


def objects(rows):
    return [(r["quantifier"], [o["name"] for o in r["objects"]], r["role"])
            for r in rows if r["k"] == "objects"]


def var(n, name):
    return n["k"] == "var" and n["name"] == name


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_statements_read_as_mathematics(tmp_path, toolchain):
    root = build_copy(tmp_path, toolchain)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    links = {l["name"]: l for c in view["body"]["claims"] for l in c["links"]}
    st = {n: simple._link_view(l)["statement"] for n, l in links.items()}

    # One constant chosen once, above the "for every"; and one chosen after each n.
    once, each = st["Shape.bound_once"]["readable"], st["Shape.bound_each"]["readable"]
    assert objects(once["rows"]) == [("exists", ["C"], "output"), ("forall", ["n"], "input")]
    assert objects(each["rows"]) == [("forall", ["n"], "input"), ("exists", ["C"], "output")]
    assert [r["after"] for r in each["rows"] if r["k"] == "objects"] == [[], [0]]
    c = by_id(st["Shape.bound_once"])[once["rows"][0]["at"]]
    assert c["math"]["k"] == "type" and c["math"]["name"] == "nat", "C is a natural number"

    # The isometry: every condition, the typed isometry, a representative of each class and its
    # uniqueness almost everywhere, each for the product measure.
    s = st["Shape.isometry_classes"]
    rows = s["readable"]["rows"]
    pp = by_id(s)
    assert [(r["k"], r["role"]) for r in rows] == [
        ("objects", "input"), ("structure", "input"), ("structure", "input"),
        ("objects", "input"), ("objects", "input"), ("condition", "assumption"),
        ("condition", "assumption"), ("objects", "input"), ("objects", "input"),
        ("and", "output")]
    assert objects(rows)[0] == ("forall", ["Ω₁", "Ω₂"], "input")
    assert pp[rows[0]["at"]]["math"]["k"] == "universe"
    # A σ-algebra on each space is supplied structure; σ-finiteness is assumed in addition.
    assert [(r["origin"], r["on"]) for r in rows[1:3]] == [("supplied", [0]), ("supplied", [1])]
    assert pp[rows[1]["at"]]["math"]["k"] == "sigma_algebra"
    assert [(r["origin"], r["about"]) for r in rows[5:7]] == [("assumed", [4]), ("assumed", [5])]
    sf = pp[rows[5]["at"]]["math"]
    assert sf["k"] == "sigma_finite" and var(sf["measure"], "μ")
    assert [x["field"] for x in rows[5]["states"]] == ["out'"]
    # The measure's type carries its own properties, included in that type.
    mu = rows[3]
    assert pp[mu["at"]]["math"]["k"] == "measure_type"
    assert [(p["field"], p["origin"]) for p in mu["properties"]] == [("empty", "type"),
                                                                    ("mono", "type")]
    # Φ : L²(μ.prod ν) ≃ₗᵢ[ℝ] ℝ³, with its scalars, domain and codomain.
    phi = pp[rows[7]["at"]]["math"]
    assert phi["k"] == "isometry_equiv" and phi["field"]["name"] == "real"
    lp, eu = phi["domain"], phi["codomain"]
    assert (lp["k"], lp["codomain"]["name"], lp["exponent"]["value"]) == ("lp", "real", "2")
    assert lp["exponent"]["in"]["name"] == "ennreal"
    assert lp["measure"]["k"] == "prod_measure" and var(lp["measure"]["left"], "μ") and \
        var(lp["measure"]["right"], "ν")
    assert (eu["k"], eu["field"]["name"], eu["index"]["k"], eu["index"]["n"]["value"]) == \
        ("euclidean", "real", "fin", "3")
    # The class F has a representative g, produced inside its part, equal to F a.e. for μ.prod ν.
    _, rep, uniq = rows[9]["parts"]
    assert objects(rep) == [("exists", ["g"], "output")] and rep[0]["scope"] == "produced"
    ae = pp[rep[1]["at"]]["math"]
    assert ae["k"] == "ae" and ae["measure"]["k"] == "prod_measure"
    lhs, rhs = ae["body"]["args"]
    assert ae["body"]["op"] == "eq" and var(lhs["fn"], "g")
    assert rhs["k"] == "app" and rhs["fn"]["k"] == "rep" and var(rhs["fn"]["of"], "F"), \
        "F applied to a point is a representative of the class F"
    # Unique almost everywhere: any two such g, h agree a.e., for the same measure.
    assert objects(uniq) == [("forall", ["g", "h"], "input")]
    [imp] = [r for r in uniq if r["k"] == "implies"]
    first = pp[imp["parts"][0][0]["at"]]["math"]
    assert (first["k"], first["op"], first["args"][1]["k"]) == ("rel", "ae_eq", "rep")
    assert first["measure"]["k"] == "prod_measure"
    last = pp[imp["parts"][1][0]["parts"][1][0]["at"]]["math"]
    assert last["op"] == "ae_eq" and [a["name"] for a in last["args"]] == ["g", "h"]

    # An alternative of two witnesses both named x, a number taken as a real number, and an
    # assumption quantified over m, with its own rows.
    s = st["Shape.alternatives"]
    rows, pp = s["readable"]["rows"], by_id(s)
    h = next(r for r in rows if r["k"] == "condition")
    assert (h["name"], h["about"], h["joint"]) == ("h", [0, 1], True)
    assert objects(h["rows"]) == [("forall", ["m"], "assumption")]
    hm = pp[h["at"]]["math"]
    assert hm["k"] == "forall" and hm["body"]["k"] == "implies"
    up = hm["body"]["args"][1]
    assert up["op"] == "le" and up["in"]["name"] == "real"
    coe = up["args"][0]
    assert (coe["k"], coe["from"]["name"], coe["to"]["name"], coe["of"]["k"]) == \
        ("coe", "nat", "real", "bound")
    [alt] = [r for r in rows if r["k"] == "or"]
    left, right = alt["parts"]
    assert [p[0]["objects"][0]["name"] for p in (left, right)] == ["x", "x"]
    assert left[0]["objects"][0]["var"] != right[0]["objects"][0]["var"]
    assert [pp[p[0]["at"]]["math"]["name"] for p in (left, right)] == ["real", "nat"]

    # Given, assumed and produced solutions: the same type, three readings.
    s = st["Shape.supplied"]["readable"]["rows"]
    sol = next(r for r in s if r["k"] == "objects" and r["objects"][0]["name"] == "s")
    assert sol["role"] == "input" and {p["origin"] for p in sol["properties"]} == {"type"}
    p = st["Shape.produced"]["readable"]["rows"]
    sol = next(r for r in p if r["k"] == "objects" and r["objects"][0]["name"] == "s")
    assert (sol["role"], sol["quantifier"]) == ("output", "exists")
    assert {p["origin"] for p in sol["properties"]} == {"established"}
    a = st["Shape.assumed"]["readable"]["rows"]
    h = a[0]
    assert h["k"] == "condition" and objects(h["rows"]) == [("forall", ["d"], "assumption")]
    [imp] = [r for r in h["rows"] if r["k"] == "implies"]
    inner = imp["parts"][1]
    assert objects(inner) == [("exists", ["s"], "assumption")]
    assert {p["origin"] for p in inner[0]["properties"]} == {"type"}
    assert objects(a[1:]) == [("exists", ["s"], "output")]

    # Notation the probe does not know stays exact Lean: `G →[Nat] H` is the project's own.
    s = st["Shape.one_map"]
    phi = next(r for r in s["readable"]["rows"] if r["k"] == "objects" and r["quantifier"] ==
               "exists")
    m = by_id(s)[phi["at"]]["math"]
    assert m["k"] == "lean" and m["text"] == "G →[Nat] H"

    # Every row names a printed expression of the statement, by an identity a symbol link or
    # an alignment resolves; every node that is an occurrence of a variable is that variable's
    # occurrence in the printed text, and each expression's reading stands at its identity.
    for name, s in st.items():
        if not s or not s.get("readable"):
            continue
        pp = by_id(s)

        def rows_of(rs):
            for r in rs:
                yield r
                for p in r.get("parts") or []:
                    yield from rows_of(p)
                yield from rows_of(r.get("rows") or [])
        for r in rows_of(s["readable"]["rows"]):
            if r.get("at"):
                assert r["at"] in pp, (name, r)
                assert symbols.term_by_id(s, r["at"]) is not None, (name, r)
        for x in pp.values():
            assert "math" in x, (name, x["text"])
            occ = {g["at"]: g for g in x["segments"] if "at" in g}
            terms = {t["id"] for t in x.get("terms") or []} | {x["id"]}
            for n in walk(x["math"]):
                assert n["k"] != "lean" or "error" not in n, (name, n)
                if n["k"] == "var" and n.get("id") in occ:
                    assert occ[n["id"]]["var"] == n["var"], (name, n)
            assert x["math"].get("id") in terms, (name, x["text"])

    # The readable statement is display only: the statement's identity is its fingerprint.
    assert all(s["readable"]["schema"] == "prooflens/readable@1" for s in st.values()
               if s and s.get("readable"))


@needs_lean
@needs_tex
def test_toy_statements_read_as_mathematics(toy):
    """Even addition shows its natural witness from the definition of evenness at each argument,
    one definition for the three applications; the bound keeps its constant above its "for
    every"; the published claim file carries the rows."""
    index, body, cfg = build(toy)
    c = next(c for c in index["claims"] if c["id"] == "T:thm:even-add")
    chunk = json.loads((cfg.out_dir / "site/data/claims" / c["file"]).read_text())
    st = chunk["clauses"][0]["statement"]
    r = st["readable"]
    assert [(x["k"], x["role"]) for x in r["rows"]] == [
        ("objects", "input"), ("condition", "assumption"), ("condition", "assumption"),
        ("claim", "output")]
    assert [o["name"] for o in r["rows"][0]["objects"]] == ["a", "b"]
    [d] = r["definitions"]
    assert d["name"] == "Toy.IsEven" and len(d["applications"]) == 3
    pp = by_id(st)
    h1 = pp[r["rows"][1]["at"]]
    assert h1["math"]["k"] == "apply" and h1["math"]["name"] == "Toy.IsEven"
    assert var(h1["math"]["args"][0], "a")
    # IsEven a, at its argument: ∃ k : ℕ, a = 2 * k.
    x = body["lean"]["specs"]["Toy.PaperSpec.thm_even_add"]
    raw = by_id(x)[r["rows"][1]["at"]]
    [ex] = raw["expansions"]
    assert ex["at"] == h1["math"]["id"] == r["rows"][1]["definitions"][0]["at"]
    m = ex["body"]["math"]
    assert (m["k"], m["name"], m["type"]["name"]) == ("exists", "k", "nat")
    assert m["body"]["op"] == "eq" and var(m["body"]["args"][0], "a")
    two = m["body"]["args"][1]
    assert (two["op"], two["args"][0]["value"], two["args"][1]["k"]) == ("mul", "2", "bound")
    # The definition itself, once: n is even when n = 2 * k for some natural k.
    even = body["lean"]["decls"]["Toy.IsEven"]
    assert even["body"]["math"]["k"] == "exists" and even["params"][0]["type"]["math"]["name"] == "nat"
    # ∃ C, ∀ n: C is chosen once; the readable rows keep that order.
    b = next(c for c in index["claims"] if c["id"] == "T:thm:bound")
    chunk = json.loads((cfg.out_dir / "site/data/claims" / b["file"]).read_text())
    rows = chunk["clauses"][0]["statement"]["readable"]["rows"]
    assert objects(rows) == [("exists", ["C"], "output"), ("forall", ["n"], "input")]
    assert rows[-1]["definitions"][0]["name"] == "Toy.triangle"
