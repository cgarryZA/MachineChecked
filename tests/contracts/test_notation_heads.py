"""Derivative bounds and norms that differ only in what they range over stay distinct in the
computed hints (#538, part of #111), on the structure fixture's built data
(`web/tests/fixtures/structure/data`, no Lean).

The fixture's Definition 4 writes `J_x(D, k, C)`, `J_t(D, k, C)` and `J(D, k, C)` for the bounds
on the derivatives in space, in time and in all variables (`Shape.SpaceJet`, `Shape.TimeJet`,
`Shape.FullJet`), and `M_x(u, t, N)`, `M_t(u, x, N)` for the norms in space and in time
(`Shape.supSpace`, `Shape.supTime`). Theorem 32 (`Shape.full_jet_split`) and Theorem 33
(`Shape.norm_bounds`) use them. An alignment of the paper's notation with a whole declaration
matches them; an aligned paper expression that applies a notation is then compared with Lean's
application of a definition, and naming another definition gives a `head` hint. A hint is a
pointer: it changes no status.
"""

import shutil
from pathlib import Path

import pytest

from prooflens import estimates as est
from prooflens import expressions as ex
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "tests" / "fixtures" / "structure" / "data"
PAPER = ROOT / "tests" / "fixtures" / "structure" / "paper" / "main.tex"
WHO = rc.parse_reviewer("human:A-Auditor")
JETS, NORMS = "P:thm:jets", "P:thm:norms"
JET_DECL, NORM_DECL = "Shape.full_jet_split", "Shape.norm_bounds"
SPACE_AT = "/1/1/1/1/0/1"   # Shape.SpaceJet D k C, the first part of the conclusion
JETS_LINE = "If $J(D, k, C)$, then $J_x(D, k, C)$ and $J_t(D, k, C)$."
NORMS_LINE = r"If $M_x(u, t, N) \le C$ and $M_t(u, x, N) \le C$, then both bounds hold."


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    shutil.copytree(DATA, w / "site" / "data")
    (w / "sources" / "P").mkdir(parents=True)
    (w / "sources" / "P" / "main.tex").write_text(PAPER.read_text(encoding="utf-8"),
                                                  encoding="utf-8")
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def put(rec):
    return {"op": "put", "record": rec}


def line_of(work, text):
    src = (work / "sources" / "P" / "main.tex").read_text(encoding="utf-8").splitlines()
    return next(i for i, t in enumerate(src, 1) if text in t)


def region(line, end=None):
    return {"file": "main.tex", "start_line": line, **({"end_line": end} if end else {})}


def reading(work, claim, decl, variables, statement, notations):
    """For every variable (each aligned with Lean's of its name); the statement, governed by its
    line; the notations, governed by Definition 4, each aligned with its whole declaration."""
    c = claim.split(":")[-1]
    first = line_of(work, "Then $J_x(D, k, C)$ says")
    ops = [put({"id": f"{c}-v", "kind": "requirement", "claim": claim, "local_id": "v",
                "form": "for every", "binds": variables, "text": "for every " +
                ", ".join(variables)}),
           put({"id": f"{c}-s", "kind": "requirement", "claim": claim, "local_id": "v.s",
                "parent": "v", "form": "statement", "text": "the statement"}),
           put({"id": f"{c}-sp", "kind": "fragment", "claim": claim, "requirement": "v.s",
                "role": "statement", "region": region(line_of(work, statement))}),
           put({"id": f"{c}-n", "kind": "requirement", "claim": claim, "local_id": "n",
                "form": "definition", "text": "the notations of Definition 4"}),
           put({"id": f"{c}-np", "kind": "fragment", "claim": claim, "requirement": "n",
                "role": "definition", "region": region(first, first + 4)}),
           put({"id": f"{c}-av", "kind": "alignment", "claim": claim, "requirements": ["v"],
                "lean": [{"decl": decl, "var": v} for v in variables]})]
    for notation, target in notations.items():
        ops.append(put({"id": f"{c}-a-{notation}", "kind": "alignment", "claim": claim,
                        "requirements": ["n"], "expression": notation,
                        "lean": [{"decl": target}]}))
    return ops


