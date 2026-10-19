"""Requirements on the toy paper's full assessment (#99): Definition 1.1's two sentences align
separately with its two Lean definitions; Proposition 2.3's correction adds `0 < n` beside the
printed sentence; Theorem 2.5's constant is chosen before n; and none of it changes a status."""

import json

from conftest import build, needs_lean, needs_tex, status

from prooflens import compare as cmp
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")


def put(rec):
    return {"op": "put", "record": rec}


@needs_lean
@needs_tex
def test_toy_requirements_align_with_its_lean_and_change_no_status(toy):
    index, _, cfg = build(toy)
    statuses = {c["id"]: c["status"] for c in index["claims"]}
    data = cfg.out_dir / "site" / "data"
    snap = Snapshot(data)
    tex = (cfg.out_dir / "sources" / "T" / "toy.tex").read_text(encoding="utf-8").splitlines()
    line = next(i for i, t in enumerate(tex, 1) if t.startswith("A natural number $n$ is"))
    cut = tex[line - 1].index("The") + 1
    p = wsp.open_for(cfg.out_dir, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        # Definition 1.1: one requirement per sentence, each with its exact source.
        put({"kind": "requirement", "claim": "Definition 1.1", "local_id": "even",
             "form": "definition", "text": "n is even if n = 2k for some natural k"}),
        put({"kind": "fragment", "claim": "Definition 1.1", "requirement": "even",
             "role": "statement", "region": {"file": "toy.tex", "start_line": line,
                                             "end_line": line, "end_column": cut}}),
        put({"kind": "requirement", "claim": "Definition 1.1", "local_id": "tri",
             "form": "definition", "text": "T_n = 0 + 1 + ... + n"}),
        put({"kind": "fragment", "claim": "Definition 1.1", "requirement": "tri",
             "role": "statement", "region": {"file": "toy.tex", "start_line": line,
                                             "start_column": cut, "end_line": line + 1}}),
        put({"kind": "alignment", "claim": "Definition 1.1", "requirements": ["even"],
             "lean": [{"decl": "Toy.IsEven"}]}),
        put({"kind": "alignment", "claim": "Definition 1.1", "requirements": ["tri"],
             "relation": "alternative representation", "lean": [{"decl": "Toy.triangle"}],
             "note": "a recursion instead of the sum"}),
        # Proposition 2.3: the printed sentence stays; the correction adds 0 < n.
        put({"kind": "requirement", "claim": "Proposition 2.3", "local_id": "r1",
             "form": "for every", "binds": ["n"], "text": "every natural number n"}),
        put({"kind": "fragment", "claim": "Proposition 2.3", "requirement": "r1",
             "role": "statement", "passage": {"claim": "Proposition 2.3"}}),
        put({"kind": "requirement", "claim": "Proposition 2.3", "local_id": "r1c",
             "form": "condition", "text": "0 < n", "origin": "correction", "corrects": "r1"}),
        put({"kind": "fragment", "claim": "Proposition 2.3", "requirement": "r1c",
             "role": "proposed correction", "passage": {"claim": "Remark 2.4"}}),
        put({"kind": "alignment", "claim": "Proposition 2.3", "requirements": ["r1c"],
             "lean": [{"decl": "Toy.PaperSpec.prop_pred_pos", "binder": "h1"}]}),
        # Theorem 2.5: one C before every n.
        put({"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c", "form": "there is",
             "binds": ["C"], "independent_of": ["n"], "text": "a constant C"}),
        put({"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c.1", "parent": "c",
             "form": "for every", "binds": ["n"], "text": "for every natural number n"}),
        put({"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c.1.1",
             "parent": "c.1", "form": "conclusion", "text": "T_n ≤ C n²"}),
        put({"kind": "alignment", "claim": "Theorem 2.5", "requirements": ["c.1.1"],
             "lean": [{"decl": "Toy.PaperSpec.thm_bound", "conclusion": True}]}),
    ], snap)
    v = wsp.view(wsp.read(p), snap)
    d = v["claims"]["T:def:even"]["reading"]
    texts = {r["local_id"]: r["fragments"]["governing"][0]["region"]["text"]
             for r in d["requirements"]}
    assert texts["even"].endswith("for some natural number $k$. ")
    assert texts["tri"].startswith("The\n") and "\\emph{triangular number}" in texts["tri"]
    assert {a["requirements"][0]: a["lean"][0]["decl"] for a in d["alignments"]} == \
        {"even": "Toy.IsEven", "tri": "Toy.triangle"}
    assert all(a["lean"][0]["fingerprint"] for a in d["alignments"])
    pr = v["claims"]["T:prop:pred"]["reading"]
    corr = next(r for r in pr["requirements"] if r["local_id"] == "r1c")
    assert corr["origin"] == "correction" and corr["corrects"] == "r1"
    assert pr["alignments"][0]["lean"][0]["target"] == "h1 : 0 < n"
    printed = next(r for r in pr["requirements"] if r["local_id"] == "r1")
    assert printed["fragments"]["governing"][0]["passage"]["claim"] == "T:prop:pred"
    bd = v["claims"]["T:thm:bound"]["reading"]
    assert [(w["binds"], w["before"]) for w in bd["witnesses"]] == [(["C"], ["n"])]
    assert all(r["currency"]["state"] == "current"
               for c in v["claims"].values() for r in c["reading"]["requirements"])
    # A proof step is a target of its own: Equation (3)'s quantifier is suggested from its
    # passage, and the proof's later choice k = 1 stays a use.
    from prooflens import requirements as rq
    step = "T:eq:bound-range"
    wsp.update(p, [put({"kind": "requirement", "claim": "Equation (3)", "local_id": "k",
                        "form": "for every", "binds": ["k"], "text": "for every natural k ≥ 0"})],
               snap)
    wsp.update(p, rq.suggestion_ops(wsp.read(p), snap, step, "k"), snap)
    use = next(i for i, t in enumerate(tex, 1) if "the choice $k = 1$" in t)
    wsp.update(p, [put({"kind": "fragment", "claim": step, "requirement": "k",
                        "role": "later use", "region": {"file": "toy.tex", "start_line": use}})],
               snap)
    k = wsp.view(wsp.read(p), snap)["claims"][step]["reading"]["requirements"][0]
    assert any(f["role"] == "quantifier domain" and "For every natural number $k \\ge 0$"
               in f["region"]["text"] for f in k["fragments"]["proposed"])
    assert not any(f["region"]["start_line"] == use for f in k["fragments"]["proposed"])
    assert [f["region"]["start_line"] for f in k["fragments"]["later_uses"]] == [use]
    # The informed packet carries it; nothing is assessed again and no status moves.
    rd = v["claims"]["T:def:even"]["reading"]
    pk = cmp.claim_packet(cmp.Site(data), "Definition 1.1", "informed",
                          reading={"workspace": v["id"], **rd})
    assert pk["interpretations"]["requirements"]["requirements"][0]["local_id"] == "even"
    assert {c["id"]: status(index, c["id"]) for c in index["claims"]} == statuses
    again = json.loads((data / "index.json").read_text())
    assert {c["id"]: c["status"] for c in again["claims"]} == statuses
