"""Extracted Lean facts, kept between builds: one local store shared by `view`, `build`,
`check` and `inspect`.

The probe's answers (a module's index, a linked declaration's record with the declarations of
its closure, a declaration's dependencies) are stored with what they were extracted from:

* the version of MachineChecked and of the store's format, the probe, the libraries asked about
  and the axioms allowed;
* the toolchain, the Lake manifest and the lakefiles of the project and of each path
  dependency;
* for each module of the project or of a path dependency in the environment the answer came
  from (the modules it was asked of and everything they import, as Lean reports it), the
  content of its source and the size and time of each compiled file.

An answer is reused only while all of these are unchanged. An edit to a module therefore
reopens the answers whose environment holds that module, and no other; a note, a link or the
paper changes none of them. The modules of other packages (Mathlib, say) are pinned by the
manifest and the toolchain. The store is derived data: deleting it costs only the time to
extract the facts again, and it holds nothing authored.

Writes are atomic, and `lock` serialises extraction between processes, so concurrent requests
for the same facts make one extraction: the later request finds the stored answer.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import threading
import time
from importlib import resources
from pathlib import Path

from .probe import FINGERPRINT_VERSION
from .util import canonical_json, read_json

FORMAT = "machinechecked/facts@1"
DIR = "facts"


def probe_digest() -> str:
    """The probe's own text: a change to it reopens every stored answer."""
    body = resources.files("prooflens").joinpath("data/ProofLensProbe.lean").read_bytes()
    return hashlib.sha256(body).hexdigest()


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("machinechecked")
    except PackageNotFoundError:
        return "unknown"


