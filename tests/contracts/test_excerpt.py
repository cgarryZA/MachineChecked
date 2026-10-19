"""Display excerpts: a passage is typeset from its pinned source whole, under the definitions in
effect at it and with the numbers the compiled paper prints, or not at all (docs/SOURCE_REGIONS.md).
"""

import json
from pathlib import Path

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import excerpt as ex
from prooflens.sources import Snapshot
from prooflens.tex import anchors_for

MAIN = r"""\documentclass{article}
\usepackage{amsmath,amssymb,amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{proposition}[theorem]{Proposition}
\counterwithin{equation}{section}
\newcommand{\cost}{A}
\input{macros}
\begin{document}
\section{Results}
\begin{theorem}[Energy bound]\label{thm:energy}
Let $u \in \R^d$ and let $\norm{u}$ be its length. % a remark the reader does not print
Then, as in~\cite[Lemma~3]{lit}, the energy satisfies
$\energy(u) \le \cost\,\norm{u}^2$ and Proposition~\ref{prop:next} applies.
\end{theorem}

\begin{equation}\label{eq:energy}
  \energy(u) \le \cost
\end{equation}
holds by~\cite{lit}. Proposition~\ref{prop:next} states more.

\begin{proposition}\label{prop:next}
For every $u$, \eqref{eq:energy} is sharp.
\end{proposition}
\renewcommand{\cost}{C}
\begin{theorem}\label{thm:later}
Here $\cost > 0$.
\end{theorem}
\begin{thebibliography}{9}
\bibitem{lit} A. Author, \emph{A synthetic reference}, 2020.
\end{thebibliography}
\end{document}
"""

MACROS = r"""\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\lVert #1\rVert}
\DeclareMathOperator{\energy}{E}
\renewcommand{\cost}{B}
"""


def snapshot(tmp_path, main=MAIN, macros=MACROS):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.tex").write_text(main)
    (src / "macros.tex").write_text(macros)
    return Snapshot("P", src, "path", "rev-1", "latex", "main.tex", None)


def line_of(text, needle):
    return text.split("\n").index(needle) + 1


def texts(nodes):
    return "".join(n.get("text", "") for n in nodes)


@needs_tex
def test_a_theorem_is_typeset_whole_from_its_source(tmp_path):
    snap = snapshot(tmp_path)
    t = anchors_for(snap, tmp_path / "work", ["theorem", "proposition"])
    aux = ex.read_aux(t["cwd"], "main")
    anchors = {a.label: a.to_json() for a in t["anchors"]}
    rec = ex.excerpt_for(snap.dir, "main.tex", aux, "rev-1", {"theorem", "proposition"},
                         anchors["thm:energy"], None, None)
    assert rec["ready"], rec["reasons"]
    # The definitions in effect at the passage: \cost as redefined in macros.tex, not as first
    # defined, and \energy as an operator.
    assert rec["macros"]["\\cost"]["body"] == "B"
    assert rec["macros"]["\\energy"]["body"] == "\\operatorname{E}"
    assert set(rec["macros"]) == {"\\R", "\\norm", "\\cost", "\\energy"}
    para = rec["blocks"][0]["p"]
    maths = [n["math"] for n in para if "math" in n]
    assert maths == ["u \\in \\R^d", "\\norm{u}", "\\energy(u) \\le \\cost\\,\\norm{u}^2"]
    # A comment ends with its line: the next sentence is kept.
    assert "be its length. Then, as in" in texts(para)
    cite = next(n for n in para if "cite" in n)
    assert cite == {"cite": ["1"], "note": "Lemma\u00a03", "keys": ["lit"]}
    ref = next(n for n in para if "ref" in n)
    assert ref["ref"] == "1.2" and ref["key"] == "prop:next"
    assert rec["refs"] == {"prop:next": "1.2"} and rec["cites"] == {"lit": "1"}
    assert rec["fingerprint"].startswith("tex-excerpt-v1:")
    assert rec["body_style"] == "italic", "a plain theorem's body is printed in italics"
    # A later theorem sees the later definition.
    later = ex.excerpt_for(snap.dir, "main.tex", aux, "rev-1", {"theorem"}, anchors["thm:later"],
                           None, None)
    assert later["ready"] and later["macros"]["\\cost"]["body"] == "C"
    assert later["fingerprint"] != rec["fingerprint"]


