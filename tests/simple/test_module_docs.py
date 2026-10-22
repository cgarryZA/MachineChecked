"""Module docstrings that name declarations which do not exist (#107), on a copy of the
synthetic project tests/fixtures/structure with one more module: `check` lists each such name
with its file and line, the reader's notes say so, and names that resolve to a declaration (in
the namespaces the module enters or opens, a private declaration, a dependency's) are not
listed. A module or namespace written in full is accepted; a shorter name that reaches only a
module or a namespace through the file's namespaces is listed as what it reaches."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, TOY, needs_lean, needs_tex
from prooflens import cli
from prooflens.moddocs import stale_doc_names
from prooflens.simple import build_view

SRC = ROOT / "tests" / "fixtures" / "structure"

WIDGETS = '''import Shape.Gizmo

/-!
# Widgets

## Main definitions

* `Shape.Widget` — a widget.
* `bar_pos` — the bar of a widget is positive (named inside its namespace).
* `secret_le` — a private lemma.

## Main statements

* `Shape.Widget.foo_le_bar` — the foo of a widget is at most its bar.
* `gone_lemma` — deleted too.
* `L` — notation, not checked.

See `Shape.Main`, `Nat.le_refl`, `Shape` and `Gizmo.Parts`; the proofs use `omega`, and a
widget `w` has `w.bar`.

The parts are bounded by `Parts.part_le`, through the namespace opened below; `Parts.part_gone`
is gone. The old structures `Widgets` and `Parts` are no declarations.

Spare parts come from `Spare.helper`, in the module `Shape.Spare` that nothing here imports.

```
example : Shape.Widget.ghost := sorry
```
-/

namespace Shape

structure Widget where
  bar : Nat

theorem Widget.bar_pos (w : Widget) (h : 0 < w.bar) : 0 < w.bar := h

private theorem secret_le (n : Nat) : n ≤ n := Nat.le_refl n

end Shape

open Gizmo
'''

# A module of another namespace: a name of it resolves in `Shape.Widgets` only through `open`.
GIZMO = '''namespace Gizmo.Parts

theorem part_le (n : Nat) : n ≤ n := Nat.le_refl n

end Gizmo.Parts
'''

# A module of the library that no module of the project imports, so the probe never loads it:
# the names WIDGETS gives of it are declared all the same (#213).
SPARE = '''namespace Shape.Spare

theorem helper (n : Nat) : n ≤ n := Nat.le_refl n

end Shape.Spare
'''

# Each listed name, by line of WIDGETS: a declaration that is gone, a name that resolves to
# nothing, and short names that reach a module and a namespace where a declaration is expected.
# The module `Shape.Main` and the namespaces `Shape` and `Gizmo.Parts`, written in full, are not
# listed, nor are `Spare.helper` and `Shape.Spare` of the module nothing imports.
EXPECTED = [("Shape/Widgets.lean", 14, "Shape.Widget.foo_le_bar"),
            ("Shape/Widgets.lean", 15, "gone_lemma"),
            ("Shape/Widgets.lean", 21, "Parts.part_gone"),
            ("Shape/Widgets.lean", 22, "Parts"),
            ("Shape/Widgets.lean", 22, "Widgets")]


def project(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(SRC, root)
    (root / "Shape.lean").write_text((SRC / "Shape.lean").read_text() + "import Shape.Widgets\n")
    (root / "Shape" / "Widgets.lean").write_text(WIDGETS)
    (root / "Shape" / "Gizmo.lean").write_text(GIZMO)
    (root / "Shape" / "Spare.lean").write_text(SPARE)
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
def test_stale_names_in_module_docstrings_are_listed(tmp_path, monkeypatch, capsys, toolchain):
    root = project(tmp_path, toolchain)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked",
                      log=lambda m: None)
    found = [(d["file"], d["line"], d["name"]) for d in view["body"]["module_docs"]]
    lines = WIDGETS.splitlines()
    assert found == EXPECTED
    assert all(f"`{n}`" in lines[l - 1] for _, l, n in found)
    assert any(n.startswith("5 name(s) in module docstrings are not declared")
               for n in view["body"]["notes"])
    monkeypatch.chdir(root)
    capsys.readouterr()
    cli.main(["check", "paper/main.tex"])  # a warning: the check still passes
    out = capsys.readouterr().out
    assert ("warning: Shape/Widgets.lean:14: module docstring names Shape.Widget.foo_le_bar, "
            "which is not declared") in out
    assert ("warning: Shape/Widgets.lean:22: module docstring names Widgets, which is the "
            "module Shape.Widgets, not a declaration") in out
    assert ("warning: Shape/Widgets.lean:22: module docstring names Parts, which is the "
            "namespace Gizmo.Parts, not a declaration") in out
    # Modules and namespaces written in full are not listed, whatever the line says.
    assert not any(f"names {n}," in out for n in ("Shape.Main", "Shape", "Gizmo.Parts",
                                                    "Spare.helper", "Shape.Spare"))
    # A name that resolves through the namespace the file opens is not listed.
    assert "Parts.part_le," not in out
    cli.main(["check", "--json", "paper/main.tex"])
    doc = json.loads(capsys.readouterr().out)
    assert [(w["file"], w["line"], w["name"]) for w in doc["warnings"]] == found


def test_only_names_shaped_like_project_declarations_are_listed():
    def rec(name, heading="Overview", lead=False, line=3):
        return {"record": "moddoc", "module": "A.B", "line": line, "name": name,
                "heading": heading, "item_lead": lead}
    found = stale_doc_names([
        rec("Widget.gone"), rec("w.bar"), rec("omega"), rec("x_T", "Main results", True),
        rec("gone_lemma", "Main results", True), rec("W₂x", "Main results", True),
        rec("gone_lemma", "Main results", True), rec("lead_elsewhere", "Notation", True)])
    assert [(d["file"], d["name"]) for d in found] == [("A/B.lean", "Widget.gone"),
                                                       ("A/B.lean", "gone_lemma"),
                                                       ("A/B.lean", "x_T")]


@needs_lean
@needs_tex
def test_docstring_names_are_kept_with_the_facts_until_the_module_changes(tmp_path):
    """The names a module's docstrings hold are stored with its index: a build with nothing
    changed asks Lean nothing and lists the same names; an edit to the docstring re-indexes the
    module and lists what it now says."""
    root = project(tmp_path, None)

    def view():
        v = build_view(root, root / "paper/main.tex", root / ".machinechecked",
                       log=lambda m: None)
        return v, [(d["file"], d["line"], d["name"]) for d in v["body"]["module_docs"]]
    _, first = view()
    v, again = view()
    assert v["lean"]["sessions"] == 0 and again == first

    widgets = root / "Shape" / "Widgets.lean"
    widgets.write_text(WIDGETS.replace("* `gone_lemma` — deleted too.",
                                       "* `Shape.Widget.ghost_lemma` — also gone."))
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    v, after = view()
    assert v["lean"]["sessions"] > 0
    assert after == [(f, 15, "Shape.Widget.ghost_lemma") if n == "gone_lemma" else (f, l, n)
                     for f, l, n in EXPECTED]


def test_a_module_or_namespace_is_listed_as_what_it_is():
    """A short name that reaches only a module or a namespace is listed when it is capitalised
    or dotted (a capitalised word is the name of a structure that is gone), and its message
    names what it reaches."""
    from prooflens.moddocs import stale_doc_message

    def rec(name, kind, full=None):
        return {"record": "moddoc", "module": "A.B", "line": 3, "name": name, "heading": "",
                "item_lead": False, "kind": kind, "full": full or name}
    found = stale_doc_names([rec("Widget", "module", "A.Widget"), rec("Tools", "namespace", "A.Tools"),
                             rec("Widget", "none"), rec("tools", "namespace")])
    assert [stale_doc_message(d) for d in found] == [
        "A/B.lean:3: module docstring names Tools, which is the namespace A.Tools, not a "
        "declaration",
        "A/B.lean:3: module docstring names Widget, which is the module A.Widget, not a "
        "declaration"]


def test_a_name_of_a_module_the_project_does_not_import_is_declared(tmp_path):
    """A name the probe's environment lacks is not listed when a module of the same library
    declares it, inside one of the scopes of the docstring's module, or when it names a module
    of that library in full; a name no source of the library declares is listed (#213)."""
    lib = tmp_path / ".lake" / "packages" / "lib"
    (lib / "Lib").mkdir(parents=True)
    (tmp_path / "lake-manifest.json").write_text(json.dumps(
        {"packages": [{"type": "git", "name": "lib"}]}))
    (lib / "Lib" / "B.lean").write_text("namespace Lib.Data\n\ndef ofSolves : Nat := 0\n\n"
                                        "end Lib.Data\n")

    def rec(name):
        return {"record": "moddoc", "module": "Lib.A", "line": 3, "name": name, "heading": "",
                "item_lead": False, "kind": "none", "scopes": ["Lib"]}
    names = ["Lib.Data.ofSolves", "Data.ofSolves", "Lib.B", "Data.gone", "Lib.C"]
    found = stale_doc_names([rec(n) for n in names], tmp_path)
    assert [d["name"] for d in found] == ["Data.gone", "Lib.C"]
    assert len(stale_doc_names([rec(n) for n in names])) == 5


@needs_lean
@needs_tex
def test_the_toy_example_names_only_what_its_modules_resolve(tmp_path, monkeypatch):
    """The toy example's module docstrings name only what each module resolves: a build of its
    Lean project with both libraries, in zero configuration, lists no name, and the probe
    reports none for the sources to resolve either (#254)."""
    import prooflens.simple as simple
    probed = []

    def spy(records, lean_root=None):
        probed.append(list(records))
        return stale_doc_names(records, lean_root)
    monkeypatch.setattr(simple, "stale_doc_names", spy)
    root = tmp_path / "toy"
    shutil.copytree(TOY / "lean", root, ignore=shutil.ignore_patterns(".lake"))
    (root / "paper").mkdir()
    shutil.copy(TOY / "paper" / "toy.tex", root / "paper")
    subprocess.run(["lake", "build", "Toy", "ToyAudit"], cwd=root, check=True,
                   capture_output=True, timeout=900)
    view = build_view(root, root / "paper/toy.tex", root / ".machinechecked",
                      log=lambda m: None)
    assert view["body"]["module_docs"] == []
    assert not any("module docstrings" in n for n in view["body"]["notes"])
    assert probed and all(stale_doc_names(records) == [] for records in probed)
