"""The engine's messages name the command `machinechecked` (#384). `prooflens` is an alias of
the command and the name of the Python package; no message tells the reader to run it. The
command's `--help` lists the everyday commands and names the others, which `help --all` lists
(#79)."""

import argparse
import ast
import re
import sys
import tomllib
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


ROOT = ENGINE.parents[2]


def help_text(capsys, *args) -> str:
    try:
        cli.main(list(args))
    except SystemExit as e:
        assert e.code == 0
    return capsys.readouterr().out


def test_both_names_are_one_command_and_name_themselves(monkeypatch, capsys):
    """`machinechecked` and its alias `prooflens` run the same entry point; each names itself
    in its usage."""
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "scripts"]
    assert scripts["machinechecked"] == scripts["prooflens"] == "prooflens.cli:main"
    for name in ("machinechecked", "prooflens"):
        monkeypatch.setattr(sys, "argv", [f"/some/bin/{name}"])
        assert help_text(capsys, "--help").startswith(f"usage: {name} [-h] [--version] "
                                                      "{view,build,check,review} ...")


def test_help_lists_the_everyday_commands_and_names_every_other(capsys):
    """#79: `--help` lists view, build, check and review; its last lines name every other
    command, and `help --all` lists each one, by group, with what it does."""
    out = help_text(capsys, "--help")
    listed = re.findall(r"^    (\w+) ", out.split("positional arguments:")[1].split("options:")[0],
                        re.M)
    assert listed == ["view", "build", "check", "review"]
    every = [n for _, n, _ in cli.COMMANDS]
    further = re.search(r"Further commands: (.*?)\. ", " ".join(out.split())).group(1)
    assert further.split(", ") == [n for n in every if n not in listed]
    assert "help --all" in out
    full = help_text(capsys, "help", "--all")
    assert re.findall(r"^  (\w+) ", full, re.M) == every
    for group in dict.fromkeys(g for g, _, _ in cli.COMMANDS):
        assert f"\n{group}:\n" in f"\n{full}"


def test_every_command_of_the_parser_is_in_the_command_list(capsys):
    """No command is left out of `help --all`, and each one's own --help works."""
    (sub,) = [x for x in cli._parser()._actions if isinstance(x, argparse._SubParsersAction)]
    assert set(sub.choices) == {n for _, n, _ in cli.COMMANDS} | {"help"}
    for name in sub.choices:
        assert help_text(capsys, name, "--help").startswith(f"usage: machinechecked {name} ")
        assert help_text(capsys, "help", name) == help_text(capsys, name, "--help")


def test_export_without_a_release_names_the_build_command(toy, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["export", "-c", str(toy / "machinechecked.toml"), "--out", str(tmp_path / "x")])
    assert e.value.code == 2
    assert capsys.readouterr().err.strip() == \
        "machinechecked: no release: run `machinechecked build` first"
