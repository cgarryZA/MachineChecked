"""A replay runs Comparator under its sandbox guard when the machine can, and the record says how
it ran (#108): the guard and how it came to hold (started by `replay`, inherited, unavailable or
opted out), the systemd unit, the Landlock ABI, and the programs used with their SHA-256 and, for
Comparator built in a Git checkout, its commit. Stand-ins replace `lake`, Comparator and
`systemd-run`, so no Lean or systemd is needed."""

import json
import os
import subprocess
import sys

from prooflens import replay as rp

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@x"}


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, **ENV})


def script(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)
    return path


def setup(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "lean-toolchain").write_text("leanprover/lean4:v4.32.0\n")
    (project / "Main.lean").write_text("theorem t : True := trivial\n")
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "p")
    tools = tmp_path / "comparator-src"
    comparator = script(tools / ".lake" / "build" / "bin" / "comparator", "echo checked")
    (tools / "lakefile.toml").write_text('name = "comparator"\n')
    git(tools, "init", "-q")
    git(tools, "add", "-A")
    git(tools, "commit", "-q", "-m", "c")
    lake = script(tmp_path / "bin" / "lake", 'shift\nexec "$@"')  # `lake env X` runs X
    bin_ = tmp_path / "path"
    script(bin_ / "landrun", "true")
    script(bin_ / "nanoda_bin", "true")
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("COMPARATOR_LANDRUN", raising=False)
    monkeypatch.setenv("COMPARATOR_LEAN4EXPORT", str(script(tmp_path / "other" / "export", "true")))
    conf = tmp_path / "comparator.json"
    conf.write_text(json.dumps({"challenge_module": "C", "solution_module": "S",
                                "theorem_names": ["t"], "enable_nanoda": True}))
    return project, conf, comparator, lake, tools


