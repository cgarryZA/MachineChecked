"""Proof steps (#125): an equation inside a printed proof is a target of its own, with its own
Lean links, its own formal route and its own review, apart from its enclosing result."""

import json

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr
from prooflens.export import export
from prooflens.manifest import claim_file
from test_toy import EXPECTED, STEPS

REPORTS = "machinechecked-reviews/proof-steps.json"


def chunk(cfg, cid, site="site"):
    return json.loads((cfg.out_dir / site / "data" / "claims" / claim_file(cid)).read_text())


@needs_lean
@needs_tex
def test_a_proof_step_has_its_own_links_route_and_review(toy, tmp_path):
    index, body, cfg = build(toy)
    # The statements keep exactly their statuses; the steps keep their scope decision.
    assert {c["id"]: c["status"] for c in index["claims"]} == {**EXPECTED, **STEPS}
    assert [f for f in body["assessment"]["findings"] if f["tier"] == "violation"] == []
    rows = {c["id"]: c for c in index["claims"]}
    assert rows["T:thm:bound"]["unit"] == "statement" and rows["T:thm:bound"]["parent"] is None
    assert rows["T:eq:bound-range"]["unit"] == "proof-equation"
    assert rows["T:eq:bound-range"]["parent"] == "T:thm:bound"
    assert rows["T:eq:bound-range"]["anchor"]["kind"] == "approximate"
    # Statements and proof steps are counted apart.
    assert sum(index["units"]["T"]["statement"].values()) == len(EXPECTED)
    assert index["units"]["T"]["proof-equation"] == {"out of scope: proof-step": 2}

    # A step linked to the Lean that establishes it: checked by Lean, and not reviewed.
    s = chunk(cfg, "T:eq:bound-sum")["step"]
    assert s["parent"]["id"] == "T:thm:bound" and s["parent"]["number"] == "Theorem 2.5"
    assert [(l["name"], l["status_code"]) for l in s["links"]] == [
        ("Toy.Acceptance.thm_triangle", "link.checked")]
    assert s["links"][0]["statement"]["conclusion"]["text"]
    assert (s["correspondence"]["coverage"], s["correspondence"]["basis"]) == ("full", "direct")
    assert s["route"] is None
    assert s["review"] == {"state": "unreviewed", "finding": None, "reports": []}
    assert s["source"]["sha256"] == body["inventory"]["claims"][
        [c["id"] for c in body["inventory"]["claims"]].index("T:eq:bound-sum")]["source_sha256"]

    # A step false as printed, whose formal route differs: nothing establishes it, the Lean of
    # the enclosing result is recorded as the route used instead, and its finding is its own.
    r = chunk(cfg, "T:eq:bound-range")
    s = r["step"]
    assert s["links"] == [] and s["correspondence"] is None
    assert [(l["name"], l["status_code"]) for l in s["route"]["links"]] == [
        ("Toy.Acceptance.thm_bound", "link.checked")]
    assert "Nat.le_mul_self" in s["route"]["note"]
    assert s["review"]["state"] == "false" and s["review"]["finding"]["current"]
    assert "k = 0" in s["review"]["finding"]["verdict"]["detail"]
    assert "Toy.Acceptance.thm_bound" in r["decls"]

    # The parent lists its steps, keeps its own status and has no step record.
    p = chunk(cfg, "T:thm:bound")
    assert "step" not in p and p["status"] == EXPECTED["T:thm:bound"]
    assert [(x["id"], x["review"], x["linked"], x["route"]) for x in p["steps"]] == [
        ("T:eq:bound-sum", "unreviewed", ["Toy.Acceptance.thm_triangle"], []),
        ("T:eq:bound-range", "false", [], ["Toy.Acceptance.thm_bound"])]

    # Both steps are in the review queue, the one with no Lean link included.
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    units = {u["id"]: u for u in q["units"] if u["kind"] == "step"}
    assert set(units) == {"step:T:eq:bound-sum", "step:T:eq:bound-range"}
    u = units["step:T:eq:bound-range"]
    assert u["lean"] == [] and u["route"] == ["Toy.Acceptance.thm_bound"]
    assert u["fingerprints"]["source"] == r["source_sha256"] and u["state"] == "reviewed"
    assert units["step:T:eq:bound-sum"]["state"] == "pending"
    assert u["parent"] == {"id": "T:thm:bound", "number": "Theorem 2.5"}
    # Open steps follow the other open units; reviewed units come last.
    order = [(u["state"] == "reviewed", u["kind"] == "step") for u in q["units"]]
    assert order == sorted(order)

    # The export keeps the unit kind, the parent, the evidence identity and the review.
    out = export(cfg, tmp_path / "pub")["out"]
    pidx = json.loads((out / "data/index.json").read_text())
    prow = {c["id"]: c for c in pidx["claims"]}
    assert prow["T:eq:bound-range"]["unit"] == "proof-equation"
    assert prow["T:eq:bound-range"]["parent"] == "T:thm:bound"
    assert prow["T:eq:bound-range"]["step_review"] == "false"
    assert prow["T:thm:bound"]["unit"] == "statement"
    assert pidx["units"] == index["units"]
    pub = json.loads((out / "data/claims" / claim_file("T:eq:bound-range")).read_text())
    assert pub["step"]["review"]["state"] == "false"
    assert pub["step"]["review"]["finding"]["verdict"]["value"] == "false as printed"
    assert pub["step"]["route"]["links"][0]["name"] == "Toy.Acceptance.thm_bound"
    assert pub["step"]["source"]["sha256"] == r["source_sha256"]
    assert [x["id"] for x in json.loads((out / "data/claims" / claim_file("T:thm:bound"))
                                        .read_text())["steps"]] == ["T:eq:bound-sum",
                                                                    "T:eq:bound-range"]


