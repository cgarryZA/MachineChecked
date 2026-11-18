"""#572: the statement a proof proves. A proof whose optional argument names a statement, by its
label or its printed number, proves that one. An unnamed proof proves the statement before it,
unless that statement is an aside (a remark, an example) and the result before the aside has no
proof yet: either may then be the one proved, so the step's parent is left uncertain and the
candidates are named, in `check --json`, the compare packet and the reader's data. Remarks can
have proofs of their own. Synthetic sources."""

import json
import subprocess
import sys

import pytest

from conftest import needs_tex
from prooflens import steps
from prooflens.steps import PassageError, resolve_parent, select_passage, step_claims

THM = {"id": "P:thm:sum", "label": "thm:sum", "location": "paper.tex", "line": 1,
       "number": "Theorem 1.1", "kind": "theorem"}
REM = {"id": "P:remark-1.2", "label": None, "location": "paper.tex", "line": 2,
       "number": "Remark 1.2", "kind": "remark"}
EQ = "\\begin{equation}\\label{eq:last} \\max(a, b) \\le a + b. \\end{equation}\n"
SOURCES = {
    # The issue's reproduction: a remark between a theorem and an unnamed proof.
    "unnamed": "\\begin{proof}\nFinally\n" + EQ + "\\end{proof}\n",
    "by label": "\\begin{proof}[Proof of Theorem~\\ref{thm:sum}]\nFinally\n" + EQ
                + "\\end{proof}\n",
    "by number": "\\begin{proof}[Proof of Theorem 1.1]\nFinally\n" + EQ + "\\end{proof}\n",
}
HEAD = ("\\begin{theorem}\\label{thm:sum} If a and b are odd, a + b is even. \\end{theorem}\n"
        "\\begin{remark} The constant in Theorem~\\ref{thm:sum} is two. \\end{remark}\n")


def claims(tmp_path, body, statements=(THM, REM)):
    (tmp_path / "paper.tex").write_text(HEAD + body, encoding="utf-8")
    return step_claims("P", list(statements), tmp_path, ["paper.tex"], {"eq:last": "1"})


def test_an_unnamed_proof_after_a_remark_names_both_candidates(tmp_path):
    (c,) = claims(tmp_path, SOURCES["unnamed"])
    assert c["parent"] is None
    assert c["parent_candidates"] == ["P:thm:sum", "P:remark-1.2"]
    assert c["scope_note"] == ("a step of a proof whose statement is not certain: Theorem 1.1 or "
                               "Remark 1.2")


@pytest.mark.parametrize("how", ["by label", "by number"])
def test_a_proof_that_names_its_statement_proves_it(tmp_path, how):
    (c,) = claims(tmp_path, SOURCES[how])
    assert c["parent"] == "P:thm:sum" and "parent_candidates" not in c
    assert c["scope_note"] == "a step of the proof of Theorem 1.1"


def test_a_remark_with_its_own_proof_and_an_ordinary_proof_are_attached_quietly(tmp_path):
    # Theorem, its proof, a remark, the remark's proof.
    body = ("\\begin{theorem}\\label{thm:sum} Odd plus odd is even. \\end{theorem}\n"
            "\\begin{proof} Add. \\end{proof}\n"
            "\\begin{remark} Even plus even is even too. \\end{remark}\n"
            "\\begin{proof}\nIndeed\n" + EQ + "\\end{proof}\n")
    (tmp_path / "paper.tex").write_text(body, encoding="utf-8")
    rem = {**REM, "line": 3}
    (c,) = step_claims("P", [THM, rem], tmp_path, ["paper.tex"], {"eq:last": "1"})
    assert c["parent"] == "P:remark-1.2" and "parent_candidates" not in c
    # A theorem followed by its proof.
    (tmp_path / "paper.tex").write_text(HEAD.split("\n")[0] + "\n\\begin{proof}\n" + EQ
                                        + "\\end{proof}\n", encoding="utf-8")
    (c,) = step_claims("P", [THM], tmp_path, ["paper.tex"], {"eq:last": "1"})
    assert c["parent"] == "P:thm:sum" and "parent_candidates" not in c


