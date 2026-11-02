"""The semantic summary (#129) of a zero-configuration audit built with Lean, on the synthetic
project tests/fixtures/coverage with a notation record and a proof equation added: `check`,
`check --json`, the site `build --site` writes and its claim rows agree on one summary, with
explicit units; a declaration linked twice counts once; and the readings change no status."""

import json
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, needs_lean, needs_tex

SRC = ROOT / "tests" / "fixtures" / "coverage"
PAPER = "paper/main.tex"
QUESTION = "Does 'number' mean a natural number or an integer?"
MORE = r"""
\begin{notation}\label{not:even}
We write $E$ for the set of even natural numbers.
\end{notation}

\begin{theorem}\label{thm:sum}
The sum of two even natural numbers is even.
\end{theorem}
\begin{proof}
Write the numbers as $2a$ and $2b$. Then
\begin{equation}\label{eq:sum}
2a + 2b = 2(a + b).
\end{equation}
\end{proof}

\end{document}
"""


def mc(root, *args):
    return subprocess.run([sys.executable, "-m", "prooflens.cli", *args], cwd=root,
                          capture_output=True, text=True, timeout=1800)


def write_links(root, pins=None, readings=True):
    entries = {
        # The same declaration twice: one link.
        "thm:two": {"lean": ["Cover.even_add", "Cover.even_add"], "coverage": "full",
                    "basis": "direct", "by": "A. Auditor"},
        "thm:four": {"lean": ["Cover.even_add"], "coverage": "full",
                     "basis": "reviewed_composition", "argument": "Apply it three times.",
                     "by": "A. Auditor"},
        "thm:three": {"lean": ["Cover.three_even"], "coverage": "full", "basis": "checked_bridge",
                      "bridge": {"theorem": "Cover.three_even", "target": "Cover.Spec.three_even",
                                 **(pins or {})}, "by": "A. Auditor"},
        "thm:double": {"lean": ["Cover.even_two_mul"], "coverage": "unresolved",
                       "question": QUESTION, "by": "A. Auditor"},
        "not:even": {"lean": ["Cover.Even"]},
        "eq:sum": {"lean": ["Cover.even_add"], "coverage": "partial", "basis": "direct",
                   "by": "A. Auditor"}}
    if not readings:
        # The same links with no reading.
        entries = {k: {"lean": e["lean"]} for k, e in entries.items()}
    (root / "machinechecked.links.json").write_text(json.dumps(
        {"version": 1, "author": "A. Auditor", "papers": {PAPER: entries}}))


@pytest.fixture
def cover(tmp_path):
    root = tmp_path / "coverage"
    shutil.copytree(SRC, root)
    tex = root / PAPER
    tex.write_text(tex.read_text().replace(
        r"\newtheorem{theorem}{Theorem}", "\\newtheorem{theorem}{Theorem}\n"
        "\\newtheorem{notation}{Notation}").replace("\\end{document}\n", MORE))
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


@needs_lean
@needs_tex
def test_check_json_build_and_site_agree_on_one_summary(cover, tmp_path):
    write_links(cover, readings=False)
    plain = json.loads(mc(cover, "check", "--json").stdout)
    write_links(cover)
    first = json.loads(mc(cover, "check", "--json").stdout)
    three = next(c for c in first["claims"] if c["number"] == "Theorem 3")
    now = three["correspondence"]["bridge"]["current"]
    write_links(cover, {"target_fingerprint": now["target_fingerprint"],
                        "source_sha256": now["source_sha256"]})
    r = mc(cover, "check", "--json")
    out = json.loads(r.stdout)
    s = out["semantic"]

    # The readings change no status.
    def statuses(doc):
        return {c["id"]: c["status_code"] for c in doc["claims"]}
    assert statuses(out) == statuses(plain)
    assert {c["id"] for c in out["claims"]} == {c["id"] for c in plain["claims"]}

    p = s["papers"]["P"]
    assert p["inventory"]["statements"] == {"records": 5, "linked": 4, "links": 4,
                                            "declarations": 3}
    assert p["inventory"]["notation"] == {"records": 1, "linked": 1, "links": 1,
                                          "declarations": 1}
    assert p["inventory"]["proof_steps"] == {"records": 1, "linked": 1, "links": 1,
                                             "declarations": 1}
    assert p["inventory"]["proof_equations"] == 1
    cov = p["coverage"]["audit"]
    assert {k: v for k, v in cov["statements"].items() if v} == {"full": 3, "unresolved": 1,
                                                                 "not_assessed": 1}
    assert {k: v for k, v in cov["proof_steps"].items() if v} == {"partial": 1}
    assert {k: v for k, v in p["basis"]["audit"]["statements"].items() if v} == {
        "direct": 1, "reviewed_composition": 1, "checked_bridge": 1, "unspecified": 1}
    assert s["audit"]["author"] == "A. Auditor" and s["sets"][0]["by"] == ["A. Auditor"]
    double = next(c for c in out["claims"] if c["number"] == "Theorem 4")
    assert double["semantic"]["readings"][0]["question"] == QUESTION

    # `check` prints it in short, with its units and without a percentage.
    text = mc(cover, "check").stdout
    assert "semantic summary of paper P (the audit's readings):" in text
    assert "  5 statements, 4 linked to 3 declarations" in text
    assert "    correspondence: every clause (3); unresolved (1); not assessed (1)" in text
    assert "%" not in text
    # As docs/GETTING_STARTED.md shows it.
    assert """semantic summary of paper P (the audit's readings):
  5 statements, 4 linked to 3 declarations
    correspondence: every clause (3); unresolved (1); not assessed (1)
    basis: in one Lean statement (1); by an argument combining Lean results (1); through a checked bridge (1); basis not recorded (1)
    reviews: not reviewed (5)
    findings: open questions (1)
  1 notation record, 1 linked to 1 declaration
    correspondence: not assessed (1)
    reviews: not reviewed (1)
  1 proof step, 1 linked to 1 declaration
    correspondence: part of the claim (1)
    basis: in one Lean statement (1)
    reviews: printed step not reviewed (1)
""" in text

    # The site `build --site` writes carries the same summary, and each claim row its facts.
    site = tmp_path / "public"
    b = mc(cover, "build", "--site", str(site))
    assert b.returncode == 0, b.stderr
    assert "semantic summary of paper P (the audit's readings):" in b.stdout
    index = json.loads((site / "data" / "index.json").read_text())
    assert index["semantic"] == s
    assert {c["id"]: c["semantic"] for c in index["claims"]} == {
        c["id"]: c["semantic"] for c in out["claims"]}
