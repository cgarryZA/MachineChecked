"""The latest release is the one the last build produced or reproduced (#353). A build that
reproduces an earlier evidence record names that record's release again, which keeps its
`created` time; every command that reads the latest release reads that one, and the
comparison with the release before is with the one the build before made. No command chooses a
release by its file's time (#354)."""

import json
import os

from conftest import build, edit, needs_lean, needs_tex
from test_promote import queue, report
from prooflens import changes as chg
from prooflens import cli, config as cfgmod, evidence as ev, pipeline, promote as pr, retire
from prooflens.export import export
from prooflens.pipeline import lean_inputs_digest, reassess
from prooflens.symbols import add as add_symbol

DEFS = "lean/Toy/Defs.lean"
EVEN, EVEN_EDITED = "∃ k, n = 2 * k", "∃ k, n = k + k"
LATER = 4_000_000_000  # a file time later than any release file's


def statuses(index):
    return {c["id"]: c["status"] for c in index["claims"]}


def name_release(out, name, eid, created):
    """A release file as an earlier version wrote it: no build recorded in the release log."""
    path = out / "releases" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"release": name, "evidence": eid, "created": created}))


def set_created(out, name, created):
    path = out / "releases" / f"{name}.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "created": created}))


def touch(path):
    os.utime(path, (LATER, LATER))


def test_the_release_log_names_the_latest_release(tmp_path):
    """Over release files and the release log alone (no Lean)."""
    out = tmp_path
    assert ev.latest(out) is None and ev.built(out) == []
    ev.record_release(out, "r-1", "e1")
    ev.record_release(out, "r-2", "e2")
    ev.record_release(out, "r-1", "e1")  # a build that reproduces the first record
    assert ev.built(out) == ["r-1", "r-2", "r-1"]
    assert ev.latest(out)["release"] == "r-1"
    assert chg.previous_release(out, "r-1") == "r-2"
    assert chg.previous_release(out, "r-2") == "r-1"
    # A build that changes nothing keeps the comparison with the build before it.
    ev.record_release(out, "r-1", "e1")
    assert chg.previous_release(out, "r-1") == "r-2"
    # Another name for the same evidence is the latest; the release before has other evidence.
    ev.record_release(out, "named", "e1")
    assert ev.latest(out)["release"] == "named"
    assert chg.previous_release(out, "named") == "r-2"
    # A release that is gone, and a line cut short, are passed over.
    (out / "releases" / "named.json").unlink()
    with (out / ev.RELEASE_LOG).open("a") as f:
        f.write('{"release": "r-2", "evid')
    assert ev.latest(out)["release"] == "r-1"
    # A release named again with other evidence does not inherit the builds of the old one.
    (out / "releases" / "r-1.json").unlink()
    ev.record_release(out, "r-1", "e3")
    assert ev.built(out) == ["r-2", "r-1"]
    assert chg.previous_release(out, "r-1") == "r-2"


def test_a_store_without_a_release_log_reads_the_release_made_last(tmp_path):
    """A store whose releases an earlier version wrote: the latest release is the one made last,
    and the comparison falls back to the order the releases were made in for what no recorded
    build says."""
    out = tmp_path
    name_release(out, "r-b", "eb", "2026-01-02T00:00:00+00:00")
    name_release(out, "r-a", "ea", "2026-01-01T00:00:00+00:00")
    assert ev.latest(out)["release"] == "r-b"
    assert chg.previous_release(out, "r-b") == "r-a"
    ev.record_release(out, "r-c", "ec")
    assert ev.latest(out)["release"] == "r-c"
    assert chg.previous_release(out, "r-c") == "r-b"
    ev.record_release(out, "r-a", "ea")  # reproduces the oldest release
    assert ev.latest(out)["release"] == "r-a"
    assert chg.previous_release(out, "r-a") == "r-c"
    assert chg.previous_release(out, "r-c") == "r-b"


