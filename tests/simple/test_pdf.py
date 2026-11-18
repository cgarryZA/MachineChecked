"""A paper that is only a PDF, in a project that may not be built."""

import json
import subprocess
import sys

from conftest import needs_tex
from prooflens.pdfclaims import claims_from_pdf
from prooflens.simple import NO_HEADINGS, build_view, write_view_site

DOC = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\theoremstyle{definition}
\newtheorem{definition}[theorem]{Definition}
\title{A Synthetic Paper}
\begin{document}
\maketitle
\section{Results}
\begin{definition}[Even]
A number is even if it is twice a number.
\end{definition}
\begin{lemma}
Every even number plus two is even.
\end{lemma}
\begin{proof}
Add two.
\end{proof}
This paragraph is long enough to wrap so that a reference begins a line of the text, as in
the following sentence, which is about the lemma above and not a new statement at all:
\par\noindent Lemma 1.2. is used below, but this line is not a heading.
\begin{theorem}[Main]
The sum of two even numbers is even.
\end{theorem}
\appendix
\section{Auxiliary facts}
\begin{lemma}
Zero is even.
\end{lemma}
\end{document}
"""


# Headings as journals often set them (#567): in the body's weight or in small capitals, with
# the statement in the same paragraph, and a paragraph that only refers to a result.
JOURNAL = r"""\documentclass{article}
\usepackage{amsthm}
\newtheoremstyle{journal}{\topsep}{\topsep}{\normalfont}{}{\normalfont}{}{ }{}
\newtheoremstyle{caps}{\topsep}{\topsep}{\itshape}{}{\scshape}{}{ }{}
\theoremstyle{journal}
\newtheorem{theorem}{Theorem}[section]
\theoremstyle{caps}
\newtheorem{lemma}[theorem]{Lemma}
\begin{document}
\section{Results}
Some introductory text that is long enough to wrap onto a second line of the page, so that the
paragraph has the shape of ordinary prose before the first statement.
\begin{theorem}
Suppose that every number considered here is even. Then the sum of any two of them is even.
\end{theorem}
\begin{lemma}
Let a and b be even. Then a plus b is even.
\end{lemma}
Theorem 1.1 gives the bound used below; this paragraph only refers to it.
\begin{theorem}
Zero is even.
\end{theorem}
\end{document}
"""

# A paper with a text layer and no numbered statement.
PROSE = r"""\documentclass{article}
\begin{document}
\section{Notes}
This paper states nothing numbered. It discusses Theorem 1 of another paper in passing.
\end{document}
"""


def _pdf(tmp_path, doc=DOC):
    (tmp_path / "paper.tex").write_text(doc)
    subprocess.run(["latexmk", "-norc", "-pdf", "-interaction=nonstopmode", "paper.tex"],
                   cwd=tmp_path, capture_output=True, check=True, timeout=300)
    return tmp_path / "paper.pdf"


def _project(tmp_path, doc):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper.pdf").write_bytes(_pdf(tmp_path, doc).read_bytes())
    return root


def _check(root, *args):
    return subprocess.run([sys.executable, "-m", "prooflens.cli", "check", *args, "paper.pdf"],
                          cwd=root, capture_output=True, text=True, encoding="utf-8")


@needs_tex
def test_statements_are_found_by_their_bold_heads(tmp_path):
    anchors, size = claims_from_pdf(_pdf(tmp_path))
    got = [(a["env"], a["number"], a["title"]) for a in anchors]
    assert got == [("definition", "1.1", "Even"), ("lemma", "1.2", None),
                   ("theorem", "1.3", "Main"), ("lemma", "A.1", None)]
    assert size and size[1] > 700
    lemma = anchors[1]
    assert lemma["statement"].startswith("Lemma 1.2.") and "plus two" in lemma["statement"]
    assert "Add two" not in lemma["statement"]          # the proof is not the statement
    assert lemma["begin"][0] == lemma["end"][0] and lemma["end"][2] > lemma["begin"][2]
    assert {a["found_by"] for a in anchors} == {"styled"}


@needs_tex
def test_regular_weight_and_small_caps_heads_are_found_at_paragraph_starts(tmp_path):
    anchors, _ = claims_from_pdf(_pdf(tmp_path, JOURNAL))
    assert [(a["env"], a["number"], a["found_by"]) for a in anchors] == [
        ("theorem", "1.1", "paragraph"), ("lemma", "1.2", "paragraph"),
        ("theorem", "1.3", "paragraph")]
    assert anchors[0]["statement"].startswith("Theorem 1.1 Suppose that every number")
    assert anchors[1]["statement"].startswith("Lemma 1.2 Let a and b be even.")


@needs_tex
def test_check_names_the_statements_and_marks_them_approximate(tmp_path):
    root = _project(tmp_path, JOURNAL)
    run = _check(root, "--json")
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout)
    assert [c["number"] for c in out["claims"]] == ["Theorem 1.1", "Lemma 1.2", "Theorem 1.3"]
    assert any("starting a paragraph" in n for n in out["notes"])
    assert not [w for w in out["warnings"] if w["kind"] == "pdf-no-statements"]
    view = build_view(root, root / "paper.pdf", root / ".machinechecked", log=lambda m: None)
    index = write_view_site(view, root / ".machinechecked" / "site", None)
    assert {c["anchor"]["kind"] for c in index["claims"]} == {"approximate"}


@needs_tex
def test_check_says_when_no_statement_heading_is_recognised(tmp_path):
    """The issue's case: `check --json` printed `"claims": []` with no note and no warning."""
    root = _project(tmp_path, PROSE)
    run = _check(root, "--json")
    out = json.loads(run.stdout)
    assert out["claims"] == []
    assert NO_HEADINGS in out["notes"]
    assert {"kind": "pdf-no-statements", "message": NO_HEADINGS} in out["warnings"]
    text = _check(root).stdout.splitlines()
    assert f"warning: {NO_HEADINGS}" in text and f"note: {NO_HEADINGS}" not in text
    view = build_view(root, root / "paper.pdf", root / ".machinechecked", log=lambda m: None)
    index = write_view_site(view, root / ".machinechecked" / "site", None)
    assert NO_HEADINGS in index["notes"]


