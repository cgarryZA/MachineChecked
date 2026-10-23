"""Two papers mapped to separate libraries: each paper's build indexes its own (#130).

Synthetic: the `Alpha` library formalises the paper "Alpha sums" and the `Beta` library the
paper "Beta products", as formalization.yaml maps them. `Beta.Main` declares `Beta.mul_swap`
and `Beta.linked_from_alpha`; `Beta.Other`, which `Beta.Main` does not import, declares the
structure `Beta.Pt` (whose projection `Beta.Pt.x` Lean generates). Both libraries declare
`Shared.dup`, so they cannot be loaded together. `Alpha.Main` states a theorem `Foo.bar`, and
`Beta.Shape` declares `structure Foo where bar : Nat`, whose projection is `Foo.bar` too; both
libraries declare `structure Cell … deriving Repr`, so Lean names an instance `instReprCell` in
each. A build of one paper must not index the other paper's library, must say so, must still
check a link into that library, must find a name both libraries hold in both (a projection or
an instance Lean generates included), and a search or an inspection must still reach it.
"""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import simple
from prooflens.simple import build_view, save_link
from prooflens.util import content_id

ALPHA = """namespace Alpha
/-- Addition of naturals commutes. -/
theorem add_swap (a b : Nat) : a + b = b + a := Nat.add_comm a b
end Alpha

namespace Shared
theorem dup : 2 + 2 = 4 := rfl
end Shared

/-- Stated under a name another library gives to a projection. -/
theorem Foo.bar : 3 = 3 := rfl
"""

CELL = """structure Cell where
  n : Nat
deriving Repr
"""

BETA_MAIN = """namespace Beta
/-- Multiplication of naturals is commutative. -/
theorem mul_swap (a b : Nat) : a * b = b * a := Nat.mul_comm a b

theorem linked_from_alpha : 1 + 1 = 2 := rfl
end Beta

namespace Shared
theorem dup : 2 + 2 = 4 := rfl
end Shared
"""

BETA_OTHER = """namespace Beta
structure Pt where
  x : Nat
end Beta
"""

PAPER = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\title{%s}
\begin{document}
\begin{theorem}\label{thm:one} %s \end{theorem}
\begin{theorem}\label{thm:two} One plus one is two. \end{theorem}
\begin{theorem}\label{thm:three} Two plus two is four. \end{theorem}
\begin{theorem}\label{thm:four} A point has a coordinate. \end{theorem}
\end{document}
"""

YAML = """version: "v0.4"
sources:
  - title: "Alpha sums"
    relationship: "formalizes"
  - title: "Beta products"
    relationship: "formalizes"
alignment:
  statements:
    - source: "Theorem 1 (alpha)"
      lean: "Alpha.add_swap"
    - source: "Theorem 1 (beta)"
      lean: "Beta.mul_swap"
"""

BETA_SHAPE = """structure Foo where
  bar : Nat
