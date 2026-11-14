"""Rows of a readings ledger that need a fresh reading (#686).

An auditor may keep, beside the inventory, a ledger of readings: notes such as "path continuity
of `Toy.proc` is not proved" or "the paper's limit is the Lean's `Toy.lim` read on the grid". A
note goes out of date when the declarations it is about change, or when a declaration it says
is missing is added. The configuration names the ledger (`readings_ledger` under `[project]`),
a JSON file whose rows are

    {"id": "R1", "text": "...", "declarations": ["Toy.proc"], "namespaces": ["Toy"],
     "read_at": "<git revision>"}

`declarations` are the Lean names the row is about, `namespaces` (optional) further namespaces
whose new declarations concern it (each named declaration's own namespace is one), and
`read_at` the revision of the Lean project at which the row was last read. The file is either
a list of rows or an object with a `rows` list.

`stale_rows` compares each row with the working tree of the Lean project, through Git: a named
declaration whose lines differ from those at `read_at`, a declaration of one of the row's
namespaces that is not declared in its file at `read_at`, and a name no built module declares,
each make the row stale. A stale row is a warning that asks for a fresh reading, with the new
declarations' statements as Lean has them. It never accepts, rewrites or dismisses a row, and
it changes no status: the auditor reads the row again and records the new revision in
`read_at`. Declarations are those of the content index (every declaration of the built
modules, with its module, first line and statement), so a declaration of a dependency is not
in it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .review_sources import _git

DECL_WORDS = ("theorem", "lemma", "def", "abbrev", "instance", "structure", "inductive",
              "class", "axiom", "opaque", "noncomputable def")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


def load(path: Path) -> tuple[list[dict], str | None]:
    """The ledger's rows, and why it could not be read (None when it could)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "the file does not exist"
    except (OSError, ValueError) as e:
        return [], f"it is not readable JSON ({e})"
    rows = doc.get("rows") if isinstance(doc, dict) else doc
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return [], "it is neither a list of rows nor an object with a `rows` list"
    return rows, None


def _namespace(name: str) -> str | None:
    head, _, _ = name.rpartition(".")
    return head or None


def _ranges(docs: list[dict]) -> dict[str, tuple[str, int, int | None]]:
    """Each declaration's module and lines: from its first line to the line before the next
    declaration of its module (to the end of the file, None, for the last)."""
    by_mod: dict[str, list[dict]] = {}
    for d in docs:
        if d.get("module") and isinstance(d.get("line"), int):
            by_mod.setdefault(d["module"], []).append(d)
    out = {}
    for mod, ds in by_mod.items():
        ds.sort(key=lambda d: d["line"])
        for k, d in enumerate(ds):
            nxt = next((e["line"] for e in ds[k + 1:] if e["line"] > d["line"]), None)
            out[d["name"]] = (mod, d["line"], nxt - 1 if nxt else None)
    return out


class Changes:
    """The lines of the Lean project's files that differ from a revision, read once per file."""

    def __init__(self, lean_root: Path, rev: str):
        self.root, self.rev = lean_root, rev
        self.files: dict[str, tuple[list[tuple[int, int]], str | None]] = {}

    def _file(self, rel: str) -> tuple[list[tuple[int, int]], str | None]:
        """The changed spans of `rel` (first line, last line, in the working tree; a deletion
        is the span of the line before it), and its text at the revision (None if absent)."""
        if rel not in self.files:
            old = _git(self.root, "show", f"{self.rev}:./{rel}")
            if old is None:
                self.files[rel] = ([(1, 10 ** 9)], None)
            else:
                diff = _git(self.root, "diff", "-U0", "--no-color", "--no-ext-diff",
                            self.rev, "--", rel) or ""
                spans = []
                for m in HUNK.finditer(diff):
                    start, n = int(m.group(1)), int(m.group(2) or 1)
                    spans.append((start, start + n - 1) if n else (start, start))
                self.files[rel] = (spans, old)
        return self.files[rel]

    def changed(self, rel: str, first: int, last: int | None) -> bool:
        spans, _ = self._file(rel)
        end = last if last is not None else 10 ** 9
        return any(a <= end and b >= first for a, b in spans)

    def declared_then(self, rel: str, name: str) -> bool:
        """Whether the file at the revision declares a declaration of this last name."""
        _, old = self._file(rel)
        if old is None:
            return False
        short = re.escape(name.rpartition(".")[2])
        words = "|".join(re.escape(w) for w in DECL_WORDS)
        return re.search(rf"\b(?:{words})\s+(?:[\w.']+\.)?{short}(?![\w'.])", old) is not None


