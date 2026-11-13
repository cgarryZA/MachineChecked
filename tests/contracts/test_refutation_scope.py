"""The scope of a refutation (#653): the readings its counterexample is declared to cover and not
to cover, each covering theorem checked as a proof is; and, for a refutation scoped outside the
paper's standing assumptions, class lemmas showing the counterexample meets each assumption.
Only a proved lemma for every declared assumption makes it refute the printed claim; a lemma
holding up to an unproved identity, a failing one or none keeps it scoped."""

import json

from prooflens.assess import OUTSIDE, Assessor, refutation_scope, status_reason
from prooflens.review_queue import refutation_scope_text

from conftest import build, findings

PROVED = {"errors": [], "axioms": [], "type": {"text": "0 < 1"}}


def assessor(proofs: dict) -> Assessor:
    a = Assessor.__new__(Assessor)
    a.findings = []
    a.lean = {"proofs": {f"accept:{n}:": p for n, p in proofs.items()}}
    a.not_found = lambda n: f"{n} is not found"
    return a


def test_a_lemma_counts_only_when_declared_proved_and_proved():
    a = assessor({"Toy.c": PROVED, "Toy.d": PROVED, "Toy.bad": {"errors": ["axioms=[sorryAx]"]}})
    cl = {"standing_assumptions": ["complete", "right-continuous", "measurable", "bounded"],
          "class_lemmas": [
              {"assumption": "complete", "theorem": "Toy.c"},
              # Proved in Lean, but only under an identity Lean does not prove.
              {"assumption": "right-continuous", "theorem": "Toy.d", "state": "up-to-identity",
               "identity": "the natural filtration equals its augmentation"},
              {"assumption": "measurable", "theorem": "Toy.bad"}]}
    got = {l["assumption"]: l["state"] for l in a.class_lemmas("T:thm:1#0", cl)}
    assert got == {"complete": "proved", "right-continuous": "up-to-identity",
                   "measurable": "failed", "bounded": "not-addressed"}
    assert [f["code"] for f in a.findings] == ["class-lemma"]
    # No declared assumption: nothing is shown, so nothing can close the scope.
    assert a.class_lemmas("T:thm:1#0", {"class_lemmas": cl["class_lemmas"]}) == []


def test_a_covered_reading_is_checked_when_it_names_a_theorem():
    a = assessor({"Toy.f": PROVED})
    assert a._scope_theorem("s", "refutation-cover", {"move": "m"})["state"] == "declared"
    assert a._scope_theorem("s", "refutation-cover", {"move": "m", "theorem": "Toy.f"})[
        "state"] == "proved"
    out = a._scope_theorem("s", "refutation-cover", {"move": "m", "theorem": "Toy.gone"})
    assert out["state"] == "failed" and a.findings[0]["code"] == "refutation-cover"


def test_the_scope_is_shown_under_the_label():
    c = {"name": "main", "state": "refuted", "refute_ok": True, "spec": "Toy.main",
         "refutation_covers": [{"move": "∃ C after ∀ f", "theorem": "Toy.f", "state": "proved",
                                "type": {"text": "¬ ∀ T, ∀ f, ∃ C, ∀ n, P T f n C"}},
                               {"move": "C may depend on T", "state": "declared"}],
         "refutation_does_not_cover": ["∃ C after ∀ n"]}
    assert refutation_scope(c) == [
        "the refutation of “main” also covers ∃ C after ∀ f (proved by Toy.f); C may depend on "
        "T (declared, no theorem), and does not cover ∃ C after ∀ n"]
    assert status_reason([c]) == refutation_scope(c)
    assert refutation_scope_text(c)[-1] == "Toy.f : ¬ ∀ T, ∀ f, ∃ C, ∀ n, P T f n C"
    # A refutation that fails its checks has no scope to show.
    assert refutation_scope({**c, "refute_ok": False}) == []
    scoped = {"name": "main", "state": "refuted-outside", "refute_ok": True,
              "refute_scope": OUTSIDE, "class_lemmas": [
                  {"assumption": "complete", "theorem": "Toy.c", "state": "proved"},
                  {"assumption": "usual", "state": "up-to-identity", "identity": "a 0-1 law"},
                  {"assumption": "bounded", "state": "not-addressed"}]}
    assert refutation_scope(scoped) == [
        "the counterexample refuting “main” and the paper's standing assumptions: complete: "
        "proved by Toy.c; usual: holds only up to an identity not proved in Lean: a 0-1 law; "
        "bounded: not addressed"]
    assert "no standing assumption" in refutation_scope({**scoped, "class_lemmas": []})[0]


