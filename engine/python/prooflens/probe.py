"""Run the Lean probe inside a project and collect its records.

The probe body (`data/ProofLensProbe.lean`) is prefixed with `import Lean` and the project's
modules and run with `lake env lean` in the project root, with the project's own toolchain. The
project is not modified and needs no dependency on ProofLens.
"""

from __future__ import annotations

import json
import os
import tempfile
from importlib import resources
from pathlib import Path

from .config import Config
from .util import run, sha256_text

FINGERPRINT_VERSION = "pl-fp-v1"


class ProbeError(RuntimeError):
    pass


def requests_from_inventory(inv: dict) -> list[dict]:
    """One request per specification, proof, refutation, witness and definition named by the
    inventory, without duplicates and in a stable order."""
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
    return reqs


def fingerprint(canon: str) -> str:
    return f"{FINGERPRINT_VERSION}:{sha256_text(canon)}"


def run_probe(cfg: Config, requests: list[dict], lake: str = "lake",
              timeout: int = 3600, build: bool = True) -> dict:
    """Build the project's modules (unless `build` is false), run the probe, and return its
    records grouped by kind, with every canonical serialisation replaced by its SHA-256
    fingerprint."""
    if build:
        r = run([lake, "build", *cfg.modules], cwd=cfg.lean_root, timeout=timeout)
        if r.returncode != 0:
            raise ProbeError(f"lake build failed:\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
    body = resources.files("prooflens").joinpath("data/ProofLensProbe.lean").read_text()
    header = "import Lean\n" + "".join(f"import {m}\n" for m in cfg.modules) + "\n"
    with tempfile.TemporaryDirectory(prefix="prooflens-probe-") as tmp:
        tmp = Path(tmp)
        (tmp / "Probe.lean").write_text(header + body)
        (tmp / "query.json").write_text(json.dumps({
            "scope_roots": cfg.scope_roots, "spec_prefix": cfg.spec_prefix,
            "accept_prefix": cfg.accept_prefix, "allowed_axioms": cfg.allowed_axioms,
            "requests": requests}))
        env = dict(os.environ, PROOFLENS_QUERY=str(tmp / "query.json"),
                   PROOFLENS_OUT=str(tmp / "out.jsonl"))
        r = run([lake, "env", "lean", str(tmp / "Probe.lean")], cwd=cfg.lean_root, env=env,
                timeout=timeout)
        out = tmp / "out.jsonl"
        if r.returncode != 0 or not out.exists():
            raise ProbeError(f"probe failed ({r.returncode}):\n{r.stdout[-4000:]}\n{r.stderr[-4000:]}")
        return parse_records(out.read_text(encoding="utf-8").splitlines())


def _strip_decl(rec: dict) -> dict:
    rec = dict(rec)
    rec["fingerprint"] = fingerprint(rec.pop("canon"))
    rec.pop("record", None)
    return rec


def parse_records(lines: list[str]) -> dict:
    res = {"env": None, "layering": [], "specs": {}, "proofs": {}, "decls": {}, "defs": {},
           "complete": False}
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
        elif kind in ("accept", "refute", "witness"):
            rec = dict(rec)
            rec["kind"] = rec.pop("record")
            res["proofs"][f"{rec['kind']}:{rec['name']}:{rec.get('spec') or ''}"] = rec
        elif kind == "done":
            res["complete"] = True
    if not res["complete"]:
        raise ProbeError("probe output ends before its `done` record")
    return res
