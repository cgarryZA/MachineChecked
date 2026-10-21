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

    def digests(self) -> dict[str, str]:
        """A digest per declaration of its fingerprint and those of the constants Lean generated
        for it (`N._f`, `N.match_1`, `N.eq_1`, …), which hold what a definition by recursion or
        by cases says: a change to its equations changes the digest even when the
        declaration's own fingerprint does not."""
        if self._digests is not None:
            return self._digests
        own = {**self.store_fingerprints(), **self.fingerprints()}
        names = sorted(own)
        out = {}
        for n in names:
            parts = [own[m] for m in names if m.startswith(n + ".") and _generated(m[len(n) + 1:])]
            out[n] = own[n] if not parts else "ws-digest:" + hashlib.sha256(
                "\n".join([own[n], *parts]).encode()).hexdigest()
        self._digests = out
        return out

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
    build). A name the project does not declare is refused, with the nearest names."""
    from .probe import lib_names
    from .simple import built_modules, declaring_modules
    name = str(name or "").strip()
    if not re.fullmatch(r"[^\s]+", name):
        raise TargetError(f"{name!r} is not a declaration name")
    index = snap.lean_index() or []
    mods = sorted({d.get("module") for d in index if d.get("name") == name})
    if module:
        if module in mods:
            return {"name": name, "module": module, "build": "built"}
        mods = []
    if len(mods) > 1:
        raise TargetError(f"{name} is declared in several modules: {', '.join(mods)}; the links "
                          "file cannot yet record which one is meant", [{"name": name, "module": m}
                                                                         for m in mods],
                          kind="ambiguous")
    if mods:
        return {"name": name, "module": mods[0], "build": "built"}
    if not index:
        # A full assessment keeps no Lean index: the declarations its probe recorded (the
        # shared store) are the build's own.
        stored = sorted({r.get("module") for r in snap.store_records(name) if r.get("module")})
        if module in stored or (len(stored) == 1 and not module):
            return {"name": name, "module": module or stored[0], "build": "built"}
    if root is not None:
        libs = lib_names(root)
        built, unbuilt = built_modules(root, libs) if libs else ([], [])
        # The working directory holds the site (`site/data`) and the facts store beside it.
        from .facts import load_failures
        failed = load_failures(snap.data.parent.parent / "build")
        for m in declaring_modules(root, [module] if module in unbuilt else unbuilt, name):
            return {"name": name, "module": m, "build": "unbuilt"}
        for m in declaring_modules(root, list(failed), name):
            return {"name": name, "module": m, "build": "not loaded"}
        if not index and built and not module:
            # No index of a built project: this build did not run Lean.
            raise TargetError(f"{name}: this build has no Lean index; run `machinechecked view` "
                              "after `lake build`", kind="no-build")
    if external:
        return {"name": name, "module": module, "build": "external"}
    names = [d["name"] for d in index if d.get("name")]
    near = [n for n in names if n.endswith("." + name)][:5] or \
        difflib.get_close_matches(name, names, n=5, cutoff=0.6)
    raise TargetError(f"{name} is not a declaration of the project (pass --external for one "
                      "from a dependency)", [{"name": n} for n in near])
