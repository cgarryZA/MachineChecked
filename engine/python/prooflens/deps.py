"""What a Lean declaration rests on: `machinechecked inspect`.

The probe's other records erase proofs, so that fingerprints and reviews see statements and data
only. This asks Lean for the constants a declaration's statement mentions and, kept apart, those
its proof (or a definition's body) uses, and follows both through the project's libraries. The
result says what Lean terms mention. It does not say that a declaration formalises a statement
of a paper: that takes a reviewer.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path

from .config import work_dir_name
from .probe import lib_names
from .simple import (ViewError, built_modules, declaring_modules, lean_digest, probe_modules,
                     run_simple_probe)

SCHEMA = "machinechecked/inspect@1"
NOTE = ("Dependencies are the constants Lean's terms mention: what a statement is stated with, "
        "and what its proof uses. They do not show that a declaration formalises a statement of "
        "a paper; that takes a reviewer.")
VALUE_KIND = {"theorem": "proof", "def": "definition body", "opaque": "definition body",
              "inductive": "constructors", "ctor": "inductive type"}


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("machinechecked")
    except PackageNotFoundError:
        return "unknown"


def _probe_digest() -> str:
    """The probe's own text: a change to it invalidates every stored answer."""
    body = resources.files("prooflens").joinpath("data/ProofLensProbe.lean").read_bytes()
    return hashlib.sha256(body).hexdigest()[:16]


def cache_dir(root: Path) -> Path:
    return root / work_dir_name(root) / "build" / "inspect"


def cache_key(root: Path, name: str, module: str | None) -> str:
    """The answer is reused while no Lean input or built module of the project changes, and for
    the same tool and probe."""
    h = hashlib.sha256()
    for part in (lean_digest(root), name, module or "", _tool_version(), _probe_digest()):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()


def _resolve(root: Path, name: str, module: str | None, built: list[str],
             unbuilt: list[str]) -> tuple[str | None, dict | None]:
    """The module to probe, or the answer when there is none to probe. A name two modules
    declare is ambiguous until its module is given, never a choice; a declaration whose module
    is not built is not built, not missing. A name the source does not show (one a macro
    generates, say) is looked for in every library."""
    if module:
        if module in built:
            return module, None
        if module in unbuilt:
            return None, {"status": "not built", "modules": [module]}
        return None, {"status": "not found", "modules": [],
                      "reason": f"{module} is not a module of the project's libraries"}
    found = sorted(declaring_modules(root, built + unbuilt, name))
    if len(found) > 1:
        return None, {"status": "ambiguous", "modules": found}
    if found:
        return (found[0], None) if found[0] in built else \
            (None, {"status": "not built", "modules": found})
    return None, None


def _user_facing(nodes: dict[str, dict]):
    """Names as a reader knows them: a compiler-generated constant (`_proof_1`, `match_1`, an
    auxiliary lemma) stands for the user-facing declarations it uses, transitively."""
    memo: dict[str, set[str]] = {}

    def through(n: str, stack: frozenset[str]) -> set[str]:
        if n in memo:
            return memo[n]
        node = nodes.get(n)
        if node is None or n in stack:
            return set()
        out = set()
        for d in node["statement_uses"] + node["value_uses"]:
            out |= collapse([d], stack | {n})
        memo[n] = out
        return out

    def collapse(names, stack=frozenset()) -> set[str]:
        out = set()
        for d in names:
            node = nodes.get(d)
            if node is None:
                continue
            out |= {d} if node["user_facing"] else through(d, stack)
        return out

    return lambda names: sorted(collapse(names))


