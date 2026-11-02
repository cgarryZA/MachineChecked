"""The project configuration, `prooflens.toml`."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

STANDARD_AXIOMS = ["propext", "Classical.choice", "Quot.sound"]


class ConfigError(ValueError):
    pass


@dataclass
class Publish:
    """What of a paper may appear in a public export. Everything defaults to private."""

    pdf: bool = False
    source_text: bool = False
    lean: bool = False
    reviews: bool = False


@dataclass
class Paper:
    id: str
    title: str
    source: dict
    root: str | None = None
    pdf: str | None = None
    commit: str | None = None
    envs: list[str] | None = None
    publish: Publish = field(default_factory=Publish)
    # The public record the audited revision corresponds to (an arXiv identifier with version,
    # a DOI or a URL), and how the revision differs from it. Descriptive only: no status uses it.
    published: str | None = None
    published_note: str | None = None
    # The version of the paper this audit pins: "published" (the version `published` names) or
    # "manuscript" (the unpublished source at its pinned revision, `source.rev`). When absent, a
    # paper with `published` (or an arXiv source) pins that published version (docs/ASSURANCE.md).
    version: str | None = None
    # Notation macros: those of the project and the paper's own, as control sequences. A passage
    # that uses one is read with its definition's digest (docs/SOURCE_REGIONS.md).
    notation_macros: list[str] = field(default_factory=list)
    # A paper whose source is a PDF: the PDF's SHA-256, pinned by the configuration. The release
    # gate accepts a PDF as source evidence only when it is pinned and matches (EVIDENCE_POLICY).
    pdf_sha256: str | None = None


@dataclass
class Config:
    path: Path
    name: str
    lean_root: Path
    modules: list[str]
    scope_roots: list[str]
    spec_prefix: str
    accept_prefix: str
    allowed_axioms: list[str]
    inventory: Path
    reviews: list[Path]
    statement_authors: list[str]
    ai_reviewers: list[str]
    dismissals: Path | None
    comparator_log: Path | None
    papers: list[Paper]
    out_dir: Path
    review_check: str | None = None
    # Every prefix of the statement layer and of the proof layer: `spec_prefix` and
    # `accept_prefix` may each be a list, of which the first is `spec_prefix`, `accept_prefix`.
    spec_prefixes: list[str] = field(default_factory=list)
    accept_prefixes: list[str] = field(default_factory=list)
    display: Path | None = None
    symbols: Path | None = None
    issues: str | None = None         # "owner/repo" where the reader's "Report issue" opens issues
    site_url: str | None = None       # the public address of the published site, for permalinks
    author: str | None = None         # the name the audit is published under (audit.json)
    repository: str | None = None     # "owner/repo" of the Lean source, if not the git remote
    repository_private: bool = False  # the reader does not show the repository's name
    # Citations in review text (`review_citations.py`): patterns of backticked tokens that are
    # notation, not names (None: the default), and whether an unresolved one is a violation.
    review_citations_ignore: list[str] | None = None
    review_citations_strict: bool = False
    # Reviewers whose review markers count without review text before them (`assess.py`).
    bare_markers_by: list[str] = field(default_factory=list)
    # Type classes treated as inhabited by the witness check (`assess.INHABITED_CLASSES` when
    # not configured).
    inhabited_classes: list[str] | None = None
    # Whether the declarations only witnesses use need a review like the definitions of the
    # propositions (`assess.witness_defs`); otherwise they are listed as advice.
    require_witness_def_reviews: bool = False

    @property
    def root(self) -> Path:
        return self.path.parent

    def paper(self, pid: str) -> Paper:
        for p in self.papers:
            if p.id == pid:
                return p
        raise ConfigError(f"no paper {pid!r} in {self.path}")


CONFIG_NAMES = ("machinechecked.toml", "prooflens.toml")


def work_dir_name(base: Path) -> str:
    """The working directory's name: `.machinechecked`, or `.prooflens` where one exists."""
    return ".prooflens" if (base / ".prooflens").is_dir() and \
        not (base / ".machinechecked").is_dir() else ".machinechecked"


def issue_repo(value: str | None, where: str) -> str | None:
    """A GitHub repository given as `owner/repo` (or its URL), checked."""
    if not value:
        return None
    v = re.sub(r"^(https?://)?(www\.)?github\.com/", "", value.strip()).rstrip("/")
    v = re.sub(r"\.git$", "", v)
    if not re.fullmatch(r"[A-Za-z0-9][\w.-]*/[\w.-]+", v):
        raise ConfigError(f"{where}: issues must be a GitHub repository, owner/repo: {value!r}")
    return v


def _prefixes(d: dict, key: str, where: str) -> list[str]:
    """A layer's prefixes: one string, or a non-empty list of strings."""
    v = _req(d, key, where)
    vs = [v] if isinstance(v, str) else v
    if not isinstance(vs, list) or not vs or not all(isinstance(x, str) for x in vs):
        raise ConfigError(f"{where}: `{key}` must be a string or a non-empty list of strings")
    return vs


