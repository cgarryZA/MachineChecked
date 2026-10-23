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


class EvidenceMissing(EvidenceError):
    """The evidence file a release names is not on disk: pruned (`prune`), or deleted by hand."""


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
    if not path.exists():
        raise EvidenceMissing(f"the evidence {eid[:12]} {absence(out_dir, eid)}")
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


PRUNED = "pruned.json"


def pruned(out_dir: Path) -> dict:
    """The evidence `prune` deleted: `{id: {"pruned": time, "releases": [names]}}`."""
    path = out_dir / PRUNED
    try:
        return read_json(path) if path.exists() else {}
    except (OSError, ValueError):
        return {}


def absence(out_dir: Path, eid: str) -> str:
    """Why evidence `eid` is not on disk, in words: pruned on a date, or missing."""
    when = (pruned(out_dir).get(eid) or {}).get("pruned")
    return (f"was pruned on {when[:10]}" if when else
            "is missing (its file was deleted)")


def release_unavailable(out_dir: Path, release: str) -> str | None:
    """Why the evidence of `release` cannot be read, or None when its file is on disk."""
    path = out_dir / "releases" / f"{release}.json"
    try:
        eid = read_json(path)["evidence"]
    except (OSError, ValueError, KeyError, TypeError):
        return f"the record of release {release} cannot be read"
    if (out_dir / "evidence" / f"{eid}.json").exists():
        return None
    return f"the evidence of release {release} {absence(out_dir, eid)}"


def kept(out_dir: Path, keep: int) -> dict[str, list[str]]:
    """The evidence `prune(keep)` keeps, each with why: the newest `keep` distinct evidence
    records (the latest is the one `build --reuse-lean`, `reassess` and `site` read; the one
    before it is the one the next build's change summary compares with), the evidence of every
    release given a name of its own (`build --release NAME`, which may be published), what no
    release names yet but was written in the last hour, and the evidence a kept record was
    reassessed from as far as needed to find its content file."""
    from . import content as content_mod
    rels = [read_json(p) for p in releases(out_dir)]
    why: dict[str, list[str]] = {}
    newest = []
    for r in reversed(rels):
        if r["evidence"] not in newest and len(newest) < keep:
            newest.append(r["evidence"])
    for i, eid in enumerate(newest):
        why.setdefault(eid, []).append("the latest" if i == 0 else f"one of the newest {keep}")
    for r in rels:
        if not auto_name(r["release"], r["evidence"]):
            why.setdefault(r["evidence"], []).append(f"release {r['release']} is named")
    # A build stores its evidence and content before it names the release: a recent file that no
    # release names yet may be a build's in progress.
    named = {r["evidence"] for r in rels}
    recent = _dt.datetime.now().timestamp() - 3600
    for d in ("evidence", "content"):
        for p in (out_dir / d).glob("*.json"):
            if p.stem not in named and p.stat().st_mtime > recent:
                why.setdefault(p.stem, []).append("written in the last hour and not yet named by "
                                                  "a release (a build may be writing it)")
    # A reassessed record shows the content of the record it was reassessed from (`content.py`).
    for eid in list(why):
        seen = {eid}
        cur = eid
        while not content_mod.path(out_dir, cur).exists():
            try:
                cur = load(out_dir, cur)["body"].get("provenance", {}).get("reassessed_from")
            except (OSError, ValueError, KeyError, EvidenceError):
                break
            if not cur or cur in seen:
                break
            seen.add(cur)
            why.setdefault(cur, []).append(f"{eid[:12]} was reassessed from it")
    return why


def auto_name(release: str, eid: str) -> bool:
    """Whether `release` is the name a build gives when none is asked for."""
    return release == f"r-{eid[:12]}"


def prune(out_dir: Path, keep: int, dry_run: bool = False) -> dict:
    """Delete the evidence files (and their content files) that `kept` does not keep, and record
    what was deleted in `pruned.json`, so that a release whose evidence is gone says so. Release
    records are never changed or deleted. Returns `{"kept": {id: [why]}, "deleted": {id:
    [releases]}, "bytes": freed}`."""
    if keep < 2:
        raise EvidenceError("keep at least 2: the latest evidence and the one the next build "
                            "compares with")
    from . import content as content_mod
    keep_ids = kept(out_dir, keep)
    by_id: dict[str, list[str]] = {}
    for p in releases(out_dir):
        r = read_json(p)
        by_id.setdefault(r["evidence"], []).append(r["release"])
    found = {p.stem for d in ("evidence", "content") for p in (out_dir / d).glob("*.json")}
    deleted, freed = {}, 0
    for eid in sorted(found - set(keep_ids)):
        files = [out_dir / "evidence" / f"{eid}.json", content_mod.path(out_dir, eid)]
        freed += sum(f.stat().st_size for f in files if f.exists())
        deleted[eid] = by_id.get(eid, [])
    if not dry_run and deleted:
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        log = pruned(out_dir)
        for eid, names in deleted.items():
            if (out_dir / "evidence" / f"{eid}.json").exists():
                log[eid] = {"pruned": now, "releases": names}
        tmp = out_dir / (PRUNED + ".tmp")
        tmp.write_text(json.dumps(log, indent=1, sort_keys=True) + "\n")
        tmp.replace(out_dir / PRUNED)
        for eid in deleted:
            for f in (out_dir / "evidence" / f"{eid}.json", content_mod.path(out_dir, eid)):
                f.unlink(missing_ok=True)
    return {"kept": keep_ids, "deleted": deleted, "bytes": freed}