def stale_rows(cfg, content: dict | None) -> list[dict]:
    """The ledger's rows that need a fresh reading, and the problems that keep a row or the
    ledger from being checked, as `check` warnings (`kind` `readings-ledger`). Empty when the
    configuration names no ledger."""
    path = getattr(cfg, "readings_ledger", None)
    if path is None:
        return []
    from .layout import module_file
    from .util import git_head
    shown = _shown(path, cfg.root)

    def problem(msg, **extra):
        return {"kind": "readings-ledger", "file": shown, **extra,
                "message": f"readings ledger {shown}{_row(extra)}: {msg}"}

    rows, why = load(path)
    if why:
        return [problem(f"not checked: {why}")]
    docs = ((content or {}).get("retrieval") or {}).get("docs")
    if docs is None:
        return [problem("not checked: the build has no index of the project's declarations "
                        "(the Lean project is not built, or no module could be loaded)")]
    if git_head(cfg.lean_root) is None:
        return [problem("not checked: the Lean project is not in a Git repository, so the "
                        "revisions rows were read at cannot be compared with it")]
    by_name = {d["name"]: d for d in docs}
    lines = _ranges(docs)
    out = []
    for k, r in enumerate(rows):
        rid = str(r.get("id") or f"#{k + 1}")
        names = [n for n in r.get("declarations") or [] if isinstance(n, str)]
        spaces = [n for n in r.get("namespaces") or [] if isinstance(n, str)]
        if not names and not spaces:
            continue
        rev = r.get("read_at")
        if not isinstance(rev, str) or not rev.strip():
            out.append(problem("records no revision it was read at (`read_at`), so whether its "
                               "declarations changed cannot be told; record the revision of "
                               "the reading", row=rid))
            continue
        commit = _git(cfg.lean_root, "rev-parse", "--verify", "--quiet", f"{rev.strip()}^{{commit}}")
        if commit is None:
            out.append(problem(f"was read at {rev}, which is not a revision of the Lean "
                               "project's repository; read the row again and record the "
                               "revision", row=rid, read_at=rev))
            continue
        ch = Changes(cfg.lean_root, commit.strip())
        missing = [n for n in names if n not in by_name]
        changed = []
        for n in names:
            if n in lines:
                mod, first, last = lines[n]
                rel = module_file(cfg.lean_root, mod)
                if ch.changed(rel, first, last):
                    changed.append(_entry(by_name[n], rel))
        ns = list(dict.fromkeys(spaces + [s for s in map(_namespace, names) if s]))
        added = []
        for d in docs:
            if d["name"] in names or _namespace(d["name"]) not in ns or d["name"] not in lines:
                continue
            mod, first, last = lines[d["name"]]
            rel = module_file(cfg.lean_root, mod)
            if ch.changed(rel, first, last) and not ch.declared_then(rel, d["name"]):
                added.append(_entry(d, rel))
        if not (missing or changed or added):
            continue
        parts = []
        if missing:
            parts.append("no built module declares " + ", ".join(missing))
        if changed:
            parts.append("changed since then: " + ", ".join(e["name"] for e in changed))
        if added:
            parts.append("new in " + ", ".join(ns) + ": "
                         + "; ".join(f"{e['name']} : {e['statement']}" for e in added))
        out.append(problem(f"was read at {rev}; " + "; ".join(parts) + ". Read the row again "
                           "and record the revision of the new reading; this changes no status",
                           row=rid, read_at=rev, missing=missing, changed=changed, new=added))
    return out


def _entry(d: dict, rel: str) -> dict:
    return {"name": d["name"], "kind": d.get("kind"), "statement": d.get("type"),
            "file": rel, "line": d.get("line")}


def _row(extra: dict) -> str:
    return f" row {extra['row']}" if "row" in extra else ""


def _shown(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