def test_the_record_says_how_comparator_ran(tmp_path, monkeypatch):
    project, conf, comparator, lake, tools = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(rp, "guard_prefix", lambda cwd, unit: None)  # no guard on this machine
    out = tmp_path / "replay.json"
    rec = rp.replay(project, conf, out, comparator=str(comparator), lake=str(lake))
    assert rec["passed"] and json.loads(out.read_text())["conditions"] == rec["conditions"]
    how = rec["conditions"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tools, capture_output=True,
                          text=True).stdout.strip()
    assert how["comparator"] == {"path": os.path.realpath(comparator),
                                 "sha256": rp.sha256_file(comparator), "commit": head}
    assert how["landrun"]["path"] == os.path.realpath(tmp_path / "path" / "landrun")
    assert how["lean4export"]["path"] == os.path.realpath(tmp_path / "other" / "export")
    assert how["nanoda"]["path"] == os.path.realpath(tmp_path / "path" / "nanoda_bin")
    assert how["landrun"]["commit"] is None  # not built in a Lake project's checkout
    # Run as here, a Unix socket can be opened: no guard, and the record says so.
    assert how["guard"] == "none" and how["af_unix_blocked"] is False
    assert how["guard_mode"] == "unavailable"
    assert how["landlock_abi"] is None or how["landlock_abi"] >= 1
    # Under the guard (simulated), the record names it; without landrun it says so.
    monkeypatch.setattr(rp, "af_unix_blocked", lambda: True)
    monkeypatch.setattr(rp, "systemd_unit", lambda: "run-u7.service")
    monkeypatch.setenv("PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
    how = rp.replay(project, conf, out, comparator=str(comparator), lake=str(lake))["conditions"]
    assert how["guard"] == "RestrictAddressFamilies=~AF_UNIX" and how["af_unix_blocked"]
    assert how["guard_mode"] == "inherited"
    assert how["systemd_unit"] == "run-u7.service" and how["landrun"] is None


def test_the_unit_is_read_from_the_cgroup(monkeypatch):
    texts = {"0::/user.slice/user-1000.slice/user@1000.service/app.slice/run-u12.service\n":
             "run-u12.service", "0::/\n": None}
    real = rp.Path.read_text
    for text, unit in texts.items():
        monkeypatch.setattr(rp.Path, "read_text",
                            lambda self, *a, t=text, **k: t if str(self) == "/proc/self/cgroup"
                            else real(self, *a, **k))
        assert rp.systemd_unit() == unit


# A stand-in for `systemd-run`: it logs its options (without the environment) and command, answers
# the socket check as the guard would when FAKE_GUARD_HOLDS is set, and runs other commands in the
# working directory and environment it was given.
SYSTEMD_RUN = f"""#!{sys.executable}
import json, os, subprocess, sys
args = sys.argv[1:]
i = args.index("--")
opts, cmd = args[:i], args[i + 1:]
with open(os.environ["FAKE_SYSTEMD_LOG"], "a") as f:
    f.write(json.dumps([o for o in opts if not o.startswith("--setenv=")] + ["--"] + cmd) + "\\n")
if "-c" in cmd:
    sys.exit(0 if os.environ.get("FAKE_GUARD_HOLDS") else 3)
env = dict(o[len("--setenv="):].split("=", 1) for o in opts if o.startswith("--setenv="))
cwd = next(o.split("=", 1)[1] for o in opts if o.startswith("--working-directory="))
sys.exit(subprocess.run(cmd, cwd=cwd, env=env).returncode)
"""


def systemd(tmp_path, monkeypatch):
    stub = tmp_path / "systemd-bin" / "systemd-run"
    stub.parent.mkdir()
    stub.write_text(SYSTEMD_RUN)
    stub.chmod(0o755)
    log = tmp_path / "systemd.log"
    monkeypatch.setenv("PATH", f"{stub.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SYSTEMD_LOG", str(log))
    monkeypatch.setattr(rp, "af_unix_blocked", lambda: False)
    return lambda: [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def test_replay_starts_the_guard_when_the_machine_can(tmp_path, monkeypatch):
    project, conf, comparator, lake, tools = setup(tmp_path, monkeypatch)
    calls = systemd(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_GUARD_HOLDS", "1")
    rec = rp.replay(project, conf, tmp_path / "r.json", comparator=str(comparator),
                    lake=str(lake))
    how = rec["conditions"]
    assert rec["passed"] and "checked" in rec["output_tail"]
    assert how["guard"] == rp.GUARD and how["guard_mode"] == "started"
    assert how["systemd_unit"].startswith("machinechecked-replay-")
    check, run = calls()
    assert check[check.index("--") + 1:][:2] == [sys.executable, "-I"]  # the socket check first
    assert f"--property={rp.GUARD}" in run and "--user" in run and "--wait" in run
    assert f"--unit={how['systemd_unit']}" in run and f"--working-directory={project}" in run
    assert run[run.index("--") + 1:] == [str(lake), "env", str(comparator), str(conf)]


def test_replay_runs_unguarded_when_the_guard_does_not_hold_or_is_declined(tmp_path, monkeypatch):
    project, conf, comparator, lake, tools = setup(tmp_path, monkeypatch)
    calls = systemd(tmp_path, monkeypatch)
    monkeypatch.delenv("FAKE_GUARD_HOLDS", raising=False)
    # systemd-run is there, but the unit could still open a Unix socket: run directly.
    rec = rp.replay(project, conf, tmp_path / "r.json", comparator=str(comparator),
                    lake=str(lake))
    assert rec["passed"] and rec["conditions"]["guard"] == "none"
    assert rec["conditions"]["guard_mode"] == "unavailable" and len(calls()) == 1
    # Opted out: systemd-run is not asked at all, even where the guard would hold.
    monkeypatch.setenv("FAKE_GUARD_HOLDS", "1")
    rec = rp.replay(project, conf, tmp_path / "r.json", comparator=str(comparator),
                    lake=str(lake), guard=False)
    assert rec["passed"] and rec["conditions"]["guard"] == "none"
    assert rec["conditions"]["guard_mode"] == "opted-out" and len(calls()) == 1


def test_the_summary_says_when_replays_ran_without_the_guard():
    def assessment(*facts):
        return {"claims": [{"clauses": [{"checks": {"replay": f}} for f in facts]}]}
    assert rp.guard_summary(assessment({"state": "not-run"})) is None
    assert rp.guard_summary(assessment({"state": "pass", "guard": "guarded"})) == \
        {"guard": "guarded", "replayed": 1, "message": None}
    got = rp.guard_summary(assessment({"state": "pass", "guard": "unguarded"},
                                      {"state": "pass", "guard": "unguarded"}))
    assert got["message"] == "2 proof(s) replayed without the sandbox guard"
    assert rp.guard_summary(assessment({"state": "pass", "guard": "unrecorded"}))["guard"] == \
        "unrecorded"
