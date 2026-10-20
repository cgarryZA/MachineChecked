"""Content retrieval (#126) on the synthetic corpus of tests/fixtures/retrieval: complete
statements, the reasons given for each result, users of a close match, the order of
quantifiers, the reader's identical search, the latency on 40,000 declarations, and the same
search through suggestions and `compare --query search`. No Lean session is involved."""

import json
import random
import sys
import time

import pytest

from conftest import ROOT
from prooflens import compare as cmp
from prooflens.retrieval import Retrieval, lean_quantifiers, paper_quantifiers, terms
from prooflens.simple import SuggestContext, suggest

FIX = ROOT / "tests" / "fixtures" / "retrieval"
sys.path.insert(0, str(FIX))
from corpus import CLAIMS, DECLS, large_index  # noqa: E402
import make_cases  # noqa: E402

THEOREMS = lambda k: k == "theorem"


def top(ret, text, n=3):
    res = ret.search(text, kinds=THEOREMS, limit=n, paper_order=paper_quantifiers(text))
    return res["results"]


def corpus_successes(ret):
    return sum(want in [r["name"] for r in top(ret, text)] for _, text, want in CLAIMS)


def test_the_reader_and_the_engine_answer_alike():
    # web/tests/retrieval.test.mjs runs the reader's search on these cases.
    assert json.loads((FIX / "cases.json").read_text(encoding="utf-8")) == \
        json.loads(json.dumps(make_cases.cases(), ensure_ascii=False, sort_keys=True)), \
        "tests/fixtures/retrieval/cases.json is out of date: run make_cases.py"


def test_the_corpus_is_retrieved_by_content(capsys):
    ret = Retrieval.build(DECLS)
    ok = corpus_successes(ret)
    with capsys.disabled():
        print(f"\nretrieval corpus: correct declaration in the top three for {ok} of "
              f"{len(CLAIMS)} claims")
    assert ok == len(CLAIMS)


def test_terms_unify_tex_lean_and_words():
    assert terms(r"$a \le b$, $\mathbb{R}$") == terms("a ≤ b, ℝ") == ["§≤", "§ℝ"]
    assert terms("x ≥ y") == terms("y ≤ x") == terms(r"$x \geq y$")
    assert "§ℕ" in terms("natural numbers") and "§ℕ" in terms("(n : Nat)")
    # A dotted name is a constant and the words of its last part; comments and tags vanish.
    assert terms("Nat.Prime p") == ["@Nat.Prime", "prime"]
    assert terms("% \\lean{Foo.bar}\n\\label{x} odd") == ["odd"]
    assert terms("sq_le_two_mul") == ["square", "§≤", "#2", "mul"]


def test_a_misleading_number_does_not_outrank_the_content():
    # The docstring of Ineq.amgm_two cites "Theorem 3.2"; the claim is numbered 2.4 here and a
    # distractor cites 2.4. Content decides; the citation is a lead, and says it may be stale.
    index = DECLS + [{"record": "index", "name": "Seq.cites", "kind": "theorem",
                      "module": "Seq", "range": {"line": 1}, "type": "∀ (a : ℕ), a = a",
                      "doc": "Theorem 2.4 of the paper.", "uses": [], "value_uses": []}]
    claim = {"id": "P:thm:amgm", "kind": "theorem", "number": "Theorem 2.4", "title": "",
             "label": "thm:amgm", "scope": "formal", "statement": CLAIMS[2][1]}
    out = suggest(claim, index)
    assert out[0]["name"] == "Ineq.amgm_two"
    assert out[0]["reasons"][0]["signal"] == "content"
    cites = next(s for s in out if s["name"] == "Seq.cites")
    assert any(r["signal"] == "number" for r in cites["reasons"])
    # With a pattern of stale numbers, the citation counts less and says why.
    drift = {"references": [], "pattern": {"drift": True}}
    out = suggest(claim, index, ctx=SuggestContext(index, numbering=drift))
    cites = next((s for s in out if s["name"] == "Seq.cites"), None)
    assert cites is None or "possibly stale" in cites["why"]


def test_no_citation_and_an_unrelated_name_still_rank_by_content():
    ret = Retrieval.build(DECLS)
    names = [r["name"] for r in top(ret, CLAIMS[1][1])]
    assert "Seq.aux7" in names
    r = next(r for r in top(ret, CLAIMS[1][1]) if r["name"] == "Seq.aux7")
    assert r["reasons"][0]["signal"] == "content" and "monotone" in r["reasons"][0]["terms"]


def test_a_wrapper_is_reached_through_the_helper_it_uses():
    ret = Retrieval.build(DECLS)
    res = ret.search("a uniform bound for derivatives of this inverse", limit=5)["results"]
    names = [r["name"] for r in res]
    assert names[:2] == ["Fn.deriv_inv_bound_aux", "Fn.main_estimate"]
    via = next(x for x in res[1]["reasons"] if x["signal"] == "uses")
    assert via["via"] == "Fn.deriv_inv_bound_aux" and via["relation"] == "value"
    assert via["text"] == "its proof uses Fn.deriv_inv_bound_aux, a close match"


