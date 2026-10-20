"""A refuted printed step of the toy paper (#111, #125): Equation (3), in the proof of
Theorem 2.5, states n ≤ k n² for every natural number k ≥ 0, and k = 0, n = 1 violates it. The
auditor records the counterexample with a Lean certificate (`ToyAudit`, a library of the toy
project outside the paper's statements and proofs), the corrected reading k ≥ 1 with its own
certificate, and a finding "false as printed" on the step. No status changes, Theorem 2.5's
included."""

import json
import shutil
import subprocess

import pytest

from conftest import TOY, build, needs_lean, needs_tex, status

from prooflens import estimates as est
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
STEP = "T:eq:bound-range"
REFUTES = {"theorem": "ToyAudit.bound_range_at_one_false",
           "target": "ToyAudit.bound_range_at_one", "certifies": "refutes"}
PROVES = {"theorem": "ToyAudit.bound_range_corrected_holds",
          "target": "ToyAudit.bound_range_corrected", "certifies": "proves"}


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def lake_build(root, target):
    subprocess.run(["lake", "build", target], cwd=root, check=True, capture_output=True,
                   timeout=900)


@pytest.fixture
def audit(tmp_path):
    """The toy's Lean project with its certificates built."""
    root = tmp_path / "lean"
    shutil.copytree(TOY / "lean", root, ignore=shutil.ignore_patterns(".lake"))
    lake_build(root, "ToyAudit")
    return root


@needs_lean
def test_a_certificate_is_checked_by_lean_with_its_scope_and_pins(audit):
    doc = est.check(audit, **REFUTES)
    assert doc["status"] == "checked" and doc["reasons"] == []
    assert doc["type"] == "¬ToyAudit.bound_range_at_one"
    assert doc["target_statement"] == "∀ (k : Nat), 1 ≤ k * 1 ^ 2"
    assert doc["module"] == "ToyAudit" and doc["file"] == "ToyAudit.lean"
    assert doc["lean"]["version"] and doc["toolchain"].startswith("leanprover/lean4:")
    assert doc["file_sha256"] and doc["target_fingerprint"] and doc["manifest_sha256"]
    assert est.check(audit, **REFUTES)["cache"]["hit"]
    assert est.check(audit, **PROVES)["status"] == "checked"
    # A theorem whose type is not the negation of the target is no certificate of it.
    bad = est.check(audit, **{**REFUTES, "certifies": "proves"})
    assert bad["status"] == "failed"
    assert bad["reasons"] == ["its type is not exactly the target"]
    bad = est.check(audit, **{**PROVES, "target": "ToyAudit.bound_range_at_one"})
    assert "its type is not exactly the target" in bad["reasons"]
    # The certificate's source changes: its currency says so before Lean runs again, and the
    # checked proposition is read again once the module is rebuilt.
    ref = {k: doc[k] for k in est.CERT_KEPT if doc.get(k) is not None}
    assert est.certificate_currency(audit, ref)["state"] == "current"
    src = audit / "ToyAudit.lean"
    src.write_text(src.read_text().replace("∀ k : Nat, 1 ≤ k * 1 ^ 2",
                                           "∀ k : Nat, 1 ≤ k * k"))
    cur = est.certificate_currency(audit, ref)
    assert cur["state"] == "stale"
    assert cur["changes"][0]["reason"] == "the certificate's source changed"
    lake_build(audit, "ToyAudit")
    cur = est.certificate_currency(audit, ref, check_now=True)
    assert {c["reason"] for c in cur["changes"]} >= {
        "the certificate's source changed", "the target or a definition it uses changed"}


