"""Proof-step targets through a published audit and an import (#545): a finding, a
counterexample and a review draft on a proof step keep the step's kind, parent and scope, their
evidence and their review state. The end-to-end round trip on the toy paper is in
tests/simple/test_step_roundtrip.py; nothing here builds Lean."""

import copy
import json

from published_fixture import REPO, STEP, STEP_TARGET, stepped
from prooflens.steps import target_differences, target_of
from prooflens.workspace import target_problems


def test_a_published_proof_step_keeps_its_kind_parent_and_review_on_a_paper_page(tmp_path):
    index, audit = stepped(tmp_path)
    rows = {r["by_project"][REPO]["audit"]["claim"]: r for r in index["claims"]
            if REPO in r["by_project"] and r["by_project"][REPO].get("audit")}
    parent, step = rows["T:one"], rows[STEP]
    # The page lists the step under its own id, with the audit's kind, scope and review, and
    # its parent by the page's id.
    mine = step["by_project"][REPO]
    assert (mine["unit"], mine["scope"], mine["kind"], mine["step_review"]) == \
        ("proof-equation", "proof-step", "equation", "false")
    assert mine["parent"] == parent["id"] == "P:theorem-1"
    assert mine["status_code"] == "scope.proof-step"
    assert "unit" not in parent["by_project"][REPO]

    def record(row):
        c = json.loads((tmp_path / "data/claims" / row["file"]).read_text())
        return c["by_project"][REPO]["record"]

    # The records are the audit's, whole: the step block with its review, the parent's list.
    loaded = {c["id"]: c["record"] for c in audit["claims"]}
    assert record(step) == loaded[STEP] and record(parent) == loaded["T:one"]
    assert record(step)["step"]["review"]["state"] == "false"
    assert [s["id"] for s in record(parent)["steps"]] == [STEP]
    # The auditor's records on the step keep their kind, evidence and state, and pin the step.
    reading = record(step)["work"]["readings"][0]
    (f,), (x,), (e,) = reading["findings"], reading["counterexamples"], reading["evidence"]
    assert (f["kind"], f["state"], f["verdict"], f["in_force"]) == \
        ("finding", "submitted", "false as printed", True)
    assert f["counterexamples"][0]["id"] == x["id"] and x["evidence"] == [e["id"]]
    assert e["ref"]["certificate"]["certifies"] == "refutes"
    assert {r["pins"]["target"] == STEP_TARGET for r in (f, x, e)} == {True}


class Snap:
    """A build as `workspace.target_problems` reads it: its claim records and review queue."""

    def __init__(self, tmp, chunks, units):
        self.chunks, self.data = chunks, tmp
        self.index = {"release": "v-other"}
        (tmp / "review-queue.json").write_text(json.dumps({"units": [{"id": u} for u in units]}))

    def chunk(self, cid):
        return self.chunks.get(cid)


def test_an_import_names_each_record_and_draft_whose_step_differs_here(tmp_path):
    step = {"scope": "proof-step",
            "step": {"unit": "proof-equation", "parent": {"id": "P:thm:a", "number": "Theorem 1"},
                     "source": {"location": "p.tex:9", "region": {"end_line": 11},
                                "sha256": "s" * 64}}}
    pinned = target_of(step)
    assert pinned == {"unit": "proof-equation", "parent": {"id": "P:thm:a", "number": "Theorem 1"},
                      "scope": "proof-step", "source": {"location": "p.tex:9",
                                                        "region": {"end_line": 11},
                                                        "sha256": "s" * 64}}
    assert target_of({"scope": "formal"}) is None
    # Its text alone changed: that is the record's currency, not its target.
    moved = copy.deepcopy(step)
    moved["step"]["source"]["sha256"] = "t" * 64
    assert target_differences(pinned, target_of(moved)) == []
    other = copy.deepcopy(step)
    other["step"].update(unit="proof-passage", parent={"id": "P:thm:b", "number": "Theorem 2"})
    assert target_differences(pinned, target_of(other)) == [
        "it was recorded on a proof-equation and is a proof-passage here",
        "it was a step of P:thm:a and is a step of P:thm:b here"]
    assert target_differences(pinned, None) == ["it is no proof step in this build"]

    ws = {"records": {"f-1": {"id": "f-1", "claim": "P:eq:x", "pins": {"target": pinned}},
                      "f-2": {"id": "f-2", "claim": "P:thm:a", "pins": {}}},
          "review": {"drafts": {
              "step:P:eq:x": {"stage": "compare", "target": {"unit": "proof-equation",
                                                             "claim": "P:eq:x",
                                                             "parent": pinned["parent"]}},
              "step:P:eq:gone": {"stage": "read", "target": {"unit": "proof-equation",
                                                             "claim": "P:eq:gone",
                                                             "parent": pinned["parent"]}},
              "link:thm:a": {"stage": "read"}}}}
    same = Snap(tmp_path, {"P:eq:x": step, "P:thm:a": {"scope": "formal"}},
                ["step:P:eq:x", "link:thm:a"])
    assert target_problems(ws, same) == [
        {"record": "draft step:P:eq:gone", "problem": "step:P:eq:gone is not a review unit of "
                                                      "release v-other"}]
    there = Snap(tmp_path, {"P:eq:x": other, "P:thm:a": {"scope": "formal"}},
                 ["step:P:eq:x", "step:P:eq:gone", "link:thm:a"])
    found = target_problems(ws, there)
    assert [p["record"] for p in found] == ["f-1", "f-1", "draft step:P:eq:gone",
                                            "draft step:P:eq:x", "draft step:P:eq:x"]
    assert found[0]["problem"] == ("P:eq:x: it was recorded on a proof-equation and is a "
                                   "proof-passage here")
    assert found[2]["problem"] == "P:eq:gone: it is no proof step in this build"
