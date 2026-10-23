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


def test_a_part_of_the_paper_or_the_lean_after_the_number_is_not_another_work():
    # After "of", "in" or "from", a part of this paper or of its formalisation names no other
    # work, so a stale number written that way is checked (#308); a citation after the part, or
    # another work's name, still names another work.
    checked = {"P.a": "Lemma 7.7 in Section 7.", "P.b": "Lemma 7.7 of Section 7.",
               "P.c": "Lemma 7.7 from Appendix A.", "P.d": "Theorem 9.9 in Lean.",
               "P.e": "Theorem 9.9 in Mathlib form.", "P.f": "Theorem 9.9 in the Appendix.",
               "P.g": "Theorem 9.9, in Sec. 9.", "P.h": "Theorem 9.9 of Part II.",
               "P.i": "Theorem 9.9 in Sections 2 and 3.", "P.j": "Theorem 9.9 in Lemma 3.2.",
               "P.k": "Theorem 9.9 in Lean 4."}
    elsewhere = {"Q.a": "Theorem 4.1 of [Gauss].", "Q.b": "Theorem 3 in Hardy and Wright.",
                 "Q.c": "Lemma 7.7 in Section 7 of [AB].", "Q.d": "Lemma 7.7 from Appendix A [AB].",
                 "Q.e": "Theorem 9.9 in Chapter IV of Hardy and Wright.",
                 "Q.f": "Theorem 9.9 in Prop. 4.7 of [AB].", "Q.g": "Theorem 9.9 of Paper B.",
                 "Q.h": "Theorem 9.9 in Sections 4 and 5 of [AB]."}
    index = [decl(n, d) for n, d in {**checked, **elsewhere}.items()]
    out = nb.analyse(index, CLAIMS, INV)
    first = {}
    for o in out["references"]:
        first.setdefault(o["source"]["declaration"], o)
    for n in checked:
        assert first[n]["status"] == "absent" and nb.suspect(first[n]), (n, first[n])
    for n in elsewhere:
        assert first[n]["status"] == "other-source", (n, first[n])
        assert first[n]["detail"] == "it refers to another work"
    # The current numbers, written the same way, are exact.
    index = [decl("R.a", "Theorem 2.1 in Section 2."), decl("R.b", "Theorem 3.1 from Appendix A."),
             decl("R.c", "Proposition 2.3 in Lean.")]
    assert statuses(nb.analyse(index, CLAIMS, INV)) == {
        ("R.a", "Theorem 2.1"): "exact", ("R.a", "Section 2"): "exact",
        ("R.b", "Theorem 3.1"): "exact", ("R.c", "Proposition 2.3"): "exact"}


def test_a_word_that_only_starts_like_ref_cites_no_other_work():
    # After "of", "in" or "from", a lowercase reference word cites another work only with its
    # label; any other word starting "ref" leaves a stale number checked (#329).
    checked = {"P.a": "Theorem 9.9 in refined form.", "P.b": "Lemma 7.7 from refs.",
               "P.c": "Theorem 9.9 in reference to Lemma 2.",
               "P.d": "Lemma 7.7 of reflexive spaces.", "P.e": "Theorem 9.9, in refs."}
    elsewhere = {"Q.a": "Theorem 9.9 of ref. [3].", "Q.b": "Lemma 7.7 in ref. 12.",
                 "Q.c": "Theorem 9.9 in [ref].", "Q.d": "Lemma 7.7 from refs. [3, 4].",
                 "Q.e": "Theorem 9.9 in reference [3].", "Q.f": "Lemma 7.7 of ref.~\\cite{AB}.",
                 "Q.g": "Theorem 9.9 in Ref. [3]."}
    index = [decl(n, d) for n, d in {**checked, **elsewhere}.items()]
    out = nb.analyse(index, CLAIMS, INV)
    first = {}
    for o in out["references"]:
        first.setdefault(o["source"]["declaration"], o)
    for n in checked:
        assert first[n]["status"] == "absent" and nb.suspect(first[n]), (n, first[n])
    for n in elsewhere:
        assert first[n]["status"] == "other-source", (n, first[n])
        assert first[n]["detail"] == "it refers to another work"
    # The current number, written the same way, is exact.
    assert statuses(nb.analyse([decl("R.a", "Theorem 2.1 in refined form.")], CLAIMS, INV)) \
        == {("R.a", "Theorem 2.1"): "exact"}


