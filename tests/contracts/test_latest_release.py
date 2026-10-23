"""The latest release is the one the last build produced or reproduced (#353). A build that
reproduces an earlier evidence record names that record's release again, which keeps its
`created` time; every command that reads the latest release reads that one, and the
comparison with the release before is with the one the build before made."""

import json

from conftest import build, edit, needs_lean, needs_tex
from test_promote import queue, report
from prooflens import changes as chg
from prooflens import cli, evidence as ev, promote as pr, retire
from prooflens.pipeline import reassess
from prooflens.symbols import add as add_symbol

DEFS = "lean/Toy/Defs.lean"
EVEN, EVEN_EDITED = "∃ k, n = 2 * k", "∃ k, n = k + k"


def statuses(index):
    return {c["id"]: c["status"] for c in index["claims"]}


def name_release(out, name, eid, created):
    """A release file as an earlier version wrote it: no build recorded in the release log."""
    path = out / "releases" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"release": name, "evidence": eid, "created": created}))


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

    res = reassess(cfg, log=lambda *a: None)
    last = ev.latest(cfg.out_dir)
    assert last["release"] == res["release"] not in (r1, r2)
    body = ev.load(cfg.out_dir, last["evidence"])["body"]
    assert body["provenance"]["reassessed_from"] == first["evidence"]
    assert statuses(res["index"]) == statuses(first)
