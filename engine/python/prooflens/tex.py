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
    title: str | None = None        # the optional argument of `\\begin{env}[…]`, as TeX

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
                "head": list(self.head) if self.head else None, "title": self.title,
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


ENGINE_FLAG = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def tex_engine(root: Path) -> str:
    """The TeX engine a LaTeX root needs, read without running anything from the source: a
    `% !TEX program` comment, else the engine a `latexmkrc` beside it names (matched as text,
    never executed), else XeLaTeX if the sources load `fontspec` or `unicode-math`."""
    head = "\n".join(root.read_text(errors="replace").splitlines()[:30])
    m = re.search(r"^\s*%\s*!\s*TEX\s+(?:TS-)?program\s*=\s*(pdflatex|xelatex|lualatex)",
                  head, re.M | re.I)
    if m:
        return m.group(1).lower()
    for rc in ("latexmkrc", ".latexmkrc"):
        try:
            t = (root.parent / rc).read_text(errors="replace")
        except OSError:
            continue
        t = "\n".join(l.split("#", 1)[0] for l in t.splitlines())
        m = re.search(r"\$pdflatex\s*=\s*['\"]\s*(xelatex|lualatex)", t)
        if m:
            return m.group(1)
        m = re.search(r"\$pdf_mode\s*=\s*([45])", t)
        if m:
            return "lualatex" if m.group(1) == "4" else "xelatex"
    for f in root.parent.rglob("*.tex"):
        try:
            if re.search(r"^[^%\n]*\\usepackage(\[[^\]]*\])?\{[^}]*\b(fontspec|unicode-math)\b",
                         f.read_text(errors="replace"), re.M):
                return "xelatex" if shutil.which("xelatex") else "lualatex"
        except OSError:
            pass
    return "pdflatex"


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
    cmd = [latexmk, "-norc", ENGINE_FLAG[tex_engine(root)], "-synctex=1", f"-jobname={root.stem}",
           "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
           f"-usepretex={pretex}", root.name]
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


def env_title(path: Path, line: int, env: str) -> str | None:
    """The optional argument of the environment `env` opening on `line` of `path`: its title as
    printed, in TeX (`Efficiency` for `\\begin{theorem}[Efficiency]`)."""
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    offs = sum(len(l) + 1 for l in txt.split("\n")[: max(line - 1, 0)])
    m = re.compile(r"\\begin\{" + re.escape(env) + r"\}\s*\[").search(txt, offs)
    if m is None or txt[offs:m.start()].strip():
        return None
    depth, brace, i = 1, 0, m.end()
    while i < len(txt) and depth:
        c = txt[i]
        if c == "\\":
            i += 2
            continue
        brace += (c == "{") - (c == "}")
        if not brace:
            depth += (c == "[") - (c == "]")
        i += 1
    return norm_ws(txt[m.end():i - 1]) or None if not depth else None


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
    prev: dict[int, str] = {}
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
        elif tag == "prev" and int(parts[1]) in anchors:
            prev[int(parts[1])] = " ".join(parts[2:])
        elif tag == "label" and int(parts[1]) in anchors:
            anchors[int(parts[1])].labels.append((parts[2], " ".join(parts[3:])))
        elif tag == "pos" and int(parts[1]) in anchors:
            page, x, y = int(parts[3]), int(parts[4]) / SP_PER_BP, int(parts[5]) / SP_PER_BP
            pt = (page, round(x, 2), round(page_h - y, 2))
            setattr(anchors[int(parts[1])], parts[2], pt)
    out = []
    names: dict[str, list[Path]] = {}
    for a in sorted(anchors.values(), key=lambda a: a.id):
        if a.id in prev and a.number == prev[a.id] and not (a.labels and a.labels[0][1] ==
                                                            a.number):
            # The head's paragraph began before the environment stepped its counter (a run-in
            # heading before it), or the environment is unnumbered: its own first label, if
            # any, gives its number. (A number equal to the previous label and confirmed by the
            # environment's own label is a coincidence of counters, as Lemma 4.1 after (4.1).)
            a.number = a.labels[0][1] if a.labels else None
        f = (cwd / a.file)
        if not f.exists():
            # A TeX older than \CurrentFilePath records the name alone: take the snapshot's
            # only file of that name.
            if not names:
                for p in snap_dir.rglob("*.tex"):
                    names.setdefault(p.name, []).append(p)
            cands = names.get(Path(a.file).name, [])
            if len(cands) == 1:
                f = cands[0]
        st = statement_at(f, a.line, a.env)
        a.title = env_title(f, a.line, a.env)
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


MARGIN = 60.0  # points at the top and bottom of a page holding running heads and page numbers


DISPLAY = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|flalign|alignat)\*?\}")
HEADING = re.compile(r"\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[\[{]")


