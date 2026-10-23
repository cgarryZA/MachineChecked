"""Stored evidence that is no longer on disk (#299), and pruning it (#324).

A release whose evidence file was deleted or pruned leaves the build working: there is no change
summary, and the reader says which release's evidence is gone. `machinechecked evidence prune`
deletes only what no release still needs. The first tests use synthetic evidence records and run
no Lean; the last one builds the toy paper."""

import datetime
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


def test_a_missing_latest_evidence_is_not_reused(toy):
    from prooflens import config as cfgmod
    cfg = cfgmod.load(toy / "machinechecked.toml")
    a, b = two_releases(cfg.out_dir)
    (cfg.out_dir / "evidence" / f"{b}.json").unlink()
    with pytest.raises(StaleEvidence, match="no stored Lean results to reuse: the evidence "
                       f"{b[:12]} is missing.*without `--reuse-lean`"):
        reusable_lean(cfg)


def test_prune_keeps_what_a_release_still_needs_and_deletes_the_rest(tmp_path):
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
    records = sorted(p.read_text() for p in (out / "releases").glob("*.json"))

    with pytest.raises(ev.EvidenceError, match="keep at least 2"):
        ev.prune(out, 1)
    dry = ev.prune(out, 2, dry_run=True)
    assert set(dry["deleted"]) == {e0, orphan} and dry["bytes"] > 0
    assert (out / "evidence" / f"{e0}.json").exists() and not (out / ev.PRUNED).exists()

    res = ev.prune(out, 2)
    assert res["deleted"] == {e0: [f"r-{e0[:12]}"], orphan: []}
    assert set(res["kept"]) == {e1, e2, e3, e4, fresh}
    assert res["kept"][e4] == ["the latest", "release v2 is named"]
    assert res["kept"][e3] == ["one of the newest 2"]
    assert "not yet named by a release" in res["kept"][fresh][0]
    assert res["kept"][e2] == ["release v1 is named"]
    assert res["kept"][e1] == [f"{e4[:12]} was reassessed from it"]
    assert not (out / "evidence" / f"{e0}.json").exists()
    assert not content_mod.path(out, e0).exists() and not content_mod.path(out, orphan).exists()
    assert content_mod.path(out, e1).exists()
    assert content_mod.load(out, e4) is not None
    # Release records are never changed; the pruned one says so.
    assert sorted(p.read_text() for p in (out / "releases").glob("*.json")) == records
    assert set(ev.pruned(out)) == {e0}
    assert ev.release_unavailable(out, f"r-{e0[:12]}").startswith(
        f"the evidence of release r-{e0[:12]} was pruned on ")
    assert ev.release_unavailable(out, "v1") is None
    # Pruning again deletes nothing more.
    assert ev.prune(out, 2)["deleted"] == {}


def test_after_pruning_the_next_build_still_compares_with_the_one_before(tmp_path):
    out = tmp_path / ".machinechecked"
    e = [store(out, n) for n in range(3)]
    for i, eid in enumerate(e):
        release(out, f"r-{eid[:12]}", eid, f"2026-01-0{i + 1}T00:00:00+00:00")
    ev.prune(out, 2)
    new = store(out, 3)
    release(out, f"r-{new[:12]}", new, "2026-01-04T00:00:00+00:00")
    assert chg.previous_release(out, f"r-{new[:12]}") == f"r-{e[2][:12]}"
    assert ev.release_unavailable(out, f"r-{e[2][:12]}") is None
    # The pruned release, compared on request, is named as pruned.
    notes = []
    assert release_changes(SimpleNamespace(out_dir=out), f"r-{e[1][:12]}", notes) is None
    assert "pruned on" in notes[0] and f"r-{e[0][:12]}" in notes[0]


def test_the_evidence_command_lists_and_prunes(toy, monkeypatch, capsys):
    monkeypatch.chdir(toy)
    out = toy / ".machinechecked"
    e = [store(out, n) for n in range(3)]
    for i, eid in enumerate(e):
        release(out, f"r-{eid[:12]}", eid, f"2026-01-0{i + 1}T00:00:00+00:00")
    cli.main(["evidence", "prune", "--dry-run"])
    text = capsys.readouterr().out
    assert f"would delete {e[0][:12]} (release r-{e[0][:12]})" in text
    assert "would delete 1 evidence file(s)" in text
    assert (out / "evidence" / f"{e[0]}.json").exists()
    cli.main(["evidence", "prune"])
    assert f"deleted {e[0][:12]}" in capsys.readouterr().out
    cli.main(["evidence", "list"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"r-{e[2][:12]}  evidence {e[2][:12]}") and "MB" in lines[0]
    assert lines[-1].startswith(f"r-{e[0][:12]}") and "was pruned on" in lines[-1]
    with pytest.raises(SystemExit) as x:
        cli.main(["evidence", "prune", "--keep", "1"])
    assert x.value.code == 2 and "keep at least 2" in capsys.readouterr().err


@needs_lean
@needs_tex
def test_a_build_after_an_earlier_evidence_file_was_deleted_completes(toy):
    index, body, cfg = build(toy)
    out = cfg.out_dir
    # A release after the first build whose evidence file is gone: the next build compares with it.
    time.sleep(1.1)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    release(out, "r-earlier", "0" * 64, now)
    time.sleep(1.1)
    # `--reuse-lean` reads the latest release's evidence, which is gone: it refuses and says so.
    with pytest.raises(StaleEvidence, match="evidence 000000000000 is missing"):
        build(toy, reuse_lean=True)
    index, body, cfg = build(toy, release="r-later")
    note = "No change summary: the evidence of release r-earlier is missing (its file was deleted)."
    assert index["changes_unavailable"] == note
    site = json.loads((out / "site" / "data" / "index.json").read_text())
    assert site["changes_unavailable"] == note and "changes" not in site
