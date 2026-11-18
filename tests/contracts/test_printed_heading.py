"""#575: a statement's number is the heading its `\\newtheorem` prints with its counter
(`\\newtheorem{standing}{S.}`: "S. 1"), with the environment kept as its kind. An inventory entry
numbered as printed matches; one numbered after the environment's name ("Standing 1"), as an
earlier version numbered it, still matches, with a warning. Synthetic sources."""

import json
import subprocess
import sys
from types import SimpleNamespace

from conftest import needs_tex
from prooflens.assess import Assessor, match_anchor
from prooflens.tex import printed_number, theorem_headings

PREAMBLE = (r"\newtheorem{standing}{S.}" "\n" r"\newtheorem{thm}{Theorem}[section]" "\n"
            r"\newtheorem{lem}[thm]{Lemma}" "\n" r"\newtheorem*{named}{Main~Theorem}" "\n"
            r"\newtheorem{odd}{\textbf{Odd}}" "\n" r"% \newtheorem{gone}{Gone}" "\n")


def test_the_heading_each_environment_prints(tmp_path):
    (tmp_path / "paper.tex").write_text(PREAMBLE)
    assert theorem_headings(tmp_path) == {"standing": "S.", "thm": "Theorem", "lem": "Lemma",
                                          "named": "Main Theorem"}
    assert printed_number({"env": "standing", "name": "S.", "number": "1"}) == "S. 1"
    assert printed_number({"env": "standing", "number": "1"}) == "Standing 1"
    assert printed_number({"env": "named", "name": "Main Theorem", "number": None}) == \
        "Main Theorem"


ANCHOR = {"id": 1, "env": "standing", "name": "S.", "number": "1", "label": None,
          "file": "paper.tex", "line": 3, "source_sha256": "a" * 64}


def claim(number):
    return {"id": "P:s1", "paper": "P", "kind": "standing", "number": number,
            "location": "paper.tex", "source_sha256": "a" * 64, "scope": "expository",
            "scope_reviewed": True, "clauses": []}


def test_an_entry_matches_as_printed_and_in_the_old_form_with_a_warning():
    assert match_anchor(claim("S. 1"), [ANCHOR]) is ANCHOR
    assert match_anchor(claim("Standing 1"), [ANCHOR]) is ANCHOR
    assert match_anchor(claim("S. 2"), [ANCHOR]) is None
    cfg = SimpleNamespace(statement_authors=[], lean_root=None, papers=[SimpleNamespace(id="P")])
    tex = {"P": {"mode": "latex", "envs": ["standing"], "anchors": [ANCHOR], "regions": {}}}
    for number, warned in (("S. 1", False), ("Standing 1", True)):
        out = Assessor(cfg, {"claims": [claim(number)]}, {"specs": {}, "decls": {}, "proofs": {},
                       "defs": {}, "layering": []}, tex, [], []).run()
        codes = [f["code"] for f in out["findings"]]
        assert "inventory-gap" not in codes and "inventory-unanchored" not in codes
        found = [f for f in out["findings"] if f["code"] == "inventory-number-form"]
        assert bool(found) is warned
    assert "the paper prints 'S. 1'" in found[0]["message"]


PAPER = r"""\documentclass{article}
\usepackage{amsthm}
""" + PREAMBLE + r"""\begin{document}
\section{Results}
\begin{standing}\label{st:pos} The number $n$ is positive. \end{standing}
\begin{thm}\label{thm:one} One is odd. \end{thm}
\end{document}
"""


@needs_tex
def test_check_numbers_a_statement_as_printed(tmp_path):
    """The issue's reproduction: `check --json` named the statement "Standing 1"."""
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper" / "paper.tex").write_text(PAPER, encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=root,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    got = {c["id"]: c["number"] for c in out["claims"]}
    assert got["P:st:pos"] == "S. 1" and got["P:thm:one"] == "Theorem 1.1"
