"""Links declared in a project's formalization.yaml (the mathlib-initiative standard)."""

import shutil

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import formalization as fz
from prooflens.simple import build_view, built_modules, correspondence, load_links, save_link

PLAIN = ROOT / "examples" / "plain-paper"

TWO_SOURCES = {
    "version": "v0.4",
    "sources": [{"title": "Blowup for the heat flow", "relationship": "formalizes"},
                {"title": "Blowup for the wave flow", "relationship": "formalizes"}],
    "review": {"status": "self-assessed"},
    "automation": {"methods": [{"method": "manual"}]},
    "alignment": {"statements": [
        {"source": "Theorem 1.1 (heat flow)", "lean": "Heat.main", "status": "proved"},
        {"source": "Theorem 1.1 (wave flow)", "lean": ["Wave.main", "Wave.main'"]},
        {"source": "Corollary 10.6 (heat flow, periodic)", "lean": "Heat.periodic"},
        {"source": "an informal remark", "lean": "Heat.other"}]},
}


def test_statements_are_read_from_the_suggested_shape():
    st = fz.statements(TWO_SOURCES)
    assert [(s["kind"], s["number"], s["lean"]) for s in st] == [
        ("theorem", "1.1", ["Heat.main"]), ("theorem", "1.1", ["Wave.main", "Wave.main'"]),
        ("corollary", "10.6", ["Heat.periodic"])]


def test_with_several_sources_a_statement_must_say_which():
    heat = fz.links_for(TWO_SOURCES, "theorem", "Theorem 1.1", "Blowup for the heat flow")
    assert [s["lean"] for s in heat] == [["Heat.main"]]
    wave = fz.links_for(TWO_SOURCES, "corollary", "Corollary 10.6", "Blowup for the wave flow")
    assert wave == []


def test_summary_reports_the_projects_own_review_status():
    s = fz.summary(TWO_SOURCES)
    assert s["review_status"] == "self-assessed" and s["methods"] == ["manual"]
    assert len(s["sources"]) == 2


def test_a_malformed_file_is_reported_not_raised(tmp_path):
    (tmp_path / "formalization.yaml").write_text("alignment: [unclosed\n")
    assert "error" in fz.load(tmp_path)


@pytest.fixture
def plain(tmp_path):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"),
        symlinks=True)
    return dst


@needs_lean
@needs_tex
def test_declared_links_reach_the_view(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    (plain / "formalization.yaml").write_text(
        'version: "v0.4"\nreview:\n  status: "self-assessed"\nalignment:\n  statements:\n'
        '    - source: "Theorem 2"\n      lean: "Plain.oddSum_eq_sq"\n')
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                      log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["number"] == "Theorem 2")
    assert [(l["name"], l["source"]) for l in c["links"]] == [
        ("Plain.oddSum_eq_sq", "formalization.yaml")]
    assert c["status"] == "linked: Lean proof incomplete (sorry)"
    assert view["body"]["formalization"]["review_status"] == "self-assessed"
    # A link rejected in the reader stays rejected.
    save_link(plain, "paper/main.tex", "thm:sum-odd", None, rejected=["Plain.oddSum_eq_sq"])
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                      log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["number"] == "Theorem 2")
    assert c["links"] == []


def test_a_rows_note_is_kept():
    fy = {"alignment": {"statements": [
        {"source": "Lemma 2.1", "lean": "A.b", "note": " Partial: the bound has one more derivative. "},
        {"source": "Lemma 2.2", "lean": "A.c", "note": 3}]}}
    assert [s["note"] for s in fz.statements(fy)] == [
        "Partial: the bound has one more derivative.", ""]


def test_the_auditors_note_comes_before_the_projects():
    claim = {"declared_notes": ["The project's note."]}
    entry = {"lean": ["A.b"], "coverage": "changed", "confidence": "high",
             "note": "The bound needs n + 5 derivatives where the paper has m + 4.", "by": "A. Auditor"}
    assert correspondence(claim, entry) == {
        "source": "confirmed", "coverage": "changed", "basis": None, "refs": [], "argument": None,
        "next_step": None, "bridge": None, "question": None, "would_decide": None, "confidence": "high",
        "note": "The bound needs n + 5 derivatives where the paper has m + 4.", "by": "A. Auditor"}
    # Unknown words are dropped, never shown as given.
    odd = correspondence(claim, {"lean": ["A.b"], "coverage": "verified", "confidence": "sure",
                                 "note": "x"})
    assert (odd["coverage"], odd["confidence"]) == (None, None)
    assert correspondence(claim, {"lean": ["A.b"], "coverage": "unresolved"})["coverage"] == \
        "unresolved"
    # Without an auditor's entry, the project's formalization.yaml notes are shown as the project's.
    assert correspondence(claim, {})["source"] == "formalization.yaml"
    assert correspondence({}, {}) is None
    assert correspondence(claim, {"lean": ["A.b"]}) is None


