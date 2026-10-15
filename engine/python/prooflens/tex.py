"""Compile a LaTeX snapshot with claim anchors, and read the anchors back.

The compilation runs on a private copy of the snapshot, with `latexmk -norc` (no rc files from the
source), shell escape off, kpathsea's paranoid output policy, and CPU and file-size limits.
`prooflens.sty` is injected before `\\documentclass`; the source is not edited.
"""

from __future__ import annotations

import os
import re
import resource
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from .sources import Snapshot
from .util import norm_ws, sha256_file, sha256_text

SP_PER_BP = 65781.76  # scaled points per PostScript point (PDF user unit)
DEFAULT_ENVS = ["theorem", "lemma", "proposition", "corollary", "definition", "assumption",
                "remark", "example", "conjecture", "claim", "hypothesis", "convention"]


class TexError(RuntimeError):
    pass


@dataclass
class Anchor:
    id: int
    env: str
    file: str
    line: int
    number: str | None = None
    labels: list[tuple[str, str]] = field(default_factory=list)
    begin: tuple[int, float, float] | None = None   # (page, x, y) in PDF points, y from top
    end: tuple[int, float, float] | None = None
    head: tuple[int, float, float] | None = None
    statement: str | None = None
    source_sha256: str | None = None

    @property
    def label(self) -> str | None:
        """The environment's own label: the first whose current label is its number."""
        for name, cur in self.labels:
            if cur == self.number:
                return name
        return None

    def to_json(self) -> dict:
        return {"id": self.id, "env": self.env, "file": self.file, "line": self.line,
                "number": self.number, "label": self.label,
                "labels": [list(x) for x in self.labels],
                "begin": list(self.begin) if self.begin else None,
                "end": list(self.end) if self.end else None,
                "head": list(self.head) if self.head else None,
                "source_sha256": self.source_sha256, "statement": self.statement}


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (600, 600))
    resource.setrlimit(resource.RLIMIT_FSIZE, (512 << 20, 512 << 20))


def theorem_envs(d: Path) -> list[str]:
    """Environment names declared with `\\newtheorem` anywhere in the source."""
    names = set()
    for p in d.rglob("*.tex"):
        txt = p.read_text(encoding="utf-8", errors="replace")
        names.update(re.findall(r"\\newtheorem\*?\{([A-Za-z@]+)\}", txt))
    return sorted(names)


def source_epoch(snap: Snapshot) -> int:
    """The time the build is dated with, so that the same source gives the same PDF: the
    commit time for a git source, else the latest modification time of the source files."""
    if snap.commit_time is not None:
        return snap.commit_time
    times = [p.stat().st_mtime for p in snap.dir.rglob("*") if p.is_file()]
    return int(max(times)) if times else 0


def compile_snapshot(snap: Snapshot, work: Path, envs: list[str] | None = None,
                     latexmk: str = "latexmk") -> dict:
    """Compile `snap` in `work`; return the PDF path, the `.plx` and `.fls` paths and the log."""
    if snap.mode != "latex":
        raise TexError("not a LaTeX snapshot")
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(snap.dir, work)
    root = work / snap.root
    cwd = root.parent
    sty = resources.files("prooflens").joinpath("data/prooflens.sty").read_text()
    (cwd / "prooflens.sty").write_text(sty)
    envs = envs or sorted(set(DEFAULT_ENVS) | set(theorem_envs(work)))
    pretex = "\\def\\prooflensEnvs{" + ",".join(envs) + "}\\RequirePackage{prooflens}"
    env = dict(os.environ, shell_escape="f", openout_any="p", TEXMFOUTPUT="",
               SOURCE_DATE_EPOCH=str(source_epoch(snap)), FORCE_SOURCE_DATE="1")
    for k in ("TEXINPUTS",):
        env.pop(k, None)
    cmd = [latexmk, "-norc", "-pdf", f"-jobname={root.stem}", "-interaction=nonstopmode",
           "-halt-on-error", "-file-line-error", f"-usepretex={pretex}", root.name]
    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                       preexec_fn=_limits, timeout=1800)
    pdf = cwd / f"{root.stem}.pdf"
    plx = cwd / f"{root.stem}.plx"
    if r.returncode != 0 or not pdf.exists() or not plx.exists():
        log = cwd / f"{root.stem}.log"
        tail = log.read_text(errors="replace")[-3000:] if log.exists() else r.stdout[-3000:]
        raise TexError(f"LaTeX compilation of {snap.root} failed:\n{tail}")
    return {"pdf": pdf, "plx": plx, "fls": cwd / f"{root.stem}.fls", "cwd": cwd}


