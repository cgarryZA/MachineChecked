"""Changing a claim's source-region bounds at its pinned revision (#184), on a synthetic
manuscript."""

import json
import subprocess

import pytest

from prooflens.rebound import main, parse_lines, rebound_plan
from prooflens.review_sources import marker_state
from prooflens.source_regions import SCHEME, RegionError, collect, extract, matches

REV = "a" * 40
TEXT = ("\\documentclass{article}\n\\begin{document}\n"            # 1-2
        "\\section{Rates}\n"                                       # 3
        "On the test problem the estimator is consistent and converges at\n"   # 4
        "rate $n^{-1/2}$, uniformly over the compact parameter set\n"         # 5
        "(Theorem~\\ref{X:thm:rate}).\n"                           # 6
        "\n"                                                       # 7
        "% a comment line\n"                                       # 8
        "\\section{Discussion}\n"                                  # 9
        "The rate is optimal.\n"                                   # 10
        "\\end{document}\n")


def pinned(root, cid, line, **extra):
    c = {"id": cid, "paper": "X", "location": f"paper.tex:{line}", "scope": "expository",
         "scope_reviewed": True, "clauses": [], **extra}
    region = extract(root, c)
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": region.sha256,
            "source_line_sha256": region.line_sha256}


@pytest.fixture
def paper(tmp_path):
    (tmp_path / "paper.tex").write_text(TEXT, encoding="utf-8")
    return tmp_path


def inventory(root):
    return {"papers": {"X": {"commit": REV[:7]}},
            "claims": [pinned(root, "X:intro:rate", 5), pinned(root, "X:disc", 10)]}


def req(cid, spec, **kw):
    start, end = parse_lines(spec)
    return {"claim": cid, "start": start, "end": end, **kw}


def test_widening_recomputes_the_digests_and_reopens_the_scope(paper):
    inv = inventory(paper)
    old = inv["claims"][0]["source_sha256"]
    result, changes = rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "4-6")])
    c = result["claims"][0]
    assert c["location"] == "paper.tex:4" and c["source_region"] == {"end_line": 6}
    region = extract(paper, c)
    assert c["source_sha256"] == region.sha256 != old
    assert c["source_line_sha256"] == region.line_sha256 and len(region.line_sha256) == 3
    assert c["scope_reviewed"] is False
    assert matches(c, {"regions": collect({"claims": [c]}, "X", paper)})
    # The plan shows both passages by their first and last lines.
    ch = changes[0]
    assert ch["old"]["first"].startswith("rate $n^{-1/2}$")
    assert ch["new"]["first"].startswith("On the test problem")
    assert ch["new"]["last"] == "(Theorem~\\ref{X:thm:rate})."
    # The other claim and the input are untouched.
    assert result["claims"][1] == inv["claims"][1] and inv["claims"][0]["source_sha256"] == old


def test_a_review_that_read_the_old_passage_reads_it_as_changed(paper):
    from types import SimpleNamespace
    inv = inventory(paper)
    c = inv["claims"][0]
    marker = SimpleNamespace(source={c["id"]: c["source_sha256"]})
    result, _ = rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "4-6")])
    assert marker_state(marker, c["id"], c["source_sha256"]) == "current"
    assert marker_state(marker, c["id"], result["claims"][0]["source_sha256"]) == "changed"
    # The other claim's reading stands.
    d = inv["claims"][1]
    assert marker_state(SimpleNamespace(source={d["id"]: d["source_sha256"]}), d["id"],
                        result["claims"][1]["source_sha256"]) == "current"


def test_narrowing_and_moving_are_bounds_like_any_other(paper):
    inv = inventory(paper)
    inv["claims"][0] = pinned(paper, "X:intro:rate", 4, source_region={"end_line": 6})
    result, _ = rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "5"),
                                                    req("X:disc", "10")])
    assert result["claims"][0]["location"] == "paper.tex:5"
    assert "source_region" not in result["claims"][0]
    # Bounds that select the same passage change nothing.
    assert result["claims"][1] == inv["claims"][1]


