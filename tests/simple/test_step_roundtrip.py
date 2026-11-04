"""A finding, a counterexample and a review draft on a proof step, through a workspace file, an
import into another working directory and a published audit (#545): each keeps the step's kind,
parent and scope (`pins.target`, a draft's `target`), its evidence and its review state."""

import json
import shutil

import pytest

from conftest import needs_lean, needs_tex
from prooflens import cli
from prooflens.manifest import claim_file
from prooflens.simple import built_modules
from prooflens.steps import target_of

PAPER = "paper/toy.tex"
STEP, UNIT = "P:eq:bound-range", "step:P:eq:bound-range"
WHO = ["--as", "llm:Round-Trip"]
OPS = {"op_id": "eq3", "ops": [
    {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "n.k",
                             "form": "for every", "binds": ["k"], "domain": "k ≥ 0",
                             "text": "for every natural number k ≥ 0"}},
    {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "n.k.1",
                             "parent": "n.k", "form": "conclusion", "text": "n ≤ k n²"}},
    {"op": "put", "record": {"id": "e-refutes", "kind": "evidence", "claim": "Equation (3)",
                             "role": "supports", "ref": {"certificate": {
                                 "theorem": "ToyAudit.bound_range_at_one_false",
                                 "target": "ToyAudit.bound_range_at_one",
                                 "certifies": "refutes"}}}},
    {"op": "put", "record": {"id": "x-zero", "kind": "counterexample", "claim": "Equation (3)",
                             "requirement": "n.k.1", "specialisation": {"assign": {"n": 1, "k": 0}},
                             "reduced": "1 ≤ k · 1²", "violation": "at k = 0 it reads 1 ≤ 0",
                             "evidence": ["e-refutes"],
                             "admissibility": [{"obligation": "k = 0 satisfies k ≥ 0",
                                                "state": "verified", "method": "arithmetic"}]}},
    {"op": "put", "record": {"id": "f-step", "kind": "finding", "claim": "Equation (3)",
                             "requirement": "n.k.1", "verdict": "false as printed",
                             "counterexamples": ["x-zero"], "note": "It fails at k = 0, n = 1."}},
    {"op": "submit", "id": "f-step", "base_rev": 1}]}
RECORDS = ("e-refutes", "x-zero", "f-step")


def project(toy, where):
    """The toy paper inside its Lean project, as zero configuration finds it."""
    root = toy.parent / where
    shutil.copytree(toy / "lean", root, symlinks=True)
    (root / "paper").mkdir()
    shutil.copy(toy / "paper/toy.tex", root / PAPER)
    if not built_modules(root, ["Toy"])[0]:
        pytest.skip("the toy example is not built")
    return root


def run(capsys, *args):
    capsys.readouterr()
    cli.main(list(args))
    return capsys.readouterr().out


def chunk(root, cid):
    return json.loads((root / ".machinechecked/site/data/claims" / claim_file(cid)).read_text())


def workspace(root):
    return json.loads(next((root / ".machinechecked/review-work").glob("*.json")).read_text())


