"""A review snapshot: what a review of the paper-to-Lean correspondence reads, packed by the
project's author (`machinechecked review pack`) for a reviewer who did not build the project
(`machinechecked review … --snapshot`).

A review compares the paper's passages with the Lean as the build recorded it, so a reviewer needs
that build's records and no Lean. A snapshot holds the files of the last build's site data that
the review steps read (`FILES`, `DIRS`; the papers' PDFs only when asked), each found by name, and
a manifest (`machinechecked-snapshot.json`, `prooflens/review-snapshot@1`) naming what it is (the
release, the project's commit and repository, each paper's revision and PDF checksum, the tool's
version) with the SHA-256 of every file. Nothing else of the author's working directory travels:
no workspace, no draft or report in progress, no record of what anyone had seen. Two parts of the
site data come from the author's workspaces and are left out: the index's semantic summary, which
counts their findings, and the counterparts of paper numbers that their version maps give (the
`current` of a claim's reference whose source is a kept map).

The digests catch an incomplete or inconsistent copy: a file missing, changed since it was packed,
or not packed at all. They do not authenticate the author, since whoever holds the files can
write a new manifest beside them. What a review against a snapshot is worth is decided on the
maintainer's side: `review promote` checks each report against the maintainer's own release.

A snapshot is a directory or a zip archive of one. A zip is checked and then extracted into the
reviewer's working directory (`snapshots/<digest>/`), never beside the archive. Nothing here runs
Lean or TeX.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

SCHEMA = "prooflens/review-snapshot@1"
MANIFEST = "machinechecked-snapshot.json"
DATA = "data"
# The reviewer's working directory when none is given (`--review-dir`), in the current directory.
REVIEW_DIR = ".machinechecked-review"
# The files of the site data the review steps read (`review_cli.Session`,
# `compare.unit_packet`, `review_cli.informed_order`): the index, the review queue and the
# reverse references the informed order reads; and every claim record, declaration record and
# stored expansion.
FILES = ("index.json", "review-queue.json", "uses.json")
DIRS = ("claims", "decls", "expansions")
PAPERS = "papers"
HEX64 = re.compile(r"[0-9a-f]{64}")
# How many of a check's problems a refusal names.
SHOWN = 10


class SnapshotError(RuntimeError):
    """A snapshot that cannot be packed or read, with what is wrong."""


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _json_bytes(obj) -> bytes:
    """`obj` as the site data writes JSON (`util.write_json` without indentation)."""
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


# -- packing -----------------------------------------------------------------------------------

def _selected(data: Path, pdf: bool) -> dict[str, bytes]:
    """The allowed files of the site data `data`, by their path in the snapshot. A link is not
    followed: the site data holds none, and a link could bring in a file from elsewhere."""
    out: dict[str, bytes] = {}
    for name in FILES:
        p = data / name
        if p.is_file() and not p.is_symlink():
            out[f"{DATA}/{name}"] = p.read_bytes()
    for d, suffix in [*((d, ".json") for d in DIRS), *([(PAPERS, ".pdf")] if pdf else [])]:
        root = data / d
        if not root.is_dir() or root.is_symlink():
            continue
        for top, _, names in os.walk(root):  # links to directories are not followed
            for n in sorted(names):
                p = Path(top) / n
                if p.suffix == suffix and p.is_file() and not p.is_symlink():
                    out[f"{DATA}/{p.relative_to(data).as_posix()}"] = p.read_bytes()
    return dict(sorted(out.items()))


def _without_workspace_content(files: dict[str, bytes]) -> list[str]:
    """Leave out of `files` (in place) what the site data holds from the author's workspaces,
    saying what was left out: the index's semantic summary (it counts the findings of the
    workspaces) and each counterpart of a paper number given by a version map a workspace keeps.
    No review step reads either."""
    said = []
    key = f"{DATA}/index.json"
    index = json.loads(files[key])
    if "semantic" in index or any("semantic" in c for c in index.get("claims") or []):
        index.pop("semantic", None)
        for c in index.get("claims") or []:
            c.pop("semantic", None)
        files[key] = _json_bytes(index)
        said.append("the index's semantic summary, which counts the findings of the author's "
                    "workspaces")
    kept = 0
    for name in [n for n in files if n.startswith(f"{DATA}/claims/")]:
        ch = json.loads(files[name])
        refs = ch.get("references") if isinstance(ch, dict) else None
        n = 0
        for o in refs if isinstance(refs, list) else []:
            cur = o.get("current") if isinstance(o, dict) else None
            if isinstance(cur, dict) and isinstance(cur.get("source"), dict) \
                    and cur["source"].get("kept"):
                del o["current"]
                n += 1
        if n:
            kept += n
            files[name] = _json_bytes(ch)
    if kept:
        said.append(f"{kept} counterpart(s) of the paper's numbers that version maps kept in the "
                    "author's workspaces give")
    return said


def contents(files: dict[str, bytes]) -> dict:
    """What a snapshot holds, counted: the review units, the claims whose passages it gives, the
    Lean declaration records (statements and definitions), the author's reviews the units show
    at step 3, and whether the papers' PDFs are included."""
    queue = json.loads(files[f"{DATA}/review-queue.json"])
    units = queue.get("units") or []
    return {"units": len(units),
            "open_units": sum(1 for u in units if u.get("state") != "reviewed"),
            "claims": sum(1 for n in files if n.startswith(f"{DATA}/claims/")),
            "declarations": sum(1 for n in files if n.startswith(f"{DATA}/decls/")),
            "author_reviews": sum(len(u.get("author_review") or []) for u in units),
            "pdfs": sum(1 for n in files if n.startswith(f"{DATA}/{PAPERS}/")),
            "files": len(files), "bytes": sum(len(b) for b in files.values())}


