"""The paper around a review unit's passages, on request (`review read --context`): read from the
build's copy of the paper's source, it is context, never the unit's pinned text, and no reading
records it.

For each passage: the headings of the sections that enclose it; the paragraph just before it and
the one just after (each kept to `PARAGRAPH_LINES` lines); the labels inside it, each with the
number the compiled paper prints for it (from the build's `.aux` file); the numbered statements it
cites (`\\ref` and its kin), with their passages; for a proof step, the statement whose proof it
belongs to, with its passage; and the numbered statements that cite one of its labels or, for a
definition, use a term it defines (a word it sets in `\\emph`, `\\textit` or `\\textbf`), with
their numbers and lines. Those last are found by the label a statement cites or the word it
prints: a use in other words is not found.

Everything here is the paper's: the source, its passages and its numbers. Nothing of the Lean, of
the inventory's clauses or of anyone's reading is read, so the context may be shown before the
reading is locked. The paper's `\\lean{...}` tags are removed, as from the passages.
"""

from __future__ import annotations

import re
from pathlib import Path

PARAGRAPH_LINES = 12
SECTIONS = ("part", "chapter", "section", "subsection", "subsubsection", "paragraph")
HEADING = re.compile(r"^\s*\\(" + "|".join(SECTIONS) + r")\*?\s*(\[[^\]]*\])?\s*\{(.*)\}")
LABEL = re.compile(r"\\label\{([^{}]+)\}")
REF = re.compile(r"\\(?:eq|c|C|auto|name|page)?ref\*?\{([^{}]+)\}")
# How a definition sets the term it defines.
DEFINED = re.compile(r"\\(?:emph|textit|textbf|textsl)\{([^{}$\\]{2,60})\}"
                     r"|\{\\em\s+([^{}$\\]{2,60})\}")
NOTE = ("context, read from the build's copy of the paper's source: not the unit's pinned "
        "text, and no reading records it")


def _uncomment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def _strip(text: str) -> str:
    from .compare import LEAN_TAGS
    return re.sub(r"[ \t]{2,}", " ", LEAN_TAGS.sub("", text)).strip() if LEAN_TAGS.search(text) \
        else text


def where(ch: dict) -> tuple[str, int, int] | None:
    """The file and lines of a claim's passage in the paper's source: those its record gives,
    extended to the lines its printed text spans."""
    from .requirements import _where
    w = _where(ch)
    if w is None:
        return None
    file, first, last = w
    text = ch.get("statement_tex")
    if last == first and isinstance(text, str) and "\n" in text:
        last = first + text.count("\n")
    return file, first, last


def _paragraph(lines: list[str], i: int, step: int) -> dict | None:
    """The paragraph next to line `i` (1-based) going by `step` (-1: before, +1: after): the run
    of lines up to the next blank line, past the blank lines next to `i`, kept to
    `PARAGRAPH_LINES` lines; None when a section heading or the file's end comes first."""
    n, j = len(lines), i + step
    # Blank lines, and lines holding only a comment, before the paragraph.
    while 1 <= j <= n and not _uncomment(lines[j - 1]).strip():
        j += step
    if not 1 <= j <= n or HEADING.match(lines[j - 1]) or \
            re.match(r"\s*\\(end|begin)\{document\}", lines[j - 1]):
        return None
    got = []
    while 1 <= j <= n and lines[j - 1].strip() and not HEADING.match(lines[j - 1]) and \
            len(got) < PARAGRAPH_LINES:
        got.append(j)
        j += step
    more = 1 <= j <= n and lines[j - 1].strip() and not HEADING.match(lines[j - 1])
    a, b = min(got), max(got)
    text = "\n".join(t for t in (_uncomment(lines[k - 1]).rstrip() for k in range(a, b + 1))
                     if t.strip())
    if not text.strip():
        return None
    return {"start_line": a, "end_line": b, "text": _strip(text),
            **({"cut": f"kept to {PARAGRAPH_LINES} lines"} if more else {})}