def test_an_authors_possessive_or_a_books_chapter_before_the_number_is_another_work():
    # What comes just before the number names another work: an author's possessive, or a
    # chapter after a comma as a book's citation gives it (#287).
    elsewhere = {"P.a": "Gauss's Lemma 4.22 gives the closed form.",
                 "P.b": "As in Gauss’s Lemma 4.22.", "P.c": "By Gauss' Lemma 4.22.",
                 "P.d": "Revuz–Yor's Proposition 4.7.", "P.e": "Smith et al.'s Theorem 3.",
                 "P.f": "By [AB]'s Lemma 9.", "P.g": "The closed form is Gauss's\nLemma 4.22.",
                 "P.h": "Hardy–Wright, *An Introduction*, Ch. IV, Prop. 4.7.",
                 "P.i": "Hardy and Wright (1979), Chapter 4, Theorem 4.1."}
    # Near misses: each is checked against this paper (here, absent or other-kind).
    checked = {"Q.a": "The paper's Lemma 2.1.", "Q.b": "This paper's Lemma 4.22.",
               "Q.c": "Lemma 4.22.",
               "Q.d": "Gauss's lemma is classical; this paper's Lemma 4.22 extends it.",
               "Q.e": "By Gauss's reciprocity, Lemma 4.22 follows.",
               "Q.f": "Gauss's lemma (Lemma 4.22 here) holds.",
               "Q.g": "In Chapter 4, Lemma 4.22 holds.", "Q.h": "Chapter IV, Lemma 4.22.",
               "Q.i": "Following [AB], Lemma 2.1 bounds it.", "Q.j": "Paper A's Lemma 2.1.",
               "Q.k": "Theorem 2.1's Lemma 4.22.", "Q.l": "Lean's Lemma 4.22.",
               "Q.m": "The Appendix's Lemma 4.22."}
    index = [decl(n, d) for n, d in {**elsewhere, **checked}.items()]
    out = nb.analyse(index, CLAIMS, INV)
    # Each declaration's last reference (Q.k's second).
    last = {o["source"]["declaration"]: o for o in out["references"]}
    for n in elsewhere:
        assert last[n]["status"] == "other-source", (n, last[n])
        assert last[n]["detail"] == "it refers to another work"
    assert last["P.h"]["reference"] == "Proposition 4.7"
    for n in checked:
        assert last[n]["status"] in ("absent", "other-kind"), (n, last[n])
        assert nb.suspect(last[n])
    assert last["Q.a"]["status"] == "other-kind" and last["Q.b"]["status"] == "absent"
    # Theorem 2.1, before the possessive, is this paper's and exact.
    assert statuses(out)[("Q.k", "Theorem 2.1")] == "exact"
    assert out["pattern"]["other_source"] == len(elsewhere)


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
    assert set(statuses(out).values()) == {"exact"} and len(out["references"]) == 4
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