def pack(data: Path, out: Path, pdf: bool = False, tool: str = "unknown") -> dict:
    """Write the review snapshot of the site data `data` to `out`: a zip archive when `out` ends
    in `.zip`, else a directory (new, empty, or a snapshot written before, which it replaces).
    Returns the manifest, with `out` and its `digest`."""
    from .targets import Snapshot
    data, out = Path(data), Path(out)
    if not (data / "index.json").is_file():
        raise SnapshotError("no build to pack: run `machinechecked view` or `machinechecked "
                            "build` first")
    if not (data / "review-queue.json").is_file():
        raise SnapshotError("the last build wrote no review queue: run `machinechecked view` or "
                            "`machinechecked build` again")
    if out.resolve().is_relative_to(data.resolve()):
        raise SnapshotError(f"{out} is inside the site data it would pack: write it elsewhere")
    zipped = out.suffix.lower() == ".zip"
    if zipped and out.is_dir():
        raise SnapshotError(f"{out} is a directory: give a file name for the archive")
    if not zipped and out.exists() and not (out.is_dir() and (
            not any(out.iterdir()) or (out / MANIFEST).is_file())):
        raise SnapshotError(f"{out} exists and is neither an empty directory nor a review "
                            "snapshot: give a new name")
    files = _selected(data, pdf)
    left_out = _without_workspace_content(files)
    index = json.loads(files[f"{DATA}/index.json"])
    manifest = {
        "schema": SCHEMA,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": "machinechecked", "version": tool},
        "sources": Snapshot(data).sources(),
        "evidence_id": index.get("evidence"),
        "mode": index.get("mode") or "full",
        "pdf": bool(pdf),
        "contains": contents(files),
        "left_out": left_out,
        "files": {n: _sha256(b) for n, b in sorted(files.items())},
    }
    raw = (json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True) + "\n") \
        .encode("utf-8")
    if zipped:
        _write_zip(out, raw, files)
    else:
        _write_dir(out, raw, files)
    return {**manifest, "out": str(out), "digest": _sha256(raw)}


def _write_zip(out: Path, raw: bytes, files: dict[str, bytes]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            # A fixed time on every entry: the same files give the same archive.
            for name, b in [(MANIFEST, raw), *sorted(files.items())]:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, b)
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_dir(out: Path, raw: bytes, files: dict[str, bytes]) -> None:
    """Write the snapshot into the directory `out`, replacing the data and manifest of a snapshot
    written there before; the manifest is written last."""
    out.mkdir(parents=True, exist_ok=True)
    (out / MANIFEST).unlink(missing_ok=True)
    if (out / DATA).exists():
        shutil.rmtree(out / DATA)
    for name, b in files.items():
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    (out / MANIFEST).write_bytes(raw)


def summary_text(m: dict) -> str:
    """What `review pack` says it wrote (`m`, the manifest `pack` returns)."""
    c, src = m["contains"], m["sources"]
    proj = src.get("project") or {}
    papers = "; ".join(f"paper {p.get('id')}" + (f" at revision {p['revision']}"
                                                  if p.get("revision") else "")
                       for p in src.get("papers") or [])
    lines = [f"wrote the review snapshot {m['out']}: release {src.get('release')}"
             + (f", project commit {proj['commit']}" if proj.get("commit") else "")
             + (f"; {papers}" if papers else ""),
             f"  {c['units']} review unit(s), {c['open_units']} of them open",
             f"  the paper's passages of {c['claims']} claim(s)",
             f"  {c['declarations']} Lean declaration record(s): statements and definitions",
             f"  {c['author_reviews']} review(s) by the author, shown at step 3",
             "  the paper's PDF" if c["pdfs"] else
             "  no PDF of the paper (`--pdf` includes it)"]
    for what in m.get("left_out") or []:
        lines.append(f"  left out: {what}")
    lines += [f"Manifest digest {m['digest']}.",
              "Its contents are yours to publish: share it where the paper's text and your "
              "reviews may go. A reviewer opens it with `machinechecked review next --snapshot "
              f"{Path(m['out']).name}`, without Lean."]
    return "\n".join(lines)