@needs_lean
@needs_tex
def test_commands_read_the_release_a_reverted_build_reproduces(toy, monkeypatch, capsys):
    """The toy's edit and revert: build, change a definition and build, revert the change and
    build again. The third build reproduces the first evidence record and names the first
    release, though the second was made later; `changes`, `site`, `export`, `retire --markers`,
    `review promote`, `symbol add` and `reassess` read the first release, and the third build's
    site compares it with the second."""
    first, body1, cfg = build(toy)
    edit(toy / DEFS, EVEN, EVEN_EDITED)
    second, body2, _ = build(toy)
    assert statuses(second) != statuses(first) and body2["lean"] != body1["lean"]
    edit(toy / DEFS, EVEN_EDITED, EVEN)
    third, _, _ = build(toy)
    r1, r2 = first["release"], second["release"]
    assert (third["evidence"], third["release"]) == (first["evidence"], r1)
    assert [p.stem for p in ev.releases(cfg.out_dir)] == [r1, r2]
    assert ev.latest(cfg.out_dir)["release"] == r1

    # The third build's site has the comparison with the release the build before made.
    data = cfg.out_dir / "site" / "data"
    assert json.loads((data / "index.json").read_text())["changes"] == "data/changes.json"
    shown = json.loads((data / "changes.json").read_text())
    assert (shown["from"]["release"], shown["to"]["release"]) == (r2, r1)

    toml = str(toy / "machinechecked.toml")

    def run(*args):
        capsys.readouterr()
        cli.main(list(args))
        return capsys.readouterr().out

    doc = json.loads(run("changes", "-c", toml, "--json"))
    assert (doc["from"]["release"], doc["to"]["release"]) == (r2, r1)
    by = {c["claim"]: c for c in doc["claims"]}
    assert by["T:thm:even-add"]["status"]["to"]["status"] == \
        statuses(first)["T:thm:even-add"]

    assert f"site of release {r1} written" in run("site", "-c", toml)
    assert json.loads((data / "index.json").read_text())["release"] == r1

    out = toy.parent / "export"
    assert f"exported release {r1} to" in run("export", "-c", toml, "--out", str(out))
    exported = json.loads((out / "data" / "index.json").read_text())
    assert exported["release"] == r1 and statuses(exported) == statuses(first)
    assert json.loads((out / "data" / "changes.json").read_text())["from"]["release"] == r2

    seen = []
    monkeypatch.setattr(retire, "plan", lambda inventory, reviews, lean, markers:
                        seen.append(lean) or {"readings": [], "markers": [], "left": []})
    assert retire.main(["--config", toml, "--markers"]) == 0
    assert seen == [body1["lean"]]

    # A report made from the third build's queue is checked against the first release's
    # evidence, which is the Lean project as it now is.
    assert pr.latest_record(cfg)["id"] == first["evidence"]
    units = {u["name"]: u for u in queue(cfg)["units"]}
    (_, _, why), = pr.plan(cfg, [report(third, units["Toy.triangle"])])
    assert why == []
    add_symbol(cfg, "T:thm:even-add", "a", "Toy.PaperSpec.thm_even_add", "human:A-Referee",
               var="a")
    assert [ln["claim"] for ln in json.loads((toy / "symbols.json").read_text())["links"]] \
        == ["T:thm:even-add"]

    # Nothing changed since the third build: reassessing the first release reproduces it.
    res = reassess(cfg, log=lambda *a: None)
    assert res["release"] == ev.latest(cfg.out_dir)["release"] == r1
    assert statuses(res["index"]) == statuses(first)


def test_a_touched_older_release_file_changes_no_commands_release(toy):
    """Over stored records alone (no Lean): an older release whose file is the newest, as after
    copying or restoring `.machinechecked/`, changes neither the release order nor the latest
    release, so `review promote` checks reports against the newer release. So with the release
    log and without it, and with two releases recorded in the same second."""
    cfg = cfgmod.load(toy / "machinechecked.toml")
    out = cfg.out_dir
    claims = json.loads((toy / "claims.json").read_text())["claims"]

    def record(inputs):
        return ev.store(out, {
            "provenance": {"tool": {}, "project": {}, "papers": {}, "lean_inputs_sha256": inputs},
            "inventory": {"claims": claims}, "reviews": {"files": {}, "records": []}, "tex": {},
            "lean": {}, "assessment": {"claims": [], "findings": []}})
    older, newer = record("0" * 64), record(lean_inputs_digest(cfg))
    ev.record_release(out, "r-older", older)
    ev.record_release(out, "r-newer", newer)

    def reads_the_newer_release():
        touch(out / "releases" / "r-older.json")
        assert [p.stem for p in ev.releases(out)] == ["r-older", "r-newer"]
        assert ev.latest(out)["release"] == "r-newer"
        assert pr.latest_record(cfg)["id"] == newer
        assert pr.plan(cfg, []) == []  # not refused as made before a change of the Lean

    set_created(out, "r-older", "2026-01-01T00:00:00+00:00")
    set_created(out, "r-newer", "2026-01-01T00:00:01+00:00")
    reads_the_newer_release()
    set_created(out, "r-older", "2026-01-01T00:00:01+00:00")  # the same second
    reads_the_newer_release()
    (out / ev.RELEASE_LOG).unlink()  # a store an earlier version wrote
    set_created(out, "r-older", "2026-01-01T00:00:00+00:00")
    reads_the_newer_release()


