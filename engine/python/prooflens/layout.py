"""Where a Lake package keeps the sources of its modules (#535).

A module `A.B.C` of a library is the file `A/B/C.lean` under the library's source directory:
the package's `srcDir` joined with the library's own, both `.` by default, as the lakefile
(`lakefile.toml` or `lakefile.lean`) sets them. Every place that reads a module's source maps
the module to its file here, and a file back to its module. A `srcDir` that the lakefile
computes other than by string literals joined with `/` is not read: its modules are looked
for at the default place, where they are not found.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath

# Lake reads `lakefile.lean` when both are present.
LAKEFILES = ("lakefile.lean", "lakefile.toml")

# A top-level command of a `lakefile.lean` that configures the package or a library.
TARGET = re.compile(r"(?:@\[[^\]]*\]\s*)*(package|lean_lib)\s+«?([^\s«»{]+?)»?(?=\s|\{|$)")
SRC_DIR = re.compile(r'\bsrcDir\s*:=\s*((?:"[^"\\]*"\s*/\s*)*"[^"\\]*")')
ROOTS = re.compile(r"\broots\s*:=\s*#\[([^\]]*)\]")

_cache: dict[tuple, list[tuple[frozenset[str], str]]] = {}


def _join(*parts: str) -> str:
    p = PurePosixPath(*(x.strip() or "." for x in parts))
    s = str(p)
    return "." if s in ("", ".") else s


def _lean_dirs(text: str) -> tuple[str, list[tuple[str, str | None, list[str]]]]:
    """The package's `srcDir` and each library's name, `srcDir` and `roots` in a
    `lakefile.lean`, read from string literals."""
    text = re.sub(r"/-.*?-/", "", text, flags=re.S)
    text = re.sub(r"--[^\n]*", "", text)
    pkg, libs = ".", []
    # Each top-level command starts at the beginning of a line.
    for block in re.split(r"(?m)^(?=\S)", text):
        m = TARGET.match(block)
        if not m:
            continue
        sd = SRC_DIR.search(block)
        d = _join(*re.findall(r'"([^"\\]*)"', sd.group(1))) if sd else None
        if m.group(1) == "package":
            pkg = d or "."
        else:
            r = ROOTS.search(block)
            roots = re.findall(r"`+«?([\w.']+)»?", r.group(1)) if r else []
            libs.append((m.group(2), d, roots))
    return pkg, libs


def _toml_dirs(text: str) -> tuple[str, list[tuple[str, str | None, list[str]]]]:
    cfg = tomllib.loads(text)
    pkg = str(cfg.get("srcDir") or ".")
    libs = []
    for lib in cfg.get("lean_lib", []):
        if isinstance(lib, dict) and lib.get("name"):
            roots = lib.get("roots")
            libs.append((str(lib["name"]), str(lib["srcDir"]) if lib.get("srcDir") else None,
                         [str(r) for r in roots] if isinstance(roots, list) else []))
    return pkg, libs


def source_dirs(root: Path) -> list[tuple[frozenset[str], str]]:
    """The source directory of each `lean_lib` of the package at `root`, with the top-level
    module names it holds (its `roots`, by default its name's first component), in the order
    the lakefile gives them; the directory is relative to `root` in POSIX form (`.` for `root`
    itself). The package's own `srcDir` comes last, for modules no library names. Empty when
    there is no lakefile it can read."""
    files = [root / f for f in LAKEFILES]
    try:
        key = (str(root.resolve()),
               *((f.stat().st_mtime_ns, f.stat().st_size) if f.is_file() else None
                 for f in files))
    except OSError:
        return []
    if key in _cache:
        return _cache[key]
    pkg, libs = ".", []
    for f in files:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
            p, ls = (_toml_dirs if f.suffix == ".toml" else _lean_dirs)(text)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            continue
        pkg, libs = p, libs + ls
        break
    out = [(frozenset(r.split(".")[0] for r in (roots or [name])), _join(pkg, d or "."))
           for name, d, roots in libs]
    out.append((frozenset(), _join(pkg)))
    _cache[key] = out
    return out


def library_dir(root: Path | None, top: str) -> str:
    """The source directory (relative to `root`) of the library that holds the top-level
    module name `top`: `.` when no library of the lakefile names it."""
    if root is None:
        return "."
    dirs = source_dirs(root)
    return next((d for roots, d in dirs if top in roots), dirs[-1][1] if dirs else ".")


def module_file(root: Path | None, module: str) -> str:
    """The file of `module`, relative to `root` in POSIX form: `A/B/C.lean` under the source
    directory of its library (the one whose roots hold its first component), else under another
    source directory of the package that holds that file, else at the default place
    `A/B/C.lean`. When no such file exists, the place in its library's source directory."""
    rel = module.replace(".", "/") + ".lean"
    if root is None:
        return rel
    dirs = source_dirs(root)
    own = library_dir(root, module.split(".")[0])
    seen = []
    for d in [own, *(d for _, d in dirs), "."]:
        if d in seen:
            continue
        seen.append(d)
        p = rel if d == "." else f"{d}/{rel}"
        if (root / p).is_file():
            return p
    return rel if own == "." else f"{own}/{rel}"


def module_of(root: Path, rel: str | PurePosixPath, dirs=None) -> str:
    """The module a `.lean` file is, from its path relative to `root`: relative to the deepest
    source directory of the package that holds it, else to `root`. `dirs` are the package's
    `source_dirs`, when the caller has read them."""
    parts = PurePosixPath(rel).with_suffix("").parts
    best: tuple[str, ...] = ()
    for _, d in source_dirs(root) if dirs is None else dirs:
        dp = () if d == "." else PurePosixPath(d).parts
        if len(dp) > len(best) and parts[:len(dp)] == dp and len(parts) > len(dp):
            best = dp
    return ".".join(parts[len(best):])


def library_files(root: Path, lib: str) -> list[tuple[Path, Path]]:
    """The source files of the library whose root module is `lib`'s first component: the root
    module's file and every file under its folder, in its library's source directory, each
    with its path relative to that directory (`A/B/C.lean` for the module `A.B.C`)."""
    base = lib.split(".")[0]
    d = library_dir(root, base)
    src = root if d == "." else root / d
    files = [src / f"{base}.lean"]
    if (src / base).is_dir():
        files += sorted((src / base).rglob("*.lean"))
    return [(f, f.relative_to(src)) for f in files if f.exists()]