"""

ALPHA_MODULES = {"Alpha", "Alpha.Main", "Alpha.Cell"}
BETA_MODULES = {"Beta", "Beta.Main", "Beta.Other", "Beta.Shape", "Beta.Cell"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("pair")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "pair"\n\n[[lean_lib]]\nname = "Alpha"\n\n[[lean_lib]]\nname = "Beta"\n')
    for path, body in [("Alpha/Main.lean", ALPHA), ("Alpha/Cell.lean", CELL),
                       ("Alpha.lean", "import Alpha.Main\nimport Alpha.Cell\n"),
                       ("Beta/Main.lean", BETA_MAIN), ("Beta/Other.lean", BETA_OTHER),
                       ("Beta/Shape.lean", BETA_SHAPE), ("Beta/Cell.lean", CELL),
                       ("Beta.lean", "".join(f"import Beta.{m}\n"
                                             for m in ("Main", "Other", "Shape", "Cell")))]:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(body)
    (root / "alpha.tex").write_text(PAPER % ("Alpha sums", "Addition of naturals commutes."))
    (root / "beta.tex").write_text(PAPER % ("Beta products",
                                            "Multiplication of naturals is commutative."))
    (root / "formalization.yaml").write_text(YAML)
    r = subprocess.run(["lake", "build", "Alpha", "Beta"], cwd=root, capture_output=True,
                       text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


@pytest.fixture
def pair(built, tmp_path, monkeypatch):
    """A copy of the built project, and the Lean sessions each build starts."""
    root = tmp_path / "pair"
    shutil.copytree(built, root, symlinks=True,
                    ignore=shutil.ignore_patterns(".machinechecked", "machinechecked.links.json"))
    sessions, real = [], simple.run_simple_probe

    def spy(root, modules, libs, requests, *a, **k):
        sessions.append({"modules": set(modules), "kinds": {r["kind"] for r in requests},
                         "links": {r["name"] for r in requests if r["kind"] == "link"}})
        return real(root, modules, libs, requests, *a, **k)
    monkeypatch.setattr(simple, "run_simple_probe", spy)
    return root, sessions


def view(root, paper="alpha.tex"):
    return build_view(root, root / paper, root / ".machinechecked", log=lambda m: None)


def by_number(v):
    return {c["number"]: c for c in v["body"]["claims"]}


@needs_lean
@needs_tex
def test_a_library_mapped_only_to_another_paper_is_not_indexed(pair):
    root, sessions = pair
    v = view(root)
    # No Lean session of the Alpha paper's build loads a module of Beta.
    assert sessions and not any(s["modules"] & BETA_MODULES for s in sessions)
    assert {d["module"].split(".")[0] for d in v["body"]["index"]} == {"Alpha"}
    assert by_number(v)["Theorem 1"]["status_code"] == "link.checked"
    # The scope is reported, so that a declaration of Beta is not taken for absent.
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 5}
    assert any("of Beta, which formalization.yaml maps only to other papers, are not indexed"
               in n for n in v["body"]["notes"])
    sessions.clear()
    assert content_id(view(root)["body"]) == content_id(v["body"]) and sessions == []

    # The Beta paper's build indexes Beta, and leaves Alpha out.
    w = view(root, "beta.tex")
    indexed = set().union(*(s["modules"] for s in sessions if "index" in s["kinds"]))
    assert indexed == BETA_MODULES
    assert not any(s["modules"] & ALPHA_MODULES for s in sessions)
    assert by_number(w)["Theorem 1"]["status_code"] == "link.checked"
    assert w["body"]["index_scope"] == {"left_out": ["Alpha"], "modules": 3}


@needs_lean
@needs_tex
def test_a_link_into_another_papers_library_is_checked_there(pair):
    """A link of the Alpha paper into Beta is checked there: the modules of Beta whose sources
    use the name's words are indexed (all that mention `Beta` here), the others are not. A name
    both libraries declare is ambiguous, as when both are indexed."""
    root, sessions = pair
    save_link(root, "alpha.tex", "thm:two", ["Beta.linked_from_alpha"])
    save_link(root, "alpha.tex", "thm:three", ["Shared.dup"])
    v = view(root)
    st = by_number(v)
    assert st["Theorem 2"]["links"][0]["status_code"] == "link.checked"
    dup = st["Theorem 3"]["links"][0]
    assert dup["status_code"] == "link.ambiguous"
    assert "Alpha.Main" in dup["status_detail"] and "Beta.Main" in dup["status_detail"]
    assert {d["module"] for d in v["body"]["index"]} & BETA_MODULES == {"Beta.Main",
                                                                         "Beta.Other"}
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 2}
    sessions.clear()
    again = view(root)
    assert sessions == [] and content_id(again["body"]) == content_id(v["body"])


@needs_lean
@needs_tex
def test_a_projection_another_library_generates_keeps_a_link_ambiguous(pair):
    """`Foo.bar` is a theorem the source of Alpha states, and a projection Lean generates in
    Beta from `structure Foo where bar : Nat`, whose source declares no `Foo.bar`. The module
    whose source has the name's words joins the index, and the link reads ambiguous, as it does
    when every library is indexed."""
    root, sessions = pair
    save_link(root, "alpha.tex", "thm:four", ["Foo.bar"])
    v = view(root)
    link = by_number(v)["Theorem 4"]["links"][0]
    assert link["status_code"] == "link.ambiguous"
    assert link["status_detail"] == "Declared in Alpha.Main, Beta.Shape."
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 4}


@needs_lean
@needs_tex
def test_an_instance_lean_names_brings_in_every_library(pair):
    """`instReprCell` is the instance `deriving Repr` makes in both libraries; no source names
    it. A linked name that starts with `inst` brings every library into the index, as before
    libraries were left out, and the link reads ambiguous."""
    root, sessions = pair
    save_link(root, "alpha.tex", "thm:two", ["instReprCell"])
    v = view(root)
    link = by_number(v)["Theorem 2"]["links"][0]
    assert link["status_code"] == "link.ambiguous"
    assert link["status_detail"] == "Declared in Alpha.Cell, Beta.Cell."
    assert "index_scope" not in v["body"]
    assert not any("are not indexed for this paper" in n for n in v["body"]["notes"])


NOTES = """/-!
# Notes