def test_the_scope_fields_are_checked():
    a = Assessor.__new__(Assessor)
    a.findings = []
    a.clause_relation_checks({"id": "T:thm:1", "clauses": [
        {"name": "ok", "refute": "Toy.no", "refute_scope": OUTSIDE,
         "standing_assumptions": ["complete"],
         "refutation_covers": [{"move": "m"}], "refutation_does_not_cover": ["n"],
         "class_lemmas": [{"assumption": "complete", "theorem": "Toy.c"}]},
        {"name": "no refutation", "refutation_does_not_cover": ["n"]},
        {"name": "not scoped", "refute": "Toy.no", "class_lemmas": [{"assumption": "a"}]},
        {"name": "lemmas", "refute": "Toy.no", "refute_scope": OUTSIDE,
         "standing_assumptions": ["a"], "class_lemmas": [
             {"assumption": "b", "theorem": "Toy.b"},
             {"assumption": "a", "state": "proved"},
             {"assumption": "a", "state": "up-to-identity"},
             {"assumption": "a", "state": "maybe"}]}]})
    msgs = [f["message"] for f in a.findings]
    assert all("'ok'" not in m for m in msgs)
    assert any("'no refutation' lists the readings" in m for m in msgs)
    # Not scoped, and its lemma's assumption is not declared.
    assert sum("'not scoped'" in m for m in msgs) == 2
    assert any("'b', which is not one of its standing_assumptions" in m for m in msgs)
    assert any("declared proved but names no theorem" in m for m in msgs)
    assert any("identity it does not name" in m for m in msgs)
    assert any("'maybe', which is not one of" in m for m in msgs)


def _clause_of(body, cid, name):
    c = next(c for c in body["assessment"]["claims"] if c["id"] == cid)
    return c, next(cl for cl in c["clauses"] if cl["name"] == name)


def test_class_lemmas_decide_whether_a_refutation_answers_the_printed_claim(toy):
    """The toy's refuted Proposition 2.3, its refutation scoped outside two declared standing
    assumptions: scoped while one holds only up to an identity, refuted as printed once both
    have proved class lemmas."""
    p = toy / "claims.json"
    inv = json.loads(p.read_text(encoding="utf-8"))
    claim = next(c for c in inv["claims"] if c["label"] == "prop:pred")
    cl = claim["clauses"][0]
    cl.update(refute_scope=OUTSIDE, standing_assumptions=["natural numbers", "positive"],
              refutation_covers=[{"move": "n chosen first", "theorem": "Toy.Acceptance.prop_pred"},
                                 {"move": "gone", "theorem": "Toy.Acceptance.no_such"}],
              refutation_does_not_cover=["n positive"],
              class_lemmas=[{"assumption": "natural numbers",
                             "theorem": "Toy.Acceptance.prop_pred_pos_hypotheses"},
                            {"assumption": "positive", "state": "up-to-identity",
                             "identity": "0 = 1"}])
    p.write_text(json.dumps(inv), encoding="utf-8")
    index, body, cfg = build(toy)
    c, got = _clause_of(body, claim["id"], cl["name"])
    assert got["state"] == "refuted-outside"
    # The review queue carries the author's account for step 3, with each theorem's statement.
    queue = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text(encoding="utf-8"))
    unit = next(u for u in queue["units"] if u["id"] == "spec:" + cl["spec"])
    lines = unit["refutation_scope"][0]["lines"]
    assert any(l.startswith("Toy.Acceptance.prop_pred_pos_hypotheses : ") for l in lines)
    assert c["status_code"].startswith("formal.open")
    assert [r["state"] for r in got["refutation_covers"]] == ["proved", "failed"]
    assert [l["state"] for l in got["class_lemmas"]] == ["proved", "up-to-identity"]
    assert [f["trigger"] for f in findings(body, "refutation-cover", claim["id"])] == \
        ["Toy.Acceptance.no_such"]
    assert any("does not cover n positive" in r for r in c["status_reason"])

    cl["class_lemmas"][1] = {"assumption": "positive",
                             "theorem": "Toy.Acceptance.prop_pred_pos_hypotheses"}
    p.write_text(json.dumps(inv), encoding="utf-8")
    index, body, _ = build(toy)
    c, got = _clause_of(body, claim["id"], cl["name"])
    assert got["state"] == "refuted"
    assert c["status_code"].startswith("formal.refuted")