@needs_lean
@needs_tex
def test_review_promote_and_symbol_add_read_the_latest_release_not_the_newest_file(toy):
    """Build, change a definition and build again, then touch the first release's file: `review
    promote`, `symbol add`, `export` and `reassess` all read the second release, with the
    release log and without it."""
    first, _, cfg = build(toy)
    edit(toy / DEFS, EVEN, EVEN_EDITED)
    second, body2, _ = build(toy)
    spec = "Toy.PaperSpec.thm_even_add"
    units = {u["name"]: u for u in queue(cfg)["units"]}
    for kept in (True, False):
        if not kept:
            (cfg.out_dir / ev.RELEASE_LOG).unlink()  # a store an earlier version wrote
        touch(cfg.out_dir / "releases" / f"{first['release']}.json")
        assert pr.latest_record(cfg)["id"] == second["evidence"]
        (_, _, why), = pr.plan(cfg, [report(second, units["Toy.triangle"])])
        assert why == []
        link = add_symbol(cfg, "T:thm:even-add", "a", spec, "human:A-Referee", var="a")
        assert link["pins"]["statement"] == body2["lean"]["specs"][spec]["fingerprint"]
        assert export(cfg, toy.parent / "export")["release"] == second["release"]
    res = reassess(cfg, log=lambda *a: None)  # nothing changed: it reproduces the second release
    assert res["release"] == ev.latest(cfg.out_dir)["release"] == second["release"]
    assert statuses(res["index"]) == statuses(second)


def test_a_reassessment_that_changes_nothing_reproduces_its_release(toy):
    """#385: a build, then two reassessments, make one release, which the release log records
    three times. A changed review file makes a new release, which names the record it was
    reassessed from; reassessing it again reproduces it. (A build without Lean or TeX, so
    that no Lean runs; the Lean tests above reassess real builds.)"""
    cfg = cfgmod.load(toy / "machinechecked.toml")

    def quiet(*_):
        pass
    first = pipeline.build(cfg, skip_lean=True, skip_tex=True, log=quiet)
    r1 = first["release"]
    for _ in range(2):
        res = reassess(cfg, log=quiet)
        assert res["release"] == r1 and statuses(res["index"]) == statuses(first["index"])
    assert [p.stem for p in ev.releases(cfg.out_dir)] == [r1]
    assert len(list((cfg.out_dir / "evidence").glob("*.json"))) == 1
    assert ev.built(cfg.out_dir) == [r1] * 3
    assert not (cfg.out_dir / "site" / "data" / "changes.json").exists()

    with (toy / "reviews" / "T.md").open("a") as f:
        f.write("\nA note after the last review.\n")
    second = reassess(cfg, log=quiet)
    r2 = second["release"]
    assert r2 != r1 and ev.latest(cfg.out_dir)["evidence"] != first["evidence"]
    body = ev.load(cfg.out_dir, ev.latest(cfg.out_dir)["evidence"])["body"]
    assert body["provenance"]["reassessed_from"] == first["evidence"]
    assert reassess(cfg, log=quiet)["release"] == r2
    assert [p.stem for p in ev.releases(cfg.out_dir)] == [r1, r2]
    assert ev.built(cfg.out_dir) == [r1] * 3 + [r2] * 2
    assert chg.previous_release(cfg.out_dir, r2) == r1
    shown = json.loads((cfg.out_dir / "site" / "data" / "changes.json").read_text())
    assert (shown["from"]["release"], shown["to"]["release"]) == (r1, r2)
