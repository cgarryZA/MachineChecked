"""`review lock|decide|submit --manifest FILE` (#624): each entry of a JSON list is that step for
its unit, through the same `Session` methods and refusals as the single command; a refused entry
is reported, and the others are still taken; `--json` gives one document; a unit's name may be
non-ASCII; texts are inline or `NAME_file`, relative to the manifest.

The site is the synthetic zero-configuration build of `test_compare.write_site`, with two more
units copied from its first. Nothing here builds Lean."""

import copy
import json

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from test_compare import write_site

UNIT = "link:thm:t0"
SIGMA = "link:thm:σ-bound"
UNREAD = "link:thm:unread"
WHO = "human:Manifest-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text(encoding="utf-8"))
    for uid in (SIGMA, UNREAD):
        u = copy.deepcopy(q["units"][0])
        u["id"] = uid
        q["units"].append(u)
    (data / "review-queue.json").write_text(json.dumps(q), encoding="utf-8")
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    return work


def manifest(tmp_path, name, entries):
    f = tmp_path / name
    f.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return str(f)


def run(capsys, *args, code=None):
    """The command's output, parsed when --json is given, after checking how it exited."""
    if code is None:
        cli.main(["review", *args, "--as", WHO])
    else:
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, "--as", WHO])
        assert e.value.code == code
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in args else out


def test_a_batch_takes_every_step_with_the_usual_refusals(work, tmp_path, capsys):
    (tmp_path / "reading.md").write_text(READING, encoding="utf-8")
    (tmp_path / "cmp.md").write_text("Item by item, the same bound.", encoding="utf-8")
    s = rc.Session(work, rc.parse_reviewer(WHO))
    s.read(UNIT)
    s.read(SIGMA)

    # A unit not read is refused at the lock, as `review lock` refuses it; the others are locked.
    doc = run(capsys, "lock", "--manifest", manifest(tmp_path, "lock.json", [
        {"unit": UNIT, "reading_file": "reading.md"},
        {"unit": SIGMA, "reading": READING},
        {"unit": UNREAD, "reading": READING},
        {"unit": "link:nothing", "reading": READING},
        {"unit": UNIT, "reading": READING, "reading_file": "reading.md"},
        {"unit": UNIT, "verdict": "faithful"},
        "not an entry"]), "--json", code=2)
    assert doc["schema"] == "machinechecked/review-manifest@1" and doc["ok"] is False
    got = [(e["unit"], e["ok"] or e["error"]["kind"]) for e in doc["entries"]]
    assert got == [(UNIT, True), (SIGMA, True), (UNREAD, "order"), ("link:nothing", "unknown-unit"),
                   (UNIT, "invalid"), (UNIT, "invalid"), (None, "invalid")]
    assert "not both" in doc["entries"][4]["error"]["message"]
    assert "no field verdict" in doc["entries"][5]["error"]["message"]
    drafts = rc.Session(work, rc.parse_reviewer(WHO)).work["drafts"]
    assert drafts[UNIT]["reading"] == READING and drafts[SIGMA]["stage"] == "compare"
    assert UNREAD not in drafts

    # The verdict is still checked: a verdict that needs a detail is refused without one.
    for uid in (UNIT, SIGMA):
        rc.Session(work, rc.parse_reviewer(WHO)).show(uid)
    out = run(capsys, "decide", "--manifest", manifest(tmp_path, "decide.json", [
        {"unit": UNIT, "verdict": "faithful", "comparison_file": "cmp.md",
         "coverage": "full", "basis": "direct"},
        {"unit": SIGMA, "verdict": "broader", "comparison": "Weaker in n."},
        {"unit": UNREAD, "verdict": "faithful", "comparison": "x"}]), code=2)
    assert f"{UNIT}: verdict recorded" in out
    assert f"{SIGMA}: refused (invalid): verdict 'broader' needs --detail" in out
    assert f"{UNREAD}: refused (order)" in out and "1 of 3 entries taken" in out
    run(capsys, "decide", "--manifest", manifest(tmp_path, "decide2.json", [
        {"unit": SIGMA, "verdict": "faithful", "comparison": "The same bound, in σ too."}]))

    # The author's review must be shown before the report: one shown, one not.
    rc.Session(work, rc.parse_reviewer(WHO)).author(SIGMA)
    doc = run(capsys, "submit", "--manifest", manifest(tmp_path, "submit.json", [
        {"unit": UNIT, "disagreements": "none"},
        {"unit": SIGMA, "disagreements": "none"}]), "--json", code=2)
    assert [e["ok"] or e["error"]["kind"] for e in doc["entries"]] == ["order", True]
    assert doc["entries"][1]["verdict"] == "faithful"
    reports = rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]
    assert [r["unit"]["id"] for r in reports] == [SIGMA]

    # All taken: exit 0.
    rc.Session(work, rc.parse_reviewer(WHO)).author(UNIT)
    doc = run(capsys, "submit", "--manifest", manifest(tmp_path, "submit2.json", [
        {"unit": UNIT, "disagreements": "none"}]), "--json")
    assert doc["ok"] is True


def test_a_manifest_replaces_the_positional_arguments(work, tmp_path, capsys):
    f = manifest(tmp_path, "m.json", [{"unit": UNIT, "reading": READING}])
    doc = run(capsys, "lock", UNIT, "--manifest", f, "--json", code=2)
    assert doc["error"]["kind"] == "invalid" and "not both" in doc["error"]["message"]
    doc = run(capsys, "decide", UNIT, "--json", code=2)
    assert "needs VERDICT and COMPARISON, or --manifest FILE" in doc["error"]["message"]
    (tmp_path / "bad.json").write_text('{"unit": "x"}', encoding="utf-8")
    doc = run(capsys, "lock", "--manifest", str(tmp_path / "bad.json"), "--json", code=2)
    assert "JSON list" in doc["error"]["message"]
