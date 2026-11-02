"""Review drafts brought in by `machinechecked workspace import` (#493): a workspace the working
directory already holds takes the file's newer drafts under the rules the reader's import uses
too (tests/fixtures/review/import-drafts.json, which web/tests/workfile.test.mjs checks against
the reader), says which drafts it did not apply and why, keeps both versions of each that
differed, and never unlocks a reading or makes what was seen count as blind.

The sites are the synthetic zero-configuration build of `test_compare.write_site`: one unit,
`link:thm:t0`. Nothing here builds Lean."""

import copy
import json
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from test_compare import write_site

UNIT = "link:thm:t0"
WHO = "human:Round-Trip-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
FIX = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "review"
                  / "import-drafts.json").read_text(encoding="utf-8"))


def named(v):
    if isinstance(v, str):
        return copy.deepcopy(FIX["named"][v])
    return {**copy.deepcopy(FIX["named"][v["$"]]), **{k: x for k, x in v.items() if k != "$"}}


def drafts(m: dict) -> dict:
    return {u: named(v) for u, v in m.items()}


@pytest.mark.parametrize("case", FIX["cases"], ids=lambda c: c["name"])
def test_drafts_merge_as_the_reader_merges_them(case):
    out = wsp.merge_drafts(drafts(case["here"]), drafts(case["theirs"]), case["reports"],
                           case["replace"])
    assert out["drafts"] == drafts(case["drafts"])
    assert out["applied"] == case["applied"]
    assert out["not_applied"] == case["not_applied"]
    assert [(k["unit"], k["current"], k["proposed"]) for k in out["kept"]] == [
        (k["unit"], named(k["current"]), named(k["proposed"])) for k in case["kept"]]


@pytest.fixture
def machines(tmp_path):
    """Two working directories with the same build: where a workspace is exported, and where it
    is imported."""
    return [write_site(tmp_path / name).parent.parent for name in ("here", "there")]


def session(work, wid=None):
    return rc.Session(work, rc.parse_reviewer(WHO), wid)


def exported(work, wid) -> dict:
    return json.loads(json.dumps(wsp.export(wsp.find(work, wid))))


def import_cli(work, monkeypatch, capsys, path, *flags):
    """`machinechecked workspace import FILE` in a project whose last build is `work`: its JSON
    answer and exit status."""
    root = work.parent
    (root / "lakefile.toml").write_text('name = "syn"\n')
    if not (root / ".machinechecked").exists():
        (root / ".machinechecked").symlink_to(work, target_is_directory=True)
    monkeypatch.chdir(root)
    code = 0
    try:
        cli.main(["workspace", "import", str(path), "--as", WHO, *flags])
    except SystemExit as e:
        code = e.code
    return json.loads(capsys.readouterr().out), code


def test_a_newer_draft_comes_across_in_a_second_import(machines, tmp_path, monkeypatch, capsys):
    """#493: a workspace exported, imported, taken on elsewhere and imported again: the second
    import takes the newer draft, says so, and the review continues from it here."""
    here, there = machines
    s = session(there)
    s.read(UNIT)
    s.edit(UNIT, "read", {"reading": READING[:30]})
    wid = wsp.read(s.path)["id"]
    f1 = tmp_path / "first.json"
    f1.write_text(json.dumps(exported(there, wid)))
    out, code = import_cli(here, monkeypatch, capsys, f1)
    assert code == 0 and out["drafts"] == {"applied": [{"unit": UNIT, "how": "added"}],
                                           "not_applied": []}
    # Taken on where it began: the reading locked and the Lean shown.
    s = session(there, wid)
    s.lock(UNIT, READING)
    s.show(UNIT)
    f2 = tmp_path / "second.json"
    f2.write_text(json.dumps(exported(there, wid)))
    dry, code = import_cli(here, monkeypatch, capsys, f2, "--dry-run")
    assert code == 0 and dry["dry_run"] and dry["drafts"]["applied"] == [
        {"unit": UNIT, "how": "advanced from step 1 to step 2"}]
    assert session(here, wid).work["drafts"][UNIT]["stage"] == "read", "a dry run saves nothing"
    out, code = import_cli(here, monkeypatch, capsys, f2)
    assert code == 0 and out["drafts"] == {
        "applied": [{"unit": UNIT, "how": "advanced from step 1 to step 2"}], "not_applied": []}
    mine = session(here, wid)
    assert mine.work["drafts"][UNIT] == exported(there, wid)["review"]["drafts"][UNIT]
    # The review goes on here from the imported draft, through the protocol's checks.
    rc_refused(mine.lock, UNIT, READING + " Again.")
    mine.decide(UNIT, "faithful", "Same statement.")
    mine.author(UNIT)
    r = mine.submit(UNIT, "none")
    assert r["reading"]["text"] == READING


def rc_refused(fn, *args):
    with pytest.raises(rc.ReviewError) as e:
        fn(*args)
    assert e.value.kind == "order", e.value
    return e.value


