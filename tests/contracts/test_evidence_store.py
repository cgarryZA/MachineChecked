"""Stored evidence that is no longer on disk (#299), and pruning it (#324).

A release whose evidence file was deleted or pruned leaves the build working: there is no change
summary, and the build and the reader say which release's evidence is gone.
`machinechecked evidence prune` deletes only what no release still needs, together with the
release records that name it. The first tests use synthetic evidence records and run no Lean;
the last one builds the toy paper."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import changes as chg
from prooflens import cli
from prooflens import content as content_mod
from prooflens import evidence as ev
from prooflens import pipeline as pl
from prooflens import workspace as wsp
from prooflens.pipeline import StaleEvidence, release_changes, reusable_lean


def release(out, name, eid, created):
    path = out / "releases" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"release": name, "evidence": eid, "created": created}))


def store(out, n, **provenance):
    return ev.store(out, {"n": n, "provenance": provenance})


def content(out, eid):
    path = content_mod.path(out, eid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": content_mod.SCHEMA}))


def two_releases(out):
    a, b = store(out, 1), store(out, 2)
    release(out, f"r-{a[:12]}", a, "2026-01-01T00:00:00+00:00")
    release(out, f"r-{b[:12]}", b, "2026-01-02T00:00:00+00:00")
    return a, b


def built_in_turn(out, n):
    """`n` releases, each built once, in order."""
    e = [store(out, i) for i in range(n)]
    for i, eid in enumerate(e):
        release(out, f"r-{eid[:12]}", eid, f"2026-01-0{i + 1}T00:00:00+00:00")
        ev.record_release(out, f"r-{eid[:12]}", eid)
    return e


def records(out):
    return sorted(p.name for p in (out / "releases").glob("*.json"))


def test_a_missing_earlier_evidence_gives_no_change_summary_and_says_why(tmp_path):
    out = tmp_path / ".machinechecked"
    a, b = two_releases(out)
    (out / "evidence" / f"{a}.json").unlink()
    notes = []
    assert release_changes(SimpleNamespace(out_dir=out), f"r-{b[:12]}", notes) is None
    assert notes == [f"No change summary: the evidence of release r-{a[:12]} is missing (its "
                     "file was deleted)."]
    with pytest.raises(ev.EvidenceMissing, match=f"the evidence {a[:12]} is missing"):
        ev.load(out, a)
    # `changes` names the release whose evidence is gone instead of failing on a missing file.
    with pytest.raises(chg.ChangesError,
                       match=f"no comparison: the evidence of release r-{a[:12]}"):
        chg.between(out)


def test_reuse_skips_a_release_whose_evidence_is_missing(toy):
    from prooflens import config as cfgmod
    cfg = cfgmod.load(toy / "machinechecked.toml")
    out = cfg.out_dir
    prov = {"lean_inputs_sha256": pl.lean_inputs_digest(cfg), "probe_sha256": pl.probe_digest(),
            "probe_settings_sha256": pl.probe_settings_digest(cfg),
            "lean_records_engine": pl.records_engine()}
    lean = {"specs": {}, "defs": {}, "proofs": {}}
    a = ev.store(out, {"lean": lean, "provenance": prov})
    b = ev.store(out, {"lean": lean, "provenance": {**prov, "n": 2}})
    release(out, "r-a", a, "2026-01-01T00:00:00+00:00")
    release(out, "r-b", b, "2026-01-02T00:00:00+00:00")
    (out / "evidence" / f"{b}.json").unlink()
    # The latest release's evidence is gone: the newest stored release that matches is reused.
    assert reusable_lean(cfg, []) == ("r-a", lean)
    (out / "evidence" / f"{a}.json").unlink()
    with pytest.raises(StaleEvidence, match="no stored Lean results to reuse.*without "
                       "`--reuse-lean`"):
        reusable_lean(cfg, [])


def test_prune_deletes_old_evidence_with_its_releases_and_keeps_what_is_still_needed(tmp_path):
    out = tmp_path / ".machinechecked"
    e0, e1, e2, e3 = (store(out, n) for n in range(4))
    e4 = store(out, 4, reassessed_from=e1)  # shows the content kept with e1
    release(out, f"r-{e0[:12]}", e0, "2026-01-01T00:00:00+00:00")
    release(out, f"r-{e1[:12]}", e1, "2026-01-02T00:00:00+00:00")
    release(out, "v1", e2, "2026-01-03T00:00:00+00:00")  # a release given its own name
    release(out, f"r-{e3[:12]}", e3, "2026-01-04T00:00:00+00:00")
    release(out, f"r-{e4[:12]}", e4, "2026-01-05T00:00:00+00:00")
    release(out, "v2", e4, "2026-01-06T00:00:00+00:00")  # the same evidence again, named
    for eid in (e0, e1):
        content(out, eid)
    orphan = "9" * 64
    content(out, orphan)  # content whose evidence was deleted by hand, two hours ago
    hours_ago = time.time() - 7200
    os.utime(content_mod.path(out, orphan), (hours_ago, hours_ago))
    fresh = store(out, 5)  # a build's evidence, not yet named by a release
    before = records(out)

    with pytest.raises(ev.EvidenceError, match="keep at least 2"):
        ev.prune(out, 1)
    dry = ev.prune(out, 2, dry_run=True)
    assert set(dry["deleted"]) == {e0, orphan} and dry["bytes"] > 0
    assert (out / "evidence" / f"{e0}.json").exists() and not (out / ev.PRUNED).exists()
    assert records(out) == before

    res = ev.prune(out, 2)
    assert res["deleted"] == {e0: [f"r-{e0[:12]}"], orphan: []}
    assert set(res["kept"]) == {e1, e2, e3, e4, fresh}
    assert res["kept"][e4] == ["the latest", "release v2 is named"]
    assert res["kept"][e3] == ["the one the latest is compared with"]
    assert "not yet named by a release" in res["kept"][fresh][0]
    assert res["kept"][e2] == ["release v1 is named"]
    assert res["kept"][e1] == [f"{e4[:12]} was reassessed from it"]
    assert not (out / "evidence" / f"{e0}.json").exists()
    assert not content_mod.path(out, e0).exists() and not content_mod.path(out, orphan).exists()
    assert content_mod.path(out, e1).exists()
    assert content_mod.load(out, e4) is not None
    # The pruned evidence's release record goes with it; every other record stays as it was.
    assert records(out) == [n for n in before if n != f"r-{e0[:12]}.json"]
    assert set(ev.pruned(out)) == {e0}
    assert ev.pruned_releases(out)[f"r-{e0[:12]}"]["evidence"] == e0
    assert ev.release_unavailable(out, f"r-{e0[:12]}").startswith(
        f"the evidence of release r-{e0[:12]} was pruned on ")
    assert ev.release_unavailable(out, "v1") is None
    # A pruned release's name keeps its evidence.
    with pytest.raises(ev.EvidenceError, match="once given, keeps its evidence"):
        ev.record_release(out, f"r-{e0[:12]}", e1)
    # Pruning again deletes nothing more.
    assert ev.prune(out, 2)["deleted"] == {}


def test_prune_follows_the_builds_and_keeps_what_a_version_map_compares(tmp_path):
    out = tmp_path / ".machinechecked"
    e = built_in_turn(out, 4)
    # The last build reproduced the first release's evidence: that release is the latest.
    ev.record_release(out, f"r-{e[0][:12]}", e[0])
    ws = wsp.new({"id": "someone"}, "independent", wid="w")
    ws["version_maps"] = [{"from": {"release": f"r-{e[1][:12]}"},
                           "to": {"release": f"r-{e[0][:12]}"}}]
    wsp.store(out).mkdir()
    (wsp.store(out) / "w.json").write_text(json.dumps(ws))
    res = ev.prune(out, 2, dry_run=True)
    assert res["kept"][e[0]][0] == "the latest"
    assert res["kept"][e[3]] == ["the one the latest is compared with"]
    assert res["kept"][e[1]] == ["a version map of workspace w compares it"]
    assert set(res["deleted"]) == {e[2]}


def test_after_pruning_a_comparison_with_a_pruned_release_says_so(tmp_path):
    out = tmp_path / ".machinechecked"
    e = built_in_turn(out, 3)
    ev.prune(out, 2)
    assert not (out / "releases" / f"r-{e[0][:12]}.json").exists()
    new = store(out, 3)
    ev.record_release(out, f"r-{new[:12]}", new)
    # The next build compares with the latest, which pruning keeps.
    assert chg.previous_release(out, f"r-{new[:12]}") == f"r-{e[2][:12]}"
    assert ev.release_unavailable(out, f"r-{e[2][:12]}") is None
    # The release before the oldest one kept was pruned: no comparison goes past it to an older
    # release, and the reason names it.
    notes = []
    assert release_changes(SimpleNamespace(out_dir=out), f"r-{e[1][:12]}", notes) is None
    assert notes == [f"No change summary: the evidence of release r-{e[0][:12]} was pruned on "
                     f"{ev.pruned(out)[e[0]]['pruned'][:10]}."]
    with pytest.raises(chg.ChangesError, match=f"no comparison: the evidence of release "
                       f"r-{e[0][:12]} was pruned on"):
        chg.between(out, f"r-{e[0][:12]}", f"r-{new[:12]}")
    with pytest.raises(ev.EvidenceMissing, match=f"no release r-{e[0][:12]}: the evidence of "
                       "release .* was pruned on"):
        ev.release(out, f"r-{e[0][:12]}")
    with pytest.raises(ev.EvidenceError, match="no release nowhere"):
        ev.release(out, "nowhere")
    # The same evidence stored again by a build that named no release, and pruned again: the
    # release pruned the first time is still known as pruned.
    assert store(out, 0) == e[0]
    hours_ago = time.time() - 7200
    os.utime(out / "evidence" / f"{e[0]}.json", (hours_ago, hours_ago))
    assert ev.prune(out, 2)["deleted"][e[0]] == []
    assert ev.pruned_releases(out)[f"r-{e[0][:12]}"]["evidence"] == e[0]


def test_prune_removes_a_release_whose_evidence_was_deleted_by_hand(tmp_path):
    out = tmp_path / ".machinechecked"
    e = built_in_turn(out, 4)
    (out / "evidence" / f"{e[0]}.json").unlink()
    res = ev.prune(out, 2)
    assert res["deleted"] == {e[0]: [f"r-{e[0][:12]}"], e[1]: [f"r-{e[1][:12]}"]}
    assert ev.pruned(out)[e[0]]["missing"] is True and "missing" not in ev.pruned(out)[e[1]]
    assert ev.release_unavailable(out, f"r-{e[0][:12]}").startswith(
        f"the evidence of release r-{e[0][:12]} is missing (its file was deleted), and its "
        "record was pruned on ")


def test_the_evidence_command_lists_and_prunes(toy, monkeypatch, capsys):
    monkeypatch.chdir(toy)
    out = toy / ".machinechecked"
    e = [store(out, n) for n in range(3)]
    for i, eid in enumerate(e):
        release(out, f"r-{eid[:12]}", eid, f"2026-01-0{i + 1}T00:00:00+00:00")
    cli.main(["evidence", "prune", "--dry-run"])
    text = capsys.readouterr().out
    assert f"would delete {e[0][:12]} and release r-{e[0][:12]}" in text
    assert "would delete 1 evidence record(s) and 1 release(s)" in text
    assert (out / "evidence" / f"{e[0]}.json").exists()
    cli.main(["evidence", "prune"])
    assert f"deleted {e[0][:12]} and release r-{e[0][:12]}" in capsys.readouterr().out
    cli.main(["evidence", "list"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"r-{e[2][:12]}  evidence {e[2][:12]}")
    assert lines[0].endswith("MB  (latest)")
    assert lines[2].startswith(f"r-{e[0][:12]}") and "evidence pruned on" in lines[2]
    assert lines[3].startswith("2 evidence record(s) on disk")
    with pytest.raises(SystemExit) as x:
        cli.main(["evidence", "prune", "--keep", "1"])
    assert x.value.code == 2 and "keep at least 2" in capsys.readouterr().err


@needs_lean
@needs_tex
def test_a_build_completes_when_the_earlier_evidence_was_deleted_and_after_pruning(
        toy, monkeypatch, capsys):
    # #299: build once, delete that build's evidence to free disk, change the Lean and build
    # again. The build completes, says why there is no change summary, and the reader says it.
    index, body, cfg = build(toy)
    out = cfg.out_dir
    first = ev.latest(out)
    (out / "evidence" / f"{first['evidence']}.json").unlink()
    lean = toy / "lean" / "Toy.lean"
    lean.write_text(lean.read_text() + "\n-- a change\n")
    monkeypatch.chdir(toy)
    cli.main(["build"])
    note = (f"No change summary: the evidence of release {first['release']} is missing (its "
            "file was deleted).")
    assert f"warning: {note}" in capsys.readouterr().out
    site = json.loads((out / "site" / "data" / "index.json").read_text())
    assert site["changes_unavailable"] == note and "changes" not in site
    second = ev.latest(out)
    # #324: pruning keeps the latest and the one it is compared with; the next build compares
    # with the latest.
    cli.main(["evidence", "prune", "--keep", "2"])
    capsys.readouterr()
    lean.write_text(lean.read_text() + "\n-- another change\n")
    index, body, cfg = build(toy)
    assert "changes_unavailable" not in index
    site = json.loads((out / "site" / "data" / "index.json").read_text())
    assert site["changes"] == "data/changes.json"
    changes = json.loads((out / "site" / "data" / "changes.json").read_text())
    assert changes["from"]["release"] == second["release"]
    # Pruning again removes the first release, whose evidence was already gone.
    res = ev.prune(out, 2)
    assert list(res["deleted"]) == [first["evidence"]]
    assert not (out / "releases" / f"{first['release']}.json").exists()
    assert ev.latest(out)["release"] == index["release"]
