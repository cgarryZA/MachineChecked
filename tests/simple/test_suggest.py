"""Suggestions (`simple.suggest`) on a synthetic index: what ranks first, and why."""

from prooflens import formalization as fz
from prooflens.simple import SuggestContext, suggest


def decl(name, kind="theorem", doc=None, type_="True", module=None, line=1):
    return {"name": name, "kind": kind, "doc": doc, "type": type_,
            "module": module or name.rsplit(".", 1)[0], "range": {"line": line}}


THM = {"kind": "theorem", "number": "Theorem 1.1", "title": None, "label": None}


def names(out):
    return [s["name"] for s in out]


def test_a_theorem_citing_the_claim_outranks_definitions_citing_it():
    index = [decl(f"P.Def{i}", "def", doc="The statement of Theorem 1.1.") for i in range(4)]
    index.append(decl("P.main", doc="Theorem 1.1 of the paper."))
    assert names(suggest(THM, index))[0] == "P.main"


def test_a_theorem_proving_a_cited_definition_ranks_first():
    index = [decl("P.Statement.breakdown", "def", doc="The statement of Theorem 1.1."),
             decl("P.other", doc="Used in the proof of Theorem 1.1."),
             decl("P.theorem_1_1", type_="P.Statement.breakdown")]
    out = suggest(THM, index)
    assert names(out)[0] == "P.theorem_1_1" and "it proves" in out[0]["why"]


def test_ties_are_broken_by_name_not_index_order():
    index = [decl("P.zeta", doc="Theorem 1.1."), decl("P.alpha", doc="Theorem 1.1.")]
    assert names(suggest(THM, index)) == names(suggest(THM, list(reversed(index)))) == \
        ["P.alpha", "P.zeta"]


def test_a_citation_from_another_papers_namespace_is_ranked_low_and_says_so():
    fy = {"sources": [{"title": "Blowup for Navier-Stokes", "relationship": "formalizes"},
                      {"title": "Blowup for Euler", "relationship": "formalizes"}],
          "alignment": {"statements": [
              {"source": "Theorem 1.1 (Navier-Stokes)", "lean": "NS.main"},
              {"source": "Theorem 1.1 (Euler)", "lean": "Euler.main"}]}}
    foreign = fz.foreign_roots(fy, "Blowup for Euler")
    assert foreign == {"NS"}
    index = [decl("NS.helper", doc="Theorem 1.1."), decl("Euler.lemma", doc="See Theorem 1.1.")]
    out = suggest(THM, index, ctx=SuggestContext(index, foreign=foreign))
    assert names(out) == ["Euler.lemma", "NS.helper"]
    assert "another paper" in out[1]["why"] and out[1]["score"] < out[0]["score"]


def test_a_module_docstring_suggests_its_last_theorem(tmp_path):
    (tmp_path / "P").mkdir()
    (tmp_path / "P" / "Slot.lean").write_text("/-! # Slots\nThis file proves Theorem 1.1. -/\n")
    index = [decl("P.Slot.first", module="P.Slot", line=3),
             decl("P.Slot.main", module="P.Slot", line=40),
             decl("P.Slot.aux", "def", module="P.Slot", line=50)]
    out = suggest(THM, index, ctx=SuggestContext(index, root=tmp_path))
    assert names(out) == ["P.Slot.main"] and "module's docstring" in out[0]["why"]


def test_shared_title_words_must_include_a_rare_one():
    claim = {"kind": "lemma", "number": "Lemma 6.3", "title": "Number of relevant labels",
             "label": None}
    common = [decl(f"P.thing{i}_labels_number") for i in range(20)]
    rare = decl("P.relevant_labels_bound")
    out = suggest(claim, common + [rare])
    assert names(out) == ["P.relevant_labels_bound"]
