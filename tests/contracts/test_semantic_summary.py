"""The semantic summary (#129, `semantic.py`), on synthetic records: explicit units and
denominators, coverage and basis as separate dimensions, unresolved, stale and unassessed kept
apart, clause-level work never counted as a whole statement, each reviewer and workspace a set of
its own, and no status changed. Also: zero configuration's `check` computes the same summary as
the site it would write, and a published audit's summary is computed from its published
records."""

import copy
import json

import pytest

from prooflens import semantic
from prooflens.schemas import validate
from prooflens.status import fields

AUDITOR = "A. Auditor"
QUESTION = "Does any Lean result state the claim for real numbers?"


def link(*names):
    return [{"name": n} for n in names]


def reading(coverage, basis=None, **more):
    return {"source": "confirmed", "coverage": coverage, "basis": basis, "refs": [],
            "argument": None, "next_step": None, "bridge": None, "question": None,
            "would_decide": None, "confidence": None, "note": "", "by": AUDITOR, **more}


def bridge(state):
    return {"theorem": "X.bridge", "target": "X.Spec.target", "state": state, "reasons": [],
            "pinned": {}, "current": {}}


def report(who, current, coverage=None, verdict="faithful", revealed=(), basis=None,
           at="2026-01-01T00:00:00Z"):
    return {"reviewer": {"id": f"human:{who}", "kind": "human", "name": who,
                         "identity": "self-declared"},
            "revealed": list(revealed), "verdict": {"group": "matches", "value": verdict,
                                                    "detail": ""},
            "submitted_at": at, "current": current,
            "correspondence": {"coverage": coverage, "basis": basis, "refs": [],
                               "argument": None, "next_step": None, "bridge": None,
                               "question": None, "would_decide": None} if coverage else None}


def statement(cid, kind="theorem", links=(), cor=None, reviews=()):
    return cid, {"kind": kind, "unit": "statement", "links": link(*links),
                 "correspondence": cor, "reviews": list(reviews), "clauses": []}


def step(cid, unit, links=(), cor=None, review="unreviewed"):
    return cid, {"kind": "equation", "unit": unit, "links": link(*links), "correspondence": cor,
                 "reviews": [], "clauses": [],
                 "step": {"links": link(*links), "correspondence": cor,
                          "review": {"state": review, "finding": None, "reports": []}}}


CLAIMS = [
    statement("P:a", links=["X.a", "X.a"], cor=reading("full", "direct"),
              reviews=[report("R1", True, "full", basis="direct")]),
    statement("P:b", links=["X.a", "X.b"], cor=reading("full", "reviewed_composition"),
              reviews=[report("R1", False, "full"),
                       report("R2", True, "partial", verdict="narrower", revealed=["Lean"])]),
    statement("P:c", links=["X.c"], cor=reading("full", "checked_bridge", bridge=bridge("checked"))),
    statement("P:d", links=["X.d"],
              cor=reading("full", "checked_bridge", bridge=bridge("unchecked"))),
    statement("P:e", cor=reading("unresolved", question=QUESTION)),
    statement("P:f", links=["X.f"]),
    statement("P:j", links=["X.j"], cor=reading("full", "checked_bridge", bridge=bridge("stale"))),
    statement("P:k", links=["X.k"], cor=reading("verified")),
    statement("P:n", kind="notation", links=["X.n"]),
    step("P:eq", "proof-equation", ["X.a"], {"source": "confirmed", "coverage": "partial",
                                             "basis": "direct", "note": "", "by": AUDITOR},
         review="gap"),
    step("P:pass", "proof-passage", review="undetermined"),
]


def finding(fid, coverage=None, state="current", **more):
    return {"id": fid, "kind": "finding", "state": "submitted", "in_force": True,
            "submitted_at": "2026-02-01T00:00:00Z", "currency": {"state": state, "changes": []},
            **({"coverage": coverage} if coverage else {}), **more}


