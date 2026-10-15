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
        shutil.copytree(base, dest, dirs_exist_ok=True, copy_function=shutil.copy2,
                        ignore=shutil.ignore_patterns(".git", "*.aux", "*.log", "*.fls"))
        kind, rev, commit_time = "path", None, None
    elif "git" in src:
        rev = src.get("rev")
        if not rev:
            raise SourceError(f"paper {paper.id}: a git source needs `rev` (a commit)")
        sub = src.get("subdir")
        local = (cfg.root / src["git"]).resolve() if not re.fullmatch(
            r"[\w.-]+/[\w.-]+", src["git"]) and not src["git"].startswith(("http", "git@")) \
            else None
        env = _git_env(paper)
        if local and local.exists():
            repo = local
        else:
            repo = dest.parent / f".{paper.id}-repo"
            if not repo.exists():
                r = subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                                    _git_url(src["git"]), str(repo)], env=env,
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise SourceError(f"paper {paper.id}: clone failed: {r.stderr.strip()}")
            subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin", rev], env=env,
                           capture_output=True)
        full = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{rev}^{{commit}}"],
                              capture_output=True, text=True)
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


def branch_ahead(cfg: Config, paper: Paper, branch: str) -> int | None:
    """How many commits `branch` has beyond the pinned revision (informational drift)."""
    if "git" not in paper.source or not paper.source.get("rev"):
        return None
    local = (cfg.root / paper.source["git"]).resolve()
    if not local.exists():
        return None
    r = subprocess.run(["git", "-C", str(local), "rev-list", "--count",
                        f"{paper.source['rev']}..{branch}"], capture_output=True, text=True)
    return int(r.stdout.strip()) if r.returncode == 0 else None
