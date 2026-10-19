"""Proof steps in zero configuration (#125): the numbered equations of a proof are found in the
paper, linked in the links file or formalization.yaml, reviewed on their own, and leave every
statement's links and status as they were."""

import json
import re
import shutil

import pytest

from conftest import needs_lean, needs_tex
from prooflens.manifest import claim_file
from prooflens.review_queue import simple_queue
from prooflens.simple import build_view, built_modules, save_link, save_route, write_view_site
from prooflens.steps import aux_numbers, find_proof_equations

TRI, BOUND = "Toy.Acceptance.thm_triangle", "Toy.Acceptance.thm_bound"
PAPER = "paper/toy.tex"


@pytest.fixture
def proj(toy):
    """The toy paper inside its Lean project, as zero configuration finds it."""
    root = toy / "lean"
    (root / "paper").mkdir()
    shutil.copy(toy / "paper/toy.tex", root / PAPER)
    if not built_modules(root, ["Toy"])[0]:
        pytest.skip("the toy example is not built")
    return root


def view(root):
    return build_view(root, root / PAPER, root / ".machinechecked", log=lambda m: None)


def test_equations_inside_proofs_are_found_by_label_and_number():
    lines = [r"\begin{theorem}\label{thm:a} X. \end{theorem}",
             r"\begin{equation}\label{eq:out} 1 \end{equation}",
             r"\begin{proof}[Proof of Theorem~\ref{thm:a}]",
             r"\begin{equation}\label{eq:in}",
             r"  a \le b,",
             r"\end{equation}",
             r"% \begin{equation}\label{eq:commented} 2 \end{equation}",
             r"\begin{equation*} c \end{equation*}",
             r"\begin{align}\label{eq:one} x \\ y \label{eq:two}\end{align}",
             r"\end{proof}"]
    numbers = aux_numbers(r"\newlabel{eq:out}{{1}{1}}\newlabel{eq:in}{{2}{1}{}{equation.2}{}}"
                          r"\newlabel{eq:one}{{3}{1}}\newlabel{eq:two}{{4}{1}}")
    assert numbers["eq:in"] == "2"
    # Outside a proof, commented out, unnumbered, or with two labels: not a step.
    found = find_proof_equations(lines, "p.tex", numbers)
    assert [(f["label"], f["number"], f["line"], f["end_line"], f["proof_line"], f["proof_ref"])
            for f in found] == [("eq:in", "2", 4, 6, 3, "thm:a")]


