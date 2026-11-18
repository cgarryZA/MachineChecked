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

A project can keep its snapshot in its repository (`project_path`: `[review] snapshot`, else
`review-snapshot/` at its root), so that a reviewer who clones it reviews with the plain
commands. `build` writes it again after each build, and leaves it as it is while it holds the
build's review material (`_unchanged`): the release, evidence, commit and times that name each
build change with every commit, and a snapshot committed with the project would otherwise never
be current.
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
# A snapshot that leaves out the text of a paper's source (`snapshot_text`): a version that does
# not read it again from the source cannot read it.
SCHEMA_WITHOUT_TEXT = "prooflens/review-snapshot@2"
SCHEMAS = (SCHEMA, SCHEMA_WITHOUT_TEXT)
MANIFEST = "machinechecked-snapshot.json"
DATA = "data"
# The reviewer's working directory when none is given (`--review-dir`), in the current directory
# (at the project's root, for the snapshot a project keeps).
REVIEW_DIR = ".machinechecked-review"
# The directory a project keeps its review snapshot in, at its root, when its configuration names
# none (`[review] snapshot`).
PROJECT_DIR = "review-snapshot"
INDEX = f"{DATA}/index.json"
QUEUE = f"{DATA}/review-queue.json"
# The files of the site data the review steps read (`review_cli.Session`,
# `compare.unit_packet`, `review_cli.informed_order`): the index, the review queue and the
# reverse references the informed order reads; and every claim record, declaration record and
# stored expansion, and each proof step's proposed verdict, which step 3 shows.
FILES = ("index.json", "review-queue.json", "uses.json")
DIRS = ("claims", "decls", "expansions", "proposals")
PAPERS = "papers"
HEX64 = re.compile(r"[0-9a-f]{64}")
# How many of a check's problems a refusal names.
SHOWN = 10
# Why a paper of a configuration keeps its text in a snapshot (the manifest's `paper_text`).
KEPT = {"published": "its source text is published (publish.source_text)",
        "asked": "as asked (--with-paper-text): hand this snapshot over privately",
        "pdf": "it is read from its PDF, whose text has no source to read it again from"}


class SnapshotError(RuntimeError):
    """A snapshot that cannot be packed or read, with what is wrong."""


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _json_bytes(obj) -> bytes:
    """`obj` as a snapshot holds JSON: its keys in the order read (`util.write_json` sorts
    them), with no space after a separator, which keeps a snapshot kept in a repository about a
    tenth smaller than the site data."""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _compact(files: dict[str, bytes]) -> None:
    """Each JSON file of `files` (in place) as `_json_bytes` writes it: the same value, read
    back identically."""
    for name, b in files.items():
        if name.endswith(".json"):
            try:
                files[name] = _json_bytes(json.loads(b))
            except ValueError:
                pass


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


def project_path(root: Path, configured: Path | None = None) -> Path:
    """The review snapshot a project keeps: the directory its configuration names (`[review]
    snapshot`), else `review-snapshot/` at its root."""
    return Path(configured) if configured else Path(root) / PROJECT_DIR


def kept(path: Path) -> bool:
    """Whether `path` is a directory holding a review snapshot (its manifest)."""
    return Path(path).is_dir() and (Path(path) / MANIFEST).is_file()


def packed_pdf(path: Path) -> bool:
    """Whether the snapshot directory at `path` holds the papers' PDFs, as its manifest says;
    False when it holds no readable manifest."""
    try:
        return json.loads((Path(path) / MANIFEST).read_text(encoding="utf-8")).get("pdf") is True
    except (OSError, ValueError, AttributeError):
        return False


