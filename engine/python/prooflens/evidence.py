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
        gone = pruned_releases(out_dir).get(name)
        if gone and gone["evidence"] != eid:
            raise EvidenceError(f"release {name} named evidence {gone['evidence']}, pruned on "
                                f"{gone['pruned'][:10]}; a release name, once given, keeps its "
                                "evidence")
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


def built(out_dir: Path, with_pruned: bool = False) -> list[str]:
    """The releases the builds produced or reproduced, one per build, in the order the builds
    ran (`record_release`). A build whose release is no longer stored with the evidence it
    named is left out (with `with_pruned`, unless `prune` removed that release with that
    evidence), and so is a line that cannot be read."""
    try:
        lines = (out_dir / RELEASE_LOG).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    gone = pruned_releases(out_dir) if with_pruned else {}
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
                stored[name] = (gone.get(name) or {}).get("evidence")
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


PRUNED = "pruned.json"


def pruned(out_dir: Path) -> dict:
    """What `prune` deleted, by evidence id: `{"pruned": time, "releases": [the release records
    it removed with it, as they were]}`, and `"missing": true` when the evidence file was
    already gone (deleted by hand)."""
    try:
        log = read_json(out_dir / PRUNED)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in log.items() if isinstance(v, dict)} if isinstance(log, dict) else {}


def pruned_releases(out_dir: Path) -> dict[str, dict]:
    """The release records `prune` removed, by name, each as it was (`{release, evidence,
    created}`) with the time it was pruned (`pruned`) and whether its evidence was already
    missing. A name a later build gave again is left out."""
    out = {}
    for eid, entry in pruned(out_dir).items():
        for r in entry.get("releases") or []:
            name = r.get("release") if isinstance(r, dict) else None
            if name and not (out_dir / "releases" / f"{name}.json").exists():
                out[name] = {**r, "evidence": eid, "pruned": str(entry.get("pruned") or ""),
                             "missing": bool(entry.get("missing"))}
    return out


def absence(out_dir: Path, eid: str) -> str:
    """Why evidence `eid` is not on disk, in words: pruned on a date, or missing."""
    entry = pruned(out_dir).get(eid) or {}
    when = str(entry.get("pruned") or "")
    return (f"was pruned on {when[:10]}" if when and not entry.get("missing") else
            "is missing (its file was deleted)")


def gone_release(out_dir: Path, name: str) -> str | None:
    """How `prune` removed release `name`, in words, or None when it did not."""
    r = pruned_releases(out_dir).get(name)
    if r is None:
        return None
    if r["missing"]:
        return (f"the evidence of release {name} is missing (its file was deleted), and its "
                f"record was pruned on {r['pruned'][:10]}")
    return f"the evidence of release {name} was pruned on {r['pruned'][:10]}"


def release(out_dir: Path, name: str) -> dict:
    """The record of release `name` (`{release, evidence, created}`), or an error saying why
    there is none."""
    try:
        return read_json(out_dir / "releases" / f"{name}.json")
    except FileNotFoundError:
        gone = gone_release(out_dir, name)
        raise (EvidenceMissing(f"no release {name}: {gone}") if gone else
               EvidenceError(f"no release {name}: `machinechecked evidence list` lists the "
                             "releases")) from None


def release_unavailable(out_dir: Path, release: str) -> str | None:
    """Why the evidence of `release` cannot be read, or None when its file is on disk."""
    path = out_dir / "releases" / f"{release}.json"
    if not path.exists():
        return gone_release(out_dir, release) or f"there is no release {release}"
    try:
        eid = read_json(path)["evidence"]
    except (OSError, ValueError, KeyError, TypeError):
        return f"the record of release {release} cannot be read"
    if (out_dir / "evidence" / f"{eid}.json").exists():
        return None
    return f"the evidence of release {release} {absence(out_dir, eid)}"


def auto_name(release: str, eid: str) -> bool:
    """Whether `release` is the name a build gives when none is asked for."""
    return release == f"r-{eid[:12]}"


def by_recency(out_dir: Path) -> list[str]:
    """The evidence ids the releases name, each once, the latest release's first: in the order
    the builds last produced or reproduced them (`built`), then those of releases no recorded
    build names, newest first."""
    rels = [read_json(p) for p in releases(out_dir)]
    of = {r["release"]: r["evidence"] for r in rels}
    out: list[str] = []
    for eid in [of[n] for n in reversed(built(out_dir)) if n in of] + \
            [r["evidence"] for r in reversed(rels)]:
        if eid not in out:
            out.append(eid)
    return out


