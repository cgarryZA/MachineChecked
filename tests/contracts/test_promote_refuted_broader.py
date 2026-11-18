"""#765: a "broader" verdict says the Lean proposition is more general than the printed claim. A
proof of it carries to the printed claim; a refutation does not, since the printed claim can hold
while a more general proposition fails. `review promote` refuses such a verdict on a proposition
that a clause refutes, unless the clause declares its refutation outside the paper's standing
assumptions (a refutation of the formal proposition only). It promotes it on a proved one."""

import json
from types import SimpleNamespace

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr
from prooflens.assess import OUTSIDE

SPEC, H = "Toy.PaperSpec.prop_x", "a" * 32
CFG = SimpleNamespace(statement_authors=["statement-author"])


def body(**clause):
    return {"lean": {"specs": {SPEC: {"fingerprint": "pl-fp-v1:" + H, "legacy_hash": H}},
                     "decls": {}},
            "inventory": {"claims": [{"id": "T:prop:x", "paper": "T", "clauses": [
                {"name": "as printed", "spec": SPEC, **clause}]}]},
            "tex": {}, "provenance": {"papers": {}}}


def report(verdict, detail="take n = 1", kind="spec"):
    return {"schema": "prooflens/review-report@1",
            "unit": {"id": f"{kind}:{SPEC}", "kind": kind, "name": SPEC, "claims": [],
                     "papers": ["T"]},
            "pins": {"release": "r1", "legacy_hash": H, "fingerprint": "pl-fp-v1:" + H,
                     "source_sha256": {}, "manuscripts": {}},
            "reviewer": {"id": "human:Referee", "kind": "human", "same_family_as_author": "no"},
            "reading": {"text": "The printed claim, read first.",
                        "locked_at": "2026-01-01T10:00:00Z"},
            "comparison": {"text": "Compared item by item.",
                           "decided_at": "2026-01-01T10:05:00Z"},
            "verdict": {"group": "matches", "value": verdict, "detail": detail},
            "author_review": {"shown_at": "2026-01-01T10:05:00Z", "disagreements": "none"},
            "submitted_at": "2026-01-01T10:06:00Z"}


def refusals(r, b):
    return [w for w in pr.check_report(r, b, CFG, False) if "more general" in w]


def test_a_broader_verdict_on_a_refuted_proposition_is_refused():
    (why,) = refusals(report("broader"), body(refute="Toy.Acceptance.no_x"))
    assert why.startswith("verdict 'broader' says the proposition is more general than the "
                          "printed claim, so a refutation of it does not refute the printed claim")
    assert "T:prop:x (clause 'as printed')" in why


@pytest.mark.parametrize("clause", [
    {"accept": "Toy.Acceptance.x"},                                    # proved
    {"refute": "Toy.Acceptance.no_x", "refute_scope": OUTSIDE},       # refuted outside only
])
def test_a_broader_verdict_where_it_agrees_with_the_clause_is_promoted(clause):
    assert pr.check_report(report("broader"), body(**clause), CFG, False) == []


@pytest.mark.parametrize("verdict,detail", [
    ("faithful", ""), ("faithful with representation choices", "n is a natural number")])
def test_a_verdict_that_carries_the_refutation_is_promoted(verdict, detail):
    assert pr.check_report(report(verdict, detail), body(refute="Toy.Acceptance.no_x"), CFG,
                           False) == []


WHO = ["--as", "human:Test-Referee"]


def run(capsys, *args):
    cli.main(["review", *args, *WHO])
    return capsys.readouterr().out


@needs_lean
@needs_tex
def test_the_toy_paper_refused_through_the_review_steps(toy, tmp_path, monkeypatch, capsys):
    """The issue's reproduction: "broader" on the toy's refuted proposition, through every
    step of the protocol, then promotion; and "broader" on a proved proposition."""
    _, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    files = {n: tmp_path / f"{n}.md" for n in ("reading", "comparison", "detail", "none")}
    for n, text in (("reading", "For every natural number n, the predecessor of n is below n."),
                    ("comparison", "The Lean states it for every n, item by item."),
                    ("detail", "Take the printed range of n."), ("none", "none")):
        files[n].write_text(text)
    for uid in ("spec:Toy.PaperSpec.prop_pred", "spec:Toy.PaperSpec.thm_triangle"):
        run(capsys, "read", uid)
        run(capsys, "lock", uid, str(files["reading"]))
        run(capsys, "show", uid)
        run(capsys, "decide", uid, "broader", str(files["comparison"]), "--detail",
            str(files["detail"]))
        run(capsys, "author", uid)
        run(capsys, "submit", uid, str(files["none"]))
    out = tmp_path / "reports.json"
    run(capsys, "export", "--out", str(out))
    plan = {r["unit"]["name"]: why for r, _, why in pr.plan(cfg, pr.load_reports([out]))}
    assert any("more general than the printed claim" in w and "T:prop:pred" in w
               for w in plan["Toy.PaperSpec.prop_pred"]), plan
    assert not [w for w in plan["Toy.PaperSpec.thm_triangle"] if "more general" in w]
    # Promotion refuses it from the command line, and writes no marker.
    doc = json.loads(out.read_text())
    doc["reports"] = [r for r in doc["reports"]
                      if r["unit"]["name"] == "Toy.PaperSpec.prop_pred"]
    refused = tmp_path / "refused.json"
    refused.write_text(json.dumps(doc))
    before = {p: p.read_text() for p in (toy / "reviews").rglob("*.md")}
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "promote", str(refused), "--yes"])
    said = capsys.readouterr()
    assert e.value.code == 2 and "nothing to promote" in said.err
    assert "REFUSED  Toy.PaperSpec.prop_pred (spec)" in said.out
    assert {p: p.read_text() for p in (toy / "reviews").rglob("*.md")} == before
