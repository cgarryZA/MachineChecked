"""A review of a project the reviewer did not build (#743): its author packs the last build's
site data as a review snapshot (`review pack`), and the reviewer takes every step against it
(`review … --snapshot`) with no configuration, no Lean project and no Lean, in a working
directory of their own. A snapshot holds only what the review steps read, nothing of the author's
workspaces; an incomplete or inconsistent one is refused before any step; and the reports it gives
record what they were reviewed against and pass `review promote` by its usual rules.

The fast tests use the synthetic site of `test_compare.write_site`; the last one builds the toy
example and runs the steps in a subprocess whose PATH holds no Lean, Lake or TeX."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT, build, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import review_snapshot as rs
from prooflens import workspace as wsp
from test_compare import MARKER, write_site

UNIT = "link:thm:t0"
WHO = ["--as", "human:Snapshot-Referee"]
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
# Text of the synthetic Lean: its statement and the definition it uses.
LEAN_TEXT = ("Syn.Jet 0 n", "fun m n => m ≤ n")
AUTHOR_READING = "AUTHOR-DRAFT: the author's own reading of this unit, never packed."


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def site(tmp_path):
    """The synthetic site, with everything else a build writes beside the files a review reads,
    and an author's workspace with a draft, a finding and a kept version map."""
    data = write_site(tmp_path)
    work = data.parent.parent
    (data / "search.json").write_text("{}")
    (data / "retrieval.json").write_text('{"docs": []}')
    (data / "numbering.json").write_text('{"references": [], "pattern": null}')
    (data / "changes.json").write_text("{}")
    (data / "uses.json").write_text("{}")
    (data / "papers").mkdir()
    (data / "papers" / "S.pdf").write_bytes(b"%PDF-1.4 synthetic")
    (data / "expansions").mkdir()
    (data / "expansions" / f"{'a' * 24}.json").write_text('{"equations": []}')
    index = json.loads((data / "index.json").read_text())
    index["semantic"] = {"papers": {"S": {"finding_currency": {"current": 1}}}}
    for c in index["claims"]:
        c["semantic"] = {"finding_currency": {"current": 1}}
    (data / "index.json").write_text(json.dumps(index))
    ch = json.loads((data / "claims" / "S_thm_t3.json").read_text())
    ch["references"] = [{"reference": "Theorem 9", "status": "absent",
                         "current": {"reference": "Theorem 3", "source": {
                             "kept": [{"workspace": "ws-author1", "kept_by": "human:Author"}]}}},
                        {"reference": "Theorem 8", "status": "absent"}]
    (data / "claims" / "S_thm_t3.json").write_text(json.dumps(ch))
    author = rc.Session(work, rc.parse_reviewer("human:Author"))
    author.read(UNIT)
    author.lock(UNIT, AUTHOR_READING)
    return data


def files_of(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def step(capsys, *args, rc_=0):
    """A review step through the command line, as a reviewer runs it: its output."""
    if rc_:
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, *WHO])
        assert e.value.code == rc_
    else:
        cli.main(["review", *args, *WHO])
    return capsys.readouterr()