A point of the Beta paper has its coordinate `Beta.Pt.x`, is made by `Beta.Pt.mk` and is
printed by `Beta.instReprPt`; `Beta.Pt.gone` is no declaration.
-/

theorem Alpha.noted : True := trivial
"""


@needs_lean
@needs_tex
def test_a_docstring_name_a_library_left_out_generates_is_declared(pair):
    """A module docstring of Alpha names the projection, the constructor and the derived `Repr`
    instance of `Beta.Pt`, which Lean generates in `Beta.Other` and no source declares, and a
    name nothing declares. With Beta left out of the Alpha paper's index, the modules of Beta
    that could hold the names are indexed for them alone, and only the last name is reported;
    with those modules in the index, the same (#276)."""
    root, sessions = pair
    (root / "Alpha" / "Notes.lean").write_text(NOTES)
    (root / "Alpha.lean").write_text("import Alpha.Main\nimport Alpha.Cell\nimport Alpha.Notes\n")
    (root / "Beta" / "Other.lean").write_text(BETA_OTHER.replace("  x : Nat\n",
                                                                 "  x : Nat\nderiving Repr\n"))
    r = subprocess.run(["lake", "build", "Alpha", "Beta"], cwd=root, capture_output=True,
                       text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    stale = [("Alpha/Notes.lean", 5, "Beta.Pt.gone")]
    v = view(root)
    assert [(d["file"], d["line"], d["name"]) for d in v["body"]["module_docs"]] == stale
    assert {d["module"].split(".")[0] for d in v["body"]["index"]} == {"Alpha"}
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 5}
    assert [s["kinds"] for s in sessions if s["modules"] & BETA_MODULES] == \
        [{"index", "refs", "modules"}]
    sessions.clear()
    assert content_id(view(root)["body"]) == content_id(v["body"]) and sessions == []

    # A link into Beta brings `Beta.Other` into the index: its constants answer the names.
    save_link(root, "alpha.tex", "thm:two", ["Beta.linked_from_alpha"])
    w = view(root)
    assert "Beta.Other" in {d["module"] for d in w["body"]["index"]}
    assert [(d["file"], d["line"], d["name"]) for d in w["body"]["module_docs"]] == stale


@needs_lean
def test_a_name_no_library_in_scope_declares_is_looked_for_in_those_left_out(pair):
    """When the scope misses the module that holds a linked name, the name is looked for in
    the modules left out, in one session, and the answer is stored."""
    root, sessions = pair
    libs = ["Alpha", "Beta"]
    built, unbuilt = simple.built_modules(root, libs)
    scope = sorted(m for m in built if m in ALPHA_MODULES)

    def links():
        lean = simple.LeanFacts(root, libs, built, unbuilt, root / ".machinechecked" / "build",
                                log=lambda m: None, scope=scope)
        with lean.store.lock():
            index, failed = lean.index({"Beta.Pt.x"})
            return lean.links({"Beta.Pt.x"}, index, failed)[0]["Beta.Pt.x"]

    found = [r for r in links() if "missing" not in (r.get("errors") or [])]
    assert [r["decl"]["module"] for r in found] == ["Beta.Other"]
    wide = [s for s in sessions if s["modules"] & BETA_MODULES]
    assert [(w["kinds"], w["links"]) for w in wide] == [({"link", "modules"}, {"Beta.Pt.x"})]
    assert wide[0]["modules"] == BETA_MODULES
    sessions.clear()
    assert [r for r in links() if "missing" not in (r.get("errors") or [])] == found
    assert sessions == []


def test_the_scope_keeps_every_module_that_could_hold_a_linked_name(tmp_path):
    """The rule, on sources alone: a module of a library left out joins the index when its
    source has one of a linked name's words, when it uses an attribute that translates names,
    when its source cannot be read, or when the project names it as the module of a linked
    declaration; every module joins for a name with a component starting with `inst` or
    written in `«»`, or when a source of the project defines commands."""
    from prooflens.simple import index_scope
    files = {"Own/A.lean": "theorem Own.a : True := trivial\n",
             "Other/Shape.lean": "structure Foo where\n  bar : Nat\n",
             "Other/Rel.lean": "inductive Chain : Nat → Prop\n",
             "Other/Mul.lean": "@[to_additive] theorem mul_one' : True := trivial\n",
             "Other/Named.lean": "theorem Other.named : True := trivial\n",
             "Other/Plain.lean": "theorem Other.plain : True := trivial\n"}
    for f, text in files.items():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text(text)
    # A built module whose source is not where it is looked for.
    built = sorted([f[:-5].replace("/", ".") for f in files] + ["Other.Gone"])

    def left(linked, named=frozenset()):
        keep, libs, rest = index_scope(tmp_path, ["Own", "Other"], built, {"Other"},
                                       set(linked), set(named))
        assert sorted(keep + rest) == built and (libs == ["Other"]) == bool(rest)
        return set(rest)

    # A projection of `Foo`, a name `mk_iff` makes from `Chain` (`chain_iff`, by its beginning
    # and in any case), and a translated name are each kept with the modules that could hold
    # them; the rest is left out.
    assert left(["Foo.bar"]) == {"Other.Rel", "Other.Named", "Other.Plain"}
    assert left(["chain_iff"]) == {"Other.Shape", "Other.Named", "Other.Plain"}
    assert left(["Own.a"]) == {"Other.Shape", "Other.Rel", "Other.Named", "Other.Plain"}
    assert left(["Own.a"], ["Other.Named"]) == {"Other.Shape", "Other.Rel", "Other.Plain"}
    # An instance Lean names, one of its fields, a name in «», or a project that defines
    # commands: every module.
    for name in ("instReprFoo", "instReprFoo.repr", "Box.instInhabitedFoo", "«foo bar».x"):
        assert left([name]) == set(), name
    for maker in ('syntax "make" ident : command', "macro_rules | `(make $n) => `(def $n := 0)",
                  "macro_rules | `(make $n) => `($[$doc]? def $n := 0)",
                  "def go : CommandElabM Unit := pure ()", "run_cmd pure ()"):
        (tmp_path / "Own" / "A.lean").write_text(maker + "\n")
        assert left(["Own.a"]) == set(), maker


@needs_lean
@needs_tex
def test_search_and_inspection_reach_the_libraries_left_out(pair, tmp_path):
    from prooflens.compare import Site, query, search, search_text
    from prooflens.deps import inspect
    from prooflens.simple import write_view_site
    root, sessions = pair
    write_view_site(view(root), tmp_path / "site", None, root)
    site = Site(tmp_path / "site" / "data")

    # The build's search leaves Beta out, and says so.
    own = search(site, "multiplication of naturals is commutative")
    assert "Beta.mul_swap" not in [r["name"] for r in own["results"]]
    assert own["scope"]["left_out"] == ["Beta"]
    assert "--all-libraries" in search_text(own)

    # Asked to, it searches every library: Lean indexes Beta, and only Beta.
    sessions.clear()
    wide = query(site, "search", "multiplication of naturals is commutative", root=root,
                 every_library=True)
    assert wide["results"][0]["name"] == "Beta.mul_swap"
    assert "left_out" not in wide["scope"]
    indexed = set().union(*(s["modules"] for s in sessions if "index" in s["kinds"]))
    assert indexed == BETA_MODULES
    sessions.clear()
    assert search(site, "multiplication", every_library=root)["results"] and sessions == []

    # `inspect` reaches a declaration of Beta.
    out = inspect(root, "Beta.mul_swap")
    assert out["ok"] and out["declaration"]["module"] == "Beta.Main"
