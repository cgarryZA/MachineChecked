"""Estimates read with their quantifiers and constants, differences recorded as findings,
candidate counterexamples and their certificates (#111), on the synthetic build of
`test_requirements` (no Lean).

The synthetic estimate (1) reads "for every ε > 0, |u| ≤ ε|f| + C/ε, with C independent of ε".
With f = 0 and |u| = 1 it reduces to 1 ≤ C/ε, which ε = C + 1 violates for every C ≥ 0; with
0 < ε ≤ 1 it holds for C = 1. The section's opening sentence makes f bounded throughout.
"""

import json

import pytest

from test_requirements import PAPER, _run, make_build

from prooflens import cli
from prooflens import estimates as est
from prooflens import published_work as pw
from prooflens import requirements as rq
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.schemas import validate
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
CLAIM = "P:eq:young"
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
CLOSED = Publish(pdf=False, source_text=False, lean=False, reviews=False)

# Line 4 of the synthetic paper, blank there, opens the section with a standing assumption.
SECTION_PAPER = PAPER.replace("\\section{Estimates}\n\n",
                              "\\section{Estimates}\nThroughout this section, $f$ is bounded.\n")
STANDING_LINE = 4


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w, paper=SECTION_PAPER)
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def region(a, b=None):
    return {"file": "paper.tex", "start_line": a, "end_line": b or a}


# The printed reading: one C, independent of ε; for every ε > 0; the estimate.
READING = [
    put({"id": "r-C", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
         "form": "there is", "binds": ["C"], "independent_of": ["ε"], "domain": "C ≥ 0",
         "text": "there is a constant C, independent of ε"}),
    put({"id": "r-eps", "kind": "requirement", "claim": CLAIM, "local_id": "r1.1",
         "parent": "r1", "form": "for every", "binds": ["ε"], "domain": "ε > 0",
         "text": "for every ε > 0"}),
    put({"id": "r-est", "kind": "requirement", "claim": CLAIM, "local_id": "r1.1.1",
         "parent": "r1.1", "form": "conclusion", "text": "|u| ≤ ε|f| + C/ε"}),
    put({"id": "p-dep", "kind": "fragment", "claim": CLAIM, "requirement": "r1",
         "role": "constant dependence", "region": region(10)}),
    put({"id": "p-eps", "kind": "fragment", "claim": CLAIM, "requirement": "r1.1",
         "role": "quantifier domain", "region": region(6)}),
    put({"id": "p-est", "kind": "fragment", "claim": CLAIM, "requirement": "r1.1.1",
         "role": "statement", "passage": {"claim": CLAIM}}),
]

FAMILY = {"id": "x-fam", "kind": "counterexample", "claim": CLAIM, "requirement": "r1.1.1",
          "specialisation": {"assign": {"ε": "C + 1"}, "zero": ["f"], "other": ["|u| = 1"]},
          "reduced": "1 ≤ C/ε", "violation": "C/(C + 1) < 1 for every C ≥ 0",
          "admissibility": [{"obligation": "u with |u| = 1 and f = 0 solve the problem of "
                                           "Definition 3.2", "state": "open"}]}


def opened(work):
    p = wsp.open_for(work, WHO, "informed", sources=snap_of(work).sources())
    wsp.update(p, READING, snap_of(work))
    return p


def block(work, p, claim=CLAIM):
    return wsp.view(wsp.read(p), snap_of(work))["claims"][claim]["reading"]["estimates"]


def records(p, claim=CLAIM):
    return [r for r in wsp.read(p)["records"].values() if r["claim"] == claim]


def rec(p, rid):
    return wsp.read(p)["records"][rid]


def edit(p, work, rid, **change):
    r = rec(p, rid)
    keep = {k: v for k, v in r.items() if k not in wsp.MANAGED + ("id", "obligation_sha256",
                                                                   "evidence_pins")}
    wsp.update(p, [put({"id": rid, "kind": r["kind"], **keep, **change}, r["rev"])],
               snap_of(work))


# -- the reading of an estimate ------------------------------------------------------------