def test_a_snapshot_holds_what_the_review_reads_and_nothing_of_the_workspaces(site, tmp_path):
    work = site.parent.parent
    author_ws = [ws["id"] for _, ws in wsp.list_all(work)]
    assert author_ws
    m = rs.pack(site, tmp_path / "snap", tool="test")
    got = files_of(tmp_path / "snap")
    claims = {f"data/claims/S_thm_t{i}.json" for i in range(8)}
    decls = {f"data/{p.relative_to(site).as_posix()}" for p in (site / "decls").iterdir()}
    assert got == {rs.MANIFEST, "data/index.json", "data/review-queue.json", "data/uses.json",
                   f"data/expansions/{'a' * 24}.json", *claims, *decls}
    manifest = json.loads((tmp_path / "snap" / rs.MANIFEST).read_text())
    assert manifest["schema"] == "prooflens/review-snapshot@1"
    assert manifest["files"] == {f: sha(tmp_path / "snap" / f) for f in got - {rs.MANIFEST}}
    assert manifest["sources"] == {"release": "v-synthetic",
                                   "project": {"name": "syn", "commit": "c" * 40},
                                   "papers": [{"id": "S", "title": "Synthetic",
                                               "revision": "c" * 40}]}
    assert manifest["pdf"] is False and manifest["tool"]["version"] == "test"
    assert manifest["contains"]["author_reviews"] == 1 and manifest["contains"]["claims"] == 8
    assert m["digest"] == sha(tmp_path / "snap" / rs.MANIFEST)
    # What the site data holds from the author's workspaces is left out, and said to be.
    index = json.loads((tmp_path / "snap" / "data" / "index.json").read_text())
    assert "semantic" not in index and not any("semantic" in c for c in index["claims"])
    refs = json.loads((tmp_path / "snap" / "data" / "claims" / "S_thm_t3.json").read_text())[
        "references"]
    assert refs == [{"reference": "Theorem 9", "status": "absent"},
                    {"reference": "Theorem 8", "status": "absent"}]
    assert len(manifest["left_out"]) == 2
    text = "\n".join((tmp_path / "snap" / f).read_text(encoding="utf-8") for f in got)
    for x in [*author_ws, AUTHOR_READING, "ws-author1", "review-work"]:
        assert x not in text, x
    said = rs.summary_text(m)
    assert "8 claim(s)" in said and "1 review(s) by the author" in said and "no PDF" in said
    # The PDF only when asked; a directory written before is replaced.
    rs.pack(site, tmp_path / "snap", pdf=True)
    assert files_of(tmp_path / "snap") == got | {"data/papers/S.pdf"}
    with pytest.raises(rs.SnapshotError, match="neither an empty directory"):
        rs.pack(site, work)  # a directory that is not a snapshot
    with pytest.raises(rs.SnapshotError, match="inside the site data"):
        rs.pack(site, site / "snap.zip")


def test_a_reviewer_without_a_build_takes_every_step_against_the_snapshot(site, tmp_path,
                                                                          monkeypatch, capsys):
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    m = rs.pack(site, handoff / "review-snapshot.zip")
    reviewer = tmp_path / "reviewer"
    reviewer.mkdir()
    monkeypatch.chdir(reviewer)
    for name, text in {"reading.md": READING, "comparison.md": "The same bound, for every n.",
                       "none.md": "none"}.items():
        (reviewer / name).write_text(text)
    snap = ["--snapshot", str(handoff / "review-snapshot.zip")]
    assert step(capsys, "next", *snap).out.startswith(UNIT)
    # Step 1 is the paper alone: no Lean, no review by the author.
    read = step(capsys, "read", UNIT, *snap).out
    assert "Statement 0." in read
    for x in [*LEAN_TEXT, MARKER]:
        assert x not in read, x
    assert "lock your reading first" in step(capsys, "show", UNIT, *snap, rc_=2).err
    step(capsys, "lock", UNIT, "reading.md", *snap)
    shown = step(capsys, "show", UNIT, *snap).out
    assert LEAN_TEXT[0] in shown and MARKER not in shown
    step(capsys, "decide", UNIT, "faithful", "comparison.md", "--coverage", "full",
         "--basis", "direct", *snap)
    assert MARKER in step(capsys, "author", UNIT, *snap).out
    step(capsys, "submit", UNIT, "none.md", *snap)
    assert "review snapshot " + m["digest"] in step(capsys, "status", *snap).out
    step(capsys, "export", "--out", "reports.json", *snap)
    # The work is the reviewer's, in their working directory; nothing is written beside the zip.
    assert sorted(p.name for p in handoff.iterdir()) == ["review-snapshot.zip"]
    work = reviewer / rs.REVIEW_DIR
    assert (work / ".gitignore").read_text().strip().endswith("*")
    (ws,) = [w for _, w in wsp.list_all(work)]
    assert ws["reviewer"]["id"] == "human:Snapshot-Referee" and ws["exposure"] == []
    (r,) = pr.load_reports([reviewer / "reports.json"])
    assert r["reading"]["revealed_by"] == [] and r["reading"]["text"] == READING
    assert r["evidence"] == {"kind": "snapshot", "manifest_sha256": m["digest"],
                             "schema": rs.SCHEMA, "created_at": m["created_at"],
                             "tool": m["tool"], "release": "v-synthetic",
                             "evidence_id": "e" * 64, "project": m["sources"]["project"],
                             "papers": m["sources"]["papers"]}
    assert r["pins"]["release"] == "v-synthetic"
    # The maintainer's plan and text block say what it was reviewed against.
    said = pr.evidence_text(r)
    assert said == ("reviewed against supplied evidence: the review snapshot "
                    f"{m['digest']} of release v-synthetic")
    assert pr.report_text(r).split("\n")[2] == f"Evidence: {said}"
    assert pr.evidence_text({k: v for k, v in r.items() if k != "evidence"}) is None
    assert "Evidence:" not in pr.report_text({k: v for k, v in r.items() if k != "evidence"})
    # A directory snapshot reads the same; the work stays in the reviewer's directory.
    rs.pack(site, tmp_path / "snapdir")
    out = step(capsys, "status", "--json", "--snapshot", str(tmp_path / "snapdir"),
               "--review-dir", str(tmp_path / "other-work")).out
    assert json.loads(out)["open"] == [UNIT]
    assert rs.MANIFEST in files_of(tmp_path / "snapdir") and not any(
        "review-work" in f for f in files_of(tmp_path / "snapdir"))


