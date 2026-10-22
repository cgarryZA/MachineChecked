"""Two papers mapped to separate libraries: each paper's build indexes its own (#130).

Synthetic: the `Alpha` library formalises the paper "Alpha sums" and the `Beta` library the
paper "Beta products", as formalization.yaml maps them. `Beta.Main` declares `Beta.mul_swap`
and `Beta.linked_from_alpha`; `Beta.Other`, which `Beta.Main` does not import, declares the
structure `Beta.Pt` (whose projection `Beta.Pt.x` Lean generates). Both libraries declare
`Shared.dup`, so they cannot be loaded together. A build of one paper must not index the other
paper's library, must say so, must still check a link into that library (and find a name both
libraries declare in both), and a search or an inspection must still reach it.
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

BETA_MODULES = {"Beta", "Beta.Main", "Beta.Other"}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("pair")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "pair"\n\n[[lean_lib]]\nname = "Alpha"\n\n[[lean_lib]]\nname = "Beta"\n')
    for path, body in [("Alpha/Main.lean", ALPHA), ("Alpha.lean", "import Alpha.Main\n"),
                       ("Beta/Main.lean", BETA_MAIN), ("Beta/Other.lean", BETA_OTHER),
                       ("Beta.lean", "import Beta.Main\nimport Beta.Other\n")]:
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
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 3}
    assert any("of Beta, which formalization.yaml maps only to other papers, are not indexed"
               in n for n in v["body"]["notes"])
    sessions.clear()
    assert content_id(view(root)["body"]) == content_id(v["body"]) and sessions == []

    # The Beta paper's build indexes Beta, and leaves Alpha out.
    w = view(root, "beta.tex")
    indexed = set().union(*(s["modules"] for s in sessions if "index" in s["kinds"]))
    assert indexed == BETA_MODULES
    assert not any(s["modules"] & {"Alpha", "Alpha.Main"} for s in sessions)
    assert by_number(w)["Theorem 1"]["status_code"] == "link.checked"
    assert w["body"]["index_scope"] == {"left_out": ["Alpha"], "modules": 2}


@needs_lean
@needs_tex
def test_a_link_into_another_papers_library_is_checked_there(pair):
    """A link of the Alpha paper into Beta is checked by loading only the module whose source
    declares it; a name both libraries declare is ambiguous, as when both are indexed; a name
    Lean generates in a module of Beta that no indexed library declares is found by looking in
    the modules left out, once."""
    root, sessions = pair
    save_link(root, "alpha.tex", "thm:two", ["Beta.linked_from_alpha"])
    save_link(root, "alpha.tex", "thm:three", ["Shared.dup"])
    save_link(root, "alpha.tex", "thm:four", ["Beta.Pt.x"])
    v = view(root)
    st = by_number(v)
    assert st["Theorem 2"]["links"][0]["status_code"] == "link.checked"
    dup = st["Theorem 3"]["links"][0]
    assert dup["status_code"] == "link.ambiguous"
    assert "Alpha.Main" in dup["status_detail"] and "Beta.Main" in dup["status_detail"]
    pt = st["Theorem 4"]["links"][0]
    assert pt["status_code"] == "link.definition"
    assert pt["record"]["decl"]["module"] == "Beta.Other"

    # Beta.Main is indexed for the links it declares; Beta.Other is not indexed, and is loaded
    # once, to look for the generated name.
    indexed = set().union(*(s["modules"] for s in sessions if "index" in s["kinds"]))
    assert indexed & BETA_MODULES == {"Beta.Main"}
    wide = [s for s in sessions if "Beta.Other" in s["modules"]]
    assert [(w["kinds"], w["links"]) for w in wide] == [({"link", "modules"}, {"Beta.Pt.x"})]
    assert "Beta.Pt" not in {d["name"] for d in v["body"]["index"]}
    assert v["body"]["index_scope"] == {"left_out": ["Beta"], "modules": 2}

    sessions.clear()
    again = view(root)
    assert sessions == [] and content_id(again["body"]) == content_id(v["body"])


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
