"""The semantic summary's readings of parts of claims and what a publication withholds (#479):
a workspace's reading of a clause or a requirement is recorded on its own, with the declaration of
the comparison it concerns, and counted apart from the readings of whole statements; a published
audit names what its publication settings withhold, on each paper and on a reading whose
question's words it leaves out, so that nothing withheld reads as not assessed. On synthetic
records; no Lean runs."""

import json

from test_semantic_summary import AUDITOR, finding, records, statement

from prooflens import published_work as pw
from prooflens import semantic
from prooflens.config import Publish

WS = "workspace:ws-111111111111"


def claims():
    """A claim of two clauses, a claim read on a requirement, and a claim read as a whole."""
    two = statement("P:two", links=["X.two"])
    two[1]["clauses"] = [{"name": "as printed", "spec": "X.Spec.printed"},
                         {"name": "corrected", "spec": "X.Spec.corrected"}]
    defn = statement("P:def", kind="definition")
    defn[1]["clauses"] = [{"name": "definition", "defs": ["X.Even", "X.Odd"]}]
    return [two, defn, statement("P:req", links=["X.req"]), statement("P:whole", links=["X.w"])]


def work():
    later = "2026-03-01T00:00:00Z"
    return {
        "P:two": [finding("f-printed", "changed", clause="as printed", basis="direct"),
                  finding("f-corrected", "full", clause="corrected"),
                  # A later reading of the same clause replaces the earlier one.
                  finding("f-corrected-2", "partial", clause="corrected", submitted_at=later),
                  # A finding with no coverage is no reading.
                  finding("f-note", clause="as printed", note="a note")],
        "P:def": [finding("f-def", "full", clause="definition", state="stale")],
        "P:req": [finding("f-req", "full", requirement="r1", basis="checked_bridge")],
        "P:whole": [finding("f-whole", "full", basis="direct")],
    }


def summary(alignments=()):
    index, chunks, works = records(claims(), work())
    works["P:req"]["readings"][0]["alignments"] = list(alignments)
    return semantic.summarise(index, chunks, works, author=AUDITOR), index


def test_a_part_s_reading_is_recorded_apart_with_the_declaration_it_concerns():
    al = {"id": "a1", "kind": "alignment", "claim": "P:req", "requirements": ["r1"],
          "lean": [{"decl": "X.req", "conclusion": True}]}
    (s, facts), _ = summary([al])
    two = facts["P:two"]
    # The whole statement is read only in part: counted as before.
    assert [r["count"] for r in two["readings"]] == ["clauses_only"]
    assert two["clause_readings"] == [
        {"set": WS, "clause": "as printed", "coverage": "changed", "basis": "direct",
         "currency": "current", "count": "changed", "decl": "X.Spec.printed"},
        {"set": WS, "clause": "corrected", "coverage": "partial", "basis": None,
         "currency": "current", "count": "partial", "decl": "X.Spec.corrected"}]
    # A definition's clause names its first definition; a reading made for other Lean is out of
    # date; a requirement names what it is aligned with.
    (d,) = facts["P:def"]["clause_readings"]
    assert (d["decl"], d["count"], d["coverage"]) == ("X.Even", "stale", "full")
    (r,) = facts["P:req"]["clause_readings"]
    assert (r["requirement"], r["decl"], r["basis"]) == ("r1", "X.req", "checked_bridge")
    # A claim read as a whole has no part readings.
    assert "clause_readings" not in facts["P:whole"]
    # Per set and unit, each claim once under each key it has a part counted under.
    table = s["papers"]["P"]["clause_coverage"][WS]["statements"]
    assert table == {"full": 1, "partial": 1, "changed": 1, "related": 0, "unresolved": 0,
                     "stale": 1}
    assert set(s["papers"]["P"]["clause_coverage"]) == {"audit", WS}
    assert sum(s["papers"]["P"]["clause_coverage"]["audit"]["statements"].values()) == 0


def test_a_requirement_aligned_with_nothing_names_no_declaration():
    (_, facts), _ = summary()
    (r,) = facts["P:req"]["clause_readings"]
    assert r["decl"] is None