def test_a_constant_independent_of_eps_is_chosen_before_every_eps(work):
    p = opened(work)
    ob = est.obligation(records(p), "r1.1.1")
    assert [(e["var"], e["quantifier"], e["domain"]) for e in ob["order"]] == \
        [("C", "there is", "C ≥ 0"), ("ε", "for every", "ε > 0")]
    assert ob["text"] == ("there is C (C ≥ 0), independent of ε; for every ε (ε > 0): "
                          "|u| ≤ ε|f| + C/ε")
    c = ob["order"][0]
    assert c["may_depend_on"] == [] and c["chosen_before"] == ["ε"]
    # The same reading written the other way round: ε outside, the constant's dependence
    # attached to it. The constant is still chosen before ε.
    other = [
        {"kind": "requirement", "local_id": "s1", "form": "for every", "binds": ["ε"],
         "domain": "ε > 0", "text": "for every ε > 0"},
        {"kind": "requirement", "local_id": "s1.1", "parent": "s1", "form": "conclusion",
         "text": "|u| ≤ ε|f| + C/ε"},
        {"kind": "requirement", "local_id": "s1.2", "parent": "s1",
         "form": "constant dependence", "binds": ["C"], "independent_of": ["ε"],
         "text": "C does not depend on ε"}]
    ob2 = est.obligation(other, "s1.1")
    assert [e["var"] for e in ob2["order"]] == ["C", "ε"]
    # Without the independence, C is chosen after ε and may depend on it: another reading.
    other[2] = {**other[2], "independent_of": []}
    ob3 = est.obligation(other, "s1.1")
    assert [e["var"] for e in ob3["order"]] == ["ε", "C"]
    assert ob3["order"][1]["may_depend_on"] == ["ε"]
    assert ob3["sha256"] != ob2["sha256"]
    # The domain is part of the reading the terminal shows.
    v = wsp.view(wsp.read(p), snap_of(work))
    text = "\n".join(rq.lines(v["claims"][CLAIM]["reading"]))
    assert "r1.1  for every ε (ε > 0): for every ε > 0" in text


def test_a_domain_belongs_to_a_quantifier(work):
    p = opened(work)
    with pytest.raises(wsp.WorkspaceError, match="has a domain"):
        wsp.update(p, [put({"kind": "requirement", "claim": CLAIM, "local_id": "r9",
                            "form": "condition", "domain": "x > 0", "text": "x"})],
                   snap_of(work))


# -- counterexamples: symbolic, not sampled --------------------------------------------------

def test_a_symbolic_family_over_the_constant_refutes_the_printed_reading(work):
    p = opened(work)
    wsp.update(p, [put(FAMILY)], snap_of(work))
    b = block(work, p)
    printed = b["estimates"][0]["readings"][0]
    assert b["estimates"][0]["requirement"] == "r1.1.1" and printed["printed"]
    cx, = printed["counterexamples"]
    a = cx["analysis"]
    assert a["form"] == "family" and a["decisive"] and a["family"] == ["C"]
    assert a["values"] == [{"var": "ε", "value": "C + 1", "symbolic": True, "uses": ["C"]}]
    # Until its admissibility is shown it stays a candidate.
    assert a["standing"] == "candidate" and a["open_obligations"]
    assert a["shows"].startswith("for every C (C ≥ 0): ε = C + 1 reduces the reading to "
                                 "1 ≤ C/ε")
    assert cx["currency"]["state"] == "current"
    adm = [{**FAMILY["admissibility"][0], "state": "verified",
            "method": "the auditor checked the equations of Definition 3.2"}]
    edit(p, work, "x-fam", admissibility=adm)
    a = block(work, p)["estimates"][0]["readings"][0]["counterexamples"][0]["analysis"]
    assert a["standing"] == "admissible counterexample"
    # An admissibility obligation the assignment violates leaves it not admissible.
    edit(p, work, "x-fam", admissibility=[{**adm[0], "state": "fails",
                                           "method": "f = 0 is not allowed"}])
    a = block(work, p)["estimates"][0]["readings"][0]["counterexamples"][0]["analysis"]
    assert a["standing"] == "not admissible" and not a["open_obligations"]


