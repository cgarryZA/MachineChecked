"""Acquire a paper's source at a pinned revision, and decide between LaTeX and PDF.

Acquisition is the only stage that may use credentials; it writes a plain snapshot directory and
nothing it produces is executed. Compilation (`tex.py`) works on a copy of the snapshot.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import io
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Paper
from .util import link_or_copy


class SourceError(RuntimeError):
    pass


@dataclass
class Snapshot:
    paper: str
    dir: Path
    kind: str                 # "path" | "git" | "arxiv"
    revision: str | None      # commit for git, version for arXiv, None for a working tree
    mode: str                 # "latex" | "pdf"
    root: str | None          # LaTeX root, relative to `dir`
    pdf: str | None           # committed or provided PDF, relative to `dir`
    note: str = ""
    commit_time: int | None = None


DOCCLASS = re.compile(r"^[^%\n]*\\documentclass", re.M)


def _latex_roots(d: Path) -> list[str]:
    roots = []
    for p in sorted(d.rglob("*.tex")):
        try:
            if DOCCLASS.search(p.read_text(encoding="utf-8", errors="replace")):
                roots.append(str(p.relative_to(d)))
        except OSError:
            continue
    return roots


SKIP = (".git", ".lake", ".machinechecked", ".prooflens")


def _has_latex_root(d: Path) -> bool:
    """Whether a copy of `d` (without the directories a snapshot leaves out) has a LaTeX root."""
    for top, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP]
        for f in files:
            if f.endswith(".tex"):
                try:
                    if DOCCLASS.search((Path(top) / f).read_text(encoding="utf-8",
                                                                errors="replace")):
                        return True
                except OSError:
                    continue
    return False


def _pdfs(d: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) for p in d.rglob("*.pdf"))


def choose(paper: Paper, d: Path) -> tuple[str, str | None, str | None, str]:
    """LaTeX if a root is found, else the PDF of the same source. Several candidate roots or PDFs
    without an explicit choice is an error, not a guess."""
    pdfs = _pdfs(d)
    pdf = paper.pdf if paper.pdf else None
    if pdf and not (d / pdf).exists():
        raise SourceError(f"paper {paper.id}: pdf {pdf} not in the source")
    if paper.root:
        if not (d / paper.root).exists():
            raise SourceError(f"paper {paper.id}: root {paper.root} not in the source")
        return "latex", paper.root, pdf, ""
    roots = _latex_roots(d)
    if len(roots) == 1:
        return "latex", roots[0], pdf, ""
    if len(roots) > 1:
        raise SourceError(f"paper {paper.id}: several LaTeX roots {roots}; set `root`")
    if pdf:
        return "pdf", None, pdf, "no LaTeX root in the source"
    if len(pdfs) == 1:
        return "pdf", None, pdfs[0], "no LaTeX root in the source"
    if not pdfs:
        raise SourceError(f"paper {paper.id}: neither a LaTeX root nor a PDF in the source")
    raise SourceError(f"paper {paper.id}: no LaTeX root and several PDFs {pdfs}; set `pdf`")


def _git_url(spec: str) -> str:
    if re.fullmatch(r"[\w.-]+/[\w.-]+", spec):
        return f"https://github.com/{spec}.git"
    return spec


def _git_env(paper: Paper) -> dict:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    tok_var = paper.source.get("token_env")
    if tok_var and os.environ.get(tok_var):
        import base64
        cred = base64.b64encode(f"x-access-token:{os.environ[tok_var]}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {cred}"
    return env


def acquire(cfg: Config, paper: Paper, dest: Path) -> Snapshot:
    src = paper.source
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if "path" in src:
        base = (cfg.root / src["path"]).resolve()
        if not base.is_dir():
            raise SourceError(f"paper {paper.id}: {base} is not a directory")
        if paper.pdf and not paper.root and (base / paper.pdf).is_file() \
                and not _has_latex_root(base):
            # A paper that is only a PDF needs only that file, not the directory it is in (the
            # source would be read as the same PDF either way).
            link_or_copy(base / paper.pdf, dest / paper.pdf)
        else:
            shutil.copytree(base, dest, dirs_exist_ok=True, copy_function=shutil.copy2,
                            ignore_dangling_symlinks=True,
                            ignore=shutil.ignore_patterns(*SKIP, "*.aux", "*.log", "*.fls"))
        kind, rev, commit_time = "path", None, None
    elif "git" in src:
        rev = src.get("rev")
        if not rev:
            raise SourceError(f"paper {paper.id}: a git source needs `rev` (a commit)")
        sub = src.get("subdir")
        # A directory that exists (relative to the configuration) is a local repository, even
        # when it reads like `owner/repo` ("../repo"); otherwise `owner/repo` is on GitHub.
        on_disk = (cfg.root / src["git"]).resolve()
        local = on_disk if on_disk.is_dir() or not (
            re.fullmatch(r"[\w.-]+/[\w.-]+", src["git"])
            or src["git"].startswith(("http", "git@", "file://"))) else None
        env = _git_env(paper)
        target = rev
        if local and local.exists():
            repo = local
        else:
            # Only the pinned revision is fetched: a manuscript repository's other branches
            # (other papers, drafts) are neither downloaded nor copied here.
            repo = dest.parent / f".{paper.id}-repo"
            if not (repo / ".git").exists():
                repo.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", "--quiet"], cwd=repo, capture_output=True)
                subprocess.run(["git", "remote", "add", "origin", _git_url(src["git"])],
                               cwd=repo, capture_output=True)
            r = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "--depth", "1",
                                "origin", rev], env=env, capture_output=True, text=True)
            if r.returncode == 0:
                target = "FETCH_HEAD"
            else:
                # A revision the server will not give by name (an abbreviated commit): fetch the
                # history, as before, and find it there.
                r = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"],
                                   env=env, capture_output=True, text=True)
                if r.returncode != 0:
                    raise SourceError(f"paper {paper.id}: fetch failed: {r.stderr.strip()}")
        full = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify",
                               f"{target}^{{commit}}"], capture_output=True, text=True)
        if full.returncode != 0:
            raise SourceError(f"paper {paper.id}: revision {rev} not found")
        rev = full.stdout.strip()
        ct = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%ct", rev],
                            capture_output=True, text=True)
        commit_time = int(ct.stdout.strip()) if ct.returncode == 0 else None
        args = ["git", "-C", str(repo), "archive", "--format=tar", rev] + ([sub] if sub else [])
        arch = subprocess.run(args, capture_output=True)
        if arch.returncode != 0:
            raise SourceError(f"paper {paper.id}: git archive failed: {arch.stderr.decode()}")
        with tarfile.open(fileobj=io.BytesIO(arch.stdout)) as t:
            t.extractall(dest, filter="data")
        kind = "git"
    else:
        raise SourceError(f"paper {paper.id}: arXiv sources are not supported yet")
    mode, root, pdf, note = choose(paper, dest)
    return Snapshot(paper.id, dest, kind, rev, mode, root, pdf, note, commit_time)