def _assemble(name: str, nodes: list[dict], summary: dict) -> dict:
    by = {n["name"]: n for n in nodes}
    root = by[name]
    uf = _user_facing(by)
    shown = [n for n in nodes if n["user_facing"] and n["name"] != name]
    external: dict[str, int] = {}
    distinct = set()
    for n in nodes:
        distinct |= set(n["statement_external"]) | set(n["value_external"])
    for c in distinct:
        external[c.split(".")[0]] = external.get(c.split(".")[0], 0) + 1
    decl = {"name": name, "kind": root["kind"], "module": root["module"],
            "file": root["module"].replace(".", "/") + ".lean", "range": root["range"],
            "doc": root["doc"], "statement": root["type"],
            "axioms": summary.get("axioms", []), "sorry": summary.get("sorry", False)}
    return {
        "declaration": decl,
        "value_kind": VALUE_KIND.get(root["kind"], "none"),
        "statement_dependencies": uf(root["statement_uses"]),
        "proof_dependencies": uf(root["value_uses"]),
        "external_dependencies": {"statement": sorted(set(root["statement_external"])),
                                  "proof": sorted(set(root["value_external"]))},
        "closure": {
            "declarations": len(shown),
            "generated": sum(1 for n in nodes if not n["user_facing"]),
            "deepest": max((n["depth"] for n in shown), default=0),
            "members": [{"name": n["name"], "kind": n["kind"], "module": n["module"],
                         "range": n["range"], "depth": n["depth"], "statement": n["type"],
                         "doc": n["doc"],
                         "statement_dependencies": uf(n["statement_uses"]),
                         "proof_dependencies": uf(n["value_uses"]),
                         "external": len(set(n["statement_external"]) | set(n["value_external"]))}
                        for n in sorted(shown, key=lambda n: (n["depth"], n["name"]))],
            "external": {"constants": len(distinct),
                         "by_package": dict(sorted(external.items(), key=lambda kv: -kv[1]))},
        },
    }


def _read(recs: list[dict], name: str) -> tuple[list[dict], dict | None]:
    nodes = [r for r in recs if r.get("record") == "depnode"]
    summary = next((r for r in recs if r.get("record") == "deps" and r.get("name") == name), None)
    if summary is not None:
        errs = [e for e in summary.get("errors", []) if e.startswith("probe-error")]
        if errs:
            raise ViewError(errs[0])
    return nodes, summary


def inspect(root: Path, name: str, module: str | None = None, lake: str = "lake", log=None,
            refresh: bool = False) -> dict:
    """The dependencies of `name` in the Lean project at `root`, as one JSON-ready document."""
    libs = lib_names(root)
    if not libs:
        raise ViewError("no Lean library found in the lakefile")
    built, unbuilt = built_modules(root, libs)
    if not built:
        raise ViewError("the Lean project is not built (run `lake build`)")
    head = {"schema": SCHEMA, "name": name, "tool": _tool_version(), "note": NOTE}
    target, answer = _resolve(root, name, module, built, unbuilt)
    if answer is not None:
        return {**head, "ok": False, **answer}
    key = cache_key(root, name, target or module)
    stored = cache_dir(root) / f"{key}.json"
    if stored.exists() and not refresh:
        body = json.loads(stored.read_text(encoding="utf-8"))
        return {**head, **body, "cache": {"hit": True, "key": key[:16]}}
    work = root / work_dir_name(root) / "build"
    request = [{"kind": "deps", "name": name}]
    if target is not None:
        nodes, summary = _read(run_simple_probe(root, [target], libs, request, lake, work=work,
                                                log=log, label=target), name)
    else:
        # The source does not show the name: ask every library, each in its own session.
        recs, failed = probe_modules(root, built, libs, request, lake, log=log or (lambda m: None),
                                     work=work)
        hits = {}
        for r in recs:
            if r.get("record") == "deps" and r.get("name") == name and not r.get("errors"):
                hits.setdefault(r["probe_group"], r)
        if len({h.get("module") for h in hits.values()}) > 1:
            return {**head, "ok": False, "status": "ambiguous",
                    "modules": sorted(h.get("module") for h in hits.values())}
        group = next(iter(hits), None)
        nodes, summary = _read([r for r in recs if r.get("probe_group") == group], name) \
            if group else ([], None)
        if group is None and failed:
            return {**head, "ok": False, "status": "not checked", "modules": sorted(failed),
                    "reason": "some built modules could not be loaded"}
    if summary is None or "missing" in summary.get("errors", []) or name not in \
            {n["name"] for n in nodes}:
        body = {"ok": False, "status": "not found", "modules": [target] if target else []}
    else:
        body = {"ok": True, "status": "found", **_assemble(name, nodes, summary)}
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(json.dumps(body), encoding="utf-8")
    return {**head, **body, "cache": {"hit": False, "key": key[:16]}}
