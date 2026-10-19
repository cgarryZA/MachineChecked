"""The version of a paper an audit pins, and the check that the claim inventory pins the same one.

A version is either published (the version `published` names, such as `arXiv:2601.01234v1`, or
an arXiv source) or an unpublished manuscript at a commit (`version = "manuscript"`, with the
source's pinned revision). Its record says which, with a label for readers: "arXiv v1", or
"Latest manuscript (commit abc1234)". An unpublished manuscript is never given a version number.

The record is descriptive: no status depends on it. What is checked is that the inventory's pins
(`papers.<id>.commit`, a claim's `commit`) name the declared version: a published version by its
identifier (`2601.01234v1`), a manuscript by its commit. So an audit labelled with one version
cannot carry claims pinned to another. The record's `checked` says whether that check covers
every claim: it is false when some claim carries no pin, so the version is only as the
configuration states it, and readers are told so.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .audit import published_record

COMMIT = re.compile(r"[0-9a-f]{7,40}")
ARXIV_PIN = re.compile(r"(?:arxiv:)?([a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(v\d+)?", re.I)
SHORT = 7


class VersionError(ValueError):
    """A paper's declared version is incomplete or disagrees with the inventory's pins."""


def same_commit(a: str, b: str) -> bool:
    """Whether two commit names (full or abbreviated, at least 7 hexadecimal digits) agree."""
    a, b = a.strip().lower(), b.strip().lower()
    return a == b or bool(COMMIT.fullmatch(a) and COMMIT.fullmatch(b)
                          and (a.startswith(b) or b.startswith(a)))


def _toplevel_head(folder: Path) -> str | None:
    """The commit checked out in `folder`, when `folder` is the top of its own Git work tree
    (a folder inside another repository is not the manuscript's own history)."""
    if not folder.is_dir():
        return None
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=folder,
                         capture_output=True, text=True)
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != folder.resolve():
        return None
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder, capture_output=True,
                          text=True)
    return head.stdout.strip() if head.returncode == 0 else None


def manuscript_revision(paper, snap, base: Path) -> str | None:
    """The commit of the source the audit reads: a Git source's resolved `rev`; a folder's
    stated `rev` (checked against the folder's own history when it has one), else the folder's
    commit when it is a repository of its own."""
    if snap.kind == "git":
        return snap.revision
    if snap.kind != "path":
        return None
    stated = paper.source.get("rev")
    head = _toplevel_head((base / paper.source["path"]).resolve())
    if stated and head and not same_commit(stated, head):
        raise VersionError(f"paper {paper.id}: source rev {stated} is not the commit checked "
                           f"out in {paper.source['path']} ({head[:SHORT]})")
    return str(stated) if stated else head


def manuscript_record(revision: str) -> dict:
    short = revision[:SHORT]
    return {"kind": "manuscript", "id": f"manuscript:{short}", "revision": revision,
            "label": f"Latest manuscript (commit {short})"}


def published_version(value: str) -> dict:
    """The record of a published version named as `published` names it."""
    rec = published_record(value)
    if rec["id"] and rec["id"].startswith("arxiv:"):
        n = rec["version"]
        return {"kind": "published", "id": rec["id"] + (n or ""), "arxiv": rec["id"],
                "number": n, "label": f"arXiv {n}" if n else f"arXiv {rec['id'][6:]}"}
    if rec["id"]:
        return {"kind": "published", "id": rec["id"], "label": f"Published ({rec['id']})"}
    return {"kind": "published", "id": rec["url"] or value, "label": "Published version"}


