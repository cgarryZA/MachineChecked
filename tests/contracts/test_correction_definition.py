"""A definition only a correction uses (#617): the formalisation introduced it, and the paper's
passages do not define it. Step 1 reads the printed passages as before; step 2 names the
correcting clause by its place and shows its proposition, with no wording of the addition (the
author's, after the verdict); "faithful to the correction" is offered to it, and promotion
accepts it only while the evidence still shows the definition used only by a correction. The
site is the synthetic one of `test_review_withholds_outcome.py`; nothing here builds Lean."""

import json

import pytest

from prooflens import manifest as mf
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from test_review_withholds_outcome import FIXED_SPEC, SPEC, TEXTS, withheld, write_spec_site

NEW = "Syn.Pos"
INTRODUCED = [{"claim": "S:prop:p", "clause": 2, "of_clause": 1, "relation": "corrects"}]
WHO = rc.parse_reviewer("human:Correction-Reviewer")


def body(extra_defs=()):
    """Evidence in which the printed clause's proposition uses `Syn.P`, and the correcting
    clause's uses it and `Syn.Pos`."""
    return {"inventory": {"claims": [
        {"id": "S:prop:p", "clauses": [{"name": "printed", "spec": SPEC},
                                       {"name": "fixed", "spec": FIXED_SPEC,
                                        "corrects": "printed"}]},
        {"id": "S:def:other", "scope": "definition",
         "clauses": [{"name": "main", "defs": list(extra_defs)}]}]},
        "lean": {"specs": {SPEC: {"closure": ["Syn.P"]},
                           FIXED_SPEC: {"closure": ["Syn.P", NEW]}}}}


def test_a_definition_only_a_correction_uses_is_found_by_its_clauses():
    assert mf.introduced_by_correction(body()) == {NEW: INTRODUCED}
    # One a printed clause maps as a definition is the paper's.
    assert mf.introduced_by_correction(body([NEW])) == {}
    # Promotion asks the same of the current evidence.
    assert pr.corrects_a_clause(body(), {"kind": "def", "name": NEW})
    assert not pr.corrects_a_clause(body([NEW]), {"kind": "def", "name": NEW})
    assert not pr.corrects_a_clause(body(), {"kind": "def", "name": "Syn.P"})


def with_new_definition(tmp_path):
    """The synthetic site, with `Syn.Pos` a definition only the correction uses, and its unit."""
    data = write_spec_site(tmp_path)
    f = data / "claims" / "S_prop_p.json"
    ch = json.loads(f.read_text())
    ch["decls"] = {NEW: "k-pos"}
    f.write_text(json.dumps(ch))
    rec = {"name": NEW, "kind": "def", "module": "Syn.Defs", "fingerprint": "fp-pos",
           "legacy_hash": "0" * 32,
           "signature": {"text": "ℕ → Prop", "segments": [{"t": "ℕ → Prop"}]},
           "value": {"text": "fun n => 0 < n", "segments": [{"t": "fun n => 0 < n"}]},
           "uses": [], "review": {"state": "pending", "current": [], "stale": [],
                                  "source_sha256": {}},
           "introduced_by_correction": INTRODUCED}
    (data / "decls" / "k-pos.json").write_text(json.dumps(rec))
    index = json.loads((data / "index.json").read_text())
    queue = rq.assurance_queue(index, {"S_prop_p.json": ch}, {"k-pos": rec}, ["author"])
    (data / "review-queue.json").write_text(json.dumps(queue))
    return data.parent.parent


def test_step_2_names_the_correcting_clause_and_offers_the_correction_verdict(tmp_path):
    work = with_new_definition(tmp_path)
    s = rc.Session(work, WHO)
    uid = f"def:{NEW}"
    assert s.unit(uid)["introduced_by"] == INTRODUCED
    # Step 1 is the paper's passages, as for any definition.
    read = s.read(uid) + json.dumps(s.read(uid, as_json=True))
    assert "introduced" not in read and "correct" not in read
    withheld(read)
    s.lock(uid, TEXTS["reading.md"])
    text, pk = s.show(uid), s.show(uid, as_json=True)
    assert ("Only clause 2 of S:prop:p, which corrects clause 1, uses this definition: the "
            "formalisation introduced it") in text
    assert "The correcting proposition that uses it, clause 2 of S:prop:p:" in text
    assert pk["unit"]["introduced_by"] == INTRODUCED
    roles = [d["role"] for d in pk["lean"]["declarations"]]
    assert roles == ["definition under review", "correction that uses it"]
    # Nothing of the correction's wording or outcome before the verdict.
    withheld(text)
    withheld(json.dumps(pk, ensure_ascii=False))
    assert "outcome" in [w["section"] for w in pk["retrieval"]["withheld"]]
    s.decide(uid, "faithful to the correction", TEXTS["comparison.md"])
    assert s.work["drafts"][uid]["verdict"] == "faithful to the correction"


def test_the_correction_verdict_is_refused_for_another_definition(tmp_path):
    work = with_new_definition(tmp_path)
    q = work / "site" / "data" / "review-queue.json"
    queue = json.loads(q.read_text())
    for u in queue["units"]:
        u.pop("introduced_by", None)
    q.write_text(json.dumps(queue))
    s = rc.Session(work, WHO)
    uid = f"def:{NEW}"
    s.read(uid)
    s.lock(uid, TEXTS["reading.md"])
    s.show(uid)
    with pytest.raises(rc.ReviewError, match="or to a definition only a correction uses"):
        s.decide(uid, "faithful to the correction", TEXTS["comparison.md"])
