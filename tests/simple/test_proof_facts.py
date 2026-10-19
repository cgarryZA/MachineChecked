"""Typed facts inside a selected proof (#145), on the synthetic project
tests/fixtures/prooffacts.

`Facts.bound` exports `x ≤ C * (h + h)` for integers with `0 ≤ C`, `0 ≤ h` and `x + 1 ≤ C * h`;
its proof first establishes the sharper `x ≤ C * h` and weakens it with `Facts.weaken`, which
needs both sign conditions. `Facts.bound_unsigned` has no sign condition on `C`, so its proof
stops at the sharper bound. `Facts.bound_cases` establishes the doubled bound in the case
`0 ≤ h` only; `Facts.branches` and `Facts.witnesses` establish facts in two branches and for
two witnesses; `Facts.above` is a definition whose proof Lean moved to a lemma of its own.
"""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, edit, needs_lean, needs_tex
from prooflens import cli
from prooflens import proof_facts as pf
from prooflens import workspace as wsp
from prooflens.simple import run_simple_probe
from prooflens.targets import Snapshot

SRC = ROOT / "tests" / "fixtures" / "prooffacts"


def project(tmp_path, toolchain=None):
    root = tmp_path / "prooffacts"
    shutil.copytree(SRC, root, ignore=shutil.ignore_patterns(".lake", ".machinechecked"))
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return project(tmp_path_factory.mktemp("pf"))


def fact(doc, name=None, kind="have", head=None):
    found = [f for f in doc["facts"] if f["kind"] == kind
             and (name is None or f.get("name") == name) and (head is None or f.get("head") == head)]
    assert len(found) == 1, (name, kind, [(f["kind"], f.get("name")) for f in doc["facts"]])
    return found[0]


def hyps(f):
    return [(a["name"], a["type"]) for a in f["assumptions"] if a["role"] == "hypothesis"]


@needs_lean
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_a_proof_shows_its_sharper_bound_and_the_weakening(tmp_path, toolchain):
    root = project(tmp_path, toolchain)
    doc = pf.extract(root, "Facts.bound")
    assert doc["ok"] and doc["declaration"]["basis"] == "exported theorem"
    assert pf.extract(root, "Facts.bound")["cache"]["hit"]
    strong = fact(doc, "strong")
    assert strong["type"]["text"] == "x ≤ C * h" and strong["basis"] == pf.BASIS
    # The sharper bound needs only the hypothesis its proof uses.
    assert hyps(strong) == [("hx", "x + 1 ≤ C * h")]
    assert strong["standalone"]["text"] == "∀ (x C h : Int), x + 1 ≤ C * h → x ≤ C * h"
    # The weakening is an application of `Facts.weaken`, with each of its hypotheses at the
    # application and the local that supplies it: the two sign conditions and the sharper bound.
    w = fact(doc, kind="application", head="Facts.weaken")
    names = {l["id"]: l["name"] for l in doc["locals"]}
    assert [(p["name"], p["type"]["text"], names.get(p["supplied_by"])) for p in w["premises"]] \
        == [("hC", "0 ≤ C", "hC"), ("hh", "0 ≤ h", "hh"), ("hx", "x ≤ C * h", "strong")]
    assert w["type"]["text"] == "x ≤ C * (h + h)" and w["uses_facts"] == [strong["id"]]
    assert w["id"] in strong["used_by"]
    # Source lines: the `have` and the application by name, the `show` by its order.
    text = (root / "Facts/Main.lean").read_text().splitlines()
    assert "have strong" in text[strong["source"]["line"] - 1]
    assert "weaken" in text[w["source"]["line"] - 1]
    assert "show" in text[fact(doc, kind="show")["source"]["line"] - 1]
    assert doc["proof"]["complete"] and doc["proof"]["hash"]


@needs_lean
def test_without_the_sign_condition_no_weakening_is_claimed(built):
    doc = pf.extract(built, "Facts.bound_unsigned")
    strong = fact(doc, "strong")
    assert strong["type"]["text"] == "x ≤ C * h"
    assert not [f for f in doc["facts"] if f["kind"] == "application"]
    assert not [f for f in doc["facts"] if "h + h" in f["type"]["text"]]
    # A ranked search says what it found, never that one bound gives another.
    ranked = pf.rank(doc["facts"], "x ≤ C * (h + h)")
    assert ranked and all(set(r["match"]) == {"shared", "score"} for r in ranked)


@needs_lean
def test_a_fact_of_a_case_stays_with_the_case_hypothesis(built):
    doc = pf.extract(built, "Facts.bound_cases")
    d = fact(doc, "doubled")
    assert ("hh", "0 ≤ h") in hyps(d)
    assert d["cases"] == ["in the case hh : 0 ≤ h (argument 3 of dite)"]
    assert "0 ≤ h →" in d["standalone"]["text"]


@needs_lean
def test_branches_and_witnesses_are_kept_apart(built):
    doc = pf.extract(built, "Facts.branches")
    left, right = fact(doc, "left_bound"), fact(doc, "right_bound")
    assert hyps(left) == [("hp", "x ≤ h")] and hyps(right) == [("hn", "x ≤ -h")]
    assert left["scope"] != right["scope"] and left["cases"] != right["cases"]
    assert not set(left["needs"]) & {a["id"] for a in right["assumptions"]
                                     if a["role"] == "hypothesis"}
    doc = pf.extract(built, "Facts.witnesses")
    first, second = fact(doc, "first"), fact(doc, "second")
    n, = [a for a in first["assumptions"] if a["role"] == "variable" and a["name"] == "n"]
    m, = [a for a in second["assumptions"] if a["role"] == "variable" and a["name"] == "m"]
    assert n["id"] != m["id"] and m["id"] not in first["needs"] and n["id"] not in second["needs"]
    # A fact Lean names `this` is referenced by its position and proposition.
    both = fact(doc, "this")
    assert both["type"]["text"] == "P n ∧ P m"
    assert pf.find_fact(doc, both["ref"]) == both
    assert pf.find_fact(doc, {**both["ref"], "fact_hash": "0" * 16}) is None