@needs_tex
def test_a_labelled_equation_with_prose_ends_where_its_selector_ends(tmp_path):
    snap = snapshot(tmp_path)
    t = anchors_for(snap, tmp_path / "work", ["theorem", "proposition"])
    aux = ex.read_aux(t["cwd"], "main")
    start = line_of(MAIN, "\\begin{equation}\\label{eq:energy}")
    last = MAIN.split("\n")[start + 2]
    col = last.index(" Proposition") + 1
    sel = {"location": f"main.tex:{start}", "end_line": start + 3, "end_column": col}
    rec = ex.excerpt_for(snap.dir, "main.tex", aux, "rev-1", {"theorem"}, None, None, sel)
    assert rec["ready"], rec["reasons"]
    assert rec["text"].endswith("holds by~\\cite{lit}.")
    assert [list(b) for b in rec["blocks"]] == [["math", "display"], ["p"]]
    assert rec["blocks"][0]["math"] == "\\begin{equation*} \\energy(u) \\le \\cost \\tag{1.1}\\end{equation*}"
    assert "Proposition" not in json.dumps(rec["blocks"]), "the next claim is not included"
    # The same equation selected by its label.
    by_label = ex.excerpt_for(snap.dir, "main.tex", aux, "rev-1", {"theorem"}, None, None,
                              {"label": "eq:energy"})
    assert by_label["ready"] and by_label["blocks"] == rec["blocks"][:1]
    # References inside the proposition resolve to the printed equation number.
    prop = ex.excerpt_for(snap.dir, "main.tex", aux, "rev-1", {"proposition"}, None, None,
                          {"label": "prop:next"})
    assert prop["ready"], prop["reasons"]
    assert {"ref": "(1.1)", "key": "eq:energy"} in prop["blocks"][0]["p"]


# The fallbacks need no compilation: the .aux is given.
AUX = {"labels": {"thm:x": "1.1", "eq:x": "1.1"}, "cites": {"lit": "1"}}


def one(tmp_path, body, preamble="", aux=AUX, extra=None, selector=None):
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    doc = ("\\documentclass{article}\n\\usepackage{amsmath}\n\\newtheorem{theorem}{Theorem}\n"
           + preamble + "\\begin{document}\n\\begin{theorem}\\label{thm:x}\n" + body
           + "\n\\end{theorem}\n\\end{document}\n")
    (src / "main.tex").write_text(doc)
    for name, text in (extra or {}).items():
        (src / name).write_text(text)
    anchor = {"file": "main.tex", "line": doc.split("\n").index("\\begin{theorem}\\label{thm:x}") + 1,
              "env": "theorem"}
    return ex.excerpt_for(src, "main.tex", aux, "rev", {"theorem"}, None if selector else anchor,
                          None, selector)


def test_a_plain_passage_is_ready(tmp_path):
    rec = one(tmp_path, "For every $n$, \\emph{the} sum $\\sum_i i$ is finite.\n% gone\nNext sentence.")
    assert rec["ready"], rec["reasons"]
    assert texts(rec["blocks"][0]["p"]).endswith("is finite. Next sentence.")


@pytest.mark.parametrize("body, preamble, why", [
    ("Here \\foo{x} holds.", "", "the text command \\foo is not supported"),
    ("As in \\cite{nowhere}.", "", "the citation nowhere is not resolved"),
    ("By Theorem~\\ref{thm:none}.", "", "the reference thm:none is not resolved"),
    ("$x \\le \\eqref{eq:none}$", "", "the reference eq:none is not resolved"),
    ("\\begin{itemize}\\item a\n", "", "mismatched source environment"),
    ("\\begin{itemize}\\item a\\end{enumerate}", "", "mismatched"),
    ("\\begin{tikzpicture}x\\end{tikzpicture}", "", "the environment tikzpicture is not supported"),
    ("\\begin{equation}x\\end{equation}", "", "numbered equation row without a label"),
    ("$\\cost$", "{\\newcommand{\\cost}{A}}\n", "defined inside a group"),
    ("$\\cost$", "\\newcommand{\\cost}[1][d]{#1}\n", "optional argument"),
    ("$\\cost$", "\\let\\cost\\alpha\n", "\\let"),
    ("$\\cost$", "\\iffalse\\newcommand{\\cost}{A}\\fi\n", "conditional"),
    ("$\\cost$", "\\def\\cost#1.{#1}\n", "delimited parameters"),
    ("Text \\textbf{\\cost} here.", "\\newcommand{\\cost}{A}\n", "the paper defines \\cost, used in the text"),
    ("\\newcommand{\\x}{y}$\\x$", "", "the passage defines a macro"),
    ("a $b", "", "mathematics without its closing $"),
    ("a < b", "", "the character < prints differently"),
])
def test_anything_not_reproduced_falls_back_whole(tmp_path, body, preamble, why):
    rec = one(tmp_path, body, preamble)
    assert rec["ready"] is False and rec["blocks"] is None
    assert any(why in r for r in rec["reasons"]), rec["reasons"]


def test_a_redefinition_is_used_as_in_effect_at_the_passage(tmp_path):
    rec = one(tmp_path, "$\\cost$", "\\newcommand{\\cost}{A}\n\\input{more}\n",
              extra={"more.tex": "\\renewcommand{\\cost}{B}\n"})
    assert rec["ready"] and rec["macros"]["\\cost"]["body"] == "B"
    # A definition made after the passage does not apply to it.
    src = tmp_path / "src"
    edit(src / "main.tex", "\\end{document}", "\\renewcommand{\\cost}{Z}\n\\end{document}")
    rec2 = ex.excerpt_for(src, "main.tex", AUX, "rev", {"theorem"}, None, None, {"label": "thm:x"})
    assert rec2["ready"] and rec2["macros"]["\\cost"]["body"] == "B"


