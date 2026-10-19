"""References to the paper's numbers in Lean docstrings and names (#127), on synthetic
indexes: each kind of observation stays distinct, references to other works are not drift, an
incomplete numbering refutes nothing, a version map resolves only what it names once, one stray
reference is no pattern, and correct references are quiet. No Lean session is involved."""

from prooflens import numbering as nb
from prooflens.retrieval import Retrieval


def decl(name, doc=None, type_="True", kind="theorem", module="P.Main", line=1):
    return {"name": name, "kind": kind, "module": module, "range": {"line": line},
            "type": type_, "doc": doc, "uses": [], "value_uses": []}


CLAIMS = [{"id": "P:t21", "kind": "theorem", "number": "Theorem 2.1", "scope": "formal",
           "statement": "Every odd square is odd."},
          {"id": "P:p23", "kind": "proposition", "number": "Proposition 2.3", "scope": "formal",
           "statement": "A prime greater than two is odd."},
          {"id": "P:t31", "kind": "theorem", "number": "Theorem 3.1", "scope": "formal",
           "statement": "There is a constant $C$ with $T(n) \\le C n^2$ for every triangle "
                        "number $T(n)$."}]
INV = nb.inventory(CLAIMS, True, sections={"1", "2", "3"})


def statuses(out):
    return {(o["source"].get("declaration") or o["source"]["module"], o["reference"]): o["status"]
            for o in out["references"]}


def test_exact_other_kind_and_absent_are_distinct():
    index = [decl("P.a", "Theorem 2.1: odd squares."), decl("P.b", "Lemma 2.3 here."),
             decl("P.c", "Corollary 5.2."), decl("P.theorem_7_1"), decl("P.d", "See Section 2."),
             decl("P.e", "See Section 9.")]
    out = nb.analyse(index, CLAIMS, INV)
    assert statuses(out) == {
        ("P.a", "Theorem 2.1"): "exact", ("P.b", "Lemma 2.3"): "other-kind",
        ("P.c", "Corollary 5.2"): "absent", ("P.theorem_7_1", "Theorem 7.1"): "absent",
        ("P.d", "Section 2"): "exact", ("P.e", "Section 9"): "absent"}
    b = next(o for o in out["references"] if o["reference"] == "Lemma 2.3")
    assert b["paper"]["reference"] == "Proposition 2.3" and "not a lemma" in b["detail"]
    # Each observation keeps its exact text and where it is.
    a = next(o for o in out["references"] if o["source"]["declaration"] == "P.a")
    assert a["text"] == "Theorem 2.1" and a["source"] == {
        "declaration": "P.a", "module": "P.Main", "file": "P/Main.lean", "line": 1,
        "where": "docstring"}
    name = next(o for o in out["references"] if o["source"]["where"] == "name")
    assert name["text"] == "theorem_7_1"


def test_another_works_numbers_are_not_this_papers():
    index = [decl("P.a", "This is Theorem 4.1 of [Gauss]."), decl("P.b", "By [AB, Lemma 9]."),
             decl("P.c", "Theorem 3 in Hardy and Wright."), decl("P.d", "Theorem 8 of the paper."),
             decl("Other.e", "Theorem 9.9.", module="Other.Main")]
    out = nb.analyse(index, CLAIMS, INV, foreign={"Other"})
    st = statuses(out)
    assert st[("P.a", "Theorem 4.1")] == st[("P.b", "Lemma 9")] == \
        st[("P.c", "Theorem 3")] == st[("Other.e", "Theorem 9.9")] == "other-source"
    assert st[("P.d", "Theorem 8")] == "absent"
    assert "another paper" in next(o["detail"] for o in out["references"]
                                   if o["source"]["declaration"] == "Other.e")
    assert out["pattern"]["other_source"] == 4 and not out["pattern"]["drift"]


def test_an_incomplete_numbering_refutes_nothing():
    inv = nb.inventory(CLAIMS, False, "the paper is a PDF whose statements were found by their "
                       "headings, so its numbering may be incomplete")
    index = [decl(f"P.x{i}", f"Lemma {i}.7.") for i in range(5)] + [decl("P.a", "Theorem 2.1.")]
    out = nb.analyse(index, CLAIMS, inv)
    st = statuses(out)
    assert {st[(f"P.x{i}", f"Lemma {i}.7")] for i in range(5)} == {"unchecked"}
    assert st[("P.a", "Theorem 2.1")] == "exact"
    assert out["pattern"]["absent"] == 0 and not out["pattern"]["drift"]
    assert not out["pattern"]["inventory"]["complete"]
    assert "PDF" in out["pattern"]["inventory"]["reason"]
    assert nb.drift_note(out["pattern"], out["references"]) is None


