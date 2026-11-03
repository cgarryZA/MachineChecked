"""A difference resolved by a checked bridge (#499), on the synthetic project
tests/fixtures/composition: the bridge is checked by Lean when it is recorded and refused when Lean
does not check it; it resolves the conditions it names and leaves the others open; it reads as
resolving the difference only while Lean checks it, in `workspace show`, the reading and a
published audit, and as recorded, with why, once its target changes. No status changes."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, edit, needs_lean, needs_tex
from prooflens import cli
from prooflens import estimates as est
from prooflens import published_work as pw
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.targets import Snapshot

SRC = ROOT / "tests" / "fixtures" / "composition"
CLAIM = "P:thm:double"
BRIDGE = {"theorem": "Comp.pos_double_even", "target": "Comp.Spec.pos_double_even"}
CONDITIONS = ["n is positive", "n + n is even"]
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def statuses(root):
    idx = json.loads((root / ".machinechecked" / "site" / "data" / "index.json").read_text())
    return {c["id"]: c["status_code"] for c in idx["claims"]}


def finding(fid, **resolution):
    return put({"id": fid, "kind": "finding", "claim": CLAIM, "requirement": "r1",
                "difference": {"feature": "domain", "paper": "a positive natural number n",
                               "lean": "0 < n", "transport": "the bridge", "outcome": "resolved",
                               "conditions": CONDITIONS,
                               "resolution": {"by": "checked bridge",
                                              "text": "the bridge states it", **resolution}},
                "note": "n"})


@needs_lean
@needs_tex
def test_a_difference_resolved_by_a_checked_bridge(tmp_path, monkeypatch, capsys):
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
    wid = wsp.read(p)["id"]
    wsp.update(p, [put({"id": "r", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
                        "form": "there is", "binds": ["n"],
                        "text": "a positive natural number n with n + n even"})], snap, root)

    # A bridge Lean does not check is refused: a theorem it does not find, one whose type is a
    # weaker statement, a target that is not a proposition.
    for bad, why in (({"theorem": "Nope.x", "target": BRIDGE["target"]},
                      "no module of the project declares Nope.x"),
                     ({"theorem": "Comp.double_even", "target": BRIDGE["target"]},
                      "its type is not exactly the target"),
                     ({"theorem": BRIDGE["theorem"], "target": "Comp.even_add"},
                      "not a proposition stated as a definition")):
        with pytest.raises(wsp.WorkspaceError, match=why):
            wsp.update(p, [finding("f-bad", **bad, conditions=CONDITIONS[:1])], snap, root)
    assert "f-bad" not in wsp.read(p)["records"]

    # The bridge Lean checks, pinned to the target and the claim's passage. It resolves the
    # condition it names; the other stays open.
    wsp.update(p, [finding("f-one", **BRIDGE, conditions=CONDITIONS[:1]),
                   {"op": "submit", "id": "f-one", "base_rev": 1}], snap, root)
    r = wsp.read(p)["records"]["f-one"]["difference"]["resolution"]
    assert (r["type"], r["module"], r["file"]) == (BRIDGE["target"], "Comp.Spec",
                                                  "Comp/Spec.lean")
    assert r["target_fingerprint"] and r["file_sha256"] and r["checked_at"]
    assert r["source_sha256"] == snap.chunk(CLAIM)["source_sha256"]
    assert "sorryAx" not in r["axioms"]
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    b = v["claims"][CLAIM]["reading"]["estimates"]
    d, = b["differences"]
    assert d["bridge_check"] == {"state": "checked", "reasons": []}
    assert d["open_conditions"] == CONDITIONS[1:]
    assert est.outcome_text(d) == "resolved in part"
    assert est.resolution_text(d) == ("resolved by checked bridge for the condition n is "
                                      "positive: the bridge states it; still open: the condition "
                                      "n + n is even")
    f, = v["claims"][CLAIM]["findings"]
    assert f["currency"]["state"] == "current"
    assert "checked bridge" in f["dependencies"]["kinds"]
    # Naming every condition, it resolves the difference.
    wsp.update(p, [finding("f-all", **BRIDGE, conditions=CONDITIONS),
                   {"op": "submit", "id": "f-all", "base_rev": 1}], snap, root)
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    assert [x["finding"] for x in v["claims"][CLAIM]["reading"]["estimates"]["resolved"]] == \
        ["f-all"]
    capsys.readouterr()
    cli.main(["workspace", "show", "--id", wid])
    out = capsys.readouterr().out
    assert ("domain on r1, resolved by checked bridge for the conditions n is positive, n + n is "
            "even: the bridge states it") in out
    assert "Lean does not check" not in out

    # A published audit counts the bridge only while it is checked against the Lean project.
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {CLAIM}, root)[CLAIM]
    pub = {x["id"]: x["difference"] for x in rd["findings"]}
    assert pub["f-all"]["bridge_check"] == {"state": "checked", "reasons": []}
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {CLAIM})[CLAIM]
    pub = {x["id"]: x["difference"] for x in rd["findings"]}
    assert est.resolution_text(pub["f-all"]) == (
        "recorded as resolved by a checked bridge for the conditions n is positive, n + n is "
        "even; Lean does not check it now: no Lean project to check the bridge against")

    # Recording all this changes no status.
    cli.main(["build"])
    assert statuses(root) == before

    # The target changes: the bridge is out of date once Lean reads it again, the difference
    # reads as recorded as resolved, and the finding is due for review.
    spec = root / "Comp" / "Spec.lean"
    edit(spec, "∃ n : Nat, 0 < n ∧ Even (n + n)", "∃ n : Nat, 1 ≤ n ∧ Even (n + n)")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    v = wsp.view(wsp.read(p), snap, root=root)
    d = {x["finding"]: x for x in v["claims"][CLAIM]["reading"]["estimates"]["differences"]}
    assert d["f-all"]["bridge_check"]["state"] == "unchecked"
    v = wsp.view(wsp.read(p), snap, root=root, check_facts=True)
    b = v["claims"][CLAIM]["reading"]["estimates"]
    assert b["resolved"] == []
    d = {x["finding"]: x for x in b["differences"]}
    assert d["f-all"]["bridge_check"]["state"] == "stale"
    assert est.resolution_text(d["f-all"]) == (
        "recorded as resolved by a checked bridge for the conditions n is positive, n + n is "
        "even; Lean does not check it now: the target is not the version the auditor read")
    f = {x["id"]: x for x in v["claims"][CLAIM]["findings"]}
    assert f["f-all"]["currency"]["state"] == "stale"
    assert f["f-all"]["difference"]["bridge_check"]["state"] == "stale"
    capsys.readouterr()
    cli.main(["workspace", "show", "--id", wid])
    out = capsys.readouterr().out
    assert ("recorded as resolved by a checked bridge for the conditions n is positive, n + n is "
            "even; Lean does not check it now: the target is not the version the auditor read"
            ) in out
    assert "resolved by checked bridge" not in out
    assert ("changed: the bridge Comp.pos_double_even for Comp.Spec.pos_double_even the "
            "difference is resolved by is out of date") in out
