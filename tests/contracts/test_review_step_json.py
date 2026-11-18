"""`review lock|decide|submit UNIT ... --json` (#614): a single unit's step answers with one JSON
document, holding what a manifest entry's result holds; a refusal is the structured refusal;
`decide` alone takes the verdict's fields, and its help says which verdicts need a detail and
what it says, as the review page asks (tests/fixtures/review/verdict-details.json).

The site is the synthetic zero-configuration build of `test_compare.write_site`, with one more
unit copied from its first. Nothing here builds Lean."""

import copy
import json
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from test_compare import write_site

UNIT = "link:thm:t0"
OTHER = "link:thm:other"
WHO = "human:Step-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
DETAILS = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "review"
                      / "verdict-details.json").read_text(encoding="utf-8"))


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text(encoding="utf-8"))
    u = copy.deepcopy(q["units"][0])
    u["id"] = OTHER
    q["units"].append(u)
    (data / "review-queue.json").write_text(json.dumps(q), encoding="utf-8")
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    return work


def run(capsys, *args, code=None):
    """What the command prints on standard output (one JSON document with --json), after
    checking how it exited."""
    if code is None:
        cli.main(["review", *args, "--as", WHO])
    else:
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, "--as", WHO])
        assert e.value.code == code
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in args else out


def texts(tmp_path) -> dict:
    files = {"reading": READING, "cmp": "Item by item, the same bound.", "none": "none",
             "detail": "Weaker in n: take n = 0 to recover the printed bound."}
    for name, text in files.items():
        (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    return {name: str(tmp_path / f"{name}.md") for name in files}


@pytest.mark.parametrize("kind,key", [("spec", "statement"), ("link", "statement"),
                                      ("step", "step")])
def test_the_detail_each_verdict_needs_is_the_review_page_s(kind, key):
    """The command line asks for the detail of tests/fixtures/review/verdict-details.json, which
    web/tests/review.test.mjs checks the review page asks for too, verdict for verdict."""
    table = rc.STEP_VERDICTS if kind == "step" else rc.VERDICTS
    assert sorted(v for vs in table.values() for v in vs) == sorted(DETAILS[key])
    for verdict, detail in DETAILS[key].items():
        assert rc.detail_asked({"kind": kind}, verdict) == detail, verdict


def test_each_step_of_a_unit_answers_with_one_document(work, tmp_path, capsys):
    f = texts(tmp_path)
    rc.Session(work, rc.parse_reviewer(WHO)).read(UNIT)
    lock = run(capsys, "lock", UNIT, f["reading"], "--json")
    assert {k: lock[k] for k in ("schema", "action", "ok", "unit", "step", "revealed_by")} == {
        "schema": "machinechecked/review-step@1", "action": "lock", "ok": True, "unit": UNIT,
        "step": "compare", "revealed_by": []}
    s = rc.Session(work, rc.parse_reviewer(WHO))
    assert lock["locked_at"] == s.work["drafts"][UNIT]["locked_at"]
    assert lock["workspace"] == {"id": s.workspace["id"], "mode": "independent"}

    s.show(UNIT)
    decide = run(capsys, "decide", UNIT, "broader", f["cmp"], "--detail", f["detail"],
                 "--coverage", "full", "--basis", "direct", "--json")
    assert {k: decide[k] for k in ("action", "ok", "step", "verdict", "group",
                                   "correspondence")} == {
        "action": "decide", "ok": True, "step": "author", "verdict": "broader",
        "group": "matches", "correspondence": {"coverage": "full", "basis": "direct"}}
    assert decide["decided_at"] >= lock["locked_at"]

    rc.Session(work, rc.parse_reviewer(WHO)).author(UNIT)
    submit = run(capsys, "submit", UNIT, f["none"], "--json")
    report, = rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]
    assert {k: submit[k] for k in ("action", "ok", "step", "verdict", "group", "submitted_at",
                                   "revealed_by")} == {
        "action": "submit", "ok": True, "step": "submitted", "verdict": "broader",
        "group": "matches", "submitted_at": report["submitted_at"],
        "revealed_by": report["reading"]["revealed_by"]}

    # Without --json, the same line as before.
    rc.Session(work, rc.parse_reviewer(WHO)).read(OTHER)
    assert run(capsys, "lock", OTHER, f["reading"]) == \
        f"reading locked; `review show {OTHER}` shows the Lean\n"


