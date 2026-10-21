"""#203: a passage whose manuscript text no longer matches its pin is unread. Every review that
read it stops counting, and the claim reads "review pending" with a reason naming the passage,
until the passage is pinned again and a reading is recorded at the new pin."""

import json
from types import SimpleNamespace

from conftest import build, edit, findings, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens import promote as pr
from prooflens.assess import Assessor
from prooflens.reviews import Review

from test_promote import report, queue

EVEN_ADD = "If $a$ and $b$ are even natural numbers, then $a + b$ is even."
CHANGED = "If $a$ and $b$ are even natural numbers, then $a + b$ is even and so is $a b$."
SPEC = "Toy.PaperSpec.thm_even_add"

# A synthetic claim pinned at two passages: its own, and the definition of a macro.
FP = "synthetic-fingerprint"
PIN, PART, NEW, NEW_PART = "a" * 64, "1" * 64, "9" * 64, "2" * 64


def synthetic(pin=PIN, part=PART):
    claim = {"id": "P:est", "paper": "P", "scope": "formal", "scope_reviewed": True,
             "location": "main.tex:10", "source_region": {"end_line": 11},
             "source_hash_scheme": "tex-regions-v1", "source_sha256": pin,
             "source_line_sha256": ["l1", "l2"],
             "source_parts": [{"location": "values.tex:2", "macro": "\\iterCount",
                               "sha256": part, "line_sha256": ["m1"]}],
             "clauses": [{"name": "main", "spec": "S.spec", "accept": "S.accept"}]}
    return {"claims": [claim]}


def tex(sha, part, mode="latex"):
    return {"P": {"mode": mode, "anchors": [], "envs": [], "regions": {"P:est": {
        "scheme": "tex-regions-v1", "sha256": sha, "passage_sha256": "p" * 64,
        "file": "main.tex", "start_line": 10, "end_line": 11, "line_sha256": ["l1", "l2"],
        "parts": [{"file": "values.tex", "start_line": 2, "macro": "\\iterCount",
                   "sha256": part, "line_sha256": ["m1" if part == PART else "m2"]}]}}}}


def run(inv, evidence, read):
    lean = {"specs": {"S.spec": {"fingerprint": FP, "errors": [], "closure": [], "binders": [],
                                 "consts": []}},
            "proofs": {"accept:S.accept:S.spec": {"errors": [], "sorry": False, "axioms": []}},
            "decls": {}, "defs": {}, "layering": []}
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)
    r = Review("spec", "S.spec", FP, "a-referee", "human", "self-declared", "r.md", 1,
               "Synthetic review.", source={"P:est": read})
    return Assessor(cfg, inv, lean, evidence, [r], []).run()


def test_a_changed_further_passage_reopens_the_review_until_repinned_and_read():
    # Pinned and matching: the reading counts.
    out = run(synthetic(), tex(PIN, PART), PIN)
    assert out["claims"][0]["status"] == "formal: accepted"

    # The macro definition changes; the inventory still pins the earlier text.
    out = run(synthetic(), tex(NEW, NEW_PART), PIN)
    c = out["claims"][0]
    assert c["status"] == "formal: proved, review pending"
    sr = c["clauses"][0]["spec_review"]
    assert sr["state"] == "stale" and sr["why"] == "source-unpinned"
    assert sr["source_claim"] == "P:est" and not sr["current"]
    blocker = next(b for b in c["blockers"] if "no longer matches the pin" in b)
    assert "part 1 (the definition of \\iterCount) (line 2 of values.tex) changed" in blocker
    f = next(f for f in out["findings"] if f["code"] == "spec-review")
    assert f["reason"] == "source-unpinned" and "pin the passage again" in f["message"]
    assert any(f["code"] == "source-changed" for f in out["findings"])

    # A reading recorded at the manuscript's digest does not count while the pin is stale.
    out = run(synthetic(), tex(NEW, NEW_PART), NEW)
    assert out["claims"][0]["status"] == "formal: proved, review pending"

    # Pinned again: the reading of the earlier text is stale; a reading at the new pin counts.
    inv = synthetic(NEW, NEW_PART)
    out = run(inv, tex(NEW, NEW_PART), PIN)
    c = out["claims"][0]
    assert c["status"] == "formal: proved, review pending"
    assert c["clauses"][0]["spec_review"]["why"] == "source-changed"
    assert run(inv, tex(NEW, NEW_PART), NEW)["claims"][0]["status"] == "formal: accepted"


def test_a_paper_read_from_its_pdf_has_no_source_check_and_keeps_the_reading():
    out = run(synthetic(), tex(NEW, NEW_PART, mode="pdf"), PIN)
    assert out["claims"][0]["status"] == "formal: accepted"


@needs_lean
@needs_tex
def test_toy_an_edit_without_a_repin_reads_review_pending_until_repinned_and_read(toy):
    index, body, cfg = build(toy)
    assert status(index, "T:thm:even-add") == "formal: accepted"

    # The statement is edited and the inventory is not repinned.
    edit(toy / "paper/toy.tex", EVEN_ADD, CHANGED)
    index, body, _ = build(toy, reuse_lean=True)
    assert findings(body, "source-changed", "T:thm:even-add")
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    row = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
    sr = row["clauses"][0]["spec_review"]
    assert sr["why"] == "source-unpinned" and sr["source_claim"] == "T:thm:even-add"
    assert any("no longer matches the pin of Theorem 2.1 (T:thm:even-add)" in b
               for b in row["blockers"])
    f, = findings(body, "spec-review", "T:thm:even-add")
    assert f["reason"] == "source-unpinned"
    # Passages that did not change keep their reviews; nothing is raised.
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"
    assert status(index, "T:def:even") == "definition: author-reviewed"

    # A report on the unpinned passage is refused.
    unit = next(u for u in queue(cfg)["units"] if u["name"] == SPEC)
    (_, _, why), = pr.plan(cfg, [report(index, unit)])
    assert any("no longer matches the pin of T:thm:even-add" in w for w in why)

    # Repinned to the text the paper prints: the old reading is stale, not current.
    anchor = next(a for a in body["tex"]["T"]["anchors"] if a.get("label") == "thm:even-add")
    inv = json.loads((toy / "claims.json").read_text())
    next(c for c in inv["claims"] if c["id"] == "T:thm:even-add")["source_sha256"] = \
        anchor["source_sha256"]
    (toy / "claims.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False) + "\n")
    index, body, cfg = build(toy, reuse_lean=True)
    assert not findings(body, "source-changed")
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    sr = next(c for c in body["assessment"]["claims"]
              if c["id"] == "T:thm:even-add")["clauses"][0]["spec_review"]
    assert sr["why"] == "source-changed"

    # A reading recorded at the new pin restores the status.
    unit = next(u for u in queue(cfgmod.load(toy / "machinechecked.toml"))["units"]
                if u["name"] == SPEC)
    steps = pr.plan(cfg, [report(index, unit)])
    assert all(not why for _, _, why in steps)
    pr.apply(cfg, [(r, cur) for r, cur, _ in steps])
    index, _, _ = build(toy, reuse_lean=True)
    assert status(index, "T:thm:even-add") == "formal: accepted"
