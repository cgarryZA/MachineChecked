"""Declarations read from the Lean sources of the project and its Lake packages (#213).

The probe resolves names against the environment it loads: the import closure of the audited
modules. A module docstring or a review can name a declaration of a module that closure leaves
out (another module of the same library, or of a dependency). Before such a name is reported as
undeclared, it is looked up here, in the source files: the declarations they make (with the
namespaces they are made in), the namespaces those form, and the modules the files are.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

SKIP = {".git", ".machinechecked", ".prooflens", "build", "node_modules", "__pycache__"}

DECL = re.compile(
    r"(?:@\[[^\]]*\]\s*)*"
    r"(?:(?:private|protected|noncomputable|partial|unsafe|nonrec|scoped|public)\s+)*"
    r"(?:theorem|lemma|def|abbrev|instance|structure|class(?:\s+inductive)?|inductive|opaque"
    r"|axiom|irreducible_def)\s+"
    r"(?:\([^)]*\)\s+)?"  # an instance's priority
    r"([^\s:({\[⦃]+)")


def strip_comments(text: str) -> str:
    """`text` with its comments (`--`, and nested `/- … -/`, docstrings included) blanked, its
    newlines kept."""
    out, depth, i, n = [], 0, 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if depth:
            if two == "/-":
                depth, i = depth + 1, i + 2
            elif two == "-/":
                depth, i = depth - 1, i + 2
            else:
                out.append("\n" if text[i] == "\n" else "")
                i += 1
        elif two == "/-":
            depth, i = 1, i + 2
        elif two == "--":
            j = text.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def declarations(text: str) -> tuple[set[str], set[str]]:
    """The full names a Lean file declares, and the namespaces it enters, tracking `namespace`,
    `section`, `mutual` and `end`."""
    names: set[str] = set()
    entered: set[str] = set()
    stack: list[list[str]] = []
    for line in strip_comments(text).splitlines():
        s = line.strip()
        words = s.split()
        if not words:
            continue
        if words[0] == "namespace" and len(words) > 1:
            for part in words[1].split("."):
                stack.append([part])
                entered.add(".".join(p for e in stack for p in e))
            continue
        if words[0] in ("section", "mutual") or words[:2] == ["noncomputable", "section"]:
            stack.append([])
            continue
        if words[0] == "end":
            k = len(words[1].split(".")) if len(words) > 1 else 1
            del stack[len(stack) - min(k, len(stack)):]
            continue
        m = DECL.match(s)
        if not m:
            continue
        name = m.group(1)
        if name.startswith("_root_."):
            names.add(name[len("_root_."):])
        else:
            ns = ".".join(p for e in stack for p in e)
            names.add(f"{ns}.{name}" if ns else name)
    return names, entered


def lean_files(roots: list[Path]):
    """Every `.lean` file under `roots` (the project, and the Lake packages it depends on),
    without version control and build output, with the module it is: its path relative to the
    root or to its package's folder (`.lake/packages/<package>`)."""
    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP]
            for f in files:
                if f.endswith(".lean"):
                    path = Path(dirpath) / f
                    parts = path.relative_to(root).with_suffix("").parts
                    if parts[:2] == (".lake", "packages"):
                        parts = parts[3:]
                    yield path, ".".join(parts)


class SourceNames:
    """The declarations, namespaces and modules of the Lean sources under `roots`, read from the
    files that mention one of `lasts` (the last components of the names to look up)."""

    def __init__(self, roots: list[Path], lasts: set[str]):
        self.names: set[str] = set()
        self.modules: set[str] = set()
        for path, module in lean_files(roots):
            self.modules.add(module)
            if not lasts:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(t in text for t in lasts):
                self.names |= declarations(text)[0]
        self.spaces = {n.rsplit(".", 1)[0] for n in self.names if "." in n}
        self.spaces |= {s for n in set(self.spaces) for s in prefixes(n)}

    def known(self, name: str) -> bool:
        """Whether a declaration, a namespace or a module has the full name `name`."""
        return name in self.names or name in self.spaces or name in self.modules

    def known_suffix(self, name: str) -> bool:
        """Whether `name` is a declaration, namespace or module, or the last components of a
        declaration's name."""
        return self.known(name) or any(n.endswith("." + name) for n in self.names)


def undeclared_doc_names(docs: list[dict], lean_root: Path) -> list[dict]:
    """Of the names module docstrings list that the probe found undeclared
    (`moddocs.stale_doc_names`), those of the project's own modules that its sources and its
    packages' do not declare either. A module whose file is not in the project is a
    dependency's, whose own audit checks its docstrings. A name is tried as written and inside
    each namespace the docstring's file enters, as the probe tries it in the namespaces the
    module declares into."""
    own = [d for d in docs if (lean_root / d["file"]).is_file()]
    if not own:
        return []
    src = SourceNames([lean_root], {last(d["name"]) for d in own})
    entered: dict[str, set[str]] = {}
    out = []
    for d in own:
        if d["file"] not in entered:
            text = (lean_root / d["file"]).read_text(encoding="utf-8", errors="replace")
            entered[d["file"]] = declarations(text)[1]
        if not any(src.known(f"{ns}.{d['name']}" if ns else d["name"])
                   for ns in {""} | entered[d["file"]]):
            out.append(d)
    return out


def prefixes(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def last(name: str) -> str:
    return name.rsplit(".", 1)[-1]
