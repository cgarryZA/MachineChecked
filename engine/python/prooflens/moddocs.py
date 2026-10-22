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


def stale_doc_names(records: list[dict]) -> list[dict]:
    """The names in module docstrings that look like declarations of the project and are not
    (`moddoc` records, which hold every backticked name the environment does not know): a
    dotted name whose first part is capitalised (`Widget.foo_le_bar`), or the name a list item
    under a "Main …" heading begins with. Short and symbol-like names (`L`, `W₂`) are left
    alone, as notation more often than a declaration. A short name that reaches only a module
    or a namespace (`kind`) is listed when it is capitalised or dotted, as the name of a
    declaration that is gone. Each once, by file and line."""
    out, seen = [], set()
    for r in records:
        n = r["name"]
        kind = r.get("kind", "none")
        dotted = "." in n and n[:1].isupper()
        listed = r.get("item_lead") and r.get("heading", "").lower().startswith("main")
        other = kind in ("module", "namespace") and ("." in n or n[:1].isupper())
        if not (dotted or other or listed and len(n) >= 3 and n.isascii()):
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
