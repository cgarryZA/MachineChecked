"""Run the Lean probe inside a project and collect its records.

The probe body (`data/ProofLensProbe.lean`) is prefixed with `import Lean` and the project's
modules and run with `lake env lean` in the project root, with the project's own toolchain. The
project is not modified and needs no dependency on ProofLens.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from importlib import resources
from pathlib import Path

from .config import Config
from .util import run, sha256_text

FINGERPRINT_VERSION = "pl-fp-v1"


class ProbeError(RuntimeError):
    """A Lean session that failed. `deterministic` is true when Lean finished and reported an
    error in what it was given (a module that does not import or elaborate): the same inputs
    fail the same way. It is false for a failure of resources or of the session itself (out of
    memory, a timeout, a heartbeat budget, a killed process, a session that did not finish),
    which another attempt may not repeat."""

    def __init__(self, message: str, deterministic: bool = False):
        super().__init__(message)
        self.deterministic = deterministic


# What Lean or the system prints when a session runs out of a resource rather than meeting an
# error in its input. A heartbeat budget is a resource: a larger budget or another machine may
# finish where this one did not.
RESOURCE_SIGNS = ("out of memory", "bad_alloc", "cannot allocate memory", "heartbeats",
                  "(deterministic) timeout", "stack overflow", "killed", "timed out")


def failure_is_deterministic(returncode: int, text: str) -> bool:
    """Whether a finished Lean session's failure is an error in its input: Lean exited on its
    own (no signal), printed an `error`, and showed no sign of running out of a resource."""
    if returncode <= 0 or returncode >= 128:      # a signal (128 + n through a shell) or no exit
        return False
    low = text.lower()
    if any(sign in low for sign in RESOURCE_SIGNS):
        return False
    return "error" in low


def requests_from_inventory(inv: dict) -> list[dict]:
    """One request per specification, proof, refutation, witness and definition named by the
    inventory, and one `link` request per declaration a proof step is linked to (`lean`, and its
    different formal route), without duplicates and in a stable order."""
    reqs, seen = [], set()

    def add(r):
        key = (r["kind"], r["name"], r.get("spec"))
        if key not in seen:
            seen.add(key)
            reqs.append(r)

    for c in inv["claims"]:
        for cl in c.get("clauses", []):
            for d in cl.get("defs", []):
                add({"kind": "decl", "name": d})
            if cl.get("spec"):
                add({"kind": "spec", "name": cl["spec"]})
                if cl.get("accept"):
                    add({"kind": "accept", "name": cl["accept"], "spec": cl["spec"]})
                if cl.get("refute"):
                    add({"kind": "refute", "name": cl["refute"], "spec": cl["spec"]})
            for w in [cl.get("witness")] + [r.get("witness") for r in cl.get("regimes", [])]:
                if w:
                    add({"kind": "witness", "name": w})
    from .steps import is_step, lean_names, route_names
    for c in inv["claims"]:
        if is_step(c):
            for n in lean_names(c) + route_names(c):
                add({"kind": "link", "name": n})
    return reqs


# The request for the names in the project's module docstrings that nothing declares.
MODDOCS = {"kind": "moddocs", "name": ""}


def fingerprint(canon: str) -> str:
    return f"{FINGERPRINT_VERSION}:{sha256_text(canon)}"


def lib_names(root: Path) -> list[str]:
    """The `lean_lib` names of the project's lakefile."""
    names = []
    t = root / "lakefile.toml"
    if t.exists():
        cfg = tomllib.loads(t.read_text(encoding="utf-8"))
        names = [lib["name"] for lib in cfg.get("lean_lib", [])]
        if not names and cfg.get("name"):
            names = [str(cfg["name"]).capitalize()]
    l = root / "lakefile.lean"
    if l.exists():
        names += re.findall(r"^\s*lean_lib\s+«?([\w.]+)»?", l.read_text(encoding="utf-8"), re.M)
    return list(dict.fromkeys(names))


def library_of(module: str, libs: list[str]) -> str:
    """The library a module belongs to: the one whose root is its first component."""
    first = module.split(".")[0]
    return next((l for l in libs if l.split(".")[0] == first), first)


def by_library(modules: list[str], libs: list[str]) -> list[tuple[str, list[str]]]:
    """The modules grouped by library, each group in the order given. Each group is probed in
    its own Lean session: two libraries may declare the same name (a statement left as a
    challenge and its solution), and Lean can load both and silently keep one."""
    groups: dict[str, list[str]] = {}
    for m in modules:
        groups.setdefault(library_of(m, libs), []).append(m)
    return sorted(groups.items())