@needs_lean
@needs_tex
def test_proof_steps_in_zero_configuration(proj):
    # The same paper with the proof's equations unlabelled: the statements as they were.
    plain = proj.parent / "plain"
    shutil.copytree(proj, plain, symlinks=True,
                    ignore=shutil.ignore_patterns(".machinechecked"))
    tex = (plain / PAPER).read_text()
    (plain / PAPER).write_text(re.sub(r"\\label\{eq:bound-(sum|range)\}", "", tex))
    before = {c["id"]: (c["status_code"], [l["name"] for l in c["links"]],
                        [s["name"] for s in c["suggestions"]])
              for c in view(plain)["body"]["claims"]}
    assert not any(c.startswith("P:eq:") for c in before)

    body = view(proj)["body"]
    claims = {c["id"]: c for c in body["claims"]}
    assert {k: (c["status_code"], [l["name"] for l in c["links"]],
                [s["name"] for s in c["suggestions"]])
            for k, c in claims.items() if c.get("unit") != "proof-equation"} == before
    s2, s3 = claims["P:eq:bound-sum"], claims["P:eq:bound-range"]
    assert (s2["number"], s2["parent"], s2["unit"]) == ("Equation (2)", "P:thm:bound",
                                                        "proof-equation")
    assert s3["number"] == "Equation (3)" and s3["location"] == "toy.tex:76"
    assert s3["line_anchor"]["kind"] == "approximate"
    # Its context: the quantifier sentence before it and the use of it after it.
    assert r"For every natural number $k \ge 0$," in s3["context_tex"]
    assert "the choice $k = 1$" in s3["context_tex"]
    # Nothing is suggested for a step, and nothing links it until someone does.
    assert s2["suggestions"] == [] and s2["status_code"] == "link.none"

    # Linked in the reader: the Lean that establishes one step, the route used instead of the
    # other.
    save_link(proj, PAPER, "eq:bound-sum", [TRI], by="human:A-Referee")
    save_route(proj, PAPER, "eq:bound-range", [BOUND], note="Lean bounds n by n * n.",
               by="human:A-Referee")
    v = view(proj)
    body = v["body"]
    claims = {c["id"]: c for c in body["claims"]}
    assert claims["P:eq:bound-sum"]["status_code"] == "link.checked"
    assert claims["P:eq:bound-range"]["status_code"] == "link.other-route"
    assert claims["P:eq:bound-range"]["links"] == []
    assert {k: c["status_code"] for k, c in claims.items() if not c.get("unit")} == \
        {k: x[0] for k, x in before.items()}

    # A reviewer's report on the step is its finding; the parent has none of it.
    rs = proj / "machinechecked-reviews"
    rs.mkdir()
    rep = {"schema": "prooflens/review-report@1",
           "unit": {"id": "step:P:eq:bound-range", "kind": "step"},
           "pins": {"fingerprints": {"source": claims["P:eq:bound-range"]["source_sha256"]}},
           "reviewer": {"id": "human:A-Referee", "kind": "human", "name": "A Referee"},
           "reading": {"text": "n <= k n^2 for all k >= 0", "locked_at": "2026-10-19T00:00:00Z"},
           "comparison": {"text": "k = 0, n = 1 gives 1 <= 0."},
           "verdict": {"group": "problem", "value": "false as printed",
                       "detail": "fails at k = 0"},
           "submitted_at": "2026-10-19T00:01:00Z"}
    (rs / "r.json").write_text(json.dumps({"schema": "prooflens/review-reports@1",
                                           "reports": [rep]}))
    v = view(proj)
    site = proj / ".machinechecked/site"
    index = write_view_site(v, site, None, proj)
    rows = {c["id"]: c for c in index["claims"]}
    assert rows["P:eq:bound-range"]["unit"] == "proof-equation"
    assert rows["P:eq:bound-range"]["anchor"]["kind"] == "approximate"
    assert rows["P:thm:bound"]["unit"] == "statement"
    assert index["units"]["P"]["proof-equation"] == {
        "linked: Lean proof checked": 1, "linked: a different formal route": 1}
    assert sum(index["units"]["P"]["statement"].values()) == len(before)

    def chunk(cid):
        return json.loads((site / "data/claims" / claim_file(cid)).read_text())

    st = chunk("P:eq:bound-range")["step"]
    assert st["links"] == [] and st["route"]["links"][0]["name"] == BOUND
    assert st["route"]["note"] == "Lean bounds n by n * n." and st["route"]["by"] == "human:A-Referee"
    assert st["review"]["state"] == "false"
    s2 = chunk("P:eq:bound-sum")["step"]
    assert [l["name"] for l in s2["links"]] == [TRI] and s2["review"]["state"] == "unreviewed"
    parent = chunk("P:thm:bound")
    assert "step" not in parent and parent["reviews"] == []
    assert [(s["id"], s["review"]) for s in parent["steps"]] == [
        ("P:eq:bound-sum", "unreviewed"), ("P:eq:bound-range", "false")]

    # Both steps are review units, the one with no Lean link included; a step is never a
    # `link` unit as well.
    q = json.loads((site / "data/review-queue.json").read_text())
    ids = {u["id"]: u for u in q["units"]}
    assert ids["step:P:eq:bound-range"]["lean"] == [] and \
        ids["step:P:eq:bound-range"]["state"] == "reviewed"
    assert ids["step:P:eq:bound-sum"]["state"] == "pending"
    assert "link:eq:bound-sum" not in ids
    assert q == simple_queue(json.loads((site / "data/index.json").read_text()),
                             {c["file"]: chunk(c["id"]) for c in index["claims"]})

    # Removing the route leaves the step unlinked again.
    save_route(proj, PAPER, "eq:bound-range", None)
    claims = {c["id"]: c for c in view(proj)["body"]["claims"]}
    assert claims["P:eq:bound-range"]["status_code"] == "link.none"


