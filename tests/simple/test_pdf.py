"""A paper that is only a PDF, in a project that may not be built."""

import subprocess

from conftest import needs_tex
from prooflens.pdfclaims import claims_from_pdf
from prooflens.simple import build_view

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


def _pdf(tmp_path):
    (tmp_path / "paper.tex").write_text(DOC)
    subprocess.run(["latexmk", "-norc", "-pdf", "-interaction=nonstopmode", "paper.tex"],
                   cwd=tmp_path, capture_output=True, check=True, timeout=300)
    return tmp_path / "paper.pdf"


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
