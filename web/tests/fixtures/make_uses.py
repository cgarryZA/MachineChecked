"""Regenerate web/tests/fixtures/uses: the reader data the engine writes for the synthetic
project tests/fixtures/uses (zero configuration), and the answers its local server gives to
`GET /api/uses` for the declarations the browser test opens, and for one application asked for
in its caller (`in`, keyed `NAME in ID`). Needs elan and TeX Live.

    python3 web/tests/fixtures/make_uses.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "uses"
OUT = Path(__file__).resolve().parent / "uses"
ASKED = ["Uses.half_lt", "Uses.half_lt_four"]
WITHIN = [("Uses.half_lt", "app:Uses.caller_proves:0")]

sys.path.insert(0, str(ROOT / "engine" / "python"))
from prooflens.uses import route  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "uses"
    shutil.copytree(SRC, work)
    subprocess.run(["lake", "build"], cwd=work, check=True)
    site = Path(tmp) / "site"
    subprocess.run([sys.executable, "-m", "prooflens", "build", "--site", str(site)], cwd=work,
                   check=True)
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(site / "data", OUT / "data")
    get = route(work, site / "data")
    answers = {n: get({"name": [n]}) for n in ASKED}
    answers.update({f"{n} in {w}": get({"name": [n], "in": [w]}) for n, w in WITHIN})
    for doc in answers.values():
        doc.pop("cache", None)
    (OUT / "api-uses.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n")
print(f"wrote {OUT}")
