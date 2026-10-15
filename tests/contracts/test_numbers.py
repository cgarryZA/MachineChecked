"""The number and source file each anchor records, in the cases that defeat a naive reading."""

from conftest import needs_tex
from prooflens.sources import Snapshot
from prooflens.tex import anchors_for

DOC = r"""\documentclass{article}
\usepackage{amsmath,amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem*{theorem*}{Theorem}
\counterwithin{equation}{section}
\begin{document}
\section{One}
\input{parts/one}
\end{document}
"""

ONE = r"""\begin{theorem}\label{thm:a}
First.
\end{theorem}

\paragraph{A run-in heading}
\begin{theorem}\label{thm:b}
After a run-in heading.
\end{theorem}

\begin{theorem*}
Unnumbered.
\end{theorem*}

\begin{equation}\label{eq:x} x = 1 \end{equation}
Text.
\begin{equation}\label{eq:y} y = 2 \end{equation}
\begin{equation}\label{eq:z} z = 3 \end{equation}
\begin{lemma}\label{lem:c}
Lemma 1.3, right after equation (1.3).
\end{lemma}
"""


@needs_tex
def test_numbers_and_files(tmp_path):
    src = tmp_path / "src"
    (src / "parts").mkdir(parents=True)
    (src / "main.tex").write_text(DOC)
    (src / "parts" / "one.tex").write_text(ONE)
    snap = Snapshot("P", src, "path", None, "latex", "main.tex", None)
    anchors = anchors_for(snap, tmp_path / "work", ["theorem", "lemma", "theorem*"])["anchors"]
    got = {(a.env, a.labels[0][0] if a.labels else None): a for a in anchors}
    assert got[("theorem", "thm:a")].number == "1.1"
    assert got[("theorem", "thm:b")].number == "1.2"      # not the previous label's 1.1
    assert got[("theorem*", None)].number is None         # unnumbered
    assert got[("lemma", "lem:c")].number == "1.3"       # equal to the previous label (1.3)
    # The file as \input gave it, with its directory, and the statement read from it.
    assert {a.file for a in anchors} == {"parts/one.tex"}
    assert got[("theorem", "thm:b")].statement.startswith("\\label{thm:b}")