def _sections(lines: list[str], first: int) -> list[dict]:
    """The headings enclosing line `first`, the outermost first: the nearest heading before it,
    and each heading of a higher level before that."""
    out, level = [], len(SECTIONS)
    for k in range(first - 1, 0, -1):
        m = HEADING.match(_uncomment(lines[k - 1]))
        if m and SECTIONS.index(m.group(1)) < level:
            level = SECTIONS.index(m.group(1))
            out.append({"level": m.group(1), "title": _strip(m.group(3).strip()), "line": k})
    return out[::-1]


def _ref(c: dict, ch: dict, file_lines: tuple | None, with_text: bool) -> dict:
    out = {"claim": c["id"], "number": c.get("number") or ch.get("number"),
           "kind": ch.get("kind")}
    if file_lines:
        out.update(file=file_lines[0], start_line=file_lines[1], end_line=file_lines[2])
    if with_text and isinstance(ch.get("statement_tex"), str):
        out["text"] = _strip(ch["statement_tex"])
    return out


def _aux_numbers(build: Path | None) -> dict[str, str]:
    """The printed number of each label of a paper, from the `.aux` files of its build."""
    from .steps import aux_numbers
    out: dict[str, str] = {}
    for f in sorted(build.glob("*.aux")) if build and build.is_dir() else []:
        try:
            for k, v in aux_numbers(f.read_text(encoding="utf-8", errors="replace")).items():
                out.setdefault(k, v)
        except OSError:
            continue
    return out


