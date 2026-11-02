"""Saved investigations travel with a published audit (#462): each published finding carries what
it rests on, and each version map its workspace keeps is published per claim with what it
reopens, as the paper's publication settings allow. Only accepted records are published, each
with its author; a draft is never published, and the site's loader refuses revisions that name
a finding the audit does not publish. Synthetic papers and builds stand in for real ones, so no
Lean runs."""

import copy
import json
import shutil

import pytest

from test_finding_dependencies import READING, make_build as dep_build
from test_reopen import (  # noqa: F401  (`setting` is a fixture)
    WHO, by_id, setting, site, submit,
)

from prooflens import published_work as pw
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.published import AuditError
from prooflens.schemas import validate
from prooflens.targets import Snapshot

EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
NOTHING = Publish(pdf=False, source_text=False, lean=False, reviews=False)


def put(rec):
    return {"op": "put", "record": rec}


def body(claim, readings):
    """A claim's published file, checked against its schema."""
    doc = {"schema": pw.SCHEMA, "release": "v-1", "claim": claim, "readings": readings}
    validate(doc, "published-work")
    return doc


# -- what a finding rests on ------------------------------------------------------------------

def _young(work):
    snap = Snapshot(work / "site" / "data")
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, READING + [
        put({"id": "f-bound", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "basis": "direct", "evidence": ["e-young", "e-quote"],
             "note": "The Lean states the bound."}),
        put({"id": "f-draft", "kind": "finding", "claim": "P:eq:young", "coverage": "partial",
             "evidence": ["e-young"], "note": "DRAFT-FINDING-NOTE"})], snap)
    wsp.update(p, [submit("f-bound")[0]], snap)
    return p, snap


def test_a_published_finding_carries_what_it_rests_on(tmp_path):
    work = tmp_path / ".machinechecked"
    dep_build(work)
    p, snap = _young(work)
    found = pw.readings(work, snap, lambda cid: EVERYTHING, {"P:eq:young"})
    raw = json.dumps(found, ensure_ascii=False)
    assert "f-draft" not in raw and "DRAFT-FINDING-NOTE" not in raw
    (rd,) = found["P:eq:young"]
    body("P:eq:young", [rd])
    (f,) = rd["findings"]
    recorded = wsp.read(p)["records"]["f-bound"]["dependencies"]
    deps = f["dependencies"]
    assert deps["kinds"] == recorded["kinds"] and deps["at"] == recorded["at"]
    assert [(it["dependency"], it.get("record")) for it in deps["items"]] == \
        [(it["dependency"], it.get("record")) for it in recorded["items"]]
    by = {(it["dependency"], it.get("record")): it for it in deps["items"]}
    # With the source text and the Lean: the passage's place, the quotation, the target's text.
    assert by[("context", "p-eps")]["region"]["start_line"] == 4
    assert by[("paper", "e-quote")]["ref"]["paper"]["quote"] == "Every solution is bounded."
    assert by[("object", "a-bound")]["lean"][0]["target"] == "|u| ≤ ε * Ex.norm f + C / ε"
    # The cited declaration with the definitions its statement uses and what it expands.
    ref = by[("declaration", "e-young")]["ref"]
    assert ref["closure"] == {"Ex.norm": "fp:norm-1", "Ex.Sol": "fp:sol-1"}
    assert ref["expansions"][0]["fingerprint"] == "fp:norm-1"


def test_a_finding_s_dependencies_follow_the_publication_settings(tmp_path):
    work = tmp_path / ".machinechecked"
    dep_build(work)
    _, snap = _young(work)
    found = pw.readings(work, snap, lambda cid: NOTHING, {"P:eq:young"})
    raw = json.dumps(found, ensure_ascii=False)
    for word in ("Every solution is bounded.", "|u| ≤ ε", "paper.tex", "DRAFT-FINDING-NOTE"):
        assert word not in raw, word
    (rd,) = found["P:eq:young"]
    body("P:eq:young", [rd])
    by = {(it["dependency"], it.get("record")): it for it in rd["findings"][0]["dependencies"]
          ["items"]}
    # A passage keeps its digest, a quotation its claim and version, a target its declaration and
    # pins: what identifies them, without the paper's or the Lean's text.
    assert set(by[("context", "p-eps")]["region"]) == {"paper", "sha256"}
    assert by[("paper", "e-quote")]["ref"] == {"paper": {"claim": "P:thm:main",
                                                         "sha256": "s-main-1"}}
    (t,) = by[("object", "a-bound")]["lean"]
    assert "target" not in t and t["decl"] == "Ex.young" and t["conclusion"] is True


