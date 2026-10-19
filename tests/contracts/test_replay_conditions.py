"""A replay record says how Comparator ran (#108): the guard observed on the process (a Unix
socket forbidden, as `systemd-run --property=RestrictAddressFamilies=~AF_UNIX` does), the systemd
unit, the Landlock ABI, and the programs used with their SHA-256 and, for Comparator built in a
Git checkout, its commit. Stand-ins replace `lake` and Comparator, so no Lean is needed."""

import json
import os
import subprocess

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
    assert how["landlock_abi"] is None or how["landlock_abi"] >= 1
    # Under the guard (simulated), the record names it; without landrun it says so.
    monkeypatch.setattr(rp, "af_unix_blocked", lambda: True)
    monkeypatch.setattr(rp, "systemd_unit", lambda: "run-u7.service")
    monkeypatch.setenv("PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
    how = rp.replay(project, conf, out, comparator=str(comparator), lake=str(lake))["conditions"]
    assert how["guard"] == "RestrictAddressFamilies=~AF_UNIX" and how["af_unix_blocked"]
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
