"""Regenerate web/tests/fixtures/structure/data: the reader data the engine writes for the
synthetic project tests/fixtures/structure (zero configuration). Needs elan and TeX Live.

    python3 web/tests/fixtures/make_structure.py
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "structure"
OUT = Path(__file__).resolve().parent / "structure" / "data"

with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "structure"
    shutil.copytree(SRC, work)
    subprocess.run(["lake", "build"], cwd=work, check=True)
    site = Path(tmp) / "site"
    subprocess.run([sys.executable, "-m", "prooflens", "build", "--site", str(site)], cwd=work,
                   check=True)
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(site / "data", OUT)
print(f"wrote {OUT}")
