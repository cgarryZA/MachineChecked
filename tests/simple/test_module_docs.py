"""Module docstrings that name declarations which do not exist (#107), on a copy of the
synthetic project tests/fixtures/structure with one more module: `check` lists each such name
with its file and line, the reader's notes say so, and names that resolve (in the module's
namespaces, to a private declaration, a namespace, a module or a dependency) are not listed."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import cli
from prooflens.simple import build_view, stale_doc_names

SRC = ROOT / "tests" / "fixtures" / "structure"

WIDGETS = '''/-!
# Widgets

## Main definitions

* `Shape.Widget` — a widget.
* `bar_pos` — the bar of a widget is positive (named inside its namespace).
* `secret_le` — a private lemma.

## Main statements

* `Shape.Widget.foo_le_bar` — the foo of a widget is at most its bar.
* `gone_lemma` — deleted too.
* `L` — notation, not checked.

See `Shape.Main`, `Nat.le_refl` and `Shape`; the proofs use `omega`, and a widget `w` has
`w.bar`.

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
'''


def project(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(SRC, root)
    (root / "Shape.lean").write_text("import Shape.Main\nimport Shape.Widgets\n")
    (root / "Shape" / "Widgets.lean").write_text(WIDGETS)
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
    assert found == [("Shape/Widgets.lean", 12, "Shape.Widget.foo_le_bar"),
                     ("Shape/Widgets.lean", 13, "gone_lemma")]
    assert all(f"`{n}`" in lines[l - 1] for _, l, n in found)
    assert any(n.startswith("2 name(s) in module docstrings are not declared")
               for n in view["body"]["notes"])
    monkeypatch.chdir(root)
    capsys.readouterr()
    cli.main(["check", "paper/main.tex"])  # a warning: the check still passes
    out = capsys.readouterr().out
    assert ("warning: Shape/Widgets.lean:12: module docstring names Shape.Widget.foo_le_bar, "
            "which is not declared") in out
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
