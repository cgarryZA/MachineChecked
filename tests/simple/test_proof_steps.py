"""Proof steps in zero configuration (#125): the numbered equations of a proof are found in the
paper, linked in the links file or formalization.yaml, reviewed on their own, and leave every
statement's links and status as they were."""

import json
import re
import shutil
from pathlib import Path

import pytest

from conftest import needs_lean, needs_tex
from prooflens import authoring, cli as _cli, simple as _simple
from prooflens.manifest import claim_file
from prooflens.review_queue import prioritise, simple_queue
from prooflens.simple import build_view, built_modules, save_link, save_route, write_view_site
from prooflens.steps import (PassageError, aux_numbers, find_proof_equations, parse_passage,
                             passage_claims, passage_key, select_passage)
from prooflens.targets import Snapshot

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
    written = json.loads((site / "data/index.json").read_text())
    assert q == prioritise(simple_queue(written,
                                        {c["file"]: chunk(c["id"]) for c in index["claims"]}),
                           uses=v.get("uses"), unbuilt=v["body"]["project"]["unbuilt"],
                           claims=written["claims"])

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
    # A route link Lean did not check names its module, as a link does.
    unbuilt = {"name": BOUND, "status_code": "link.module-unbuilt",
               "status_detail": "Module Synthetic.Main is not built."}
    assert _step_json({**c, "route_links": [unbuilt]})["route"] == [unbuilt]
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


# -- proof passages (#544) --------------------------------------------------------------------

PLAIN = Path(__file__).resolve().parents[2] / "examples" / "plain-paper"
SQ = "Plain.sq_odd"
TEX = r"""\begin{theorem}\label{thm:a}
A.
\end{theorem}
\begin{theorem}\label{thm:b}
B.
\end{theorem}
\begin{proof}[Proof of Theorem~\ref{thm:a}]
First line.
\begin{equation}
x = y
\end{equation}
% only a comment
Last line.
\end{proof}
"""
STATEMENTS = [{"id": "P:thm:a", "key": "thm:a", "number": "Theorem 1", "label": "thm:a",
               "location": "p.tex", "line": 1},
              {"id": "P:thm:b", "key": "thm:b", "number": "Theorem 2", "label": "thm:b",
               "location": "p.tex", "line": 4}]


def test_a_passage_is_whole_lines_inside_one_proof(tmp_path):
    (tmp_path / "p.tex").write_text(TEX)
    assert parse_passage("p.tex:8-13") == ("p.tex", 8, 13)
    assert parse_passage("p.tex:8") == ("p.tex", 8, 8)
    for bad in ("p.tex", "p.tex:9-8", "p.tex:0-2"):
        with pytest.raises(PassageError):
            parse_passage(bad)

    def refused(a, b, taken=()):
        with pytest.raises(PassageError) as e:
            select_passage(tmp_path, "p.tex", a, b, STATEMENTS, list(taken))
        return str(e.value)

    assert "not inside a proof" in refused(2, 2)
    assert "not inside a proof" in refused(7, 8)        # the proof's opening line
    assert "not inside a proof" in refused(13, 14)      # its closing line
    assert "begins the equation environment at line 9 without its end" in refused(8, 10)
    assert "ends the equation environment at line 11" in refused(10, 13)
    assert "hold no text" in refused(12, 12)
    assert "outside it" in refused(8, 99)
    hit = refused(8, 13, [{"id": "P:eq:x", "number": "Equation (1)", "file": "p.tex",
                           "start_line": 9, "end_line": 11}])
    assert "overlap Equation (1) (lines 9-11)" in hit
    sel = select_passage(tmp_path, "p.tex", 8, 13, STATEMENTS, [])
    # The proof names Theorem 1, which it follows only at a distance.
    assert sel["parent"]["id"] == "P:thm:a" and sel["proof_line"] == 7
    pin = sel["pin"]
    assert (pin["file"], pin["start_line"], pin["end_line"], pin["scheme"]) == \
        ("p.tex", 8, 13, "tex-region-v1")
    assert len(pin["line_sha256"]) == 6
    assert passage_key("thm:a", ["thm:a/passage-1", "thm:a/passage-3", "thm:b/passage-7"]) == \
        "thm:a/passage-4"


