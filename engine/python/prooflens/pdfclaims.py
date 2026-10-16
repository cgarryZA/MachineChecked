"""Claims of a paper that is only a PDF: its numbered statements, found by their bold heads.

A typeset theorem starts with its head in bold ("Lemma 8.6."), which distinguishes it from a
reference to it in the text ("by Lemma 8.6"). The PDF is read with poppler's `pdftohtml -xml`,
which keeps bold runs and positions. Each claim is placed from its head to the next head or
proof on the same page; the end is an estimate (a PDF does not record where a statement ends),
so its anchor is `approximate`.
"""

from __future__ import annotations

import html
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .util import norm_ws, sha256_text

KINDS = ("Theorem", "Lemma", "Proposition", "Corollary", "Definition", "Remark", "Example",
         "Assumption", "Conjecture", "Claim", "Hypothesis", "Convention")
# A statement's number: "3", "8.6", "A1", "4.2a", or an appendix's "A.1", "B.10".
NUMBER = r"(?:[A-Z](?:\.\d+)+|[A-Z]?\d+(?:\.\d+)*)[a-z]?"
HEAD = re.compile(r"^(" + "|".join(KINDS) + r")\s+(" + NUMBER + r")\s*(\.|\(|$)")
STOP = re.compile(r"^(Proof\b|\d+(\.\d+)*\s+[A-Z])")


BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi|cmbx|-bd\b|bx\d", re.I)


def _lines(xml_text: str) -> list[dict]:
    """Every text run, in reading order: page, top and bottom in PDF points, text, bold. A run
    is bold when it is marked so, or when its font's name says so (Computer Modern's bold,
    CMBX, is not marked)."""
    root = ET.fromstring(xml_text)
    bold_fonts = {f.get("id") for f in root.iter("fontspec")
                  if BOLD_FONT.search(f.get("family", ""))}
    out = []
    for page in root.iter("page"):
        pno = int(page.get("number"))
        h = float(page.get("height"))
        scale = 1.0
        if page.get("pt_height"):
            scale = float(page.get("pt_height")) / h
        for t in page.iter("text"):
            raw = ET.tostring(t, encoding="unicode", method="xml")
            whole = t.get("font") in bold_fonts
            bold = "<b>" in raw or whole
            txt = html.unescape(re.sub(r"<[^>]+>", "", raw))
            top, height = float(t.get("top")), float(t.get("height"))
            out.append({"page": pno, "y0": top * scale, "y1": (top + height) * scale,
                        "text": txt.strip(), "bold": bold,
                        "head": txt.strip() if whole else html.unescape(re.sub(
                            r"<[^>]+>", "", "".join(ET.tostring(b, encoding="unicode")
                                                    for b in t.iter("b")))).strip()})
    return out


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
        m = HEAD.match(l["head"]) if l["bold"] else None
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
        rest = text[len(m.group(0)):].lstrip() if text.startswith(m.group(0)) else text
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