def _req(d: dict, key: str, where: str):
    if key not in d:
        raise ConfigError(f"{where}: missing `{key}`")
    return d[key]


def load(path: str | Path) -> Config:
    path = Path(path).resolve()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    base = path.parent
    proj = _req(raw, "project", str(path))
    notation = _macros(proj, str(path))
    papers = []
    for p in raw.get("paper", []):
        src = _req(p, "source", "paper")
        if not any(k in src for k in ("path", "git", "arxiv")):
            raise ConfigError(f"paper {p.get('id')}: source needs one of path, git, arxiv")
        if p.get("version") not in (None, "published", "manuscript"):
            raise ConfigError(f"paper {p.get('id')}: version must be \"published\" or "
                              f"\"manuscript\", not {p.get('version')!r}")
        papers.append(Paper(
            id=_req(p, "id", "paper"), title=p.get("title", p["id"]), source=src,
            root=p.get("root"), pdf=p.get("pdf"), pdf_sha256=p.get("pdf_sha256"), commit=src.get("rev"), envs=p.get("envs"),
            publish=Publish(**p.get("publish", {})), published=p.get("published"),
            published_note=p.get("note"), version=p.get("version"),
            notation_macros=list(dict.fromkeys(notation + _macros(p, f"paper {p['id']}")))))
    return Config(
        path=path,
        name=_req(proj, "name", "project"),
        lean_root=(base / proj.get("lean_root", ".")).resolve(),
        modules=_req(proj, "modules", "project"),
        scope_roots=_req(proj, "scope_roots", "project"),
        spec_prefix=_prefixes(proj, "spec_prefix", "project")[0],
        accept_prefix=_prefixes(proj, "accept_prefix", "project")[0],
        spec_prefixes=_prefixes(proj, "spec_prefix", "project"),
        accept_prefixes=_prefixes(proj, "accept_prefix", "project"),
        allowed_axioms=proj.get("allowed_axioms", STANDARD_AXIOMS),
        inventory=(base / _req(proj, "inventory", "project")).resolve(),
        reviews=[(base / r).resolve() for r in proj.get("reviews", [])],
        statement_authors=proj.get("statement_authors", []),
        ai_reviewers=proj.get("ai_reviewers", []),
        dismissals=(base / proj["dismissals"]).resolve() if "dismissals" in proj else None,
        comparator_log=(base / proj["comparator_log"]).resolve()
        if "comparator_log" in proj else None,
        papers=papers,
        out_dir=(base / proj.get("out_dir", work_dir_name(base))).resolve(),
        # A command run after promoting reviews (from the configuration's directory): the
        # project's own acceptance checker, if it has one.
        review_check=raw.get("review", {}).get("check"),
        # Display corrections (TeX descriptions, printed numbers), outside the inventory.
        display=(base / proj["display"]).resolve() if "display" in proj else None,
        # Links from symbols of the paper to Lean objects, each an author's assertion (display
        # only, docs/SYMBOL_LINKS.md).
        symbols=(base / proj.get("symbols", "symbols.json")).resolve(),
        issues=issue_repo(proj.get("issues"), str(path)),
        site_url=proj.get("site_url"),
        author=proj.get("author"),
        repository=issue_repo(proj.get("repository"), str(path)),
        repository_private=bool(proj.get("repository_private", False)),
        review_citations_ignore=_patterns(proj, "review_citations_ignore", str(path)),
        review_citations_strict=bool(proj.get("review_citations_strict", False)),
        bare_markers_by=_names(proj, "bare_markers_by", str(path)) or [],
        inhabited_classes=_names(proj, "inhabited_classes", str(path)),
        require_witness_def_reviews=_flag(proj, "require_witness_def_reviews", str(path)),
    )


# The `[project]` header, and the line that opens its `modules` array (`check --fix-modules`).
_PROJECT_HEADER = re.compile(
    r"""[ \t]*\[[ \t]*(?:project|"project"|'project')[ \t]*\][ \t]*(?:#.*)?""")
_MODULES_KEY = re.compile(r"""[ \t]*(?:modules|"modules"|'modules')[ \t]*=[ \t]*\[""")