def test_the_summary_with_parts_is_valid_and_optional():
    (s, facts), index = summary()
    for row in index["claims"]:
        row["semantic"] = facts[row["id"]]
    index["semantic"] = s
    index.update(schema="prooflens/manifest@1", findings={"total": {}, "general": []},
                 summary={}, classes={})
    from prooflens.published import semantic_part, take_semantic
    got = semantic_part(*take_semantic(json.loads(json.dumps(index))))
    assert got["state"] == "loaded"
    # A summary with no part readings has no table of them.
    index2, chunks2, works2 = records()
    del works2["P:a"]
    s2, _ = semantic.summarise(index2, chunks2, works2)
    assert "clause_coverage" not in s2["papers"]["P"]


def test_a_publication_names_the_prose_it_withholds_never_quoting_it():
    rec = {"id": "f1", "kind": "finding", "claim": "P:a", "coverage": "unresolved",
           "question": "WITHHELD-QUESTION", "note": "WITHHELD-NOTE", "state": "submitted",
           "evidence": []}
    closed = Publish(pdf=False, source_text=False, lean=False, reviews=False)
    out = pw.public_record(rec, closed, {}, {"f1"})
    assert out["withheld"] == ["note", "question"]
    assert "WITHHELD" not in json.dumps(out)
    opened = pw.public_record(rec, Publish(reviews=True), {}, {"f1"})
    assert "withheld" not in opened and opened["question"] == "WITHHELD-QUESTION"
    # Nothing to withhold, nothing named.
    assert "withheld" not in pw.public_record({**rec, "question": None, "note": ""}, closed, {},
                                              {"f1"})


def test_a_withheld_question_is_said_so_and_its_reading_still_counts(tmp_path):
    work = {"P:e": [finding("f-open", "unresolved", withheld=["note", "question"])]}
    index, chunks, works = records(work=work)
    s, facts = semantic.summarise(index, chunks, works)
    (r,) = [x for x in facts["P:e"]["readings"] if x["set"] == WS]
    assert r["count"] == "unresolved" and r["withheld"] == ["question"]
    assert "question" not in r
    assert s["papers"]["P"]["coverage"][WS]["statements"]["unresolved"] == 1
    # A reading with nothing withheld says nothing of it.
    index, chunks, works = records(work={"P:e": [finding("f-open", "unresolved")]})
    _, facts = semantic.summarise(index, chunks, works)
    assert "withheld" not in [x for x in facts["P:e"]["readings"] if x["set"] == WS][0]


def test_a_published_summary_names_what_each_paper_withholds(tmp_path):
    index, chunks, works = records()
    data = tmp_path / "data"
    (data / "claims").mkdir(parents=True)
    for row in index["claims"]:
        (data / "claims" / row["file"]).write_text(json.dumps(chunks[row["file"]]))
    (data / "index.json").write_text(json.dumps(index))
    plain = semantic.refresh(data, AUDITOR)
    assert "withheld" not in plain["papers"]["P"]
    got = semantic.refresh(data, AUDITOR, {"P": ["reviews", "unknown", "source_text"],
                                           "Q": ["lean"]})
    assert got["papers"]["P"]["withheld"] == ["source_text", "reviews"]
    assert "Q" not in got["papers"]
    assert got["digest"] != plain["digest"]
    written = json.loads((data / "index.json").read_text())
    assert written["semantic"] == got
    # Nothing withheld: no field, and the digest of the records alone.
    assert semantic.refresh(data, AUDITOR, {"P": []})["digest"] == plain["digest"]


def test_the_words_are_the_vocabulary_s():
    v = semantic.VOCABULARY
    assert set(v["clause_coverage"]) == set(semantic.CLAUSE_KEYS)
    assert set(v["withheld"]) == {"question", *semantic.WITHHOLDS}
    assert all(w["label"] and w["explanation"] for d in ("clause_coverage", "withheld")
               for w in v[d].values())
    schema = json.loads((semantic.files("prooflens") / "data/schema/manifest-index.schema.json")
                        .read_text())
    assert schema["$defs"]["semanticClauseCoverage"]["required"] == list(semantic.CLAUSE_KEYS)
