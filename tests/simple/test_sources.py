"""Paper sources (`prooflens.sources`): a paper pinned in a Git repository."""

import os
import subprocess
from types import SimpleNamespace

from prooflens.config import Paper
from prooflens.sources import acquire

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


def manuscripts(tmp_path):
    """A manuscript repository: the paper on main, another draft on another branch."""
    repo = tmp_path / "manuscripts"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the paper")
    pinned = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "other-draft")
    (repo / "draft.tex").write_text("another paper\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "another draft")
    other = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return repo, pinned, other


def test_only_the_pinned_revision_is_fetched(tmp_path):
    repo, pinned, other = manuscripts(tmp_path)
    paper = Paper(id="P", title="A paper", root="paper.tex",
                  source={"git": f"file://{repo}", "rev": pinned})
    cfg = SimpleNamespace(root=tmp_path)
    snap = acquire(cfg, paper, tmp_path / "work" / "sources" / "P")
    assert snap.revision == pinned and snap.mode == "latex" and (snap.dir / "paper.tex").is_file()
    fetched = tmp_path / "work" / "sources" / ".P-repo"
    missing = subprocess.run(["git", "cat-file", "-e", f"{other}^{{commit}}"], cwd=fetched,
                             capture_output=True)
    assert missing.returncode != 0, "another branch's commit was fetched"


def test_an_abbreviated_revision_still_resolves(tmp_path):
    repo, pinned, _ = manuscripts(tmp_path)
    paper = Paper(id="P", title="A paper", root="paper.tex",
                  source={"git": f"file://{repo}", "rev": pinned[:10]})
    snap = acquire(SimpleNamespace(root=tmp_path), paper, tmp_path / "work" / "sources" / "P")
    assert snap.revision == pinned


def test_a_local_repository_given_by_relative_path_is_read_from_disk(tmp_path):
    """`git = "../manuscripts"` reads like `owner/repo`; a directory that exists is local."""
    repo, pinned, _ = manuscripts(tmp_path)
    cfg_dir = tmp_path / "audit"
    cfg_dir.mkdir()
    paper = Paper(id="P", title="A paper", root="paper.tex",
                  source={"git": "../manuscripts", "rev": pinned})
    snap = acquire(SimpleNamespace(root=cfg_dir), paper, tmp_path / "work" / "sources" / "P")
    assert snap.revision == pinned and (snap.dir / "paper.tex").is_file()
    assert not (tmp_path / "work" / "sources" / ".P-repo").exists()  # nothing fetched
