"""What a saved record refers to, resolved against the selected build: a claim of the paper and
a Lean declaration of the project.

The build's site data (`<work dir>/site/data/`, written by `view`, `build` and the full
assessment) is the snapshot: it lists the claims with their identifiers, numbers and printed-text
hashes, and the fingerprints of the declarations it shows. Resolving reads only that data and
the project's sources; it never runs Lean, so recording a link or a finding starts no probe.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path


class TargetError(RuntimeError):
    """A claim or a declaration that does not resolve to exactly one; `candidates` lists what
    it might have meant."""

    def __init__(self, message: str, candidates: list | None = None, kind: str = "unknown"):
        super().__init__(message)
        self.candidates = candidates or []
        self.kind = kind

    def to_json(self) -> dict:
        return {"kind": self.kind, "message": str(self), "candidates": self.candidates}


def _generated(rest: str) -> bool:
    """Whether the name below a declaration is one Lean generates for it."""
    return any(re.fullmatch(r"_.*|match_\d+|proof_\d+|eq_\d+|eq_def|eq_unfold", c)
               for c in rest.split("."))


def script_owners(records) -> dict[str, str]:
    """The declaration each tactic-default script among the declaration records `records`
    belongs to. A binder or a structure field with a tactic default (`(h : 0 < n := by omega)`)
    makes Lean store the tactic as a declaration of its own, which the probe marks `auto_param`,
    and the type of the declaration that has the default names it (`autoParam (0 < n) …`): a
    definition's or a theorem's, or a structure's constructor's. Its name does not always say
    whose it is: a binder's script is `f._auto_1` on Lean 4.32 and `_auto._@.M._hyg.N` on Lean
    4.24. So the owner is the declaration whose printed type refers to the script (the first by
    name, of several). A script no printed type refers to has no owner here."""
    scripts, typed = set(), []
    for r in records:
        n = r.get("name")
        if not n:
            continue
        if r.get("auto_param") is True:
            scripts.add(n)
            continue
        sig = r.get("signature")
        refs = {s["ref"] for s in (sig.get("segments") if isinstance(sig, dict) else None) or []
                if isinstance(s, dict) and isinstance(s.get("ref"), str)}
        if refs:
            typed.append((n, refs))
    out: dict[str, str] = {}
    for n, refs in sorted(typed, key=lambda x: x[0]):
        for s in refs & scripts:
            out.setdefault(s, n)
    return out


def _expansion_refs(obj) -> list[dict]:
    """The expansions a printed statement or definition refers to (`{at, name, key}`, as the
    site data stores them, `manifest.split_expansions`), each once, in the order found."""
    out, seen, stack = [], set(), [obj]
    while stack:
        o = stack.pop(0)
        if isinstance(o, list):
            stack[:0] = o
        elif isinstance(o, dict):
            refs = o.get("expansions")
            for x in refs if isinstance(refs, list) else []:
                if isinstance(x, dict) and x.get("key"):
                    ref = {k: x.get(k) for k in ("at", "name", "key")}
                    k = (ref["at"], ref["name"], ref["key"])
                    if k not in seen:
                        seen.add(k)
                        out.append(ref)
            stack[:0] = [v for k, v in o.items() if k != "expansions"]
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


class Snapshot:
    """The claims and declaration fingerprints of one build's site data."""

    def __init__(self, data_dir: Path):
        self.data = Path(data_dir)
        p = self.data / "index.json"
        if not p.exists():
            raise TargetError("no build to resolve against: run `machinechecked view` or "
                              "`machinechecked build` first", kind="no-build")
        self.index = json.loads(p.read_text(encoding="utf-8"))
        self.claims = list(self.index.get("claims") or [])
        self._by_id = {c["id"]: c for c in self.claims}
        self._chunks: dict[str, dict | None] = {}
        self._fps: dict[str, str] | None = None
        self._digests: dict[str, str] | None = None
        self._scripts: dict[str, str] | None = None
        self._statements: dict[str, dict] | None = None
        self._store: dict[str, dict] | None = None

    # -- identity --------------------------------------------------------------------------

    def sources(self) -> dict:
        """The source versions this snapshot is: the release, the project's commit and
        repository, and each paper's revision and PDF checksum."""
        proj = self.index.get("project") or {}
        return {"release": self.index.get("release"),
                "project": {k: proj.get(k) for k in ("name", "commit", "repository")
                            if proj.get(k) is not None},
                "papers": [{k: p.get(k) for k in ("id", "title", "revision", "pdf_sha256")
                            if p.get(k) is not None}
                           for p in self.index.get("papers") or []]}

    # -- claims ----------------------------------------------------------------------------

    def chunk(self, cid: str) -> dict | None:
        """A claim's full record (its passport)."""
        if cid not in self._chunks:
            meta = self._by_id.get(cid)
            p = meta and self.data / "claims" / meta["file"]
            self._chunks[cid] = (json.loads(p.read_text(encoding="utf-8"))
                                 if p and p.exists() else None)
        return self._chunks[cid]

    def key_of(self, cid: str) -> str:
        """A claim's key within its paper (the links file's key)."""
        ch = self.chunk(cid) or {}
        return ch.get("key") or cid.split(":", 1)[-1]

    def claim_ref(self, cid: str) -> dict:
        c = self._by_id[cid]
        return {"id": cid, "key": self.key_of(cid), "paper": c.get("paper"),
                "number": c.get("number"), "kind": c.get("kind")}

    def resolve_claim(self, query: str) -> str:
        """The id of the one claim `query` names: its id (`P:thm:main`), its key within the
        paper (`thm:main`), its number with its kind (`Theorem 2`, any case), or a bare number
        (`2.3`) that only one claim has. Anything else is refused with the nearest claims."""
        q = str(query or "").strip()
        if not q:
            raise TargetError("no claim given")
        if q in self._by_id:
            return q
        tries = [
            lambda c: self.key_of(c["id"]) == q,
            lambda c: _norm(c["id"]) == _norm(q) or _norm(self.key_of(c["id"])) == _norm(q),
            lambda c: _norm(c.get("number")) == _norm(q)
            or _norm(f"{c.get('paper')}:{c.get('number')}") == _norm(q),
            lambda c: bool(re.fullmatch(r"[\w.]+", q))
            and _norm(c.get("number")).rsplit(" ", 1)[-1] == _norm(q),
        ]
        for match in tries:
            found = [c for c in self.claims if match(c)]
            if len(found) == 1:
                return found[0]["id"]
            if len(found) > 1:
                raise TargetError(f"{q!r} names {len(found)} claims; give one of their ids",
                                  [self.claim_ref(c["id"]) for c in found], kind="ambiguous")
        words = {c["id"]: c for c in self.claims}
        for c in self.claims:
            words.setdefault(self.key_of(c["id"]), c)
            if c.get("number"):
                words.setdefault(c["number"], c)
        near = difflib.get_close_matches(q, list(words), n=5, cutoff=0.4)
        cands = []
        for w in near:
            ref = self.claim_ref(words[w]["id"])
            if ref not in cands:
                cands.append(ref)
        raise TargetError(f"no claim {q!r} in release {self.index.get('release')}", cands)

    # -- declarations ----------------------------------------------------------------------

    def fingerprints(self) -> dict[str, str]:
        """Every declaration fingerprint the snapshot shows, by name: linked and suggested
        declarations, clause statements, and the shared declaration store."""
        if self._fps is not None:
            return self._fps
        out: dict[str, str] = {}
        for c in self.claims:
            ch = self.chunk(c["id"]) or {}
            for l in (ch.get("links") or []) + (ch.get("suggestions") or []):
                if l.get("name") and l.get("fingerprint"):
                    out.setdefault(l["name"], l["fingerprint"])
            for cl in ch.get("clauses") or []:
                st = cl.get("statement") or {}
                if cl.get("spec") and st.get("fingerprint"):
                    out.setdefault(cl["spec"], st["fingerprint"])
            for name, key in (ch.get("decls") or {}).items():
                if name in out:
                    continue
                p = self.data / "decls" / f"{key}.json"
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if rec.get("fingerprint"):
                    out[name] = rec["fingerprint"]
        self._fps = out
        return out

    def store_fingerprints(self) -> dict[str, str]:
        """The fingerprint of every record of the shared declaration store, by name."""
        out = {}
        for p in sorted((self.data / "decls").glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if rec.get("name") and rec.get("fingerprint"):
                out.setdefault(rec["name"], rec["fingerprint"])
        return out

    def store_records(self, name: str) -> list[dict]:
        """The records of the shared declaration store for `name`."""
        out = []
        for p in sorted((self.data / "decls").glob("*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if rec.get("name") == name:
                out.append(rec)
        return out

    def script_owners(self) -> dict[str, str]:
        """The owner of each tactic-default script of the shared declaration store
        (`script_owners`)."""
        if self._scripts is None:
            def records():
                for p in sorted((self.data / "decls").glob("*.json")):
                    try:
                        yield json.loads(p.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
            self._scripts = script_owners(records())
        return self._scripts

    def digests(self) -> dict[str, str]:
        """A digest per declaration of its fingerprint and those of the constants Lean generated
        for it (`N._f`, `N.match_1`, `N.eq_1`, …), which hold what a definition by recursion or
        by cases says: a change to its equations changes the digest even when the
        declaration's own fingerprint does not. The tactic script of a tactic default in its
        type is one of them whatever its name, by the records (`script_owners`)."""
        if self._digests is not None:
            return self._digests
        own = {**self.store_fingerprints(), **self.fingerprints()}
        scripts = self.script_owners()
        names = sorted(own)
        out = {}
        for n in names:
            parts = [own[m] for m in names
                     if (m.startswith(n + ".") and _generated(m[len(n) + 1:]))
                     or scripts.get(m) == n]
            out[n] = own[n] if not parts else "ws-digest:" + hashlib.sha256(
                "\n".join([own[n], *parts]).encode()).hexdigest()
        self._digests = out
        return out

    def statement_records(self) -> dict[str, dict]:
        """The statement record the build shows for each declaration, by name, from the claims'
        links, suggestions, proof steps' links and formal routes, and the clauses' propositions:
        `closure` (the project constants its statement uses, with proofs erased, and for a
        definition those of its value; absent when the record gives none) and `expansions`, the
        applications of definitions it prints as the build expanded them (`{at, name, key}`, the
        key naming the stored expansion, which changes with the definition)."""
        if self._statements is not None:
            return self._statements
        out: dict[str, dict] = {}

        def add(name, st, definition=None):
            if not name or not isinstance(st, dict) or name in out:
                return
            rec = {"expansions": _expansion_refs([st, definition])}
            if isinstance(st.get("closure"), list):
                rec["closure"] = [n for n in st["closure"] if isinstance(n, str)]
            out[name] = rec

        for c in self.claims:
            ch = self.chunk(c["id"]) or {}
            step = ch.get("step") or {}
            for l in ((ch.get("links") or []) + (ch.get("suggestions") or [])
                      + (step.get("links") or []) + ((step.get("route") or {}).get("links")
                                                     or [])):
                if isinstance(l, dict):
                    add(l.get("name"), l.get("statement"), l.get("definition"))
            for cl in ch.get("clauses") or []:
                add(cl.get("spec"), cl.get("statement"))
        self._statements = out
        return out

    def _store_by_name(self) -> dict[str, dict]:
        if self._store is None:
            out: dict[str, dict] = {}
            for p in sorted((self.data / "decls").glob("*.json")):
                try:
                    rec = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if rec.get("name"):
                    out.setdefault(rec["name"], rec)
            self._store = out
        return self._store

    def closure(self, name: str) -> tuple[list[str] | None, bool, str | None]:
        """The project constants the statement of `name` uses (for a definition, its value's
        too), as `(names, complete, source)`: from its statement record (`statement`), else by
        following what each record of the shared declaration store uses (`declarations`), which
        is incomplete when a constant used has no record there; `(None, False, None)` when the
        build shows neither."""
        st = self.statement_records().get(name)
        if st is not None and "closure" in st:
            return sorted(set(st["closure"]) - {name}), True, "statement"
        store = self._store_by_name()
        if "uses" not in store.get(name, {}):
            return None, False, None
        seen, todo, complete = set(), [name], True
        while todo:
            for u in store[todo.pop()].get("uses") or []:
                if u == name or u in seen:
                    continue
                seen.add(u)
                if "uses" in store.get(u, {}):
                    todo.append(u)
                else:
                    complete = False
        return sorted(seen), complete, "declarations"

    def lean_index(self) -> list[dict] | None:
        """The project's declarations as the build indexed them (zero configuration), or None
        when this build has no index."""
        p = self.data / "lean-index.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None


def resolve_declaration(name: str, snap: Snapshot, root: Path | None, module: str | None = None,
                        external: bool = False) -> dict:
    """What `name` is in the selected build: `{name, module, build}`, where `build` is `built`
    (the build indexed it), `unbuilt` (its module's source declares it and the module is not
    built), `not loaded` (its module is built but could not be loaded) or `external` (not a
    project declaration; accepted only with `external`, and checked by Lean at the next
    build). A name the project does not declare is refused, with the nearest names. With
    `module`, only that module is searched (`_in_module`)."""
    from .simple import declaring_modules
    name = str(name or "").strip()
    if not re.fullmatch(r"[^\s]+", name):
        raise TargetError(f"{name!r} is not a declaration name")
    index = snap.lean_index() or []
    mods = sorted({d.get("module") for d in index if d.get("name") == name})
    if module:
        return _in_module(name, module, snap, root, index, mods, external)
    if len(mods) > 1:
        raise TargetError(f"{name} is declared in several modules: {', '.join(mods)}; the links "
                          "file cannot yet record which one is meant", [{"name": name, "module": m}
                                                                         for m in mods],
                          kind="ambiguous")
    if mods:
        return {"name": name, "module": mods[0], "build": "built"}
    if not index:
        stored = _stored_modules(snap, name)
        if len(stored) == 1:
            return {"name": name, "module": stored[0], "build": "built"}
    if root is not None:
        built, unbuilt, failed = _project_modules(snap, root)
        for m in declaring_modules(root, unbuilt, name):
            return {"name": name, "module": m, "build": "unbuilt"}
        for m in declaring_modules(root, list(failed), name):
            return {"name": name, "module": m, "build": "not loaded"}
        if not index and built:
            # No index of a built project: this build did not run Lean.
            raise TargetError(f"{name}: this build has no Lean index; run `machinechecked view` "
                              "after `lake build`", kind="no-build")
    if external:
        return {"name": name, "module": None, "build": "external"}
    raise TargetError(f"{name} is not a declaration of the project (pass --external for one "
                      "from a dependency)", [{"name": n} for n in _near(index, name)])


def _stored_modules(snap: Snapshot, name: str) -> list[str]:
    """The modules of the shared store's records of `name`: a full assessment keeps no Lean
    index, and the declarations its probe recorded are the build's own."""
    return sorted({r.get("module") for r in snap.store_records(name) if r.get("module")})


def _project_modules(snap: Snapshot, root: Path) -> tuple[list[str], list[str], dict]:
    """The project's built and unbuilt modules, and those the last extraction could not load
    (with the reason)."""
    from .facts import load_failures
    from .probe import lib_names
    from .simple import built_modules
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    # The working directory holds the site (`site/data`) and the facts store beside it.
    return built, unbuilt, load_failures(snap.data.parent.parent / "build")


def _near(index: list[dict], name: str) -> list[str]:
    names = [d["name"] for d in index if d.get("name")]
    return [n for n in names if n.endswith("." + name)][:5] or \
        difflib.get_close_matches(name, names, n=5, cutoff=0.6)


def _in_module(name: str, module: str, snap: Snapshot, root: Path | None, index: list[dict],
               indexed: list[str], external: bool) -> dict:
    """`name` in `module` and nowhere else: `built` when the build's index (or, without one,
    the shared store) has it there, `unbuilt` when the module is not built and its source
    declares it, `not loaded` when the module could not be loaded and its source declares it.
    Anything else is refused, naming the modules that do declare it; a name the project declares
    nowhere is `external` only with `external`."""
    from .simple import declaring_modules
    if module in indexed:
        return {"name": name, "module": module, "build": "built"}
    stored = [] if index else _stored_modules(snap, name)
    if module in stored:
        return {"name": name, "module": module, "build": "built"}
    elsewhere, cannot_tell = set(indexed) | set(stored), False
    if root is not None:
        built, unbuilt, failed = _project_modules(snap, root)
        if module in unbuilt and declaring_modules(root, [module], name):
            return {"name": name, "module": module, "build": "unbuilt"}
        if module in failed and declaring_modules(root, [module], name):
            return {"name": name, "module": module, "build": "not loaded"}
        elsewhere |= set(declaring_modules(root, unbuilt, name))
        elsewhere |= set(declaring_modules(root, list(failed), name))
        cannot_tell = not index and bool(built)
    elsewhere.discard(module)
    if elsewhere:
        where = sorted(elsewhere)
        raise TargetError(f"{name} is not declared in {module}; it is declared in "
                          f"{', '.join(where)}", [{"name": name, "module": m} for m in where])
    if external:
        return {"name": name, "module": module, "build": "external"}
    if cannot_tell:
        raise TargetError(f"{name}: this build has no Lean index to find it in {module}; run "
                          "`machinechecked view` after `lake build`", kind="no-build")
    raise TargetError(f"{name} is not declared in {module}, nor elsewhere in the project (pass "
                      "--external for one from a dependency)",
                      [{"name": n} for n in _near(index, name)])
