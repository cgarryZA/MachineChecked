"""#571: a review compares a Lean statement with the paper, so a clause that names no
proposition (in a definition claim, no proposition and no definition) has nothing to review and
is never reviewed. Its claim reads "not reviewed" and is not counted among reviewed claims, in
the assessment, `check`, `check --json`, the semantic summary and the reader's data; a claim
with a reviewed proposition still reads as reviewed, and no status word changes."""

import json
import subprocess
import sys
from types import SimpleNamespace

from conftest import edit, needs_lean, needs_tex
from prooflens import semantic
from prooflens.assess import Assessor
from prooflens.manifest import clause_evidence
from prooflens.probe import proof_key
from prooflens.reviews import Review


def spec(name):
    return {"fingerprint": f"fp-{name}", "errors": [], "binders": [], "closure": [], "consts": []}


LEAN = {"specs": {"S.a": spec("S.a")},
        "decls": {n: {"name": n, "fingerprint": f"fp-{n}", "uses": []} for n in ("S.a", "D.x")},
        "proofs": {proof_key("accept", "S.a_proof", "S.a"): {"errors": [], "sorry": False,
                                                              "axioms": []}},
        "defs": {"D.x": {"closure": []}}, "layering": []}

REVIEWS = [Review("spec", "S.a", "fp-S.a", "reader", "human", "self-declared", "r.md", 1,
                  "Read against the paper."),
           Review("def", "D.x", "fp-D.x", "reader", "human", "self-declared", "r.md", 2,
                  "Read against the paper.")]

PROVED = {"name": "statement", "spec": "S.a", "accept": "S.a_proof"}


def claim(cid, *clauses, scope="formal"):
    return {"id": f"P:{cid}", "paper": "P", "kind": "theorem", "scope": scope,
            "scope_reviewed": True, "clauses": list(clauses)}


CLAIMS = [
    claim("none", {"name": "statement", "spec": None}),
    claim("ok", PROVED),
    claim("mixed", PROVED, {"name": "second part", "spec": None}),
    claim("defs-only", {"name": "statement", "spec": None, "defs": ["D.x"]}),
    claim("def-empty", {"name": "definition", "spec": None, "defs": []}, scope="definition"),
    claim("def-ok", {"name": "definition", "spec": None, "defs": ["D.x"]}, scope="definition"),
]


def assess():
    cfg = SimpleNamespace(statement_authors=[], lean_root=None,
                          papers=[SimpleNamespace(id="P")])
    out = Assessor(cfg, {"claims": CLAIMS}, LEAN, {}, REVIEWS, []).run()
    return {c["id"]: c for c in out["claims"]}


def test_a_clause_with_no_proposition_is_never_reviewed():
    got = assess()
    assert [cl["review"] for cl in got["P:none"]["clauses"]] == ["pending"]
    assert got["P:none"]["clauses"][0]["state"] == "unspecified"
    assert [cl["review"] for cl in got["P:mixed"]["clauses"]] == ["reviewed", "pending"]
    # Definitions named by a theorem's clause are reviewed (their obligations stand), but the
    # clause states no proposition, so it has no review of its own.
    assert got["P:defs-only"]["clauses"][0]["def_reviews"]["D.x"]["state"] == "reviewed"
    assert got["P:defs-only"]["clauses"][0]["review"] == "pending"
    assert got["P:def-empty"]["clauses"][0]["review"] == "pending"
    # A reviewed proposition, and a definition claim's reviewed definition, still read reviewed.
    assert got["P:ok"]["clauses"][0]["review"] == "reviewed"
    assert got["P:def-ok"]["clauses"][0]["review"] == "reviewed"


def test_the_status_words_are_unchanged_and_never_rounded_up():
    got = {cid: c["status_code"] for cid, c in assess().items()}
    assert got == {"P:none": "formal.open", "P:ok": "formal.accepted",
                   "P:mixed": "formal.open.partial", "P:defs-only": "formal.open",
                   "P:def-empty": "definition.review-pending",
                   "P:def-ok": "definition.reviewed"}


def test_the_summary_and_the_reader_read_it_as_not_reviewed():
    got = assess()
    rows = [{"id": cid, "paper": "P", "file": cid, "kind": "theorem", "unit": "statement",
             "status_code": c["status_code"]} for cid, c in got.items()]
    chunks = {cid: {"kind": "theorem", "unit": "statement", "clauses": c["clauses"]}
              for cid, c in got.items()}
    summary, facts = semantic.summarise({"claims": rows, "papers": []}, chunks)
    assert {cid: f["review"] for cid, f in facts.items()} == {
        "P:none": "none", "P:ok": "independent", "P:mixed": "none", "P:defs-only": "none",
        "P:def-empty": "none", "P:def-ok": "independent"}
    assert facts["P:none"]["declarations"] == 0
    review = summary["papers"]["P"]["review"]["statements"]
    assert (review["independent"], review["none"]) == (2, 4)
    assert "    reviews: current, independent (2); not reviewed (4)" in semantic.text(summary)
    # The reader shows each clause's review rung as the assessment computed it.
    rung = clause_evidence(got["P:none"]["clauses"][0], None, None, None)
    assert rung["review"] == {"state": "pending"}
    assert clause_evidence(got["P:ok"]["clauses"][0], None, None, None)["review"] == \
        {"state": "reviewed"}


def _check(root, *args):
    return subprocess.run([sys.executable, "-m", "prooflens.cli", "check", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8")


@needs_lean
@needs_tex
def test_the_toy_paper_counts_no_review_of_a_claim_without_a_proposition(toy):
    """The issue's reproduction: a formal claim whose only clause has `spec: null`."""
    edit(toy / "paper" / "toy.tex", "\\section{Discussion}",
         "\\begin{theorem}\\label{thm:new} Zero is even. \\end{theorem}\n\n"
         "\\section{Discussion}")
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"].append({"id": "T:thm:new", "paper": "T", "kind": "theorem",
                          "number": "Theorem 2.7", "title": "", "label": "thm:new",
                          "location": "toy.tex", "scope": "formal", "scope_note": "",
                          "scope_reviewed": True,
                          "clauses": [{"name": "statement", "spec": None}]})
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))

    run = _check(toy, "--json")
    assert run.stdout, run.stderr
    out = json.loads(run.stdout)
    claims = {c["id"]: c for c in out["claims"]}
    new = claims["T:thm:new"]
    assert new["status"] == "formal: open"
    assert new["semantic"]["declarations"] == 0
    assert new["semantic"]["review"] == "none"
    # Theorem 2.1, whose proposition an independent reviewer read, is the only one counted so.
    assert claims["T:thm:even-add"]["semantic"]["review"] == "independent"
    review = out["semantic"]["papers"]["T"]["review"]["statements"]
    assert review["independent"] == 1

    text = _check(toy).stdout
    assert "reviews: current, independent (1);" in text
    view = _check(toy, "--claim", "T:thm:new").stdout
    assert "    review: pending" in view and "review: reviewed" not in view

    # The reader's data: the clause's review rung and the claim's evidence summary.
    data = toy / ".machinechecked" / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    row = next(c for c in index["claims"] if c["id"] == "T:thm:new")
    assert [e["review"] for e in row["evidence_summary"]] == [{"state": "pending"}]
    assert row["semantic"]["review"] == "none"
    chunk = json.loads((data / "claims" / row["file"]).read_text())
    assert [cl["evidence"]["review"] for cl in chunk["clauses"]] == [{"state": "pending"}]
