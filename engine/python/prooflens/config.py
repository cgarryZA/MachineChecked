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
    display: Path | None = None
    symbols: Path | None = None
    issues: str | None = None         # "owner/repo" where the reader's "Raise issue" opens issues
    site_url: str | None = None       # the public address of the published site, for permalinks
    author: str | None = None         # the name the audit is published under (audit.json)
    repository: str | None = None     # "owner/repo" of the Lean source, if not the git remote
    repository_private: bool = False  # the reader does not show the repository's name
    # Type classes treated as inhabited by the witness check (`assess.INHABITED_CLASSES` when
    # not configured).
    inhabited_classes: list[str] | None = None

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
            published_note=p.get("note"), version=p.get("version")))
    return Config(
        path=path,
        name=_req(proj, "name", "project"),
        lean_root=(base / proj.get("lean_root", ".")).resolve(),
        modules=_req(proj, "modules", "project"),
        scope_roots=_req(proj, "scope_roots", "project"),
        spec_prefix=_req(proj, "spec_prefix", "project"),
        accept_prefix=_req(proj, "accept_prefix", "project"),
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
        inhabited_classes=_names(proj, "inhabited_classes", str(path)),
    )


def _names(proj: dict, key: str, where: str) -> list[str] | None:
    """A list of names from the configuration, or None when the key is absent."""
    if key not in proj:
        return None
    v = proj[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{where}: {key} must be a list of names")
    return v