def add_modules(path: str | Path, modules: list[str]) -> list[str]:
    """Append `modules` to the `modules` array under `[project]` in the configuration at `path`,
    after the modules it lists and in the order given, leaving every other byte of the file as
    it is (comments, order, layout, line endings). Returns the modules added: those not listed
    already. Writes nothing and raises ConfigError when the array is not one this can extend in
    place (a `modules` given otherwise than as `modules = [...]` under a `[project]` header),
    or when the edited file would not read as the same configuration with those modules
    appended."""
    path = Path(path)
    text = path.read_bytes().decode("utf-8")
    before = tomllib.loads(text)
    listed = (before.get("project") or {}).get("modules")
    if not isinstance(listed, list) or not all(isinstance(m, str) for m in listed):
        raise ConfigError(f"{path}: `modules` under [project] is not a list of module names")
    add = [m for m in dict.fromkeys(modules) if m not in listed]
    if not add:
        return []
    after = _appended(text, add, path)
    expected = {**before, "project": {**before["project"], "modules": listed + add}}
    try:
        same = tomllib.loads(after) == expected
    except tomllib.TOMLDecodeError:
        same = False
    if not same:
        raise ConfigError(f"{path}: `modules` could not be extended in place")
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(after.encode("utf-8"))
    tmp.chmod(path.stat().st_mode & 0o7777)
    tmp.replace(path)
    return add


def _appended(text: str, add: list[str], path: Path) -> str:
    """`text` with the strings `add` appended to its `[project]` table's `modules` array, in the
    array's own layout: on its line when it is written on one line, else one per line with the
    indentation and trailing comma of its last element."""
    opening, in_project, pos = None, False, 0
    for line in text.splitlines(keepends=True):
        if re.match(r"[ \t]*\[", line):
            in_project = bool(_PROJECT_HEADER.fullmatch(line.rstrip("\r\n")))
        elif in_project and (m := _MODULES_KEY.match(line)):
            opening = pos + m.end() - 1
            break
        pos += len(line)
    if opening is None:
        raise ConfigError(f"{path}: no `modules = [` line under a [project] header")
    elems, i = [], opening + 1
    while True:
        if i >= len(text):
            raise ConfigError(f"{path}: the `modules` array is not closed")
        c = text[i]
        if c in " \t\r\n,":
            i += 1
        elif c == "#":
            i = text.find("\n", i)
            i = len(text) if i < 0 else i
        elif c == "]":
            break
        elif c in "\"'" and not text.startswith(c * 3, i):
            j = i + 1
            while j < len(text) and text[j] != c and text[j] != "\n":
                j += 2 if c == '"' and text[j] == "\\" else 1
            if j >= len(text) or text[j] != c:
                raise ConfigError(f"{path}: a string in the `modules` array is not closed")
            elems.append((i, j + 1, c))
            i = j + 1
        else:
            raise ConfigError(f"{path}: the `modules` array holds something other than "
                              "one-line strings")
    closing = i
    if not elems:
        return text[:opening + 1] + ", ".join(map(_toml_string, add)) + text[opening + 1:]
    start, end, quote = elems[-1]
    new = [_toml_string(m, quote) for m in add]
    if "\n" not in text[opening:start]:
        return text[:end] + "".join(", " + q for q in new) + text[end:]
    nl = "\r\n" if "\r\n" in text else "\n"
    line_start = text.rfind("\n", 0, start) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group(0)
    tail = re.compile(r"[ \t]*(,)?[ \t]*(?:#[^\r\n]*)?").match(text, end, closing)
    if tail.group(1):
        return text[:tail.end()] + "".join(nl + indent + q + "," for q in new) + text[tail.end():]
    return (text[:end] + "," + text[end:tail.end()] + ",".join(nl + indent + q for q in new)
            + text[tail.end():])


def _toml_string(s: str, quote: str = '"') -> str:
    """`s` as a TOML string: a literal string when `quote` is `'` and `s` allows one, else a
    basic string (JSON's escapes are TOML's)."""
    import json
    if quote == "'" and not re.search(r"['\x00-\x1f\x7f]", s):
        return f"'{s}'"
    return json.dumps(s, ensure_ascii=False)


def _flag(proj: dict, key: str, where: str) -> bool:
    """A true/false option of the configuration, false when absent."""
    v = proj.get(key, False)
    if not isinstance(v, bool):
        raise ConfigError(f"{where}: {key} must be true or false")
    return v


def _names(proj: dict, key: str, where: str) -> list[str] | None:
    """A list of names from the configuration, or None when the key is absent."""
    if key not in proj:
        return None
    v = proj[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where}: {key} must be a list of names")
    return v


def _macros(table: dict, where: str) -> list[str]:
    """The notation macros a table lists (`notation_macros`), as control sequences."""
    from .source_regions import RegionError, macro_name
    names = _names(table, "notation_macros", where) or []
    try:
        return [macro_name(n) for n in names]
    except RegionError as error:
        raise ConfigError(f"{where}: {error}") from None


def _patterns(proj: dict, key: str, where: str) -> list[str] | None:
    """A list of regular expressions from the configuration, or None when the key is absent."""
    if key not in proj:
        return None
    v = proj[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where}: {key} must be a list of regular expressions")
    for x in v:
        try:
            re.compile(x)
        except re.error as e:
            raise ConfigError(f"{where}: {key}: {x!r} is not a regular expression: {e}") from None
    return v