HEARTBEAT = 60  # seconds between progress lines while a Lean session runs


def _run_watched(cmd: list[str], cwd: Path, env: dict, timeout: int, out: Path, log, label: str):
    """Run `cmd` like `util.run`, and while it runs, report every HEARTBEAT seconds how long it
    has run and how much it has written, so a long module load does not look like a hang."""
    import subprocess
    import time
    with tempfile.TemporaryFile("w+") as so, tempfile.TemporaryFile("w+") as se:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=so, stderr=se, text=True)
        start = time.monotonic()
        while True:
            try:
                proc.wait(timeout=HEARTBEAT)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.monotonic() - start
                if elapsed > timeout:
                    proc.kill()
                    proc.wait()
                    raise ProbeError(f"the Lean probe ({label}) timed out after {timeout} s")
                size = out.stat().st_size if out.exists() else 0
                log(f"lean: {label}: {int(elapsed // 60)} min, "
                    + (f"{size / 1e6:.1f} MB of records written" if size else
                       "loading the modules"))
        so.seek(0)
        se.seek(0)
        return subprocess.CompletedProcess(cmd, proc.returncode, so.read(), se.read())


def lean_session(root: Path, modules: list[str], query: dict, read, lake: str = "lake",
                 timeout: int = 3600, work: Path | None = None, log=None, label: str = ""):
    """Run the probe in one Lean session importing `modules`, in the project at `root` with its
    own toolchain, and return `read(lines)` of its output, read as it is iterated (the output
    can be gigabytes). The output file is written in `work` when given (rather than a system
    temporary folder, which may be in memory). With `log`, the session announces itself and
    reports its progress while it runs. Raises ProbeError if the session fails."""
    body = resources.files("prooflens").joinpath("data/ProofLensProbe.lean").read_text()
    header = "import Lean\n" + "".join(f"import {m}\n" for m in modules) + "\n"
    if work is not None:
        work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="prooflens-probe-", dir=work) as tmp:
        tmp = Path(tmp)
        (tmp / "Probe.lean").write_text(header + body)
        (tmp / "query.json").write_text(json.dumps(query))
        env = dict(os.environ, PROOFLENS_QUERY=str(tmp / "query.json"),
                   PROOFLENS_OUT=str(tmp / "out.jsonl"))
        out = tmp / "out.jsonl"
        cmd = [lake, "env", "lean", str(tmp / "Probe.lean")]
        if log is None:
            import subprocess
            try:
                r = run(cmd, cwd=root, env=env, timeout=timeout)
            except subprocess.TimeoutExpired:
                raise ProbeError(f"the Lean probe timed out after {timeout} s") from None
        else:
            label = label or ", ".join(modules[:2]) + ("…" if len(modules) > 2 else "")
            log(f"lean: {label}: loading {len(modules)} module(s)")
            r = _run_watched(cmd, root, env, timeout, out, log, label)
        if r.returncode != 0 or not out.exists():
            text = f"{r.stdout[-3000:]}\n{r.stderr[-3000:]}"
            raise ProbeError(f"the Lean probe failed ({r.returncode}):\n{text}",
                             deterministic=r.returncode != 0
                             and failure_is_deterministic(r.returncode, text))
        with out.open(encoding="utf-8") as f:
            return read(line for line in f if line.strip())


