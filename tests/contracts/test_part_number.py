"""#623: a claim located by its lines inside a numbered environment, which the inventory gives no
number, is named by that environment: its printed number and the claim's place among the
inventory's claims in it, in source order ("Remark 2.4 (part 2)"), in `check`, the queue and the
read and show packets. A claim the inventory numbers keeps its number. Display only."""

import json
import subprocess
import sys

from conftest import needs_lean, needs_tex
from prooflens.manifest import part_number
from prooflens.tex import enclosing

SOURCE = ("\\begin{theorem}\\label{thm:a} One. \\end{theorem}\n"
          "\\begin{remark}\\label{rem:x}\n"
          "First claim.\n"
          "Second claim.\n"
          "\\end{remark}\n"
          "Prose outside.\n")
ANCHORS = [{"id": 1, "env": "theorem", "name": "Theorem", "number": "1", "file": "p.tex",
            "line": 1},
           {"id": 2, "env": "remark", "name": "Remark", "number": "2", "file": "p.tex",
            "line": 2}]
REGIONS = {f"P:{k}": {"file": "p.tex", "start_line": n, "end_line": n}
           for k, n in (("first", 3), ("second", 4), ("outside", 6))}
CLAIMS = [{"id": f"P:{k}", "paper": "P", "number": ""} for k in ("second", "first", "outside")]


def test_a_claim_inside_a_remark_is_named_by_it(tmp_path):
    (tmp_path / "p.tex").write_text(SOURCE)
    inside = enclosing(CLAIMS, "P", tmp_path, ANCHORS, REGIONS)
    assert inside == {"P:first": 2, "P:second": 2}
    t = {"anchors": ANCHORS, "regions": REGIONS, "enclosing": inside}
    names = {c["id"]: part_number(c, t, CLAIMS) for c in CLAIMS}
    assert names == {"P:first": "Remark 2 (part 1)", "P:second": "Remark 2 (part 2)",
                     "P:outside": ""}


def toy_claim(toy, cid, match):
    from prooflens.source_regions import SCHEME, extract
    lines = (toy / "paper" / "toy.tex").read_text().split("\n")
    n = next(i + 1 for i, l in enumerate(lines) if match in l)
    c = {"id": cid, "paper": "T", "kind": "remark", "number": "", "title": "",
         "location": f"toy.tex:{n}", "scope": "expository", "scope_note": "",
         "scope_reviewed": True, "clauses": []}
    region = extract(toy / "paper", c)
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": region.sha256,
            "source_line_sha256": region.line_sha256}


@needs_lean
@needs_tex
def test_the_toy_paper_names_two_claims_cut_from_a_remark(toy):
    """Two claims, each a sentence of Remark 2.4, with no number of their own."""
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"] += [toy_claim(toy, "T:rem:pred-holds", "for every $n \\ge 1$."),
                      toy_claim(toy, "T:rem:pred-fails", "With truncated subtraction")]
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=toy,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    got = {c["id"]: c["number"] for c in out["claims"]}
    assert got["T:rem:pred-fails"] == "Remark 2.4 (part 1)"
    assert got["T:rem:pred-holds"] == "Remark 2.4 (part 2)"
    assert got["T:rem:pred"] == "Remark 2.4"
    # The reader's data, which the review queue and its packets read the number from.
    data = toy / ".machinechecked" / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    row = next(c for c in index["claims"] if c["id"] == "T:rem:pred-holds")
    assert row["number"] == "Remark 2.4 (part 2)"
    chunk = json.loads((data / "claims" / row["file"]).read_text())
    assert chunk["number"] == "Remark 2.4 (part 2)"
