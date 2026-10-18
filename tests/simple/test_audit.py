"""The audit descriptor, publishing a reader as a directory, and the reader's handling of an
audit read from another address."""

import json
import re
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, build, needs_lean, needs_tex
from prooflens import audit
from prooflens.simple import build_view, built_modules, save_settings, write_view_site

PLAIN = ROOT / "examples" / "plain-paper"
WEB = ROOT / "web" / "src"


def test_arxiv_identifiers_and_versions():
    assert audit.arxiv_id("https://arxiv.org/abs/2601.01234v2") == ("arxiv:2601.01234", "v2")
    assert audit.arxiv_id("https://arxiv.org/pdf/2601.01234") == ("arxiv:2601.01234", None)
    assert audit.arxiv_id("https://arxiv.org/abs/math/0211159v1") == ("arxiv:math/0211159", "v1")
    assert audit.arxiv_id("https://example.org/paper.pdf") is None


def test_github_repository_of_a_remote(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for url, want in [("https://github.com/someone/proj.git", "someone/proj"),
                      ("git@github.com:someone/proj.git", "someone/proj"),
                      ("https://gitlab.com/someone/proj.git", None)]:
        subprocess.run(["git", "remote", "remove", "origin"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=tmp_path, check=True)
        assert audit.github_repository(tmp_path) == want


@pytest.fixture
def plain(tmp_path):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"),
        symlinks=True)
    return dst


@needs_lean
@needs_tex
def test_a_site_carries_its_descriptor(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    save_settings(plain, issues="someone/audits", author="A. Reviewer")
    view = build_view(plain, plain / "paper/main.tex", plain / ".machinechecked",
                      log=lambda m: None)
    site = plain / ".machinechecked" / "site"
    index = write_view_site(view, site, None, plain)
    d = json.loads((site / "audit.json").read_text())
    assert d["schema"] == audit.SCHEMA and d["author"] == "A. Reviewer"
    assert d["release"] == index["release"] and d["issues"] == "someone/audits"
    assert (site / d["data"]).is_file()
    assert d["formalisation"]["toolchain"] == (plain / "lean-toolchain").read_text().strip()
    assert d["papers"][0]["title"] == index["papers"][0]["title"]
    # A paper on disk has no arXiv identifier; the descriptor does not invent one.
    assert d["papers"][0]["id"] is None


@needs_lean
@needs_tex
def test_build_writes_a_directory_to_publish(plain, tmp_path):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    out = tmp_path / "published"
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "build", "--site", str(out),
                        "--author", "A. Reviewer"], cwd=plain, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # Progress goes to stderr; stdout carries only the result.
    assert "lean:" in r.stderr and "lean:" not in r.stdout and "wrote the reader" in r.stdout
    assert json.loads((out / "audit.json").read_text())["author"] == "A. Reviewer"
    assert (out / "data" / "index.json").is_file()
    # It refuses to replace a directory that is not a previous site.
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("mine")
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "build", "--site", str(other)],
                       cwd=plain, capture_output=True, text=True)
    assert r.returncode != 0 and (other / "keep.txt").exists()


def test_the_export_carries_its_descriptor(toy, tmp_path):
    from prooflens import config as cfgmod
    from prooflens.export import export
    build(toy, skip_lean=True, skip_tex=True)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    export(cfg, tmp_path / "out")
    d = json.loads((tmp_path / "out" / "audit.json").read_text())
    assert d["schema"] == audit.SCHEMA and (tmp_path / "out" / d["data"]).is_file()
    assert d["issues"] == cfg.issues
    # With --data-only (for a site with its own reader), the data and descriptor, no reader.
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "export", "--data-only",
                        "--out", str(tmp_path / "data-only")], cwd=toy, capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in (tmp_path / "data-only").iterdir()) == ["audit.json", "data"]


# The reader displays an audit's text; it never inserts it as HTML. These checks keep it so.

def _sources():
    return [p for p in WEB.rglob("*") if p.suffix in (".svelte", ".js")]


def test_the_reader_never_inserts_data_as_html():
    bad = []
    for p in _sources():
        s = p.read_text(encoding="utf-8")
        for pat in (r"\{@html", r"\.innerHTML\s*=", r"insertAdjacentHTML", r"outerHTML\s*=",
                    r"document\.write", r"\beval\(", r"new Function\("):
            if re.search(pat, s):
                bad.append(f"{p.relative_to(WEB)}: {pat}")
    assert bad == []


