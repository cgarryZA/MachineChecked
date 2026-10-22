"""Exit codes: 1 means the check ran and found a problem, 2 that it could not run. With --json a
check that could not run still prints one JSON document, saying so. A command whose output's
reader stops reading exits quietly with 141 (128 + SIGPIPE)."""

import json
import os
import signal
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


def test_a_missing_program_is_reported_before_a_paper_is_downloaded(tmp_path):
    (tmp_path / "lakefile.toml").write_text('name = "p"\n')
    code, out, err = check(tmp_path, "https://example.invalid/paper.pdf",
                           env={**os.environ, "PATH": str(tmp_path / "nothing")})
    assert code == 2 and not_run(out)["kind"] == "missing-tool"
    assert "downloading" not in err and not (tmp_path / ".machinechecked").exists()


# A command (`validate`, replaced) that writes a long output; or a short one, still buffered
# when it returns, once its reader has gone; or into a pipe of its own whose reader has gone.
WRITER = '''
import select, subprocess, sys, time
from prooflens import cli

def run(a):
    if a.file == "long":
        for i in range(100000):
            print(f"line {i} of a long output")
    elif a.file == "buffered":
        print("a short output")
        poll = select.poll()
        poll.register(sys.stdout.fileno(), select.POLLOUT)
        while not any(ev & select.POLLERR for _, ev in poll.poll(0)):
            time.sleep(0.01)
    else:
        p = subprocess.Popen(["true"], stdin=subprocess.PIPE)
        p.wait()
        p.stdin.write(b"x" * 100000)

cli.cmd_validate = run
cli.main(["validate", sys.argv[1], "--schema", "inventory"])
'''


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason="no SIGPIPE on this platform")
@pytest.mark.parametrize("output", ["long", "buffered"])
def test_a_reader_that_stops_reading_ends_the_command_quietly(output):
    """`machinechecked … | head`: once the reader closes the pipe, the command stops with the
    status of a program stopped by SIGPIPE, and prints nothing more, on either stream."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}  # output buffered
    p = subprocess.Popen([sys.executable, "-c", WRITER, output], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, env=env)
    if output == "long":
        assert p.stdout.readline() == "line 0 of a long output\n"
    p.stdout.close()
    err = p.stderr.read()
    assert p.wait(timeout=60) == 128 + signal.SIGPIPE and err == ""


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason="no SIGPIPE on this platform")
def test_a_broken_pipe_of_the_command_s_own_is_an_error():
    r = subprocess.run([sys.executable, "-c", WRITER, "own"], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 2
    assert "unexpected error (BrokenPipeError" in r.stderr and "Traceback" in r.stderr


def test_the_full_assessment_records_the_installed_release():
    from importlib.metadata import version
    from prooflens import pipeline
    assert pipeline.tool_version() == version("machinechecked")