def test_numeric_samples_never_show_that_every_constant_fails(work):
    p = opened(work)
    sweep = [{"C": c, "ε": c + 1} for c in range(50)]
    wsp.update(p, [put({**FAMILY, "id": "x-sweep",
                        "specialisation": {"assign": {"C": 3, "ε": 4}, "zero": ["f"]},
                        "samples": sweep, "admissibility": [
                            {"obligation": "the data solve the problem", "state": "verified",
                             "method": "checked"}]})], snap_of(work))
    a = block(work, p)["estimates"][0]["readings"][0]["counterexamples"][0]["analysis"]
    assert a["form"] == "fixed constants" and not a["decisive"]
    assert a["standing"] == "illustration" and a["samples"] == 50
    assert "not that every choice does" in a["shows"]
    assert a["samples_note"] == est.SAMPLES_NOTE
    # A value for ε that uses a variable chosen after it is not a family of this reading.
    wsp.update(p, [put({**FAMILY, "id": "x-late",
                        "specialisation": {"assign": {"ε": "ε + 1"}}})], snap_of(work))
    late = next(c for c in block(work, p)["estimates"][0]["readings"][0]["counterexamples"]
                if c["id"] == "x-late")["analysis"]
    assert late["standing"] == "incomplete" and "chosen after ε" in late["problems"][0]


def test_letting_C_depend_on_eps_changes_the_target(work):
    p = opened(work)
    wsp.update(p, [put(FAMILY),
                   put({"id": "r-Cc", "kind": "requirement", "claim": CLAIM, "local_id": "r1c",
                        "form": "there is", "binds": ["C"], "domain": "C ≥ 0",
                        "depends_on": ["ε"], "origin": "correction", "corrects": "r1",
                        "text": "there is C, which may depend on ε"}),
                   put({"kind": "fragment", "claim": CLAIM, "requirement": "r1c",
                        "role": "proposed correction", "passage": {"claim": CLAIM}}),
                   put({**FAMILY, "id": "x-per", "reading": ["r1c"]})], snap_of(work))
    est_, = block(work, p)["estimates"]
    by = {tuple(rd["corrections"]): rd for rd in est_["readings"]}
    assert set(by) == {(), ("r1c",)}
    # The corrected reading chooses C after ε; the same assignment is no longer a family.
    assert [e["var"] for e in by[("r1c",)]["obligation"]["order"]] == ["ε", "C"]
    per, = by[("r1c",)]["counterexamples"]
    assert per["id"] == "x-per" and per["analysis"]["standing"] == "incomplete"
    assert "uses C, chosen after ε" in per["analysis"]["problems"][0]
    # The printed reading keeps its own counterexample and its order.
    assert [c["id"] for c in by[()]["counterexamples"]] == ["x-fam"]
    assert by[()]["counterexamples"][0]["analysis"]["form"] == "family"
    # The printed requirement is unchanged.
    assert rec(p, "r-C")["independent_of"] == ["ε"]


