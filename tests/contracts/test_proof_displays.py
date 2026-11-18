"""#573: the numbered displays of a proof. Each labelled, numbered row of a display of several
rows is a step of its own, with its own lines; a display opened by a macro defined as a display
environment is recognised; and a numbered display still left out is said in `notes`, with its
label, its place and why. A display with one label reads as before. Synthetic sources."""

import json
import subprocess
import sys

from conftest import needs_tex
from prooflens.steps import display_macros, step_claims

THM = {"id": "P:thm:sum", "label": "thm:sum", "location": "paper.tex", "line": 2,
       "number": "Theorem 1.1", "kind": "theorem"}
SOURCE = r"""\def\beq{\begin{equation}}\def\eeq{\end{equation}}
\begin{theorem}\label{thm:sum} If a and b are odd, a + b is even. \end{theorem}
\begin{proof}
\begin{align}
  a + b &= 2j + 2k + 2 \label{eq:s1}\\
        &= 2(j + k + 1). \label{eq:s2}
\end{align}
\beq\label{eq:s3} 2\max(a,b) \ge a + b. \eeq
\begin{equation}\label{eq:s4} \max(a, b) \le a + b. \end{equation}
\begin{equation}\label{eq:s5}\label{eq:s6} x = y. \end{equation}
\begin{align} u &= v \label{eq:s7} \\ v &= w \label{eq:s8} \end{align}
\end{proof}
"""
NUMBERS = {"eq:s1": "1", "eq:s2": "2", "eq:s3": "3", "eq:s4": "4", "eq:s5": "5", "eq:s6": "5",
           "eq:s7": "6", "eq:s8": "7"}


def steps_of(tmp_path, source=SOURCE, numbers=NUMBERS):
    (tmp_path / "paper.tex").write_text(source, encoding="utf-8")
    notes = []
    return step_claims("P", [THM], tmp_path, ["paper.tex"], numbers, notes), notes


def test_rows_and_macro_displays_are_steps_and_the_rest_are_said(tmp_path):
    found, notes = steps_of(tmp_path)
    got = {c["label"]: (c["location"], c["source_region"]["end_line"]) for c in found}
    assert got == {"eq:s1": ("paper.tex:5", 5), "eq:s2": ("paper.tex:6", 6),
                   "eq:s3": ("paper.tex:8", 8), "eq:s4": ("paper.tex:9", 9)}
    assert all(c["parent"] == "P:thm:sum" for c in found)
    # A row is typeset inside its environment; a macro display with the macros written out.
    s1 = next(c for c in found if c["label"] == "eq:s1")
    assert s1["statement_tex"].startswith("\\begin{align}\n") and \
        s1["statement_tex"].endswith("\n\\end{align}")
    s3 = next(c for c in found if c["label"] == "eq:s3")
    assert s3["statement_tex"].startswith("\\begin{equation}\\label{eq:s3}")
    assert notes == [
        "paper.tex:10: the numbered display eq:s5, eq:s6 in a proof is not listed as a step: it "
        "is one equation display, with one number, and it has several labels",
        "paper.tex:11: the numbered display eq:s7 in a proof is not listed as a step: its row "
        "shares a line with another labelled row, so it has no lines of its own",
        "paper.tex:11: the numbered display eq:s8 in a proof is not listed as a step: its row "
        "shares a line with another labelled row, so it has no lines of its own"]


def test_a_row_is_pinned_by_its_own_lines(tmp_path):
    found, _ = steps_of(tmp_path)
    from prooflens.source_regions import extract
    for c in found:
        rec = extract(tmp_path, {"location": c["location"], "source_region": c["source_region"]})
        assert rec.sha256 == c["source_sha256"], c["label"]
    # Two rows, two pins.
    assert len({c["source_sha256"] for c in found}) == 4


def test_a_display_with_one_label_reads_as_before(tmp_path):
    source = ("\\begin{theorem}\\label{thm:sum} x \\end{theorem}\n\\begin{theorem} y "
              "\\end{theorem}\n\\begin{proof}\n\\begin{align}\n a &= b \\nonumber \\\\\n"
              "   &= c \\label{eq:one}\n\\end{align}\n\\end{proof}\n")
    found, notes = steps_of(tmp_path, source, {"eq:one": "1"})
    (c,) = found
    # The whole display, as a display: its pin is the one an earlier version made.
    assert c["location"] == "paper.tex:4" and c["source_region"]["end_line"] == 7
    assert c["statement_tex"] == "\n".join(source.split("\n")[3:7])
    assert notes == []
    # A label with no printed number is said.
    found, notes = steps_of(tmp_path, source, {})
    assert found == [] and notes == [
        "paper.tex:4: the numbered display eq:one in a proof is not listed as a step: its label "
        "has no printed number"]


def test_the_macros_of_a_display():
    assert display_macros([r"\def\beq{\begin{equation}}", r"\newcommand{\eeq}{\end{equation}}",
                           r"\newcommand\ba{\begin{align}} % \def\x{\begin{gather}}"]) == {
        "beq": ("begin", "equation"), "eeq": ("end", "equation"), "ba": ("begin", "align")}


PAPER = r"""\documentclass{article}
\usepackage{amsthm,amsmath}
\newtheorem{theorem}{Theorem}[section]
\def\beq{\begin{equation}}\def\eeq{\end{equation}}
\begin{document}
\section{Results}
\begin{theorem}\label{thm:sum} If $a$ and $b$ are odd, $a + b$ is even. \end{theorem}
\begin{proof}
\begin{align}
  a + b &= 2j + 2k + 2 \label{eq:s1}\\
        &= 2(j + k + 1). \label{eq:s2}
\end{align}
\beq\label{eq:s3} 2\max(a,b) \ge a + b. \eeq
\begin{equation}\label{eq:s4} \max(a, b) \le a + b. \end{equation}
\begin{align} u &= v \label{eq:s5} \\ v &= w \label{eq:s6} \end{align}
\end{proof}
\end{document}
"""


@needs_tex
def test_check_lists_every_row_and_says_what_it_leaves_out(tmp_path):
    """The issue's reproduction, compiled: `check --json` listed only eq:s4, with no note."""
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper" / "paper.tex").write_text(PAPER, encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=root,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    eqs = [c["number"] for c in out["claims"] if c.get("unit") == "proof-equation"]
    assert eqs == ["Equation (1)", "Equation (2)", "Equation (3)", "Equation (4)"]
    # Two labelled rows on one line have no lines of their own: each is said.
    assert sum("shares a line with another labelled row" in n for n in out["notes"]) == 2
