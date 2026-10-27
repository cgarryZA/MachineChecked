"""Compositions (#147): an auditor's argument that several results together cover a claim, saved
through the workspace's checked writes, read back with what it leaves open, shown by `compare`,
and published with the accepted records. A small synthetic build stands in for site data, so
these tests run no Lean; the Lean bridge is tested in tests/simple/test_composition_bridge.py."""

import json
import shutil

import pytest

from test_workspace import make_build

from prooflens import compare as cmp
from prooflens import composition as cp
from prooflens import published_work as pw
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.schemas import validate
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
CLOSED = Publish(pdf=False, source_text=False, lean=False, reviews=False)
CLAIM = "P:lem:bound"


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def setup(tmp_path):
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        put({"id": "q1", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
             "form": "there is", "binds": ["u"], "text": "there is an inverse u"}),
        put({"id": "q2", "kind": "requirement", "claim": CLAIM, "local_id": "r1.1",
             "parent": "r1", "form": "condition", "text": "u solves the equation"}),
        put({"id": "q3", "kind": "requirement", "claim": CLAIM, "local_id": "r1.2",
             "parent": "r1", "form": "condition", "text": "u satisfies the bound"}),
        put({"id": "e-exists", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Ex.inverse_solves"}}),
        put({"id": "e-bound", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Ex.inverse_bound"}}),
        put({"id": "e-passage", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"paper": {"claim": CLAIM, "quote": "the inverse"}}}),
        put({"id": "e-no", "kind": "evidence", "claim": CLAIM, "role": "rejected",
             "ref": {"decl": "Ex.main"}, "reason": "another claim's result"}),
    ], snap)
    return work, snap, p


# An existence theorem, and a property theorem applied to the witness it produces.
RETAINED = {
    "id": "c-retained", "kind": "composition", "claim": CLAIM, "coverage": "full",
    "statement": "COMBINED-STATEMENT",
    "steps": [
        {"id": "s1", "establishes": "STEP-ONE: an inverse u solving the equation",
         "uses": ["e-exists"], "requirements": ["r1.1"]},
        {"id": "s2", "establishes": "the bound for that u", "uses": ["e-bound"],
         "after": ["s1"], "requirements": ["r1.2", "r1"],
         "substitutions": [{"variable": "v", "value": "LEAN-VALUE-u", "in": "e-bound"}],
         "inference": "AUDITOR-INFERENCE"}],
    "identifications": [{"left": {"step": "s1", "object": "u"},
                         "right": {"step": "s2", "object": "v"}, "how": "retained witness"}],
    "obligations": [{"id": "o1", "kind": "compatible witnesses",
                     "text": "OBLIGATION-TEXT: the bound concerns the inverse produced",
                     "state": "discharged", "by": {"steps": ["s2"]}}]}

# The same argument with two separate existence results: their witnesses need not agree.
SEPARATE = {
    "id": "c-separate", "kind": "composition", "claim": CLAIM,
    "steps": [
        {"id": "s1", "establishes": "some u solves the equation", "uses": ["e-exists"],
         "requirements": ["r1.1"]},
        {"id": "s2", "establishes": "some u satisfies the bound", "uses": ["e-bound"],
         "requirements": ["r1.2"]}],
    "obligations": [{"id": "o1", "kind": "compatible witnesses",
                     "text": "the two existence results may choose different u"}]}


def test_a_composition_that_covers_every_clause_is_the_auditors_argument(tmp_path):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(RETAINED)], snap)
    v = wsp.view(wsp.read(p), snap)
    c, = v["claims"][CLAIM]["compositions"]
    assert (c["coverage"], c["basis"], c["complete"]) == ("full", "reviewed_composition", True)
    assert c["gaps"] == {"requirements": 3, "uncovered": [], "open": []}
    assert c["next_step"] == "State the combination as one Lean result."
    assert c["evidence"] == ["e-exists", "e-bound"] and c["currency"]["state"] == "current"
    assert v["compositions"] == 1
    text = "\n".join(cp.lines(c))
    assert "every clause, by an argument combining Lean results" in text
    assert "u of s1 is same object as v of s2 (retained witness)" in text
    assert "Lean has not checked this combination" in text

    # A finding resting on it is never direct coverage, and never a bridge without one.
    for basis, why in (("direct", "never direct coverage"), ("checked_bridge", "no bridge"),
                       (None, "never direct coverage")):
        with pytest.raises(wsp.WorkspaceError, match=why):
            wsp.update(p, [put({"kind": "finding", "claim": CLAIM, "coverage": "full",
                                "composition": "c-retained",
                                **({"basis": basis} if basis else {})})], snap)
    wsp.update(p, [put({"id": "f1", "kind": "finding", "claim": CLAIM, "coverage": "full",
                        "basis": "reviewed_composition", "composition": "c-retained",
                        "note": "FINDING-NOTE"}),
                   {"op": "submit", "id": "f1", "base_rev": 1}], snap)
    # The argument a submitted finding rests on is kept as it was.
    with pytest.raises(wsp.WorkspaceError, match="record a new composition and supersede"):
        wsp.update(p, [put({**RETAINED, "note": "changed"}, base=1)], snap)
    with pytest.raises(wsp.WorkspaceError, match="composition of f1"):
        wsp.update(p, [{"op": "delete", "id": "c-retained", "base_rev": 1}], snap)
    with pytest.raises(wsp.WorkspaceError, match="evidence of c-retained"):
        wsp.update(p, [{"op": "delete", "id": "e-bound", "base_rev": 1}], snap)
    with pytest.raises(wsp.WorkspaceError, match="used by c-retained"):
        wsp.update(p, [{"op": "delete", "id": "q3", "base_rev": 1}], snap)

    # `compare` gives the same record, as a prior interpretation.
    site = cmp.Site(work / "site" / "data")
    q = cmp.query(site, "composition", "Lemma 2.3")
    assert q["available"] and q["subject"]["contains"] == ["prior interpretations"]
    r, = q["results"]
    assert (r["id"], r["basis"], r["workspace"], r["reviewer"]) == \
        ("c-retained", "reviewed_composition", wsp.read(p)["id"], "human:A-Auditor")
    with pytest.raises(cmp.CompareError, match="no workspace"):
        cmp.query(site, "composition", "Lemma 2.3", workspace="ws-000000000000")
    pk = cmp.claim_packet(site, "Lemma 2.3", "informed",
                          reading={"workspace": "w", "requirements": [], "witnesses": [],
                                   "alignments": [], "questions": [],
                                   "compositions": [r]})
    assert pk["interpretations"]["compositions"] == [r]
    assert "compositions" not in pk["interpretations"]["requirements"]
    assert "Compositions recorded in that workspace" in cmp.packet_text(pk)
    assert "compositions" not in json.dumps(cmp.claim_packet(site, "Lemma 2.3", "compare"))

    # Published with the finding that rests on it, and the evidence it uses.
    data = tmp_path / "out" / "data"
    shutil.copytree(work / "site" / "data", data)
    before = json.loads((data / "claims" / "lem_bound.json").read_text())
    pw.write(data, work, lambda cid: EVERYTHING)
    after = json.loads((data / "claims" / "lem_bound.json").read_text())
    assert {k: v for k, v in after.items() if k != "work"} == before
    body = json.loads((data / "work" / "lem_bound.json").read_text())
    validate(body, "published-work")
    rd, = body["readings"]
    pc, = rd["compositions"]
    assert (pc["basis"], pc["complete"], pc["statement"]) == \
        ("reviewed_composition", True, "COMBINED-STATEMENT")
    assert pc["steps"][1]["substitutions"][0]["value"] == "LEAN-VALUE-u"
    assert rd["findings"][0]["composition"] == "c-retained"
    assert sorted(e["id"] for e in rd["evidence"]) == ["e-bound", "e-exists"]
    # Prose only when reviews are published, Lean values only when the Lean is.
    rd, = pw.readings(work, snap, lambda cid: CLOSED, {CLAIM})[CLAIM]
    raw = json.dumps(rd)
    for word in ("COMBINED-STATEMENT", "STEP-ONE", "AUDITOR-INFERENCE", "OBLIGATION-TEXT",
                 "LEAN-VALUE-u", "FINDING-NOTE"):
        assert word not in raw, word
    pc, = rd["compositions"]
    assert [s["id"] for s in pc["steps"]] == ["s1", "s2"]
    assert pc["obligations"] == [{"id": "o1", "kind": "compatible witnesses",
                                  "state": "discharged", "by": {"steps": ["s2"]}}]
    validate({"schema": pw.SCHEMA, "release": "v-1", "claim": CLAIM, "readings": [rd]},
             "published-work")


