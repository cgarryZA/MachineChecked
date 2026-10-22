"""Review records: markers in Markdown files, and dismissals of advisory findings.

A marker `<!-- spec-review: <name> <hash> by=<reviewer> [kind=human|ai] [source=<claim>@<sha>]...
-->` records a review of the proposition `<name>` at `<hash>`; `def-review` does the same for a
definition. The hash is either the legacy 128-bit structural hash or a `pl-fp-v1:` fingerprint;
each `source` names a claim whose passage the reviewer read and that passage's digest as read
(`review_sources.py`). A marker
`<!-- step-review: <claim id> <source sha256> verdict=<holds|gap|false|undetermined> by=… -->`
records a review of a printed proof step (`steps.py`) at the hash of its source text, which is
the digest of the passage it read. The last marker of a declaration (files in order, then
position) is its record; it counts only while its hash is current, and for a claim only while it
read the claim's current passage. The text of the review is the section the marker closes; a
marker straight after another shares its text, and the `Review by` lines that `review promote`
writes are the text of the reviewer's marker that follows each, never part of the section's.

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

MARKER = re.compile(r"<!--\s*(spec|def|step)-review:\s*(\S+)\s+(\S+)((?:\s+[\w-]+=\S+)*)\s*-->")
# A marker that `inventory retire` set aside (`retire.py`): it stays in the file with its review
# text, which it still closes, and records no review.
RETIRED = re.compile(r"<!--\s*retired\s+(spec|def|step)-review:\s*(\S+)\s+(\S+)"
                     r"((?:\s+[\w-]+=\S+)*)\s*-->")
ANY = re.compile(MARKER.pattern + "|" + RETIRED.pattern)
HEADING = re.compile(r"^#{1,6} ", re.M)
# The line `review promote` writes before a reviewer's marker (`promote.apply`).
PROMOTED = re.compile(r"^[ \t]*Review by \S+: [^\n]*\(report `[^`\n]*`\)\.[ \t]*$\n?", re.M)


@dataclass
class Review:
    target: str            # "spec" | "def" | "step"
    name: str
    hash: str
    by: str
    kind: str              # "human" | "ai" | "unknown"
    provenance: str        # "self-declared"
    file: str
    line: int
    text: str
    source: dict[str, str] | None = None   # claim id -> digest of the passage read, if recorded
    verdict: str | None = None   # a step review's finding: holds, gap, false, undetermined

    def to_json(self) -> dict:
        out = dict(self.__dict__)
        if out["verdict"] is None:
            out.pop("verdict")
        return out


def reviewer_kind(by: str, explicit: str | None, ai_patterns: list[str]) -> str:
    if explicit in ("human", "ai"):
        return explicit
    if any(fnmatch.fnmatch(by, p) for p in ai_patterns):
        return "ai"
    return "unknown"


def parse_file(path: Path, ai_patterns: list[str], rel_to: Path) -> list[Review]:
    txt = path.read_text(encoding="utf-8")
    out, prev, block, seen = [], 0, "", False
    for any_ in ANY.finditer(txt):
        live = any_.group(1) is not None
        m = MARKER.fullmatch(any_.group()) if live else RETIRED.fullmatch(any_.group())
        attrs = dict(a.split("=", 1) for a in m.group(4).split() if not a.startswith("source="))
        start = prev
        heads = [h.start() for h in HEADING.finditer(txt, prev, any_.start())]
        if heads:
            start = heads[-1]
        since = txt[prev:any_.start()]
        promoted = [p.strip() for p in PROMOTED.findall(since)]
        if not PROMOTED.sub("", since).strip() and (seen or promoted):
            # Nothing of the author's since the previous marker. A `Review by` line written by
            # `review promote` is the record of the reviewer's marker it precedes; a marker
            # straight after another closes the same review: one section reviewing several
            # declarations ends with one marker per declaration, and promotion may have
            # interleaved reviewers' lines and markers among them.
            body = "\n".join(promoted) if promoted else block
        else:
            body = ANY.sub("", PROMOTED.sub("", txt[start:any_.start()])).strip()
            body = re.sub(r"\A#{1,6} [^\n]*(?:\n|\Z)", "", body).strip()
            block = body
        seen = True
        if not live:
            prev = any_.end()
            continue
        by = attrs.get("by", "unknown")
        out.append(Review(
            target=m.group(1), name=m.group(2), hash=m.group(3), by=by,
            kind=reviewer_kind(by, attrs.get("kind"), ai_patterns), provenance="self-declared",
            file=os.path.relpath(path, rel_to),
            line=txt.count("\n", 0, any_.start()) + 1, text=body,
            source=parse_source(m.group(4), m.group(2) if m.group(1) == "step" else None,
                                m.group(3)),
            verdict=attrs.get("verdict") if m.group(1) == "step" else None))
        prev = any_.end()
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