def test_katex_runs_without_trust():
    for p in _sources():
        s = p.read_text(encoding="utf-8")
        assert not re.search(r"\btrust\s*:\s*(true|\()", s), p
    tex = (WEB / "components" / "TexInline.svelte").read_text()
    assert "el.textContent = " in tex   # the text is set as text before KaTeX reads it


def test_an_audit_is_read_only_and_confined_to_its_directory():
    data = (WEB / "lib" / "data.js").read_text()
    assert 'credentials: "omit"' in data
    assert "if (window.__PROOFLENS__ || AUDIT) return false;" in data   # never editable
    assert 'u.protocol !== "https:"' in data
    assert "outside the audit's directory" in data


@needs_lean
@needs_tex
def test_check_json_is_one_document_on_stdout(plain):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=plain,
                       capture_output=True, text=True)
    out = json.loads(r.stdout)
    assert out["schema"] == "machinechecked/check@1" and out["ok"] and r.returncode == 0
    c = {x["number"]: x for x in out["claims"]}
    assert c["Theorem 1"]["links"][0] == {"name": "Plain.odd_add_odd", "class": "proved",
                                          "status": "linked: Lean proof checked",
                                          "source": "paper"}
    assert c["Theorem 2"]["status"] == "suggested link, not confirmed"
    assert "not checked here" in out["note"]


def test_the_skill_says_what_the_statuses_do_not_mean():
    skill = (ROOT / "skills" / "machinechecked" / "SKILL.md").read_text()
    head = skill.split("---")[1]
    assert "name: machinechecked" in head and "description:" in head
    from prooflens.status import STATUSES
    src = "\n".join(v["label"] for v in STATUSES.values())
    # Every status the skill explains is one the engine writes.
    for st in re.findall(r"^\| `(linked: [^`]+|suggested link, not confirmed|not linked)` \|",
                         skill, re.M):
        assert st.split(" (")[0] in src or st in src, st
    assert "does **not** check that a Lean statement says what the paper" in skill


def test_source_links_point_into_the_project_and_can_be_private(toy, tmp_path):
    from prooflens import config as cfgmod
    from prooflens.export import export
    toml = toy / "machinechecked.toml"
    toml.write_text(toml.read_text().replace(
        "[project]\n", '[project]\nrepository = "someone/lean-proj"\nrepository_private = true\n', 1))
    build(toy, skip_lean=True, skip_tex=True)
    cfg = cfgmod.load(toml)
    export(cfg, tmp_path / "out")
    pr = json.loads((tmp_path / "out" / "data" / "index.json").read_text())["project"]
    assert pr["repository"] == "someone/lean-proj" and pr["repository_private"] is True
    # Only the project's own top-level modules get source links.
    assert pr["source_roots"] == ["Toy"]
    d = json.loads((tmp_path / "out" / "audit.json").read_text())["formalisation"]
    assert d["repository"] == "someone/lean-proj" and d["repository_private"] is True


@needs_lean
@needs_tex
def test_check_writes_no_site_and_names_the_release_build_writes(plain, tmp_path):
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=plain,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr
    release = json.loads(r.stdout)["release"]
    assert not (plain / ".machinechecked" / "site").exists()
    out = tmp_path / "published"
    subprocess.run([sys.executable, "-m", "prooflens.cli", "build", "--site", str(out)], cwd=plain,
                   capture_output=True, text=True, check=True)
    assert json.loads((out / "audit.json").read_text())["release"] == release


@needs_lean
@needs_tex
def test_the_one_file_reader_is_written_where_git_ignores_it(plain):
    """The file embeds the paper, so by default it goes in the ignored working directory."""
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    subprocess.run(["git", "init", "-q"], cwd=plain, check=True)
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "build"], cwd=plain,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (plain / ".machinechecked" / "MachineChecked.html").is_file()
    assert not (plain / "MachineChecked.html").exists()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=plain,
                            capture_output=True, text=True).stdout
    assert "MachineChecked.html" not in status and ".machinechecked" not in status
