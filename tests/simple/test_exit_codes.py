"""Exit codes: 1 means the check ran and found a problem, 2 that it could not run. With --json a
check that could not run still prints one JSON document, saying so."""

import json
import os
import subprocess
import sys

import pytest

from prooflens import cli
from prooflens.simple import ViewError


def check(cwd, *args, env=None):
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json", *args],
                       cwd=cwd, capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def not_run(out: str) -> dict:
    d = json.loads(out)
    assert d["schema"] == "machinechecked/check@1" and d["ok"] is False
    return d["error"]


def test_a_missing_program_exits_2_with_a_json_error(tmp_path):
    (tmp_path / "lakefile.toml").write_text('name = "p"\n')
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    # No lake, latexmk or poppler on PATH: whichever is needed first is reported.
    code, out, err = check(tmp_path, env={**os.environ, "PATH": str(tmp_path / "nothing")})
    assert code == 2, err
    e = not_run(out)
    assert e["kind"] == "missing-tool" and e["tool"] in cli.MISSING and "not found" in err


def test_no_lean_project_exits_2_with_a_json_error(tmp_path):
    code, out, err = check(tmp_path)
    assert code == 2
    e = not_run(out)
    assert e["kind"] == "error" and "no Lean project" in e["message"] and "no Lean project" in err


def test_without_json_only_the_message_and_exit_2(tmp_path):
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode == 2 and r.stdout == "" and "no Lean project" in r.stderr


@pytest.mark.parametrize("error, kind", [
    (ViewError("the Lean probe failed: boom"), "error"),
    (KeyError("a bug"), "internal"),
])
def test_engine_errors_and_crashes_exit_2(monkeypatch, capsys, error, kind):
    def fail(a):
        raise error
    monkeypatch.setattr(cli, "_check_json", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--json"])
    assert exc.value.code == 2
    e = not_run(capsys.readouterr().out)
    assert e["kind"] == kind and (kind != "error" or e["message"] == "the Lean probe failed: boom")


def test_findings_still_exit_1(monkeypatch):
    def found(a):
        raise SystemExit(1)
    monkeypatch.setattr(cli, "_check_json", found)
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--json"])
    assert exc.value.code == 1


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0 and capsys.readouterr().out.strip().endswith(cli.tool_version())