# -- reading -----------------------------------------------------------------------------------

def _name_ok(name: str) -> bool:
    """Whether `name` is a path a snapshot can hold: relative, under `data/`, with no `.` or `..`
    part and no backslash."""
    if not isinstance(name, str) or "\\" in name or "\0" in name or name.startswith("/"):
        return False
    parts = PurePosixPath(name).parts
    return len(parts) >= 2 and parts[0] == DATA and not {"", ".", ".."} & set(parts) \
        and "/".join(parts) == name


def _manifest(raw: bytes, where: str) -> dict:
    """The manifest in `raw`, refused unless it is one this version reads."""
    try:
        m = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise SnapshotError(f"{where}: the snapshot's manifest is not JSON ({e})") from None
    if not isinstance(m, dict) or m.get("schema") != SCHEMA:
        schema = m.get("schema") if isinstance(m, dict) else None
        raise SnapshotError(f"{where} is not a review snapshot this version reads (schema "
                            f"{schema!r}, not {SCHEMA}): ask its author for one written by "
                            "`machinechecked review pack`")
    files = m.get("files")
    if not isinstance(files, dict) or not files or not all(
            _name_ok(k) and isinstance(v, str) and HEX64.fullmatch(v) for k, v in files.items()):
        raise SnapshotError(f"{where}: the manifest's list of files is not one "
                            "`machinechecked review pack` writes")
    for need in (f"{DATA}/index.json", f"{DATA}/review-queue.json"):
        if need not in files:
            raise SnapshotError(f"{where}: the manifest lists no {need}")
    if not isinstance(m.get("sources"), dict):
        raise SnapshotError(f"{where}: the manifest does not say what the snapshot is (sources)")
    return m


def _refuse(where: str, problems: list[str]) -> None:
    more = len(problems) - SHOWN
    raise SnapshotError(
        f"incomplete or inconsistent review snapshot {where}: " + "; ".join(problems[:SHOWN])
        + (f"; and {more} more" if more > 0 else "")
        + ". No step was taken: ask its author for a complete copy (`machinechecked review "
          "pack`)")


def _check_dir(root: Path, m: dict, where: str) -> None:
    """Refuse the snapshot directory `root` unless it holds exactly the files its manifest `m`
    lists, each with its digest."""
    want = m["files"]
    problems = []
    for name, digest in want.items():
        p = root / name
        if p.is_symlink():
            problems.append(f"{name} is a link")
        elif not p.is_file():
            problems.append(f"{name} is missing")
        else:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != digest:
                problems.append(f"{name} differs from the manifest")
    data = root / DATA
    if data.is_symlink():
        problems.append(f"{DATA} is a link")
    else:
        for top, dirs, names in os.walk(data):
            for n in sorted(names + [d for d in dirs if (Path(top) / d).is_symlink()]):
                rel = (Path(top) / n).relative_to(root).as_posix()
                if rel not in want:
                    problems.append(f"{rel} is not in the manifest")
    if problems:
        _refuse(where, problems)


def _check_sources(data: Path, m: dict, where: str) -> None:
    """Refuse a snapshot whose index is not the build its manifest names."""
    from .targets import Snapshot
    have = Snapshot(data).sources()
    if have != m["sources"]:
        _refuse(where, ["its index is not the build its manifest names (release "
                        f"{have.get('release')}, project commit "
                        f"{(have.get('project') or {}).get('commit')}, and the manifest's release "
                        f"{m['sources'].get('release')}, project commit "
                        f"{(m['sources'].get('project') or {}).get('commit')}, or their papers "
                        "differ)"])


def provenance(m: dict, raw: bytes) -> dict:
    """What a report made against the snapshot records it was reviewed against (`evidence`):
    the manifest's digest and the snapshot's pins."""
    src = m["sources"]
    return {"kind": "snapshot", "manifest_sha256": _sha256(raw), "schema": SCHEMA,
            "created_at": m.get("created_at"), "tool": m.get("tool"),
            "release": src.get("release"), "evidence_id": m.get("evidence_id"),
            "project": src.get("project") or {}, "papers": src.get("papers") or []}