WORK = {
    # A finding on one clause of P:a: not a reading of the whole statement.
    "P:a": [finding("f1", "full", clause="first", basis="direct")],
    "P:f": [finding("f2", "full", basis="direct"),
            finding("f3", difference={"feature": "domain", "outcome": "difference"})],
}


def records(claims=CLAIMS, work=WORK):
    rows, chunks = [], {}
    for cid, ch in claims:
        rows.append({"id": cid, "paper": "P", "file": cid + ".json", "kind": ch["kind"],
                     "unit": ch["unit"], **fields("link.checked" if ch["links"] else "link.none")})
        chunks[cid + ".json"] = ch
    index = {"release": "v-synthetic", "evidence": "e" * 64,
             "project": {"repository": "synthetic/alpha", "commit": "c" * 40},
             "papers": [{"id": "P", "revision": "c" * 40,
                         "paper_version": {"id": "manuscript:ccccccc"}}],
             "claims": rows}
    works = {cid: {"schema": "prooflens/published-work@1", "claim": cid, "readings": [
        {"workspace": "ws-111111111111", "mode": "independent",
         "reviewer": {"id": "human:W", "kind": "human", "name": "W"}, "findings": fs}]}
        for cid, fs in work.items()}
    return index, chunks, works


@pytest.fixture
def summary():
    index, chunks, works = records()
    return semantic.summarise(index, chunks, works, author=AUDITOR)


def test_units_and_denominators_are_explicit(summary):
    s, _ = summary
    inv = s["papers"]["P"]["inventory"]
    # A declaration linked twice to one statement is one link; notation and proof steps are
    # counted apart from the statements.
    assert inv["statements"] == {"records": 8, "linked": 7, "links": 8, "declarations": 7}
    assert inv["notation"] == {"records": 1, "linked": 1, "links": 1, "declarations": 1}
    assert inv["proof_steps"] == {"records": 2, "linked": 1, "links": 1, "declarations": 1}
    assert (inv["proof_equations"], inv["proof_passages"]) == (1, 1)
    assert s["audit"] == {"author": AUDITOR, "release": "v-synthetic", "evidence": "e" * 64,
                          "project": {"repository": "synthetic/alpha", "commit": "c" * 40}}
    assert (s["papers"]["P"]["revision"], s["papers"]["P"]["paper_version"]) == (
        "c" * 40, "manuscript:ccccccc")


def test_coverage_and_basis_are_separate_dimensions(summary):
    s, facts = summary
    p = s["papers"]["P"]
    # Each statement once: four full (direct, composition, checked bridge, and a bridge Lean
    # does not check), one unresolved and unlinked, one out of date, two not assessed (one with
    # an unknown coverage word).
    assert p["coverage"]["audit"]["statements"] == {
        "full": 4, "partial": 0, "changed": 0, "related": 0, "unresolved": 1,
        "not_recorded": 0, "stale": 1, "clauses_only": 0, "not_assessed": 2}
    assert sum(p["coverage"]["audit"]["statements"].values()) == 8
    # The same coverage, different bases; a bridge Lean does not check counts as the
    # composition it reads as, and says what it was recorded as.
    assert p["basis"]["audit"]["statements"] == {
        "direct": 1, "reviewed_composition": 2, "checked_bridge": 1, "unspecified": 1}
    d = facts["P:d"]["readings"][0]
    assert (d["count"], d["basis"], d["recorded_basis"]) == ("full", "reviewed_composition",
                                                             "checked_bridge")
    assert p["currency"]["audit"]["statements"] == {"current": 1, "unchecked": 0,
                                                    "unpinned": 4, "stale": 1}
    # The stale reading keeps what it recorded, for display, and is counted as out of date.
    j = facts["P:j"]["readings"][0]
    assert (j["count"], j["coverage"], j["basis"]) == ("stale", "full", None)
    # Notation and proof steps have their own distributions.
    assert p["coverage"]["audit"]["notation"]["not_assessed"] == 1
    assert p["coverage"]["audit"]["proof_steps"]["partial"] == 1
    assert p["coverage"]["audit"]["proof_steps"]["not_assessed"] == 1


