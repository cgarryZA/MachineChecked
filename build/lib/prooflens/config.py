"""The project configuration, `prooflens.toml`."""

from __future__ import annotations

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

    @property
    def root(self) -> Path:
        return self.path.parent

    def paper(self, pid: str) -> Paper:
        for p in self.papers:
            if p.id == pid:
                return p
        raise ConfigError(f"no paper {pid!r} in {self.path}")


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
        papers.append(Paper(
            id=_req(p, "id", "paper"), title=p.get("title", p["id"]), source=src,
            root=p.get("root"), pdf=p.get("pdf"), commit=src.get("rev"), envs=p.get("envs"),
            publish=Publish(**p.get("publish", {}))))
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
        out_dir=(base / proj.get("out_dir", ".prooflens")).resolve(),
    )