def check_work_dir(work: Path, snapshot: Path) -> None:
    """Refuse a reviewer's working directory inside the snapshot directory (the snapshot stays as
    its author wrote it), or one that is a build's working directory (the author's work is not
    the reviewer's)."""
    work, snap = Path(work).resolve(), Path(snapshot).resolve()
    if snap.is_dir() and work.is_relative_to(snap):
        raise SnapshotError(f"the review's working directory {work} is inside the snapshot "
                            f"{snap}: keep your work outside it (--review-dir DIR)")
    if (work / "site" / "data" / "index.json").is_file() or (work / "evidence").is_dir():
        raise SnapshotError(f"{work} is a build's working directory: review in a directory of "
                            "your own (--review-dir DIR)")


def prepare_work_dir(work: Path) -> Path:
    """The reviewer's working directory, made if there is none, with a `.gitignore` of `*` when
    it is made, so that the work stays out of any repository it is in."""
    work = Path(work)
    if not work.is_dir():
        work.mkdir(parents=True)
        (work / ".gitignore").write_text("# A reviewer's working files, never committed.\n*\n",
                                         encoding="utf-8")
    return work


def open_snapshot(path: Path, work: Path) -> tuple[Path, dict]:
    """The site data of the snapshot at `path` (a directory or a zip archive), checked against
    its manifest, and its provenance for reports (`provenance`). A zip is extracted, once checked,
    into the reviewer's working directory `work`. A snapshot that is incomplete, inconsistent or
    of another format is refused (`SnapshotError`); nothing is ever built."""
    path = Path(path)
    if path.is_dir():
        mp = path / MANIFEST
        if not mp.is_file():
            raise SnapshotError(f"{path} holds no snapshot manifest ({MANIFEST}): ask its author "
                                "for the snapshot `machinechecked review pack` writes")
        raw = mp.read_bytes()
        m = _manifest(raw, str(path))
        _check_dir(path, m, str(path))
        _check_sources(path / DATA, m, str(path))
        return path / DATA, provenance(m, raw)
    if not path.exists():
        raise SnapshotError(f"{path}: no such snapshot (a directory or a .zip file that "
                            "`machinechecked review pack` wrote)")
    if not zipfile.is_zipfile(path):
        raise SnapshotError(f"{path} is neither a directory nor a zip archive of a review "
                            "snapshot")
    return _open_zip(path, prepare_work_dir(work))


def _open_zip(path: Path, work: Path) -> tuple[Path, dict]:
    """Check the zip archive `path` against its manifest and extract it into
    `work/snapshots/<digest>/`, unless that holds it already, checked. An archive that cannot be
    read in full is refused as incomplete."""
    try:
        return _extract(path, work)
    except (zipfile.BadZipFile, EOFError) as e:
        _refuse(str(path), [f"the archive cannot be read ({e})"])


def _extract(path: Path, work: Path) -> tuple[Path, dict]:
    where = str(path)
    with zipfile.ZipFile(path) as z:
        members = {i.filename: i for i in z.infolist() if not i.is_dir()}
        if MANIFEST not in members:
            raise SnapshotError(f"{path} holds no snapshot manifest ({MANIFEST}): ask its author "
                                "for the snapshot `machinechecked review pack` writes")
        raw = z.read(MANIFEST)
        m = _manifest(raw, where)
        want = m["files"]
        problems = [f"{n} is missing" for n in want if n not in members]
        problems += [f"{n} is not in the manifest" for n in sorted(members)
                     if n != MANIFEST and n not in want]
        if problems:
            _refuse(where, problems)
        target = work / "snapshots" / _sha256(raw)[:24]
        if (target / MANIFEST).is_file() and (target / MANIFEST).read_bytes() == raw:
            try:
                _check_dir(target, m, str(target))
                _check_sources(target / DATA, m, where)
                return target / DATA, provenance(m, raw)
            except SnapshotError:
                pass  # the copy extracted before was changed: extract it again from the archive
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=target.parent, prefix=".extract-"))
        try:
            for name, digest in sorted(want.items()):
                dst = tmp / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with z.open(members[name]) as src, open(dst, "wb") as f:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        h.update(chunk)
                        f.write(chunk)
                if h.hexdigest() != digest:
                    problems.append(f"{name} differs from the manifest")
            if problems:
                _refuse(where, problems)
            (tmp / MANIFEST).write_bytes(raw)
            _check_sources(tmp / DATA, m, where)
            if target.exists():
                shutil.rmtree(target)
            os.replace(tmp, target)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    return target / DATA, provenance(m, raw)
