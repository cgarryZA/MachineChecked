"""#187: a definition claim counts as reviewed only through a reading of its own passage. A
definition in a statement's closure needs one review that read every passage that names it;
readings made separately do not combine, and the finding says so and where each was read. The
assessment says which marker each definition claim's state rests on, and a warning names a
review whose text names another claim and not the one it is counted for."""

from types import SimpleNamespace

from prooflens.assess import Assessor
from prooflens.reviews import Review

D2, D5 = "2" * 64, "5" * 64

# A synthetic structure of constants, fixed by two passages of the paper (Section 2 and
# Section 5), and a theorem whose statement uses it.
LEAN = {
    "specs": {"S.bench": {"fingerprint": "fp-spec", "errors": [], "binders": [],
                          "closure": ["S.paperConsts"], "consts": []}},
    "proofs": {"accept:S.bench_proof:S.bench": {"errors": [], "sorry": False, "axioms": []}},
    "decls": {"S.paperConsts": {"name": "S.paperConsts", "fingerprint": "fp-c", "uses": []},
              "S.bench": {"name": "S.bench", "fingerprint": "fp-spec", "uses": []}},
    "defs": {"S.paperConsts": {"closure": []}},
    "layering": []}


def defclaim(cid, number, sha):
    return {"id": cid, "paper": "X", "scope": "definition", "scope_reviewed": True,
            "number": number, "source_sha256": sha,
            "clauses": [{"name": "main", "defs": ["S.paperConsts"]}]}


CLAIMS = [defclaim("X:sec2:params", "Definition 2.1", D2),
          defclaim("X:sec5:consts", "Definition 5.1", D5),
          {"id": "X:thm:bench", "paper": "X", "scope": "formal", "scope_reviewed": True,
           "clauses": [{"name": "main", "spec": "S.bench", "accept": "S.bench_proof"}]}]


def mark(target, name, h, line, source, text="Read against the paper.", by="auditor"):
    return Review(target, name, h, by, "human", "self-declared", "r.md", line, text,
                  source=source)


def run(reviews):
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)
    out = Assessor(cfg, {"claims": CLAIMS}, LEAN, {}, reviews, []).run()
    return {c["id"]: c for c in out["claims"]}, out["findings"]


SPEC = mark("spec", "S.bench", "fp-spec", 1, {})


def test_separate_readings_count_for_their_own_claims_and_do_not_combine_in_a_closure():
    claims, findings = run([SPEC, mark("def", "S.paperConsts", "fp-c", 12,
                                       {"X:sec5:consts": D5}),
                            mark("def", "S.paperConsts", "fp-c", 40, {"X:sec2:params": D2})])
    assert claims["X:sec5:consts"]["status"] == "definition: reviewed"
    assert claims["X:sec2:params"]["status"] == "definition: reviewed"
    # Each rests on its own marker.
    for cid, line in (("X:sec5:consts", 12), ("X:sec2:params", 40)):
        r = claims[cid]["clauses"][0]["def_reviews"]["S.paperConsts"]
        assert r["rests_on"] == {"file": "r.md", "line": line, "by": "auditor",
                                 "passages": [cid]}
    # The theorem's closure asks for one reading of both passages: unchanged, it stays pending,
    # and the finding names where each passage was read.
    assert claims["X:thm:bench"]["status"] == "formal: proved, review pending"
    r = claims["X:thm:bench"]["clauses"][0]["def_reviews"]["S.paperConsts"]
    assert r["why"] == "source-unread" and r["split"] == {
        "X:sec2:params": [{"file": "r.md", "line": 40, "by": "auditor"}],
        "X:sec5:consts": [{"file": "r.md", "line": 12, "by": "auditor"}]}
    f, = [f for f in findings if f["code"] == "def-review" and f["subject"] == "X:thm:bench#0"]
    assert ("no single review read all the passages that name it, and a review must read them "
            "together: Definition 2.1 (X:sec2:params) read at r.md:40; Definition 5.1 "
            "(X:sec5:consts) read at r.md:12") in f["message"]
    # One reading of both passages is current for all three.
    claims, _ = run([SPEC, mark("def", "S.paperConsts", "fp-c", 60,
                                {"X:sec5:consts": D5, "X:sec2:params": D2})])
    assert {c: claims[c]["status"] for c in claims} == {
        "X:sec2:params": "definition: reviewed", "X:sec5:consts": "definition: reviewed",
        "X:thm:bench": "formal: accepted"}


def test_a_passage_nobody_read_keeps_the_old_message():
    claims, findings = run([SPEC, mark("def", "S.paperConsts", "fp-c", 12,
                                       {"X:sec5:consts": D5})])
    assert claims["X:sec2:params"]["status"] == "definition: review pending"
    r = claims["X:thm:bench"]["clauses"][0]["def_reviews"]["S.paperConsts"]
    assert r["why"] == "source-unread" and "split" not in r


def test_a_review_whose_text_names_another_claim_is_warned_about():
    text = "Definition 5.1 fixes a and b, and c = 4: the structure matches."
    _, findings = run([SPEC, mark("def", "S.paperConsts", "fp-c", 12,
                                  {"X:sec5:consts": D5, "X:sec2:params": D2}, text)])
    w = [f for f in findings if f["code"] == "def-review-other-claim"]
    assert [(f["tier"], f["subject"]) for f in w] == [("warning", "X:sec2:params#0")]
    assert ("Definition 2.1 (X:sec2:params) is reviewed through the review of S.paperConsts at "
            "r.md:12, whose text names Definition 5.1 (X:sec5:consts) and not this claim"
            ) in w[0]["message"]
    # A text that names both claims raises none.
    _, findings = run([SPEC, mark("def", "S.paperConsts", "fp-c", 12,
                                  {"X:sec5:consts": D5, "X:sec2:params": D2},
                                  text + " Definition 2.1 fixes T as well.")])
    assert not [f for f in findings if f["code"] == "def-review-other-claim"]