def surroundings(site, chunks: list[dict], sources: Path | None, builds: Path | None,
                 unavailable: str | None = None) -> dict[str, dict]:
    """The context of each passage of `chunks` (claim records of `site`), by claim id. `sources`
    holds each paper's source as the build copied it (`<sources>/<paper>/`), `builds` each
    paper's compiled files (`<builds>/<paper>/*.aux`); `unavailable` says why there is no source
    to read (a review snapshot holds the passages only)."""
    from .source_regions import RegionError, source_file
    own = {ch["id"] for ch in chunks}
    others = []
    for c in site.claims:
        ch = site.chunk(c["id"])
        if ch is not None and c["id"] not in own:
            others.append((c, ch, where(ch)))
    # Each label the paper's passages hold, with the claim that holds it.
    holder: dict[str, tuple] = {}
    for c, ch, w in others:
        keys = [(ch.get("anchor") or {}).get("label")] + \
            LABEL.findall(ch.get("statement_tex") or "")
        if (ch.get("step") or ch.get("unit") in ("proof-equation",)) and ch.get("key"):
            keys.append(ch["key"])
        for k in keys:
            if k:
                holder.setdefault(k, (c, ch, w))
    out = {}
    numbers: dict[str, dict] = {}
    for ch in chunks:
        pid, w = ch.get("paper"), where(ch)
        src = Path(sources) / pid if sources and pid else None
        if unavailable or w is None or src is None or not src.is_dir():
            out[ch["id"]] = {"available": False, "reason": unavailable or (
                "the build places this passage in no file of the paper's source (a paper read "
                "from its PDF has none)" if w is None
                else "the build holds no copy of the paper's source")}
            continue
        file, first, last = w
        try:
            lines = source_file(src, file).read_text(encoding="utf-8").splitlines()
        except (RegionError, OSError, UnicodeError):
            out[ch["id"]] = {"available": False,
                             "reason": f"the build's copy of the paper's source has no {file}"}
            continue
        if pid not in numbers:
            numbers[pid] = _aux_numbers(Path(builds) / pid if builds else None)
        body = "\n".join(_uncomment(t) for t in lines[first - 1:last])
        mine = (ch.get("anchor") or {}).get("label") or ch.get("key")
        labels = [{"label": k, "number": numbers[pid].get(k),
                   "line": next((first + i for i, t in enumerate(lines[first - 1:last])
                                 if "\\label{" + k + "}" in t), None)}
                  for k in dict.fromkeys(LABEL.findall(body)) if k != mine]
        cites = []
        for k in dict.fromkeys(REF.findall(body)):
            for lab in (x.strip() for x in k.split(",")):
                hit = holder.get(lab)
                if hit and not any(x["claim"] == hit[0]["id"] for x in cites):
                    cites.append({**_ref(hit[0], hit[1], hit[2], True), "label": lab})
        cited = {}
        ownlabels = {x for x in [mine, *(lab["label"] for lab in labels)] if x}
        terms = list(dict.fromkeys(t.strip() for m in DEFINED.finditer(body)
                                   for t in m.groups() if t and t.strip())) \
            if ch.get("kind") == "definition" else []
        for c, oc, ow in others:
            text = _uncomment(oc.get("statement_tex") or "")
            why = [f"cites \\ref{{{lab}}}" for lab in sorted(ownlabels)
                   if any(lab in (x.strip() for x in r.split(",")) for r in REF.findall(text))]
            plain = LABEL.sub("", text)
            why += [f"uses the term “{t}”" for t in terms
                    if re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", plain, re.I)]
            if why:
                cited[c["id"]] = {**_ref(c, oc, ow, False), "why": why}
        s = {"available": True, "note": NOTE, "file": file, "start_line": first,
             "end_line": last, "sections": _sections(lines, first),
             "before": _paragraph(lines, first, -1), "after": _paragraph(lines, last, +1),
             "labels": labels, "cites": cites,
             "cited_by": sorted(cited.values(), key=lambda x: (
                 x.get("file") or "", x.get("start_line") or 0, x["claim"]))}
        if terms:
            s["terms"] = terms
        par = ((ch.get("step") or {}).get("parent") or {}).get("id") or (
            ch.get("parent") if isinstance(ch.get("parent"), str) else None)
        if par:
            pc = next(((c, oc, ow) for c, oc, ow in others if c["id"] == par), None)
            if pc:
                s["belongs_to"] = _ref(*pc, True)
        out[ch["id"]] = s
    return out


def lines_of(s: dict) -> list[str]:
    """The context of one passage (`surroundings`), as the text the read step prints."""
    if not s.get("available"):
        return [f"Its context in the paper: not available ({s.get('reason')})."]

    def span(x) -> str:
        a, b = x.get("start_line"), x.get("end_line")
        return f"{x.get('file') or s['file']}:{a}" + (f"-{b}" if b and b != a else "")

    def ref(x) -> str:
        return f"{x.get('number') or x['claim']}" + (f" ({span(x)})" if x.get("start_line") else "")

    out = [f"Its context in the paper ({NOTE}):"]
    if s["sections"]:
        out.append("  in " + " > ".join(f"{h['level']} “{h['title']}” (line {h['line']})"
                                       for h in s["sections"]))
    for key, what in (("before", "the paragraph before"), ("after", "the paragraph after")):
        p = s.get(key)
        if p:
            out.append(f"  {what} ({span(p)}" + (f", {p['cut']}" if p.get("cut") else "") + "):")
            out += ["    " + t for t in p["text"].split("\n")]
    if s["labels"]:
        out.append("  its labels: " + "; ".join(
            f"{x['label']}, printed as {x['number']}" if x.get("number") else
            f"{x['label']} (its printed number is not known)" for x in s["labels"]))
    if s.get("belongs_to"):
        out.append(f"  it belongs to the proof of {ref(s['belongs_to'])}:")
        out += ["    " + t for t in (s["belongs_to"].get("text") or "").split("\n")]
    for x in s["cites"]:
        out.append(f"  it cites {ref(x)}, by \\ref{{{x['label']}}}:")
        out += ["    " + t for t in (x.get("text") or "").split("\n")]
    if s["cited_by"]:
        out.append("  statements that cite it or use its terms:")
        out += [f"    {ref(x)}: {'; '.join(x['why'])}" for x in s["cited_by"]]
    return out