@needs_lean
@needs_tex
def test_a_step_finding_belongs_to_its_source_text_and_never_to_its_parent(toy):
    build(toy)
    # A report made on other source text is kept and shown, and no longer is the finding.
    rep = json.loads((toy / REPORTS).read_text())
    rep["reports"][0]["pins"]["fingerprints"]["source"] = "0" * 64
    (toy / REPORTS).write_text(json.dumps(rep))
    index, _, cfg = build(toy, reuse_lean=True)
    s = chunk(cfg, "T:eq:bound-range")["step"]
    assert s["review"]["state"] == "stale" and s["review"]["finding"] is None
    assert s["review"]["reports"][0]["current"] is False
    # A report whose verdict is not a step verdict is not a finding.
    rep["reports"][0]["pins"]["fingerprints"]["source"] = chunk(cfg, "T:eq:bound-range")[
        "source_sha256"]
    rep["reports"][0]["verdict"]["value"] = "faithful"
    (toy / REPORTS).write_text(json.dumps(rep))
    _, _, cfg = build(toy, reuse_lean=True)
    assert chunk(cfg, "T:eq:bound-range")["step"]["review"]["state"] == "unreviewed"
    # A stored `composed` coverage reads as full by the auditor's composition.
    inv = json.loads((toy / "claims.json").read_text())
    step = next(c for c in inv["claims"] if c["id"] == "T:eq:bound-sum")
    step["coverage"] = "composed"
    step.pop("basis")
    (toy / "claims.json").write_text(json.dumps(inv))
    index, _, cfg = build(toy, reuse_lean=True)
    cor = chunk(cfg, "T:eq:bound-sum")["step"]["correspondence"]
    assert (cor["coverage"], cor["basis"]) == ("full", "reviewed_composition")
    # Whatever is recorded on a step, no assessed status moves.
    assert {c["id"]: c["status"] for c in index["claims"]} == {**EXPECTED, **STEPS}
    # An inventory written before unit kinds: a claim recorded by line whose scope is
    # `proof-step` is a proof step (an equation when its pinned region is a display), and
    # unreviewed until a report covers it; its scope decision is not a reading of it.
    for c in inv["claims"]:
        if c["id"] == "T:eq:bound-sum":
            c.pop("unit")
    (toy / "claims.json").write_text(json.dumps(inv))
    index, _, cfg = build(toy, reuse_lean=True)
    row = next(c for c in index["claims"] if c["id"] == "T:eq:bound-sum")
    assert (row["unit"], row["step_review"]) == ("proof-equation", "unreviewed")
    assert row["status"] == STEPS["T:eq:bound-sum"]
    assert "step:T:eq:bound-sum" in {u["id"] for u in json.loads(
        (cfg.out_dir / "site/data/review-queue.json").read_text())["units"]}


