"""Compositions with Lean (#147), on the synthetic project tests/fixtures/composition: a
positive number whose double is even, by an existence theorem and the sum rule applied to the
witness it produces; a bridge whose type is exactly the combined statement, checked through the
probe's `accept` request; a bridge for a weaker statement, refused; and a bridge that stops
counting once its target or the paper's passage changes. No status changes on the way."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, edit, needs_lean, needs_tex
from prooflens import cli
from prooflens import composition as cp
from prooflens import published_work as pw
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.targets import Snapshot

SRC = ROOT / "tests" / "fixtures" / "composition"
CLAIM = "P:thm:double"
BRIDGE = {"theorem": "Comp.pos_double_even", "target": "Comp.Spec.pos_double_even"}
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def statuses(root):
    idx = json.loads((root / ".machinechecked" / "site" / "data" / "index.json").read_text())
    return {c["id"]: c["status_code"] for c in idx["claims"]}


def composition(app_id, **extra):
    return {"id": "c1", "kind": "composition", "claim": CLAIM, "coverage": "full",
            "steps": [
                {"id": "s1", "establishes": "a positive even n", "uses": ["e-exists"]},
                {"id": "s2", "establishes": "n + n is even", "uses": ["e-app"],
                 "after": ["s1"], "requirements": ["r1"],
                 "substitutions": [{"variable": "a", "value": "n", "in": "e-app"},
                                   {"variable": "b", "value": "n", "in": "e-app"}]}],
            "identifications": [{"left": {"step": "s1", "object": "n"},
                                 "right": {"step": "s2", "object": "a"},
                                 "how": "retained witness"}],
            **extra}


@needs_lean
@needs_tex
def test_a_composition_with_a_checked_bridge(tmp_path, monkeypatch, capsys):
    root = tmp_path / "composition"
    shutil.copytree(SRC, root, ignore=shutil.ignore_patterns(".lake", ".machinechecked"))
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    monkeypatch.chdir(root)
    cli.main(["build"])
    before = statuses(root)
    work = root / ".machinechecked"
    snap = Snapshot(work / "site" / "data")
    p = wsp.open_for(work, {"id": "human:A", "kind": "human"}, "informed",
                     sources=snap.sources())

    # The sum rule as Lean applies it inside a proof: its arguments are the retained witness.
    capsys.readouterr()
    cli.main(["compare", "--query", "uses", "Comp.even_add", "--json"])
    apps = json.loads(capsys.readouterr().out)["results"][0]["applications"]
    app = next(a for a in apps if a["caller"] == "Comp.pos_double_even")
    wsp.update(p, [
        put({"id": "r", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
             "form": "there is", "binds": ["n"],
             "text": "a positive natural number n with n + n even"}),
        put({"id": "e-exists", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Comp.exists_pos_even"}}),
        put({"id": "e-app", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"app": {"callee": "Comp.even_add", "id": app["id"]}}}),
        put(composition(app["id"]))], snap, root)
    ref = wsp.read(p)["records"]["e-app"]["ref"]["app"]
    assert (ref["caller"], ref["result"]) == ("Comp.pos_double_even", "Comp.Even (n + n)")
    assert [(a["binder"], a["value"]) for a in ref["arguments"]] == [("a", "n"), ("b", "n")]
    v = wsp.view(wsp.read(p), snap, root=root)
    c, = v["claims"][CLAIM]["compositions"]
    assert (c["basis"], c["complete"]) == ("reviewed_composition", True)
    ev = {e["id"]: e for e in v["claims"][CLAIM]["evidence"]}
    assert ev["e-app"]["currency"]["state"] == "current"

    # A bridge whose type is a weaker statement, or a target that is not a proposition, is
    # refused, and the composition stays as it was.
    for bad, why in (({"theorem": "Comp.double_even", "target": BRIDGE["target"]},
                      "its type is not exactly the target"),
                     ({"theorem": BRIDGE["theorem"], "target": "Comp.Spec.double_even"},
                      "its type is not exactly the target"),
                     ({"theorem": BRIDGE["theorem"], "target": "Comp.even_add"},
                      "not a proposition stated as a definition"),
                     ({"theorem": "Comp.missing", "target": BRIDGE["target"]},
                      "no such theorem")):
        with pytest.raises(wsp.WorkspaceError, match=why):
            wsp.update(p, [put(composition(app["id"], bridge=bad), base=1)], snap, root)
    assert "bridge" not in wsp.read(p)["records"]["c1"]

    # The bridge Lean checks: the composition's basis becomes a checked bridge.
    wsp.update(p, [put(composition(app["id"], bridge=BRIDGE), base=1)], snap, root)
    b = wsp.read(p)["records"]["c1"]["bridge"]
    assert b["type"] == BRIDGE["target"] and "sorryAx" not in b["axioms"]
    assert b["target_fingerprint"] and b["source_sha256"] == snap.chunk(CLAIM)["source_sha256"]
    wsp.update(p, [put({"id": "f1", "kind": "finding", "claim": CLAIM, "coverage": "full",
                        "basis": "checked_bridge", "composition": "c1", "note": "n"}),
                   {"op": "submit", "id": "f1", "base_rev": 1}], snap, root)
    v = wsp.view(wsp.read(p), snap, root=root)
    c, = v["claims"][CLAIM]["compositions"]
    assert (c["basis"], c["bridge_check"]["state"], c["next_step"]) == \
        ("checked_bridge", "checked", None)
    assert v["claims"][CLAIM]["findings"][0]["basis"] == "checked_bridge"
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {CLAIM}, root)[CLAIM]
    assert rd["compositions"][0]["basis"] == "checked_bridge"
    assert rd["compositions"][0]["bridge_check"] == {"state": "checked", "reasons": []}
    # Without the Lean project the published bridge is not counted.
    assert rd["findings"][0]["basis"] == "checked_bridge"
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {CLAIM})[CLAIM]
    assert rd["compositions"][0]["basis"] == "reviewed_composition"
    assert (rd["findings"][0]["basis"], rd["findings"][0]["recorded_basis"]) == \
        ("reviewed_composition", "checked_bridge")
    capsys.readouterr()
    cli.main(["compare", "--query", "composition", "Theorem 1"])
    out = capsys.readouterr().out
    assert "every clause, through a checked bridge" in out
    assert "bridge Comp.pos_double_even for Comp.Spec.pos_double_even: Lean checks it" in out

    # Recording all this changes no status.
    cli.main(["build"])
    assert statuses(root) == before

    # A changed target: the bridge is out of date once Lean reads it again, and the finding
    # reads as the auditor's composition.
    spec = root / "Comp" / "Spec.lean"
    edit(spec, "∃ n : Nat, 0 < n ∧ Even (n + n)", "∃ n : Nat, 1 ≤ n ∧ Even (n + n)")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    v = wsp.view(wsp.read(p), snap, root=root)
    c, = v["claims"][CLAIM]["compositions"]
    assert (c["basis"], c["bridge_check"]["state"]) == ("reviewed_composition", "unchecked")
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    c, = v["claims"][CLAIM]["compositions"]
    f, = v["claims"][CLAIM]["findings"]
    assert (c["basis"], c["bridge_check"]["state"]) == ("reviewed_composition", "stale")
    assert c["bridge_check"]["reasons"] == ["the target is not the version the auditor read"]
    assert (f["basis"], f["recorded_basis"]) == ("reviewed_composition", "checked_bridge")
    assert c["next_step"] == "State the combination as one Lean result."

    # Restored, it is checked again; a changed passage of the paper puts it out of date.
    edit(spec, "∃ n : Nat, 1 ≤ n ∧ Even (n + n)", "∃ n : Nat, 0 < n ∧ Even (n + n)")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    assert v["claims"][CLAIM]["compositions"][0]["basis"] == "checked_bridge"
    edit(root / "paper" / "main.tex", "There is a positive natural number",
         "There is some positive natural number")
    cli.main(["build"])
    snap = Snapshot(work / "site" / "data")
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    c, = v["claims"][CLAIM]["compositions"]
    assert (c["basis"], c["bridge_check"]["state"]) == ("reviewed_composition", "stale")
    assert "the paper's passage is not the version the auditor read" in \
        c["bridge_check"]["reasons"]
    assert c["currency"]["state"] == "stale"
    assert "\n".join(cp.lines(c)).count("out of date") == 1

    # A finding recorded as a checked bridge of its own (#271): Lean checks it, but nothing pins
    # the target and the passage the auditor read, so it reads as the auditor's composition;
    # one naming a theorem Lean does not find says so. Both everywhere: show and an export.
    wsp.update(p, [put({"id": "f-own", "kind": "finding", "claim": CLAIM, "coverage": "full",
                        "basis": "checked_bridge", "bridge": BRIDGE, "note": "n"}),
                   put({"id": "f-missing", "kind": "finding", "claim": CLAIM, "coverage": "full",
                        "basis": "checked_bridge", "note": "n",
                        "bridge": {"theorem": "Comp.missing", "target": BRIDGE["target"]}}),
                   {"op": "submit", "id": "f-own", "base_rev": 1},
                   {"op": "submit", "id": "f-missing", "base_rev": 1}], snap, root)
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    own = {f["id"]: f for f in v["claims"][CLAIM]["findings"]}
    assert (own["f-own"]["basis"], own["f-own"]["recorded_basis"]) == \
        ("reviewed_composition", "checked_bridge")
    assert own["f-own"]["bridge_check"]["state"] == "stale"
    assert "no reviewed version of the target is recorded" in own["f-own"]["basis_reason"]
    assert own["f-missing"]["basis"] == "reviewed_composition"
    assert own["f-missing"]["basis_reason"] == ["Lean finds no such theorem"]
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {CLAIM}, root)[CLAIM]
    pub = {f["id"]: f for f in rd["findings"]}
    assert {pub[f]["basis"] for f in ("f-own", "f-missing")} == {"reviewed_composition"}
    assert pub["f-missing"]["bridge_check"] == {"state": "unchecked",
                                                "reasons": ["Lean finds no such theorem"]}
