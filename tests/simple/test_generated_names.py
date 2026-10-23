"""A name one library declares by hand and another has only as a constant Lean generates (#275).

Synthetic: `Alpha.Main` states theorems named `Foo.mk` and `instReprCell`; `Beta.Main` declares
`structure Foo` (whose constructor Lean names `Foo.mk`) and `structure Cell … deriving Repr`
(whose instance Lean names `instReprCell`). There is no formalization.yaml, so every library is
indexed. The index holds only the theorems of Alpha, but each name is held by both libraries,
so a link to it reads ambiguous and names both modules, as a name both declare by hand does.
"""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import simple
from prooflens.simple import build_view, save_link
from prooflens.util import content_id

ALPHA = """theorem Foo.mk : 1 = 1 := rfl

theorem instReprCell : True := trivial
"""

BETA = """structure Foo where
  n : Nat

structure Cell where
  n : Nat
deriving Repr
"""

PAPER = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:one} One is one. \end{theorem}
\begin{theorem}\label{thm:two} Truth holds. \end{theorem}
\begin{theorem}\label{thm:three} A cell has a number. \end{theorem}
\end{document}
"""

BOTH = "Declared in Alpha.Main, Beta.Main."


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("generated")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "generated"\n\n[[lean_lib]]\nname = "Alpha"\n\n[[lean_lib]]\nname = "Beta"\n')
    for path, body in [("Alpha/Main.lean", ALPHA), ("Alpha.lean", "import Alpha.Main\n"),
                       ("Beta/Main.lean", BETA), ("Beta.lean", "import Beta.Main\n"),
                       ("paper.tex", PAPER)]:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(body)
    r = subprocess.run(["lake", "build", "Alpha", "Beta"], cwd=root, capture_output=True,
                       text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


@pytest.fixture
def project(built, tmp_path, monkeypatch):
    """A copy of the built project, and the Lean sessions each build starts."""
    root = tmp_path / "generated"
    shutil.copytree(built, root, symlinks=True,
                    ignore=shutil.ignore_patterns(".machinechecked", "machinechecked.links.json"))
    sessions, real = [], simple.run_simple_probe

    def spy(root, modules, libs, requests, *a, **k):
        sessions.append({"modules": set(modules),
                         "links": {r["name"] for r in requests if r["kind"] == "link"}})
        return real(root, modules, libs, requests, *a, **k)
    monkeypatch.setattr(simple, "run_simple_probe", spy)
    return root, sessions


def view(root):
    return build_view(root, root / "paper.tex", root / ".machinechecked", log=lambda m: None)


def links(v):
    return {l["name"]: l for c in v["body"]["claims"] for l in c["links"]}


@needs_lean
@needs_tex
def test_a_constructor_or_instance_another_library_generates_keeps_a_link_ambiguous(project):
    root, sessions = project
    save_link(root, "paper.tex", "thm:one", ["Foo.mk"])
    save_link(root, "paper.tex", "thm:two", ["instReprCell"])
    v = view(root)
    # The index holds Alpha's theorems only; Beta's constructor and instance are not in it.
    assert {(d["name"], d["module"]) for d in v["body"]["index"]
            if d["name"] in ("Foo.mk", "instReprCell")} == {("Foo.mk", "Alpha.Main"),
                                                            ("instReprCell", "Alpha.Main")}
    found = links(v)
    for name in ("Foo.mk", "instReprCell"):
        assert found[name]["status_code"] == "link.ambiguous", name
        assert found[name]["status_detail"] == BOTH
        assert found[name]["record"] is None
    claims = {c["number"]: c for c in v["body"]["claims"]}
    assert claims["Theorem 1"]["status_code"] == claims["Theorem 2"]["status_code"] \
        == "link.ambiguous"
    # The answers are stored: a second build asks Lean nothing and says the same.
    sessions.clear()
    again = view(root)
    assert sessions == [] and content_id(again["body"]) == content_id(v["body"])


@needs_lean
@needs_tex
def test_a_link_made_after_another_library_changed_is_answered_where_the_name_is(project):
    """With Alpha changed, the build loads only Alpha to index it; a name that Beta holds is
    still answered in Beta: a constructor that keeps a link ambiguous, and a projection that only
    Beta has, which reads as the definition it is, not as missing."""
    root, sessions = project
    view(root)
    main = root / "Alpha" / "Main.lean"
    main.write_text(ALPHA + "\ntheorem Alpha.two : 2 = 2 := rfl\n")
    r = subprocess.run(["lake", "build", "Alpha", "Beta"], cwd=root, capture_output=True,
                       text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    save_link(root, "paper.tex", "thm:one", ["Foo.mk"])
    save_link(root, "paper.tex", "thm:two", ["instReprCell"])
    save_link(root, "paper.tex", "thm:three", ["Cell.n"])
    sessions.clear()
    v = view(root)
    found = links(v)
    assert found["Foo.mk"]["status_code"] == found["instReprCell"]["status_code"] \
        == "link.ambiguous"
    assert found["Foo.mk"]["status_detail"] == found["instReprCell"]["status_detail"] == BOTH
    assert found["Cell.n"]["status_code"] == "link.definition"
    assert found["Cell.n"]["record"]["decl"]["module"] == "Beta.Main"
    # Beta's index is reused; Beta.Main is loaded once, for the names it holds.
    beta = [s for s in sessions if s["modules"] & {"Beta", "Beta.Main"}]
    assert [s["modules"] for s in beta] == [{"Beta.Main"}]
    assert {"Foo.mk", "instReprCell", "Cell.n"} <= beta[0]["links"]
    sessions.clear()
    assert content_id(view(root)["body"]) == content_id(v["body"]) and sessions == []
