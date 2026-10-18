"""Display words cannot select an assessment, a link result or a scope filter."""

from copy import deepcopy
import itertools
from pathlib import Path
from types import SimpleNamespace

import pytest

from prooflens import status
from prooflens.export import public_claim
from prooflens.manifest import build
from prooflens.simple import link_state


def clause(**values):
    return {"name": "main", "state": "proved", "review": "reviewed", "accept_ok": True, **values}


@pytest.mark.parametrize("scope,clauses,code", [
    ("formal", [], "formal.unspecified"),
    ("formal", [clause()], "formal.accepted"),
    ("formal", [clause(review="pending")], "formal.review-pending"),
    ("formal", [clause(review="author-reviewed")], "formal.author-reviewed"),
    ("formal", [clause(state="open", accept_ok=False)], "formal.open"),
    ("formal", [clause(state="unchecked")], "formal.unchecked"),
    ("definition", [], "definition.unstated"),
    ("definition", [clause(review="pending")], "definition.pending"),
    ("definition", [clause()], "definition.reviewed"),
    ("definition", [clause(review="author-reviewed")], "definition.author-reviewed"),
    ("definition", [clause(state="unchecked")], "definition.unchecked"),
    ("literature", [clause()], "scope.literature"),
    ("formal", [clause(corrects="missing original")], "formal.malformed"),
])
def test_assessment_code_is_not_a_sentence(scope, clauses, code):
    assert status.claim_code({"scope": scope}, clauses) == code
    assert status.result(code)["status_code"] == code


@pytest.mark.parametrize("corrected,partial", itertools.product((False, True), repeat=2))
def test_refutation_dimensions_are_preserved(corrected, partial):
    clauses = [clause(state="refuted", accept_ok=False, refute_ok=True)]
    if corrected:
        clauses.append(clause(name="correction", corrects="main"))
    if partial:
        clauses.append(clause(name="second", state="open", accept_ok=False))
    code = status.claim_code({"scope": "formal"}, clauses)
    assert code == "formal.refuted" + (".corrected" if corrected else "") + (".partial" if partial else "")


def test_renaming_every_label_does_not_change_codes_or_colours(monkeypatch):
    before = deepcopy(status.LABELS)
    monkeypatch.setattr(status, "LABELS", {code: ("Different words", colour) for code, (_, colour) in before.items()})
    for code, (_, colour) in before.items():
        assert status.result(code) == {"status_code": code, "status": "Different words", "class": colour}
    assert status.claim_code({"scope": "formal"}, [clause()]) == "formal.accepted"


@pytest.mark.parametrize("record,code", [
    (None, "link.missing"),
    ({"errors": ["probe-error: timeout"]}, "link.failed"),
    ({"kind": "theorem", "errors": ["probe-error: timeout"]}, "link.failed"),
    ({"errors": ["missing"]}, "link.missing"),
    ({"kind": "def", "errors": []}, "link.definition"),
    ({"kind": "theorem", "errors": [], "sorry": True}, "link.incomplete"),
    ({"kind": "theorem", "errors": ["axioms=[Synthetic.extra]"]}, "link.axioms"),
    ({"kind": "theorem", "errors": [], "sorry": False}, "link.checked"),
])
def test_link_code_comes_from_probe(record, code):
    assert link_state(record)["status_code"] == code


def test_unknown_code_is_not_a_positive_fallback():
    with pytest.raises(KeyError):
        status.result("made-up")


def test_published_audit_words_are_not_interpreted_as_local_evidence():
    from prooflens.paper import _state
    for words in ("formal: accepted", "definitely proved", "not checked", "Some other language"):
        record = _state([{"name": "Synthetic.theorem"}], {"status": words, "class": "accepted"})
        assert record == {"status": words, "class": "accepted", "status_code": "published-audit"}
    assert _state([{}], None, True)["status_code"] == "link.not-in-audit"
    assert _state([{}], None, False)["status_code"] == "link.no-audit"


def test_codes_survive_manifest_and_publication_without_private_content(tmp_path):
    from test_source_regions import assessed, claim
    rec = assessed(tmp_path, claim(), {"mode": "latex", "envs": [], "anchors": [], "regions": {}})
    _, chunks, _ = build(rec, "synthetic")
    chunk = next(iter(chunks.values()))
    pub = SimpleNamespace(source_text=False, lean=False, reviews=False)
    shown = public_claim(chunk, pub)
    assert shown["status_code"] == "formal.accepted"
    assert shown["source_matches"] is False
    assert shown["statement_tex"] is None
    assert shown["clauses"][0]["statement"] is None


def test_frontend_does_not_classify_human_readable_status_strings():
    root = Path(__file__).resolve().parents[2] / "web/src"
    import re
    for path in root.rglob("*"):
        if path.suffix not in (".js", ".svelte"):
            continue
        text = path.read_text()
        assert not re.search(r'(?:String\([^\n]*\.status\)|\.status)\.(?:startsWith|includes)\(', text), path
        assert 'const s = l.status' not in text, path