@needs_lean
@needs_tex
def test_a_proof_step_s_records_and_draft_keep_their_target(toy, tmp_path, monkeypatch,
                                                            capsys):
    here = project(toy, "here")
    monkeypatch.chdir(here)
    monkeypatch.setenv("MACHINECHECKED_REVIEWER", "llm:Round-Trip")
    run(capsys, "build")
    run(capsys, "link", "Equation (3)", "Toy.Acceptance.thm_bound", "--route", *WHO)
    run(capsys, "build")
    run(capsys, "workspace", "open", "--mode", "informed", *WHO)
    (tmp_path / "ops.json").write_text(json.dumps(OPS))
    run(capsys, "workspace", "update", str(tmp_path / "ops.json"), *WHO)
    (tmp_path / "reading.md").write_text("For every k at least zero, n is at most k n squared.")
    run(capsys, "review", "read", UNIT, *WHO)
    run(capsys, "review", "lock", UNIT, str(tmp_path / "reading.md"), *WHO)
    step = target_of(chunk(here, STEP))
    assert step["unit"] == "proof-equation" and step["parent"]["id"] == "P:thm:bound"
    assert step["scope"] == "proof-step" and step["source"]["sha256"]
    ws = workspace(here)
    for rid in RECORDS:
        assert ws["records"][rid]["pins"]["target"] == step, rid
    draft = ws["review"]["drafts"][UNIT]
    assert draft["target"] == {"unit": "proof-equation", "claim": STEP,
                               "parent": {"id": "P:thm:bound", "number": "Theorem 2.5"}}
    assert draft["stage"] == "compare"

    # A workspace file holds them exactly.
    exported = tmp_path / "work.json"
    run(capsys, "workspace", "export", "--out", str(exported), *WHO)
    data = json.loads(exported.read_text())
    assert {r: data["records"][r] for r in RECORDS} == {r: ws["records"][r] for r in RECORDS}
    assert data["review"]["drafts"] == ws["review"]["drafts"]

    # Imported into another working directory with the same paper and Lean: the same records
    # and draft, nothing to report, and the same reading of the step.
    there = project(toy, "there")
    shutil.copy(here / "machinechecked.links.json", there / "machinechecked.links.json")
    monkeypatch.chdir(there)
    run(capsys, "build")
    try:
        cli.main(["workspace", "import", str(exported), *WHO])
    finally:
        out = json.loads(capsys.readouterr().out)
    assert out["problems"] == [] and out["conflicts"] == []
    assert out["drafts"]["applied"] == [{"unit": UNIT, "how": "added"}]
    theirs = workspace(there)
    assert {r: theirs["records"][r] for r in RECORDS} == {r: ws["records"][r] for r in RECORDS}
    assert theirs["review"]["drafts"] == ws["review"]["drafts"]
    assert target_of(chunk(there, STEP)) == step
    shown = json.loads(run(capsys, "workspace", "show", "--id", ws["id"], "--json", *WHO))
    found = shown["claims"][STEP]
    assert [(f["id"], f["state"], f["in_force"], f["currency"]["state"])
            for f in found["findings"]] == [("f-step", "submitted", True, "current")]
    assert [(x["id"], x["evidence"]) for x in found["counterexamples"]] == \
        [("x-zero", ["e-refutes"])]
    # The review goes on from the imported draft, at its step; the report names the step.
    (tmp_path / "cmp.md").write_text("At k = 0 and n = 1 the step reads 1 <= 0.")
    (tmp_path / "none.md").write_text("none")
    (tmp_path / "detail.md").write_text("It fails at k = 0.")
    mine = ["--workspace", ws["id"], *WHO]
    run(capsys, "review", "show", UNIT, *mine)
    run(capsys, "review", "decide", UNIT, "false as printed", str(tmp_path / "cmp.md"),
        "--detail", str(tmp_path / "detail.md"), *mine)
    run(capsys, "review", "author", UNIT, *mine)
    run(capsys, "review", "submit", UNIT, str(tmp_path / "none.md"), *mine)
    (there / "machinechecked-reviews").mkdir()
    run(capsys, "review", "export", "--out", "machinechecked-reviews/r.json", *mine)
    (report,) = json.loads((there / "machinechecked-reviews/r.json").read_text())["reports"]
    assert (report["unit"]["target"], report["unit"]["parent"]["id"]) == \
        ("proof-equation", "P:thm:bound")
    assert report["pins"]["source_sha256"] == {STEP: step["source"]["sha256"]}

    # Published: the step keeps its kind, parent, scope and review, and the records theirs.
    site = tmp_path / "site"
    run(capsys, "build", "--site", str(site))
    pub = json.loads((site / "data/claims" / claim_file(STEP)).read_text())
    assert (pub["unit"], pub["parent"], pub["scope"]) == ("proof-equation", "P:thm:bound",
                                                          "proof-step")
    assert pub["step"]["review"]["state"] == "false"
    work = json.loads((site / "data" / pub["work"]).read_text())
    (reading,) = work["readings"]
    published = {r["id"]: r for k in ("findings", "counterexamples", "evidence")
                 for r in reading[k]}
    for rid in RECORDS:
        mine = ws["records"][rid]
        assert published[rid]["pins"] == mine["pins"], rid
        assert {k: published[rid][k] for k in ("kind", "claim", "created_by", "rev")} == \
            {k: mine[k] for k in ("kind", "claim", "created_by", "rev")}
    assert published["f-step"]["state"] == "submitted" and published["f-step"]["in_force"]
    assert published["x-zero"]["evidence"] == ["e-refutes"]
    assert published["e-refutes"]["ref"]["certificate"] == ws["records"]["e-refutes"]["ref"][
        "certificate"]
