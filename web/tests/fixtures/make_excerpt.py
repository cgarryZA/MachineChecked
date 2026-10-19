"""Print synthetic display excerpts, as the engine writes them, for the reader tests: a complete
theorem (several pieces of mathematics, paper macros, a citation with a note, references, a
numbered display and prose after a comment), one whose mathematics KaTeX refuses, and one the
engine itself refuses. The compiled labels are given, so no TeX is needed.

    python3 web/tests/fixtures/make_excerpt.py > excerpts.json
"""

import json
import sys
import tempfile
from pathlib import Path

from prooflens.excerpt import excerpt_for

DOC = r"""\documentclass{article}
\usepackage{amsmath,amssymb}
\newtheorem{theorem}{Theorem}
\newcommand{\cost}{A}
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\lVert #1\rVert}
\renewcommand{\cost}{B}
\begin{document}
\begin{theorem}\label{thm:x}
%s
\end{theorem}
\end{document}
"""
AUX = {"labels": {"thm:x": "1.1", "eq:x": "1.1", "prop:y": "1.2"}, "cites": {"lit": "1"}}
BODIES = {
    "complete": "Let $u \\in \\R^d$ and $\\norm{u} \\le 1$. % not printed\n"
                "Then, as in~\\cite[Lemma~3]{lit},\n"
                "\\begin{equation}\\label{eq:x}\n  \\norm{u}^2 \\le \\cost\n\\end{equation}\n"
                "and Proposition~\\ref{prop:y} applies to \\eqref{eq:x}.",
    "katex-refuses": "Let $\\undefinedcommand u$ be given.",
    "engine-refuses": "Let $u$ be \\unknowncommand{given}.",
}

out = {}
with tempfile.TemporaryDirectory() as tmp:
    for name, body in BODIES.items():
        doc = DOC % body
        (Path(tmp) / "main.tex").write_text(doc)
        line = doc.split("\n").index("\\begin{theorem}\\label{thm:x}") + 1
        out[name] = excerpt_for(Path(tmp), "main.tex", AUX, "synthetic-revision", {"theorem"},
                                {"file": "main.tex", "line": line, "env": "theorem"}, None, None)
json.dump(out, sys.stdout)
