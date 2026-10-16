"""Links declared in a project's formalization.yaml (the mathlib-initiative standard)."""

import shutil

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import formalization as fz
from prooflens.simple import build_view, built_modules, save_link

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
