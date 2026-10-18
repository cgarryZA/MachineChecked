"""Claims of a paper that is only a PDF: its numbered statements, found by styled headings.

A typeset theorem starts with its head in bold ("Lemma 8.6."), which distinguishes it from a
reference to it in the text ("by Lemma 8.6"). The PDF is read with poppler's `pdftohtml -xml`,
which keeps bold runs and positions. Each claim is placed from its head to the next head or
proof on the same page; the end is an estimate (a PDF does not record where a statement ends),
so its anchor is `approximate`. Remark-like heads may be italic. These are typography
heuristics, not a guarantee that every statement in an arbitrary PDF will be found.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .util import norm_ws, sha256_text

KINDS = ("Theorem", "Lemma", "Proposition", "Corollary", "Definition", "Remark", "Example",
         "Assumption", "Conjecture", "Claim", "Hypothesis", "Convention", "Note")
# A statement's number: "3", "8.6", "A1", "4.2a", or an appendix's "A.1", "B.10".
NUMBER = r"(?:[A-Z](?:\.\d+)+|[A-Z]?\d+(?:\.\d+)*)[a-z]?"
HEAD = re.compile(r"^(" + "|".join(KINDS) + r")\s+(" + NUMBER + r")\s*(\.|\(|$)")
STOP = re.compile(r"^(Proof\b|\d+(\.\d+)*\s+[A-Z])")


BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi|cmbx|-bd\b|bx\d", re.I)
ITALIC_FONT = re.compile(r"italic|oblique|cmti|cmsl", re.I)
ITALIC_KINDS = {"Remark", "Example", "Note", "Claim"}


def _prefix(element: ET.Element, tag: str, whole: bool) -> str:
    """The leading text in one style; later emphasis does not turn a reference into a head."""
    if whole:
        return "".join(element.itertext()).strip()
    fragments = []

    def visit(node, active=False):
        active = active or node.tag == tag
        if node.text:
            fragments.append((node.text, active))
        for child in node:
            visit(child, active)
            if child.tail:
                fragments.append((child.tail, active))

    visit(element)
    prefix = []
    for text, active in fragments:
        if text.strip() and not active:
            break
        prefix.append(text)
    return "".join(prefix).strip()


def _lines(xml_text: str) -> list[dict]:
    """Join nearby same-baseline font runs, retaining each row's leading styled text.

    amsthm can print an italic 'Remark' and an upright number as separate PDF runs. Large
    horizontal gaps (such as a column boundary) are not joined.
    """
    root = ET.fromstring(xml_text)
    bold_fonts = {f.get("id") for f in root.iter("fontspec")
                  if BOLD_FONT.search(f.get("family", ""))}
    italic_fonts = {f.get("id") for f in root.iter("fontspec")
                    if ITALIC_FONT.search(f.get("family", ""))}
    out = []
    for page in root.iter("page"):
        pno = int(page.get("number"))
        height = float(page.get("height"))
        scale = float(page.get("pt_height")) / height if page.get("pt_height") else 1.0
        for node in page.iter("text"):
            text = "".join(node.itertext()).strip()
            if not text:
                continue
            y = float(node.get("top")) * scale
            h = float(node.get("height")) * scale
            x = float(node.get("left", "0")) * scale
            right = x + float(node.get("width", "0")) * scale
            bold = node.get("font") in bold_fonts
            italic = node.get("font") in italic_fonts
            row = {"page": pno, "y0": y, "y1": y + h, "x0": x, "x1": right,
                   "text": text, "bold": bold or any(True for _ in node.iter("b")),
                   "italic": italic or any(True for _ in node.iter("i")),
                   "head": _prefix(node, "b", bold), "italic_head": _prefix(node, "i", italic)}
            previous = out[-1] if out else None
            gap = x - previous["x1"] if previous else 0
            if (previous and previous["page"] == pno and abs(previous["y0"] - y) <= scale
                    and -2 * scale <= gap <= 1.5 * h):
                separator = "" if gap <= max(scale, 0.15 * h) else " "
                for key in ("head", "italic_head"):
                    if previous[key] == previous["text"] and row[key]:
                        previous[key] += separator + row[key]
                previous["text"] += separator + text
                previous["x1"] = right
                previous["y1"] = max(previous["y1"], row["y1"])
                previous["bold"] |= row["bold"]
                previous["italic"] |= row["italic"]
            else:
                out.append(row)
    return out


def heading(line: dict):
    """A heading must start the text run; italic style is allowed only for remark-like kinds."""
    match = HEAD.match(line["text"])
    if match is None:
        return None
    styles = [(line.get("bold"), line.get("head", ""))]
    if match.group(1) in ITALIC_KINDS:
        styles.append((line.get("italic"), line.get("italic_head", "")))
    for enabled, text in styles:
        styled = HEAD.match(text) if enabled else None
        if enabled and (text.strip() == match.group(1)
                        or styled and styled.group(1, 2) == match.group(1, 2)):
            return match
    return None


def page_heights(pdf: Path) -> dict[int, float]:
    """Each page's height in points, from `pdfinfo`."""
    r = subprocess.run(["pdfinfo", "-f", "1", "-l", "100000", str(pdf)], capture_output=True,
                       text=True)
    out = {}
    for m in re.finditer(r"Page\s+(\d+)\s+size:\s+[\d.]+\s+x\s+([\d.]+)", r.stdout):
        out[int(m.group(1))] = float(m.group(2))
    return out


