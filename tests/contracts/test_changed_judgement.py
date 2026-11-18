"""A reviewer's judgement changed after the author's review was shown (#665): `review submit`
(and the review page) records it, with its reason and optionally a revised verdict, beside the
blind verdict, which stays as it was recorded; each keeps its time. `review promote` never
promotes such a report, whatever the maintainer passes, and its plan shows both judgements. In
zero configuration it is not counted (`simple.counted`). The site is the synthetic one of
`test_compare.write_site`; nothing here builds Lean."""

import json
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import simple
from test_compare import write_site

UNIT = "link:thm:t0"
WHO = "human:Changed-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
REASON = "The author's account shows the bound is meant for n >= 1 only."
CASES = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "review"
                    / "changed-judgement.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["name"])
def test_a_changed_judgement_is_recorded_as_the_review_page_records_it(case):
    """The command line records, or refuses, the changed judgements of
    tests/fixtures/review/changed-judgement.json as web/tests/review.test.mjs checks the review
    page does."""
    got, why = rc.changed_judgement(CASES["units"][case["unit"]], case["blind"], case["given"])
    assert bool(why) == bool(case.get("refused")), why
    if not case.get("refused"):
        assert got == case["judgement"]


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_site(tmp_path)
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    for name, text in {"reading.md": READING, "cmp.md": "The same bound, for every n.",
                       "none.md": "none", "reason.md": REASON,
                       "detail.md": "Lean adds n >= 1."}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return work


def session(work):
    return rc.Session(work, rc.parse_reviewer(WHO))


def at_step_3(work, verdict="faithful"):
    s = session(work)
    s.read(UNIT)
    s.lock(UNIT, READING)
    s.show(UNIT)
    session(work).decide(UNIT, verdict, "The same bound, for every n.")
    session(work).author(UNIT)


def run(capsys, *args, code=None):
    if code is None:
        cli.main(["review", *args, "--as", WHO])
    else:
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, "--as", WHO])
        assert e.value.code == code
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in args else out


def test_submit_keeps_the_blind_verdict_beside_the_changed_judgement(work, tmp_path, capsys):
    at_step_3(work)
    f = {n: str(tmp_path / f"{n}.md") for n in ("none", "reason", "detail")}
    # A revised verdict needs a reason, and the detail it asks for.
    doc = run(capsys, "submit", UNIT, f["none"], "--revised-verdict", "narrower", "--json",
              code=2)
    assert doc["error"]["kind"] == "invalid" and "give the reason" in doc["error"]["message"]
    doc = run(capsys, "submit", UNIT, f["none"], "--judgement-changed", f["reason"],
              "--revised-verdict", "narrower", "--json", code=2)
    assert "needs its detail" in doc["error"]["message"]
    doc = run(capsys, "submit", UNIT, f["none"], "--judgement-changed", f["reason"],
              "--revised-verdict", "narrower", "--revised-detail", f["detail"], "--json")
    assert doc["step"] == "submitted" and doc["verdict"] == "faithful"
    cj = doc["changed_judgement"]
    assert (cj["reason"], cj["verdict"]) == (REASON, {"group": "problem", "value": "narrower",
                                                      "detail": "Lean adds n >= 1."})
    (r,) = session(work).work["reports"]
    assert r["verdict"]["value"] == "faithful" and r["changed_judgement"] == cj
    assert r["comparison"]["decided_at"] <= r["author_review"]["shown_at"] <= cj["recorded_at"]
    # Undo gives the judgement back; submitted again without it named, it stands, at its time.
    session(work).undo()
    assert session(work).work["drafts"][UNIT]["changed"] == {
        "reason": REASON, "verdict": "narrower", "detail": "Lean adds n >= 1.",
        "recorded_at": cj["recorded_at"]}
    doc = run(capsys, "submit", UNIT, f["none"], "--json")
    assert doc["changed_judgement"] == cj


