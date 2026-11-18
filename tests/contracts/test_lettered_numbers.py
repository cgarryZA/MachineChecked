"""#574: an appendix statement's number has a letter (`Lemma B.1`, `Lemma C.2.3`). It is part of
the paper's numbering, and a docstring citing a lettered number is checked like any other: a
stale one reads `absent` and warns. A letter alone (`Theorem A`) names a statement and is not a
number. Synthetic indexes; no Lean session."""

from prooflens import numbering as nb
from test_numbering import decl, statuses

CLAIMS = [{"id": "P:t1", "kind": "theorem", "number": "Theorem 1", "scope": "formal",
           "statement": "Odd plus odd is even."},
          {"id": "P:b1", "kind": "lemma", "number": "Lemma B.1", "scope": "formal",
           "statement": "The square of an odd number is odd."},
          {"id": "P:c23", "kind": "lemma", "number": "Lemma C.2.3", "scope": "formal",
           "statement": "Zero is even."},
          {"id": "P:ta", "kind": "theorem", "number": "Theorem A", "scope": "formal",
           "statement": "Every even number is a sum of two odd ones."}]


def test_lettered_numbers_are_part_of_the_numbering():
    inv = nb.inventory(CLAIMS, True, sections={"1", "A", "B", "B.1"})
    assert set(inv["statements"]) == {("theorem", "1"), ("lemma", "B.1"), ("lemma", "C.2.3")}
    assert nb.claim_ref({"number": "Lemma B.1", "kind": "lemma"}) == ("lemma", "B.1")
    assert nb.claim_ref({"number": "Theorem A", "kind": "theorem"}) is None


def test_a_stale_lettered_citation_is_absent_and_warns():
    inv = nb.inventory(CLAIMS, True, sections={"1", "A", "B", "B.1"})
    index = [decl("P.sq", "Lemma B.1 of the paper: odd squares."),
             decl("P.zero", "Lemma C.4 of the paper."), decl("P.sum", "Theorem 3."),
             decl("P.sec", "See Section B.1 and Section B.7."), decl("P.named", "Theorem A.")]
    out = nb.analyse(index, CLAIMS, inv)
    st = statuses(out)
    assert st[("P.sq", "Lemma B.1")] == "exact"
    assert st[("P.zero", "Lemma C.4")] == "absent"
    assert st[("P.sum", "Theorem 3")] == "absent"
    assert st[("P.sec", "Section B.1")] == "exact" and st[("P.sec", "Section B.7")] == "absent"
    # "Theorem A" names a statement; it is not read as a number.
    assert not [k for k in st if k[0] == "P.named"]
    stale = next(o for o in out["references"] if o["reference"] == "Lemma C.4")
    assert nb.suspect(stale)
    assert out["pattern"]["inventory"]["statements"] == 3


def test_the_sections_of_an_appendix_are_read_from_the_compilation(tmp_path):
    aux = tmp_path / "paper.aux"
    aux.write_text("\\@writefile{toc}{\\contentsline {section}{\\numberline {1}Results}{1}}\n"
                   "\\@writefile{toc}{\\contentsline {section}{\\numberline {A}Proofs}{2}}\n"
                   "\\@writefile{toc}{\\contentsline {subsection}{\\numberline {A.1}One}{2}}\n")
    assert nb.sections_from_aux(aux) == {"1", "A", "A.1"}
