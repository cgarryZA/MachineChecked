"""`check --fix-modules`: the modules it adds to `modules`, and how it edits the configuration."""

import tomllib

import pytest

from prooflens import cli
from prooflens import config as cfgmod
from prooflens import evidence as ev
from prooflens.config import ConfigError, add_modules

NEW = ["Pkg.Spec.New", "Pkg.Acceptance.New"]


@pytest.mark.parametrize("before, after", [
    # On one line: appended on that line, the line's comment kept.
    ('[project]\nname = "p"\nmodules = ["Pkg"]  # the root\nscope_roots = ["Pkg"]\n',
     '[project]\nname = "p"\nmodules = ["Pkg", "Pkg.Spec.New", "Pkg.Acceptance.New"]  # the root\n'
     'scope_roots = ["Pkg"]\n'),
    ('[project]\nmodules = ["Pkg", ]\n',
     '[project]\nmodules = ["Pkg", "Pkg.Spec.New", "Pkg.Acceptance.New", ]\n'),
    # One per line: the last element's indentation and trailing comma.
    ('[project]\nmodules = [\n    "Pkg",  # first\n    "Pkg.Defs",\n]\n\n[[paper]]\nid = "A"\n',
     '[project]\nmodules = [\n    "Pkg",  # first\n    "Pkg.Defs",\n    "Pkg.Spec.New",\n'
     '    "Pkg.Acceptance.New",\n]\n\n[[paper]]\nid = "A"\n'),
    ('[project]\nmodules = [\n  "Pkg",\n  "Pkg.Defs"  # last\n]\n',
     '[project]\nmodules = [\n  "Pkg",\n  "Pkg.Defs",  # last\n  "Pkg.Spec.New",\n'
     '  "Pkg.Acceptance.New"\n]\n'),
    ('[project]\nmodules = ["Pkg",\n           "Pkg.Defs"]\n',
     '[project]\nmodules = ["Pkg",\n           "Pkg.Defs",\n           "Pkg.Spec.New",\n'
     '           "Pkg.Acceptance.New"]\n'),
    # Literal strings stay literal; Windows line endings stay.
    ("[project]\nmodules = ['Pkg']\n",
     "[project]\nmodules = ['Pkg', 'Pkg.Spec.New', 'Pkg.Acceptance.New']\n"),
    ('[project]\r\nmodules = [\r\n  "Pkg",\r\n]\r\nname = "p"\r\n',
     '[project]\r\nmodules = [\r\n  "Pkg",\r\n  "Pkg.Spec.New",\r\n  "Pkg.Acceptance.New",\r\n]\r\n'
     'name = "p"\r\n'),
    # Only the `modules` of [project] is edited.
    ('[tool]\nmodules = ["Other"]\n\n[ project ]  # the audit\nmodules = ["Pkg"]\n',
     '[tool]\nmodules = ["Other"]\n\n[ project ]  # the audit\n'
     'modules = ["Pkg", "Pkg.Spec.New", "Pkg.Acceptance.New"]\n'),
])
def test_modules_are_appended_and_every_other_byte_is_kept(tmp_path, before, after):
    p = tmp_path / "machinechecked.toml"
    p.write_bytes(before.encode())
    assert add_modules(p, NEW + ["Pkg"]) == NEW
    assert p.read_bytes().decode() == after
    assert tomllib.loads(after)["project"]["modules"][-2:] == NEW


def test_an_empty_list_gets_the_modules(tmp_path):
    p = tmp_path / "machinechecked.toml"
    p.write_text('[project]\nmodules = []  # none yet\n')
    assert add_modules(p, NEW) == NEW
    assert p.read_text() == ('[project]\nmodules = ["Pkg.Spec.New", "Pkg.Acceptance.New"]'
                             '  # none yet\n')


def test_listed_modules_are_not_added_again(tmp_path):
    p = tmp_path / "machinechecked.toml"
    p.write_text('[project]\nmodules = ["Pkg", "Pkg.Spec.New"]\n')
    assert add_modules(p, ["Pkg.Spec.New", "Pkg"]) == []
    assert p.read_text() == '[project]\nmodules = ["Pkg", "Pkg.Spec.New"]\n'