def test_the_corrected_domain_is_a_separate_reading_with_its_own_evidence(work):
    p = opened(work)
    cert = {"theorem": "Ex.reduced_on_unit_interval", "target": "Ex.ReducedOnUnitInterval",
            "certifies": "proves", "module": "Ex.Audit", "type": "Ex.ReducedOnUnitInterval",
            "target_fingerprint": "f" * 16, "result": "checked", "reasons": [],
            "target_statement": "∀ ε : ℝ, 0 < ε → ε ≤ 1 → 1 ≤ 1 / ε"}
    wsp.update(p, [
        put(FAMILY),
        put({"id": "r-epsc", "kind": "requirement", "claim": CLAIM, "local_id": "r1.1c",
             "parent": "r1", "form": "for every", "binds": ["ε"], "domain": "0 < ε ≤ 1",
             "origin": "correction", "corrects": "r1.1", "text": "for every 0 < ε ≤ 1"}),
        put({"kind": "fragment", "claim": CLAIM, "requirement": "r1.1c",
             "role": "proposed correction", "region": region(13)}),
        put({"id": "e-cert", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"certificate": cert}}),
        put({"id": "f-fixed", "kind": "finding", "claim": CLAIM, "requirement": "r1.1c",
             "coverage": "full", "basis": "checked_bridge", "evidence": ["e-cert"],
             "note": "With 0 < ε ≤ 1 the reduced bound holds with C = 1."}),
    ], snap_of(work))
    est_, = block(work, p)["estimates"]
    printed, corrected = est_["readings"]
    assert printed["printed"] and corrected["corrections"] == ["r1.1c"]
    assert corrected["obligation"]["text"].startswith(
        "there is C (C ≥ 0), independent of ε; for every ε (0 < ε ≤ 1):")
    assert printed["obligation"]["sha256"] != corrected["obligation"]["sha256"]
    # Each reading has its own evidence: the counterexample on the printed one, the
    # certificate on the corrected one, with its checked scope.
    assert [c["id"] for c in printed["counterexamples"]] == ["x-fam"] and \
        not printed["certificates"]
    assert not corrected["counterexamples"]
    c, = corrected["certificates"]
    assert c["theorem"] == "Ex.reduced_on_unit_interval" and c["certifies"] == "proves"
    assert c["scope"].endswith("It certifies that proposition only, not the reading it is "
                               "attached to.")
    assert "∀ ε : ℝ, 0 < ε → ε ≤ 1 → 1 ≤ 1 / ε" in c["scope"]
    # Specialisations follow each reading's domain, with C kept fixed.
    assert [s["try"] for s in printed["specialisations"]] == \
        ["ε → 0⁺, with C fixed", "ε → ∞, with C fixed"]
    assert [s["try"] for s in corrected["specialisations"]] == \
        ["ε → 0⁺, with C fixed", "ε = 1, with C fixed"]
    # The printed requirement keeps its domain.
    assert rec(p, "r-eps")["domain"] == "ε > 0"


# -- currency: a counterexample is never rebound to a changed reading ------------------------

def test_a_changed_reading_reopens_the_counterexample_and_the_finding_citing_it(work):
    p = opened(work)
    wsp.update(p, [put(FAMILY),
                   put({"id": "f-step", "kind": "finding", "claim": CLAIM,
                        "requirement": "r1.1.1", "verdict": "false as printed",
                        "counterexamples": ["x-fam"], "note": "ε = C + 1 violates it."})],
               snap_of(work))
    wsp.update(p, [{"op": "submit", "id": "f-step", "base_rev": 1}], snap_of(work))
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["x-fam"]["state"] == "current" and cur["f-step"]["state"] == "current"
    # The quantifier's domain changes: the counterexample was made against another reading.
    edit(p, work, "r-eps", domain="ε ≥ 1")
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["x-fam"]["state"] == "stale"
    assert cur["x-fam"]["changes"][0]["reason"] == "the reading it was made against changed"
    assert cur["f-step"]["state"] == "stale"
    edit(p, work, "r-eps", domain="ε > 0")
    assert wsp.currency(wsp.read(p), snap_of(work))["x-fam"]["state"] == "current"
    # The passage that fixes C's dependence changes in the paper: stale too.
    tex = SECTION_PAPER.replace("does not depend on the choice", "may depend on the choice")
    make_build(work, paper=tex)
    assert wsp.currency(wsp.read(p), snap_of(work))["x-fam"]["state"] == "stale"
    make_build(work, paper=SECTION_PAPER)
    # Re-pinning the counterexample to a reading is an explicit step; editing its reduction
    # reopens the finding that cited it.
    edit(p, work, "x-fam", reduced="1 ≤ C/ε for |u| = 1")
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["x-fam"]["state"] == "current"
    assert cur["f-step"]["changes"] == [{"counterexample": "x-fam", "reason": "the "
                                         "counterexample changed since the finding cited it"}]


def test_a_certificate_attached_to_a_counterexample_is_pinned_with_it(work):
    p = opened(work)
    cert = {"theorem": "Ex.no_uniform_C", "target": "Ex.UniformC", "certifies": "refutes",
            "type": "¬Ex.UniformC", "target_fingerprint": "a" * 16, "result": "checked",
            "reasons": []}
    wsp.update(p, [put({"id": "e-no", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"certificate": cert}}),
                   put({**FAMILY, "evidence": ["e-no"]})], snap_of(work))
    cx = block(work, p)["estimates"][0]["readings"][0]["counterexamples"][0]
    assert cx["certificates"][0]["scope"].startswith(
        "Lean checks that the type of Ex.no_uniform_C is the negation of Ex.UniformC.")
    # Without the Lean project a certificate is unchecked, never current.
    assert cx["certificates"][0]["currency"]["state"] == "unchecked"
    # Replacing the certificate the evidence names makes the counterexample stale: it was made
    # with the other one.
    e = rec(p, "e-no")
    wsp.update(p, [put({"id": "e-no", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"certificate": {**cert, "theorem": "Ex.other"}}}, e["rev"])],
               snap_of(work))
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["x-fam"]["state"] == "stale"
    assert any(c.get("evidence") == "e-no" for c in cur["x-fam"]["changes"])


