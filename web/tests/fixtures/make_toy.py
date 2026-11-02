"""Regenerate web/tests/fixtures/toy/data: the toy example's audit as the engine exports it, with
two symbol links recorded (in a copy; the example itself has none). Needs elan and TeX Live.

    python3 web/tests/fixtures/make_toy.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "toy" / "data"
MC = [sys.executable, "-m", "prooflens"]
SPEC = "Toy.PaperSpec.thm_even_add"

with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "toy"
    shutil.copytree(ROOT / "examples" / "toy-paper", work,
                    ignore=shutil.ignore_patterns(".prooflens", ".machinechecked", "symbols.json"))
    run = lambda *a: subprocess.run([*MC, *a], cwd=work, check=True)  # noqa: E731
    run("build")
    stored = lambda: set(work.glob(".*/releases/*.json"))  # noqa: E731
    first = stored()
    run("symbol", "add", "T:thm:even-add", "a", SPEC, "--var", "a", "--as", "human:A-Referee")
    run("symbol", "add", "T:thm:even-add", "b", SPEC, "--var", "b", "--as", "human:A-Referee")
    run("build", "--reuse-lean")
    # The toy is a release without an earlier one: the build made before its links were
    # recorded is not kept (the reader's tests make a site with changes apart).
    if stored() - first:
        for p in first:
            p.unlink()
    run("export", "--out", str(Path(tmp) / "site"), "--data-only")
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(Path(tmp) / "site" / "data", OUT)
print(f"wrote {OUT}")
