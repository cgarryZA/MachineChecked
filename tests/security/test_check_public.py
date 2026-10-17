"""scripts/check_public.py: 0 when nothing private is found, 1 when something is, 2 when the
check cannot run (never a crash that reads as either)."""

import os
import subprocess
import sys

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "check_public.py"
ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}


def run(repo, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, capture_output=True,
                          text=True, env=ENV)


def repo_with(tmp_path, text):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "Notes.lean").write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "notes ×"], cwd=repo, check=True, env=ENV)
    return repo


def test_found_clean_and_could_not_run(tmp_path):
    repo = repo_with(tmp_path, "-- a bound: n × m ≤ C … for SecretProject\n")
    deny = tmp_path / "deny.txt"
    deny.write_text("secretproject\n")
    found = run(repo, "--denylist", str(deny), "--range", "HEAD~0")
    assert found.returncode == 1 and "Notes.lean" in found.stdout
    deny.write_text("nothing-like-this\n")
    assert run(repo, "--denylist", str(deny)).returncode == 0
    gone = run(repo, "--denylist", str(tmp_path / "missing.txt"))
    assert gone.returncode == 2 and "could not run" in gone.stderr
    bad = run(repo, "--denylist", str(deny), "--range", "nosuchref..HEAD")
    assert bad.returncode == 2 and "could not run" in bad.stderr


def test_an_allowed_published_string_is_not_an_occurrence(tmp_path):
    repo = repo_with(tmp_path, "-- Formalises: Public Paper on Widgets (widgets-public-lean)\n"
                               "-- see also widgets-private\n")
    deny = tmp_path / "deny.txt"
    deny.write_text("widgets\n")
    allow = tmp_path / "allow.txt"
    allow.write_text("Public Paper on Widgets\nwidgets-public-lean\n")
    r = run(repo, "--denylist", str(deny), "--allow", str(allow))
    # The published title and repository pass; the private name on the next line does not.
    assert r.returncode == 1 and "widgets-private" in r.stdout and "Public Paper" not in r.stdout
    (repo / "Notes.lean").write_text("-- Formalises: Public Paper on Widgets (widgets-public-lean)\n")
    subprocess.run(["git", "commit", "-qam", "public only"], cwd=repo, check=True, env=ENV)
    assert run(repo, "--denylist", str(deny), "--allow", str(allow)).returncode == 0
