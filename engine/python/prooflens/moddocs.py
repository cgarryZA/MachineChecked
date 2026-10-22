"""Names in module docstrings that nothing declares (#107).

The probe reports every backticked name in a module docstring (`/-! … -/`) of the project that
resolves to no declaration of the project or its dependencies (`moddoc` records). It resolves a
name as Lean resolves an identifier, inside the namespaces the module's file enters or declares
into and with every namespace the file opens (#198). A module or namespace written in full is
accepted; a shorter name that reaches only a module or a namespace through the file's namespaces
is reported as what it reaches (#202). Most names that resolve to nothing are notation or
variables; the ones listed here have the shape of a declaration of the project. Both modes
report them: the zero-configuration view as warnings of `check` and a note in the reader, the
full assessment as findings of the `warning` tier, which never change a status and can be
dismissed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def library_dirs(lean_root: Path) -> list[Path]:
    """The folders that may hold a library's sources: the project and each package of its Lake
    manifest (a path dependency where it points, any other in `.lake/packages`)."""
    dirs = [lean_root]
    try:
        packages = json.loads((lean_root / "lake-manifest.json").read_text()).get("packages", [])
    except (OSError, ValueError):
        packages = []
    for p in packages:
        d = lean_root / p["dir"] if p.get("type") == "path" and p.get("dir") else \
            lean_root / ".lake" / "packages" / str(p.get("name", ""))
        if d not in dirs:
            dirs.append(d)
    return dirs


class LibrarySources:
    """The modules and declarations of a library as its source files show them, for every
    module of the library, imported by the project or not (#213)."""

    def __init__(self, lean_root: Path | None):
        self.lean_root = lean_root
        self._libs: dict[str, tuple[set[str], set[str]]] = {}

    def library(self, root: str) -> tuple[set[str], set[str]]:
        if root not in self._libs:
            from .simple import declared_names
            mods, names = set(), set()
            for d in library_dirs(self.lean_root) if self.lean_root else []:
                files = ([d / f"{root}.lean"] if (d / f"{root}.lean").is_file() else []) + \
                    (sorted((d / root).rglob("*.lean")) if (d / root).is_dir() else [])
                for f in files:
                    if ".lake" in f.relative_to(d).parts:
                        continue
                    mods.add(".".join(f.relative_to(d).with_suffix("").parts))
                    try:
                        names |= declared_names(f.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        continue
                if files:
                    break
            self._libs[root] = (mods, names)
        return self._libs[root]

    def declares(self, r: dict) -> bool:
        """Whether the library of the record's module has a module of that full name, or a
        source that declares the name inside one of the record's scopes."""
        mods, names = self.library(r["module"].split(".")[0])
        n = r["name"]
        return n in mods or any(c in names for c in
                                [n] + [f"{ns}.{n}" for ns in r.get("scopes", ())])


def stale_doc_names(records: list[dict], lean_root: Path | None = None) -> list[dict]:
    """The names in module docstrings that look like declarations of the project and are not
    (`moddoc` records, which hold every backticked name the environment does not know): a
    dotted name whose first part is capitalised (`Widget.foo_le_bar`), or the name a list item
    under a "Main …" heading begins with. Short and symbol-like names (`L`, `W₂`) are left
    alone, as notation more often than a declaration. A short name that reaches only a module
    or a namespace (`kind`) is listed when it is capitalised or dotted, as the name of a
    declaration that is gone. A name the environment does not hold but a module of the same
    library declares, or a module of that library named in full, is left out (`lean_root`
    locates the sources): the project need not import every module of a library its
    docstrings mention. Each once, by file and line."""
    out, seen = [], set()
    library = LibrarySources(lean_root)
    for r in records:
        n = r["name"]
        kind = r.get("kind", "none")
        dotted = "." in n and n[:1].isupper()
        listed = r.get("item_lead") and r.get("heading", "").lower().startswith("main")
        other = kind in ("module", "namespace") and ("." in n or n[:1].isupper())
        if not (dotted or other or listed and len(n) >= 3 and n.isascii()):
            continue
        if kind == "none" and lean_root is not None and library.declares(r):
            continue
        file = r["module"].replace(".", "/") + ".lean"
        if (file, r["line"], n) not in seen:
            seen.add((file, r["line"], n))
            out.append({"module": r["module"], "file": file, "line": r["line"], "name": n,
                        "heading": r.get("heading", ""), "kind": kind,
                        "full": r.get("full") or n})
    return sorted(out, key=lambda d: (d["file"], d["line"], d["name"]))


def stale_doc_message(d: dict) -> str:
    where = f"{d['file']}:{d['line']}: module docstring names {d['name']}"
    kind = d.get("kind", "none")
    if kind in ("module", "namespace"):
        return f"{where}, which is the {kind} {d.get('full') or d['name']}, not a declaration"
    return f"{where}, which is not declared"


def stale_doc_fingerprint(d: dict) -> str:
    """What a dismissal of the name is tied to: the module, the heading it is under and the
    name, so that moving it under another heading or into another module reopens it."""
    key = "\n".join((d["module"], d.get("heading", ""), d["name"]))
    return "pl-moddoc-v1:" + hashlib.sha256(key.encode()).hexdigest()
