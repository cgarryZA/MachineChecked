"""The engine's messages name the command `machinechecked` (#384). `prooflens` is an alias of
the command and the name of the Python package; no message tells the reader to run it."""

import ast
import re
from pathlib import Path

import pytest

from prooflens import cli

ENGINE = Path(__file__).resolve().parents[2] / "engine" / "python" / "prooflens"
OLD = re.compile(r"\bprooflens (build|view|check|site|reassess|export|changes|review|inventory"
                 r"|symbol|bundle|cache|link|compare|inspect|workspace|replay)\b"
                 r"|-m prooflens\b")


def strings(tree: ast.AST):
    """The string constants of a module that are not docstrings: what it can print."""
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node


def test_no_message_names_the_old_command():
    found = [f"{p.relative_to(ENGINE)}:{s.lineno}: {s.value!r}"
             for p in sorted(ENGINE.rglob("*.py"))
             for s in strings(ast.parse(p.read_text(encoding="utf-8")))
             if OLD.search(s.value)]
    assert found == []


def test_export_without_a_release_names_the_build_command(toy, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "-c", str(toy / "machinechecked.toml"), "--out", str(tmp_path / "x")])
    assert e.value.code == 2
    assert capsys.readouterr().err.strip() == \
        "machinechecked: no release: run `machinechecked build` first"
