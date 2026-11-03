"""A difference of quantifier order or dependence between an aligned requirement and its Lean
statement is pointed out (#502, part of #111), on the structure fixture's built data (no Lean).

`Shape.bound_once` states `∃ C, ∀ n, n ≤ C * (n * n) + n`: one C for every n. `Shape.bound_each`
states `∀ n, ∃ C, …`: a C for each n, which may depend on n although its type `Nat` does not
mention n. The paper's reading of the claim gives the order in which its variables are chosen
(`estimates.obligation`); each hint is a computed pointer, as those of #500 are.
"""

import shutil
from pathlib import Path

import pytest

from prooflens import estimates as est
from prooflens import review_cli as rc
from prooflens import symbols
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "tests" / "fixtures" / "structure" / "data"
WHO = rc.parse_reviewer("human:A-Auditor")
OTHER = rc.parse_reviewer("human:B-Auditor")
CLAIM = "P:thm:bound-once"
ONCE, EACH = "Shape.bound_once", "Shape.bound_each"


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    shutil.copytree(DATA, w / "site" / "data")
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def put(rec):
    return {"op": "put", "record": {"claim": CLAIM, **rec}}


def req(lid, form, text, **kw):
    return put({"id": "r-" + lid, "kind": "requirement", "local_id": lid, "form": form,
                "text": text, **kw})


def align(aid, lid, decl, var):
    return put({"id": aid, "kind": "alignment", "requirements": [lid],
                "lean": [{"decl": decl, "var": var}]})


# One constant before every n: there is C; for every n; the bound.
ONE_C = [req("c", "there is", "a constant C", binds=["C"]),
         req("c.n", "for every", "for every n", binds=["n"], parent="c"),
         req("c.n.b", "conclusion", "n ≤ C n² + n", parent="c.n")]
# A constant for each n: for every n; there is C; the bound.
EACH_C = [req("n", "for every", "for every n", binds=["n"]),
          req("n.c", "there is", "such a constant", binds=["C"], parent="n"),
          req("n.c.b", "conclusion", "n ≤ C n² + n", parent="n.c")]


def hints_of(work, ops, claim=CLAIM, who=WHO):
    """The hints of a workspace of `who` with the records `ops`, apart from the hypotheses no
    requirement is aligned with."""
    p = wsp.open_for(work, who, "informed", sources=snap_of(work).sources())
    wsp.update(p, ops, snap_of(work))
    b = wsp.view(wsp.read(p), snap_of(work))["claims"][claim]["reading"]["estimates"]
    return p, [h for h in b["hints"] if h["kind"] != "unmatched hypothesis"], b


def test_the_lean_scope_is_read_off_the_tree():
    st = next(l for l in Snapshot(DATA).chunk(CLAIM)["links"] if l["name"] == EACH)["statement"]
    sc = symbols.scopes(st)
    assert {i: (s["op"], s["name"], s["scope"], s["after"]) for i, s in sc.items()} == \
        {0: ("forall", "n", "given", []), 1: ("exists", "C", "produced", [0])}
    # A record without `after` and `scope` has them from the nesting.
    bare = {"binders": [], "tree": {"op": "forall", "var": 0, "name": "n", "args": [
        {"op": "implies", "args": [{"op": "exists", "var": 1, "name": "y", "args": []},
                                   {"op": "exists", "var": 2, "name": "C", "args": []}]}]}}
    sc = symbols.scopes(bare)
    assert (sc[1]["scope"], sc[2]["scope"], sc[2]["after"]) == ("assumed", "produced", [0])


def test_one_constant_for_every_n_against_one_for_each_n(work):
    _, hs, _ = hints_of(work, ONE_C + [align("a-C", "c", EACH, "C"),
                                       align("a-n", "c.n", EACH, "n")])
    h, = hs
    assert (h["kind"], h["feature"], h["basis"], h["alignment"]) == \
        ("quantifier order", "quantifier order", "computed hint", "a-C")
    assert h["paper"] == {"text": "there is C; for every n", "order": ["C", "n"]}
    assert h["lean"] == {"text": "for every n; there is C"}
    # The witness may depend on n in the Lean because of where it stands, though its type
    # (`Nat`) does not mention n.
    assert h["dependence"] == {"paper": False, "lean": True}
    assert h["target"] == {"decl": EACH, "var": 1} and h["requirements"] == ["c", "c.n"]
    assert h["text"] == ("The paper chooses C before n, so C may not depend on n; in "
                         "Shape.bound_each, C is chosen after n and may depend on it, whatever "
                         "its type mentions.")
    assert [v["via"] for v in h["variables"]] == ["alignment a-C", "alignment a-n"]


