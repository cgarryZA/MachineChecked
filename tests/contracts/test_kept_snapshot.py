"""A review snapshot kept in the project's repository (#747). `build` writes it again when the
project keeps one (`[review] snapshot`, or a `review-snapshot/` directory at its root) and leaves
it as it is while it holds the build's review material, so that a committed snapshot changes only
with that material. The review steps without --snapshot use the project's own build when there is
one, and otherwise the snapshot it keeps, checked as with --snapshot; they say which they used.

The fast tests use the synthetic site of `test_compare.write_site` as a project's build; the last
one builds the toy example, commits its snapshot, and reviews a clone of the repository in a
subprocess whose PATH holds no Lean, Lake or TeX."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import config as cfgmod
from prooflens import promote as pr
from prooflens import review_snapshot as rs
from prooflens.versions import manuscript_record
from test_compare import write_site
from test_review_snapshot import READING, UNIT, files_of, lean_free, refusal, sha, step

TEXTS = {"reading.md": READING, "comparison.md": "The same bound, for every n.",
         "none.md": "none"}
CONFIG = """[project]
name = "syn"
modules = ["Syn"]
scope_roots = ["Syn"]
spec_prefix = "Syn.Spec"
accept_prefix = "Syn.Acceptance"
inventory = "claims.json"
"""


@pytest.fixture
def project(tmp_path):
    """A zero-configuration project whose last build is the synthetic site."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "syn"\n')
    write_site(tmp_path)
    shutil.move(tmp_path / "work", root / ".machinechecked")
    return root


def texts(where: Path) -> Path:
    where.mkdir(exist_ok=True)
    for name, text in TEXTS.items():
        (where / name).write_text(text)
    return where


def contents(root: Path) -> dict[str, bytes]:
    return {f: (root / f).read_bytes() for f in files_of(root)}