def test_a_repeated_reference_has_its_own_id(tmp_path):
    # The same text twice in one docstring, name or module docstring line gives two references
    # with different ids (#348); the first keeps the id it has alone.
    pad = "x " * 40
    index = [decl("P.a", "Lemma 7.7, and again Lemma 7.7."), decl("P.lemma_7_7_lemma_7_7"),
             decl("P.b", f"{pad}Lemma 7.7 {pad}Lemma 7.7 {pad}")]
    (tmp_path / "P").mkdir()
    (tmp_path / "P" / "Main.lean").write_text("/-! Lemma 8.1 and Lemma 8.1. -/\n")
    out = nb.analyse(index, CLAIMS, INV, nb.module_doc_blocks(tmp_path, ["P.Main"]))
    refs = out["references"]
    by = {}
    for o in refs:
        by.setdefault((o["source"]["declaration"] or o["source"]["module"],
                       o["source"]["where"]), []).append(o)
    assert sorted(len(v) for v in by.values()) == [2, 2, 2, 2]
    assert len({o["id"] for o in refs}) == len(refs) == 8
    # Long enough apart, two copies have the same context and place in it: only the id differs.
    b1, b2 = by[("P.b", "docstring")]
    assert (b1["context"], b1["at"]) == (b2["context"], b2["at"]) and b1["id"] != b2["id"]
    assert {o["status"] for o in refs} == {"absent"} and out["pattern"]["absent"] == 8
    alone = nb.find_references([decl("P.a", "Lemma 7.7.")], [])
    assert alone[0]["id"] == by[("P.a", "docstring")][0]["id"]


def test_module_docstrings_are_read_with_their_lines(tmp_path):
    (tmp_path / "P").mkdir()
    (tmp_path / "P" / "Main.lean").write_text(
        "import X\n\n/-!\n# Main\n\nThe proof of Theorem 2.1 and Lemma 8.1.\n-/\n")
    blocks = nb.module_doc_blocks(tmp_path, ["P.Main"])
    out = nb.analyse([], CLAIMS, INV, blocks)
    lem = next(o for o in out["references"] if o["reference"] == "Lemma 8.1")
    assert lem["status"] == "absent" and lem["source"]["line"] == 6
    assert lem["source"]["where"] == "module docstring"


LEMMA_41 = CLAIMS + [{"id": "P:l41", "kind": "lemma", "number": "Lemma 4.1", "scope": "formal",
                      "statement": "Every even square is even."},
                     {"id": "P:a22", "kind": "assumption", "number": "Assumption 2.2",
                      "scope": "formal", "statement": "The coefficients are bounded."}]


def test_run_together_digits_in_names_follow_the_papers_numbering():
    # `lem41` drops the dot of Lemma 4.1: the paper's numbering decides how it is read, and a
    # name in a docstring written as an identifier (`Assumption22`) is read the same way.
    index = [decl("P.lem41_bound"), decl("P.thm21_odd"), decl("P.sec31_intro"),
             decl("P.a", "Uses `Assumption22` throughout."), decl("P.b", "Lemma 41.")]
    out = nb.analyse(index, LEMMA_41, nb.inventory(LEMMA_41, True, sections={"1", "3.1"}))
    by = {(o["source"]["declaration"], o["source"]["where"]): o for o in out["references"]}
    lem = by[("P.lem41_bound", "name")]
    assert lem["status"] == "exact" and lem["reference"] == "Lemma 4.1"
    assert lem["readings"] == ["4.1", "41"] and lem["paper"]["claims"] == ["P:l41"]
    assert "could mean 4.1 or 41" in lem["detail"]
    assert by[("P.thm21_odd", "name")]["reference"] == "Theorem 2.1"
    assert by[("P.sec31_intro", "name")]["status"] == "exact"
    assert by[("P.a", "docstring")]["reference"] == "Assumption 2.2"
    assert by[("P.a", "docstring")]["status"] == "exact"
    # A number written out in prose is read as written.
    b = by[("P.b", "docstring")]
    assert b["status"] == "absent" and b["reference"] == "Lemma 41" and "readings" not in b
    assert [o["source"]["declaration"] for o in out["references"] if nb.suspect(o)] == ["P.b"]