def test_separate_existence_results_leave_the_compatibility_obligation_open(tmp_path):
    work, snap, p = setup(tmp_path)
    with pytest.raises(wsp.WorkspaceError, match="obligation.*o1 are open"):
        wsp.update(p, [put({**SEPARATE, "coverage": "full"})], snap)
    # Without the obligation, the uncovered clause still keeps it from full coverage.
    with pytest.raises(wsp.WorkspaceError, match="no step establishes r1$"):
        wsp.update(p, [put({**SEPARATE, "coverage": "full", "obligations": []})], snap)
    wsp.update(p, [put({**SEPARATE, "coverage": "partial"})], snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    assert c["gaps"] == {"requirements": 3, "uncovered": ["r1"], "open": ["o1"]}
    assert not c["complete"] and c["basis"] == "reviewed_composition"
    assert "obligation o1 (compatible witness choices), open" in "\n".join(cp.lines(c))
    with pytest.raises(wsp.WorkspaceError, match="o1 are open"):
        wsp.update(p, [put({"kind": "finding", "claim": CLAIM, "coverage": "full",
                            "basis": "reviewed_composition",
                            "composition": "c-separate"})], snap)
    wsp.update(p, [put({"id": "f-part", "kind": "finding", "claim": CLAIM,
                        "coverage": "partial", "basis": "reviewed_composition",
                        "composition": "c-separate", "note": "n"})], snap)
    # Claiming the witnesses are retained needs the later step to follow from the earlier.
    with pytest.raises(wsp.WorkspaceError, match="s2 does not follow from s1"):
        wsp.update(p, [put({**SEPARATE, "id": "c-x", "identifications": [
            {"left": {"step": "s1", "object": "u"}, "right": {"step": "s2", "object": "u"},
             "how": "retained witness"}]})], snap)
    with pytest.raises(wsp.WorkspaceError, match="known by evidence: name it"):
        wsp.update(p, [put({**SEPARATE, "id": "c-x", "identifications": [
            {"left": {"step": "s1", "object": "u"}, "right": {"step": "s2", "object": "u"},
             "how": "evidence"}]})], snap)


@pytest.mark.parametrize("change, why", [
    ({"steps": []}, "lists its steps"),
    ({"steps": [{"establishes": "x"}]}, "rests on nothing"),
    ({"steps": [{"establishes": "x", "uses": ["e-passage"]}]}, "cites a passage"),
    ({"steps": [{"establishes": "x", "uses": ["e-no"]}]}, "rejected candidate"),
    ({"steps": [{"establishes": "x", "uses": ["e-missing"]}]}, "not an evidence record"),
    ({"steps": [{"establishes": "x", "after": ["s9"]}]}, "not an earlier step"),
    ({"steps": [{"establishes": "x", "uses": ["e-bound"], "requirements": ["r7"]}]},
     "no requirement 'r7'"),
    ({"steps": [{"id": "s1", "establishes": "x", "uses": ["e-bound"]},
                {"id": "s1", "establishes": "y", "uses": ["e-bound"]}]}, "two steps"),
    ({"basis": "checked_bridge"}, "basis is not written"),
    ({"obligations": [{"text": "t", "state": "discharged"}]}, "name the steps or evidence"),
    ({"bridge": {"theorem": "Ex.main", "target": "Ex.Spec"}}, "needs the Lean project"),
])
def test_a_composition_is_refused_when_it_does_not_hold_together(tmp_path, change, why):
    work, snap, p = setup(tmp_path)
    rec = {**SEPARATE, "id": "c-bad", **change}
    with pytest.raises(wsp.WorkspaceError, match=why):
        wsp.update(p, [put(rec)], snap)
    assert "c-bad" not in wsp.read(p)["records"]


def test_a_changed_result_makes_the_composition_and_its_finding_stale(tmp_path):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(RETAINED),
                   put({"id": "f1", "kind": "finding", "claim": CLAIM, "coverage": "full",
                        "basis": "reviewed_composition", "composition": "c-retained",
                        "note": "n"})], snap)
    make_build(work, fp_bound="fp:bound-2", release="v-2")
    v = wsp.view(wsp.read(p), Snapshot(work / "site" / "data"))
    c, = v["claims"][CLAIM]["compositions"]
    f, = v["claims"][CLAIM]["findings"]
    assert c["currency"]["state"] == "stale" and f["currency"]["state"] == "stale"
    assert {ch.get("decl") for ch in c["currency"]["changes"]} == {"Ex.inverse_bound"}