def test_unlinked_unresolved_work_is_visible(summary):
    s, facts = summary
    e = facts["P:e"]
    assert e["declarations"] == 0
    assert e["readings"] == [{"set": "audit", "coverage": "unresolved", "basis": None,
                              "currency": "unpinned", "count": "unresolved", "by": AUDITOR,
                              "question": QUESTION}]
    assert "open-question" in e["findings"]
    assert s["papers"]["P"]["findings"]["statements"]["open-question"] == 1


def test_each_reviewer_and_workspace_is_a_set_of_its_own(summary):
    s, facts = summary
    assert [x["id"] for x in s["sets"]] == ["audit", "review:human:R1", "review:human:R2",
                                            "workspace:ws-111111111111"]
    assert s["selected"] == "audit" and s["sets"][0]["by"] == [AUDITOR]
    p = s["papers"]["P"]["coverage"]
    # R1's reading of P:b is out of date; R2's is current: neither is combined with the other.
    assert (p["review:human:R1"]["statements"]["full"],
            p["review:human:R1"]["statements"]["stale"]) == (1, 1)
    assert p["review:human:R2"]["statements"]["partial"] == 1
    assert p["review:human:R2"]["statements"]["full"] == 0
    b = {r["set"]: r for r in facts["P:b"]["readings"]}
    assert (b["review:human:R1"]["count"], b["review:human:R2"]["count"]) == ("stale", "partial")
    assert b["review:human:R2"]["provenance"] == "informed"
    assert {r["set"]: r["provenance"] for r in facts["P:a"]["readings"]
            if r.get("provenance")} == {"review:human:R1": "independent",
                                        "workspace:ws-111111111111": "independent"}
    # The review of a statement: P:a has a current independent review; P:b only an informed one.
    assert (facts["P:a"]["review"], facts["P:b"]["review"]) == ("independent", "informed")
    assert s["papers"]["P"]["review"]["statements"] == {
        "independent": 1, "author": 0, "informed": 1, "stale": 0, "unchecked": 0, "none": 6}
    assert s["papers"]["P"]["review"]["proof_steps"] == {
        "holds": 0, "gap": 1, "false": 0, "undetermined": 1, "stale": 0, "unreviewed": 0}


def test_clause_level_work_is_not_a_whole_statement(summary):
    s, facts = summary
    ws = s["papers"]["P"]["coverage"]["workspace:ws-111111111111"]["statements"]
    # P:a's only finding is on a clause: it counts as clauses only, never as full.
    assert (ws["full"], ws["clauses_only"], ws["not_assessed"]) == (1, 1, 6)
    a = {r["set"]: r for r in facts["P:a"]["readings"]}["workspace:ws-111111111111"]
    assert (a["count"], a["coverage"], a["clauses"]) == ("clauses_only", None, 1)


def test_finding_categories(summary):
    s, facts = summary
    assert facts["P:b"]["findings"] == ["other-difference"]
    assert facts["P:f"]["findings"] == ["input-restriction"]
    assert facts["P:eq"]["findings"] == ["printed-step"]
    assert facts["P:pass"]["findings"] == ["open-question"]
    f = s["papers"]["P"]["findings"]
    assert f["statements"]["input-restriction"] == 1 and f["proof_steps"]["printed-step"] == 1