def test_the_review_steps_use_the_build_here_else_the_snapshot_the_project_keeps(
        project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(project)
    cli.main(["review", "pack"])
    out = capsys.readouterr().out
    snap = project / rs.PROJECT_DIR
    assert rs.kept(snap) and out.startswith(f"wrote the review snapshot {snap}")
    assert out.rstrip().endswith("Commit it with the project: a reviewer who clones the "
                                 "repository reviews it with `machinechecked review next`, "
                                 "without Lean, and `machinechecked build` keeps it current.")
    assert "--snapshot" not in out
    # Its JSON holds the build's values, written compactly.
    data = project / ".machinechecked" / "site" / "data"
    for f in files_of(snap / "data"):
        packed = (snap / "data" / f).read_bytes()
        assert json.loads(packed) == json.loads((data / f).read_bytes()), f
        assert packed == (json.dumps(json.loads(packed), ensure_ascii=False,
                                     separators=(",", ":")) + "\n").encode(), f
    assert sum(len(b) for b in contents(snap / "data").values()) < sum(
        (data / f).stat().st_size for f in files_of(snap / "data"))
    built_read = step(capsys, "read", UNIT, "--json").out
    # With a build here, the build is reviewed, and the step says so.
    got = step(capsys, "next")
    assert got.out.startswith(UNIT)
    assert got.err == ("note: reviewing this project's build (.machinechecked/, release "
                       "v-synthetic), not its review snapshot review-snapshot/\n")
    e = refusal(capsys, "status", "--review-dir", "w")
    assert e["kind"] == "invalid" and "leave out --review-dir" in e["message"]

    # A clone holds what is committed: the project and its snapshot, and no build.
    clone = tmp_path / "clone"
    shutil.copytree(project, clone, ignore=shutil.ignore_patterns(".machinechecked"))
    kept = contents(clone / rs.PROJECT_DIR)
    t = texts(tmp_path / "texts")
    (clone / "sub").mkdir()
    monkeypatch.chdir(clone / "sub")
    got = step(capsys, "next")
    assert got.out.startswith(UNIT)
    assert got.err == ("note: reviewing the project's review snapshot "
                       f"{clone}/review-snapshot/ (release v-synthetic), as there is no build "
                       f"here; your work is kept in {clone}/.machinechecked-review/\n")
    monkeypatch.chdir(clone)
    # Step 1 shows what it shows from the build.
    assert step(capsys, "read", UNIT, "--json").out == built_read
    assert "Statement 0." in step(capsys, "read", UNIT).out
    step(capsys, "lock", UNIT, str(t / "reading.md"))
    step(capsys, "show", UNIT)
    step(capsys, "decide", UNIT, "faithful", str(t / "comparison.md"), "--coverage", "full",
         "--basis", "direct")
    step(capsys, "author", UNIT)
    step(capsys, "submit", UNIT, str(t / "none.md"))
    status = step(capsys, "status")
    digest = sha(clone / rs.PROJECT_DIR / rs.MANIFEST)
    assert f"the review snapshot {digest}" in status.out
    assert "release v-synthetic), as there is no build here" in status.err
    step(capsys, "export", "--out", str(t / "reports.json"))
    (r,) = pr.load_reports([t / "reports.json"])
    assert r["evidence"]["kind"] == "snapshot" and r["evidence"]["manifest_sha256"] == digest
    assert r["reading"]["text"] == READING
    # The work is at the project's root, out of Git; nothing was built and the snapshot is as
    # its author wrote it.
    work = clone / rs.REVIEW_DIR
    assert (work / ".gitignore").read_text().strip().endswith("*")
    assert not (clone / ".machinechecked").exists()
    assert contents(clone / rs.PROJECT_DIR) == kept
    # --review-dir names another working directory; --snapshot names another snapshot.
    out = step(capsys, "status", "--json", "--review-dir", str(tmp_path / "other")).out
    assert json.loads(out)["open"] == [UNIT] and (tmp_path / "other").is_dir()
    rs.pack(project / ".machinechecked" / "site" / "data", tmp_path / "given.zip")
    got = step(capsys, "status", "--json", "--snapshot", str(tmp_path / "given.zip"),
               "--review-dir", str(tmp_path / "third"))
    assert json.loads(got.out)["open"] == [UNIT] and got.err == ""
    # The project's snapshot is checked before each step, as one given with --snapshot.
    (clone / rs.PROJECT_DIR / "data" / "claims" / "S_thm_t3.json").write_text("{}")
    e = refusal(capsys, "read", UNIT)
    assert e["kind"] == "snapshot"
    assert "data/claims/S_thm_t3.json differs from the manifest" in e["message"]


def test_pack_names_the_snapshot_as_a_reviewer_gives_it(project, tmp_path, monkeypatch, capsys):
    """The hint `review pack` ends with names the path from the project's root, or the path
    given when it is outside the project; the snapshot the project keeps needs no flag."""
    (project / "sub").mkdir()
    monkeypatch.chdir(project / "sub")
    for out, given in [("../some/dir/review-snapshot", "some/dir/review-snapshot"),
                       ("snap.zip", "sub/snap.zip"),
                       (str(tmp_path / "handoff.zip"), str(tmp_path / "handoff.zip"))]:
        cli.main(["review", "pack", "--out", out])
        said = capsys.readouterr().out
        assert said.rstrip().endswith("A reviewer opens it with `machinechecked review next "
                                      f"--snapshot {given}`, without Lean."), said
    cli.main(["review", "pack", "--out", "../review-snapshot"])
    said = capsys.readouterr().out
    assert "reviews it with `machinechecked review next`, without Lean" in said
    assert "--snapshot" not in said


def renamed(data: Path, release: str, evidence: str, commit: str) -> None:
    """The site data `data` as a later build of the same material writes it: another release,
    evidence record and commit (which names the paper, a file of the project), another time, and
    uncommitted changes in the tree."""
    index = json.loads((data / "index.json").read_text())
    index.update(release=release, evidence=evidence, created="2030-01-01T00:00:00+00:00")
    index["project"].update(commit=commit, dirty=True)
    index["papers"][0].update(revision=commit, paper_version=manuscript_record(commit))
    (data / "index.json").write_text(json.dumps(index))
    queue = json.loads((data / "review-queue.json").read_text())
    queue["release"] = release
    (data / "review-queue.json").write_text(json.dumps(queue))


def test_a_snapshot_is_written_again_only_when_its_review_material_changes(tmp_path):
    data = write_site(tmp_path)
    # The paper is a file of the project: the manuscript at the project's commit.
    index = json.loads((data / "index.json").read_text())
    index["papers"][0]["paper_version"] = manuscript_record("c" * 40)
    (data / "index.json").write_text(json.dumps(index))
    snap = tmp_path / "snap"
    first = rs.pack(data, snap, tool="1.0")
    was = contents(snap)
    again = rs.pack(data, snap, tool="2.0")
    assert again["unchanged"] and again["digest"] == first["digest"]
    assert again["tool"]["version"] == "1.0" and contents(snap) == was
    # A later build of the same material names itself differently: the snapshot stands, and
    # says which release it was written for.
    renamed(data, "v-later", "f" * 64, "d" * 40)
    later = rs.pack(data, snap)
    assert later["unchanged"] and later["built"] == "v-later" and contents(snap) == was
    assert later["sources"]["release"] == "v-synthetic"
    assert "this build, release v-later, holds the same review material" in rs.summary_text(later)
    assert rs.refresh_line(later, "review-snapshot/") == (
        "the review snapshot review-snapshot/ is current (release v-synthetic; this build, "
        "release v-later, holds the same review material)")
    rs.open_snapshot(snap, tmp_path / "w")
    # A change of the material is written, under the build's own names.
    ch = json.loads((data / "claims" / "S_thm_t3.json").read_text())
    ch["statement_tex"] = ch["statement_tex"].replace("Statement 3.", "Statement three.")
    (data / "claims" / "S_thm_t3.json").write_text(json.dumps(ch))
    changed = rs.pack(data, snap)
    assert not changed.get("unchanged") and changed["sources"]["release"] == "v-later"
    assert changed["sources"]["project"]["commit"] == "d" * 40
    assert rs.refresh_line(changed, "review-snapshot/") == (
        "wrote the review snapshot review-snapshot/ (release v-later): commit it with the "
        "project for reviewers who clone the repository")
    # So is a snapshot changed since it was written, and one asked for with other PDFs.
    (snap / "data" / "claims" / "S_thm_t5.json").write_text("{}")
    assert not rs.pack(data, snap).get("unchanged")
    rs.open_snapshot(snap, tmp_path / "w")
    (data / "papers").mkdir()
    (data / "papers" / "S.pdf").write_bytes(b"%PDF-1.4 synthetic")
    assert not rs.pack(data, snap, pdf=True).get("unchanged") and rs.packed_pdf(snap)
    assert rs.pack(data, snap, pdf=True)["unchanged"]
    # The commit of a project that was not a repository is a change: the snapshot names it.
    index = json.loads((data / "index.json").read_text())
    index["project"].pop("commit")
    (data / "index.json").write_text(json.dumps(index))
    assert not rs.pack(data, snap, pdf=True).get("unchanged")


def no_build(monkeypatch, full: bool = False) -> None:
    """`build` without its build: the site data is there already."""
    if full:
        monkeypatch.setattr(cli, "_build_full", lambda a, then=None, **kw: then())
    else:
        monkeypatch.setattr(cli, "_build_simple", lambda a: None)


def test_build_writes_the_snapshot_only_for_a_project_that_keeps_one(project, monkeypatch,
                                                                     capsys):
    monkeypatch.chdir(project)
    no_build(monkeypatch)
    snap = project / rs.PROJECT_DIR
    cli.main(["build"])
    assert not snap.exists() and capsys.readouterr().out == ""
    snap.mkdir()
    cli.main(["build"])
    assert capsys.readouterr().out == (
        "wrote the review snapshot review-snapshot/ (release v-synthetic): commit it with the "
        "project for reviewers who clone the repository\n")
    was = contents(snap)
    cli.main(["build"])
    assert capsys.readouterr().out == "the review snapshot review-snapshot/ is current " \
                                      "(release v-synthetic)\n"
    assert contents(snap) == was
    # The PDF the author packed stays in.
    data = project / ".machinechecked" / "site" / "data"
    (data / "papers").mkdir()
    (data / "papers" / "S.pdf").write_bytes(b"%PDF-1.4 synthetic")
    cli.main(["review", "pack", "--pdf"])
    cli.main(["build"])
    assert "data/papers/S.pdf" in files_of(snap) and "is current" in capsys.readouterr().out
    # A directory of that name that holds something else is the project's own.
    shutil.rmtree(snap)
    snap.mkdir()
    (snap / "notes.txt").write_text("mine")
    cli.main(["build"])
    assert capsys.readouterr().err == ("note: review-snapshot/ holds no review snapshot: the "
                                       "build left it as it is\n")
    assert files_of(snap) == {"notes.txt"}


def test_a_configuration_names_the_snapshot_build_keeps_and_the_review_reads(
        project, tmp_path, monkeypatch, capsys):
    (project / "machinechecked.toml").write_text(CONFIG + '\n[review]\nsnapshot = "audit/snap"\n')
    monkeypatch.chdir(project)
    no_build(monkeypatch, full=True)
    cli.main(["build"])
    snap = project / "audit" / "snap"
    assert rs.kept(snap) and not (project / rs.PROJECT_DIR).exists()
    assert capsys.readouterr().out.startswith("wrote the review snapshot audit/snap/ ")
    cli.main(["review", "pack"])
    assert "is current" in capsys.readouterr().out
    shutil.rmtree(project / ".machinechecked")
    got = step(capsys, "next")
    assert got.out.startswith(UNIT) and "snapshot audit/snap/ (release v-synthetic)" in got.err
    assert (project / rs.REVIEW_DIR).is_dir()
    # A configured snapshot that cannot be written stops the build.
    write_site(tmp_path)
    shutil.move(tmp_path / "work", project / ".machinechecked")
    shutil.rmtree(snap)
    snap.mkdir()
    (snap / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit) as e:
        cli.main(["build"])
    assert e.value.code == 2
    assert "the review snapshot audit/snap/ was not written: " in capsys.readouterr().err
    # The setting is a directory inside the project.
    for bad, why in [("/abs", "relative to the project's root"), ("../out", "inside the project"),
                     (".", "inside the project"), ("snap.zip", "not a .zip archive"),
                     ("", "relative to the project's root")]:
        (project / "machinechecked.toml").write_text(
            CONFIG + f"\n[review]\nsnapshot = {json.dumps(bad)}\n")
        with pytest.raises(cfgmod.ConfigError, match=why):
            cfgmod.load(project / "machinechecked.toml")


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=Toy Author", "-c",
                        "user.email=toy@example.invalid", *args], cwd=cwd,
                       capture_output=True, text=True, check=True)
    return r.stdout