def test_a_passage_whose_lines_changed_has_no_current_text(tmp_path):
    (tmp_path / "p.tex").write_text(TEX)
    sel = select_passage(tmp_path, "p.tex", 13, 13, STATEMENTS, [])
    entries = {"thm:a/passage-1": {"passage": {**sel["pin"], "parent": "thm:a"},
                                   "route": {"lean": ["X.y"]}}}
    (c,), notes = passage_claims("P", entries, STATEMENTS, tmp_path)
    assert notes == []
    assert (c["id"], c["unit"], c["parent"], c["number"]) == (
        "P:thm:a/passage-1", "proof-passage", "P:thm:a", "Proof of Theorem 1, p.tex:13")
    assert c["source_sha256"] == sel["pin"]["sha256"] and c["statement_tex"] == "Last line."
    assert c["passage"]["matches"] and "First line." in c["context_tex"]
    # A line added above it: its lines hold other text now, and its text is two lines on.
    (tmp_path / "p.tex").write_text(TEX.replace("First line.\n", "First line.\nMore.\n"))
    (c,), notes = passage_claims("P", entries, STATEMENTS, tmp_path)
    assert c["source_sha256"] is None and c["statement_tex"] is None
    assert c["passage"]["matches"] is False
    assert c["passage"]["moved_to"] == {"start_line": 14, "end_line": 14}
    assert "no review of it counts" in notes[0] and "now at line 14" in notes[0]
    assert "machinechecked link thm:a/passage-1 --passage p.tex:14`" in notes[0]