def refusal(capsys, *args) -> dict:
    out = step(capsys, *args, "--json", rc_=2).out
    d = json.loads(out)
    assert d["schema"] == "machinechecked/review-error@1" and not d["ok"]
    return d["error"]


def test_an_incomplete_or_inconsistent_snapshot_is_refused_before_any_step(site, tmp_path,
                                                                           monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    good = tmp_path / "good"
    rs.pack(site, good)

    def copy(name):
        dst = tmp_path / name
        shutil.copytree(good, dst)
        return dst

    changed = copy("changed")
    (changed / "data" / "claims" / "S_thm_t3.json").write_text("{}")
    e = refusal(capsys, "status", "--snapshot", str(changed))
    assert e["kind"] == "snapshot"
    assert e["message"].startswith(f"incomplete or inconsistent review snapshot {changed}: "
                                   "data/claims/S_thm_t3.json differs from the manifest")
    missing = copy("missing")
    (missing / "data" / "review-queue.json").unlink()
    with pytest.raises(rs.SnapshotError, match="data/review-queue.json is missing"):
        rs.open_snapshot(missing, tmp_path / "w")
    extra = copy("extra")
    (extra / "data" / "decls" / "more.json").write_text("{}")
    with pytest.raises(rs.SnapshotError, match="data/decls/more.json is not in the manifest"):
        rs.open_snapshot(extra, tmp_path / "w")
    bare = copy("bare")
    (bare / rs.MANIFEST).unlink()
    e = refusal(capsys, "read", UNIT, "--snapshot", str(bare))
    assert e["kind"] == "snapshot" and "holds no snapshot manifest" in e["message"]
    other = copy("other")
    m = json.loads((other / rs.MANIFEST).read_text())
    (other / rs.MANIFEST).write_text(json.dumps({**m, "schema": "prooflens/review-snapshot@9"}))
    with pytest.raises(rs.SnapshotError, match="not a review snapshot this version reads"):
        rs.open_snapshot(other, tmp_path / "w")
    # A manifest rewritten for another index is caught too: the index is not the build named.
    moved = copy("moved")
    idx = moved / "data" / "index.json"
    idx.write_text(idx.read_text().replace("v-synthetic", "v-other"))
    m = json.loads((moved / rs.MANIFEST).read_text())
    m["files"]["data/index.json"] = sha(idx)
    (moved / rs.MANIFEST).write_text(json.dumps(m))
    with pytest.raises(rs.SnapshotError, match="its index is not the build its manifest names"):
        rs.open_snapshot(moved, tmp_path / "w")
    # A zip: a member changed, a manifest missing.
    zipped = tmp_path / "snap.zip"
    rs.pack(site, zipped)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(zipped) as z, zipfile.ZipFile(bad, "w") as out:
        for i in z.infolist():
            b = z.read(i)
            out.writestr(i, b"{}" if i.filename == "data/index.json" else b)
    e = refusal(capsys, "next", "--snapshot", str(bad))
    assert e["kind"] == "snapshot" and "data/index.json differs from the manifest" in e["message"]
    assert not list((tmp_path / rs.REVIEW_DIR / "snapshots").iterdir())
    with zipfile.ZipFile(zipped) as z, zipfile.ZipFile(bad, "w") as out:
        for i in z.infolist():
            if i.filename != rs.MANIFEST:
                out.writestr(i, z.read(i))
    e = refusal(capsys, "next", "--snapshot", str(bad))
    assert e["kind"] == "snapshot" and "holds no snapshot manifest" in e["message"]
    # A copy extracted before and changed since is extracted again from the archive.
    data, _ = rs.open_snapshot(zipped, tmp_path / "w")
    (data / "index.json").write_text("{}")
    again, _ = rs.open_snapshot(zipped, tmp_path / "w")
    assert again == data and json.loads((data / "index.json").read_text())["release"]


def test_the_reviewers_work_is_kept_apart_from_the_snapshot_and_the_authors(site, tmp_path,
                                                                           monkeypatch, capsys):
    snap = tmp_path / "snap"
    rs.pack(site, snap)
    monkeypatch.chdir(snap)
    # Inside the snapshot (the default working directory of a reviewer who went into it).
    e = refusal(capsys, "status", "--snapshot", ".")
    assert e["kind"] == "snapshot" and "is inside the snapshot" in e["message"]
    assert not (snap / rs.REVIEW_DIR).exists()
    monkeypatch.chdir(tmp_path)
    work = site.parent.parent
    e = refusal(capsys, "status", "--snapshot", str(snap), "--review-dir", str(work))
    assert e["kind"] == "snapshot" and "is a build's working directory" in e["message"]
    e = refusal(capsys, "status", "--snapshot", str(snap), "-c", "machinechecked.toml")
    assert e["kind"] == "invalid" and "leave out -c" in e["message"]
    e = refusal(capsys, "status", "--review-dir", "w")
    assert e["kind"] == "invalid" and "give --snapshot" in e["message"]


NO_BUILD = ("no review queue here. To review a project you did not build, get its author's "
            "review snapshot (`machinechecked review pack`) and pass it with --snapshot FILE: "
            "that needs no Lean. To review your own project, run `machinechecked view` or "
            "`machinechecked build` first")


def test_with_nothing_to_review_the_reviewer_is_told_of_the_snapshot(tmp_path, monkeypatch,
                                                                       capsys):
    """Without a build and without a snapshot, the refusal names both routes, the one for a
    project the reviewer did not build first: no Lean is needed to review. Outside a project
    the command cannot run; in a project with no build, the step is refused as `no-build`."""
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    got = step(capsys, "read", UNIT, "--json", rc_=2)
    assert (got.out, got.err) == ("", f"machinechecked: {NO_BUILD}\n")
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "lakefile.toml").write_text('name = "p"\n')
    monkeypatch.chdir(tmp_path / "project")
    e = refusal(capsys, "read", UNIT)
    assert e == {"kind": "no-build", "message": NO_BUILD}
    (tmp_path / "work").mkdir()
    with pytest.raises(rc.ReviewError) as err:
        rc.Session(tmp_path / "work", rc.parse_reviewer("human:R"))
    assert (err.value.kind, str(err.value)) == ("no-build", NO_BUILD)
    from prooflens.targets import Snapshot, TargetError
    with pytest.raises(TargetError) as err:
        Snapshot(tmp_path / "work")
    assert err.value.kind == "no-build" and "--snapshot FILE: that needs no Lean" in str(err.value)


