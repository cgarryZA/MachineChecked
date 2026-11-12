"""Regenerate web/tests/fixtures/mainuse: the reader data the engine writes for the synthetic
project tests/fixtures/mainuse (zero configuration), with how the suggested main result uses each
link (`data/main-use.json`), and the answer its local server gives to `GET /api/main-use` once a
workspace saves other main results (`api-main-use.json`). Needs elan and TeX Live.

    python3 web/tests/fixtures/make_mainuse.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "mainuse"
OUT = Path(__file__).resolve().parent / "mainuse"
SAVED = ["Lemma 2"]

sys.path.insert(0, str(ROOT / "engine" / "python"))
from prooflens import review_cli as rc  # noqa: E402
from prooflens import workspace as wsp  # noqa: E402
from prooflens.targets import Snapshot  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "mainuse"
    shutil.copytree(SRC, work)
    subprocess.run(["lake", "build"], cwd=work, check=True)
    site = Path(tmp) / "site"
    subprocess.run([sys.executable, "-m", "prooflens", "build", "--site", str(site)], cwd=work,
                   check=True)
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(site / "data", OUT / "data")
    # A workspace that saves Lemma 2 as the main result, and the answer `view` gives then.
    wd = work / ".machinechecked"
    data = wd / "site" / "data"
    snap = Snapshot(data)
    p = wsp.open_for(wd, rc.parse_reviewer("human:A-Auditor"), "informed", sources=snap.sources())
    wsp.update(p, [{"op": wsp.MAIN_OP, "main": SAVED}], snap, work)
    get, _ = wsp.api(wd, data, work)
    (OUT / "api-main-use.json").write_text(
        json.dumps(get["/api/main-use"]({}), ensure_ascii=False, indent=1) + "\n")
print(f"wrote {OUT}")
