"""Module docstrings that name declarations which do not exist (#107), on a copy of the
synthetic project tests/fixtures/structure with one more module: `check` lists each such name
with its file and line, the reader's notes say so, and names that resolve to a declaration (in
the namespaces the module enters or opens, a private declaration, a dependency's) are not
listed. A name that is only a module or a namespace is listed as such, unless the line calls it
a module or a namespace and writes it in full."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
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

See the module `Shape.Main`, `Nat.le_refl` and the namespace `Shape`; the proofs use `omega`,
and a widget `w` has `w.bar`.

The parts are bounded by `Parts.part_le`, through the namespace opened below; `Parts.part_gone`
is gone. The old structure `Widgets` and `Gizmo.Parts` are no declarations.

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

# Each listed name, by line of WIDGETS: a declaration that is gone, a name that resolves to
# nothing, and a module and a namespace named where a declaration is expected.
EXPECTED = [("Shape/Widgets.lean", 14, "Shape.Widget.foo_le_bar"),
            ("Shape/Widgets.lean", 15, "gone_lemma"),
            ("Shape/Widgets.lean", 21, "Parts.part_gone"),
            ("Shape/Widgets.lean", 22, "Gizmo.Parts"),
            ("Shape/Widgets.lean", 22, "Widgets")]


def project(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(SRC, root)
    (root / "Shape.lean").write_text((SRC / "Shape.lean").read_text() + "import Shape.Widgets\n")
    (root / "Shape" / "Widgets.lean").write_text(WIDGETS)
    (root / "Shape" / "Gizmo.lean").write_text(GIZMO)
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
    assert ("warning: Shape/Widgets.lean:22: module docstring names Gizmo.Parts, which is a "
            "namespace, not a declaration") in out
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
    """A name that is only a module or a namespace is listed whatever its shape (a capitalised
    word is the name of a structure that is gone), and its message says what it is."""
    from prooflens.moddocs import stale_doc_message

    def rec(name, kind, full=None):
        return {"record": "moddoc", "module": "A.B", "line": 3, "name": name, "heading": "",
                "item_lead": False, "kind": kind, "full": full or name}
    found = stale_doc_names([rec("Widget", "module", "A.Widget"), rec("Tools", "namespace"),
                             rec("Widget", "none"), rec("tools", "namespace")])
    assert [stale_doc_message(d) for d in found] == [
        "A/B.lean:3: module docstring names Tools, which is a namespace, not a declaration",
        "A/B.lean:3: module docstring names Widget, which is the module A.Widget, not a "
        "declaration"]
