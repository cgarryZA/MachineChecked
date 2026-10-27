"""Content retrieval (#126) on the synthetic corpus of tests/fixtures/retrieval: complete
statements, the reasons given for each result, users of a close match, the order of
quantifiers, searches from a declaration (the hypotheses, conclusion and variables of each
result compared with its), the reader's identical search, the latency on 40,000 declarations,
and the same search through suggestions and `compare --query search`. No Lean session is
involved."""

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


# -- searches from a declaration -------------------------------------------------------------------

def reasons(r, signal=None):
    return [x for x in r["reasons"] if signal is None or x["signal"] == signal]


def test_a_search_from_a_helper_reaches_its_generic_wrapper():
    ret = Retrieval.build(DECLS)
    res = ret.search_like("Fn.deriv_inv_bound_aux", limit=3)["results"]
    top = res[0]
    assert top["name"] == "Fn.main_estimate"
    assert "Fn.deriv_inv_bound_aux" not in [r["name"] for r in res]
    texts = [x["text"] for x in top["reasons"]]
    assert "its proof uses Fn.deriv_inv_bound_aux, the declaration searched from" in texts
    assert "the same hypotheses as Fn.deriv_inv_bound_aux" in texts
    assert "a different conclusion from Fn.deriv_inv_bound_aux's" in texts
    assert "it also binds variables of type ℕ, which Fn.deriv_inv_bound_aux does not" in texts


def test_alternatives_with_fewer_hypotheses_or_another_domain_come_first():
    ret = Retrieval.build(DECLS)
    res = ret.search_like("Ineq.triangle_abs_of_nonneg", limit=5)["results"]
    assert [r["name"] for r in res[:2]] == ["Ineq.triangle_abs", "Ineq.triangle_abs_int"]
    for r in res[:2]:
        # The same conclusion lifts a result half way to 1; its content score is kept apart.
        assert r["score"] == round((1 + r["content"]) / 2, 6) or r["score"] > r["content"]
        fewer = next(x for x in reasons(r, "structure") if x["aspect"] == "fewer hypotheses")
        assert fewer["hypotheses"] == ["0 ≤ a", "0 ≤ b"]
        assert fewer["text"] == ("it does not assume 0 ≤ a and 0 ≤ b, which "
                                 "Ineq.triangle_abs_of_nonneg assumes")
        assert any(x["text"] == "the same conclusion as Ineq.triangle_abs_of_nonneg"
                   for x in reasons(r, "structure"))
    # Variables named differently are matched; their types are compared.
    dom = next(x for x in reasons(res[1], "structure") if x["aspect"] == "variables")
    assert dom["here"] == ["ℤ", "ℤ"] and dom["there"] == ["ℝ", "ℝ"]
    assert dom["text"] == "it binds variables of type ℤ where Ineq.triangle_abs_of_nonneg binds ℝ"
    # From the general statement, the special one says what it also assumes.
    back = ret.search_like("Ineq.triangle_abs", limit=3)["results"][0]
    assert back["name"] == "Ineq.triangle_abs_of_nonneg"
    assert any(x["text"] == "it also assumes 0 ≤ a and 0 ≤ b, which Ineq.triangle_abs does not"
               for x in reasons(back, "structure"))
    # A result is a candidate: nothing is linked or decided.
    assert all("status" not in r and "link" not in r for r in res)


def test_a_restatement_with_renamed_variables_and_reordered_hypotheses_is_recognised():
    ret = Retrieval.build(DECLS)
    top = ret.search_like("Ineq.amgm_two", limit=3)["results"][0]
    assert top["name"] == "Ineq.amgm_two'"
    assert [x["aspect"] for x in reasons(top, "structure")] == ["same"]
    assert reasons(top, "structure")[0]["text"] == \
        "the same hypotheses and conclusion as Ineq.amgm_two, as printed"


def test_reversed_quantifiers_are_kept_in_a_search_from_a_declaration():
    ret = Retrieval.build(DECLS)
    for name, other, searched, lean in (
            ("Unif.exists_const_forall", "Unif.forall_exists_const", "∃∀", "∀∃"),
            ("Unif.forall_exists_const", "Unif.exists_const_forall", "∀∃", "∃∀")):
        r = ret.search_like(name, limit=2)["results"][0]
        assert r["name"] == other
        q = next(x for x in reasons(r, "structure") if x.get("aspect") == "quantifiers")
        assert (q["searched"], q["lean"]) == (searched, lean)
        assert q["text"].startswith(f"the quantifiers come in a different order ({name}: ")


def test_a_definition_searches_definitions_without_comparing_hypotheses():
    ret = Retrieval.build(DECLS)
    res = ret.search_like("Num.IsPerfect")["results"]
    assert res and all(r["kind"] != "theorem" for r in res)
    assert not any(reasons(r, "structure") for r in res)
    with pytest.raises(KeyError):
        ret.search_like("No.such")