def jets_reading(work, **more):
    return reading(work, JETS, JET_DECL, ["D", "k", "C"], JETS_LINE,
                   {"J_x": "Shape.SpaceJet", "J_t": "Shape.TimeJet", "J": "Shape.FullJet",
                    **more})


def norms_reading(work):
    return reading(work, NORMS, NORM_DECL, ["u", "t", "x", "N", "C"], NORMS_LINE,
                   {"M_x": "Shape.supSpace", "M_t": "Shape.supTime"})


def align(claim, aid, expression, **target):
    decl = JET_DECL if claim == JETS else NORM_DECL
    return put({"id": aid, "kind": "alignment", "claim": claim, "requirements": ["v.s"],
                "expression": expression, "lean": [{"decl": decl, **target}]})


def opened(work, ops):
    p = wsp.open_for(work, WHO, "informed", sources=snap_of(work).sources())
    wsp.update(p, ops, snap_of(work))
    return p


def hints(work, p, claim):
    b = wsp.view(wsp.read(p), snap_of(work))["claims"][claim]["reading"]["estimates"]
    return {h["alignment"]: h for h in b["hints"] if h.get("alignment")}


# -- the TeX reader ------------------------------------------------------------------------------

def test_a_notation_matched_with_a_definition_is_read_applied():
    node = ex.read_tex("J_x(D, k + 1, C)", {"J_x"})
    assert (node["k"], node["name"], node["tex"]) == ("apply", "J_x", "J_x")
    assert [a.get("name") or a.get("op") for a in node["args"]] == ["D", "add", "C"]
    assert ex.read_tex(r"2 J_x\left(D, k, C\right)", {"J_x"})["args"][1]["k"] == "apply"
    # Without a match it stays what it was: a function applied or a product.
    with pytest.raises(ex.Unsupported, match=r"J_x\(…\) may be a function applied"):
        ex.read_tex("J_x(D, k, C)")
    with pytest.raises(ex.Unsupported, match="brackets that do not match"):
        ex.read_tex("J_x(D, k, C", {"J_x"})


def test_the_same_definition_compares_its_arguments_and_another_differs_in_its_head():
    k = {"k": "type", "name": "nat"}
    lean = {"k": "apply", "name": "Shape.SpaceJet", "args": [
        {"k": "var", "var": 0, "name": "D"}, {"k": "var", "var": 1, "name": "k"},
        {"k": "var", "var": 2, "name": "C"}]}
    pairs, known = {"D": "v:0", "k": "v:1", "C": "v:2"}, {"v:0": "D", "v:1": "k", "v:2": "C"}
    heads = {"J_x": "Shape.SpaceJet", "J_t": "Shape.TimeJet"}
    assert ex.compare("J_x(D, k, C)", lean, pairs, known, heads)["outcome"] == "same"
    res = ex.compare("J_t(D, k, C)", lean, pairs, known, heads)
    assert (res["outcome"], res["kind"], res["feature"]) == ("differs", "head", "other")
    res = ex.compare("J_x(D, k + 1, C)", lean, pairs, known, heads)
    assert (res["kind"], res["difference"], res["argument"]) == \
        ("offset", "-1", {"index": 1, "paper_normal": "k + 1", "lean_normal": "k"})
    assert (res["paper_normal"], res["lean_normal"]) == \
        ("J_x(D, k + 1, C)", "Shape.SpaceJet(D, k, C)")
    # Two arguments that differ are other terms; another number of arguments, an ambiguous
    # notation and Lean arithmetic are not compared.
    res = ex.compare("J_x(D, k + 1, 2 C)", lean, pairs, known, heads)
    assert (res["kind"], res["arguments"]) == ("terms", [1, 2])
    assert "2 argument(s)" in ex.compare("J_x(D, k)", lean, pairs, known, heads)["reason"]
    res = ex.compare("J_x(D, k, C)", lean, pairs, known, {"J_x": ["Shape.SpaceJet", "Shape.X"]})
    assert res == {"outcome": "not compared", "reason": "the paper's J_x is aligned with more "
                   "than one declaration (Shape.SpaceJet, Shape.X)"}
    res = ex.compare("J_x(D, k, C)", {"k": "op", "op": "add", "in": k, "args": []}, pairs, known,
                     heads)
    assert res["reason"] == ("the paper's expression applies J_x, and Lean's is not an "
                             "application of a definition")