def test_a_refused_step_answers_with_the_structured_refusal(work, tmp_path, capsys):
    f = texts(tmp_path)
    # Out of order: no verdict before the reading is locked, and nothing is recorded.
    doc = run(capsys, "decide", UNIT, "faithful", f["cmp"], "--json", code=2)
    assert doc["schema"] == "machinechecked/review-error@1" and doc["ok"] is False
    assert doc["error"]["kind"] == "order" and "needs step 'compare'" in doc["error"]["message"]
    rc.Session(work, rc.parse_reviewer(WHO)).read(UNIT)
    run(capsys, "lock", UNIT, f["reading"], "--json")
    doc = run(capsys, "lock", UNIT, f["reading"], "--json", code=2)
    assert doc["error"]["kind"] == "order"
    rc.Session(work, rc.parse_reviewer(WHO)).show(UNIT)
    # A verdict without the detail it needs says what the detail says.
    doc = run(capsys, "decide", UNIT, "narrower", f["cmp"], "--json", code=2)
    assert doc["error"] == {"kind": "invalid", "message": "verdict 'narrower' needs --detail: "
                            "say exactly how: which hypothesis is added, which case is lost."}
    # A text that cannot be read is refused too, as in a manifest.
    doc = run(capsys, "decide", UNIT, "faithful", str(tmp_path / "missing.md"), "--json",
              code=2)
    assert doc["error"]["kind"] == "invalid" and "missing.md" in doc["error"]["message"]
    assert rc.Session(work, rc.parse_reviewer(WHO)).work["drafts"][UNIT]["stage"] == "compare"


def test_a_unit_s_result_is_a_manifest_entry_s(work, tmp_path, capsys):
    """The single command and a manifest entry give the same fields; a mixed manifest still
    reports each entry, and exits 2."""
    f = texts(tmp_path)
    for uid in (UNIT, OTHER):
        rc.Session(work, rc.parse_reviewer(WHO)).read(uid)
    one = run(capsys, "lock", UNIT, f["reading"], "--json")
    (tmp_path / "m.json").write_text(json.dumps([
        {"unit": OTHER, "reading": READING}, {"unit": UNIT, "reading": READING}]),
        encoding="utf-8")
    doc = run(capsys, "lock", "--manifest", str(tmp_path / "m.json"), "--json", code=2)
    assert doc["schema"] == "machinechecked/review-manifest@1" and doc["ok"] is False
    taken, refused = doc["entries"]
    assert set(taken) - {"entry"} == set(one) - {"schema", "action", "workspace"}
    assert (taken["unit"], taken["step"], taken["revealed_by"]) == (OTHER, "compare", [])
    assert refused["ok"] is False and refused["error"]["kind"] == "order"


def test_only_decide_takes_the_verdict_s_fields(work, tmp_path, capsys):
    f = texts(tmp_path)
    for action in ("lock", "submit"):
        for opt in (["--detail", f["detail"]], ["--coverage", "full"],
                    ["--member", "A.x", "faithful", "-"]):
            with pytest.raises(SystemExit) as e:
                cli.main(["review", action, UNIT, f["reading"], *opt, "--as", WHO])
            assert e.value.code == 2
            assert "unrecognized arguments" in capsys.readouterr().err
    # With a manifest, the verdict's fields are the entries': an option beside it is refused.
    (tmp_path / "d.json").write_text("[]", encoding="utf-8")
    doc = run(capsys, "decide", "--manifest", str(tmp_path / "d.json"), "--coverage", "full",
              "--json", code=2)
    assert doc["error"]["kind"] == "invalid" and "not both" in doc["error"]["message"]


def test_decide_s_help_says_what_each_verdict_s_detail_says(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "decide", "--help"])
    assert e.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    for key in ("statement", "step"):
        for verdict, detail in DETAILS[key].items():
            assert verdict in text and (detail is None or detail in text), verdict
    for line in ("faithful Needs no detail.", "holds as printed Needs no detail.",
                 "broader State the instantiation that gives the printed claim.",
                 "faithful to the correction Only for a correction or a special case of a "
                 "printed clause. Needs no detail.",
                 "refutation not valid Only for a locked statement, whether or not it is "
                 "refuted: that is shown after the verdict. Say how",
                 "cannot determine Say what would decide it.",
                 "(--coverage partial, changed or related)"):
        assert line in text, line