def lean_free(tmp: Path) -> dict:
    """An environment whose PATH holds only a directory with the Python interpreter in it: no
    Lean, Lake, latexmk or synctex can be found."""
    bin_ = tmp / "bin"
    bin_.mkdir()
    (bin_ / "python3").symlink_to(sys.executable)
    env = {"PATH": str(bin_), "HOME": str(tmp / "home"), "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(ROOT / "engine" / "python"),
           "MACHINECHECKED_REVIEWER": "human:Snapshot-Referee"}
    for tool in ("lean", "lake", "elan", "latexmk", "pdflatex", "synctex"):
        assert shutil.which(tool, path=env["PATH"]) is None, tool
    return env


@needs_lean
@needs_tex
def test_a_toy_review_from_a_snapshot_on_a_machine_without_lean(toy, tmp_path, monkeypatch,
                                                                 capsys):
    _, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    unit = "def:Toy.triangle"
    # The author's own work: a draft of a review and an informed investigation.
    (tmp_path / "author.md").write_text(AUTHOR_READING)
    cli.main(["review", "read", unit, "--as", "human:Toy-Author"])
    cli.main(["review", "lock", unit, str(tmp_path / "author.md"), "--as", "human:Toy-Author"])
    cli.main(["workspace", "open", "--mode", "informed", "--as", "human:Toy-Investigator"])
    author_ws = [ws["id"] for _, ws in wsp.list_all(cfg.out_dir)]
    assert len(author_ws) == 2
    handoff = tmp_path / "handoff"
    cli.main(["review", "pack", "--out", str(handoff / "review-snapshot.zip")])
    assert "wrote the review snapshot" in capsys.readouterr().out
    with zipfile.ZipFile(handoff / "review-snapshot.zip") as z:
        names = z.namelist()
        packed = {n: z.read(n) for n in names}
    assert not any("review-work" in n or n.startswith("data/search") for n in names), names
    for x in [*author_ws, AUTHOR_READING]:
        assert not any(x.encode() in b for b in packed.values()), x
    queue = json.loads(packed["data/review-queue.json"])
    (u,) = [u for u in queue["units"] if u["id"] == unit]
    authored = [r["text"].strip() for r in u.get("author_review") or [] if r.get("text")]
    assert authored

    # The reviewer: another directory, no configuration, no project, no Lean.
    reviewer = tmp_path / "reviewer"
    reviewer.mkdir()
    env = lean_free(tmp_path)
    for name, text in {
            "reading.md": "T_n is the sum 0 + 1 + ... + n, defined for every natural number n.",
            "comparison.md": "The recursion adds n + 1 to T_n; T_0 = 0. It is the paper's sum.",
            "none.md": "none"}.items():
        (reviewer / name).write_text(text)

    def review(*args, code=0):
        r = subprocess.run([sys.executable, "-m", "prooflens", "review", *args,
                            "--snapshot", str(handoff / "review-snapshot.zip")],
                           cwd=reviewer, env=env, capture_output=True, text=True,
                           encoding="utf-8", timeout=300)
        assert r.returncode == code, r.stdout + r.stderr
        return r.stdout

    read = review("read", unit)
    assert "type :" not in read and "value:" not in read
    for text in authored:
        assert text[:60] not in read
    assert "order" in json.loads(review("show", unit, "--json", code=2))["error"]["kind"]
    review("lock", unit, "reading.md")
    assert "Toy.triangle" in review("show", unit)
    review("decide", unit, "faithful", "comparison.md", "--coverage", "full", "--basis",
           "direct")
    assert authored[0][:60] in review("author", unit)
    review("submit", unit, "none.md")
    review("export", "--out", "reports.json")
    assert sorted(p.name for p in handoff.iterdir()) == ["review-snapshot.zip"]
    assert not (reviewer / "machinechecked.toml").exists()

    # The maintainer checks the reports against the author's own release, as any report.
    (r,) = pr.load_reports([reviewer / "reports.json"])
    assert r["evidence"]["kind"] == "snapshot" and r["evidence"]["release"] == r["pins"]["release"]
    assert r["reading"]["revealed_by"] == []
    (_, _, why), = pr.plan(cfg, [r])
    assert not why, why
