"""Detected PDF headings are covered by the inventory, without comparing them to TeX hashes."""

from types import SimpleNamespace
import shutil
import subprocess

import pytest

from prooflens.assess import Assessor
from prooflens.pdfclaims import _lines, claims_from_pdf, heading


def anchor(number, kind="theorem", ident=1):
    return {"id": ident, "env": kind, "number": number, "label": None,
            "file": None, "line": None, "begin": [1, 0, 100], "end": [1, 0, 130],
            "source_sha256": "b" * 64}


def item(number, kind="theorem", scope="formal", paper="T", **extra):
    return {"id": f"{paper}:{kind}:{number}", "paper": paper, "scope": scope,
            "scope_reviewed": True, "number": f"{kind.capitalize()} {number}",
            "source_sha256": "a" * 64, **extra}


def check(claims, anchors, **tex):
    cfg = SimpleNamespace(statement_authors=[], papers=[SimpleNamespace(id="T")])
    record = {"mode": "pdf", "anchors": anchors, "pdf_sha256": "c" * 64,
              "pdf_pinned": "c" * 64, **tex}
    assessor = Assessor(cfg, {"claims": claims}, {}, {"T": record}, [], [])
    # Proof replay is outside this source-coverage test; isolate the gate's source conditions.
    assessor.replay = lambda name: {"state": "pass"}
    assessor.inventory_checks()
    rows = [{"id": c["id"], "status": "formal: accepted", "status_code": "formal.accepted", "clauses": [{"accept": "Synthetic.proof"}]}
            for c in claims]
    return assessor.findings, assessor.gates(rows)["T"]


def test_omitted_pdf_heading_fails_consistency_and_release():
    findings, gate = check([item("1")], [anchor("1"), anchor("2", ident=2)])
    gaps = [f for f in findings if f["code"] == "inventory-gap"]
    assert len(gaps) == 1 and "Theorem 2" in gaps[0]["message"]
    assert not gate["consistency"]["pass"] and not gate["release"]["pass"]


def test_complete_pdf_inventory_passes_without_comparing_tex_hashes():
    findings, gate = check([item("1"), item("2")], [anchor("1"), anchor("2", ident=2)])
    assert findings == []
    assert gate["consistency"]["pass"] and gate["release"]["pass"]


def test_explicit_out_of_scope_entry_accounts_for_heading():
    findings, gate = check([item("1"), item("2", scope="expository", scope_note="Context only")],
                           [anchor("1"), anchor("2", ident=2)])
    assert findings == [] and gate["release"]["pass"]


def test_another_paper_cannot_cover_missing_heading():
    findings, _ = check([item("1"), item("2", paper="U")],
                        [anchor("1"), anchor("2", ident=2)])
    assert any(f["code"] == "inventory-gap" and "Theorem 2" in f["message"] for f in findings)


def test_manual_placement_is_not_a_blanket_coverage_waiver():
    c = item("1", location="paper.tex:20")
    findings, gate = check([c], [anchor("2")], manual_anchors={c["id"]: {"page": 1}})
    assert any(f["code"] == "inventory-gap" for f in findings)
    assert not gate["release"]["pass"]


def test_inventory_heading_not_detected_still_needs_manual_placement():
    findings, gate = check([item("1"), item("2")], [anchor("1")])
    assert not findings
    assert not gate["release"]["pass"]
    assert any("not found in the PDF" in r for r in gate["release"]["reasons"])


def test_same_number_different_kinds_are_distinct():
    findings, _ = check([item("1")], [anchor("1"), anchor("1", "remark", 2)])
    assert len(findings) == 1 and "Remark 1" in findings[0]["message"]


def test_each_gap_has_its_own_identity():
    findings, _ = check([item("1")], [anchor("2", ident=1), anchor("3", ident=2)])
    assert len({f["id"] for f in findings}) == 2


def line(content, font="0", family="Times-Roman"):
    xml = (f'<pdf2xml><page number="1" height="800" width="600">'
           f'<fontspec id="0" family="{family}"/>'
           f'<text top="100" height="12" font="{font}">{content}</text>'
           '</page></pdf2xml>')
    return _lines(xml)[0]


@pytest.mark.parametrize("kind", ["Remark", "Example", "Note", "Claim"])
def test_italic_remark_style_heads(kind):
    assert heading(line(f"<i>{kind} B.9.</i> The body.")).group(1, 2) == (kind, "B.9")
    assert heading(line(f"{kind} B.9. The body.", family="ABCDEF+CMTI10"))


@pytest.mark.parametrize("content", ["Remark B.9. Plain reference.",
                                    "By <b>Theorem 1.</b> the result follows.",
                                    "<i>Theorem 1.</i> is used in this proof.",
                                    "See <i>Remark B.9.</i> for context."])
def test_unstyled_and_inline_references_are_not_headings(content):
    assert heading(line(content)) is None


def test_bold_head_is_still_recognised():
    assert heading(line("<b>Lemma A.1.</b> A statement.")).group(1, 2) == ("Lemma", "A.1")


@pytest.mark.skipif(not all(shutil.which(x) for x in ("pdflatex", "pdftohtml", "pdfinfo")),
                    reason="requires TeX and poppler")
def test_real_pdf_with_italic_remark_style(tmp_path):
    document = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\theoremstyle{remark}
\newtheorem{remark}{Remark}
\newtheorem{example}{Example}
\newtheorem{note}{Note}
\newtheorem{claim}{Claim}
\begin{document}
\begin{theorem}A synthetic statement.\end{theorem}
\begin{remark}[Boundary]A synthetic remark.\end{remark}
\begin{example}A synthetic example.\end{example}
\begin{note}A synthetic note.\end{note}
\begin{claim}A synthetic claim.\end{claim}
\noindent By \textbf{Theorem 99.} the result follows.\par
\noindent \emph{Theorem 98.} is cited, not declared.\par
\noindent Remark 97. is an unstyled reference.
\end{document}
"""
    (tmp_path / "paper.tex").write_text(document)
    subprocess.run(["pdflatex", "-no-shell-escape", "-halt-on-error", "-interaction=nonstopmode",
                    "paper.tex"], cwd=tmp_path, capture_output=True, check=True, timeout=90)
    anchors, size = claims_from_pdf(tmp_path / "paper.pdf")
    assert [(a["env"], a["number"]) for a in anchors] == [
        ("theorem", "1"), ("remark", "1"), ("example", "1"), ("note", "1"), ("claim", "1")]
    assert anchors[1]["title"] == "Boundary"
    assert size and size[1] > 700
