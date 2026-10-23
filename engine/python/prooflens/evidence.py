"""The evidence store: content-addressed, append-only records of what the pipeline established.

A record is `{"id", "created", "body"}` with `id` the SHA-256 of the canonical JSON of `body`. A
new run with any difference produces a new record; an existing record is never rewritten.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .util import canonical_json, content_id, read_json

SCHEMA = "prooflens/evidence@0"


class EvidenceError(RuntimeError):
    pass


def store(out_dir: Path, body: dict) -> str:
    body = dict(body, schema=SCHEMA)
    eid = content_id(body)
    path = out_dir / "evidence" / f"{eid}.json"
    if path.exists():
        old = read_json(path)
        if content_id(old["body"]) != eid:
            raise EvidenceError(f"evidence record {path} does not match its id")
        return eid
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"id": eid, "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
           "body": json.loads(canonical_json(body))}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return eid


def load(out_dir: Path, eid: str) -> dict:
    path = out_dir / "evidence" / f"{eid}.json"
    return checked(read_json(path), eid, path)


def checked(rec: dict, eid: str, path: Path) -> dict:
    """`rec`, read from `path`, if its body is the one its id `eid` names."""
    if content_id(rec["body"]) != eid:
        raise EvidenceError(f"evidence record {path} does not match its id")
    return rec


def releases(out_dir: Path) -> list[Path]:
    """The named releases, oldest first by the time recorded in each; releases recorded in the
    same second in the order the builds first named them (the release log), then by name. No
    file time is read: a copied or restored directory's file times say nothing about when a
    release was made. The latest release is not always the last of these: see `latest`."""
    first: dict[str, int] = {}
    for i, name in enumerate(built(out_dir)):
        first.setdefault(name, i)

    def when(p: Path):
        try:
            created = read_json(p).get("created") or ""
        except (OSError, ValueError):
            created = ""
        return (created, first.get(p.stem, -1), p.name)
    return sorted((out_dir / "releases").glob("*.json"), key=when)


# One line per build (or reassessment): the release it produced or reproduced.
RELEASE_LOG = "release-log.jsonl"


def record_release(out_dir: Path, name: str, eid: str) -> Path:
    """Name a release, and record it as the one the build being made produced, or reproduced
    when the build stored evidence an earlier build had stored (`latest`). A release name, once
    given, keeps its evidence."""
    path = out_dir / "releases" / f"{name}.json"
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    if path.exists():
        old = read_json(path)
        if old["evidence"] != eid:
            raise EvidenceError(f"release {name} already names evidence {old['evidence']}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"release": name, "evidence": eid, "created": now},
                                   indent=1) + "\n")
    line = (json.dumps({"release": name, "evidence": eid, "at": now}) + "\n").encode()
    with (out_dir / RELEASE_LOG).open("a+b") as f:
        if f.seek(0, 2):
            f.seek(-1, 2)
            if f.read(1) != b"\n":  # a line an interrupted write left unfinished
                line = b"\n" + line
        f.write(line)
    return path


def built(out_dir: Path) -> list[str]:
    """The releases the builds produced or reproduced, one per build, in the order the builds
    ran (`record_release`). A build whose release is no longer stored with the evidence it
    named is left out, and so is a line that cannot be read."""
    try:
        lines = (out_dir / RELEASE_LOG).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    stored, out = {}, []
    for line in lines:
        try:
            entry = json.loads(line)
            name, eid = str(entry["release"]), entry["evidence"]
        except (ValueError, KeyError, TypeError):
            continue
        if name not in stored:
            try:
                stored[name] = read_json(out_dir / "releases" / f"{name}.json").get("evidence")
            except (OSError, ValueError, AttributeError):
                stored[name] = None
        if stored[name] == eid:
            out.append(name)
    return out


def latest(out_dir: Path) -> dict | None:
    """The latest release, as its file records it (`{release, evidence, created}`): the one the
    last build produced or reproduced. A build that reproduces an earlier evidence record names
    that record's release again, which keeps its `created` time, so this need not be the
    release made last. In a store no build has recorded its release in, it is the release made
    last (`releases`). None when there is no release."""
    made = built(out_dir)
    if made:
        return read_json(out_dir / "releases" / f"{made[-1]}.json")
    rels = releases(out_dir)
    return read_json(rels[-1]) if rels else None
