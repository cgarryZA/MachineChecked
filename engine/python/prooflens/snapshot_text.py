"""A review snapshot without the text of a paper whose source may not be redistributed (#748).

When a paper's `publish.source_text` is false, `review pack` leaves the text of its source out of
the snapshot (`leave_out`). Each text the review steps show that comes from the paper's source (a
claim's printed statement and its anchor's copy of it, a proof step's context in the proof, each
further passage or notation definition of its pin: `FIELDS`) is replaced by null, and
`data/paper-sources.json` records where it is: the file within the source, the byte range, how
the text is formed from those bytes (`FORMS`) and the SHA-256 of the text. The manifest names each
such paper's source (its arXiv record, its folder in the project, or the commit of its
repository) with the SHA-256 of every file a passage comes from. The typeset excerpt, which only
the reader shows, is left out. `scan` then checks the snapshot as the public export is checked: a
snapshot that still holds a line of the source is not written.

The reviewer's side (`with_text`) obtains each such source the way `build` does (an arXiv download,
kept in the reviewer's working directory; the project's folder when the review runs in the
project), or takes the copy the reviewer gives (`--paper-source`). It checks every file and every
passage against its digest, then writes the snapshot's site data with the texts in place into the
reviewer's working directory, which the review steps read: they show exactly what a snapshot with
the text shows. A source that cannot be obtained, or that differs, refuses the step. Nothing here
runs TeX.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .util import link_or_copy, norm_ws

REFS = "data/paper-sources.json"
REFS_SCHEMA = "prooflens/paper-sources@1"
# The fields of a claim record that hold text of the paper's source, which the review steps show
# (`compare.passage`); `source_parts` holds one text per passage of a pin.
FIELDS = (("statement_tex",), ("context_tex",), ("anchor", "statement"))
PARTS = "source_parts"
# What only the reader shows, left out: the passage as typeset.
DISPLAY_ONLY = ("excerpt",)
# How a text is formed from the bytes of its range, read as UTF-8: as the build reads a source
# file, with each line ending a newline (`text`), or with each run of white space one space and
# none at the ends (`whitespace`, a statement's environment body: `tex.statement_at`).
FORMS = ("text", "whitespace")
# The files of a source whose lines a snapshot without its text must not hold, as for the public
# export (`export.private_inputs`); the passages are looked for in them.
TEXT_SUFFIXES = (".tex", ".bib", ".sty", ".cls", ".bbl", ".md")
SHOWN = 10


class PaperSourceError(RuntimeError):
    """A paper's source that cannot be obtained, or that is not the one the snapshot was made
    from, with what to do."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def formed(raw: bytes, form: str) -> str:
    """The text `form` makes of the bytes `raw` (`FORMS`)."""
    s = raw.decode("utf-8")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return norm_ws(s) if form == "whitespace" else s


# -- the author's side -------------------------------------------------------------------------

class _Source:
    """A paper's source as the build read it: its text files (`TEXT_SUFFIXES`), each decoded
    as UTF-8 both as it is and with its line endings read as newlines, as the build reads a
    source file."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.paths = [p for p in sorted(self.root.rglob("*")) if p.is_file()
                      and not p.is_symlink() and p.suffix.lower() in TEXT_SUFFIXES]
        self.files: dict[str, tuple[bytes, str, str]] = {}
        for p in self.paths:
            raw = p.read_bytes()
            try:
                s = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue  # no passage is located in it, and the scan still reads it
            self.files[p.relative_to(self.root).as_posix()] = (
                raw, s, s.replace("\r\n", "\n").replace("\r", "\n"))
        self.used: set[str] = set()

    @staticmethod
    def _untranslated(s: str, k: int) -> int:
        """The position in `s` of character `k` of `s` with its line endings read as newlines
        (a `\\r\\n` is at its `\\r`)."""
        if "\r" not in s:
            return k
        i = 0
        for _ in range(k):
            i += 2 if s.startswith("\r\n", i) else 1
        return i

    def find(self, text: str, where: str | None, line: int | None) -> dict | None:
        """Where `text` is in the source: its file, byte range and form (`FORMS`), from the
        file `where` first, and in it from the line `line` on first. None when no range of any
        file gives it."""
        names = sorted(self.files, key=lambda f: (f != where, f))
        for form in FORMS:
            if form == "whitespace":
                if text != norm_ws(text):
                    continue
                rx = re.compile(r"\s+".join(map(re.escape, text.split(" "))))
            for name in names:
                raw, s, t = self.files[name]
                hay = s if form == "whitespace" else t
                span = None
                for begin in dict.fromkeys((_line_start(hay, line) if name == where else 0, 0)):
                    if form == "whitespace":
                        m = rx.search(hay, begin)
                        span = m.span() if m else None
                    else:
                        i = hay.find(text, begin)
                        span = (i, i + len(text)) if i >= 0 else None
                    if span:
                        break
                if span is None:
                    continue
                a, b = span
                if form == "text":
                    a, b = self._untranslated(s, a), self._untranslated(s, b)
                a, b = (len(s[:x].encode("utf-8")) if len(raw) != len(s) else x for x in (a, b))
                if formed(raw[a:b], form) != text:
                    continue
                self.used.add(name)
                return {"file": name, "bytes": [a, b], "form": form}
        return None


def _line_start(s: str, line: int | None) -> int:
    """The position in `s` where its line `line` (from 1) starts; 0 when there is none."""
    i = 0
    for _ in range((line or 1) - 1):
        j = s.find("\n", i)
        if j < 0:
            return 0
        i = j + 1
    return i


def _where(ch: dict, part: dict | None = None) -> tuple[str | None, int | None]:
    """The file and line a claim's text (or one passage of its pin) is printed at."""
    if part is not None:
        return part.get("file"), part.get("start_line")
    a = ch.get("anchor") or {}
    if a.get("file"):
        return a["file"], a.get("line")
    loc = str(ch.get("location") or "")
    m = re.fullmatch(r"(.+):(\d+)", loc)
    return (m.group(1), int(m.group(2))) if m else (loc or None, None)