@pytest.mark.parametrize("spec, why", [("7-10", "blank"), ("4-8", "comment-only"),
                                       ("4-10", "sectioning"), ("6-4", "reversed"),
                                       ("40", "outside the file"), ("4 to 6", "A-B")])
def test_bad_bounds_are_refused(paper, spec, why):
    with pytest.raises(RegionError, match=why):
        rebound_plan(inventory(paper), "X", paper, REV, [req("X:intro:rate", spec)])


def test_a_section_may_be_crossed_on_request(paper):
    result, _ = rebound_plan(inventory(paper), "X", paper, REV,
                             [req("X:intro:rate", "4-10")], across_sections=True)
    assert result["claims"][0]["source_region"] == {"end_line": 10}
    # A sectioning command on the first line is the passage's own heading.
    rebound_plan(inventory(paper), "X", paper, REV, [req("X:intro:rate", "3-6")])


def test_another_revision_or_a_changed_snapshot_is_refused(paper):
    with pytest.raises(RegionError, match="pinned at revision"):
        rebound_plan(inventory(paper), "X", paper, "b" * 40, [req("X:intro:rate", "4-6")])
    inv = inventory(paper)
    (paper / "paper.tex").write_text(TEXT.replace("compact", "closed"), encoding="utf-8")
    with pytest.raises(RegionError, match="differs from its pin"):
        rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "4-6")])
    with pytest.raises(RegionError, match="no claim"):
        rebound_plan(inv, "X", paper, REV, [req("X:nothing", "4-6")])


def test_a_legacy_line_hash_is_verified_then_replaced(paper):
    import hashlib
    inv = inventory(paper)
    c = inv["claims"][0]
    line = TEXT.split("\n")[4]
    for k in ("source_hash_scheme", "source_line_sha256"):
        del c[k]
    c["source_sha256"] = hashlib.sha256(" ".join(line.split()).encode()).hexdigest()
    result, changes = rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "4-6")])
    assert result["claims"][0]["source_hash_scheme"] == SCHEME
    assert changes[0]["old"]["kind"] == "legacy line hash"
    assert result["claims"][0]["scope_reviewed"] is False
    c["source_sha256"] = "f" * 64
    with pytest.raises(RegionError, match="legacy"):
        rebound_plan(inv, "X", paper, REV, [req("X:intro:rate", "4-6")])


def test_command_plans_then_writes_atomically(tmp_path, capsys):
    proj = tmp_path / "project"
    (proj / "manuscript").mkdir(parents=True)
    (proj / "manuscript" / "paper.tex").write_text(TEXT, encoding="utf-8")
    (proj / "claims.json").write_text(
        json.dumps(inventory(proj / "manuscript"), indent=2) + "\n", encoding="utf-8")
    (proj / "machinechecked.toml").write_text(
        '[project]\nname = "synthetic"\nmodules = ["S"]\nscope_roots = ["S"]\n'
        'spec_prefix = "S.Spec"\naccept_prefix = "S.Accept"\ninventory = "claims.json"\n\n'
        '[[paper]]\nid = "X"\nroot = "paper.tex"\nsource = { path = "manuscript" }\n',
        encoding="utf-8")
    args = ["--config", str(proj / "machinechecked.toml"), "--paper", "X",
            "--claim", "X:intro:rate", "--lines", "4-6"]
    before = (proj / "claims.json").read_bytes()
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["written"] is False and (proj / "claims.json").read_bytes() == before
    assert plan["changes"][0]["new"]["end_line"] == 6
    assert main(args + ["--write"]) == 0
    capsys.readouterr()
    after = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    assert after["claims"][0]["source_region"] == {"end_line": 6}
    assert (proj / "claims.json").read_text(encoding="utf-8").startswith('{\n  "papers"')
    # Again: the bounds are already those; nothing is written.
    assert main(args + ["--write"]) == 0
    assert json.loads(capsys.readouterr().out)["written"] is False
    with pytest.raises(SystemExit):
        main(args[:-2] + ["--lines", "7-10"])
    assert "blank" in capsys.readouterr().err