@pytest.mark.parametrize("text", [
    'project = { name = "p", modules = ["Pkg"] }\n',     # an inline table
    'project.modules = ["Pkg"]\n',                       # a dotted key
    '[project]\nmodules = ["""Pkg"""]\n',                # a multi-line string
    '[project]\nmodules = "Pkg"\n',                      # not a list
])
def test_a_modules_it_cannot_extend_in_place_is_left_as_it_is(tmp_path, text):
    p = tmp_path / "machinechecked.toml"
    p.write_text(text)
    with pytest.raises(ConfigError):
        add_modules(p, NEW)
    assert p.read_text() == text


def _project(tmp_path, unlisted, monkeypatch):
    """A configuration whose last build found `unlisted` (name: declaring modules)."""
    p = tmp_path / "machinechecked.toml"
    p.write_text('[project]\nname = "p"\nmodules = ["Pkg"]\nscope_roots = ["Pkg"]\n'
                 'spec_prefix = "Pkg.Spec"\naccept_prefix = "Pkg.Acceptance"\n'
                 'inventory = "claims.json"\n')
    monkeypatch.setattr(ev, "load", lambda out, eid: {"body": {"assessment": {
        "claims": [], "findings": [], **({"unlisted_modules": unlisted} if unlisted else {})}}})
    return cfgmod.load(p)


def test_the_modules_the_assessment_names_are_added_and_checked_again(tmp_path, monkeypatch,
                                                                       capsys):
    cfg = _project(tmp_path, {"Pkg.Spec.main": ["Pkg.Spec.New"],
                              "Pkg.Acceptance.main": ["Pkg.Acceptance.New"],
                              "Pkg.Acceptance.main_hypotheses": ["Pkg.Acceptance.New"],
                              "Pkg.helper": ["Pkg.ScratchA", "Pkg.ScratchB"]}, monkeypatch)
    rebuilt = []
    cfg2, res, added = cli._fix_modules(cfg, {"evidence": "e1"},
                                        lambda c: rebuilt.append(c.modules) or {"evidence": "e2"})
    # A name two unlisted modules declare adds neither: the module meant is the author's call.
    assert added == ["Pkg.Acceptance.New", "Pkg.Spec.New"]
    assert cfg2.modules == ["Pkg", "Pkg.Acceptance.New", "Pkg.Spec.New"]
    assert rebuilt == [cfg2.modules] and res == {"evidence": "e2"}
    out = capsys.readouterr().out
    assert ("--fix-modules: Pkg.helper is declared in Pkg.ScratchA and Pkg.ScratchB, none of "
            "which is listed in `modules`: list the one meant") in out
    assert "--fix-modules: added to `modules` in machinechecked.toml:" in out
    assert ("  Pkg.Acceptance.New, which declares Pkg.Acceptance.main, "
            "Pkg.Acceptance.main_hypotheses") in out
    assert "  Pkg.Spec.New, which declares Pkg.Spec.main" in out


def test_nothing_to_add_builds_nothing_again(tmp_path, monkeypatch, capsys):
    cfg = _project(tmp_path, {}, monkeypatch)
    before = cfg.path.read_bytes()
    cfg2, res, added = cli._fix_modules(cfg, {"evidence": "e1"},
                                        lambda c: pytest.fail("built again"))
    assert (added, res, cfg2) == ([], {"evidence": "e1"}, cfg)
    assert cfg.path.read_bytes() == before
    assert "--fix-modules: nothing to add to `modules`" in capsys.readouterr().out


def test_a_configuration_it_cannot_edit_gives_the_list_to_paste(tmp_path, monkeypatch):
    cfg = _project(tmp_path, {"Pkg.Spec.main": ["Pkg.Spec.New"]}, monkeypatch)
    cfg.path.write_text(cfg.path.read_text().replace('modules = ["Pkg"]',
                                                     'modules = ["""Pkg"""]'))
    with pytest.raises(SystemExit) as e:
        cli._fix_modules(cfg, {"evidence": "e1"}, lambda c: pytest.fail("built again"))
    assert str(e.value.code).endswith('list them by hand: modules = ["Pkg", "Pkg.Spec.New"]')


def test_zero_configuration_has_no_modules_to_fix(tmp_path, monkeypatch, capsys):
    (tmp_path / "lakefile.toml").write_text('name = "p"\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as e:
        cli.main(["check", "--fix-modules"])
    assert e.value.code == 2
    assert "only a project with a machinechecked.toml lists `modules`" in capsys.readouterr().err