def test_unit_kinds():
    from prooflens.steps import unit_of
    assert unit_of({"scope": "formal", "location": "a.tex"}) == "statement"
    assert unit_of({"scope": "proof-step", "location": "a.tex"}) == "statement"
    assert unit_of({"scope": "proof-step", "location": "a.tex:3"}) == "proof-passage"
    assert unit_of({"scope": "proof-step", "location": "a.tex:3"},
                   {"kind": "environment"}) == "proof-equation"
    assert unit_of({"scope": "formal", "unit": "proof-passage", "location": "a.tex:3"}) == \
        "proof-passage"
    assert unit_of({"scope": "formal", "unit": "nonsense"}) == "statement"


@needs_lean
@needs_tex
def test_a_proof_step_is_reviewed_from_the_command_line(toy, tmp_path, monkeypatch, capsys):
    _, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    who = ["--as", "human:Test-Referee"]
    unit = "step:T:eq:bound-sum"

    def run(*args):
        cli.main(["review", *args, *who])
        return capsys.readouterr().out

    def refused(*args):
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, *who])
        assert e.value.code == 2
        return capsys.readouterr().err

    files = {n: tmp_path / n for n in ("reading", "comparison", "detail", "none")}
    files["reading"].write_text("With n fixed, 2 T_n equals n^2 + n by Theorem 2.2.")
    files["comparison"].write_text("Theorem 2.2 gives 2 T_n = n(n+1) = n^2 + n for every n.")
    files["none"].write_text("none")
    step1 = run("read", unit)
    assert "A step of the proof of Theorem 2.5" in step1
    # The printed step and its context in the proof are in the packet; no Lean is.
    assert "2\\,T_n = n^2 + n." in step1 and "Fix $n$." in step1
    assert "Toy.Acceptance" not in step1
    run("lock", unit, str(files["reading"]))
    assert "Toy.Acceptance.thm_triangle" in run("show", unit)
    # A statement verdict does not apply to a printed step.
    assert "not one of" in refused("decide", unit, "faithful", str(files["comparison"]))
    run("decide", unit, "holds as printed", str(files["comparison"]))
    run("author", unit)
    run("submit", unit, str(files["none"]))
    out = tmp_path / "reports.json"
    run("export", "--out", str(out))
    (r,) = pr.load_reports([out])
    assert r["unit"]["kind"] == "step" and r["unit"]["target"] == "proof-equation"
    assert r["unit"]["parent"] == {"id": "T:thm:bound", "number": "Theorem 2.5"}
    assert r["unit"]["lean"] == ["Toy.Acceptance.thm_triangle"]
    assert r["pins"]["fingerprints"]["source"] == chunk(cfg, "T:eq:bound-sum")["source_sha256"]
    assert r["issue_draft"] is None
    # A step report is not a review marker: promotion refuses it.
    (_, _, why), = pr.plan(cfg, [r])
    assert why
    # Kept in the project's review folder, it becomes the step's finding, and only the step's.
    (toy / "machinechecked-reviews" / "cli.json").write_text(out.read_text())
    index, _, cfg = build(toy, reuse_lean=True)
    assert chunk(cfg, "T:eq:bound-sum")["step"]["review"]["state"] == "holds"
    assert {c["id"]: c["status"] for c in index["claims"]} == {**EXPECTED, **STEPS}


def test_issue_drafts_name_the_step_and_its_question():
    from prooflens.review_cli import issue_draft
    u = {"id": "step:T:eq:x", "kind": "step", "name": "Equation (3)", "claims": [],
         "parent": {"id": "T:thm:x", "number": "Theorem 2.5"}}
    d = issue_draft(u, "false as printed", "fails at k = 0")
    assert d["kind"] == "finding on a proof step"
    assert d["title"] == "Equation (3) in the proof of Theorem 2.5: false as printed"
    assert "not the statement of Theorem 2.5" in d["body"]
    assert issue_draft(u, "cannot determine", "q")["kind"] == "unresolved question"
    assert issue_draft(u, "holds as printed", "") is None