def declared(paper, snap, base: Path) -> tuple[dict | None, bool]:
    """The version this paper's audit pins, and whether the configuration declares it (a
    declared version is checked against the inventory; an inferred one is dropped instead)."""
    revision = manuscript_revision(paper, snap, base)
    want = paper.version
    source_arxiv = snap.revision if snap.kind == "arxiv" else None
    if want == "published" or (want is None and (paper.published or source_arxiv)):
        if source_arxiv:
            rec = published_version("arXiv:" + source_arxiv)
            if paper.published and published_version(paper.published)["id"] != rec["id"]:
                raise VersionError(f"paper {paper.id}: published names {paper.published}, but "
                                   f"the source is arXiv {source_arxiv}")
        elif paper.published:
            rec = published_version(paper.published)
        else:
            raise VersionError(f'paper {paper.id}: version = "published" needs `published`, '
                               'as in published = "arXiv:2601.01234v1"')
        return {**rec, "revision": revision}, True
    if want == "manuscript":
        if snap.kind == "arxiv":
            raise VersionError(f'paper {paper.id}: version = "manuscript", but the source is '
                               'arXiv; read the manuscript from its repository (git, rev)')
        if not revision:
            raise VersionError(f'paper {paper.id}: version = "manuscript" needs the commit of '
                               'the manuscript: give the source a `rev`')
        return manuscript_record(revision), True
    return (manuscript_record(revision) if revision else None), False


def inventory_pins(inv: dict, pid: str) -> dict[str, list[str]]:
    """Each pin of the paper's claims (a claim's `commit`, else `papers.<id>.commit`), with the
    claims it pins."""
    default = ((inv.get("papers") or {}).get(pid) or {}).get("commit")
    out: dict[str, list[str]] = {}
    for c in inv.get("claims", []):
        if c.get("paper") == pid and (c.get("commit") or default):
            out.setdefault(str(c.get("commit") or default), []).append(c["id"])
    return out


def pin_matches(pin: str, rec: dict) -> bool:
    """Whether an inventory pin names the version `rec` records. A published version is named
    by its own identifier (`2601.01234v1`, with or without `arXiv:`); a commit cannot show
    which published version it is. A manuscript is named by its commit."""
    pin = pin.strip()
    if rec["kind"] == "published":
        m = ARXIV_PIN.fullmatch(pin)
        if m and not COMMIT.fullmatch(pin.lower()):
            return ("arxiv:" + m.group(1) + (m.group(2) or "")).lower() == rec["id"].lower()
        return pin.lower() == rec["id"].lower()
    return bool(COMMIT.fullmatch(pin.lower()) and same_commit(pin, rec["revision"]))


def describe_pin(pin: str) -> str:
    return f"commit {pin[:SHORT]}" if COMMIT.fullmatch(pin.lower()) else pin


def unpinned_claims(inv: dict, pid: str) -> list[str]:
    """The paper's claims that carry no pin (neither their own `commit` nor the paper's)."""
    if ((inv.get("papers") or {}).get(pid) or {}).get("commit"):
        return []
    return [c["id"] for c in inv.get("claims", []) if c.get("paper") == pid and not c.get("commit")]


def check(paper, rec: dict | None, is_declared: bool, inv: dict) -> dict | None:
    """The version record to publish: `rec` when the inventory's pins agree with it, with
    `checked` false when some claim carries no pin to check it against (or there are no claims).
    A declared version the pins disagree with is refused; an inferred one is dropped (nothing is
    claimed)."""
    if rec is None:
        return None
    pins = inventory_pins(inv, paper.id)
    bad = {pin: ids for pin, ids in pins.items() if not pin_matches(pin, rec)}
    if not bad:
        return {**rec, "checked": bool(pins) and not unpinned_claims(inv, paper.id)}
    if not is_declared:
        return None
    pins = "; ".join(f"{describe_pin(p)} ({len(ids)} claim{'s' * (len(ids) != 1)}, "
                     f"such as {ids[0]})" for p, ids in sorted(bad.items()))
    fix = ('pin the inventory to ' + (rec['id'].removeprefix('arxiv:') if rec['kind'] ==
                                       'published' else f"commit {rec['revision'][:SHORT]}")
           + ', or declare the version the inventory pins (`version` and the source\'s `rev`)')
    raise VersionError(f"paper {paper.id}: the audit pins {rec['label']}, but its inventory is "
                       f"pinned to {pins}. An audit pins one version of its paper: {fix}.")
