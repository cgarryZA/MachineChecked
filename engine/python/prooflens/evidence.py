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
    rec = read_json(path)
    if content_id(rec["body"]) != eid:
        raise EvidenceError(f"evidence record {path} does not match its id")
    return rec


def releases(out_dir: Path) -> list[Path]:
    """The named releases, oldest first by the time recorded in each (a copied directory's file
    times say nothing about when a release was made); ties by name."""
    def when(p: Path):
        try:
            created = read_json(p).get("created") or ""
        except (OSError, ValueError):
            created = ""
        return (created, p.stat().st_mtime, p.name)  # file time only breaks a same-second tie
    return sorted((out_dir / "releases").glob("*.json"), key=when)


def record_release(out_dir: Path, name: str, eid: str) -> Path:
    """Name a release; a release name, once given, keeps its evidence."""
    path = out_dir / "releases" / f"{name}.json"
    if path.exists():
        old = read_json(path)
        if old["evidence"] != eid:
            raise EvidenceError(f"release {name} already names evidence {old['evidence']}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"release": name, "evidence": eid,
                                "created": _dt.datetime.now(_dt.timezone.utc)
                                .isoformat(timespec="seconds")}, indent=1) + "\n")
    return path