def pack(data: Path, out: Path, pdf: bool = False, tool: str = "unknown",
         without: dict[str, dict] | None = None, kept_text: dict[str, str] | None = None) -> dict:
    """Write the review snapshot of the site data `data` to `out`: a zip archive when `out` ends
    in `.zip`, else a directory (new, empty, or a snapshot written before, which it replaces).
    The text of the sources of the papers `without` names (`snapshot_text.leave_out`) is left
    out, and the snapshot is scanned for it (`snapshot_text.scan`); `kept_text` says why each
    other paper of a configuration keeps its text (`KEPT`). Returns the manifest, with `out` and
    its `digest`. A directory that holds this build's review material already (`_unchanged`) is
    left as it is, and the manifest returned is its own, with `unchanged` and the release of
    this build (`built`)."""
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
    _compact(files)
    paper_text = {pid: {"included": True, "because": why} for pid, why in (kept_text or {}).items()}
    if without:
        from . import snapshot_text as st
        entries, said = st.leave_out(files, without)
        paper_text.update(entries)
        left_out += said
        leaks = st.scan(files, without)
        if leaks:
            raise SnapshotError(
                f"the snapshot would hold text of the source of paper(s) "
                f"{', '.join(sorted(without))}, which their configuration keeps private "
                "(publish.source_text = false): " + "; ".join(leaks[:SHOWN])
                + (f"; and {len(leaks) - SHOWN} more" if len(leaks) > SHOWN else "")
                + ". Nothing was written: remove the quotation from the project's file it comes "
                  "from, or give --with-paper-text for a snapshot you hand over privately")
    index = json.loads(files[f"{DATA}/index.json"])
    manifest = {
        "schema": SCHEMA_WITHOUT_TEXT if without else SCHEMA,
        "created_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": {"name": "machinechecked", "version": tool},
        "sources": Snapshot(data).sources(),
        "evidence_id": index.get("evidence"),
        "mode": index.get("mode") or "full",
        "pdf": bool(pdf),
        "contains": contents(files),
        "left_out": left_out,
        **({"paper_text": dict(sorted(paper_text.items()))} if paper_text else {}),
        "files": {n: _sha256(b) for n, b in sorted(files.items())},
    }
    if not zipped and kept(out):
        same = _unchanged(out, manifest, files)
        if same is not None:
            return same
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


def _build_names(index: dict) -> tuple:
    """What names a build in its index: its release, its evidence record and the project's
    commit."""
    return (index.get("release"), index.get("evidence"),
            (index.get("project") or {}).get("commit"))


def _renamed(obj, names: dict):
    """`obj` with every string that is a key of `names` replaced by its value."""
    if isinstance(obj, str):
        return names.get(obj, obj)
    if isinstance(obj, list):
        return [_renamed(x, names) for x in obj]
    if isinstance(obj, dict):
        return {k: _renamed(v, names) for k, v in obj.items()}
    return obj


def _unnamed(name: str, obj):
    """The file `name` of a snapshot (`obj`, as read) without what names its build beside the
    release, evidence and commit: the time the index was made, whether the tree had uncommitted
    changes, and the earlier release the review queue's order compared the build with."""
    if name == INDEX and isinstance(obj, dict):
        obj.pop("created", None)
        if isinstance(obj.get("project"), dict):
            obj["project"].pop("dirty", None)
    if name == QUEUE and isinstance(obj, dict):
        changes = ((obj.get("order") or {}).get("signals") or {}).get("changes")
        if isinstance(changes, dict):
            changes.pop("from", None)
    return obj


def _same_material(new: dict[str, bytes], old: dict[str, bytes]) -> bool:
    """Whether the files `new` of a build hold what the files `old` of an earlier one hold, apart
    from what names each build: its release, evidence record and project commit, wherever they
    are given (a paper kept in the project's repository has the project's commit), and
    `_unnamed`. Anything else that differs, or a file that cannot be read, is a difference."""
    try:
        ni, oi = json.loads(new[INDEX]), json.loads(old[INDEX])
    except (KeyError, ValueError):
        return False
    swap = {}
    for a, b in zip(_build_names(ni), _build_names(oi)):
        if a != b:
            if not (isinstance(a, str) and isinstance(b, str)):
                return False
            swap[a] = b
    commits = (_build_names(ni)[2], _build_names(oi)[2])
    if commits[0] != commits[1]:
        # A paper that is a file of the project is the manuscript at the project's commit, named
        # by that commit (`versions.manuscript_record`).
        from .versions import manuscript_record
        a, b = (manuscript_record(c) for c in commits)
        swap.update({a[k]: b[k] for k in ("id", "label")})
    for name, b in new.items():
        if b == old.get(name):
            continue
        if name not in old or not name.endswith(".json"):
            return False
        try:
            x, y = _renamed(json.loads(b), swap), json.loads(old[name])
        except ValueError:
            return False
        if _unnamed(name, x) != _unnamed(name, y):
            return False
    return set(new) == set(old)


def _unchanged(out: Path, manifest: dict, files: dict[str, bytes]) -> dict | None:
    """The snapshot written at `out` before, when it is complete and holds this build's review
    material (`_same_material`, with the same PDFs and the same parts left out): its manifest,
    with `out`, `digest`, `unchanged` and the release of this build (`built`). None when it must
    be written again."""
    raw = (out / MANIFEST).read_bytes()
    try:
        old = _manifest(raw, str(out))
        _check_dir(out, old, str(out))
        _check_sources(out / DATA, old, str(out))
    except SnapshotError:
        return None
    if set(old["files"]) != set(files) or any(old.get(k) != manifest.get(k) for k in
                                              ("schema", "mode", "pdf", "left_out", "paper_text")):
        return None
    if not _same_material(files, {n: (out / n).read_bytes() for n in files}):
        return None
    return {**old, "out": str(out), "digest": _sha256(raw), "unchanged": True,
            "built": manifest["sources"].get("release")}