def test_formal_counts_are_kept_apart_and_no_status_changes():
    index, chunks, works = records()
    before = copy.deepcopy([(r["status_code"], r["status"], r["class"]) for r in index["claims"]])
    s = semantic.apply(index, chunks, works)
    assert [(r["status_code"], r["status"], r["class"]) for r in index["claims"]] == before
    assert s["papers"]["P"]["formal"]["statements"] == {"link.checked": 7, "link.none": 1}
    assert all("semantic" in r for r in index["claims"])
    validate({"schema": "prooflens/manifest@1", "release": "v-synthetic", "evidence": "e" * 64,
              "papers": [{"id": "P", "mode": "latex", "pdf": None}], "summary": {},
              "classes": {}, "findings": {},
              "claims": [{**r, "counts": {}} for r in index["claims"]], "semantic": s},
             "manifest-index")


def test_a_workspace_that_records_no_mode_or_reviewer_is_still_described():
    index, chunks, works = records()
    for w in works.values():
        for rd in w["readings"]:
            rd.pop("mode"), rd.pop("reviewer")
    s = semantic.apply(index, chunks, works)
    assert s["sets"][-1] == {"id": "workspace:ws-111111111111", "kind": "workspace",
                             "workspace": "ws-111111111111", "mode": None, "reviewer": {}}
    a = index["claims"][0]["semantic"]["readings"][-1]
    assert a == {"set": "workspace:ws-111111111111", "coverage": None, "basis": None,
                 "currency": None, "count": "clauses_only", "clauses": 1}
    validate({"schema": "prooflens/manifest@1", "release": "v-synthetic", "evidence": "e" * 64,
              "papers": [{"id": "P", "mode": "latex", "pdf": None}], "summary": {},
              "classes": {}, "findings": {},
              "claims": [{**r, "counts": {}} for r in index["claims"]], "semantic": s},
             "manifest-index")


def test_a_reading_alone_changes_the_digest():
    index, chunks, works = records()
    first, _ = semantic.summarise(index, chunks, works)
    chunks["P:e.json"]["correspondence"]["question"] = "Another question."
    second, _ = semantic.summarise(index, chunks, works)
    assert first["papers"] == second["papers"] and first["digest"] != second["digest"]
    # The same records in another build (another release and evidence record) have the same
    # digest: it is of what is counted, not of the audit's identity.
    other, _ = semantic.summarise({**index, "release": "v-other", "evidence": "f" * 64},
                                  chunks, works)
    assert other["digest"] == second["digest"] and other["audit"] != second["audit"]


def test_a_full_assessment_reads_its_clauses():
    def claim(cid, *clauses, kind="theorem"):
        return cid, {"kind": kind, "unit": "statement", "clauses": list(clauses)}

    def clause(review, spec="X.s", stale=False):
        return {"spec": spec, "defs": ["X.d"], "review": review,
                "spec_review": {"state": "stale" if stale else "reviewed"},
                "def_reviews": {"X.d": {"state": "reviewed"}}}

    claims = [claim("T:ok", clause("reviewed")),
              claim("T:author", clause("reviewed"), clause("author-reviewed", "X.t")),
              claim("T:stale", clause("reviewed"), clause("pending", "X.u", stale=True)),
              claim("T:part", clause("reviewed"), clause("pending", "X.v")),
              claim("T:unrun", clause("unknown")),
              claim("T:scope")]
    rows = [{"id": cid, "paper": "T", "file": cid, "kind": "theorem", "unit": "statement",
             **fields("formal.accepted")} for cid, _ in claims]
    s, facts = semantic.summarise({"claims": rows, "papers": []}, dict(claims))
    assert {k: f["review"] for k, f in facts.items()} == {
        "T:ok": "independent", "T:author": "author", "T:stale": "stale", "T:part": "none",
        "T:unrun": "unchecked", "T:scope": "none"}
    # A full assessment's declarations are its clauses' propositions and definitions; no
    # statement has a coverage reading.
    assert s["papers"]["T"]["inventory"]["statements"] == {"records": 6, "linked": 5,
                                                           "links": 13, "declarations": 5}
    assert s["papers"]["T"]["coverage"]["audit"]["statements"]["not_assessed"] == 6