@needs_tex
def test_an_unbuilt_project_never_reads_as_proved(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    pdf = _pdf(tmp_path)
    (root / "paper.pdf").write_bytes(pdf.read_bytes())
    (root / "formalization.yaml").write_text(
        'version: "v0.4"\nreview:\n  status: "self-assessed"\nalignment:\n  statements:\n'
        '    - source: "Theorem 1.3"\n      lean: "Proj.main"\n'
        '    - source: "Lemma A.1"\n      lean: "Proj.zero_even"\n')
    view = build_view(root, root / "paper.pdf", root / ".machinechecked", log=lambda m: None)
    c = {c["number"]: c for c in view["body"]["claims"]}
    assert c["Theorem 1.3"]["status"] == "linked: Lean not checked (the project is not built)"
    assert [l["source"] for l in c["Theorem 1.3"]["links"]] == ["formalization.yaml"]
    assert c["Lemma 1.2"]["status"] == "not linked"
    # An appendix statement ("Lemma A.1") is found, and formalization.yaml links it.
    assert [l["name"] for l in c["Lemma A.1"]["links"]] == ["Proj.zero_even"]
    assert any("not built" in n for n in view["body"]["notes"])


@needs_tex
def test_the_working_directory_is_ignored_and_holds_the_paper_once(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper.pdf").write_bytes(_pdf(tmp_path).read_bytes())
    out = root / ".machinechecked"
    build_view(root, root / "paper.pdf", out, log=lambda m: None)
    # Git ignores it, as Lake's .lake/: a `git add -A` cannot commit the paper or the reader.
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root,
                            capture_output=True, text=True, check=True).stdout
    assert ".machinechecked" not in status
    # The snapshot of a paper that is only a PDF is that file, stored once.
    snap = out / "sources" / "P"
    assert [p.name for p in snap.iterdir()] == ["paper.pdf"]
    assert (snap / "paper.pdf").stat().st_ino == (root / "paper.pdf").stat().st_ino


def test_a_working_directory_git_already_tracks_is_left_alone(tmp_path):
    from prooflens.util import prepare_work_dir
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    d = tmp_path / ".machinechecked"
    d.mkdir()
    (d / "kept.json").write_text("{}")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    prepare_work_dir(d)
    assert not (d / ".gitignore").exists()