def summary_text(m: dict, kept_here: bool = False, given: str | None = None) -> str:
    """What `review pack` says it wrote (`m`, the manifest `pack` returns); `kept_here` when it is
    the snapshot the project keeps (`project_path`), which the review steps find without a flag;
    `given`, the path a reviewer passes with --snapshot (by default the one written)."""
    c, src = m["contains"], m["sources"]
    proj = src.get("project") or {}
    papers = "; ".join(f"paper {p.get('id')}" + (f" at revision {p['revision']}"
                                                  if p.get("revision") else "")
                       for p in src.get("papers") or [])
    from .snapshot_text import source_name
    texts = m.get("paper_text") or {}
    none = bool(texts) and all(e.get("included") is False for e in texts.values())
    head = (f"the review snapshot {m['out']} is current, as written for release "
            f"{src.get('release')}" if m.get("unchanged") else
            f"wrote the review snapshot {m['out']}: release {src.get('release')}")
    lines = [head
             + (f", project commit {proj['commit']}" if proj.get("commit") else "")
             + (f"; {papers}" if papers else "")
             + (f"; this build, release {m['built']}, holds the same review material"
                if m.get("unchanged") and m.get("built") != src.get("release") else ""),
             f"  {c['units']} review unit(s), {c['open_units']} of them open",
             f"  where the paper's passages of {c['claims']} claim(s) are in its source" if none
             else f"  the paper's passages of {c['claims']} claim(s)",
             f"  {c['declarations']} Lean declaration record(s): statements and definitions",
             f"  {c['author_reviews']} review(s) by the author, shown at step 3",
             "  the paper's PDF" if c["pdfs"] else
             "  no PDF of the paper (`--pdf` includes it)"]
    for pid, e in sorted(texts.items()):
        if e.get("included") is False:
            lines.append(f"  paper {pid}: its text left out; a reviewer reads each passage from "
                         f"{source_name(e.get('source') or {})}, checked against its SHA-256")
        elif e.get("because") in ("asked", "pdf"):
            lines.append(f"  paper {pid}: its text kept, {KEPT[e['because']]}")
    for what in m.get("left_out") or []:
        lines.append(f"  left out: {what}")
    lines += [f"Manifest digest {m['digest']}.",
              ("It holds no text of the paper's source: share it where your Lean and reviews "
               "may go. " if none else
               "Its contents are yours to publish: share it where the paper's text and your "
               "reviews may go. ")
              + ("Commit it with the project: a reviewer who clones the repository reviews it "
                 "with `machinechecked review next`, without Lean, and `machinechecked build` "
                 "keeps it current." if kept_here else
                 "A reviewer opens it with `machinechecked review next --snapshot "
                 f"{given or m['out']}`, without Lean.")]
    return "\n".join(lines)


def refresh_line(m: dict, shown: str) -> str:
    """What `build` says of the snapshot the project keeps (`m`, the manifest `pack` returned;
    `shown`, its path as the command shows it)."""
    from .snapshot_text import left_out
    rel = m["sources"].get("release")
    out = sorted(left_out(m))
    without = (f"; the text of paper {', '.join(out)} is left out, for the reviewer to read "
               "from its source" if out else "")
    if not m.get("unchanged"):
        return (f"wrote the review snapshot {shown} (release {rel}{without}): commit it with the "
                "project for reviewers who clone the repository")
    return (f"the review snapshot {shown} is current (release {rel}"
            + (f"; this build, release {m['built']}, holds the same review material"
               if m.get("built") != rel else "") + without + ")")


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
    if not isinstance(m, dict) or m.get("schema") not in SCHEMAS:
        schema = m.get("schema") if isinstance(m, dict) else None
        raise SnapshotError(f"{where} is not a review snapshot this version reads (schema "
                            f"{schema!r}, not {' or '.join(SCHEMAS)}): ask its author for one "
                            "written by `machinechecked review pack`")
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
    if m["schema"] == SCHEMA_WITHOUT_TEXT:
        from .snapshot_text import REFS, left_out
        if REFS not in files or not left_out(m):
            raise SnapshotError(f"{where}: the manifest leaves out the paper's text without "
                                f"saying where it is ({REFS}, paper_text)")
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
    return {"kind": "snapshot", "manifest_sha256": _sha256(raw), "schema": m.get("schema"),
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