def test_one_stray_reference_is_not_a_pattern():
    index = [decl("P.a", "Theorem 2.1."), decl("P.b", "Theorem 3.1."), decl("P.c", "Lemma 6.6.")]
    out = nb.analyse(index, CLAIMS, INV)
    assert out["pattern"]["absent"] == 1 and not out["pattern"]["drift"]
    index += [decl("P.d", "Lemma 6.7."), decl("P.e", "Lemma 6.8.")]
    out = nb.analyse(index, CLAIMS, INV)
    assert out["pattern"]["drift"] and out["pattern"]["absent"] == 3
    note = nb.drift_note(out["pattern"], out["references"])
    assert "3 of the 5 references checked" in note and "Lemma 6.6" in note


def test_correct_references_are_quiet():
    index = [decl("P.a", "Theorem 2.1."), decl("P.b", "Proposition 2.3."),
             decl("P.c", "Theorem 3.1, in Section 3.")]
    out = nb.analyse(index, CLAIMS, INV)
    assert not [o for o in out["references"] if nb.suspect(o)]
    assert not out["pattern"]["drift"]


def test_a_same_number_content_mismatch_is_a_possibly_stale_lead():
    # P.bound cites Theorem 2.1, whose passage is about odd squares; its statement is
    # Theorem 3.1's. The reference stays exact and is marked as a lead to check.
    index = [decl("P.triangle", "The triangle number.", "ℕ → ℕ", kind="def"),
             {**decl("P.bound", "Theorem 2.1: a bound for triangle numbers by a constant.",
                     "∃ C, ∀ (n : ℕ), P.triangle n ≤ C * n ^ 2"), "uses": ["P.triangle"]},
             decl("P.sq", "Theorem 2.1: odd squares are odd.", "∀ n, Odd n → Odd (n * n)")]
    ret = Retrieval.build(index)
    out = nb.analyse(index, CLAIMS, INV, retrieval=ret, claim_text=lambda c: c["statement"])
    bound = next(o for o in out["references"] if o["source"]["declaration"] == "P.bound")
    assert bound["status"] == "exact" and bound["stale_lead"]
    assert bound["content"]["closer"]["number"] == "Theorem 3.1"
    sq = next(o for o in out["references"] if o["source"]["declaration"] == "P.sq")
    assert sq["status"] == "exact" and not sq.get("stale_lead")
    assert nb.reliability(out, "P.bound", "Theorem 2.1")[0] < 1
    assert nb.reliability(out, "P.sq", "Theorem 2.1") == (1.0, None)


def test_a_version_map_resolves_one_target_and_keeps_several():
    index = [decl("P.a", "Lemma 1.4."), decl("P.b", "Lemma 1.5."), decl("P.c", "Lemma 1.6.")]
    vmap = {"source": "the authors' list of changes between the two versions", "entries": [
        {"old": "Lemma 1.4", "new": "Theorem 3.1"},
        {"old": "Lemma 1.5", "new": ["Theorem 2.1", "Proposition 2.3"]},
        {"old": "Lemma 1.6", "new": "Theorem 2.1"}, {"old": "Lemma 1.6", "new": "Theorem 3.1"}]}
    out = nb.analyse(index, CLAIMS, INV, version_map=vmap)
    cur = {o["source"]["declaration"]: o.get("current") for o in out["references"]}
    assert cur["P.a"] == {"reference": "Theorem 3.1", "claims": ["P:t31"],
                          "source": vmap["source"]}
    assert cur["P.b"]["ambiguous"] == ["Theorem 2.1", "Proposition 2.3"]
    assert cur["P.c"]["ambiguous"] == ["Theorem 2.1", "Theorem 3.1"]
    assert "the version map gives Theorem 3.1" in nb.message(
        next(o for o in out["references"] if o["source"]["declaration"] == "P.a"))


def test_module_docstrings_are_read_with_their_lines(tmp_path):
    (tmp_path / "P").mkdir()
    (tmp_path / "P" / "Main.lean").write_text(
        "import X\n\n/-!\n# Main\n\nThe proof of Theorem 2.1 and Lemma 8.1.\n-/\n")
    blocks = nb.module_doc_blocks(tmp_path, ["P.Main"])
    out = nb.analyse([], CLAIMS, INV, blocks)
    lem = next(o for o in out["references"] if o["reference"] == "Lemma 8.1")
    assert lem["status"] == "absent" and lem["source"]["line"] == 6
    assert lem["source"]["where"] == "module docstring"