# -- differences, and the two controls ------------------------------------------------------

def align(lid, **target):
    return put({"kind": "alignment", "claim": CLAIM, "requirements": [lid] if lid else [],
                "lean": [{"decl": "Ex.young", **target}]})


def test_an_inherited_section_assumption_is_not_an_extra_lean_hypothesis(work):
    p = opened(work)
    wsp.update(p, [align("r1.1.1", conclusion=True), align("r1.1", binder=1)], snap_of(work))
    b = block(work, p)
    # `hf : Bounded f` has no requirement aligned with it: a hint to inspect, not a finding.
    assert [(h["decl"], h["binder"], h["lean"]) for h in b["hints"]] == \
        [("Ex.young", 2, "hf : Bounded f")]
    assert b["hints"][0]["basis"] == "computed hint"
    assert not b["differences"]
    # The section's opening sentence makes f bounded throughout: aligned with it, the Lean
    # hypothesis is inherited by the claim and no hint remains.
    wsp.update(p, [put({"kind": "requirement", "claim": CLAIM, "local_id": "r0",
                        "form": "assumption", "text": "f is bounded"}),
                   put({"kind": "fragment", "claim": CLAIM, "requirement": "r0",
                        "role": "standing assumption", "origin": "inferred",
                        "region": region(STANDING_LINE), "scope": "the section “Estimates”"}),
                   align("r0", binder=2)], snap_of(work))
    b = block(work, p)
    assert b["hints"] == [] and b["differences"] == []
    assert b["inherited"] == [{"decl": "Ex.young", "binder": 2, "lean": "hf : Bounded f",
                               "requirement": "r0", "from": "the section “Estimates”"}]
    text = "\n".join(est.lines(b))
    assert "inherited from the section “Estimates”" in text and "hint" not in text


def test_a_hint_dismissed_with_a_reason_is_kept_apart(work):
    p = opened(work)
    wsp.update(p, [align("r1.1.1", conclusion=True), align("r1.1", binder=1),
                   put({"id": "f-no", "kind": "finding", "claim": CLAIM,
                        "requirement": "r1.1.1",
                        "difference": {"feature": "additional assumption", "paper": "(none)",
                                       "lean": "hf : Bounded f", "outcome": "no difference",
                                       "why": "every solution has bounded f",
                                       "hint": {"decl": "Ex.young", "binder": 2}},
                        "note": "dismissed"})], snap_of(work))
    b = block(work, p)
    assert b["hints"] == []
    assert [h["settled_by"] for h in b["settled_hints"]] == ["f-no"]
    assert [d["finding"] for d in b["resolved"]] == ["f-no"]


