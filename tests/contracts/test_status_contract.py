"""Structured assurance facts survive copy changes, exports and public paper views."""
import itertools
import json
from types import SimpleNamespace

import pytest

from prooflens.assess import Assessor, OUT_OF_SCOPE
from prooflens.export import public_claim
from prooflens.manifest import clause_evidence, build
from prooflens.schemas import validate
from prooflens.simple import link_state, resolve_link
from prooflens.status import STATUSES, fields, source_evidence


def clause(state="proved", review="reviewed", replay="not-run", **extra):
    return {"name": "main", "state": state, "review": review, "spec": "Synthetic.Spec",
            "accept_ok": state == "proved", "refute_ok": state == "refuted",
            "checks": {"spec": {"ok": True}, "accept": {"ok": True, "errors": [],
                       "sorry": False, "axioms": []}, "replay": {"state": replay}}, **extra}


@pytest.mark.parametrize("review,code", [
    ("reviewed", "formal.accepted"), ("author-reviewed", "formal.author-reviewed"),
    ("pending", "formal.review-pending"), ("stale", "formal.review-pending")])
@pytest.mark.parametrize("replay", ["pass", "not-run", "unverified"])
@pytest.mark.parametrize("matches", [True, False, None])
def test_proof_review_replay_and_source_are_independent(review, code, replay, matches):
    cl = clause(review=review, replay=replay)
    assert Assessor.claim_code({"scope": "formal"}, [cl]) == code
    ev = clause_evidence(cl, {"kind": "approximate"}, "latex", matches)
    assert ev["formal"]["state"] == "proved"
    assert ev["review"]["state"] == review
    assert ev["replay"]["state"] == replay
    assert ev["source"] == {"state": "pass" if matches is True else "fail" if matches is False else "none",
                            "placement": "approximate"}


def test_all_assessor_codes_have_one_presentation_and_copy_cannot_change_them(monkeypatch):
    cases = [(scope, []) for scope in OUT_OF_SCOPE]
    for scope in ["formal", "definition"]:
        cases += [(scope, [])]
        cases += [(scope, [clause(state, review)]) for state, review in
                  itertools.product(["proved", "open", "unchecked", "stated"],
                                    ["reviewed", "author-reviewed", "pending"])]
    cases += [("formal", [clause(corrects="missing")])]
    for fixed, rest in itertools.product([False, True], repeat=2):
        cases.append(("formal", [clause("refuted")] + ([clause(corrects="main")] if fixed else [])
                      + ([clause("open", name="other")] if rest else [])))
    before = [Assessor.claim_code({"scope": scope}, cls) for scope, cls in cases]
    assert set(before) == {c for c in STATUSES if c.split('.')[0] in {"formal", "definition", "scope"}}
    for code in before:
        monkeypatch.setitem(STATUSES, code, {**STATUSES[code], "label": "entirely different copy"})
    assert [Assessor.claim_code({"scope": scope}, cls) for scope, cls in cases] == before


@pytest.mark.parametrize("rec,code", [
    (None, "link.missing"), ({"errors": ["missing"]}, "link.missing"),
    ({"kind": "def"}, "link.definition"),
    ({"kind": "theorem", "sorry": True}, "link.incomplete"),
    ({"kind": "theorem", "errors": ["axioms=Synthetic.extra"]}, "link.axioms"),
    ({"kind": "theorem"}, "link.checked")])
def test_link_codes_do_not_claim_correspondence_or_replay(rec, code):
    assert link_state(rec) == fields(code)


def test_module_failures_have_codes_and_separate_diagnostics(tmp_path):
    for unbuilt, failed, code in [(["M"], {}, "link.module-unbuilt"),
                                  ([], {"M": "error"}, "link.module-failed")]:
        rec, state = resolve_link("Synthetic.x", [], "M", tmp_path, unbuilt, failed)
        assert rec is None and state["status_code"] == code and "M" in state["status_detail"]
    _, state = resolve_link("Synthetic.x", [{"module": "A"}, {"module": "B"}], None, tmp_path, [], {})
    assert state["status_code"] == "link.ambiguous"