def run_probe(cfg: Config, requests: list[dict], lake: str = "lake",
              timeout: int = 3600, build: bool = True) -> dict:
    """Build the project's modules (unless `build` is false), run the probe on them, one Lean
    session per library, and return its records grouped by kind, with every canonical
    serialisation replaced by its SHA-256 fingerprint. When the modules are in one library this
    is a single session importing them in the order configured."""
    if build:
        r = run([lake, "build", *cfg.modules], cwd=cfg.lean_root, timeout=timeout)
        if r.returncode != 0:
            raise ProbeError(f"lake build failed:\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
    query = {"scope_roots": cfg.scope_roots, "spec_prefix": cfg.spec_prefix,
             "accept_prefix": cfg.accept_prefix, "allowed_axioms": cfg.allowed_axioms,
             "requests": requests}
    groups = by_library(cfg.modules, lib_names(cfg.lean_root))
    work = cfg.out_dir / "build"
    if len(groups) == 1:
        return lean_session(cfg.lean_root, cfg.modules, query, parse_records, lake, timeout, work)
    parts = []
    for lib, mods in groups:
        try:
            parts.append((lib, lean_session(cfg.lean_root, mods, query, parse_records, lake,
                                            timeout, work)))
        except ProbeError as e:
            raise ProbeError(f"library {lib} ({', '.join(mods)}): {e}") from None
        # A session loads only its own library: a docstring name that begins with the root of
        # another library's modules may be declared there, so it is not reported.
        others = {m.split(".")[0] for l, ms in groups if l != lib for m in ms}
        parts[-1][1]["moddocs"] = [d for d in parts[-1][1]["moddocs"]
                                   if d["name"].split(".")[0] not in others]
    return merge_records(parts)


def _module(rec: dict) -> str | None:
    return rec.get("module") or (rec.get("decl") or {}).get("module")


def _pick(found: list[tuple[str, dict]], missing: dict) -> dict:
    """One request's record from several sessions: the one that found it; if sessions found
    different declarations under the name, the name is ambiguous (an error, never a choice)."""
    if not found:
        return missing
    distinct = {(_module(r), r.get("fingerprint") or r.get("legacy_hash")) for _, r in found}
    if len(distinct) == 1:
        return found[0][1]
    rec = dict(found[0][1])
    mods = ", ".join(sorted(f"{lib}: {_module(r)}" for lib, r in found))
    rec["errors"] = list(rec.get("errors", [])) + [f"ambiguous: declared in {mods}"]
    return rec


def merge_records(parts: list[tuple[str, dict]]) -> dict:
    """The records of several sessions (one per library) as one result."""
    res = {"env": parts[0][1]["env"], "layering": [], "specs": {}, "proofs": {}, "decls": {},
           "defs": {}, "moddocs": [], "complete": all(r["complete"] for _, r in parts)}
    if any("links" in r for _, r in parts):
        res["links"] = {}
    seen = set()
    for _, r in parts:
        for d in r.get("moddocs", []):
            if d not in res["moddocs"]:
                res["moddocs"].append(d)
        for v in r["layering"]:
            key = json.dumps(v, sort_keys=True)
            if key not in seen:
                seen.add(key)
                res["layering"].append(v)
        for name, d in r["decls"].items():
            res["decls"].setdefault(name, d)
    for key in ("specs", "proofs", "defs") + (("links",) if "links" in res else ()):
        for k in dict.fromkeys(k for _, r in parts for k in r.get(key, {})):
            recs = [(lib, r[key][k]) for lib, r in parts if k in r.get(key, {})]
            found = [(lib, x) for lib, x in recs if "missing" not in x.get("errors", [])]
            res[key][k] = _pick(found, recs[0][1])
    return res


def _strip_decl(rec: dict) -> dict:
    rec = dict(rec)
    rec["fingerprint"] = fingerprint(rec.pop("canon"))
    rec.pop("record", None)
    return rec


def parse_records(lines) -> dict:
    res = {"env": None, "layering": [], "specs": {}, "proofs": {}, "decls": {}, "defs": {},
           "moddocs": [], "complete": False}
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        kind = rec.get("record")
        if kind == "env":
            res["env"] = {"lean": rec["lean"], "githash": rec["githash"]}
        elif kind == "layering":
            res["layering"] = rec["violations"]
        elif kind == "decl":
            res["decls"][rec["name"]] = _strip_decl(rec)
        elif kind == "defclosure":
            res["defs"][rec["name"]] = {"closure": rec.get("closure", []),
                                        "errors": rec.get("errors", [])}
        elif kind == "spec":
            rec = dict(rec)
            rec.pop("record")
            if "decl" in rec:
                d = _strip_decl(rec.pop("decl"))
                res["decls"][d["name"]] = d
                rec["legacy_hash"] = d["legacy_hash"]
                rec["fingerprint"] = d["fingerprint"]
            res["specs"][rec["name"]] = rec
        elif kind == "link":
            # A declaration a proof step is linked to: its statement and proof checks, as the
            # zero-configuration view records them.
            rec = dict(rec)
            rec.pop("record")
            if isinstance(rec.get("decl"), dict):
                d = _strip_decl(rec["decl"])
                rec["decl"] = d
                res["decls"].setdefault(d["name"], d)
            res.setdefault("links", {})[rec["name"]] = rec
        elif kind in ("accept", "refute", "witness"):
            rec = dict(rec)
            rec["kind"] = rec.pop("record")
            res["proofs"][f"{rec['kind']}:{rec['name']}:{rec.get('spec') or ''}"] = rec
        elif kind == "moddoc":
            res["moddocs"].append({k: rec[k] for k in ("module", "line", "name", "heading",
                                                       "item_lead") if k in rec})
        elif kind == "done":
            res["complete"] = True
    if not res["complete"]:
        raise ProbeError("probe output ends before its `done` record")
    return res
