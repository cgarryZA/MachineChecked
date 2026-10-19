"""The Lean build cache (`prooflens.cache`, `machinechecked cache`) on the toy example's Lean
project: a restore into another checkout rebuilds nothing, a one-file change rebuilds only what
it affects, and a corrupt, mismatched or incomplete archive is refused."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean
from prooflens import cache


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                        "PATH": __import__("os").environ["PATH"]})


def built(project, *args):
    """The modules `lake build` compiles (its "Built" lines)."""
    r = subprocess.run(["lake", "build", *args], cwd=project, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return [l for l in r.stdout.splitlines() if " Built " in l]


@pytest.fixture
def toy(tmp_path):
    """The toy Lean project as a Git repository, and a second clone of it elsewhere."""
    src = tmp_path / "a" / "toy"
    shutil.copytree(ROOT / "examples" / "toy-paper" / "lean", src,
                    ignore=shutil.ignore_patterns(".lake"))
    git(src, "init", "-q")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "toy")
    other = tmp_path / "b" / "toy"
    other.parent.mkdir()
    git(other.parent, "clone", "-q", str(src), "toy")
    return src, other


@needs_lean
def test_a_restore_elsewhere_rebuilds_nothing_and_a_change_only_what_it_affects(toy, tmp_path):
    src, other = toy
    out = tmp_path / "saved"
    man = cache.save(src, out, [], log=lambda m: None)
    assert man["commit"] and man["dirs"] == ["toy/.lake/build"] and not man["parts"]
    rec = cache.restore(other, local=out, log=lambda m: None)
    assert rec["commits_behind"] == 0
    assert built(other, "--rehash") == []
    # A changed file is rebuilt (with what depends on it, when its interface changed); the
    # modules it does not affect are not.
    with open(other / "Toy" / "Acceptance.lean", "a") as f:
        f.write("\n-- a comment\n")
    rebuilt = {l.split(" Built ")[1].split()[0] for l in built(other)}
    assert "Toy.Acceptance" in rebuilt and rebuilt <= {"Toy.Acceptance", "Toy"}


@needs_lean
def test_a_large_archive_is_saved_in_parts_and_restored_whole(toy, tmp_path):
    src, other = toy
    out = tmp_path / "saved"
    man = cache.save(src, out, [], part_size=4096, log=lambda m: None)
    assert len(man["parts"]) > 1 and not any(out.glob("*.tar.zst"))
    cache.restore(other, local=out, log=lambda m: None)
    assert built(other, "--rehash") == []


@needs_lean
def test_corrupt_mismatched_or_incomplete_archives_are_refused(toy, tmp_path):
    src, other = toy
    out = tmp_path / "saved"
    man = cache.save(src, out, [], log=lambda m: None)
    arc = next(out.glob("*.tar.zst"))
    good = arc.read_bytes()
    arc.write_bytes(good[:-1] + bytes([good[-1] ^ 1]))
    with pytest.raises(cache.CacheError, match="sha256"):
        cache.restore(other, local=out, log=lambda m: None)
    assert not (other / ".lake" / "build").exists()
    arc.write_bytes(good)
    # Another toolchain: the archive is not used.
    tc = other / "lean-toolchain"
    tc.write_text("leanprover/lean4:v0.0.0\n")
    with pytest.raises(cache.CacheError, match="no compatible"):
        cache.restore(other, local=out, log=lambda m: None)
    git(other, "checkout", "-q", "lean-toolchain")
    # A part missing: nothing to restore.
    arc.unlink()
    with pytest.raises(cache.CacheError, match="no compatible"):
        cache.restore(other, local=out, log=lambda m: None)
    assert json.loads(next(out.glob("*.json")).read_text())["sha256"] == man["sha256"]


@needs_lean
def test_uncommitted_lean_inputs_are_refused(toy, tmp_path):
    src, _ = toy
    (src / "Toy" / "Defs.lean").write_text("-- changed\n")
    with pytest.raises(cache.CacheError, match="uncommitted"):
        cache.save(src, tmp_path / "saved", [], log=lambda m: None)


def test_the_token_is_never_on_a_command_line(monkeypatch):
    seen = {}

    def fake_run(args, input=None, capture_output=False):
        seen["args"], seen["input"] = args, input
        return subprocess.CompletedProcess(args, 0, b"{}", b"")
    monkeypatch.setenv("MACHINECHECKED_GH_TOKEN", "secret-token-123")
    monkeypatch.setattr(cache.subprocess, "run", fake_run)
    cache.curl(["https://api.github.com/x"])
    assert not any("secret-token-123" in a for a in seen["args"])
    assert b"secret-token-123" in seen["input"] and "--config" in seen["args"]


def test_publishing_attaches_the_projects_licence(tmp_path, monkeypatch):
    """`publish` uploads the archive, its manifest and the licence files the manifest names."""
    project = tmp_path / "p"
    out = tmp_path / "saved"
    project.mkdir()
    out.mkdir()
    (project / "LICENSE").write_text("Apache License 2.0\n")
    commit = "c" * 40
    name = cache.asset_prefix(project) + commit
    (out / f"{name}.tar.zst").write_bytes(b"archive")
    (out / f"{name}.tar.zst.sha256").write_text("x\n")
    (out / f"{name}.json").write_text(json.dumps({
        "sha256": cache.sha256(out / f"{name}.tar.zst"), "parts": None,
        "licence_files": ["LICENSE"]}))
    uploaded = []
    monkeypatch.setenv("MACHINECHECKED_GH_TOKEN", "t")
    monkeypatch.setattr(cache, "_sh", lambda cmd, cwd=None: commit)
    monkeypatch.setattr(cache, "_release", lambda repo: {"id": 1, "assets": []})

    def fake_curl(args, auth=True, accept=None):
        uploaded.append(args[-1].split("name=")[1])
        return subprocess.CompletedProcess(args, 0, b"{}", b"")
    monkeypatch.setattr(cache, "curl", fake_curl)
    cache.publish(project, out, "someone/fork", log=lambda m: None)
    assert uploaded == [f"{name}.tar.zst", f"{name}.tar.zst.sha256", f"{name}.json", "LICENSE"]


def rec_commit(out):
    return json.loads(next(out.glob("*.json")).read_text())["commit"]


def clone(src, dest, *args):
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(dest.parent, "clone", "-q", *args, f"file://{src}", dest.name)
    return dest


@needs_lean
def test_any_clone_restores_whatever_its_folder_or_history(toy, tmp_path):
    """Archives are named after the Lake package and hold paths relative to the project, so a
    clone in another folder finds and unpacks them; the same Lean inputs are enough when the
    history cannot show the archived commit (a shallow clone, an amended commit)."""
    src, _ = toy
    out = tmp_path / "saved"
    cache.save(src, out, [], log=lambda m: None)
    renamed = clone(src, tmp_path / "c" / "work")
    cache.restore(renamed, local=out, log=lambda m: None)
    assert built(renamed, "--rehash") == []
    # A later commit changing no Lean file, cloned at depth 1: the archived commit is not in
    # the clone's history, so only the inputs can say the archive fits.
    (src / "README.md").write_text("notes\n")
    git(src, "add", "README.md")
    git(src, "commit", "-q", "-m", "notes")
    shallow = clone(src, tmp_path / "d" / "toy", "--depth", "1")
    assert subprocess.run(["git", "cat-file", "-e", f"{rec_commit(out)}^{{commit}}"],
                          cwd=shallow, capture_output=True).returncode != 0
    cache.restore(shallow, local=out, log=lambda m: None)
    assert built(shallow, "--rehash") == []
    # An amended commit that changes no Lean input still restores; one that does, does not.
    amended = clone(src, tmp_path / "e" / "toy")
    git(amended, "reset", "-q", "--hard", rec_commit(out))
    (amended / "README.md").write_text("notes\n")
    git(amended, "add", "README.md")
    git(amended, "commit", "-q", "--amend", "-m", "toy, amended")
    assert cache.restore(amended, local=out, log=lambda m: None)["commits_behind"] == 0
    with open(amended / "Toy" / "Defs.lean", "a") as f:
        f.write("\n-- changed\n")
    git(amended, "commit", "-q", "-am", "a Lean change")
    git(amended, "commit", "-q", "--amend", "-m", "rewritten")
    shutil.rmtree(amended / ".lake")
    with pytest.raises(cache.CacheError, match="no compatible"):
        cache.restore(amended, local=out, log=lambda m: None)


@needs_lean
def test_an_archive_in_the_older_layout_still_restores(toy, tmp_path):
    """Archives published before the package-named layout (paths from the checkout's parent,
    named after its folder) restore into a checkout in a folder of that name, in any case (#115),
    and nothing is written beside the checkout; a path outside the project is refused."""
    src, other = toy
    subprocess.run(["lake", "build"], cwd=src, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True,
                            text=True).stdout.strip()
    out = tmp_path / "old"
    out.mkdir()
    stem = cache._prefix(src.name) + commit
    arc = out / f"{stem}.tar.zst"
    subprocess.run(["tar", "-C", str(src.parent), "-I", "zstd -T0", "-cf", str(arc),
                    "toy/.lake/build"], check=True)
    (out / f"{stem}.json").write_text(json.dumps({
        "commit": commit, "project": "toy", "dirs": ["toy/.lake/build"],
        "sha256": cache.sha256(arc), **cache.fingerprint(src)}))
    cache.restore(other, local=out, log=lambda m: None)
    assert built(other, "--rehash") == []
    cased = clone(src, tmp_path / "c" / "Toy")
    cache.restore(cased, local=out, log=lambda m: None)
    assert built(cased, "--rehash") == []
    assert sorted(p.name for p in cased.parent.iterdir()) == ["Toy"]
    # An archive with a folder that is neither the project nor a path dependency is refused.
    (src.parent / "elsewhere").mkdir()
    (src.parent / "elsewhere" / "f").write_text("x")
    subprocess.run(["tar", "-C", str(src.parent), "-I", "zstd -T0", "-cf", str(arc),
                    "toy/.lake/build", "elsewhere"], check=True)
    man = json.loads((out / f"{stem}.json").read_text())
    (out / f"{stem}.json").write_text(json.dumps({**man, "sha256": cache.sha256(arc)}))
    fresh = clone(src, tmp_path / "d" / "TOY")
    with pytest.raises(cache.CacheError, match="elsewhere/f is not in this project"):
        cache.restore(fresh, local=out, log=lambda m: None)
    assert sorted(p.name for p in fresh.parent.iterdir()) == ["TOY"]
    assert not (fresh / ".lake" / "build").exists()


def test_prune_keeps_the_newest_of_each_package_platform_and_version():
    def man(project, created, toolchain="lean4:v1"):
        return {"project": project, "platform": "Linux-x86_64", "toolchain": toolchain,
                "created": created}
    manifests = {"a1": man("a", "2026-01-01"), "a2": man("a", "2026-01-02"),
                 "a3": man("a", "2026-01-03"), "a-other": man("a", "2026-01-01", "lean4:v2"),
                 "b1": man("b", "2026-01-01")}
    assert cache.prune_plan(manifests, keep=2) == ["a1"]
    assert cache.prune_plan(manifests, keep=1) == ["a1", "a2"]
    assert cache._files_of("a1", {"parts": None}) == ["a1.tar.zst", "a1.tar.zst.sha256", "a1.json"]
    assert cache._files_of("a1", {"parts": [{"name": "a1.tar.zst.part000"}]}) == \
        ["a1.tar.zst.part000", "a1.json"]


@needs_lean
def test_a_restore_that_cannot_fit_is_refused_and_a_failed_one_changes_nothing(toy, tmp_path,
                                                                               monkeypatch):
    """#100: too little free space is reported before anything is downloaded, with the sizes;
    an unpacking that fails part way (a full disk) leaves the build as it was."""
    src, other = toy
    out = tmp_path / "saved"
    man = cache.save(src, out, [], log=lambda m: None)
    assert man["unpacked_size"] > man["size"] > 0
    real = shutil.disk_usage
    monkeypatch.setattr(cache.shutil, "disk_usage",
                        lambda p: real(p)._replace(free=man["unpacked_size"] // 2))
    with pytest.raises(cache.CacheError, match=r"not enough disk space.*GB needed.*GB free"):
        cache.restore(other, local=out, log=lambda m: None)
    assert not (other / ".lake" / "build").exists()
    monkeypatch.setattr(cache.shutil, "disk_usage", real)
    import tarfile
    calls = {"n": 0}
    extract = tarfile.TarFile.extract

    def full_disk(self, *a, **k):
        calls["n"] += 1
        if calls["n"] > 3:
            raise OSError(28, "No space left on device")
        return extract(self, *a, **k)
    monkeypatch.setattr(tarfile.TarFile, "extract", full_disk)
    with pytest.raises(cache.CacheError, match="left as it was"):
        cache.restore(other, local=out, log=lambda m: None)
    assert not (other / ".lake" / "build").exists()
    assert not list(other.glob(".lean-cache-restore-*"))