def test_one_constant_for_each_n_against_one_for_every_n(work):
    _, hs, _ = hints_of(work, EACH_C + [align("a-C", "n.c", ONCE, "C"),
                                        align("a-n", "n", ONCE, "n")])
    h, = hs
    assert h["kind"] == "quantifier order" and h["dependence"] == {"paper": True, "lean": False}
    assert h["paper"]["text"] == "for every n; there is C"
    assert h["lean"]["text"] == "there is C; for every n"
    assert h["text"].endswith("Lean's C is one for every n.")


def test_agreeing_orders_give_no_hint(work):
    _, hs, _ = hints_of(work, ONE_C + [align("a-C", "c", ONCE, "C"),
                                       align("a-n", "c.n", ONCE, "n")])
    assert hs == []
    _, hs, _ = hints_of(work, EACH_C + [align("a-C", "n.c", EACH, "C"),
                                        align("a-n", "n", EACH, "n")], who=OTHER)
    assert hs == []


def test_a_domain_chosen_once_against_one_chosen_per_stage(work):
    """A domain D chosen once, before every stage k ("D does not depend on k"), against a Lean
    statement that chooses it per stage: Shape.bound_each read with k for n and D for C."""
    once = [req("k", "for every", "for every stage k", binds=["k"]),
            req("k.1", "conclusion", "the stage's estimate on D", parent="k"),
            req("d", "constant dependence", "the domain D is chosen once", binds=["D"],
                independent_of=["k"])]
    _, hs, _ = hints_of(work, once + [align("a-D", "d", EACH, "C"),
                                      align("a-k", "k", EACH, "n")])
    h, = hs
    assert (h["kind"], h["feature"]) == ("quantifier order", "constant dependence")
    assert h["paper"]["order"] == ["D", "k"] and h["lean"]["text"] == "for every n; there is C"
    assert "(stated independent of it)" in h["text"]
    _, hs, _ = hints_of(work, once + [align("a-D", "d", ONCE, "C"),
                                      align("a-k", "k", ONCE, "n")], who=OTHER)
    assert hs == []


def test_an_unaligned_variable_is_not_compared(work):
    _, hs, _ = hints_of(work, ONE_C + [align("a-n", "c.n", EACH, "n")])
    h, = hs
    assert (h["kind"], h["reason"]) == ("not compared",
                                        "the paper's C is aligned with no variable of "
                                        "Shape.bound_each")
    assert h["alignment"] == "a-n" and h["target"] == {"decl": EACH, "var": 0}
    assert h["paper"]["text"] == "there is C; for every n"
    assert h["lean"]["text"] == "(aligned with none); for every n"
    assert "feature" not in h


def test_a_constant_the_lean_takes_as_given_is_pointed_out(work):
    """The paper takes C as given where the Lean produces it."""
    given = [req("c", "for every", "for every C", binds=["C"]),
             req("c.1", "conclusion", "the bound", parent="c")]
    _, hs, _ = hints_of(work, given + [align("a-C", "c", ONCE, "C")])
    h, = hs
    assert (h["kind"], h["feature"]) == ("quantifier", "quantifier order")
    assert h["text"] == ("The paper takes C as given (for every C); Shape.bound_once produces C "
                         "(there is C).")


def test_an_order_hint_is_dismissed_with_its_reason_and_changes_no_status(work):
    status = snap_of(work).chunk(CLAIM)["status_code"]
    p, hs, _ = hints_of(work, ONE_C + [align("a-C", "c", EACH, "C"),
                                       align("a-n", "c.n", EACH, "n")])
    wsp.update(p, [put({"id": "f-d", "kind": "finding", "requirement": "c",
                        "difference": {"feature": "quantifier order", "paper": "∃ C ∀ n",
                                       "lean": "∀ n ∃ C", "outcome": "difference",
                                       "hint": {"alignment": "a-C",
                                                "kind": "quantifier order"}},
                        "note": "the Lean's constant may depend on n"})], snap_of(work))
    b = wsp.view(wsp.read(p), snap_of(work))["claims"][CLAIM]["reading"]["estimates"]
    assert [h for h in b["hints"] if h["kind"] != "unmatched hypothesis"] == []
    d, = b["settled_hints"]
    assert d["kind"] == "quantifier order" and d["settled"]["outcome"] == "difference"
    assert d["settled"]["why"] == "the Lean's constant may depend on n"
    assert snap_of(work).chunk(CLAIM)["status_code"] == status
    # It is listed per claim, attributed, as `check --json` gives it.
    hints = est.workspace_hints(work, work / "site" / "data")
    assert [h["kind"] for h in hints[CLAIM]["dismissed"]] == ["quantifier order"]