def leave_out(files: dict[str, bytes], papers: dict[str, dict]) -> tuple[dict, list[str]]:
    """Leave the text of the sources of `papers` (paper id: `{"dir", "source"}`, the build's copy
    of its source and what names it) out of the snapshot's `files` (in place), adding `REFS`.
    Returns the manifest's `paper_text` entries of those papers, and what else was left out, in
    words. A text that no range of its source gives refuses the snapshot (`SnapshotError`)."""
    from .review_snapshot import DATA, SnapshotError, _json_bytes
    for pid, p in papers.items():
        if not Path(p["dir"]).is_dir():
            raise SnapshotError(f"the build's copy of paper {pid}'s source ({p['dir']}) is "
                                "missing: run `machinechecked build` first")
    srcs = {pid: _Source(p["dir"]) for pid, p in papers.items()}
    refs: dict[str, list] = {}
    lost, excerpts = [], 0
    for name in sorted(n for n in files if n.startswith(f"{DATA}/claims/")):
        ch = json.loads(files[name])
        src = srcs.get(ch.get("paper")) if isinstance(ch, dict) else None
        if src is None:
            continue
        found = []
        places = [(at, _where(ch)) for at in FIELDS]
        places += [((PARTS, i, "text"), _where(ch, part))
                   for i, part in enumerate(ch.get(PARTS) or []) if isinstance(part, dict)]
        for at, where in places:
            obj = ch
            for k in at[:-1]:
                obj = obj.get(k) if isinstance(obj, dict) else \
                    (obj[k] if isinstance(obj, list) and k < len(obj) else None)
            text = obj.get(at[-1]) if isinstance(obj, dict) else None
            if not isinstance(text, str) or not text:
                continue
            loc = src.find(text, *where)
            if loc is None:
                lost.append(f"{'.'.join(map(str, at))} of {ch.get('id')}")
                continue
            found.append({"at": list(at), "paper": ch["paper"], **loc,
                          "sha256": _sha(text.encode("utf-8"))})
            obj[at[-1]] = None
        shown = [k for k in DISPLAY_ONLY if ch.get(k) is not None]
        for k in shown:
            ch[k] = None
        excerpts += bool(shown)
        if found or shown:
            files[name] = _json_bytes(ch)
        if found:
            refs[name.removeprefix(f"{DATA}/")] = found
    if lost:
        raise SnapshotError(
            "the text of " + "; ".join(lost[:SHOWN]) + (f"; and {len(lost) - SHOWN} more"
                                                          if len(lost) > SHOWN else "")
            + " is no passage of its paper's source as the build read it, so a reviewer could "
              "not read it again from the source. Nothing was written: give --with-paper-text "
              "for a snapshot you hand over privately")
    files[REFS] = _json_bytes({"schema": REFS_SCHEMA, "claims": refs})
    entries = {pid: {"included": False, "source": p["source"],
                     "files": {f: _sha(srcs[pid].files[f][0]) for f in sorted(srcs[pid].used)}}
               for pid, p in papers.items()}
    said = [f"the typeset excerpts of {excerpts} claim(s), which only the reader shows"] \
        if excerpts else []
    return entries, said