@needs_lean
def test_a_proof_lean_does_not_keep_is_reported_from_the_source_only(built):
    doc = pf.extract(built, "Facts.above")
    assert doc["ok"] and doc["facts"] == []
    assert doc["proof"]["auxiliary"] == ["Facts.above._proof_1"]
    only, = doc["source_only"]
    assert only["text"].startswith("have step") and only["basis"] == pf.SOURCE_ONLY
    # The generated lemma holds the fact, and can be asked about by its own name.
    inner = pf.extract(built, "Facts.above._proof_1")
    assert fact(inner, "step")["type"]["text"] == "n ≤ n + 1"


@needs_lean
def test_a_walk_cut_short_says_so_and_a_failed_request_fails_alone(built):
    doc = pf.extract(built, "Facts.witnesses", limits={"nodes": 10})
    assert not doc["proof"]["complete"] and doc["proof"]["cut"] == \
        ["the walk reached its node limit"]
    doc = pf.extract(built, "Facts.witnesses", limits={"facts": 2})
    assert len(doc["facts"]) == 2 and doc["proof"]["cut"] == ["the walk reached its fact limit"]
    # A request that runs out of heartbeats emits an error record for itself; the session ends
    # with its other records.
    recs = run_simple_probe(built, ["Facts.Main"], ["Facts"],
                            [{"kind": "proof-facts", "name": "Facts.bound"},
                             {"kind": "proof-facts", "name": "Facts.branches"}],
                            extra={"max_heartbeats": 1})
    out = [r for r in recs if r.get("record") == "proof-facts"]
    assert [r["name"] for r in out] == ["Facts.bound", "Facts.branches"]
    assert all(r["errors"][0].startswith("probe-error") for r in out)
    bad = pf.extract(built, "Facts.bound", limits={"heartbeats": 1})
    assert bad["status"] == "probe error" and not bad["cache"]["hit"]


@needs_lean
def test_a_repeated_query_runs_no_lean(built, monkeypatch):
    pf.extract(built, "Facts.branches")
    monkeypatch.setattr(pf, "run_simple_probe", lambda *a, **k: pytest.fail("ran Lean"))
    assert pf.extract(built, "Facts.branches")["cache"]["hit"]


@needs_lean
@needs_tex
def test_compare_answers_proof_facts_and_a_citation_follows_the_proof(tmp_path, monkeypatch,
                                                                      capsys):
    root = project(tmp_path)
    monkeypatch.chdir(root)
    cli.main(["build"])
    capsys.readouterr()
    cli.main(["compare", "--query", "proof-facts", "Facts.bound", "--json"])
    q = json.loads(capsys.readouterr().out)
    assert q["available"] and q["subject"]["declaration"]["name"] == "Facts.bound"
    strong = next(f for f in q["results"] if f.get("name") == "strong")
    cli.main(["compare", "--query", "proof-facts", "Facts.bound", "--match", "C * h"])
    text = capsys.readouterr().out
    assert "strong : x ≤ C * h" in text and "assuming hx : x + 1 ≤ C * h" in text
    assert "established inside this proof" in text

    # A finding cites the fact: the citation keeps its basis, and it is not direct coverage.
    snap = Snapshot(root / ".machinechecked" / "site" / "data")
    work = root / ".machinechecked"
    p = wsp.open_for(work, {"id": "human:A", "kind": "human"}, "informed", sources=snap.sources())
    claim = "P:lem:sharp"
    wsp.update(p, [{"op": "put", "record": {"id": "e1", "kind": "evidence", "claim": claim,
                                            "role": "supports",
                                            "ref": {"fact": strong["ref"]}}}], snap, root)
    ev = wsp.read(p)["records"]["e1"]["ref"]["fact"]
    assert ev["basis"] == pf.BASIS and ev["type"] == "x ≤ C * h"
    assert ev["assumptions"] == ["hx : x + 1 ≤ C * h"]
    with pytest.raises(wsp.WorkspaceError, match="not direct coverage"):
        wsp.update(p, [{"op": "put", "record": {"kind": "finding", "claim": claim,
                                                "coverage": "full", "basis": "direct",
                                                "evidence": ["e1"]}}], snap, root)
    wsp.update(p, [{"op": "put", "record": {"id": "f1", "kind": "finding", "claim": claim,
                                            "coverage": "full", "basis": "reviewed_composition",
                                            "evidence": ["e1"]}}], snap, root)
    v = wsp.view(wsp.read(p), snap, root=root)
    assert v["claims"][claim]["evidence"][0]["currency"]["state"] == "current"

    # Changing the proof makes the citation stale (once the proof is read again), and so the
    # finding that cites it.
    edit(root / "Facts/Main.lean", "have strong : x ≤ C * h := by omega",
         "have strong : x ≤ C * h := by have _ := hx; omega")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    v = wsp.view(wsp.read(p), snap, root=root)
    assert v["claims"][claim]["evidence"][0]["currency"]["state"] == "unchecked"
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    e, = v["claims"][claim]["evidence"]
    f, = v["claims"][claim]["findings"]
    assert e["currency"]["state"] == "stale" and f["currency"]["state"] == "stale"
    assert "the proof changed" in e["currency"]["changes"][0]["reason"]
