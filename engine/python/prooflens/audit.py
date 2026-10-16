"""The audit descriptor: `audit.json` at the root of a published reader.

It says, in a few fields, what the audit is about and where its data is: the paper (and its
arXiv identifier and version when it has one), the Lean repository and commit, who published
the audit, where reports go, and the path of the reader's data. A site that indexes audits reads
this file and then the data it points to; it never runs anything an audit contains.

The descriptor records what its author states; it is not evidence of anything by itself.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
from pathlib import Path

SCHEMA = "machinechecked/audit@1"
NAME = "audit.json"

ARXIV = re.compile(r"arxiv\.org/(?:abs|pdf)/([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})"
                   r"(v\d+)?", re.I)
GITHUB = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def arxiv_id(url: str | None) -> tuple[str, str | None] | None:
    """The arXiv identifier and version named by a URL (`arxiv:2601.01234`, `v2`), if any."""
    m = ARXIV.search(url or "")
    return (f"arxiv:{m.group(1)}", m.group(2)) if m else None


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
        papers.append({"title": p.get("title"), "id": ax[0] if ax else None,
                       "version": ax[1] if ax else None, "url": paper_url,
                       "revision": p.get("revision")})
    project = index.get("project") or {}
    return {
        "schema": SCHEMA,
        "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "tool": "machinechecked",
        "author": author,
        "papers": papers,
        "formalisation": {
            "repository": github_repository(lean_root) if lean_root else None,
            "commit": project.get("commit"),
            "toolchain": project.get("toolchain") or (toolchain(lean_root) if lean_root
                                                      else None),
        },
        "release": index.get("release"),
        "data": "data/index.json",
        "issues": index.get("issues"),
        "site_url": index.get("site_url"),
    }