def _file_digest(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return "absent"


def _input_roots(root: Path) -> list[Path]:
    """The project and every path dependency of its Lake manifest."""
    roots = [root.resolve()]
    lm = root / "lake-manifest.json"
    try:
        packages = read_json(lm).get("packages", []) if lm.exists() else []
    except (OSError, ValueError):
        packages = []
    for p in packages:
        if p.get("type") == "path" and p.get("dir"):
            d = (root / p["dir"]).resolve()
            if d not in roots:
                roots.append(d)
    return roots


GLOBAL_REASONS = {
    "format": "MachineChecked was updated",
    "probe": "the Lean probe changed",
    "query": "the libraries or the allowed axioms changed",
    "toolchain": "the Lean toolchain changed",
    "lake": "a lakefile or a Lake manifest changed",
}


class Store:
    """The facts store of the project at `root`, kept in `work/facts`."""

    def __init__(self, root: Path, libs: list[str], work: Path, allowed_axioms: list[str]):
        self.root = root
        self.dir = work / DIR
        self.roots = _input_roots(root)
        lake = hashlib.sha256()
        for r in self.roots:
            for f in ("lakefile.toml", "lakefile.lean", "lake-manifest.json"):
                lake.update(f"{r.name}/{f}:{_file_digest(r / f)}\n".encode())
        self.context = {
            "format": f"{FORMAT}:{FINGERPRINT_VERSION}:{_tool_version()}",
            "probe": probe_digest(),
            "query": hashlib.sha256(canonical_json(
                {"libs": sorted(l.split(".")[0] for l in libs),
                 "axioms": sorted(allowed_axioms)}).encode()).hexdigest(),
            "toolchain": _file_digest(root / "lean-toolchain"),
            "lake": lake.hexdigest(),
        }
        self._own: dict[str, str | None] = {}
        self._mutex = threading.Lock()
        # What this process did, for progress messages and tests.
        self.stats = {"stored": 0}

    # -- validity -------------------------------------------------------------------------

    def own(self, module: str) -> str | None:
        """The digest of a module of the project or of a path dependency: its source and its
        compiled files. None for a module of another package (or one with no compiled file):
        its content is pinned by the manifest and the toolchain."""
        with self._mutex:
            if module in self._own:
                return self._own[module]
        rel = Path(*module.split("."))
        out = None
        for r in self.roots:
            for base in (r / ".lake" / "build" / "lib" / "lean", r / ".lake" / "build" / "lib"):
                d = base / rel.parent
                stem = rel.name + ".olean"
                try:
                    built = sorted(f for f in d.iterdir()
                                   if f.name == stem or f.name.startswith(stem + "."))
                except OSError:
                    continue
                if not any(f.name == stem for f in built):
                    continue
                h = hashlib.sha256()
                h.update(f"source:{_file_digest(r / rel.with_suffix('.lean'))}\n".encode())
                for f in built:
                    st = f.stat()
                    h.update(f"{f.name}:{st.st_size}:{st.st_mtime_ns}\n".encode())
                    if f.name.endswith(".hash"):
                        h.update(f.read_bytes())
                out = h.hexdigest()
                break
            if out is not None:
                break
        with self._mutex:
            self._own[module] = out
        return out

    def environment(self, modules, graph: dict[str, list[str]]) -> dict[str, str]:
        """The digests of the project's (and path dependencies') modules among `modules` and
        everything they import, by the import graph a probe session reported."""
        seen, stack, env = set(), list(modules), {}
        while stack:
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            d = self.own(m)
            if d is not None:
                env[m] = d
            stack.extend(graph.get(m, []))
        return env

    def why_stale(self, entry: dict | None) -> str | None:
        """Why a stored entry no longer describes the project, or None when it does."""
        if entry is None:
            return "not extracted yet"
        ctx = entry.get("context") or {}
        for k, reason in GLOBAL_REASONS.items():
            if ctx.get(k) != self.context[k]:
                return reason
        changed = sorted(m for m, d in (entry.get("env") or {}).items() if self.own(m) != d)
        if changed:
            return "changed: " + ", ".join(changed[:3]) + ("…" if len(changed) > 3 else "")
        return None

    # -- entries --------------------------------------------------------------------------

    def _path(self, kind: str, key: str) -> Path:
        return self.dir / kind / (hashlib.sha256(key.encode()).hexdigest() + ".json")

    def get(self, kind: str, key: str) -> tuple[dict | None, str | None]:
        """The stored entry `kind`/`key` if it is current, else None and why not."""
        try:
            entry = json.loads(self._path(kind, key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entry = None
        if entry is not None and entry.get("key") != key:
            entry = None
        why = self.why_stale(entry)
        return (entry, None) if why is None else (None, why)

    def put(self, kind: str, key: str, env: dict[str, str], **data) -> dict:
        entry = {"key": key, "context": self.context, "env": env, **data}
        _atomic_write(self._path(kind, key), json.dumps(entry, ensure_ascii=False))
        self.stats["stored"] += 1
        return entry

    def drop(self, kind: str) -> None:
        """Forget every stored entry of one kind (a targeted refresh)."""
        d = self.dir / kind
        if d.is_dir():
            for f in d.glob("*.json"):
                with contextlib.suppress(OSError):
                    f.unlink()

    # -- declaration records, stored once -------------------------------------------------

    def put_object(self, rec: dict) -> str:
        text = canonical_json(rec)
        key = hashlib.sha256(text.encode()).hexdigest()
        p = self.dir / "objects" / key[:2] / f"{key}.json"
        if not p.exists():
            _atomic_write(p, text)
        return key

    def get_object(self, key: str) -> dict | None:
        try:
            return json.loads((self.dir / "objects" / key[:2] / f"{key}.json")
                              .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # -- one extraction at a time ---------------------------------------------------------

    @contextlib.contextmanager
    def lock(self, log=None):
        """Hold the store's lock: one process (or thread) extracts at a time, and one that
        waits then finds what the other stored."""
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / ".lock", "a+") as f:
            _lock(f, log)
            try:
                yield self
            finally:
                _unlock(f)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


WAITING = "lean: waiting for another MachineChecked process that is extracting Lean facts"


def _lock(f, log) -> None:
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt
        said = False
        while True:
            try:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if log and not said:
                    log(WAITING)
                    said = True
                time.sleep(0.5)
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if log:
            log(WAITING)
        fcntl.flock(f, fcntl.LOCK_EX)


def _unlock(f) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt
        f.seek(0)
        with contextlib.suppress(OSError):
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(f, fcntl.LOCK_UN)


def graphs(recs: list[dict]) -> dict[str, dict[str, list[str]]]:
    """The import graph each probe session reported (`module` records), by session label."""
    out: dict[str, dict[str, list[str]]] = {}
    for r in recs:
        if r.get("record") == "module":
            out.setdefault(r.get("probe_group", ""), {})[r["name"]] = \
                list(dict.fromkeys(r.get("imports", [])))
    return out