@needs_lean
@needs_tex
def test_formalization_yaml_names_a_step_and_its_route(proj):
    (proj / "formalization.yaml").write_text(
        "sources:\n  - title: A Toy Paper on Even and Triangular Numbers\n"
        "alignment:\n  statements:\n"
        f"    - source: Equation (2)\n      lean: {TRI}\n      note: the identity\n"
        f"    - source: Equation (3)\n      lean: {BOUND}\n      route: different\n"
        "      note: another argument\n")
    claims = {c["id"]: c for c in view(proj)["body"]["claims"]}
    s2, s3 = claims["P:eq:bound-sum"], claims["P:eq:bound-range"]
    assert [(l["name"], l["source"], l["status_code"]) for l in s2["links"]] == [
        (TRI, "formalization.yaml", "link.checked")]
    assert s2["correspondence"]["source"] == "formalization.yaml"
    assert s3["links"] == [] and s3["status_code"] == "link.other-route"
    assert [(l["name"], l["source"]) for l in s3["route_links"]] == [(BOUND, "formalization.yaml")]
    assert s3["route_note"]["note"] == "another argument"


def test_check_json_reports_a_step_review_apart():
    from prooflens.cli import _step_json
    rep = {"verdict": {"value": "false as printed"}, "pins": {"fingerprints": {"source": "a"}},
           "reviewer": {"id": "human:R"}, "submitted_at": "2026-10-19T00:00:00Z"}
    c = {"unit": "proof-equation", "source_sha256": "a", "step_reports": [rep],
         "route_links": [{"name": BOUND, "status_code": "link.checked"}]}
    out = _step_json(c)
    assert out["step_review"] == "false" and out["finding"]["verdict"] == "false as printed"
    assert out["route"] == [{"name": BOUND, "status_code": "link.checked"}]
    assert _step_json({**c, "source_sha256": "b"})["step_review"] == "stale"
    assert _step_json({**c, "step_reports": []})["step_review"] == "unreviewed"


@needs_lean
@needs_tex
def test_link_records_a_step_and_its_route_from_the_terminal(proj, monkeypatch, capsys):
    from prooflens import cli
    from prooflens.simple import load_links
    write_view_site(view(proj), proj / ".machinechecked/site", None, proj)
    monkeypatch.chdir(proj)
    cli.main(["link", "Equation (3)", BOUND, "--route", "--note", "Lean bounds n by n * n.",
              "--as", "human:A-Referee"])
    cli.main(["link", "eq:bound-sum", TRI, "--coverage", "full", "--as", "human:A-Referee"])
    entries = load_links(proj)["papers"][PAPER]
    assert entries["eq:bound-range"]["route"]["lean"] == [BOUND]
    assert entries["eq:bound-range"]["route"]["note"] == "Lean bounds n by n * n."
    assert "lean" not in entries["eq:bound-range"]
    assert entries["eq:bound-sum"]["lean"] == [TRI]
    claims = {c["id"]: c for c in view(proj)["body"]["claims"]}
    assert claims["P:eq:bound-range"]["status_code"] == "link.other-route"
    assert claims["P:eq:bound-sum"]["status_code"] == "link.checked"
    # A route belongs to a proof step only.
    with pytest.raises(SystemExit):
        cli.main(["link", "thm:bound", BOUND, "--route"])
    assert "not a proof step" in capsys.readouterr().err
    # Without declarations, --route clears the step's route.
    cli.main(["link", "eq:bound-range", "--route"])
    assert load_links(proj)["papers"][PAPER]["eq:bound-range"]["route"]["lean"] == []
