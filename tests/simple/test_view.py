"""Zero-configuration mode on an ordinary Lean project with a paper."""

import json
import shutil

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import (build_view, built_modules, find_lake_root, find_papers, lib_names,
                              save_link, write_view_site)

PLAIN = ROOT / "examples" / "plain-paper"


@pytest.fixture
def plain(tmp_path):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(".prooflens", "prooflens.links.json"),
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
    view = build_view(plain, plain / "paper/main.tex", plain / ".prooflens", log=lambda m: None)
    claims = {c["number"]: c for c in view["body"]["claims"]}
    assert set(claims) == {"Theorem 1", "Theorem 2", "Theorem 3", "Lemma 4"}
    why = {n: [(s["name"], s["why"]) for s in c["suggestions"]] for n, c in claims.items()}
    assert why["Theorem 1"][0] == ("Plain.odd_add_odd", "tagged \\lean{…} in the paper")
    assert why["Theorem 3"][0] == ("Plain.sq_odd", "its docstring cites Theorem 3")
    assert why["Theorem 2"][0][0] == "Plain.oddSum_eq_sq"
    assert why["Lemma 4"] == []
    # Only suggestions until someone links: nothing claims more.
    assert {c["status"] for c in claims.values()} == {"suggested link, not confirmed",
                                                      "not linked"}

    save_link(plain, "paper/main.tex", "thm:odd-add", ["Plain.odd_add_odd"])
    save_link(plain, "paper/main.tex", "thm:sum-odd", ["Plain.oddSum_eq_sq"])
    save_link(plain, "paper/main.tex", "lem:open", ["Plain.no_such_theorem"])
    view = build_view(plain, plain / "paper/main.tex", plain / ".prooflens", log=lambda m: None)
    st = {c["number"]: c["status"] for c in view["body"]["claims"]}
    assert st["Theorem 1"] == "linked: Lean proof checked"
    assert st["Theorem 2"] == "linked: Lean proof incomplete (sorry)"
    assert st["Lemma 4"] == "linked: Lean declaration not found"
    links = json.loads((plain / "prooflens.links.json").read_text())
    assert links["papers"]["paper/main.tex"]["thm:odd-add"]["lean"] == ["Plain.odd_add_odd"]

    index = write_view_site(view, plain / ".prooflens" / "site", None)
    assert index["mode"] == "simple" and len(index["claims"]) == 4
    assert (plain / ".prooflens/site/data/lean-index.json").exists()


@needs_lean
@needs_tex
def test_rejected_suggestions_stay_rejected(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    save_link(plain, "paper/main.tex", "thm:square", None, rejected=["Plain.sq_odd"])
    view = build_view(plain, plain / "paper/main.tex", plain / ".prooflens", log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["number"] == "Theorem 3")
    assert "Plain.sq_odd" not in [s["name"] for s in c["suggestions"]]
