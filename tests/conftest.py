"""Shared fixtures: a private copy of the toy paper, and a build of it; and CI's `--shard`."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

import shards
from prooflens import config as cfgmod
from prooflens import evidence as ev
from prooflens.pipeline import build as pl_build

ROOT = Path(__file__).resolve().parents[1]
TOY = ROOT / "examples" / "toy-paper"

ELAN = Path.home() / ".elan" / "bin"
if ELAN.exists() and str(ELAN) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{ELAN}{os.pathsep}{os.environ.get('PATH', '')}"

HAVE_LAKE = shutil.which("lake") is not None
HAVE_TEX = shutil.which("latexmk") is not None and shutil.which("pdflatex") is not None

needs_lean = pytest.mark.skipif(not HAVE_LAKE, reason="lake not installed")
needs_tex = pytest.mark.skipif(not HAVE_TEX, reason="latexmk/pdflatex not installed")


def pytest_addoption(parser):
    parser.addoption("--shard", metavar="I/N",
                     help="run only the I-th of N disjoint parts of the suite (see tests/shards.py)")
    parser.addoption("--shard-times", metavar="PATH",
                     help="write the time each test file took to PATH, for tests/durations.json")


def pytest_configure(config):
    if config.getoption("shard") or config.getoption("shard_times"):
        config.pluginmanager.register(shards.Shards(config), "shards")


@pytest.fixture
def toy(tmp_path) -> Path:
    """A copy of the toy paper (with its built `.lake`, so a mutation rebuilds only what
    changed)."""
    dst = tmp_path / "toy"
    shutil.copytree(TOY, dst, ignore=shutil.ignore_patterns(".prooflens", ".machinechecked"), symlinks=True)
    return dst


def build(root: Path, **kw):
    """Build the project at `root`; return the manifest index and the evidence body."""
    cfg = cfgmod.load(root / "machinechecked.toml")
    res = pl_build(cfg, log=lambda *a: None, **kw)
    rec = ev.load(cfg.out_dir, res["evidence"])
    return res["index"], rec["body"], cfg


def status(index, cid):
    return next(c["status"] for c in index["claims"] if c["id"] == cid)


def findings(body, code=None, subject=None):
    return [f for f in body["assessment"]["findings"]
            if (code is None or f["code"] == code)
            and (subject is None or f["subject"].split("#")[0] == subject)]


def edit(path: Path, old: str, new: str) -> None:
    txt = path.read_text()
    assert old in txt, f"{old!r} not in {path}"
    path.write_text(txt.replace(old, new, 1))