# -- hints on the structure fixture -------------------------------------------------------------

def test_a_paper_expression_naming_another_jet_bound_gives_a_head_hint(work):
    p = opened(work, jets_reading(work) + [align(JETS, "a-x", "J_x(D, k, C)", at=SPACE_AT),
                                           align(JETS, "a-t", "J_t(D, k, C)", at=SPACE_AT),
                                           align(JETS, "a-h", "J(D, k, C)", binder="h")])
    hs = hints(work, p, JETS)
    # The paper's J_x is Lean's SpaceJet, and J is the FullJet the hypothesis applies: no hint.
    assert "a-x" not in hs and "a-h" not in hs
    h = hs["a-t"]
    assert (h["kind"], h["feature"], h["basis"]) == ("head", "other", "computed hint")
    assert h["heads"] == {"paper": {"notation": "J_t", "decl": "Shape.TimeJet"},
                          "lean": "Shape.SpaceJet"}
    assert h["paper"] == {"text": "J_t(D, k, C)"} and h["lean"] == {"text": "Shape.SpaceJet D k C"}
    assert h["definition"] == {"name": "Shape.SpaceJet", "expansion": SPACE_AT + "=",
                               "expanded": "∀ (b : Nat), b ≤ k → ∀ (t x : Nat), D 0 b t x ≤ C"}
    assert h["text"] == (
        "The paper's J_t(D, k, C) and Lean's Shape.SpaceJet D k C apply different definitions: "
        "the paper's J_t is aligned with Shape.TimeJet, and Lean applies Shape.SpaceJet (in "
        "Shape.full_jet_split, where Shape.SpaceJet expands to ∀ (b : Nat), b ≤ k → "
        "∀ (t x : Nat), D 0 b t x ≤ C).")
    # The notations' own alignments name no expression of the Lean: they give no hint.
    assert not [k for k in hs if k.startswith("jets-a-")]


def test_a_norm_on_another_domain_gives_a_head_hint_through_the_relation(work):
    p = opened(work, norms_reading(work) + [
        align(NORMS, "a-s", "M_x(u, t, N)", binder="hs"),
        align(NORMS, "a-t", "M_t(u, x, N)", binder="hs"),
        align(NORMS, "a-u", "M_t(u, x, N)", binder="ht")])
    hs = hints(work, p, NORMS)
    assert "a-s" not in hs and "a-u" not in hs
    h = hs["a-t"]
    assert h["kind"] == "head" and h["heads"]["lean"] == "Shape.supSpace"
    assert h["lean"] == {"text": "Shape.supSpace u t N", "at": "/1/1/1/1/1/0/0/1"}
    assert h["definition"]["expanded"] == "Shape.maxUpTo (u t) N"


def test_a_difference_in_one_argument_of_the_same_definition_names_that_argument(work):
    f = work / "sources" / "P" / "main.tex"
    f.write_text(f.read_text(encoding="utf-8").replace(JETS_LINE, JETS_LINE.replace(
        "$J_x(D, k, C)$", "$J_x(D, k + 1, C)$")), encoding="utf-8")
    ops =reading(work, JETS, JET_DECL, ["D", "k", "C"], "If $J(D, k, C)$, then",
                  {"J_x": "Shape.SpaceJet"})
    p = opened(work, ops + [align(JETS, "a-x", "J_x(D, k + 1, C)", at=SPACE_AT)])
    h = hints(work, p, JETS)["a-x"]
    assert (h["kind"], h["feature"], h["difference"]) == ("offset", "index offset", "-1")
    assert h["argument"] == {"index": 1, "paper_normal": "k + 1", "lean_normal": "k",
                             "at": SPACE_AT + "/0/1"}
    assert h["definition"]["parameter"] == "k"
    assert h["text"].startswith(
        "The paper's J_x(D, k + 1, C) and Lean's Shape.SpaceJet D k C apply the same definition, "
        "and in one argument the paper's k + 1 and Lean's k differ by 1: Lean's is smaller (in "
        "Shape.full_jet_split, the argument k of Shape.SpaceJet, which expands to")


