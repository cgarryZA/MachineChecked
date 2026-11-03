"""Regenerate web/tests/fixtures/prooffacts: the reader data the engine writes for the synthetic
project tests/fixtures/prooffacts (zero configuration), and the engine's answers to
`compare --query proof-facts` for its two linked theorems, and for the first in pages of one fact
(`pages`, by the cursor each was asked with), which the browser test serves as the local server
would. Needs elan and TeX Live.

    python3 web/tests/fixtures/make_prooffacts.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "prooffacts"
OUT = Path(__file__).resolve().parent / "prooffacts"

with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "prooffacts"
    shutil.copytree(SRC, work)
    subprocess.run(["lake", "build"], cwd=work, check=True)
    site = Path(tmp) / "site"
    subprocess.run([sys.executable, "-m", "prooflens", "build", "--site", str(site)], cwd=work,
                   check=True)
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(site / "data", OUT / "data")
    def ask(name, *more):
        r = subprocess.run([sys.executable, "-m", "prooflens", "compare", "--query", "proof-facts",
                            name, "--json", *more], cwd=work, check=True, capture_output=True,
                           text=True)
        return json.loads(r.stdout)

    answers = {name: ask(name) for name in ("Facts.bound", "Facts.bound_cases")}
    pages, after = {}, ""
    while after is not None:
        page = ask("Facts.bound", "--limit", "1", *(["--after", after] if after else []))
        pages[after] = page
        after = page["retrieval"]["next"]
    answers["pages"] = {"Facts.bound": pages}
    (OUT / "facts.json").write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n",
                                    encoding="utf-8")
print(f"wrote {OUT}")