def source_lines(text: list[str], line: int) -> list[list[int]]:
    """The source lines whose boxes place a claim at `line`, best first.

    SyncTeX attributes the line that opens a display to the paragraph before it, and a
    `\\label` line after a heading to the paragraph after it; so a display is placed by its
    body (less the boxes it shares with the opening line, see `synctex_lines`) and a labelled
    heading by the heading."""
    here = text[line - 1].strip() if 0 < line <= len(text) else ""
    m = DISPLAY.match(here)
    if m:
        end = re.compile(r"\\end\{" + m.group(1) + r"\*?\}")
        for j in range(line, min(len(text), line + 200)):
            if end.search(text[j]):
                body = list(range(line + 1, j + 2))
                return [body, [line]] if body else [[line]]
    if here.startswith("\\label"):
        k = line - 2
        while k >= 0 and not text[k].strip():
            k -= 1
        if k >= 0 and HEADING.match(text[k].strip()):
            return [[k + 1], [line]]
    return [[line]]


def _boxes(cwd: Path, pdf: Path, rel: str, line: int) -> list[dict]:
    for name in (rel, "./" + rel):
        r = subprocess.run(["synctex", "view", "-i", f"{line}:0:{name}", "-o", pdf.name],
                           cwd=cwd, capture_output=True, text=True, timeout=60)
        boxes, rec = [], {}
        for l in r.stdout.splitlines():
            k, _, v = l.partition(":")
            if k == "Page":
                rec = {"page": int(v)}
            elif k in ("v", "H", "W") and rec:
                rec[k] = float(v)
                if "v" in rec and "H" in rec and "W" in rec:
                    boxes.append(rec)
                    rec = {}
        if boxes:
            return boxes
    return []


def _content(boxes: list[dict], page_h: float) -> list[dict]:
    """The boxes inside the text block with height, and with width when any has: zero-width
    boxes are kerns and glue markers, which SyncTeX may place on a neighbouring page."""
    boxes = [b for b in boxes if b["H"] > 0 and MARGIN < b["v"] < page_h - MARGIN]
    wide = [b for b in boxes if b.get("W", 0) > 0]
    return wide or boxes


def synctex_lines(cwd: Path, pdf: Path, snap_dir: Path, locations: list[str],
                  page_h: float, anchors: list[Anchor]) -> dict:
    """Where SyncTeX puts each `<file>:<line>` of the source (paths relative to the snapshot).

    SyncTeX maps a line to every box typeset from it, which may lie on several pages (a macro
    defined on the line and used elsewhere, a running head). Empty boxes and boxes in the page
    margins are dropped; if the rest lie on one page, the anchor is the band covering them,
    `approximate`. If they lie on several pages, the exact anchors of the same file before and
    after the line bound the page; if that does not single one out, the line is `ambiguous`
    and gets no band. The lines queried are those of `source_lines`."""
    out = {}
    texts: dict[str, list[str]] = {}
    for loc in locations:
        path, _, line = loc.rpartition(":")
        try:
            rel = os.path.relpath(snap_dir / path, cwd)
        except ValueError:
            continue
        if path not in texts:
            try:
                texts[path] = (snap_dir / path).read_text(errors="replace").splitlines()
            except OSError:
                texts[path] = []
        boxes = []
        groups = source_lines(texts[path], int(line))
        opening = set()
        src = texts[path]
        if len(groups) > 1 and DISPLAY.match(src[int(line) - 1].strip() if src else ""):
            opening = {tuple(sorted(b.items())) for b in _boxes(cwd, pdf, rel, int(line))}
        for group in groups:
            boxes = [b for n in group for b in _boxes(cwd, pdf, rel, n)]
            if group != [int(line)]:
                boxes = [b for b in boxes if tuple(sorted(b.items())) not in opening]
            boxes = _content(boxes, page_h)
            if boxes:
                break
        pages = sorted({b["page"] for b in boxes})
        if len(pages) > 1 and opening:
            # A display does not break across pages: its page is that of its last line.
            last = {b["page"] for n in groups[0][-2:] for b in _content(_boxes(cwd, pdf, rel, n), page_h)}
            if len(last) == 1:
                pages = [p for p in pages if p in last]
        if len(pages) > 1:
            same = sorted((a.line, a.begin[0]) for a in anchors
                          if a.begin and a.file == path)
            lo = max([p for l, p in same if l < int(line)], default=None)
            hi = min([p for l, p in same if l > int(line)], default=None)
            pages = [p for p in pages if (lo is None or p >= lo) and (hi is None or p <= hi)]
        if len(pages) == 1:
            on = [b for b in boxes if b["page"] == pages[0]]
            out[loc] = {"kind": "approximate", "page": pages[0],
                        "y0": round(min(b["v"] - b["H"] for b in on), 2),
                        "y1": round(max(b["v"] for b in on), 2)}
        elif boxes:
            out[loc] = {"kind": "ambiguous", "pages": sorted({b["page"] for b in boxes})}
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
            "pdf_sha256": sha256_file(res["pdf"]), "cwd": res["cwd"],
            "line_anchors": lambda locs: synctex_lines(res["cwd"], res["pdf"], work, locs,
                                                       size[1], anchors)}
