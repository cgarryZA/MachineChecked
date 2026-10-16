"""A project whose built modules cannot all be loaded together, and one with an unbuilt module.

Synthetic: a `Challenge` library states `Twin.target` with `sorry` (a statement left for others
to prove) and a `Solution` library proves the same name, so the two cannot be imported into one
Lean session; a `Later` library is never built. MachineChecked must probe them apart, tell the
solution from the challenge by module, call a link without a module ambiguous rather than
guess, and say a declaration in an unbuilt module is not built, not "not found".
"""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import build_view

PAPER = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:a} One plus one is two. \end{theorem}
\begin{theorem}\label{thm:b} One plus one is two, again. \end{theorem}
\begin{theorem}\label{thm:c} A later result. \end{theorem}
\begin{theorem}\label{thm:d} A result nobody wrote. \end{theorem}
\end{document}
"""

YAML = """version: "v0.4"
sources:
  - title: "Twin statements"
    relationship: "formalizes"
alignment:
  statements:
    - source: "Theorem 1"
      lean: "Twin.target"
      module: "Solution.Main"
    - source: "Theorem 2"
      lean: "Twin.target"
    - source: "Theorem 3"
      lean: "Later.result"
    - source: "Theorem 4"
      lean: "Nowhere.result"
"""


@pytest.fixture(scope="module")
def twins(tmp_path_factory):
    root = tmp_path_factory.mktemp("twins")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "twins"\n\n[[lean_lib]]\nname = "Challenge"\n\n'
        '[[lean_lib]]\nname = "Solution"\n\n[[lean_lib]]\nname = "Later"\n')
    for lib, body in [("Challenge", "namespace Twin\ntheorem target : 1 + 1 = 2 := by sorry\nend Twin\n"),
                      ("Solution", "namespace Twin\ntheorem target : 1 + 1 = 2 := rfl\nend Twin\n"),
                      ("Later", "theorem Later.result : True := trivial\n")]:
        (root / lib).mkdir()
        (root / lib / "Main.lean").write_text(body)
        (root / f"{lib}.lean").write_text(f"import {lib}.Main\n")
    (root / "paper.tex").write_text(PAPER)
    (root / "formalization.yaml").write_text(YAML)
    r = subprocess.run(["lake", "build", "Challenge", "Solution"], cwd=root,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


@needs_lean
@needs_tex
def test_modules_that_cannot_load_together_are_told_apart(twins):
    view = build_view(twins, twins / "paper.tex", twins / ".machinechecked", log=lambda m: None)
    st = {c["number"]: c for c in view["body"]["claims"]}
    # The solution, named by its module, is the proved one; the challenge never stands in.
    a = st["Theorem 1"]["links"][0]
    assert a["status"] == "linked: Lean proof checked"
    assert (a["record"]["decl"] or {}).get("module") == "Solution.Main"
    # Without a module the name is ambiguous, and nothing is claimed.
    b = st["Theorem 2"]["links"][0]
    assert b["status"].startswith("linked: Lean name is ambiguous")
    assert "Challenge.Main" in b["status"] and "Solution.Main" in b["status"]
    # A declaration in a module that is not built is not built, not missing.
    assert st["Theorem 3"]["links"][0]["status"] == \
        "linked: Lean not checked (its module Later.Main is not built)"
    # Only a declaration absent from the inspected modules is not found.
    assert st["Theorem 4"]["links"][0]["status"] == "linked: Lean declaration not found"
    assert not any("could not be loaded" in n for n in view["body"]["notes"])