def test_a_notation_matched_with_nothing_or_two_definitions_is_not_compared(work):
    ops = jets_reading(work)
    p = opened(work, [o for o in ops if o["record"]["id"] != "jets-a-J_t"]
               + [align(JETS, "a-t", "J_t(D, k, C)", at=SPACE_AT)])
    h = hints(work, p, JETS)["a-t"]
    assert (h["kind"], h["reason"]) == (
        "not compared", "unsupported: J_t(…) may be a function applied or a product")
    # The same notation aligned with two declarations is matched with neither.
    wsp.update(p, [put({"id": "jets-a-J_t2", "kind": "alignment", "claim": JETS,
                        "requirements": ["n"], "expression": "J_t",
                        "lean": [{"decl": "Shape.FullJet"}]}),
                   put({"id": "jets-a-J_t", "kind": "alignment", "claim": JETS,
                        "requirements": ["n"], "expression": "J_t",
                        "lean": [{"decl": "Shape.TimeJet"}]})], snap_of(work))
    recs = list(wsp.read(p)["records"].values())
    assert est.notation_pairs(recs, snap_of(work))["J_t"] == \
        {"ambiguous": ["Shape.FullJet", "Shape.TimeJet"]}
    h = hints(work, p, JETS)["a-t"]
    assert h["reason"] == ("the paper's J_t is aligned with more than one declaration "
                           "(Shape.FullJet, Shape.TimeJet)")


def test_a_notation_out_of_date_matches_nothing(work):
    p = opened(work, jets_reading(work) + [align(JETS, "a-t", "J_t(D, k, C)", at=SPACE_AT)])
    assert hints(work, p, JETS)["a-t"]["kind"] == "head"
    # Definition 4 no longer prints J_t: its alignment is out of date and matches nothing.
    f = work / "sources" / "P" / "main.tex"
    src = f.read_text(encoding="utf-8")
    start = line_of(work, "Then $J_x(D, k, C)$ says")
    lines = src.splitlines()
    for i in range(start - 1, start + 4):
        lines[i] = lines[i].replace("J_t", "K_t")
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert "J_t" not in est.notation_pairs(list(wsp.read(p)["records"].values()), snap_of(work))


def test_a_head_hint_is_dismissed_and_changes_no_status(work):
    p = opened(work, jets_reading(work) + [align(JETS, "a-t", "J_t(D, k, C)", at=SPACE_AT)])
    status = snap_of(work).chunk(JETS)["status_code"]
    wsp.update(p, [put({"id": "f-d", "kind": "finding", "claim": JETS, "requirement": "v.s",
                        "difference": {"feature": "other", "paper": "J_t(D, k, C)",
                                       "lean": "Shape.SpaceJet D k C", "outcome": "difference",
                                       "hint": {"alignment": "a-t", "kind": "head"}},
                        "note": "the paper bounds time derivatives; Lean, space derivatives"})],
               snap_of(work))
    b = wsp.view(wsp.read(p), snap_of(work))["claims"][JETS]["reading"]["estimates"]
    assert "a-t" not in {h.get("alignment") for h in b["hints"]}
    [d] = [h for h in b["settled_hints"] if h.get("alignment") == "a-t"]
    assert (d["kind"], d["settled_by"]) == ("head", "f-d")
    assert snap_of(work).chunk(JETS)["status_code"] == status