def test_the_rule_on_statements_with_no_kind_and_several_asides():
    # Statements as `authoring.paper_steps` gives them: the kind is read from the number.
    thm = {k: v for k, v in THM.items() if k != "kind"}
    ex = {"id": "P:ex", "location": "paper.tex", "line": 3, "number": "Example 1.3"}
    rem = {k: v for k, v in REM.items() if k != "kind"}
    assert resolve_parent([thm, rem, ex], "paper.tex", 4, None) == (None, [thm, rem, ex])
    assert resolve_parent([thm, rem, ex], "paper.tex", 4, None, proof_lines=[2]) == (ex, [])
    # Only asides before it: the last of them.
    assert resolve_parent([rem, ex], "paper.tex", 4, None) == (ex, [])
    assert resolve_parent([thm], "paper.tex", 1, None) == (None, [])


def test_a_passage_of_such_a_proof_is_refused(tmp_path):
    (tmp_path / "paper.tex").write_text(HEAD + SOURCES["unnamed"], encoding="utf-8")
    with pytest.raises(PassageError, match="may prove Theorem 1.1 or Remark 1.2"):
        select_passage(tmp_path, "paper.tex", 4, 4, [THM, REM], [])
    (tmp_path / "paper.tex").write_text(HEAD + SOURCES["by label"], encoding="utf-8")
    assert select_passage(tmp_path, "paper.tex", 4, 4, [THM, REM], [])["parent"] == THM


def test_the_step_record_and_the_packet_name_the_candidates():
    rows = [{"id": "P:thm:sum", "number": "Theorem 1.1"}, {"id": "P:remark-1.2",
                                                           "number": "Remark 1.2"}]
    b = steps.block({"unit": "proof-equation"}, None, [], [], None, None, {}, candidates=rows)
    assert b["parent"] is None
    assert [c["id"] for c in b["parent_candidates"]] == ["P:thm:sum", "P:remark-1.2"]
    from prooflens.compare import passage_text
    text = passage_text({"claim": "P:eq:last", "number": "Equation (1)", "available": True,
                         "quality": "LaTeX source", "text": "x", "source": {}, "complete": True,
                         "step": {"parent": {}, "question": "Does the printed step hold?",
                                  "parent_candidates": rows}})
    assert text.startswith("A step of a proof whose statement is not certain: Theorem 1.1 or "
                           "Remark 1.2. Does the printed step hold?")


PAPER = (r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}[section]
\newtheorem{remark}[theorem]{Remark}
\begin{document}
\section{Results}
""" + HEAD.replace("\\begin{remark}", "\\begin{remark}\\label{rem:two}") + SOURCES["unnamed"]
         + "\\end{document}\n")


@needs_tex
def test_check_and_the_reader_leave_the_parent_uncertain(tmp_path):
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper" / "paper.tex").write_text(PAPER, encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=root,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    by = {c["number"]: c for c in out["claims"]}
    step = by["Equation (1.1)"] if "Equation (1.1)" in by else next(
        c for c in out["claims"] if c.get("unit") == "proof-equation")
    assert step["parent"] is None
    assert step["parent_candidates"] == [by["Theorem 1.1"]["id"], by["Remark 1.2"]["id"]]
    from prooflens.simple import build_view, write_view_site
    view = build_view(root, root / "paper" / "paper.tex", root / ".machinechecked",
                      log=lambda m: None)
    index = write_view_site(view, root / ".machinechecked" / "site", None)
    row = next(c for c in index["claims"] if c["id"] == step["id"])
    assert row["parent"] is None and row["parent_candidates"] == step["parent_candidates"]
    chunk = json.loads((root / ".machinechecked" / "site" / "data" / "claims"
                        / row["file"]).read_text())
    assert chunk["step"]["parent"] is None
    assert [c["number"] for c in chunk["step"]["parent_candidates"]] == ["Theorem 1.1",
                                                                         "Remark 1.2"]
