"""The TeX sandbox and the public export."""

import json
import shutil

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import config as cfgmod
from prooflens.export import ExportError, export


@needs_lean
@needs_tex
def test_shell_escape_is_off(toy, tmp_path):
    marker = tmp_path / "pwned"
    edit(toy / "paper/toy.tex", "\\maketitle", f"\\maketitle\n\\immediate\\write18{{touch {marker}}}")
    build(toy, skip_lean=True)
    assert not marker.exists()


@needs_lean
@needs_tex
def test_tex_cannot_write_outside_its_build_directory(toy, tmp_path):
    target = tmp_path / "outside.txt"
    edit(toy / "paper/toy.tex", "\\maketitle",
         f"\\maketitle\n\\newwrite\\w\\immediate\\openout\\w={target}\\immediate\\write\\w{{x}}"
         "\\immediate\\closeout\\w")
    try:
        build(toy, skip_lean=True)
    except Exception:
        pass  # refusing to compile is also acceptable
    assert not target.exists()


@needs_lean
@needs_tex
def test_private_paper_is_not_exported(toy, tmp_path):
    edit(toy / "machinechecked.toml", "publish = { pdf = true, source_text = true, lean = true, reviews = true }",
         "publish = { pdf = false, source_text = false, lean = true, reviews = false }")
    build(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    out = tmp_path / "public"
    export(cfg, out)
    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert not any(f.endswith(".pdf") for f in files)
    for p in out.rglob("*.json"):
        d = json.loads(p.read_text())
        if "statement_tex" in d:
            assert d["statement_tex"] is None


@needs_lean
@needs_tex
def test_export_with_a_leak_is_blocked(toy, tmp_path):
    edit(toy / "machinechecked.toml", "publish = { pdf = true, source_text = true, lean = true, reviews = true }",
         "publish = { pdf = true, source_text = false, lean = true, reviews = true }")
    build(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    web = tmp_path / "web"
    web.mkdir()
    line = next(l for l in (toy / "paper/toy.tex").read_text().splitlines() if len(l.strip()) >= 40
                and not l.strip().startswith("%"))
    (web / "index.html").write_text(f"<html><body>{line}</body></html>")
    with pytest.raises(ExportError, match="toy.tex"):
        export(cfg, tmp_path / "public", web_dist=web)
    assert not (tmp_path / "public").exists()


@needs_lean
@needs_tex
def test_unapproved_pdf_is_blocked(toy, tmp_path):
    edit(toy / "machinechecked.toml", "publish = { pdf = true, source_text = true, lean = true, reviews = true }",
         "publish = { pdf = false, source_text = true, lean = true, reviews = true }")
    build(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    web = tmp_path / "web"
    web.mkdir()
    shutil.copyfile(cfg.out_dir / "site" / "data" / "papers" / "T.pdf", web / "paper.pdf")
    with pytest.raises(ExportError, match="private PDF"):
        export(cfg, tmp_path / "public", web_dist=web)


def test_config_requires_a_pinned_git_revision(tmp_path):
    from prooflens.sources import SourceError, acquire
    (tmp_path / "machinechecked.toml").write_text(
        '[project]\nname="x"\nmodules=["X"]\nscope_roots=["X"]\nspec_prefix="X.S"\n'
        'accept_prefix="X.A"\ninventory="c.json"\n[[paper]]\nid="P"\nsource={git="o/r"}\n')
    cfg = cfgmod.load(tmp_path / "machinechecked.toml")
    with pytest.raises(SourceError, match="rev"):
        acquire(cfg, cfg.papers[0], tmp_path / "snap")


def test_several_roots_need_an_explicit_choice(tmp_path):
    from prooflens.config import Paper
    from prooflens.sources import SourceError, choose
    for n in ("a.tex", "b.tex"):
        (tmp_path / n).write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    with pytest.raises(SourceError, match="several LaTeX roots"):
        choose(Paper(id="P", title="P", source={"path": "."}), tmp_path)
    mode, root, _, _ = choose(Paper(id="P", title="P", source={"path": "."}, root="b.tex"), tmp_path)
    assert (mode, root) == ("latex", "b.tex")


def test_no_latex_falls_back_to_the_pdf(tmp_path):
    from prooflens.config import Paper
    from prooflens.sources import choose
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\n")
    mode, root, pdf, note = choose(Paper(id="P", title="P", source={"path": "."}), tmp_path)
    assert (mode, root, pdf) == ("pdf", None, "paper.pdf") and note
