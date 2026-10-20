"""Zero-configuration mode on an ordinary Lean project with a paper."""

import json
import shutil

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import (build_view, built_modules, find_lake_root, find_papers, lib_names,
                              links_file, save_link, save_settings, write_view_site)

PLAIN = ROOT / "examples" / "plain-paper"


@pytest.fixture
def plain(tmp_path):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(".prooflens", ".machinechecked", "prooflens.links.json",
                                                    "machinechecked.links.json"),
                    symlinks=True)
    return dst


def test_discovery(plain):
    assert find_lake_root(plain / "paper") == plain
    assert lib_names(plain) == ["Plain"]
    assert [p.relative_to(plain).as_posix() for p in find_papers(plain)] == ["paper/main.tex"]


@needs_lean
@needs_tex
def test_view_suggests_then_links(plain):
    built, unbuilt = built_modules(plain, ["Plain"])
    if not built:
        pytest.skip("the plain example is not built")
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked", log=lambda m: None)
    claims = {c["number"]: c for c in view["body"]["claims"]}
    assert set(claims) == {"Theorem 1", "Theorem 2", "Theorem 3", "Lemma 4"}
    why = {n: [(s["name"], s["why"]) for s in c["suggestions"]] for n, c in claims.items()}
    # A \lean{…} tag is a link its author wrote into the source; a commented-out tag is none.
    assert [(l["name"], l["source"]) for l in claims["Theorem 1"]["links"]] == [
        ("Plain.odd_add_odd", "paper")]
    assert claims["Theorem 1"]["status"] == "linked: Lean proof checked"
    assert claims["Lemma 4"]["links"] == []
    # Its statement's content first, then the docstring's citation, each said.
    assert why["Theorem 3"][0][0] == "Plain.sq_odd"
    assert [r["signal"] for r in claims["Theorem 3"]["suggestions"][0]["reasons"]] == \
        ["content", "number"]
    assert why["Theorem 3"][0][1].startswith("shares square, number, odd") and \
        why["Theorem 3"][0][1].endswith("; its docstring cites Theorem 3")
    assert why["Theorem 2"][0][0] == "Plain.oddSum_eq_sq"
    assert why["Lemma 4"] == []
    # A suggestion is only a suggestion until someone links.
    assert claims["Theorem 2"]["status"] == "suggested link, not confirmed"

    save_link(plain, "paper/main.tex", "thm:sum-odd", ["Plain.oddSum_eq_sq"])
    save_link(plain, "paper/main.tex", "lem:open", ["Plain.no_such_theorem"])
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked", log=lambda m: None)
    st = {c["number"]: c["status"] for c in view["body"]["claims"]}
    assert st["Theorem 2"] == "linked: Lean proof incomplete (sorry)"
    assert st["Lemma 4"] == "linked: Lean declaration not found"
    links = json.loads((plain / "machinechecked.links.json").read_text())
    assert links["papers"]["paper/main.tex"]["thm:sum-odd"]["lean"] == ["Plain.oddSum_eq_sq"]

    # Unlinking a tagged link is recorded, and wins over the tag.
    save_link(plain, "paper/main.tex", "thm:odd-add", [])
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked", log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["number"] == "Theorem 1")
    assert c["links"] == [] and c["status"] != "linked: Lean proof checked"

    index = write_view_site(view, plain / ".machinechecked" / "site", None)
    assert index["mode"] == "simple" and len(index["claims"]) == 4
    assert (plain / ".machinechecked/site/data/lean-index.json").exists()


@needs_lean
@needs_tex
def test_rejected_suggestions_stay_rejected(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    save_link(plain, "paper/main.tex", "thm:square", None, rejected=["Plain.sq_odd"])
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked", log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["number"] == "Theorem 3")
    assert "Plain.sq_odd" not in [s["name"] for s in c["suggestions"]]


def test_links_file_name(plain):
    assert links_file(plain).name == "machinechecked.links.json"
    (plain / "prooflens.links.json").write_text('{"version": 1, "papers": {}}')
    assert links_file(plain).name == "prooflens.links.json"     # an existing older file is kept
    save_settings(plain, issues="someone/audits")
    assert json.loads((plain / "prooflens.links.json").read_text())["issues"] == "someone/audits"


@needs_lean
@needs_tex
def test_issue_settings_reach_the_reader(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    save_settings(plain, issues="someone/audits", site_url="https://example.org/audit/")
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                      log=lambda m: None)
    index = write_view_site(view, plain / ".machinechecked" / "site", None)
    assert index["issues"] == "someone/audits"
    assert index["site_url"] == "https://example.org/audit/"
    assert "commit" in index["project"] and "revision" in index["papers"][0]
