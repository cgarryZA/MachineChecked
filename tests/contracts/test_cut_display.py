"""#741: a proof step whose pinned lines begin or end inside a display (a row of an `align`) is
read with the whole display as its passage and its own lines marked (`states`), at the read
stage, before the reading is locked: the rows it depends on are not cut away. A step whose
lines hold whole environments reads as before."""

import json

from conftest import edit, needs_lean, needs_tex
from prooflens.source_regions import SCHEME, collect, extract
from prooflens.steps import step_texts

ALIGN = ("\\begin{proof}\n\\begin{align}\n  x &= a + b \\label{eq:one} \\\\\n"
         "  y &= x + c \\label{eq:two}\n\\end{align}\n\\end{proof}\n")


def pinned(root, cid, line, scope="proof-step"):
    c = {"id": cid, "paper": "T", "kind": "equation", "number": "", "location": f"p.tex:{line}",
         "scope": scope, "unit": "proof-equation", "parent": "T:thm", "clauses": []}
    r = extract(root, c)
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": r.sha256}


def test_a_row_of_a_display_is_read_in_its_display(tmp_path):
    (tmp_path / "p.tex").write_text(ALIGN)
    inv = {"claims": [pinned(tmp_path, "T:two", 4)]}
    regions = collect(inv, "T", tmp_path)
    got = step_texts(inv, "T", tmp_path, regions)["T:two"]
    assert got["text"].strip() == "y &= x + c \\label{eq:two}"
    assert got["whole"]["start_line"] == 2 and got["whole"]["end_line"] == 5
    assert "x &= a + b" in got["whole"]["text"] and "\\end{align}" in got["whole"]["text"]


def test_a_step_that_holds_whole_environments_reads_as_before(tmp_path):
    (tmp_path / "p.tex").write_text("\\begin{proof}\n\\begin{equation}\\label{eq:a}\n a = b\n"
                                    "\\end{equation}\n\\end{proof}\n")
    inv = {"claims": [pinned(tmp_path, "T:a", 2)]}
    got = step_texts(inv, "T", tmp_path, collect(inv, "T", tmp_path))["T:a"]
    assert "whole" not in got
    # The body line of a display that holds nothing else: its opening and closing hide nothing.
    (tmp_path / "p.tex").write_text("\\begin{proof}\n\\begin{equation}\\label{eq:a}\n a = b\n"
                                    "\\end{equation}\n\\end{proof}\n")
    inv = {"claims": [pinned(tmp_path, "T:a", 3)]}
    got = step_texts(inv, "T", tmp_path, collect(inv, "T", tmp_path))["T:a"]
    assert "whole" not in got and got["text"].strip() == "a = b"


@needs_lean
@needs_tex
def test_review_read_shows_the_whole_display_and_marks_the_step(toy, monkeypatch, capsys):
    """The issue's example, in the toy paper's proof of Theorem 2.5: a step per row."""
    edit(toy / "paper" / "toy.tex", "and the choice $k = 1$",
         "\\begin{align}\n  x &= n^2 + n \\label{eq:row-one} \\\\\n"
         "  y &= x + n \\label{eq:row-two}\n\\end{align}\nand the choice $k = 1$")
    lines = (toy / "paper" / "toy.tex").read_text().split("\n")
    line = next(i + 1 for i, l in enumerate(lines) if "eq:row-two" in l)
    c = {"id": "T:eq:row-two", "paper": "T", "kind": "equation", "number": "Equation (5)",
         "title": "", "location": f"toy.tex:{line}", "scope": "proof-step", "scope_note": "",
         "scope_reviewed": True, "unit": "proof-equation", "parent": "T:thm:bound",
         "clauses": []}
    r = extract(toy / "paper", c)
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"].append({**c, "source_hash_scheme": SCHEME, "source_sha256": r.sha256,
                          "source_line_sha256": r.line_sha256})
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    from conftest import build
    build(toy)
    monkeypatch.chdir(toy)
    from prooflens import cli
    cli.main(["review", "read", "step:T:eq:row-two", "--json", "--as", "human:Test-Referee"])
    out = json.loads(capsys.readouterr().out)
    (p,) = [p for p in out["paper"]["passages"] if p["claim"] == "T:eq:row-two"]
    assert p["text"].startswith("\\begin{align}") and "x &= n^2 + n" in p["text"]
    assert p["states"]["start_line"] == line
    assert p["states"]["text"].strip() == "y &= x + n \\label{eq:row-two}"
