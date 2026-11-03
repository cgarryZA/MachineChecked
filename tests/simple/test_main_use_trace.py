"""How the main results use each link (#551), on the synthetic project tests/fixtures/mainuse,
built in zero configuration.

The paper's Lemma 2 is linked to `MainUse.bound_faithful`, which states it as printed, and to
`MainUse.bound_variant`, the variant the main theorem's proof applies; the faithful statement is
proved from the variant, and the main result does not use it. Lemma 1 is linked to
`MainUse.le_ten`, which the variant's proof applies. `check --json` says, for each link, how the
suggested main result uses it, from the references the build stored: a repeated check starts no
Lean session. The reader's site data carries the same answers.
"""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import cli, simple
from prooflens import uses as us

SRC = ROOT / "tests" / "fixtures" / "mainuse"
MAIN = "MainUse.main_result"


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("mainuse") / "mainuse"
    shutil.copytree(SRC, root)
    r = subprocess.run(["lake", "build"], cwd=root, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


def check(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    cli.main(["check", "--json"])
    return json.loads(capsys.readouterr().out)


def links(doc):
    return {l["name"]: l for c in doc["claims"] for l in c["links"]}


@needs_lean
@needs_tex
def test_check_says_how_the_main_result_uses_each_link(project, monkeypatch, capsys):
    doc = check(project, monkeypatch, capsys)
    mu = doc["main_use"]
    assert mu["available"] and mu["complete"] and "claims" not in mu
    sel = mu["selection"]
    assert sel["basis"] == "suggested"
    assert sel["main_results"] == [{"name": MAIN, "claims": ["P:thm:main"],
                                    "selected": ["P:thm:main"]}]
    ls = links(doc)
    # The variant the main proof applies, beside the paper-faithful statement it does not use.
    assert ls["MainUse.bound_variant"]["main_use"] == [
        {"main": MAIN, "use": "proof", "answer": "used by its proof, directly", "through": 0,
         "path": [MAIN, "MainUse.bound_variant"]}]
    assert ls["MainUse.bound_faithful"]["main_use"] == [
        {"main": MAIN, "use": "none",
         "answer": "formalized separately: not used by this main result"}]
    assert ls["MainUse.le_ten"]["main_use"] == [
        {"main": MAIN, "use": "proof", "answer": "used by its proof, through 1 other declaration",
         "through": 1, "path": [MAIN, "MainUse.bound_variant", "MainUse.le_ten"]}]
    assert ls[MAIN]["main_use"][0]["answer"] == "this is the main result itself"
    # The statuses are the engine's, as before: a use changes none.
    assert {l["name"]: l["status"] for l in ls.values()} == {
        n: "linked: Lean proof checked" for n in ls}

    # A repeated check starts no Lean session and gives the same answers.
    sessions = []
    real = simple.run_simple_probe

    def spy(*a, **k):
        sessions.append(a[1])
        return real(*a, **k)

    def no_lean(*a, **k):
        raise AssertionError("Lean was asked where a declaration is used")
    monkeypatch.setattr(simple, "run_simple_probe", spy)
    monkeypatch.setattr(us, "uses", no_lean)
    again = check(project, monkeypatch, capsys)
    assert sessions == []
    assert again["main_use"] == mu
    assert {n: l["main_use"] for n, l in links(again).items()} == \
        {n: l["main_use"] for n, l in ls.items()}


@needs_lean
@needs_tex
def test_the_site_data_carries_the_same_answers(project, monkeypatch, capsys):
    want = links(check(project, monkeypatch, capsys))
    cli.main(["build"])
    capsys.readouterr()
    data = project / ".machinechecked" / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    assert index["main_use"] == "data/main-use.json"
    doc = json.loads((data / "main-use.json").read_text())
    assert doc["available"] and doc["selection"]["basis"] == "suggested"
    got = {n: m for per in doc["claims"].values() for n, m in per.items()}
    assert got == {n: l["main_use"] for n, l in want.items()}