@needs_lean
@needs_tex
def test_a_clone_of_the_toy_is_reviewed_from_its_committed_snapshot_without_lean(
        toy, tmp_path, monkeypatch, capsys):
    cfg_file = toy / "machinechecked.toml"
    cfg_file.write_text(cfg_file.read_text() + '\n[review]\nsnapshot = "review-snapshot"\n')
    (toy / ".gitignore").write_text(".machinechecked/\n.lake/\n")
    git(toy, "init", "-q")
    git(toy, "add", "-A")
    git(toy, "commit", "-q", "-m", "The toy paper")
    monkeypatch.chdir(toy)
    cli.main(["build"])
    assert "wrote the review snapshot review-snapshot/" in capsys.readouterr().out
    # The second release has one before it, which the review queue's order compares it with.
    cli.main(["build"])
    assert "wrote the review snapshot review-snapshot/" in capsys.readouterr().out
    git(toy, "add", "-A")
    git(toy, "commit", "-q", "-m", "Its review snapshot")
    # The next builds are of another commit, with the same review material: the committed
    # snapshot stands, and the tree stays clean.
    for _ in range(2):
        cli.main(["build"])
        assert "the review snapshot review-snapshot/ is current" in capsys.readouterr().out
        assert git(toy, "status", "--porcelain") == ""
    unit = "def:Toy.triangle"
    cli.main(["review", "status", "--as", "human:Toy-Author"])
    assert "not its review snapshot review-snapshot/" in capsys.readouterr().err

    # The reviewer clones the repository, and has Python and no Lean, Lake or TeX.
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(toy), str(clone))
    assert not (clone / ".machinechecked").exists() and rs.kept(clone / "review-snapshot")
    t = texts(tmp_path / "texts")
    (t / "reading.md").write_text("T_n is the sum 0 + 1 + ... + n, for every natural number n.")
    (t / "comparison.md").write_text("The recursion adds n + 1 to T_n; T_0 = 0: the sum.")
    env = lean_free(tmp_path)

    def review(*args):
        r = subprocess.run([sys.executable, "-m", "prooflens", "review", *args], cwd=clone,
                           env=env, capture_output=True, text=True, encoding="utf-8",
                           timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reviewing the project's review snapshot review-snapshot/" in r.stderr
        return r.stdout

    assert unit in json.loads(review("status", "--json"))["open"]
    review("read", unit)
    review("lock", unit, str(t / "reading.md"))
    assert "Toy.triangle" in review("show", unit)
    review("decide", unit, "faithful", str(t / "comparison.md"), "--coverage", "full",
           "--basis", "direct")
    review("author", unit)
    review("submit", unit, str(t / "none.md"))
    review("export", "--out", str(t / "reports.json"))
    assert git(clone, "status", "--porcelain") == ""
    assert not (clone / ".machinechecked").exists()

    # The author's release accepts the report, by the usual rules.
    (r,) = pr.load_reports([t / "reports.json"])
    assert r["evidence"]["kind"] == "snapshot"
    assert r["evidence"]["manifest_sha256"] == sha(clone / "review-snapshot" / rs.MANIFEST)
    (_, _, why), = pr.plan(cfgmod.load(cfg_file), [r])
    assert not why, why