def scan(files: dict[str, bytes], papers: dict[str, dict]) -> list[str]:
    """Every line of the sources of `papers` that the snapshot's `files` still hold, as the
    public export is scanned (`export.scan`), with the file and field that holds it."""
    from .export import scan as export_scan
    texts = [p for pid in papers for p in _Source(papers[pid]["dir"]).paths]
    with tempfile.TemporaryDirectory(prefix="machinechecked-scan-") as tmp:
        for name, b in files.items():
            dst = Path(tmp) / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
        return export_scan(Path(tmp), texts, set())


def source_name(src: dict) -> str:
    """A paper's source as a reviewer obtains it, in words."""
    if src.get("kind") == "arxiv":
        return f"arXiv {src.get('arxiv')}"
    if src.get("kind") == "path":
        return f"the folder {src.get('path')} of the project"
    if src.get("kind") == "git":
        return f"its Git repository at commit {src.get('revision')}"
    return "its source"


# -- the reviewer's side -----------------------------------------------------------------------

def left_out(manifest: dict) -> dict[str, dict]:
    """The papers whose text a snapshot leaves out (`paper_text`), by id."""
    return {pid: e for pid, e in (manifest.get("paper_text") or {}).items()
            if isinstance(e, dict) and e.get("included") is False}


def given_sources(values: list[str] | None, papers: dict[str, dict]) -> dict[str, Path]:
    """The sources a reviewer gives (`--paper-source [PAPER=]FILE`), by paper id. A value without
    a paper id is the source of the only paper whose text the snapshot leaves out."""
    out = {}
    for v in values or []:
        pid, sep, path = v.partition("=")
        if not sep or pid not in papers:
            if len(papers) != 1:
                raise PaperSourceError(
                    f"--paper-source {v}: the snapshot leaves out the text of papers "
                    f"{', '.join(sorted(papers))}: give each as PAPER=FILE")
            pid, path = next(iter(papers)), v
        out[pid] = Path(path)
    return out


def _problems(d: Path, want: dict[str, str]) -> list[str]:
    out = []
    for rel, digest in want.items():
        p = d / rel
        if not p.is_file():
            out.append(f"{rel} is missing")
        elif _sha(p.read_bytes()) != digest:
            out.append(f"{rel} differs")
    return out


def _fill(dest: Path, given: Path, want: dict[str, str]) -> None:
    """`dest`, made afresh, holding the files `want` names of the source `given`: a directory, or
    a file as arXiv serves a source (a gzipped tar, a gzipped file, a `.tex`)."""
    from .sources import unpack_eprint
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if given.is_dir():
        for rel in want:
            src = given / rel
            if src.is_file():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest / rel)
        return
    try:
        unpack_eprint(given.read_bytes(), dest)
    except (OSError, EOFError, ValueError) as e:
        raise PaperSourceError(f"{given} cannot be read as a paper's source ({e})") from None


def _source(pid: str, entry: dict, work: Path, given: Path | None, root: Path | None) -> Path:
    """The directory holding paper `pid`'s source, every file the snapshot reads checked against
    its digest: the copy given, else the one kept in the reviewer's working directory, else the
    project's folder, else the arXiv record, downloaded once into that directory."""
    from .config import Paper
    from .sources import SourceError, _arxiv
    want, src = entry.get("files") or {}, entry.get("source") or {}
    what = source_name(src)
    cache = work / "sources" / pid
    again = (f"Get the paper's source ({what}) and give it with --paper-source "
             f"{pid}=FILE (its folder, or the file arXiv serves); no step was taken")
    if given is not None:
        if not given.exists():
            raise PaperSourceError(f"--paper-source {given}: no such file or folder")
        if not given.resolve().is_relative_to(cache.resolve()):
            _fill(cache, given, want)
        bad = _problems(cache, want)
        if bad:
            shutil.rmtree(cache, ignore_errors=True)
            raise PaperSourceError(
                f"the source given for paper {pid} ({given}) is not the one the snapshot was "
                f"made from ({what}): " + "; ".join(bad[:SHOWN]) + ". No step was taken")
        return cache
    if cache.is_dir() and not _problems(cache, want):
        return cache
    if src.get("kind") == "path" and root is not None and (root / str(src.get("path"))).is_dir():
        here = root / str(src["path"])
        bad = _problems(here, want)
        if bad:
            raise PaperSourceError(
                f"the paper's source in {here} is not the one the snapshot was made from: "
                + "; ".join(bad[:SHOWN]) + ". Check out the commit the snapshot names, or "
                + again[0].lower() + again[1:])
        return here
    if src.get("kind") == "arxiv":
        if cache.exists():
            shutil.rmtree(cache)
        cache.mkdir(parents=True)
        try:
            _arxiv(Paper(id=pid, title=pid, source={"arxiv": src.get("arxiv")}), cache)
        except (SourceError, OSError, EOFError, ValueError) as e:
            shutil.rmtree(cache, ignore_errors=True)
            raise PaperSourceError(f"paper {pid}'s source could not be obtained ({e}). "
                                   + again) from None
        bad = _problems(cache, want)
        if bad:
            shutil.rmtree(cache, ignore_errors=True)
            raise PaperSourceError(
                f"the source arXiv serves for {src.get('arxiv')} is not the one the snapshot "
                "was made from: " + "; ".join(bad[:SHOWN]) + ". " + again)
        return cache
    raise PaperSourceError(f"the snapshot leaves out the text of paper {pid}, which a review "
                           f"reads from {what}. " + again)