def test_a_representation_difference_resolved_by_a_common_extension_is_not_a_defect(work):
    p = opened(work)
    domain = {"feature": "domain", "paper": "the data on [0, T]",
              "lean": "hEq : ∀ t, b₁ t = b₂ t", "outcome": "difference"}
    # A domain difference states the transport inspected before it is recorded as one.
    with pytest.raises(wsp.WorkspaceError, match="what transport was inspected"):
        wsp.update(p, [put({"kind": "finding", "claim": CLAIM, "requirement": "r1.1.1",
                            "difference": domain})], snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="names its resolution"):
        wsp.update(p, [put({"kind": "finding", "claim": CLAIM, "requirement": "r1.1.1",
                            "difference": {**domain, "outcome": "resolved"}})], snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="attached to the requirement"):
        wsp.update(p, [put({"kind": "finding", "claim": CLAIM,
                            "difference": {**domain, "outcome": "open"}})], snap_of(work))
    wsp.update(p, [
        put({"id": "f-ext", "kind": "finding", "claim": CLAIM, "requirement": "r1.1.1",
             "difference": {**domain, "outcome": "resolved",
                            "resolution": {"by": "common extension",
                                           "text": "extend both coefficients by their values "
                                                   "at T; they agree everywhere"}},
             "note": "an off-horizon representation difference"}),
        put({"id": "f-order", "kind": "finding", "claim": CLAIM, "requirement": "r1.1.1",
             "difference": {"feature": "derivative order", "paper": "m + 4", "lean": "n + 5",
                            "outcome": "difference", "conditions": ["n = m"]},
             "note": "one more derivative"})], snap_of(work))
    for f in ("f-ext", "f-order"):
        wsp.update(p, [{"op": "submit", "id": f, "base_rev": 1}], snap_of(work))
    b = block(work, p)
    assert [d["finding"] for d in b["differences"]] == ["f-order"]
    assert [(d["finding"], d["resolution"]["by"]) for d in b["resolved"]] == \
        [("f-ext", "common extension")]
    text = "\n".join(est.lines(b))
    assert "difference on r1.1.1 (derivative order, a difference): paper m + 4; Lean n + 5" \
        in text
    assert "domain on r1.1.1, resolved by common extension" in text


# -- validation ------------------------------------------------------------------------------

def test_counterexamples_and_certificates_are_validated(work):
    p = opened(work)
    s = snap_of(work)
    cases = [
        ({**FAMILY, "requirement": "r7"}, "no requirement 'r7'"),
        ({**FAMILY, "specialisation": {}}, "a specialisation is"),
        ({**FAMILY, "specialisation": {"assign": {"ε": True}}}, "maps each variable"),
        ({**FAMILY, "reduced": ""}, "reduced obligation"),
        ({**FAMILY, "admissibility": [{"obligation": "x", "state": "verified"}]}, "say how"),
        ({**FAMILY, "samples": [{"C": "big"}]}, "numeric assignments"),
        ({**FAMILY, "reading": ["r1.1"]}, "is not a correction"),
    ]
    for r, msg in cases:
        with pytest.raises(wsp.WorkspaceError, match=msg):
            wsp.update(p, [put({k: v for k, v in r.items() if k != "id"})], s)
    with pytest.raises(wsp.WorkspaceError, match="carries what Lean checked"):
        wsp.update(p, [put({"kind": "evidence", "claim": CLAIM, "ref": {"certificate": {
            "theorem": "Ex.t", "target": "Ex.T", "certifies": "refutes"}}})], s)
    with pytest.raises(wsp.WorkspaceError, match="what it certifies"):
        wsp.update(p, [put({"kind": "evidence", "claim": CLAIM, "ref": {"certificate": {
            "theorem": "Ex.t", "target": "Ex.T", "certifies": "maybe"}}})], s)
    with pytest.raises(wsp.WorkspaceError, match="the verdict"):
        wsp.update(p, [put({"kind": "finding", "claim": CLAIM, "verdict": "wrong"})], s)
    # A counterexample a finding cites is kept while it cites it.
    wsp.update(p, [put(FAMILY), put({"id": "f-c", "kind": "finding", "claim": CLAIM,
                                     "requirement": "r1.1.1", "verdict": "false as printed",
                                     "counterexamples": ["x-fam"]})], s)
    with pytest.raises(wsp.WorkspaceError, match="evidence of f-c"):
        wsp.update(p, [{"op": "delete", "id": "x-fam", "base_rev": 1}], s)
    with pytest.raises(wsp.WorkspaceError, match="used by"):
        wsp.update(p, [{"op": "delete", "id": "r-est", "base_rev": rec(p, "r-est")["rev"]}], s)
    # A verdict with the counterexample it rests on can be submitted without a coverage.
    wsp.update(p, [{"op": "submit", "id": "f-c", "base_rev": 1}], s)
    assert rec(p, "f-c")["state"] == "submitted"


# -- the terminal, the comparison packet and publication ------------------------------------