def test_a_changed_judgement_is_refused_where_it_cannot_be_one(work, tmp_path, capsys):
    at_step_3(work)
    doc = run(capsys, "submit", UNIT, str(tmp_path / "none.md"), "--judgement-changed",
              str(tmp_path / "reason.md"), "--revised-verdict", "faithful", "--json", code=2)
    assert "is the verdict recorded before the author's review" in doc["error"]["message"]
    assert UNIT in session(work).work["drafts"]
    # An informed review records its verdict again instead.
    s = rc.Session(work, rc.parse_reviewer(WHO), mode="informed")
    s.show(UNIT)
    s.decide(UNIT, "faithful", "Compared, informed.")
    with pytest.raises(rc.ReviewError) as e:
        rc.Session(work, rc.parse_reviewer(WHO), mode="informed").submit(
            UNIT, "none", {"reason": REASON})
    assert e.value.kind == "invalid" and "record the verdict again" in str(e.value)


def test_a_manifest_and_the_page_record_it_too(work, tmp_path, capsys):
    at_step_3(work)
    (tmp_path / "m.json").write_text(json.dumps([
        {"unit": UNIT, "disagreements": "none", "judgement_changed": REASON}]))
    doc = run(capsys, "submit", "--manifest", str(tmp_path / "m.json"), "--json")
    (e,) = doc["entries"]
    assert e["changed_judgement"]["reason"] == REASON and e["changed_judgement"]["verdict"] is None
    # The page: a judgement typed and saved is the draft's, an explicit empty one records none.
    session(work).undo()
    post = rc.api(work, work / "site" / "data")[1]["/api/review"]
    st = post({"reviewer": WHO, "action": "edit", "unit": UNIT, "stage": "author",
               "fields": {"changed": {**st_changed(work), "reason": REASON}}})
    assert st["drafts"][UNIT]["changed"]["recorded_at"]  # the same judgement keeps its time
    st = post({"reviewer": WHO, "action": "submit", "unit": UNIT, "disagreements": "none",
               "changed": {}})
    assert "changed_judgement" not in st["report"]


def st_changed(work) -> dict:
    return dict(session(work).work["drafts"][UNIT]["changed"])


def report_with(changed: dict | None) -> dict:
    """A report of a structure's unit (`test_structure_unit`), with a changed judgement."""
    from test_structure_unit import report, unit
    r = report(unit())
    if changed is not None:
        r["changed_judgement"] = changed
    return r


def test_promotion_never_promotes_a_changed_judgement(tmp_path):
    from types import SimpleNamespace
    from test_structure_unit import body
    cfg = SimpleNamespace(reviews=[tmp_path], ai_reviewers=[], root=tmp_path,
                          statement_authors=["statement-author"])
    changed = {"reason": REASON, "recorded_at": "2026-01-01T10:06:00Z",
               "verdict": {"group": "problem", "value": "narrower", "detail": "Lean adds n >= 1."}}
    assert pr.check_report(report_with(None), body(), cfg, False) == []
    for allow in (False, True):
        why = pr.check_report(report_with(changed), body(), cfg, True, allow_revealed=allow)
        assert why == [
            "its reviewer changed their judgement after the author's review: blind verdict "
            "'faithful' (recorded 2026-01-01T10:05:00Z, before the author's review); changed "
            "after the author's review (recorded 2026-01-01T10:06:00Z) to 'narrower' (Lean adds "
            f"n >= 1.): {REASON}. The blind verdict is not promoted, and the later judgement is "
            "not a blind review: ask for a fresh independent review, or record the later "
            "judgement as an informed review (`machinechecked review ... --mode informed`), "
            "which promotion accepts only with --allow-revealed"]
    text = pr.report_text(report_with({**changed, "verdict": None}))
    assert "Judgement changed after the author's review: blind verdict 'faithful'" in text
    assert "naming no verdict" in text


def test_zero_configuration_does_not_count_a_changed_judgement():
    plain = report_with(None)
    changed = report_with({"reason": REASON, "verdict": None, "recorded_at": "t"})
    assert simple.counted([plain, changed]) == ([plain], [changed])
    v = simple.uncounted_view(changed)
    assert v["verdict"]["value"] == "faithful" and v["changed_judgement"] == {
        "reason": REASON, "recorded_at": "t", "verdict": None}
    assert v["reviewer"]["id"] == plain["reviewer"]["id"] and "not counted" in v["why"]