def test_a_sub_term_s_text_in_a_change_is_published_only_with_the_lean():
    changes = [{"decl": "Ex.f", "at": "/1", "was": "x + 1", "now": "x + 2",
                "reason": "Ex.f: the sub-term /1 is now 'x + 2', not 'x + 1'"},
               {"region": "paper.tex:4", "lines": [4], "was": "a", "now": "b"}]
    closed = pw._changes(changes, NOTHING)
    assert "x + 1" not in json.dumps(closed) and closed[0]["at"] == "/1"
    assert closed[1] == {"was": "a", "now": "b"}
    assert pw._changes(changes, EVERYTHING) == changes


# -- what a kept version map reopens ----------------------------------------------------------

def _published(setting, tmp_path, pub):
    """The workspace keeps the map, a draft is added, the later release is built, and its data
    is published with the records."""
    p, work = setting["path"], setting["work"]
    snap = Snapshot(work / "site" / "data")
    wsp.update(p, [{"op": "version-map", "map": setting["map"]},
                   put({"id": "f-draft", "kind": "finding", "claim": "T:thm:edit",
                        "coverage": "partial", "note": "DRAFT-FINDING-NOTE"})], snap)
    site(work, "r-2", setting["new"], setting["b"])
    data = tmp_path / "out" / "data"
    shutil.copytree(work / "site" / "data", data)
    pw.write(data, work, lambda cid: pub)
    out = {}
    for f in (data / "work").glob("*.json"):
        doc = json.loads(f.read_text())
        validate(doc, "published-work")
        out[doc["claim"]] = doc
    return out


def _revision(docs, cid):
    (rd,) = docs[cid]["readings"]
    (rv,) = rd["revisions"]
    return rd, rv


def test_a_kept_map_is_published_with_what_it_reopens(setting, tmp_path):
    docs = _published(setting, tmp_path, EVERYTHING)
    raw = json.dumps(docs, ensure_ascii=False)
    assert "f-draft" not in raw and "DRAFT-FINDING-NOTE" not in raw
    rd, rv = _revision(docs, "T:thm:edit")
    assert rv["map"]["paper"] == "T" and rv["map"]["kept_by"] == WHO["id"]
    assert (rv["map"]["from"]["release"], rv["map"]["to"]["release"]) == ("r-1", "r-2")
    assert rv["build_checked"] is True
    (row,) = rv["claims"]
    assert row["class"] == "changed"
    assert (row["from"]["number"], row["to"]["number"]) == ("Theorem 2.2", "Theorem 2.3")
    assert "recorded" not in row["from"], "neither release's status is published with the map"
    (f,) = rv["findings"]
    assert f["id"] == "f-edit" and f["state"] == "reopened"
    assert f["id"] in {x["id"] for x in rd["findings"]}
    (o,) = f["paper"]
    assert "+The bound holds with constant $3$." in o["change"]["diff"]
    assert o["question"] == ("Does finding f-edit still hold for the changed text of "
                             "Theorem 2.3 (T:thm:edit)?")
    assert f["build"]["state"] == "current"
    # A moved claim keeps its finding current, and one quoting a changed passage is reopened.
    _, rv = _revision(docs, "T:thm:moved")
    assert {x["id"]: x["state"] for x in rv["findings"]} == {"f-moved": "current",
                                                             "f-moved-quote": "reopened"}
    assert {r["id"]: r["state"] for r in rv["evidence"]} == {"e-quote": "reopened"}
    # A passage attached to a requirement, followed by its text.
    _, rv = _revision(docs, "T:eq:young")
    assert {r["id"]: r["state"] for r in rv["passages"]} == {"p-eps": "reopened",
                                                             "p-c": "current"}
    # A definition the claim's Lean relies on reopens the finding citing that Lean; one whose
    # cited declaration's definitions were not recorded is not known to be current.
    _, rv = _revision(docs, "T:thm:keep")
    f = by_id(rv)
    assert (f["f-keep-lean"]["state"], f["f-keep-note"]["state"],
            f["f-keep-other"]["state"]) == ("reopened", "current", "unchecked")
    assert "Ex.other" in f["f-keep-other"]["paper"][0]["why"]
    # A claim the published build does not have publishes nothing, its map entry included.
    assert "T:eq:twice" not in docs and "T:thm:gone" not in docs