def _resolved(data: Path, refs: dict, srcs: dict[str, Path],
              papers: dict[str, dict]) -> dict[str, bytes]:
    """The claim records `refs` names, with each text in place, every passage checked against
    its digest, by their path in the snapshot. A passage is read only from a file whose digest
    the manifest gives (`papers`), which was checked."""
    from .review_snapshot import DATA, _json_bytes
    out, bad = {}, []
    for rel, items in sorted((refs.get("claims") or {}).items()):
        if not isinstance(items, list) or PurePosixPath(rel).parts[:1] != ("claims",) \
                or ".." in PurePosixPath(rel).parts:
            raise PaperSourceError(f"{REFS} names {rel!r}, which is not a claim record")
        ch = json.loads((data / rel).read_text(encoding="utf-8"))
        for r in items:
            try:
                if r["file"] not in (papers[r["paper"]].get("files") or {}):
                    raise KeyError(r["file"])
                raw = (srcs[r["paper"]] / r["file"]).read_bytes()
                a, b = r["bytes"]
                text = formed(raw[a:b], r["form"])
                obj = ch
                for k in r["at"][:-1]:
                    obj = obj[k]
                obj[r["at"][-1]]  # the field the text goes in
            except (KeyError, IndexError, OSError, TypeError, ValueError, UnicodeDecodeError):
                bad.append(f"a passage of {ch.get('id')} ({r.get('file')})")
                continue
            if r.get("form") not in FORMS or _sha(text.encode("utf-8")) != r.get("sha256"):
                bad.append(f"the passage {'.'.join(map(str, r['at']))} of {ch.get('id')} "
                           f"({r['file']}, bytes {a}-{b})")
                continue
            obj[r["at"][-1]] = text
        out[f"{DATA}/{rel}"] = _json_bytes(ch)
    if bad:
        raise PaperSourceError("the paper's source does not give " + "; ".join(bad[:SHOWN])
                               + " as the snapshot records it. No step was taken")
    return out


def with_text(data: Path, work: Path, given: list[str] | None = None,
              root: Path | None = None) -> tuple[Path, list[str]]:
    """The site data a review of the snapshot whose data is `data` reads, and what to say of
    it: the snapshot's own when it holds the paper's text; else a copy in the reviewer's working
    directory `work` with each passage read from the paper's source (`_source`, with the sources
    `given` and the project's folder at `root`) and checked. A source that cannot be obtained,
    or that differs, refuses the step (`PaperSourceError`)."""
    from .review_snapshot import DATA, MANIFEST, SnapshotError, _check_dir
    raw = (data.parent / MANIFEST).read_bytes()
    manifest = json.loads(raw)
    papers = left_out(manifest)
    if not papers:
        return data, (["the snapshot holds the paper's text: --paper-source is not used"]
                      if given else [])
    named = given_sources(given, papers)
    refs = json.loads((data / REFS.removeprefix(f"{DATA}/")).read_text(encoding="utf-8"))
    srcs = {pid: _source(pid, e, work, named.get(pid), root) for pid, e in papers.items()}
    resolved = _resolved(data, refs, srcs, papers)
    files = {n: d for n, d in manifest["files"].items() if n != REFS}
    files.update({n: _sha(b) for n, b in resolved.items()})
    target = work / "resolved" / _sha(raw)[:24]
    said = [f"the passages of paper {pid} are read from {source_name(e.get('source') or {})}, "
            "each checked against its digest" for pid, e in sorted(papers.items())]
    try:
        _check_dir(target, {"files": files}, str(target))
        return target / DATA, said
    except SnapshotError:
        pass  # not written yet, or changed since: written again
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=target.parent, prefix=".resolve-"))
    try:
        for name in files:
            dst = tmp / name
            if name in resolved:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(resolved[name])
            else:
                link_or_copy(data.parent / name, dst)
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return target / DATA, said