def test_each_draft_not_applied_is_named_with_why_and_both_versions_kept(machines, tmp_path,
                                                                          monkeypatch, capsys):
    """A draft that the import does not apply is listed with why, the command exits 1, and the
    workspace keeps both versions under `conflicts`; asked, what was typed at the same step is
    replaced, and the version here is kept."""
    here, _ = machines
    s = session(here)
    s.read(UNIT)
    s.lock(UNIT, READING)
    s.edit(UNIT, "compare", {"comparison": "The bound agrees."})
    wid = wsp.read(s.path)["id"]
    base = exported(here, wid)
    mine = base["review"]["drafts"][UNIT]

    def attempt(draft, *flags):
        f = tmp_path / "file.json"
        f.write_text(json.dumps({**base, "review": {**base["review"], "drafts": {UNIT: draft}}}))
        return import_cli(here, monkeypatch, capsys, f, *flags)

    # An unlocked reading never replaces the locked one, even asked to.
    out, code = attempt({"stage": "read", "reading": "Another reading, typed elsewhere."},
                        "--replace-drafts")
    assert code == 1 and out["drafts"]["not_applied"] == [
        {"unit": UNIT, "kind": "older",
         "why": "older than the draft here (step 1 in the file, step 2 here)"}]
    assert session(here, wid).work["drafts"][UNIT] == mine
    rc_refused(session(here, wid).lock, UNIT, READING)
    # A reading locked differently is kept as here.
    out, code = attempt({**mine, "reading": READING + " Read differently.",
                         "locked_at": "2026-01-03T00:00:00Z"}, "--replace-drafts")
    assert code == 1 and out["drafts"]["not_applied"][0]["why"] == (
        "its reading was locked differently here; kept as here")
    assert session(here, wid).work["drafts"][UNIT] == mine
    # What was typed at the same step: kept as here, unless asked.
    typed = {**mine, "comparison": "The bound agrees, and the constant too."}
    out, code = attempt(typed)
    assert code == 1 and out["drafts"]["not_applied"] == [
        {"unit": UNIT, "kind": "typed",
         "why": "differs from the draft here only in what was typed at step 2; kept as here"}]
    assert out["conflicts"][-1]["id"] == f"draft {UNIT}"
    ws = wsp.read(wsp.find(here, wid))
    assert ws["review"]["drafts"][UNIT] == mine
    assert (ws["conflicts"][-1]["current"], ws["conflicts"][-1]["proposed"]) == (mine, typed)
    out, code = attempt(typed, "--replace-drafts")
    assert code == 0 and out["drafts"]["applied"] == [
        {"unit": UNIT, "how": "replaced what was typed at step 2"}]
    ws = wsp.read(wsp.find(here, wid))
    assert ws["review"]["drafts"][UNIT] == typed
    assert ws["conflicts"][-1]["how"] == "import, replaced" and ws["conflicts"][-1]["proposed"] == mine
    # A verdict recorded differently is kept as here.
    s = session(here, wid)
    s.decide(UNIT, "faithful", "Same statement.")
    decided = exported(here, wid)["review"]["drafts"][UNIT]
    base = exported(here, wid)
    out, code = attempt({**decided, "verdict": "broader", "detail": "Take m = n.",
                         "decided_at": "2026-01-03T00:00:00Z"})
    assert code == 1 and out["drafts"]["not_applied"][0]["why"] == (
        "its verdict was recorded differently here; kept as here")
    assert session(here, wid).work["drafts"][UNIT]["verdict"] == "faithful"
    # A draft that a report here was made from is not added again.
    s = session(here, wid)
    s.author(UNIT)
    s.submit(UNIT, "none")
    out, code = attempt(decided)
    assert code == 1 and out["drafts"]["not_applied"] == [
        {"unit": UNIT, "kind": "submitted", "why": "submitted here as a report"}]
    assert session(here, wid).work["drafts"] == {}


def test_an_import_does_not_make_what_was_seen_count_as_blind(machines, tmp_path):
    """Exposure recorded here before a reading the file's draft locked elsewhere is listed in
    the report made here from that draft."""
    here, there = machines
    s = session(here)
    s.expose(["S:thm:t0"], "the claim's page in the reader", ("Lean",))
    wid = wsp.read(s.path)["id"]
    ws = wsp.read(wsp.find(here, wid))
    ws["exposure"][0]["at"] = "2026-01-01T00:00:00Z"
    wsp._write(wsp.find(here, wid), ws)
    # The same workspace, taken on elsewhere without that record.
    data = exported(here, wid)
    data["exposure"] = []
    (there / wsp.DIR).mkdir(parents=True)
    (there / wsp.DIR / f"{wid}.json").write_text(json.dumps(data))
    t = session(there, wid)
    t.read(UNIT)
    t.lock(UNIT, READING)
    assert t.work["drafts"][UNIT]["revealed_by"] == []
    res = wsp.import_(here, exported(there, wid), by=WHO)
    assert res["drafts"]["applied"] == [{"unit": UNIT, "how": "added"}]
    mine = session(here, wid)
    mine.decide(UNIT, "faithful", "Same statement.")
    mine.author(UNIT)
    r = mine.submit(UNIT, "none")
    assert r["reading"]["revealed_by"] == [
        {"unit": f"workspace {wid} (the claim's page in the reader)", "what": "Lean"}]