def test_a_passage_outside_the_compiled_document_has_no_context(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text("\\documentclass{article}\n\\begin{document}\nText.\n\\end{document}\n")
    (src / "unused.tex").write_text("Let $x$ be given.\n")
    rec = ex.excerpt_for(src, "main.tex", AUX, "rev", set(), None, None,
                         {"location": "unused.tex:1"})
    assert rec["ready"] is False
    assert "not part of the compiled document" in rec["reasons"][0]


@pytest.mark.parametrize("selector, why", [
    ({"label": "eq:twice"}, "occurs 2 times"),
    ({"label": "eq:absent"}, "occurs 0 times"),
    ({"location": "main.tex:6", "end_line": 5}, "before the start"),
    ({"location": "main.tex:6", "end_line": 6, "end_column": 1}, "empty or reversed"),
    ({"lines": [1, 2]}, "an excerpt selector is"),
])
def test_bad_selectors_are_refused(tmp_path, selector, why):
    rec = one(tmp_path, "\\begin{equation*}\\label{eq:twice}x\\end{equation*}\n"
              "\\begin{equation*}\\label{eq:twice}y\\end{equation*}", selector=selector)
    assert rec["ready"] is False and any(why in r for r in rec["reasons"]), rec["reasons"]


def test_numbered_rows_print_their_recorded_numbers(tmp_path):
    aux = {"labels": {"thm:x": "1", "eq:a": "3", "eq:b": "4"}, "cites": {}}
    rec = one(tmp_path, "\\begin{align}\na &= b \\label{eq:a}\\\\\nc &= d \\nonumber\\\\\n"
              "e &= f \\label{eq:b}\n\\end{align}", aux=aux)
    assert rec["ready"], rec["reasons"]
    assert rec["blocks"][0]["math"] == ("\\begin{align*} a &= b \\tag{3}\\\\ c &= d \\\\ "
                                        "e &= f \\tag{4}\\end{align*}")
    rec = one(tmp_path, "\\begin{align}a &= b \\label{eq:a}\\\\ c &= d\\end{align}", aux=aux)
    assert rec["ready"] is False


def test_lists_and_empty_commands(tmp_path):
    rec = one(tmp_path, "\\lean{X.y}Either\n\\begin{itemize}\n\\item[(i)] $a$, or\n"
              "\\item[(ii)] $b$.\n\\end{itemize}", "\\newcommand{\\lean}[1]{}\n")
    assert rec["ready"], rec["reasons"]
    assert rec["blocks"][1]["list"] == "itemize"
    assert [i["label"] for i in rec["blocks"][1]["items"]] == ["(i)", "(ii)"]
    assert texts(rec["blocks"][0]["p"]) == "Either"


@needs_lean
@needs_tex
def test_excerpts_are_display_only_and_kept_with_their_release(toy):
    from prooflens import pipeline
    before, body0, cfg = build(toy)
    (toy / "display.json").write_text(json.dumps({"claims": {
        "T:thm:triangle": {"excerpt": {"label": "eq:gauss"}},
        "T:rem:history": {"excerpt": False}}}))
    edit(toy / "machinechecked.toml", 'statement_authors = ["statement-author"]',
         'statement_authors = ["statement-author"]\ndisplay = "display.json"')
    after, body1, cfg = build(toy, reuse_lean=True, release="r1")
    assert body1["assessment"] == body0["assessment"]
    c = {x["id"]: x for x in after["claims"]}
    chunk = lambda cid, site=cfg.out_dir / "site": json.loads(  # noqa: E731
        (site / "data/claims" / c[cid]["file"]).read_text())
    tri, add = chunk("T:thm:triangle"), chunk("T:thm:even-add")
    assert tri["excerpt"]["selector"] == {"label": "eq:gauss"} and tri["excerpt"]["ready"]
    assert tri["excerpt"]["blocks"][0]["math"].endswith("\\tag{1}\\end{equation*}")
    assert chunk("T:rem:history")["excerpt"] is None
    assert chunk("T:def:even")["excerpt"]["body_style"] == "upright"
    assert add["excerpt"]["ready"] and add["excerpt"]["revision"] is None
    # The excerpt's fingerprint is its own; the audited source hash is unchanged.
    assert add["source_sha256"] == next(x for x in body0["inventory"]["claims"]
                                        if x["id"] == "T:thm:even-add")["source_sha256"]
    # Rebuilding the release later reads its stored excerpt, not the changed paper.
    edit(toy / "paper" / "toy.tex", "then $a + b$ is even.", "then $a + b$ is even (changed).")
    (toy / "display.json").write_text("{}")
    pipeline.rebuild_site(cfg, release="r1")
    assert chunk("T:thm:even-add")["excerpt"] == add["excerpt"]
    assert chunk("T:thm:triangle")["excerpt"] == tri["excerpt"]
