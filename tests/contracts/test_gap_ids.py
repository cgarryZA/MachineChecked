"""#576: the finding about a statement of the compiled paper that is not in the inventory is named
as zero configuration names the claim: by its label, else its environment and number
(`T:remark-2.7`), else its environment and place. Two unlabelled statements of one kind no
longer share an id and a subject, and no two findings of a build do."""

import json
import subprocess
import sys
from collections import Counter
from types import SimpleNamespace

from conftest import edit, needs_lean, needs_tex
from prooflens.assess import Assessor


def gaps(anchors):
    cfg = SimpleNamespace(statement_authors=[], lean_root=None, papers=[SimpleNamespace(id="T")])
    lean = {"specs": {}, "decls": {}, "proofs": {}, "defs": {}, "layering": []}
    tex = {"T": {"mode": "latex", "envs": ["remark"], "anchors": anchors, "regions": {}}}
    out = Assessor(cfg, {"claims": []}, lean, tex, [], []).run()
    return [(f["id"], f["subject"]) for f in out["findings"] if f["code"] == "inventory-gap"]


def test_unlabelled_statements_of_one_kind_have_their_own_ids():
    anchors = [{"id": i, "env": "remark", "number": n, "label": lab, "file": "toy.tex",
                "line": line, "source_sha256": "a" * 64}
               for i, n, lab, line in ((1, "2.7", None, 90), (2, "2.8", None, 94),
                                       (3, None, None, 98), (4, "2.9", "rem:x", 99))]
    assert gaps(anchors) == [
        ("inventory-gap:T:remark-2.7", "T:remark-2.7"),
        ("inventory-gap:T:remark-2.8", "T:remark-2.8"),
        ("inventory-gap:T:remark@toy.tex:98", "T:remark@toy.tex:98"),
        ("inventory-gap:T:rem:x", "T:rem:x")]


@needs_lean
@needs_tex
def test_the_toy_paper_gives_each_finding_its_own_id(toy):
    """The issue's reproduction: two unlabelled remarks before the discussion."""
    edit(toy / "paper" / "toy.tex", "\\section{Discussion}",
         "\\begin{remark} Two is even. \\end{remark}\n\n"
         "\\begin{remark} Four is even. \\end{remark}\n\n\\section{Discussion}")
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=toy,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    found = [f for f in out["finding_details"] if f["code"] == "inventory-gap"]
    assert len(found) == 2 and len({f["subject"] for f in found}) == 2
    assert all(f["subject"].startswith("T:remark-") for f in found)
    twice = [i for i, n in Counter(f["id"] for f in out["finding_details"]).items() if n > 1]
    assert twice == []