def test_pdf_integrity_is_not_location_precision_or_correspondence():
    anchor = {"kind": "approximate"}
    for paper, integrity in [({}, "unpinned"), ({"pdf_pinned": "a"}, "unknown"),
                             ({"pdf_pinned": "a", "pdf_sha256": "a"}, "matched"),
                             ({"pdf_pinned": "a", "pdf_sha256": "b"}, "mismatch")]:
        assert source_evidence(anchor, "pdf", paper=paper) == {
            "state": "pdf-only", "placement": "approximate", "pdf_integrity": integrity}


def synthetic_evidence(cl):
    claim = {"id": "P:synthetic", "paper": "P", "scope": "formal", "clauses": []}
    assessed = {"id": claim["id"], **fields(Assessor.claim_code(claim, [cl])), "clauses": [cl]}
    return {"id": "a" * 64, "created": "2026-01-01", "body": {
        "inventory": {"claims": [claim]}, "lean": {}, "tex": {"P": {"mode": "pdf"}},
        "assessment": {"claims": [assessed], "findings": []},
        "provenance": {"project": {}, "tool": {}, "papers": {"P": {"mode": "pdf"}}}}}


def test_manifest_export_search_and_schemas_keep_codes_and_facts():
    from prooflens.manifest import search_index
    index, chunks, _ = build(synthetic_evidence(clause()), "test")
    validate(index, "manifest-index")
    c = next(iter(chunks.values()))
    validate(c, "manifest-claim")
    public = public_claim(c, SimpleNamespace(source_text=False, lean=False, reviews=False))
    validate(public, "manifest-claim")
    assert public["clauses"][0]["evidence"] == c["clauses"][0]["evidence"]
    assert public["status_code"] == index["claims"][0]["status_code"] == "formal.accepted"
    assert search_index(index, chunks)["claims"][0]["status_code"] == "formal.accepted"
    assert public["source_evidence"]["state"] == "pdf-only"


def test_old_assessment_requires_rebuild_instead_of_parsing_its_label():
    evidence = synthetic_evidence(clause())
    del evidence["body"]["assessment"]["claims"][0]["status_code"]
    with pytest.raises(ValueError, match="rebuild"):
        build(evidence, "old")


def test_unknown_public_audit_code_is_not_upgraded_from_its_text(tmp_path):
    from prooflens.paper import apply_audits, write_paper_site
    claims = [{"key": "t-1", "number": "Theorem 1", "kind": "theorem", "links": [], "anchor": None}]
    apply_audits(claims, {"a/project": {"claims": [{"id": "x", "number": "Theorem 1",
        "status_code": "future.accepted", "status": "formal: accepted", "class": "accepted"}]}})
    index = write_paper_site(tmp_path, {"formalisations": [{"repository": "a/project"}]}, claims, None, None)
    assert index["claims"][0]["status_code"] == "unknown"
    assert index["claims"][0]["class"] == "unspecified"


def test_published_claim_status_does_not_prove_every_named_link(tmp_path):
    from prooflens.paper import apply_audits, write_paper_site
    claims = [{"key": "t-1", "number": "Theorem 1", "kind": "theorem", "links": [
        {"name": "Synthetic.spec", "repository": "a/project"}], "anchor": None}]
    apply_audits(claims, {"a/project": {"claims": [{"id": "x", "number": "Theorem 1", **fields("formal.accepted")}]}})
    index = write_paper_site(tmp_path, {"formalisations": [{"repository": "a/project"}]}, claims, None, None)
    c = json.loads((tmp_path / "data/claims" / index["claims"][0]["file"]).read_text())
    assert c["status_code"] == "formal.accepted"
    assert c["links"][0]["status_code"] == "link.claim-audit"
    assert c["links"][0]["class"] == "declared"