def test_run_together_digits_no_reading_matches_or_several_do():
    # Without a Lemma 4.1 or 41 the name still disagrees with the paper, naming both readings.
    out = nb.analyse([decl("P.lem41_bound"), decl("P.lem23_odd"), decl("P.sec45_x")],
                     CLAIMS, INV)
    by = {o["source"]["declaration"]: o for o in out["references"]}
    assert by["P.lem41_bound"]["status"] == "absent"
    assert "no statement numbered 4.1 or 41" in by["P.lem41_bound"]["detail"]
    # 2.3 exists as a proposition: the reading names another kind of statement.
    assert by["P.lem23_odd"]["status"] == "other-kind"
    assert by["P.lem23_odd"]["reference"] == "Lemma 2.3"
    assert "Proposition 2.3" in by["P.lem23_odd"]["detail"]
    assert by["P.sec45_x"]["status"] == "absent" and "Section 4.5 or 45" in \
        by["P.sec45_x"]["detail"]
    # When the paper has a statement for two readings, the name does not say which.
    both = LEMMA_41 + [{"id": "P:l41b", "kind": "lemma", "number": "Lemma 41",
                        "scope": "formal", "statement": "x"}]
    out = nb.analyse([decl("P.lem41_bound")], both, nb.inventory(both, True))
    o = out["references"][0]
    assert o["status"] == "unchecked" and "Lemma 4.1 or Lemma 41" in o["detail"]
    assert not nb.suspect(o)


def test_a_citation_of_what_a_statement_relies_on_is_not_a_stale_lead():
    # P.bound states Theorem 3.1 and relies on Assumption 2.2. Its statement reads like
    # Theorem 3.1, not like Assumption 2.2, which is fine for a citation of a hypothesis: only
    # the opening citation is compared with the content. A missing or wrong-kind citation is
    # still reported.
    tri = decl("P.triangle", "The triangle number.", "ℕ → ℕ", kind="def")
    bound_type = "∃ C, ∀ (n : ℕ), P.triangle n ≤ C * n ^ 2"
    index = [tri,
             {**decl("P.bound", "**Theorem 3.1.** A bound for triangle numbers by a constant, "
                     "under Assumption 2.2, Lemma 2.3 and Assumption 9.9.", bound_type),
              "uses": ["P.triangle"]},
             {**decl("P.stale", "**Assumption 2.2.** A bound for triangle numbers by a "
                     "constant.", bound_type), "uses": ["P.triangle"]}]
    ret = Retrieval.build(index)
    out = nb.analyse(index, LEMMA_41, nb.inventory(LEMMA_41, True), retrieval=ret,
                     claim_text=lambda c: c["statement"])
    by = {(o["source"]["declaration"], o["reference"]): o for o in out["references"]}
    t31, a22 = by[("P.bound", "Theorem 3.1")], by[("P.bound", "Assumption 2.2")]
    assert t31["role"] == "statement" and a22["role"] == "cited"
    assert t31["status"] == a22["status"] == "exact"
    assert not t31.get("stale_lead") and not a22.get("stale_lead") and "content" not in a22
    assert by[("P.bound", "Lemma 2.3")]["status"] == "other-kind"
    assert by[("P.bound", "Assumption 9.9")]["status"] == "absent"
    # A docstring that opens with a citation of another statement still gets the lead.
    stale = by[("P.stale", "Assumption 2.2")]
    assert stale["role"] == "statement" and stale["stale_lead"]
    assert stale["content"]["closer"]["number"] == "Theorem 3.1"