@needs_lean
@needs_tex
def test_a_refuted_step_is_a_finding_on_the_step_and_no_status_moves(toy):
    index, _, cfg = build(toy)
    statuses = {c["id"]: c["status"] for c in index["claims"]}
    lake_build(cfg.lean_root, "ToyAudit")
    data = cfg.out_dir / "site" / "data"
    snap = Snapshot(data)
    tex = (cfg.out_dir / "sources" / "T" / "toy.tex").read_text(encoding="utf-8").splitlines()
    fix = next(i for i, t in enumerate(tex, 1) if t.startswith("Fix $n$."))
    dom = next(i for i, t in enumerate(tex, 1) if t.startswith("For every natural number $k"))
    p = wsp.open_for(cfg.out_dir, WHO, "informed", sources=snap.sources())
    # The step's reading: n fixed by the proof, then every k ≥ 0, then the inequality.
    wsp.update(p, [
        put({"kind": "requirement", "claim": STEP, "local_id": "n", "form": "for every",
             "binds": ["n"], "domain": "n ≥ 0", "text": "the natural number n fixed by the "
                                                        "proof"}),
        put({"kind": "fragment", "claim": STEP, "requirement": "n", "role": "earlier choice",
             "region": {"file": "toy.tex", "start_line": fix}}),
        put({"kind": "requirement", "claim": STEP, "local_id": "n.k", "parent": "n",
             "form": "for every", "binds": ["k"], "domain": "k ≥ 0",
             "text": "for every natural number k ≥ 0"}),
        put({"kind": "fragment", "claim": STEP, "requirement": "n.k",
             "role": "quantifier domain", "region": {"file": "toy.tex", "start_line": dom}}),
        put({"kind": "requirement", "claim": STEP, "local_id": "n.k.1", "parent": "n.k",
             "form": "conclusion", "text": "n ≤ k n²"}),
        put({"kind": "fragment", "claim": STEP, "requirement": "n.k.1", "role": "statement",
             "passage": {"claim": STEP}}),
        # The certificate of the reduced instance, checked by Lean now.
        put({"id": "e-refutes", "kind": "evidence", "claim": STEP, "role": "supports",
             "ref": {"certificate": REFUTES}}),
        put({"id": "x-zero", "kind": "counterexample", "claim": STEP, "requirement": "n.k.1",
             "specialisation": {"assign": {"n": 1, "k": 0}},
             "reduced": "1 ≤ k · 1²", "violation": "at k = 0 it reads 1 ≤ 0",
             "admissibility": [{"obligation": "n = 1 is a natural number the proof may fix",
                                "state": "verified", "method": "read from the proof"},
                               {"obligation": "k = 0 satisfies k ≥ 0", "state": "verified",
                                "method": "arithmetic"}],
             "evidence": ["e-refutes"]}),
        put({"id": "f-false", "kind": "finding", "claim": STEP, "requirement": "n.k.1",
             "verdict": "false as printed", "counterexamples": ["x-zero"],
             "note": "k = 0 and n = 1 violate it; the proof uses only k = 1."}),
        # The corrected reading, k ≥ 1, beside the printed one, with its own certificate.
        put({"kind": "requirement", "claim": STEP, "local_id": "n.kc", "parent": "n",
             "form": "for every", "binds": ["k"], "domain": "k ≥ 1", "origin": "correction",
             "corrects": "n.k", "text": "for every natural number k ≥ 1"}),
        put({"kind": "fragment", "claim": STEP, "requirement": "n.kc",
             "role": "proposed correction", "region": {"file": "toy.tex", "start_line": dom}}),
        put({"id": "e-proves", "kind": "evidence", "claim": STEP, "role": "supports",
             "ref": {"certificate": PROVES}}),
        put({"id": "f-fixed", "kind": "finding", "claim": STEP, "requirement": "n.kc",
             "coverage": "full", "basis": "checked_bridge", "evidence": ["e-proves"],
             "note": "With k ≥ 1 the step holds for every n."}),
    ], snap, cfg.root)
    wsp.update(p, [{"op": "submit", "id": "f-false", "base_rev": 1},
                   {"op": "submit", "id": "f-fixed", "base_rev": 1}], snap, cfg.root)
    v = wsp.view(wsp.read(p), snap, root=cfg.root)
    b = v["claims"][STEP]["reading"]["estimates"]
    printed, corrected = b["estimates"][0]["readings"]
    cx, = printed["counterexamples"]
    assert cx["analysis"]["form"] == "instance"
    assert cx["analysis"]["standing"] == "admissible counterexample"
    assert cx["currency"]["state"] == "current"
    cert, = cx["certificates"]
    assert cert["result"] == "checked" and cert["currency"]["state"] == "current"
    assert cert["scope"] == ("Lean checks that the type of ToyAudit.bound_range_at_one_false is "
                             "the negation of ToyAudit.bound_range_at_one (∀ (k : Nat), "
                             "1 ≤ k * 1 ^ 2). It certifies that proposition only, not the "
                             "reading it is attached to.")
    assert [(f["id"], f["verdict"]) for f in printed["findings"]] == \
        [("f-false", "false as printed")]
    assert corrected["corrections"] == ["n.kc"] and not corrected["counterexamples"]
    assert [c["theorem"] for c in corrected["certificates"]] == [PROVES["theorem"]]
    assert corrected["obligation"]["text"] == ("for every n (n ≥ 0); for every k (k ≥ 1): "
                                               "n ≤ k n²")
    # The finding is on the step; the enclosing theorem's status and every other status are
    # as they were, in the build and when it is assessed again.
    assert v["claims"][STEP]["findings"][0]["claim"] == STEP
    assert "T:thm:bound" not in v["claims"]
    index2, _, _ = build(toy)
    assert {c["id"]: c["status"] for c in index2["claims"]} == statuses
    assert status(index2, "T:thm:bound") == status(index, "T:thm:bound")
    assert json.loads((data / "index.json").read_text())["claims"] == index2["claims"]
