"""Review records: markers in Markdown files, and dismissals of advisory findings.

A marker `<!-- spec-review: <name> <hash> by=<reviewer> [kind=human|ai] [source=<claim>@<sha>]...
-->` records a review of the proposition `<name>` at `<hash>`; `def-review` does the same for a
definition. The hash is either the legacy 128-bit structural hash or a `pl-fp-v1:` fingerprint;
each `source` names a claim whose passage the reviewer read and that passage's digest as read
(`review_sources.py`). The last marker of a declaration (files in order, then position) is its
record; it counts only while its hash is current, and for a claim only while it read the claim's
current passage. The text of the review is the section the marker closes.

A marker is a self-declared record: nothing in the file authenticates who wrote it.
"""

from __future__ import annotations

import fnmatch
import os
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .review_sources import parse as parse_source
from .util import sha256_file

MARKER = re.compile(r"<!--\s*(spec|def)-review:\s*(\S+)\s+(\S+)((?:\s+[\w-]+=\S+)*)\s*-->")
HEADING = re.compile(r"^#{1,6} ", re.M)


@dataclass
class Review:
    target: str            # "spec" | "def"
    name: str
    hash: str
    by: str
    kind: str              # "human" | "ai" | "unknown"
    provenance: str        # "self-declared"
    file: str
    line: int
    text: str
    source: dict[str, str] | None = None   # claim id -> digest of the passage read, if recorded

    def to_json(self) -> dict:
        return dict(self.__dict__)


def reviewer_kind(by: str, explicit: str | None, ai_patterns: list[str]) -> str:
    if explicit in ("human", "ai"):
        return explicit
    if any(fnmatch.fnmatch(by, p) for p in ai_patterns):
        return "ai"
    return "unknown"


def parse_file(path: Path, ai_patterns: list[str], rel_to: Path) -> list[Review]:
    txt = path.read_text(encoding="utf-8")
    out, prev = [], 0
    for m in MARKER.finditer(txt):
        attrs = dict(a.split("=", 1) for a in m.group(4).split() if not a.startswith("source="))
        start = prev
        heads = [h.start() for h in HEADING.finditer(txt, prev, m.start())]
        if heads:
            start = heads[-1]
        if out and not txt[prev:m.start()].strip():
            # A marker straight after another closes the same review: one section reviewing
            # several declarations ends with one marker per declaration.
            body = out[-1].text
        else:
            body = MARKER.sub("", txt[start:m.start()]).strip()
            body = re.sub(r"\A#{1,6} [^\n]*(?:\n|\Z)", "", body).strip()
        by = attrs.get("by", "unknown")
        out.append(Review(
            target=m.group(1), name=m.group(2), hash=m.group(3), by=by,
            kind=reviewer_kind(by, attrs.get("kind"), ai_patterns), provenance="self-declared",
            file=os.path.relpath(path, rel_to),
            line=txt.count("\n", 0, m.start()) + 1, text=body,
            source=parse_source(m.group(4))))
        prev = m.end()
    return out


def review_files(entries: list[Path]) -> list[Path]:
    """The review files named by the configuration: a file, or every `.md` file of a directory
    in name order."""
    out = []
    for e in entries:
        if e.is_dir():
            out += sorted(p for p in e.iterdir() if p.suffix == ".md")
        elif e.exists():
            out.append(e)
    return out


def load_reviews(entries: list[Path], ai_patterns: list[str],
                 root: Path) -> tuple[list[Review], dict]:
    """Every marker, in file order and then position."""
    reviews, hashes = [], {}
    for f in review_files(entries):
        reviews += parse_file(f, ai_patterns, root)
        hashes[os.path.relpath(f, root)] = sha256_file(f)
    return reviews, hashes


def history(reviews: list[Review], target: str, name: str) -> list[Review]:
    """The markers of a declaration; the last one is its current record."""
    return [r for r in reviews if r.target == target and r.name == name]


def load_dismissals(path: Path | None) -> list[dict]:
    """Dismissals of advisory findings: `[{code, subject, fingerprint, rationale, by}]`. A
    dismissal holds only while `fingerprint` is the subject's current fingerprint."""
    if path is None or not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