def test_several_papers_attribute_each_reference_to_one():
    # Two papers in one configuration (#229). A reference is checked against the paper whose
    # claims name its declaration, or whose namespace or module holds it, or that it names;
    # one that nothing attributes stays unchecked, with the reason.
    from types import SimpleNamespace
    from prooflens import content
    papers = [SimpleNamespace(id="A", title="Odd squares"),
              SimpleNamespace(id="B", title="Triangle bounds")]
    anchors = {"A": [{"env": "theorem", "number": "2.1", "statement": "Every odd square is odd."},
                     {"env": "lemma", "number": "2.2", "statement": "x"}],
               "B": [{"env": "theorem", "number": "1.1", "statement": "A triangle bound."}]}
    tex = {p: {"mode": "latex", "anchors": a} for p, a in anchors.items()}
    inv_claims = [{"id": "A:t21", "paper": "A", "kind": "theorem", "number": "Theorem 2.1",
                   "clauses": [{"spec": "PA.Spec.odd_sq"}]},
                  {"id": "B:t11", "paper": "B", "kind": "theorem", "number": "Theorem 1.1",
                   "clauses": [{"spec": "PB.Spec.bound", "defs": ["Common.tri"]}]}]
    full = [decl("PA.Spec.odd_sq", "Theorem 2.1: odd squares.", module="PA.Spec"),
            decl("PA.Spec.helper", "Lemma 2.3 of this paper.", module="PA.Spec"),
            decl("PB.Spec.bound", "Theorem 2.1: the triangle bound.", module="PB.Spec"),
            decl("PB.Spec.lem11_tri", module="PB.Spec"),
            decl("Common.tri", "Theorem 1.1 uses it.", module="Common"),
            decl("Common.both", "Lemma 2.2 here.", module="Common"),
            decl("Common.named", "As in Lemma 2.2 of [A].", module="Common"),
            decl("Other.x", "Theorem 9.9 of [Gauss].", module="Other")]
    notes = []
    num = content.several(papers, tex, inv_claims, {}, full, [], None, None, notes)
    by = {(o["source"]["declaration"], o["reference"]): o for o in num["references"]}
    # Checked against A: its claim names the declaration, or A's namespace holds it.
    assert by[("PA.Spec.odd_sq", "Theorem 2.1")]["attributed"] == "A"
    assert by[("PA.Spec.odd_sq", "Theorem 2.1")]["status"] == "exact"
    helper = by[("PA.Spec.helper", "Lemma 2.3")]
    assert (helper["attributed"], helper["status"]) == ("A", "absent")
    # B's bound cites Theorem 2.1, which B does not have: stale against B, not exact against A.
    bound = by[("PB.Spec.bound", "Theorem 2.1")]
    assert (bound["attributed"], bound["status"]) == ("B", "absent")
    assert "of paper B" in bound["message"]
    assert by[("PB.Spec.lem11_tri", "Lemma 1.1")]["status"] == "other-kind"
    assert by[("Common.tri", "Theorem 1.1")]["attributed"] == "B"
    # A definition B's claim names gives its namespace to no paper: papers share definitions,
    # so Common.both is unattributed ...
    both = by[("Common.both", "Lemma 2.2")]
    assert both["status"] == "unchecked" and "attributed" not in both
    # ... unless the reference names a paper.
    named = by[("Common.named", "Lemma 2.2")]
    assert (named["attributed"], named["status"]) == ("A", "exact")
    # Another work stays another work; a namespace no paper's claims reach is unattributed.
    assert by[("Other.x", "Theorem 9.9")]["status"] == "other-source"
    assert "attributed" not in by[("Other.x", "Theorem 9.9")]
    # Per paper, and in total.
    assert num["papers"]["A"]["absent"] == 1 and num["papers"]["B"]["absent"] == 1
    assert nb.paper_view(num, "B")["references"] and all(
        o["attributed"] == "B" for o in nb.paper_view(num, "B")["references"])
    assert num["pattern"]["references"] == len(full)


