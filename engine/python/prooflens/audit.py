"""The audit descriptor: `audit.json` at the root of a published reader.

It says, in a few fields, what the audit is about and where its data is: the paper (and its
arXiv identifier and version when it has one), the Lean repository and commit, who published
the audit, where reports go, and the path of the reader's data. A site that indexes audits reads
this file and then the data it points to; it never runs anything an audit contains.

The descriptor records what its author states; it is not evidence of anything by itself.
"""

from __future__ import annotations

import datetime as _dt
import functools
import re
import subprocess
from pathlib import Path

SCHEMA = "machinechecked/audit@1"
NAME = "audit.json"

ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})"
                   r"(v\d+)?", re.I)
GITHUB = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


ARXIV_ID = re.compile(r"^arxiv:\s*([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(v\d+)?$", re.I)
DOI = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/\S+)$", re.I)


def arxiv_id(url: str | None) -> tuple[str, str | None] | None:
    """The arXiv identifier and version named by a URL or written `arXiv:2601.01234v2`
    (`arxiv:2601.01234`, `v2`), if any."""
    m = ARXIV.search(url or "") or ARXIV_ID.match((url or "").strip())
    return (f"arxiv:{m.group(1)}", m.group(2)) if m else None


def published_record(value: str) -> dict:
    """What a paper's `published` field names: an arXiv identifier and version, a DOI, or a URL."""
    ax = arxiv_id(value)
    if ax:
        return {"id": ax[0], "version": ax[1],
                "url": f"https://arxiv.org/abs/{ax[0].split(':', 1)[1]}{ax[1] or ''}"}
    d = DOI.match(value.strip())
    if d:
        return {"id": f"doi:{d.group(1)}", "version": None, "url": f"https://doi.org/{d.group(1)}"}
    return {"id": None, "version": None,
            "url": value if value.startswith(("https://", "http://")) else None}


def github_repository(path: Path) -> str | None:
    """`owner/repo` of the GitHub remote `origin` of the repository at `path`, if there is one."""
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=path, capture_output=True,
                       text=True)
    m = GITHUB.search(r.stdout.strip()) if r.returncode == 0 else None
    return f"{m.group(1)}/{m.group(2)}" if m else None


def toolchain(path: Path) -> str | None:
    p = path / "lean-toolchain"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else None


def descriptor(index: dict, lean_root: Path | None, author: str | None = None,
               paper_url: str | None = None) -> dict:
    """The descriptor of a reader whose data index is `index`."""
    papers = []
    for p in index.get("papers", []):
        ax = arxiv_id(paper_url) if len(index.get("papers", [])) == 1 else None
        entry = {"title": p.get("title"), "id": ax[0] if ax else None,
                 "version": ax[1] if ax else None, "url": paper_url,
                 "revision": p.get("revision")}
        # A paper whose configuration names its published version: that is the public record
        # this audit corresponds to, with how the audited revision differs from it.
        if p.get("published"):
            entry.update(published_record(p["published"]))
        if p.get("published_note"):
            entry["note"] = p["published_note"]
        papers.append(entry)
    project = index.get("project") or {}
    return {
        "schema": SCHEMA,
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": "machinechecked",
        "author": author,
        "papers": papers,
        "formalisation": {
            "repository": project.get("repository") or (github_repository(lean_root)
                                                         if lean_root else None),
            "repository_private": bool(project.get("repository_private")),
            "commit": project.get("commit"),
            "toolchain": project.get("toolchain") or (toolchain(lean_root) if lean_root
                                                      else None),
        },
        "release": index.get("release"),
        "data": "data/index.json",
        "issues": index.get("issues"),
        "site_url": index.get("site_url"),
    }


@functools.lru_cache(maxsize=None)
def source_root(lean_root: Path) -> tuple[Path, str] | None:
    """The Git work tree holding the Lean project, and the project's path inside it (`""` at
    its root, else `"sub/dir/"`)."""
    r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=lean_root,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    top = Path(r.stdout.strip()).resolve()
    rel = lean_root.resolve().relative_to(top).as_posix()
    return top, ("" if rel == "." else rel + "/")


def source_path(lean_root: Path, module: str | None) -> str | None:
    """The path of a module's file in the project's Git repository, if the file is in the
    project rather than in a dependency."""
    if not module or not re.fullmatch(r"[\w.']+", module):
        return None
    sr = source_root(lean_root)
    rel = module.replace(".", "/") + ".lean"
    if sr is None or not (lean_root / rel).is_file():
        return None
    return sr[1] + rel


def source_info(lean_root: Path | None, roots: list[str], repository: str | None = None,
                private: bool = False) -> dict:
    """Where the reader's Lean source links point: the GitHub repository (given, else the
    project's `origin` remote), whether it is private (the reader then does not show its name;
    the links still name it), the project's path inside it, and the top-level module names whose
    files are the project's own."""
    if lean_root is None:
        return {}
    sr = source_root(lean_root)
    return {"repository": repository or github_repository(lean_root),
            "repository_private": bool(private),
            "source_prefix": sr[1] if sr else None,
            "source_roots": sorted(r for r in roots if (lean_root / r).is_dir()
                                   or (lean_root / f"{r}.lean").is_file())}