def test_the_terminal_and_compare_show_the_estimate(work, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_workspace_place", lambda a: (work, work / "site" / "data",
                                                            tmp_path))
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, tmp_path))
    p = opened(work)
    wsp.update(p, [put(FAMILY)], snap_of(work))
    wid = wsp.read(p)["id"]
    code, out, _ = _run(["workspace", "show", "--id", wid], capsys)
    assert code == 0
    assert "estimate r1.1.1, printed reading: there is C (C ≥ 0), independent of ε; for every " \
        "ε (ε > 0): |u| ≤ ε|f| + C/ε" in out
    assert "counterexample x-fam: a candidate counterexample: not yet shown admissible" in out
    assert "to try: ε → ∞, with C fixed" in out
    code, out, _ = _run(["workspace", "show", "--id", wid, "--json"], capsys)
    v = json.loads(out)
    assert v["claims"][CLAIM]["counterexamples"][0]["id"] == "x-fam"
    assert v["claims"][CLAIM]["reading"]["estimates"]["estimates"][0]["requirement"] == "r1.1.1"
    code, out, _ = _run(["compare", "Equation (1)", "--workspace", wid, "--json"], capsys)
    pk = json.loads(out)
    est_ = pk["interpretations"]["requirements"]["estimates"]["estimates"][0]
    assert est_["readings"][0]["counterexamples"][0]["analysis"]["form"] == "family"
    code, out, _ = _run(["compare", "Equation (1)", "--workspace", wid], capsys)
    assert "counterexample x-fam" in out


def test_a_published_audit_carries_the_counterexample_and_its_scope(work):
    p = opened(work)
    cert = {"theorem": "Ex.no_uniform_C", "target": "Ex.UniformC", "certifies": "refutes",
            "type": "LEAN-CERT-TYPE", "target_fingerprint": "a" * 16, "result": "checked",
            "reasons": [], "file": "Ex/Audit.lean"}
    wsp.update(p, [put({"id": "e-no", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"certificate": cert}}),
                   put({**FAMILY, "evidence": ["e-no"], "violation": "CX-VIOLATION"}),
                   put({"id": "x-draft", "kind": "counterexample", "claim": CLAIM,
                        "requirement": "r1.1.1", "specialisation": {"assign": {"ε": 2}},
                        "reduced": "DRAFT-CX", "violation": "v"}),
                   put({"id": "f-step", "kind": "finding", "claim": CLAIM,
                        "requirement": "r1.1.1", "verdict": "false as printed",
                        "counterexamples": ["x-fam"], "note": "n",
                        "difference": {"feature": "domain", "paper": "PAPER-EXPR",
                                       "lean": "LEAN-EXPR", "outcome": "open"}})],
               snap_of(work))
    wsp.update(p, [{"op": "submit", "id": "f-step", "base_rev": 1}], snap_of(work))
    rd, = pw.readings(work, snap_of(work), lambda cid: EVERYTHING, {CLAIM})[CLAIM]
    validate({"schema": pw.SCHEMA, "release": "v-1", "claim": CLAIM, "readings": [rd]},
             "published-work")
    cx, = rd["counterexamples"]
    assert cx["id"] == "x-fam" and cx["analysis"]["form"] == "family"
    assert cx["violation"] == "CX-VIOLATION" and cx["reading_text"].startswith("there is C")
    assert rd["evidence"][0]["ref"]["certificate"]["type"] == "LEAN-CERT-TYPE"
    f = rd["findings"][0]
    assert f["verdict"] == "false as printed" and f["counterexamples"][0]["id"] == "x-fam"
    assert f["difference"]["paper"] == "PAPER-EXPR" and f["difference"]["lean"] == "LEAN-EXPR"
    assert "DRAFT-CX" not in json.dumps(rd)
    assert [r["domain"] for r in rd["requirements"] if r.get("domain")] == ["C ≥ 0", "ε > 0"]
    rd, = pw.readings(work, snap_of(work), lambda cid: CLOSED, {CLAIM})[CLAIM]
    raw = json.dumps(rd, ensure_ascii=False)
    for hidden in ("CX-VIOLATION", "LEAN-CERT-TYPE", "PAPER-EXPR", "LEAN-EXPR",
                   "Ex/Audit.lean"):
        assert hidden not in raw
    # What it can show is still published: it is computed from the published reading.
    assert rd["counterexamples"][0]["analysis"]["standing"] == "candidate"
    assert rd["evidence"][0]["ref"]["certificate"]["result"] == "checked"