def test_several_papers_read_a_citation_at_the_references_own_place():
    # A bracketed citation just before the number names its paper (#330), and each reference
    # is attributed from its own place in its context, not from the first occurrence of its
    # text there (#331).
    papers = [("U", ""), ("A", "")]

    def named(doc):
        return [nb.attribute(o, {}, papers)[0]
                for o in nb.find_references([decl("P.a", doc)], [])]

    assert named("[U, Lemma 2.1].") == named("[U]'s Lemma 2.1.") == ["U"]
    assert named("By [U]’s\n  Lemma 2.1.") == ["U"]
    assert named("[U, Lemma 2.1 and Lemma 2.2].") == ["U", "U"]
    assert named("[U, Lemma 2.1; A, Lemma 3.2].") == ["U", "A"]
    assert named("Lemma 2.1 of [A] and Lemma 2.1 of [U].") == ["A", "U"]
    assert named("Lemma 2.1 of [U, Section 3] and Lemma 2.1 of [A].") == ["U", "U", "A"]
    # Another work's citation, or two papers cited at once, names neither paper.
    assert named("[X, Lemma 2.1], as in [U].") == [None]
    assert named("Lemma 2.1 of [A] or [U].") == [None]
    assert named("[A]'s Lemma 2.1 and [Gauss, Lemma 3].") == ["A", None]
    # Each is then checked against the paper it names.
    from types import SimpleNamespace
    from prooflens import content
    papers = [SimpleNamespace(id="A", title="Odd squares"),
              SimpleNamespace(id="B", title="Triangle bounds")]
    tex = {"A": {"mode": "latex", "anchors": [{"env": "lemma", "number": "2.2"}]},
           "B": {"mode": "latex", "anchors": [{"env": "theorem", "number": "1.1"}]}}
    inv_claims = [{"id": "A:l22", "paper": "A", "kind": "lemma", "number": "Lemma 2.2",
                   "clauses": [{"spec": "PA.l22"}]},
                  {"id": "B:t11", "paper": "B", "kind": "theorem", "number": "Theorem 1.1",
                   "clauses": [{"spec": "PB.t11"}]}]
    full = [decl("Common.c", "[A, Lemma 2.2] and [B]'s Theorem 1.1.", module="Common"),
            decl("Common.d", "Lemma 2.2 of [B] and Lemma 2.2 of [A].", module="Common")]
    num = content.several(papers, tex, inv_claims, {}, full, [], None, None, [])
    assert [(o["source"]["declaration"], o["reference"], o.get("attributed"), o["status"])
            for o in num["references"]] == [
        ("Common.c", "Lemma 2.2", "A", "exact"), ("Common.c", "Theorem 1.1", "B", "exact"),
        ("Common.d", "Lemma 2.2", "B", "absent"), ("Common.d", "Lemma 2.2", "A", "exact")]


def test_several_papers_leave_an_unattributable_reference_unchecked():
    from types import SimpleNamespace
    from prooflens import content
    papers = [SimpleNamespace(id="A", title="One"), SimpleNamespace(id="B", title="Two")]
    tex = {p: {"mode": "latex", "anchors": [{"env": "theorem", "number": "1.1"}]}
           for p in ("A", "B")}
    inv_claims = [{"id": f"{p}:t", "paper": p, "kind": "theorem", "number": "Theorem 1.1",
                   "clauses": [{"spec": f"Spec.thm_{p.lower()}"}]} for p in ("A", "B")]
    full = [decl("Spec.thm_a", "Theorem 1.1.", module="Spec"),
            decl("Spec.shared", "Theorem 7.7.", module="Spec"),
            decl("Loose.x", "Theorem 8.8.", module="Loose")]
    notes = []
    num = content.several(papers, tex, inv_claims, {}, full, [], None, None, notes)
    by = {o["source"]["declaration"]: o for o in num["references"]}
    assert by["Spec.thm_a"]["attributed"] == "A" and by["Spec.thm_a"]["status"] == "exact"
    shared, loose = by["Spec.shared"], by["Loose.x"]
    assert shared["status"] == loose["status"] == "unchecked"
    assert "holds claims of papers A and B" in shared["detail"]
    assert "no claim of any paper" in loose["detail"]
    assert not nb.suspect(shared) and num["pattern"]["unchecked"] == 2
    assert any("2 of the Lean's references" in n for n in notes)