def test_the_parts_of_a_printed_statement():
    from prooflens.retrieval import lean_shape
    sh = lean_shape("∀ ε > 0, ∃ δ > 0, ∀ (x : ℝ), |x| < δ → |f x| < ε")
    assert sh == {"binders": [("ε", "")], "premises": ["ε > 0"],
                  "conclusion": "∃ δ > 0, ∀ (x : ℝ), |x| < δ → |f x| < ε"}
    sh = lean_shape("∀ {α : Type u_1} [inst : LinearOrder α] (a b : α), a ≤ b → b ≤ a → a = b")
    assert sh["binders"] == [("α", "Type u_1"), ("a", "α"), ("b", "α")]
    assert sh["premises"] == ["LinearOrder α", "a ≤ b", "b ≤ a"] and sh["conclusion"] == "a = b"
    # Line breaks as Lean prints a long statement, and a hypothesis in brackets.
    sh = lean_shape("∀ (u : ℕ → ℝ),\n    Monotone u →\n      (u 0) ≤ 1 → ∃ L, L = 1")
    assert sh["premises"] == ["Monotone u", "(u 0) ≤ 1"] and sh["conclusion"] == "∃ L, L = 1"
    # Every hypothesis of a statement over 4000 characters, not only the first ones.
    big = lean_shape(next(d for d in DECLS if d["name"] == "Long.big_a")["type"])
    assert len(big["premises"]) == 701 and big["premises"][-1] == "Summable g"


def test_a_reason_says_which_shared_terms_are_in_the_conclusion():
    ret = Retrieval.build(DECLS)
    res = {r["name"]: r for r in top(ret, CLAIMS[1][1])}
    # The paper concludes convergence: Seq.aux7 concludes it, the converse assumes it.
    assert reasons(res["Seq.aux7"], "content")[0]["conclusion"] == ["limit"]
    other = reasons(res["Seq.bounded_of_tendsto"], "content")[0]
    assert other["conclusion"] == [] and other["text"].endswith("; its conclusion has none of them")


def test_absolute_values_are_a_term_and_lambdas_are_not_comparisons():
    assert "§|" in terms("|a + b| ≤ |a| + |b|")
    assert "§|" in terms("the absolute value") and "§|" in terms(r"$\lvert x \rvert$")
    assert "§|" in terms("abs_add")
    assert terms("fun y => y⁻¹") == ["§^"]


def test_declarations_lean_generates_are_left_out():
    from corpus import decl
    index = DECLS + [
        decl("Gen.T", "Type", kind="inductive"),
        decl("Gen.T.casesOn", "{motive : Gen.T → Sort u} → (t : Gen.T) → motive t", kind="def"),
        decl("Gen.T.mk.injEq", "∀ (a b : ℕ), (Gen.T.mk a = Gen.T.mk b) = (a = b)"),
        decl("Gen.«term_⊕_»", "TrailingParserDescr", kind="def"),
        # Not an inductive type's: kept.
        decl("Gen.other.casesOn", "∀ (n : ℕ), n = n"),
    ]
    names = {d["name"] for d in Retrieval.build(index).docs}
    assert {"Gen.T", "Gen.other.casesOn"} <= names
    assert not names & {"Gen.T.casesOn", "Gen.T.mk.injEq", "Gen.«term_⊕_»"}


def test_a_search_from_a_declaration_among_forty_thousand(capsys):
    ret = Retrieval.build(large_index(40000))
    t0 = time.perf_counter()
    first = ret.search_like("Ineq.triangle_abs", limit=5)["results"]
    t_first = time.perf_counter() - t0
    t0 = time.perf_counter()
    ret.search_like("Ineq.amgm_two", limit=5)
    t_next = time.perf_counter() - t0
    with capsys.disabled():
        print(f"\nsearch from a declaration at {len(ret)} declarations: {t_first:.2f} s the first "
              f"time (reading every statement's parts), {t_next:.2f} s after")
    assert [r["name"] for r in first[:2]] == ["Ineq.triangle_abs_of_nonneg",
                                              "Ineq.triangle_abs_int"]
    assert t_first < 20 and t_next < 5


def test_compare_searches_from_a_declaration(tmp_path):
    from test_compare import write_site
    data = write_site(tmp_path)
    (data / "retrieval.json").write_text(json.dumps(Retrieval.build(DECLS).export()))
    site = cmp.Site(data)
    out = cmp.query(site, "search", "Ineq.triangle_abs_of_nonneg", limit=2)
    sub = out["subject"]
    assert sub["declaration"] == "Ineq.triangle_abs_of_nonneg" and sub["kinds"] == "theorems"
    assert sub["statement"].startswith("∀ (a b : ℝ), 0 ≤ a") and sub["complete"]
    assert "a question for review" in sub["note"]
    assert [r["name"] for r in out["results"]] == ["Ineq.triangle_abs", "Ineq.triangle_abs_int"]
    assert out["retrieval"]["next"] == "Ineq.triangle_abs_int"
    text = cmp.search_text(out)
    assert text.startswith("Declarations (theorems) like Ineq.triangle_abs_of_nonneg, among ")
    assert "it does not assume 0 ≤ a and 0 ≤ b" in text