def test_refresh_counts_the_published_records(tmp_path):
    index, chunks, works = records()
    data = tmp_path / "data"
    (data / "claims").mkdir(parents=True)
    (data / "work").mkdir()
    for row in index["claims"]:
        chunk = dict(chunks[row["file"]])
        if row["id"] in works:
            chunk["work"] = "work/" + row["file"]
            (data / "work" / row["file"]).write_text(json.dumps(works[row["id"]]))
        (data / "claims" / row["file"]).write_text(json.dumps(chunk))
    (data / "index.json").write_text(json.dumps(index))
    s = semantic.refresh(data, AUDITOR)
    assert s == semantic.summarise(index, chunks, works, AUDITOR)[0]
    written = json.loads((data / "index.json").read_text())
    assert written["semantic"] == s and written["claims"][0]["semantic"]["unit"] == "statements"
    # A record the published data does not carry is not counted.
    (data / "work" / "P:f.json").unlink()
    assert "workspace:ws-111111111111" in [x["id"] for x in semantic.refresh(data)["sets"]]
    assert semantic.refresh(data)["papers"]["P"]["coverage"]["workspace:ws-111111111111"][
        "statements"]["full"] == 0


def test_the_terminal_summary_names_its_units(summary):
    lines = semantic.text(summary[0])
    assert lines[0] == "semantic summary of paper P (the audit's readings):"
    assert "  8 statements, 7 linked to 7 declarations" in lines
    assert ("    correspondence: every clause (4); unresolved (1); out of date (1); "
            "not assessed (2)") in lines
    assert ("    basis: in one Lean statement (1); by a reviewer's composition (2); "
            "through a checked bridge (1); basis not recorded (1)") in lines
    assert "  1 notation record, 1 linked to 1 declaration" in lines
    assert "  2 proof steps, 1 linked to 1 declaration" in lines
    assert not any("%" in line for line in lines)
    assert lines[-1].startswith("  3 further sets of readings")


def test_zero_configuration_check_computes_the_summary_of_its_site(tmp_path):
    """`check` (no site) and the site `build` writes give the same summary."""
    from prooflens.simple import write_view_site

    def claim(key, number, links=(), cor=None, reviews=(), kind="theorem"):
        return {"id": f"P:{key}", "key": key, "paper": "P", "number": number, "title": "",
                "kind": kind, "scope": "formal", "location": "main.tex", "source_sha256": "s",
                **fields("link.checked" if links else "link.none"),
                "links": [{"name": n, **fields("link.checked"), "source": "confirmed"}
                          for n in links],
                "suggestions": [], "correspondence": cor, "reviews": list(reviews),
                "references": []}

    body = {"mode": "simple", "paper": "paper/main.tex", "title": "A synthetic paper",
            "notes": [], "project": {"name": "synthetic", "libs": [], "built": 0, "unbuilt": 0},
            "commit": None, "author": AUDITOR, "issues": None, "site_url": None,
            "formalization": None, "pdf_sha256": None, "tex": {"mode": "latex", "anchors": []},
            "decls": {}, "index": [], "module_docs": [], "numbering": None,
            "claims": [claim("thm:a", "Theorem 1", ["X.a"], reading("full", "direct"),
                             [report("R1", True, "full")]),
                       claim("thm:e", "Theorem 2", (), reading("unresolved", question=QUESTION)),
                       claim("not:n", "Notation 1", ["X.n"], kind="notation")]}
    index = write_view_site({"body": body, "pdf": None}, tmp_path / "site", None)
    summary, facts = semantic.of_view(body)
    written = json.loads((tmp_path / "site" / "data" / "index.json").read_text())
    assert written["semantic"] == summary == index["semantic"]
    assert {c["id"]: c["semantic"] for c in written["claims"]} == facts
    assert summary["audit"]["author"] == AUDITOR
    assert summary["papers"]["P"]["coverage"]["audit"]["statements"]["unresolved"] == 1