def kept(out_dir: Path, keep: int) -> dict[str, list[str]]:
    """The evidence `prune(keep)` keeps, each with why: the newest `keep` distinct evidence
    records (`by_recency`: the latest, which `reassess`, `site` and `export` read and the next
    build compares with; then the one the latest is compared with; then older ones), the
    evidence of every release given a name of its own (`build --release NAME`, which may be
    published: a release name, once given, keeps its evidence), the evidence of the releases a
    workspace's version map compares, what no release names yet but was written in the last
    hour (a build in progress), and the evidence a kept record was reassessed from, as far as
    needed to reach its content file."""
    from . import content as content_mod
    rels = [read_json(p) for p in releases(out_dir)]
    why: dict[str, list[str]] = {}
    for i, eid in enumerate(by_recency(out_dir)[:keep]):
        why.setdefault(eid, []).append(
            "the latest" if i == 0 else
            "the one the latest is compared with" if i == 1 else f"one of the newest {keep}")
    for r in rels:
        if not auto_name(r["release"], r["evidence"]):
            why.setdefault(r["evidence"], []).append(f"release {r['release']} is named")
    of = {r["release"]: r["evidence"] for r in rels}
    from . import workspace as wsp
    for _, ws in wsp.list_all(out_dir):
        for m in ws.get("version_maps") or []:
            for side in ("from", "to"):
                s = (m.get(side) or {}) if isinstance(m, dict) else {}
                eid = of.get(s.get("release")) or s.get("evidence")
                if isinstance(eid, str):
                    why.setdefault(eid, []).append(
                        f"a version map of workspace {ws.get('id')} compares it")
    # A build stores its evidence and content before it names the release: a recent file that no
    # release names yet may be a build's in progress.
    named = set(of.values())
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


def prune(out_dir: Path, keep: int, dry_run: bool = False) -> dict:
    """Delete the evidence files that `kept` does not keep, with their content files and the
    release records that name them, and record what was deleted in `pruned.json`: a comparison
    with a pruned release then says that its evidence was pruned. A release record whose
    evidence file is already gone is removed the same way, unless `kept` keeps it. Returns
    `{"kept": {id: [why]}, "deleted": {id: [releases]}, "bytes": freed}`."""
    if keep < 2:
        raise EvidenceError("keep at least 2: the latest release and the one it is compared with")
    from . import content as content_mod
    keep_ids = kept(out_dir, keep)
    named: dict[str, list[tuple[Path, dict]]] = {}
    for p in releases(out_dir):
        r = read_json(p)
        named.setdefault(r["evidence"], []).append((p, r))
    found = {p.stem for d in ("evidence", "content") for p in (out_dir / d).glob("*.json")}
    deleted, freed = {}, 0
    for eid in sorted((found | set(named)) - set(keep_ids)):
        files = [out_dir / "evidence" / f"{eid}.json", content_mod.path(out_dir, eid)]
        freed += sum(f.stat().st_size for f in files if f.exists())
        deleted[eid] = [r["release"] for _, r in named.get(eid, [])]
    if not dry_run and deleted:
        now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        log = pruned(out_dir)
        for eid in deleted:
            on_disk = (out_dir / "evidence" / f"{eid}.json").exists()
            if named.get(eid) or on_disk:
                # The records an earlier pruning of the same evidence removed stay listed.
                rels = {r.get("release"): r for r in (log.get(eid) or {}).get("releases") or []
                        if isinstance(r, dict)}
                rels.update((r["release"], r) for _, r in named.get(eid, []))
                log[eid] = {"pruned": now, "releases": list(rels.values()),
                            **({} if on_disk else {"missing": True})}
        # The log first, then the release records, then the files: whatever an interruption
        # leaves, no release names evidence that is gone without the log saying so.
        tmp = out_dir / (PRUNED + ".tmp")
        tmp.write_text(json.dumps(log, indent=1, sort_keys=True) + "\n")
        tmp.replace(out_dir / PRUNED)
        for eid in deleted:
            for p, _ in named.get(eid, []):
                p.unlink(missing_ok=True)
            for f in (out_dir / "evidence" / f"{eid}.json", content_mod.path(out_dir, eid)):
                f.unlink(missing_ok=True)
    return {"kept": keep_ids, "deleted": deleted, "bytes": freed}