def claims_from_pdf(pdf: Path) -> tuple[list[dict], tuple[float, float] | None]:
    """The paper's numbered statements as anchors (the shape LaTeX anchors have), and its page
    size in points."""
    with tempfile.TemporaryDirectory(prefix="mc-pdf-") as tmp:
        base = Path(tmp) / "doc"
        r = subprocess.run(["pdftohtml", "-xml", "-i", "-q", "-nodrm", "-noframes", str(pdf),
                            str(base)], capture_output=True, text=True, timeout=600)
        x = base.with_suffix(".xml")
        if r.returncode != 0 or not x.exists():
            return [], None
        xml_text = x.read_text(encoding="utf-8", errors="replace")
    heights = page_heights(pdf)
    root = ET.fromstring(xml_text)
    xml_h = {int(p.get("number")): float(p.get("height")) for p in root.iter("page")}
    xml_w = {int(p.get("number")): float(p.get("width")) for p in root.iter("page")}
    lines = _lines(xml_text)
    for l in lines:
        s = heights.get(l["page"], 0) / xml_h[l["page"]] if heights.get(l["page"]) else 1.0
        l["y0"] *= s
        l["y1"] *= s
    size = None
    if heights:
        p1 = min(heights)
        size = (round(xml_w[p1] * heights[p1] / xml_h[p1], 2), round(heights[p1], 2))

    heads = []
    for i, l in enumerate(lines):
        m = heading(l)
        if m:
            heads.append((i, m))
    anchors, seen = [], set()
    for k, (i, m) in enumerate(heads):
        kind, number = m.group(1).lower(), m.group(2)
        if (kind, number) in seen:          # a statement restated later keeps its first place
            continue
        seen.add((kind, number))
        nxt = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
        body, end = [], lines[i]
        for j in range(i, nxt):
            l = lines[j]
            if j > i and (re.match(r"Proof\b", l["text"]) or STOP.match(l["text"]) and l["bold"]
                          or l["page"] != lines[i]["page"] and len(body) > 3):
                break
            body.append(l["text"])
            if l["page"] == lines[i]["page"]:
                end = l
        text = norm_ws(" ".join(body))
        offset = m.start(3) if m.group(3) == "(" else m.end()
        rest = text[offset:].lstrip()
        title = None
        tm = re.match(r"\(([^)]{1,120})\)\s*\.?", rest) if m.group(3) == "(" or \
            rest.startswith("(") else None
        if tm:
            title = tm.group(1).strip()
        statement = text[:4000]
        anchors.append({
            "id": len(anchors) + 1, "env": kind, "file": None, "line": None, "number": number,
            "label": None, "labels": [], "title": title,
            "begin": [lines[i]["page"], 0, round(lines[i]["y0"], 2)],
            "head": None,
            "end": [lines[i]["page"], 0, round(end["y1"], 2)],
            "statement": statement, "source_sha256": sha256_text(statement), "kind": "pdf"})
    return anchors, size