def matching_end(txt: str, start: int, env: str) -> int:
    """Index of the `\\end{env}` closing the environment whose body starts at `start`."""
    pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
    depth = 1
    for m in pat.finditer(txt, start):
        depth += 1 if m.group(1) == "begin" else -1
        if depth == 0:
            return m.start()
    return len(txt)


def statement_at(path: Path, line: int, env: str) -> str | None:
    """The body of the environment `env` opening on `line` of `path`: after `\\begin{env}[title]`, up to the matching `\\end{env}`."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    offs = sum(len(l) + 1 for l in txt.split("\n")[: max(line - 1, 0)])
    m = re.compile(r"\\begin\{" + re.escape(env) + r"\}(\[[^\]]*\])?").search(txt, offs)
    if m is None:
        return None
    be = matching_end(txt, m.end(), env)
    return txt[m.end():be].strip()


def parse_plx(text: str, cwd: Path, snap_dir: Path) -> tuple[list[Anchor], tuple[float, float]]:
    anchors: dict[int, Anchor] = {}
    page_h = 0.0
    page_w = 0.0
    for raw in text.splitlines():
        parts = raw.split(" ")
        tag = parts[0]
        if tag == "paper":
            page_w = float(parts[1].rstrip("pt")) * 72 / 72.27
            page_h = float(parts[2].rstrip("pt")) * 72 / 72.27
        elif tag == "begin":
            i = int(parts[1])
            anchors[i] = Anchor(i, parts[2], " ".join(parts[4:]), int(parts[3]))
        elif tag == "number" and int(parts[1]) in anchors:
            anchors[int(parts[1])].number = " ".join(parts[2:])
        elif tag == "label" and int(parts[1]) in anchors:
            anchors[int(parts[1])].labels.append((parts[2], " ".join(parts[3:])))
        elif tag == "pos" and int(parts[1]) in anchors:
            page, x, y = int(parts[3]), int(parts[4]) / SP_PER_BP, int(parts[5]) / SP_PER_BP
            pt = (page, round(x, 2), round(page_h - y, 2))
            setattr(anchors[int(parts[1])], parts[2], pt)
    out = []
    for a in sorted(anchors.values(), key=lambda a: a.id):
        f = (cwd / a.file)
        st = statement_at(f, a.line, a.env)
        if st is not None:
            a.statement = norm_ws(st)
            a.source_sha256 = sha256_text(norm_ws(st))
        try:
            a.file = str(f.resolve().relative_to(snap_dir.resolve()))
        except ValueError:
            pass
        out.append(a)
    return out, (round(page_w, 2), round(page_h, 2))


def parse_fls(path: Path, cwd: Path) -> list[str]:
    """Source files read during compilation, relative to the build directory; files of the TeX
    distribution are left out."""
    if not path.exists():
        return []
    seen, out = set(), []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        p = Path(line[6:])
        full = p if p.is_absolute() else (cwd / p)
        try:
            rel = str(full.resolve().relative_to(cwd.resolve()))
        except ValueError:
            continue
        if rel not in seen and not rel.endswith((".aux", ".out", ".toc", ".plx")):
            seen.add(rel)
            out.append(rel)
    return out


def anchors_for(snap: Snapshot, work: Path, envs: list[str] | None = None) -> dict:
    """Compile and return the anchors, page size, inputs and PDF of a LaTeX snapshot."""
    res = compile_snapshot(snap, work, envs)
    anchors, size = parse_plx(res["plx"].read_text(encoding="utf-8", errors="replace"),
                              res["cwd"], work)
    root_dir = (work / snap.root).parent
    inputs = [str((root_dir / p).resolve().relative_to(work.resolve()))
              for p in parse_fls(res["fls"], res["cwd"]) if p != "prooflens.sty"]
    return {"anchors": anchors, "page_size": size, "inputs": inputs, "pdf": res["pdf"],
            "pdf_sha256": sha256_file(res["pdf"])}
