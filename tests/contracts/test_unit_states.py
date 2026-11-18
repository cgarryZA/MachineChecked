"""`review read` of a claim cut from a longer passage (#671) says which part the unit states: the
claim's own pinned region (its lines), first, with the rest of the passage as context. The part is
read from the inventory's pin alone, never from the clauses, so it is shown before the reading is
locked with no clause names; a snapshot without the paper's text leaves it out and reads it again
like the other passages (`test_snapshot_without_text.py`). Nothing here builds Lean."""

import json

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import manifest as mf
from test_review_withholds_outcome import UNIT, WHO, withheld, write_spec_site

REMARK = ("\\label{rem:five} Two facts. (a) Every $n$ has a successor. (b) No $n$ is its own "
          "successor.")
A_LINES = "(a) Every $n$ has a successor."


def tex(region_text: str | None, statement: str | None = REMARK, **reg) -> tuple:
    anchor = {"kind": "exact", "file": "main.tex", "line": 40, "statement": statement} \
        if statement is not None else None
    t = {"regions": {"P:rmk5-a": {"file": "main.tex", "start_line": 42, "end_line": 42,
                                  "kind": "span", **reg}},
         "region_text": {"P:rmk5-a": region_text} if region_text is not None else {}}
    return anchor, t


def test_the_part_is_the_claim_s_own_region_when_the_passage_is_longer():
    anchor, t = tex(A_LINES)
    assert mf.own_part("P:rmk5-a", anchor, t) == {
        "file": "main.tex", "start_line": 42, "end_line": 42, "text": A_LINES}
    # A region that holds the whole passage, its environment's lines say, marks nothing.
    whole = "\\begin{remark}" + REMARK.replace(" ", "\n  ") + "\n\\end{remark}"
    assert mf.own_part("P:rmk5-a", *tex(whole)) is None
    # Nothing to mark without a passage it is part of, without its region, or with an error.
    assert mf.own_part("P:rmk5-a", *tex(A_LINES, statement=None)) is None
    assert mf.own_part("P:rmk5-a", *tex(None)) is None
    assert mf.own_part("P:rmk5-a", *tex(A_LINES, error="source line is outside the file")) \
        is None


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_spec_site(tmp_path)
    f = data / "claims" / "S_prop_p.json"
    ch = json.loads(f.read_text())
    ch["statement_tex"] = ch["anchor"]["statement"] = \
        "\\label{prop:p}\\lean{Syn.PaperSpec.p} For every $n$, $P(n)$ holds; and $Q(n)$ too."
    ch["states"] = {"file": "main.tex", "start_line": 12, "end_line": 12,
                    "text": "For every $n$, $P(n)$ holds;\\lean{Syn.PaperSpec.p}"}
    f.write_text(json.dumps(ch))
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    return work


def read(capsys, *args):
    cli.main(["review", "read", UNIT, *args, *WHO])
    return capsys.readouterr().out


def test_read_marks_the_part_the_unit_states_before_the_lock(work, capsys):
    pk = json.loads(read(capsys, "--json"))
    (p,) = pk["paper"]["passages"]
    assert p["states"] == {"file": "main.tex", "start_line": 12, "end_line": 12,
                           "text": "For every $n$, $P(n)$ holds;"}
    assert p["text"] == "\\label{prop:p} For every $n$, $P(n)$ holds; and $Q(n)$ too."
    text = read(capsys)
    assert ("This unit states line 12 of main.tex, the part its pin holds:\nFor every $n$, $P(n)$ "
            "holds;\nThe whole passage it is part of, as context:\n\\label{prop:p} For every $n$")\
        in text
    # The part names no clause, no Lean and nothing of the author's outcome.
    for out in (json.dumps(pk, ensure_ascii=False), text, read(capsys, "--context")):
        withheld(out)
        assert "\\lean{Syn" not in out


@needs_lean
@needs_tex
def test_a_claim_cut_from_a_remark_of_the_toy_is_marked(toy):
    """A second claim of Remark 2.4, located by its last line, shares the remark's environment
    (by its number): its record names that line as the part it states, and the read stage shows
    it first; the claim of the whole remark has no part to mark."""
    from prooflens import compare as cmp
    from prooflens import source_regions as sr
    inv = json.loads((toy / "claims.json").read_text())
    claim = {"id": "T:rem:pred-b", "paper": "T", "kind": "remark", "number": "Remark 2.4",
             "title": "", "label": None, "location": "toy.tex:62",
             "source_region": {"end_line": 62}, "scope": "expository",
             "scope_note": "a synthetic part of the remark", "scope_reviewed": True,
             "clauses": []}
    rec = sr.pin(toy / "paper", claim).record()
    claim.update(source_sha256=rec["sha256"], source_hash_scheme=rec["scheme"],
                 source_line_sha256=rec["line_sha256"])
    inv["claims"].append(claim)
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    index, _, cfg = build(toy)
    site = cmp.Site(cfg.out_dir / "site" / "data")
    part, whole = site.chunk("T:rem:pred-b"), site.chunk("T:rem:pred")
    assert part["states"] == {"file": "toy.tex", "start_line": 62, "end_line": 62,
                              "text": "for every $n \\ge 1$."}
    assert "states" not in whole
    p = cmp.passage(part, "read")
    assert p["states"]["text"] == "for every $n \\ge 1$." and "truncated subtraction" in p["text"]
    assert cmp.passage_text(p).count("This unit states line 62 of toy.tex") == 1
