"""`machinechecked inspect`: what a declaration's statement mentions and what its proof uses.

Synthetic: in the `Deps` library, `Deps.main` is stated with `Deps.double` and proved with two
lemmas, `Deps.helper` and `Deps.add_zero'`, that its statement never mentions; `Deps.helper` is
proved with a third, `Deps.two_mul'`. The proof-erased closures cannot see the lemmas; `inspect`
must list them among the proof's dependencies, not the statement's, and reach `two_mul'`
through them. Two libraries declare `Twin.target` (a challenge with `sorry` and its solution),
and the `Later` library is never built.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, needs_lean
from prooflens.deps import inspect
from prooflens.simple import ViewError

DEPS = """namespace Deps

def double (n : Nat) : Nat := n + n

theorem two_mul' (n : Nat) : 2 * n = n + n := by omega

theorem helper (n : Nat) : double n = 2 * n := by
  unfold double
  exact (two_mul' n).symm

theorem add_zero' (n : Nat) : n + 0 = n := Nat.add_zero n

/-- The main result: stated with `double` only. -/
theorem main (n : Nat) : double n + 0 = 2 * n := by
  rw [add_zero', helper]

end Deps
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("deps")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "deps"\n\n[[lean_lib]]\nname = "Deps"\n\n[[lean_lib]]\nname = "Challenge"\n\n'
        '[[lean_lib]]\nname = "Solution"\n\n[[lean_lib]]\nname = "Later"\n')
    for lib, body in [("Deps", DEPS),
                      ("Challenge", "namespace Twin\ntheorem target : 1 + 1 = 2 := by sorry\nend Twin\n"),
                      ("Solution", "namespace Twin\ntheorem target : 1 + 1 = 2 := rfl\nend Twin\n"),
                      ("Later", "theorem Later.result : True := trivial\n")]:
        (root / lib).mkdir()
        (root / lib / "Main.lean").write_text(body)
        (root / f"{lib}.lean").write_text(f"import {lib}.Main\n")
    r = subprocess.run(["lake", "build", "Deps", "Challenge", "Solution"], cwd=root,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


@needs_lean
def test_a_lemma_used_only_in_the_proof_is_a_proof_dependency(project):
    out = inspect(project, "Deps.main")
    assert out["ok"] and out["status"] == "found" and out["schema"] == "machinechecked/inspect@1"
    d = out["declaration"]
    assert d["kind"] == "theorem" and d["module"] == "Deps.Main" and d["file"] == "Deps/Main.lean"
    assert d["doc"].startswith("The main result") and not d["sorry"]
    assert out["value_kind"] == "proof"
    # The statement mentions `double` and nothing else of the project ...
    assert out["statement_dependencies"] == ["Deps.double"]
    # ... the proof uses the two lemmas, which the statement never mentions.
    assert {"Deps.helper", "Deps.add_zero'"} <= set(out["proof_dependencies"])
    assert "Deps.helper" not in out["statement_dependencies"]
    # Nat and Eq come from outside the project and are named as such.
    assert "Nat" in out["external_dependencies"]["statement"]
    assert out["external_dependencies"]["proof"]


@needs_lean
def test_the_closure_follows_proofs_and_records_depth(project):
    out = inspect(project, "Deps.main")
    members = {m["name"]: m for m in out["closure"]["members"]}
    # `two_mul'` is reached only through `helper`'s proof: two steps from the root.
    assert {"Deps.double", "Deps.helper", "Deps.add_zero'", "Deps.two_mul'"} <= set(members)
    assert members["Deps.helper"]["depth"] == 1 and members["Deps.two_mul'"]["depth"] == 2
    assert "Deps.two_mul'" in members["Deps.helper"]["proof_dependencies"]
    assert "Deps.two_mul'" not in members["Deps.helper"]["statement_dependencies"]
    assert out["closure"]["deepest"] >= 2
    assert out["closure"]["external"]["constants"] > 0
    # Nothing of another library leaks in: the closure stays within what the root imports.
    assert not any(n.startswith("Twin.") for n in members)


@needs_lean
def test_two_libraries_declaring_a_name_are_ambiguous_until_its_module_is_given(project):
    out = inspect(project, "Twin.target")
    assert not out["ok"] and out["status"] == "ambiguous"
    assert out["modules"] == ["Challenge.Main", "Solution.Main"]
    solved = inspect(project, "Twin.target", module="Solution.Main")
    assert solved["ok"] and not solved["declaration"]["sorry"]
    challenge = inspect(project, "Twin.target", module="Challenge.Main")
    assert challenge["ok"] and challenge["declaration"]["sorry"]


@needs_lean
def test_not_built_is_not_not_found(project):
    later = inspect(project, "Later.result")
    assert not later["ok"] and later["status"] == "not built" and later["modules"] == ["Later.Main"]
    nowhere = inspect(project, "Deps.nothing", module="Deps.Main")
    assert not nowhere["ok"] and nowhere["status"] == "not found"


@needs_lean
def test_the_answer_is_cached_until_a_lean_input_changes(project):
    first = inspect(project, "Deps.double", refresh=True)
    again = inspect(project, "Deps.double")
    assert not first["cache"]["hit"] and again["cache"]["hit"]
    assert {k: v for k, v in first.items() if k != "cache"} == \
        {k: v for k, v in again.items() if k != "cache"}
    # A changed source is a different project state: the stored answer is not reused.
    src = project / "Deps" / "Main.lean"
    src.write_text(src.read_text() + "\n-- touched\n")
    try:
        assert not inspect(project, "Deps.double")["cache"]["hit"]
    finally:
        src.write_text(DEPS)


@needs_lean
def test_the_command_prints_json_and_exits_1_for_a_negative_answer(project):
    run = lambda *a: subprocess.run([sys.executable, "-m", "prooflens.cli", "inspect", *a],
                                    cwd=project, capture_output=True, text=True)
    ok = run("Deps.main", "--json", "--dependencies")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["closure"]["members"]
    brief = run("Deps.main", "--json")
    assert "members" not in json.loads(brief.stdout)["closure"]
    amb = run("Twin.target", "--json")
    assert amb.returncode == 1 and json.loads(amb.stdout)["status"] == "ambiguous"


def test_no_lean_project_exits_2_with_a_json_error(tmp_path):
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "inspect", "X.y", "--json"],
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 2
    d = json.loads(r.stdout)
    assert d["schema"] == "machinechecked/inspect@1" and d["ok"] is False and d["error"]["kind"]


def test_an_unbuilt_project_is_an_error_not_an_answer(tmp_path):
    (tmp_path / "lakefile.toml").write_text('name = "p"\n\n[[lean_lib]]\nname = "P"\n')
    (tmp_path / "P.lean").write_text("theorem P.x : True := trivial\n")
    with pytest.raises(ViewError, match="not built"):
        inspect(tmp_path, "P.x")