def test_several_papers_read_a_cite_as_a_bracket():
    # A `\cite` names a paper as a bracket does (#350): the `\cite` whose note holds the
    # number, or one after it before the next reference; one of several works names none.
    papers = [("U", ""), ("A", "")]

    def named(doc):
        return [nb.attribute(o, {}, papers)[0]
                for o in nb.find_references([decl("P.a", doc)], [])]

    assert named("Theorem 9.9 of \\cite{U}.") == named("\\cite[Lemma 2.1]{U}.") == ["U"]
    assert named("\\citet[Lemma 2.1]{ U }.") == named("\\cite[see][Lemma 2.1]{U}.") == ["U"]
    assert named("\\cite[Lemma 2.1, Lemma 2.2]{U}.") == ["U", "U"]
    assert named("\\cite[Lemma 2.1]{U} and \\cite[Lemma 3.2]{A}.") == ["U", "A"]
    assert named("Lemma 2.1 of \\cite{A} and Lemma 2.1 of \\cite{U}.") == ["A", "U"]
    assert named("Lemma 2.1 of \\cite[Section 3]{U} and Lemma 2.1 of \\cite{A}.") == \
        ["U", "U", "A"]
    assert named("\\cite[Lemma 2.1]{A,U}.") == named("Lemma 2.1 of \\cite{A, U}.") == [None]
    assert named("\\cite[Lemma 2.1]{Gauss} and Lemma 2.2 of \\cite{U}.") == [None, "U"]
    # Each is then checked against the paper it names.
    from types import SimpleNamespace
    from prooflens import content
    papers = [SimpleNamespace(id="A", title="Odd squares"),
              SimpleNamespace(id="B", title="Triangle bounds")]
    tex = {"A": {"mode": "latex", "anchors": [{"env": "lemma", "number": "2.2"}]},
           "B": {"mode": "latex", "anchors": [{"env": "theorem", "number": "1.1"}]}}
    inv_claims = [{"id": "A:l22", "paper": "A", "kind": "lemma", "number": "Lemma 2.2",
                   "clauses": [{"spec": "PA.l22"}]},
                  {"id": "B:t11", "paper": "B", "kind": "theorem", "number": "Theorem 1.1",
                   "clauses": [{"spec": "PB.t11"}]}]
    full = [decl("Common.c", "\\cite[Lemma 2.2]{A} and Theorem 1.1 of \\cite{B}.",
                 module="Common"),
            decl("Common.d", "\\cite[Lemma 2.2]{B} and \\cite[Lemma 2.2]{Gauss}.",
                 module="Common")]
    num = content.several(papers, tex, inv_claims, {}, full, [], None, None, [])
    assert [(o["source"]["declaration"], o["reference"], o.get("attributed"), o["status"])
            for o in num["references"]] == [
        ("Common.c", "Lemma 2.2", "A", "exact"), ("Common.c", "Theorem 1.1", "B", "exact"),
        ("Common.d", "Lemma 2.2", "B", "absent"), ("Common.d", "Lemma 2.2", None, "other-source")]


def test_formalization_rows_name_their_papers_declarations():
    from prooflens import formalization as fz
    fy = {"sources": [{"title": "Odd squares in arithmetic"},
                      {"title": "Triangle bounds in arithmetic"}],
          "alignment": {"statements": [
              {"source": "Theorem 2.1 (odd squares)", "lean": "PA.odd_sq"},
              {"source": "Theorem 1.1 (triangle bounds)", "lean": ["PB.bound", "PB.aux"]},
              {"source": "Theorem 3.1", "lean": "Shared.x"}]}}
    assert fz.paper_names(fy, "Odd squares") == {"PA.odd_sq"}
    assert fz.paper_names(fy, "Triangle bounds") == {"PB.bound", "PB.aux"}
    assert fz.paper_names({"sources": [{"title": "One"}]}, "One") == set()