@needs_lean
@needs_tex
def test_a_note_is_shown_beside_the_links_and_changes_no_status(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    (plain / "formalization.yaml").write_text(
        'version: "v0.4"\nalignment:\n  statements:\n'
        '    - source: "Theorem 2"\n      lean: "Plain.oddSum_eq_sq"\n'
        '      note: "States the sum formula for n >= 1 only."\n')

    def theorem2():
        view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                          log=lambda m: None)
        return next(c for c in view["body"]["claims"] if c["number"] == "Theorem 2")

    c = theorem2()
    status = c["status"]
    assert c["correspondence"]["source"] == "formalization.yaml"
    assert c["correspondence"]["note"] == "States the sum formula for n >= 1 only."
    data = load_links(plain)
    data.setdefault("papers", {})["paper/main.tex"] = {"thm:sum-odd": {
        "lean": ["Plain.oddSum_eq_sq"], "coverage": "partial", "confidence": "medium",
        "note": "The case n = 0 is not stated.", "by": "A. Auditor"}}
    (plain / "machinechecked.links.json").write_text(__import__("json").dumps(data))
    c = theorem2()
    assert (c["correspondence"]["source"], c["correspondence"]["coverage"]) == ("confirmed", "partial")
    assert c["status"] == status
    # Linking other declarations drops the note written for the old ones.
    save_link(plain, "paper/main.tex", "thm:sum-odd", ["Plain.oddSum_eq_sq", "Plain.oddSum"])
    entry = load_links(plain)["papers"]["paper/main.tex"]["thm:sum-odd"]
    assert "note" not in entry and "coverage" not in entry


@needs_lean
@needs_tex
def test_an_exported_review_is_shown_and_changes_no_status(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    import json
    save_link(plain, "paper/main.tex", "thm:sum-odd", ["Plain.oddSum_eq_sq"])

    def theorem2():
        view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                          log=lambda m: None)
        return next(c for c in view["body"]["claims"] if c["number"] == "Theorem 2"), view

    c, _ = theorem2()
    rec = c["links"][0]["record"]
    status, fp = c["status"], rec.get("fingerprint") or rec["decl"]["fingerprint"]
    report = {"schema": "prooflens/review-report@1",
              "unit": {"id": "link:" + c["key"], "kind": "link"},
              "pins": {"fingerprints": {"Plain.oddSum_eq_sq": fp}},
              "reviewer": {"id": "human:a-reviewer", "kind": "human", "name": "A. Reviewer",
                           "identity": "self-declared"},
              "reading": {"text": "The sum of the first n odd numbers is n^2.",
                          "locked_at": "2026-01-01T00:00:00Z"},
              "comparison": {"text": "Same statement.", "checklist": {}},
              "verdict": {"group": "matches", "value": "exact", "detail": ""},
              "submitted_at": "2026-01-01T00:05:00Z"}
    (plain / "machinechecked-reviews").mkdir()
    (plain / "machinechecked-reviews" / "a.json").write_text(json.dumps(
        {"schema": "prooflens/review-reports@1", "reports": [report, report]}))
    (plain / "machinechecked-reviews" / "b.json").write_text("not json")
    c, view = theorem2()
    assert c["status"] == status
    assert [(r["verdict"]["value"], r["current"], r["reviewer"]["name"]) for r in c["reviews"]] == [
        ("exact", True, "A. Reviewer")]
    assert any("b.json was skipped" in n for n in view["body"]["notes"])
    # Linking other declarations makes the review one of other declarations.
    save_link(plain, "paper/main.tex", "thm:sum-odd", ["Plain.oddSum_eq_sq", "Plain.oddSum"])
    c, _ = theorem2()
    assert [r["current"] for r in c["reviews"]] == [False]