def test_a_kept_map_without_the_source_text_quotes_no_place_or_text_of_the_paper(setting,
                                                                                 tmp_path):
    docs = _published(setting, tmp_path, NOTHING)
    raw = json.dumps(docs, ensure_ascii=False)
    for word in ("paper.tex", "\\dimK", "constant $3$", "constant $2$", "ε \\in", "DRAFT",
                 "f-draft", "The constant is 2."):
        assert word not in raw, word
    _, rv = _revision(docs, "T:thm:edit")
    (row,) = rv["claims"]
    assert row["reason"] == "its text changed" and "location" not in row["to"]
    (f,) = rv["findings"]
    (o,) = f["paper"]
    assert o["state"] == "reopened" and "diff" not in o["change"]
    assert o["text"] == "the passage of T:thm:edit"
    assert o["question"] == ("Does finding f-edit still hold for the changed text of "
                             "Theorem 2.3 (T:thm:edit)?")
    # A changed macro definition is named without the macro.
    _, rv = _revision(docs, "T:thm:macro")
    (o,) = rv["findings"][0]["paper"]
    assert o["change"]["reason"] == ("the same text; what it is read with changed (the "
                                     "definition of a macro it uses changed)")
    # A region keeps its digest only, and its question names its role, not its place.
    _, rv = _revision(docs, "T:eq:young")
    f = by_id(rv)["f-domain"]
    (o,) = [o for o in f["paper"] if o["dependency"].get("record") == "p-eps"]
    assert set(o["dependency"]["region"]) == {"paper", "sha256"}
    assert o["question"] == ("Does finding f-domain (on r1) still hold now that the passage it "
                             "reads as the quantifier domain of r1 changed?")
    # Why a part is not known to be current, in words that name claims and declarations only.
    _, rv = _revision(docs, "T:thm:keep")
    (o,) = by_id(rv)["f-keep-other"]["paper"]
    assert o["state"] == "unchecked" and "Ex.other" in o["why"]


def test_the_loader_refuses_revisions_naming_a_finding_not_published(tmp_path):
    import published_fixture as pf
    cid = "T:one"
    fname = next(c["file"] for c in pf.files()["data/index.json"]["claims"] if c["id"] == cid)
    data = pf.with_work(pf.files(), cid)
    rd = data[f"data/work/{fname}"]["readings"][0]
    rev = {"map": {"paper": "T", "from": {"release": "r-0"}, "to": {"release": "r-1"},
                   "kept_by": "human:A-Auditor"},
           "build_checked": False, "claims": [], "evidence": [], "passages": [],
           "findings": [{"id": "f2", "claim": cid, "state": "current",
                         "paper": [{"state": "current", "text": "the passage of T:one"}]}]}
    rd["revisions"] = [rev]
    got = pf.snapshot(data)
    rec = next(c["record"] for c in got["claims"] if c["id"] == cid)
    assert rec["work"]["readings"][0]["revisions"][0]["findings"][0]["id"] == "f2"
    bad = copy.deepcopy(data)
    bad[f"data/work/{fname}"]["readings"][0]["revisions"][0]["findings"][0]["id"] = "f-draft"
    with pytest.raises(AuditError, match="does not publish"):
        pf.snapshot(bad)
    # A dependency's region carries no text of the paper.
    bad = copy.deepcopy(data)
    bad[f"data/work/{fname}"]["readings"][0]["findings"][1]["dependencies"] = {
        "kinds": [], "unknown": [],
        "items": [{"dependency": "context", "region": {"paper": "T", "text": "PRINTED"}}]}
    with pytest.raises(AuditError, match="published-work"):
        pf.snapshot(bad)
