"""How the main result uses a linked declaration (#112), on the synthetic project
tests/fixtures/uses, built in zero configuration.

The paper's theorem is linked to `Uses.main_bound`, whose proof applies the general lemma
`Uses.half_lt` (the paper's lemma) and the specialised helper `Uses.half_lt_four`, which applies
`Uses.good_double`. This copy of the paper also links a lemma to `Uses.caller_assumes`, which
applies `Uses.half_lt` and which the main theorem does not use. `Uses.Good` is in the statement
of `Uses.good_zero` and nowhere in its proof; `Uses.Other` imports `Uses.Main` and uses nothing
of it.
"""

import json
import re
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import cli
from prooflens import compare as cmp

SRC = ROOT / "tests" / "fixtures" / "uses"
LEMMA = r"""\begin{lemma}\label{lem:assumes}\lean{Uses.caller_assumes}
Every even positive $m$ satisfies $m/2 < m$.
\end{lemma}

"""


def _build(root):
    r = subprocess.run(["lake", "build"], cwd=root, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root =tmp_path_factory.mktemp("impact") / "uses"
    shutil.copytree(SRC, root)
    tex = root / "paper" / "main.tex"
    tex.write_text(tex.read_text().replace(r"\end{document}", LEMMA + r"\end{document}"))
    _build(root)
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(root)
        cli.main(["build"])
    return root


def site(project):
    return cmp.Site(project / ".machinechecked" / "site" / "data")


def impact(project, target, *main, root=None):
    q = cmp.query(site(project), "impact", target, root=root or project, main=list(main) or None)
    assert q["available"]
    (doc,) = q["results"]
    assert doc["ok"], doc
    return doc


def relations(doc):
    return {c["claim"]: c["relation"] for c in doc["claims"]}


@needs_lean
@needs_tex
def test_a_linked_lemma_used_by_the_main_theorem_shows_its_proof_path(project):
    data = project / ".machinechecked" / "site" / "data"
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    doc = impact(project, "Uses.half_lt")
    assert doc["selection"]["basis"] == "suggested" and doc["linked_to"] == ["P:lem:half"]
    (m,) = doc["main_results"]
    assert (m["name"], m["claims"], m["use"], m["direct"]) == (
        "Uses.main_bound", ["P:thm:main"], "proof", True)
    assert [(s["from"], s["to"]) for s in m["paths"]["proof"]["steps"]] == [
        ("Uses.main_bound", "Uses.half_lt")]
    # The hypothesis `Good n` of the main theorem's statement is not a use of the lemma.
    assert "statement" not in m["paths"]
    # The application of the lemma in the main proof: the premises it assumes and its result.
    (a,) = [x for x in doc["applications"] if x["id"] in m["applications"]]
    assert a["caller"] == "Uses.main_bound" and a["result"]["text"] == "n / 2 < n"
    assert {p["binder"]: p["discharge"] for p in a["premises"]} == {"h": "assumed",
                                                                     "hpos": "assumed"}
    assert relations(doc) == {"P:lem:half": "linked", "P:thm:main": "uses",
                              "P:lem:assumes": "uses"}
    assert doc["complete"] and doc["locations"]["Uses.main_bound"]["module"] == "Uses.Paper"
    # The query reads the build: it writes nothing there.
    assert before == {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}


@needs_lean
@needs_tex
def test_an_unused_linked_lemma_is_described_as_formalized_separately(project):
    doc = impact(project, "Uses.caller_assumes")
    (m,) = doc["main_results"]
    assert m["use"] == "none"
    assert m["answer"] == "formalized separately: not used by this main result"
    assert doc["linked_to"] == ["P:lem:assumes"] and doc["complete"]
    assert relations(doc) == {"P:lem:half": "none", "P:thm:main": "none",
                              "P:lem:assumes": "linked"}


@needs_lean
@needs_tex
def test_a_transitive_use_and_a_use_in_the_statement_only(project):
    doc = impact(project, "Uses.good_double")
    (m,) = doc["main_results"]
    assert m["use"] == "proof" and m["direct"] is False
    assert [(s["from"], s["to"]) for s in m["paths"]["proof"]["steps"]] == [
        ("Uses.main_bound", "Uses.half_lt_four"), ("Uses.half_lt_four", "Uses.good_double")]
    apps = [a for a in doc["applications"] if a["id"] in m["applications"]]
    assert apps and {a["caller"] for a in apps} == {"Uses.half_lt_four"}
    # `Good` is in `good_zero`'s statement only. The main theorem states it and its proof
    # reaches it through the statement of the lemma it applies: both paths are given.
    zero, main = impact(project, "Uses.Good", "Uses.good_zero", "thm:main")["main_results"]
    assert zero["name"] == "Uses.good_zero" and zero["use"] == "statement"
    assert zero["answer"] == "in its statement only, directly: not used by its proof"
    assert main["use"] == "proof" and main["paths"]["statement"]["length"] == 1
    assert [(s["from"], s["to"], s["refs"]) for s in main["paths"]["proof"]["steps"]] == [
        ("Uses.main_bound", "Uses.half_lt", ["proof"]),
        ("Uses.half_lt", "Uses.Good", ["statement"])]


@needs_lean
@needs_tex
def test_importing_a_module_is_not_a_use(project):
    doc = impact(project, "Uses.half_lt", "Uses.unrelated")
    (m,) = doc["main_results"]
    assert m["use"] == "none" and m["selected"] == ["named"]
    assert "Uses.Other" in doc["imports_without_use"]


@needs_lean
@needs_tex
def test_several_main_results_and_a_module_not_built_answer_per_root(project, tmp_path):
    root = tmp_path / "uses"
    shutil.copytree(SRC, root)
    _build(root)
    (root / "Uses" / "Later.lean").write_text(
        "import Uses.Main\n\ntheorem Uses.later : 4 / 2 < 4 := Uses.half_lt_four\n")
    doc = impact(project, "Uses.half_lt_four", "Uses.later", "thm:main", "Uses.caller_proves",
                 root=root)
    later, main, proves = doc["main_results"]
    assert later["use"] == "not traced"
    assert later["answer"] == "not traced: its module is not built (Uses.Later)"
    assert main["use"] == "proof" and main["direct"]
    # Its trace reaches only built modules: complete, whatever is not built elsewhere.
    assert proves["use"] == "none"
    assert doc["scope"]["unbuilt"] == ["Uses.Later"] and doc["complete"] is False


@needs_lean
@needs_tex
def test_the_command_prints_the_trace(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    cli.main(["compare", "--query", "impact", "Uses.half_lt", "--main", "thm:main"])
    out = capsys.readouterr().out
    assert "used by its proof, directly" in out
    assert "proof: Uses.main_bound -proof-> Uses.half_lt" in out
    assert "Lemma 1  [P:lem:half]  linked to it" in out
    cli.main(["compare", "--query", "impact", "Uses.caller_assumes", "--json"])
    q = json.loads(capsys.readouterr().out)
    assert q["schema"] == cmp.QUERY_SCHEMA and q["op"] == "impact"
    assert q["results"][0]["main_results"][0]["use"] == "none"


def _cited(out: str) -> dict:
    """The reference the terminal text offers to cite."""
    (line,) = re.findall(r"^  cite as evidence: (\{.*\})(?: \(or another .*\))?$", out, re.M)
    return json.loads(line)


@needs_lean
@needs_tex
def test_the_printed_ids_and_positions_are_what_workspace_evidence_cites(project, monkeypatch,
                                                                        capsys):
    """#401: the terminal text of `uses` names each application by its id and that of
    `proof-facts` gives each fact's position; a workspace takes both as evidence. #402: in
    `impact`, the two applications of `good_double` in `twice` (the same result, each argument
    printed `x`) are one entry with both ids."""
    monkeypatch.chdir(project)
    who = ["--as", "llm:test"]
    try:
        cli.main(["compare", "--query", "uses", "Uses.half_lt"])
        out = capsys.readouterr().out
        printed = re.findall(r"^  application (app:\S+) in ([^\s,]+)", out, re.M)
        cli.main(["compare", "--query", "uses", "Uses.half_lt", "--json"])
        apps = json.loads(capsys.readouterr().out)["results"][0]["applications"]
        assert printed == [(a["id"], a["caller"]) for a in apps] and len(printed) > 1
        app = _cited(out)["app"]
        assert app == {"callee": "Uses.half_lt", "id": printed[0][0]}
        (app["id"],) = [i for i, caller in printed if caller == "Uses.main_bound"]

        cli.main(["compare", "--query", "proof-facts", "Uses.main_bound"])
        out = capsys.readouterr().out
        positions = re.findall(r"^  (f\d+) .*\[.*at (/[\d/]*)\]$", out, re.M)
        cli.main(["compare", "--query", "proof-facts", "Uses.main_bound", "--json"])
        facts = json.loads(capsys.readouterr().out)["results"]
        assert positions == [(f["id"], f["ref"]["at"]) for f in facts] and positions
        fact = _cited(out)["fact"]
        assert fact == {"decl": "Uses.main_bound", "at": positions[0][1]}

        cli.main(["workspace", "open", "--mode", "informed", *who])
        ops = project / "ops.json"
        ops.write_text(json.dumps({"ops": [
            {"op": "put", "record": {"id": "e-app", "kind": "evidence", "claim": "thm:main",
                                     "role": "supports", "ref": {"app": app}}},
            {"op": "put", "record": {"id": "e-fact", "kind": "evidence", "claim": "thm:main",
                                     "role": "supports", "ref": {"fact": fact}}}]}))
        capsys.readouterr()
        cli.main(["workspace", "update", str(ops), *who])
        assert json.loads(capsys.readouterr().out)["ok"]
        cli.main(["workspace", "show", "--json", *who])
        ev = {e["id"]: e for e in json.loads(capsys.readouterr().out)["claims"]["P:thm:main"]
              ["evidence"]}
        assert ev["e-app"]["ref"]["app"]["caller"] == "Uses.main_bound"
        assert {e["currency"]["state"] for e in ev.values()} == {"current"}

        cli.main(["compare", "--query", "impact", "Uses.good_double", "--main", "Uses.twice"])
        out = capsys.readouterr().out
        ids = [a["id"] for a in impact(project, "Uses.good_double", "Uses.twice")["applications"]
               if a["caller"] == "Uses.twice"]
        assert len(ids) == 2
        assert (f"      2 applications in Uses.twice, with the same result: {', '.join(ids)}\n"
                "        gives Uses.Good (2 * x)\n") in out
    finally:
        shutil.rmtree(project / ".machinechecked" / "review-work", ignore_errors=True)
        (project / "ops.json").unlink(missing_ok=True)
