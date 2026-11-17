"""A structure reviewed as one unit, end to end on the toy paper (#610): `Toy.Pair` with its
generated `Toy.Pair.mk`, `Toy.Pair.x` and `Toy.Pair.y` is one unit of the queue, whose step 2
carries the structure's authored source and its fields' docstrings; one report, archived once,
promotes a marker for each of the four, and the assessment then finds each reviewed."""

import json

from conftest import build, edit, needs_lean, needs_tex
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens.pipeline import reassess
from test_promote import CHECKER

S, MK, X, Y = "Toy.Pair", "Toy.Pair.mk", "Toy.Pair.x", "Toy.Pair.y"
WHO = "human:Pair-Referee"
READING = "Two even numbers add to an even number: the sum of the pair's coordinates is even."


def with_pair(toy):
    """The toy paper with Theorem 2.1 stated of the coordinates of a pair."""
    edit(toy / "lean/Toy/Defs.lean", "end Toy",
         "/-- A pair of natural numbers. -/\nstructure Pair where\n"
         "  /-- The first coordinate. -/\n  x : Nat\n"
         "  /-- The second coordinate. -/\n  y : Nat\n\nend Toy")
    edit(toy / "lean/Toy/PaperSpec.lean",
         "∀ a b : Nat, IsEven a → IsEven b → IsEven (a + b)",
         "∀ p : Pair, IsEven p.x → IsEven p.y → IsEven (p.x + p.y)")
    edit(toy / "lean/Toy/Acceptance.lean",
         "  rintro a b ⟨j, rfl⟩ ⟨k, rfl⟩\n  exact ⟨j + k, by omega⟩",
         "  intro p ⟨j, hj⟩ ⟨k, hk⟩\n  exact ⟨j + k, by omega⟩")


@needs_lean
@needs_tex
def test_a_structure_is_reviewed_and_promoted_as_one_unit(toy):
    with_pair(toy)
    _, _, cfg = build(toy)
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text(encoding="utf-8"))
    ids = {u["id"] for u in q["units"]}
    assert "def:" + S in ids and not ids & {"def:" + n for n in (MK, X, Y)}
    uid = "def:" + S

    s = rc.Session(cfg, rc.parse_reviewer(WHO))
    s.read(uid)
    s.lock(uid, READING)
    pk = s.show(uid, as_json=True)
    (d,) = [d for d in pk["lean"]["declarations"] if d["name"] == S]
    assert "structure Pair where" in d["lean_source"]["text"]
    assert {f["field"]: (f.get("doc") or "").strip() for f in d["structure"]["fields"]} == {
        "x": "The first coordinate.", "y": "The second coordinate."}
    s.decide(uid, "faithful", "The pair's two coordinates, natural numbers, as in the paper.")
    s.author(uid)
    r = s.submit(uid, "none")
    assert r["unit"]["lean"] == [S, MK, X, Y]

    (step,) = pr.plan(cfg, [r])
    _, cur, why = step
    assert why == []
    done = pr.apply(cfg, [(r, cur)])
    assert [x["name"] for x in done] == [S, MK, X, Y]
    text = (toy / "reviews/definitions.md").read_text(encoding="utf-8")
    assert {m.group(2) for m in CHECKER.finditer(text) if m.group(4) == WHO} == {S, MK, X, Y}
    # One canonical record covering the four, not four archives.
    assert len(list((toy / "reviews/reports").iterdir())) == 1
    assert len(list((toy / "reviews/reports").glob("*.json"))) == 1

    res = reassess(cfg, log=lambda *a: None)
    claim = next(c for c in json.loads(
        (cfg.out_dir / "site/data/index.json").read_text(encoding="utf-8"))["claims"]
        if c["id"] == "T:thm:even-add")
    chunk = json.loads((cfg.out_dir / "site/data/claims" / claim["file"]).read_text(
        encoding="utf-8"))
    states = {n: r["state"] for cl in chunk["clauses"] for n, r in
              (cl.get("def_reviews") or {}).items()}
    assert all(states[n] == "reviewed" for n in (S, MK, X, Y)), states
    assert res["index"]