def test_reversed_quantifiers_are_both_candidates_and_the_difference_is_kept():
    ret = Retrieval.build(DECLS)
    text = CLAIMS[9][1]                       # ∃ C, ∀ n
    res = {r["name"]: r for r in top(ret, text)}
    assert {"Unif.exists_const_forall", "Unif.forall_exists_const"} <= set(res)
    assert not any(x["signal"] == "structure" for x in res["Unif.exists_const_forall"]["reasons"])
    diff = next(x for x in res["Unif.forall_exists_const"]["reasons"] if x["signal"] == "structure")
    assert diff["paper"] == "∃∀" and diff["lean"] == "∀∃"
    assert lean_quantifiers("∀ {u : ℕ → ℝ}, Tendsto u → ∃ C, ∀ (n : ℕ), |u n| ≤ C") == "∀∃∀"
    assert lean_quantifiers("∀ (h : ∀ n, ∃ C, f n ≤ C), True") == "∀"
    # A suggestion is a candidate: none is linked, whatever its score.
    claim = {"id": "P:x", "kind": "theorem", "number": "Theorem 9", "title": "", "label": None,
             "scope": "formal", "statement": text}
    assert all("status" not in s for s in suggest(claim, DECLS))


def test_a_premise_after_4000_characters_is_searched():
    big_a = next(d for d in DECLS if d["name"] == "Long.big_a")
    assert big_a["type"].index("Summable") > 4000
    ret = Retrieval.build(DECLS)
    res = ret.search("summable", limit=3)["results"]
    assert [r["name"] for r in res] == ["Long.big_a"]
    assert res[0]["complete"] and res[0]["statement"] == big_a["type"]
    res = ret.search("integrable", limit=3)["results"]
    assert [r["name"] for r in res] == ["Long.big_b"]


def test_order_and_reasons_are_deterministic():
    ret1 = Retrieval.build(DECLS)
    shuffled = list(DECLS)
    random.Random(1).shuffle(shuffled)
    ret2 = Retrieval.build(shuffled)
    ret3 = Retrieval.from_export(json.loads(json.dumps(ret1.export())))
    for _, text, _ in CLAIMS:
        a, b, c = (r.search(text, limit=10, paper_order=paper_quantifiers(text))
                   for r in (ret1, ret2, ret3))
        assert a == b == c
    # Pages continue where the last ended.
    full = ret1.search("bound", limit=None)["results"]
    page1 = ret1.search("bound", limit=3)
    page2 = ret1.search("bound", limit=3, after=page1["page"]["next"])
    assert [r["name"] for r in page1["results"] + page2["results"]] == \
        [r["name"] for r in full[:6]]


def test_forty_thousand_declarations(capsys):
    index = large_index(40000)
    t0 = time.perf_counter()
    ret = Retrieval.build(index)
    built = time.perf_counter() - t0
    t0 = time.perf_counter()
    ok = corpus_successes(ret)
    per_query = (time.perf_counter() - t0) / len(CLAIMS)
    with capsys.disabled():
        print(f"\nretrieval at {len(ret)} declarations: top three for {ok} of {len(CLAIMS)}; "
              f"index built in {built:.1f} s, {per_query * 1000:.0f} ms per query")
    assert ok == len(CLAIMS)
    assert per_query < 2.0 and built < 120


def test_compare_searches_every_declaration_linked_or_not(tmp_path):
    from test_compare import write_site
    data = write_site(tmp_path)
    (data / "retrieval.json").write_text(json.dumps(Retrieval.build(DECLS).export()))
    site = cmp.Site(data)
    out = cmp.query(site, "search", "a monotone sequence bounded above converges", limit=3)
    assert out["available"] and out["results"][0]["name"] == "Seq.aux7"
    assert out["results"][0]["complete"] and out["scope"]["declarations"] == len(DECLS)
    assert "no Lean session" in out["provenance"]
    nxt = cmp.query(site, "search", "a monotone sequence bounded above converges", limit=3,
                    after=out["retrieval"]["next"])
    assert nxt["results"] and nxt["results"][0]["name"] not in [r["name"] for r in out["results"]]
    # A claim as the target searches with its printed statement, without its \lean tags.
    by_claim = cmp.query(site, "search", "thm:t3")
    assert by_claim["subject"]["claim"] == "S:thm:t3" and "\\lean" in by_claim["subject"]["text"]
    assert "@Syn.big_bound_" + "x" * 20 not in by_claim["query"]["terms"]
    # The linked declaration stays in the packet beside what the search found.
    pk = cmp.claim_packet(site, "thm:t3", "compare")
    assert pk["lean"]["declarations"][0]["name"].startswith("Syn.big_bound_")
    # `mentions` reads complete statements from the content index.
    m = cmp.query(site, "mentions", "Unif.f")
    assert {r["name"] for r in m["results"]} >= {"Unif.exists_const_forall",
                                                 "Unif.forall_exists_const"}
    assert all(r["complete"] for r in m["results"])


def test_compare_without_a_content_index_says_so(tmp_path):
    from test_compare import write_site
    site = cmp.Site(write_site(tmp_path))
    out = cmp.query(site, "search", "anything")
    assert out["available"] is False and "content index" in out["reason"]