@pytest.fixture
def plain(tmp_path, monkeypatch, capsys):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"),
        symlinks=True)
    if not built_modules(dst, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    monkeypatch.chdir(dst)
    _cli.main(["build"])
    capsys.readouterr()
    return dst


def link(capsys, *args):
    try:
        _cli.main(["link", *args, "--json"])
        code = 0
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def plain_view(root):
    return build_view(root, root / "paper/main.tex", root / ".machinechecked",
                      log=lambda m: None)


@needs_lean
@needs_tex
def test_a_proof_passage_in_zero_configuration(plain, capsys, tmp_path):
    key, cid, PAPERP = "thm:square/passage-1", "P:thm:square/passage-1", "paper/main.tex"
    before = {c["id"]: c["status_code"] for c in plain_view(plain)["body"]["claims"]}
    # Lines 31-32 of the proof of Theorem 3, with the formal route Lean takes instead.
    code, out = link(capsys, "Theorem 3", "--passage", "main.tex:31-32", SQ, "--route",
                     "--note", "Lean multiplies out (2k + 1)(2k + 1).", "--as", "human:A-Referee")
    assert code == 0 and out["written"]
    assert out["claim"] == {"id": cid, "key": key, "paper": "P", "kind": "passage",
                            "number": "Proof of Theorem 3, main.tex:31\u201332"}
    pin = out["after"]["passage"]
    assert (pin["file"], pin["start_line"], pin["end_line"], pin["parent"], pin["by"]) == \
        ("main.tex", 31, 32, "thm:square", "human:A-Referee")
    assert out["after"]["route"]["lean"] == [SQ]
    # The same lines again are the same passage; a path from the project's root is the same.
    code, out = link(capsys, "Theorem 3", "--passage", "paper/main.tex:31-32")
    assert code == 0 and out["claim"]["id"] == cid and not out["changed"]
    # Overlapping lines, lines of another result's proof, and lines outside a proof are refused.
    for args, why in ((("Theorem 3", "--passage", "main.tex:30-31"), "overlap " + key),
                      (("Theorem 2", "--passage", "main.tex:30"), "in the proof of Theorem 3"),
                      (("Theorem 3", "--passage", "main.tex:26-27"), "not inside a proof")):
        code, out = link(capsys, *args)
        assert code == 1 and not out["written"] and why in out["error"]["message"], out
    # The reader's request records a passage as `link --passage` does.
    snap = Snapshot(plain / ".machinechecked/site/data")
    ch = authoring.from_reader(plain, PAPERP, snap, {"key": "thm:square",
                                                     "passage": "main.tex:30"})
    assert ch["claim"]["id"] == "P:thm:square/passage-2"
    entries = _simple.load_links(plain)["papers"][PAPERP]
    assert entries["thm:square/passage-2"]["passage"]["start_line"] == 30

    # The next build lists both under Theorem 3, counts them as proof passages, and leaves
    # every statement as it was.
    _cli.main(["build"])
    capsys.readouterr()
    site = plain / ".machinechecked/site/data"
    index = json.loads((site / "index.json").read_text())
    rows = {c["id"]: c for c in index["claims"]}
    assert {k: rows[k]["status_code"] for k in before} == before
    assert rows[cid]["unit"] == "proof-passage" and rows[cid]["parent"] == "P:thm:square"
    assert rows[cid]["status_code"] == "link.other-route"
    assert rows[cid]["anchor"]["kind"] == "approximate"
    assert index["units"]["P"]["proof-passage"] == {"linked: a different formal route": 1,
                                                    "not linked": 1}
    assert index["semantic"]["papers"]["P"]["inventory"]["proof_passages"] == 2

    def chunk(c):
        return json.loads((site / "claims" / claim_file(c)).read_text())

    parent = chunk("P:thm:square")
    assert [s["id"] for s in parent["steps"]] == ["P:thm:square/passage-2", cid]
    st = chunk(cid)
    assert st["statement_tex"] == "Then $n^2 = 4k^2 + 4k + 1 = 2(2k^2 + 2k) + 1$,\nwhich is odd."
    assert "Write the odd number" in st["context_tex"]
    assert st["step"]["passage"]["matches"] and st["step"]["review"]["state"] == "unreviewed"
    assert [l["name"] for l in st["step"]["route"]["links"]] == [SQ]
    queue = {u["id"]: u for u in json.loads((site / "review-queue.json").read_text())["units"]}
    assert queue["step:" + cid]["state"] == "pending"
    # The local server gives the proof's lines with the steps in them, for the reader.
    proof = authoring.proof_route(site)({"claim": ["P:thm:square"]})["proofs"]
    assert [(p["file"], p["start_line"], p["end_line"]) for p in proof] == [("main.tex", 29, 33)]
    assert proof[0]["lines"][2] == "Then $n^2 = 4k^2 + 4k + 1 = 2(2k^2 + 2k) + 1$,"
    assert [s["id"] for s in proof[0]["steps"]] == ["P:thm:square/passage-2", cid]

    # `check --json` reports it, with its pin and its own review.
    _cli.main(["check", "--json"])
    found = {c["id"]: c for c in json.loads(capsys.readouterr().out)["claims"]}
    assert (found[cid]["unit"], found[cid]["parent"], found[cid]["step_review"]) == \
        ("proof-passage", "P:thm:square", "unreviewed")
    assert found[cid]["passage"]["matches"] and found[cid]["route"][0]["name"] == SQ

    # Reviewed as a `step:` unit, through the protocol.
    reading, cmp_, none = (tmp_path / n for n in ("reading.md", "comparison.md", "none.md"))
    reading.write_text("n^2 expands to 2(2k^2 + 2k) + 1, an odd number.")
    cmp_.write_text("The expansion is correct.")
    none.write_text("none")
    unit = "step:" + cid
    who = ["--as", "human:A-Referee"]
    for args in (("read", unit), ("lock", unit, str(reading)), ("show", unit),
                 ("decide", unit, "holds as printed", str(cmp_)), ("author", unit),
                 ("submit", unit, str(none))):
        _cli.main(["review", *args, *who])
    (plain / "machinechecked-reviews").mkdir()
    _cli.main(["review", "export", "--out", "machinechecked-reviews/r.json", *who])
    _cli.main(["build"])
    capsys.readouterr()
    assert chunk(cid)["step"]["review"]["state"] == "holds"
    assert "step" not in chunk("P:thm:square") and chunk("P:thm:square")["reviews"] == []

    # A line added above it moves its text: the passage's lines no longer hold it, so the
    # review does not count, and the build says where the text is now.
    tex = plain / PAPERP
    tex.write_text(tex.read_text().replace("\\begin{proof}\n", "\\begin{proof}\nWe compute.\n"))
    v = plain_view(plain)
    c = next(c for c in v["body"]["claims"] if c["id"] == cid)
    assert c["source_sha256"] is None and c["passage"]["moved_to"] == {"start_line": 32,
                                                                       "end_line": 33}
    assert any(key in n and "no review of it counts" in n for n in v["body"]["notes"])
    write_view_site(v, plain / ".machinechecked/site", None, plain)
    assert chunk(cid)["step"]["review"]["state"] == "stale"
    # Selected again at its new lines, it is the text that was reviewed.
    code, out = link(capsys, key, "--passage", "main.tex:32-33")
    assert code == 0 and out["after"]["passage"]["start_line"] == 32
    assert out["after"]["route"]["lean"] == [SQ]
    _cli.main(["build"])
    capsys.readouterr()
    assert chunk(cid)["step"]["review"]["state"] == "holds"
    # `--passage none` removes a passage.
    code, out = link(capsys, "P:thm:square/passage-2", "--passage", "none")
    assert code == 0 and out["after"] is None
    assert "thm:square/passage-2" not in _simple.load_links(plain)["papers"][PAPERP]
