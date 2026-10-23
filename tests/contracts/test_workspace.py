"""The saved investigation (`prooflens/workspace@1`, #143): validated record writes, revisions
and conflicts, supersession, currency against a changed build, mode and exposure, export and
import, and the local reader's interface. A small synthetic build stands in for site data, so
these tests run no Lean."""

import json
import threading
import types
import urllib.error
import urllib.request

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.server import make_server
from prooflens.targets import Snapshot, TargetError

WHO = rc.parse_reviewer("human:A-Auditor")
OTHER = rc.parse_reviewer("human:B-Auditor")


def _claim(cid, number, kind, key, sha, links=(), decls=None):
    return {"id": cid, "paper": "P", "number": number, "kind": kind, "key": key,
            "source_sha256": sha, "links": [{"name": n, "fingerprint": f} for n, f in links],
            "suggestions": [], "clauses": [], "decls": decls or {}}


def make_build(work, fp_bound="fp:bound-1", fp_tri="fp:tri-1", fp_tri_f="fp:tri_f-1",
               sha_bound="s-bound-1", release="v-1"):
    """A synthetic build's site data under `work/site/data`: four claims (two share the number
    2.3), a theorem and a definition with a generated constant."""
    data = work / "site" / "data"
    claims = [
        _claim("P:lem:bound", "Lemma 2.3", "lemma", "lem:bound", sha_bound,
               [("Ex.inverse_bound", fp_bound)], {"Ex.tri": "k-tri", "Ex.tri._f": "k-tri-f"}),
        _claim("P:rem-2.3", "Remark 2.3", "remark", "remark-2.3", "s-rem"),
        _claim("P:thm:main", "Theorem 1", "theorem", "thm:main", "s-main",
               [("Ex.main", "fp:main-1")]),
        _claim("P:def:tri", "Definition 4", "definition", "def:tri", "s-tri",
               decls={"Ex.tri": "k-tri", "Ex.tri._f": "k-tri-f"}),
    ]
    (data / "claims").mkdir(parents=True, exist_ok=True)
    (data / "decls").mkdir(parents=True, exist_ok=True)
    for c in claims:
        (data / "claims" / f"{c['key'].replace(':', '_')}.json").write_text(json.dumps(c))
    for key, name, fp in (("k-tri", "Ex.tri", fp_tri), ("k-tri-f", "Ex.tri._f", fp_tri_f)):
        (data / "decls" / f"{key}.json").write_text(json.dumps({"name": name, "fingerprint": fp,
                                                                  "kind": "def"}))
    index = {"schema": "prooflens/manifest@1", "release": release,
             "project": {"name": "ex", "commit": "abc123"},
             "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123",
                         "pdf_sha256": "pdf-1"}],
             "claims": [{"id": c["id"], "paper": "P", "number": c["number"], "kind": c["kind"],
                         "file": f"{c['key'].replace(':', '_')}.json"} for c in claims]}
    (data / "index.json").write_text(json.dumps(index))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Ex.Basic"}
         for n in ("Ex.inverse_bound", "Ex.inverse_solves", "Ex.main", "Ex.tri")]))
    return Snapshot(data)


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w)
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def opened(work, who=WHO, mode="independent"):
    return wsp.open_for(work, who, mode, sources=snap_of(work).sources())


def put(rec, base=None):
    op = {"op": "put", "record": rec}
    if base is not None:
        op["base_rev"] = base
    return op


EVIDENCE = [put({"id": "e-bound", "kind": "evidence", "claim": "Lemma 2.3",
                 "ref": {"decl": "Ex.inverse_bound"}, "role": "supports"}),
            put({"id": "e-tri", "kind": "evidence", "claim": "lem:bound",
                 "ref": {"decl": "Ex.tri"}, "role": "context"}),
            put({"id": "e-main", "kind": "evidence", "claim": "Theorem 1",
                 "ref": {"decl": "Ex.main"}, "role": "supports"})]
FINDINGS = [put({"id": "f-bound", "kind": "finding", "claim": "P:lem:bound",
                 "coverage": "changed", "evidence": ["e-bound", "e-tri"],
                 "note": "The bound uses one more derivative."}),
            put({"id": "f-main", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
                 "evidence": ["e-main"], "note": "Direct."})]


# -- targets ---------------------------------------------------------------------------------

def test_claims_resolve_by_id_key_number_and_refuse_ambiguity(work):
    s = snap_of(work)
    assert s.resolve_claim("P:lem:bound") == "P:lem:bound"
    assert s.resolve_claim("lem:bound") == "P:lem:bound"
    assert s.resolve_claim("LEM:Bound") == "P:lem:bound"
    assert s.resolve_claim("lemma 2.3") == "P:lem:bound"
    assert s.resolve_claim("1") == "P:thm:main"
    with pytest.raises(TargetError) as e:
        s.resolve_claim("2.3")
    assert e.value.kind == "ambiguous"
    assert {c["id"] for c in e.value.candidates} == {"P:lem:bound", "P:rem-2.3"}
    with pytest.raises(TargetError) as e:
        s.resolve_claim("Lemma 2.4")
    assert "P:lem:bound" in [c["id"] for c in e.value.candidates]


# -- records ---------------------------------------------------------------------------------

def test_records_are_validated_and_a_refused_edit_writes_nothing(work):
    p = opened(work)
    before = p.read_bytes()
    bad = [
        [put({"kind": "evidence", "claim": "Lemma 9", "ref": {"decl": "Ex.main"}})],
        [put({"kind": "evidence", "claim": "1", "ref": {"decl": "Ex.nope"}})],
        [put({"kind": "finding", "claim": "1", "coverage": "mostly"})],
        [put({"kind": "finding", "claim": "1", "coverage": "unresolved"})],
        [put({"kind": "finding", "claim": "1", "coverage": "full", "evidence": ["e-x"]})],
        [put({"kind": "question", "claim": "1", "text": " "})],
        [put({"kind": "evidence", "claim": "1", "ref": {"decl": "Ex.main"}, "role": "maybe"})],
        # A basis and its fields go with the coverage they support (the links file's rules).
        [put({"kind": "finding", "claim": "1", "basis": "direct"})],
        [put({"kind": "finding", "claim": "1", "coverage": "full", "basis": "checked"})],
        [put({"kind": "finding", "claim": "1", "coverage": "full", "basis": "direct",
              "argument": "x"})],
        [put({"kind": "finding", "claim": "1", "coverage": "full",
              "basis": "reviewed_composition", "bridge": {"theorem": "A", "target": "B"}})],
        [put({"kind": "finding", "claim": "1", "coverage": "full", "question": "Which?"})],
        [put({"kind": "finding", "claim": "1", "coverage": "composed", "basis": "direct"})],
    ]
    for ops in bad:
        with pytest.raises(wsp.WorkspaceError):
            wsp.update(p, ops, snap_of(work))
    assert p.read_bytes() == before
    # Evidence for one claim cannot support a finding about another.
    wsp.update(p, EVIDENCE, snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="evidence for P:thm:main"):
        wsp.update(p, [put({"kind": "finding", "claim": "lem:bound", "coverage": "full",
                            "evidence": ["e-main"]})], snap_of(work))


def test_evidence_pins_what_the_build_shows_and_findings_pin_the_statement(work):
    p = opened(work)
    wsp.update(p, EVIDENCE + FINDINGS, snap_of(work))
    ws = wsp.read(p)
    e = ws["records"]["e-bound"]
    assert e["claim"] == "P:lem:bound" and e["ref"]["build"] == "built"
    assert e["ref"]["fingerprint"] == "fp:bound-1" and e["created_by"] == WHO["id"]
    assert ws["records"]["f-bound"]["pins"] == {"release": "v-1", "statement_sha256": "s-bound-1"}
    assert ws["records"]["f-bound"]["state"] == "draft"


def test_disjoint_edits_are_kept_and_a_stale_edit_is_a_conflict_keeping_both(work):
    p = opened(work)
    wsp.update(p, EVIDENCE + FINDINGS, snap_of(work))
    # Two clients read revision 1 of both findings.
    a = put({"id": "f-bound", "kind": "finding", "claim": "P:lem:bound", "coverage": "partial",
             "evidence": ["e-bound"], "note": "A: only the first clause."}, base=1)
    b = put({"id": "f-main", "kind": "finding", "claim": "P:thm:main", "coverage": "related",
             "evidence": ["e-main"], "note": "B: a weaker statement."}, base=1)
    wsp.update(p, [a], snap_of(work), by="human:A-Auditor")
    wsp.update(p, [b], snap_of(work), by="human:B-Auditor")
    ws = wsp.read(p)
    assert ws["records"]["f-bound"]["note"].startswith("A:")
    assert ws["records"]["f-main"]["note"].startswith("B:")
    assert ws["records"]["f-main"]["updated_by"] == "human:B-Auditor"
    # B edits f-bound from revision 1, after A's edit made it revision 2.
    c = put({"id": "f-bound", "kind": "finding", "claim": "P:lem:bound", "coverage": "full",
             "evidence": ["e-bound"], "note": "B: every clause."}, base=1)
    with pytest.raises(wsp.Conflict) as e:
        wsp.update(p, [c], snap_of(work), by="human:B-Auditor")
    (conf,) = e.value.conflicts
    assert conf["current"]["note"].startswith("A:") and conf["current"]["rev"] == 2
    assert conf["proposed"]["record"]["note"] == "B: every clause."
    ws = wsp.read(p)
    assert ws["records"]["f-bound"]["note"].startswith("A:")       # A's edit is kept
    assert ws["conflicts"][-1]["proposed"]["record"]["note"] == "B: every clause."   # and B's


def test_a_repeated_request_changes_nothing(work):
    p = opened(work)
    first = wsp.update(p, EVIDENCE + FINDINGS, snap_of(work), op_id="req-1")
    again = wsp.update(p, EVIDENCE + FINDINGS, snap_of(work), op_id="req-1")
    assert again["repeated"] and again["revision"] == first["revision"]
    # The same creates without the request id are recognised as the same records.
    wsp.update(p, [put({"kind": "question", "claim": "1", "text": "Which norm?", "id": "q-1"})],
               snap_of(work))
    ack = wsp.update(p, [put({"kind": "question", "claim": "1", "text": "Which norm?",
                              "id": "q-1"})], snap_of(work))
    ws = wsp.read(p)
    assert ack["changed"] == [] and len(ws["records"]) == 6
    assert sum(r["kind"] == "finding" for r in ws["records"].values()) == 2


def test_a_submitted_finding_is_superseded_with_a_reason_and_kept(work):
    p = opened(work)
    wsp.update(p, EVIDENCE + FINDINGS, snap_of(work))
    # Drafts are edited freely (with the revision they were read at).
    wsp.update(p, [put({"id": "f-bound", "kind": "finding", "claim": "lem:bound",
                        "coverage": "changed", "evidence": ["e-bound"],
                        "note": "One more derivative: m+5 against m+4."}, base=1)], snap_of(work))
    wsp.update(p, [{"op": "submit", "id": "f-bound", "base_rev": 2}], snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="supersede"):
        wsp.update(p, [put({"id": "f-bound", "kind": "finding", "claim": "lem:bound",
                            "coverage": "full", "note": "x"}, base=3)], snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="kept"):
        wsp.update(p, [{"op": "delete", "id": "f-bound", "base_rev": 3}], snap_of(work))
    with pytest.raises(wsp.WorkspaceError, match="reason"):
        wsp.update(p, [{"op": "supersede", "id": "f-bound", "base_rev": 3,
                        "record": {"coverage": "full", "note": "x"}}], snap_of(work))
    wsp.update(p, [{"op": "supersede", "id": "f-bound", "base_rev": 3,
                    "reason": "A stronger theorem gives the paper's derivative order.",
                    "record": {"id": "f-bound-2", "coverage": "full",
                               "evidence": ["e-bound", "e-tri"],
                               "note": "Ex.inverse_solves with Ex.tri gives m+4."}}],
               snap_of(work))
    ws = wsp.read(p)
    old, new = ws["records"]["f-bound"], ws["records"]["f-bound-2"]
    assert old["state"] == "submitted" and old["coverage"] == "changed"
    assert new["supersedes"] == "f-bound" and new["state"] == "submitted"
    assert new["reason"].startswith("A stronger theorem")
    assert {f["id"] for f in wsp.current_findings(ws)} == {"f-bound-2", "f-main"}
    v = wsp.view(ws, snap_of(work))
    assert [f["in_force"] for f in v["claims"]["P:lem:bound"]["findings"]] == [False, True]


def test_a_changed_definition_makes_only_the_findings_that_use_it_stale(work):
    p = opened(work)
    wsp.update(p, EVIDENCE + FINDINGS, snap_of(work))
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert {k: v["state"] for k, v in cur.items()} == {
        "e-bound": "current", "e-tri": "current", "e-main": "current",
        "f-bound": "current", "f-main": "current"}
    # A rebuild where only the definition's generated equations changed (its own fingerprint
    # did not): the evidence citing it, and the finding citing that evidence, are stale.
    make_build(work, fp_tri_f="fp:tri_f-2", release="v-2")
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["e-tri"]["state"] == "stale" and cur["f-bound"]["state"] == "stale"
    assert cur["e-bound"]["state"] == cur["e-main"]["state"] == cur["f-main"]["state"] == "current"
    assert cur["f-bound"]["changes"][0]["decl"] == "Ex.tri"
    # The saved records are unchanged; re-pinning is an explicit edit.
    assert wsp.read(p)["records"]["e-tri"]["ref"]["fingerprint"] == "fp:tri-1"
    wsp.update(p, [put({"id": "e-tri", "kind": "evidence", "claim": "lem:bound",
                        "ref": {"decl": "Ex.tri"}, "role": "context", "repin": True}, base=1)],
               snap_of(work))
    assert wsp.currency(wsp.read(p), snap_of(work))["f-bound"]["state"] == "current"
    # A changed printed statement makes that claim's findings stale.
    make_build(work, fp_tri_f="fp:tri_f-2", sha_bound="s-bound-2", release="v-3")
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["f-bound"]["state"] == "stale" and cur["f-main"]["state"] == "current"


def test_an_informed_investigation_stays_informed_through_mode_import_and_review(work, tmp_path):
    p = opened(work, mode="informed")
    ws = wsp.read(p)
    assert ws["mode"] == "informed" and ws["exposure"][0]["what"] == ["Lean",
                                                                       "prior interpretations"]
    assert "locked_at" not in json.dumps(ws)      # no blind reading is invented
    wsp.update(p, [{"op": "mode", "mode": "independent"}], snap_of(work))
    ws = wsp.read(p)
    assert ws["mode"] == "independent" and ws["exposure"][0]["how"] == "informed investigation"
    # Exported and imported elsewhere, it keeps its exposure and author.
    out = wsp.export(p)
    other = tmp_path / "elsewhere" / ".machinechecked"
    make_build(other)
    res = wsp.import_(other, json.loads(json.dumps(out)), snap_of(other), "human:B-Auditor")
    got = wsp.read(wsp.find(other, ws["id"]))
    assert got["exposure"] == ws["exposure"] and got["reviewer"]["id"] == WHO["id"]
    assert got["provenance"][-1]["event"] == "imported" and not res["problems"]
    # A review in this workspace reports that the reviewer had seen the Lean.
    queue = {"release": "v-1", "units": [{"id": "spec:Ex.main", "kind": "spec", "name": "Ex.main",
                                          "claims": [{"id": "P:thm:main"}], "state": "open"}]}
    (work / "site" / "data" / "review-queue.json").write_text(json.dumps(queue))
    s = rc.Session(types.SimpleNamespace(out_dir=work), WHO)
    assert s.workspace["id"] == ws["id"]
    seen = s.revealed_by(s.unit("spec:Ex.main"))
    assert {x["what"] for x in seen} == {"Lean", "author's review"}
    assert "informed investigation" in seen[0]["unit"]


THIRD = rc.parse_reviewer("human:C-Referee")
MAIN = {"id": "spec:Ex.main", "kind": "spec", "name": "Ex.main", "claims": [{"id": "P:thm:main"}],
        "state": "open", "fingerprint": "fp:main-1"}
BOUND = {"id": "spec:Ex.inverse_bound", "kind": "spec", "name": "Ex.inverse_bound",
         "claims": [{"id": "P:lem:bound"}], "state": "open", "fingerprint": "fp:bound-1",
         "reveals": {"lean": [], "author": ["spec:Ex.main"]}}


def queued(work, *units):
    (work / "site" / "data" / "review-queue.json").write_text(
        json.dumps({"release": "v-1", "units": list(units or [MAIN])}))


def session(work, who=WHO):
    return rc.Session(types.SimpleNamespace(out_dir=work), who)


def reviewed(s, uid="spec:Ex.main") -> dict:
    """Take `uid` through the protocol's steps and return its report."""
    s.read(uid)
    s.lock(uid, "The statement holds for every case, as printed.")
    s.show(uid)
    s.decide(uid, "faithful", "The Lean states it.")
    s.author(uid)
    return s.submit(uid, "none")


def informed_seen(wid):
    return [{"unit": f"workspace {wid} (informed investigation)", "what": "Lean"},
            {"unit": f"workspace {wid} (informed investigation)", "what": "author's review"}]


def test_a_review_after_importing_ones_informed_workspace_records_that_exposure(work, tmp_path):
    """#252: the investigation is imported under its own id, beside the reviewer's review file;
    the review there lists its exposure, and a reviewer who has not seen it stays blind."""
    data = wsp.export(opened(work, mode="informed"))
    other = tmp_path / "elsewhere" / ".machinechecked"
    make_build(other)
    queued(other)
    wsp.import_(other, json.loads(json.dumps(data)), snap_of(other), WHO["id"])
    s = session(other)
    assert s.workspace["id"] != data["id"]            # the review keeps its own file
    assert "will not be blind" in s.read("spec:Ex.main")
    r = reviewed(s)
    assert r["reading"]["revealed_by"] == informed_seen(data["id"])
    assert r["reviewer"]["id"] == WHO["id"]
    # Another reviewer of the same working directory has not seen it.
    r = reviewed(session(other, THIRD))
    assert r["reading"]["revealed_by"] == []


def test_an_informed_workspace_beside_ones_review_file_is_exposure(work):
    """The same in the project where it was made: the reviewer's review file exists already, so
    the informed investigation is a workspace of its own."""
    queued(work)
    s = session(work)
    s.read("spec:Ex.main")                              # the review file, independent
    p = opened(work, mode="informed")
    wid = wsp.read(p)["id"]
    assert p != s.path and wsp.read(s.path)["mode"] == "independent"
    assert session(work).revealed_by(MAIN) == informed_seen(wid)
    assert session(work, THIRD).revealed_by(MAIN) == []


def test_whoever_works_in_an_informed_workspace_has_seen_what_it_records(work):
    """A co-auditor who records work in someone's informed investigation, or imports it, has
    seen what it records; a reviewer who has done neither has not."""
    queued(work)
    p = opened(work, mode="informed")
    wid = wsp.read(p)["id"]
    assert session(work, OTHER).revealed_by(MAIN) == []
    wsp.update(p, [EVIDENCE[2]], snap_of(work), by=OTHER["id"])
    assert session(work, OTHER).revealed_by(MAIN) == informed_seen(wid)
    importer = rc.parse_reviewer("human:D-Referee")
    wsp.import_(work, {**wsp.export(p), "id": "ws-0123456789ab"}, snap_of(work), importer["id"])
    assert session(work, importer).revealed_by(MAIN) == informed_seen("ws-0123456789ab")
    assert session(work, THIRD).revealed_by(MAIN) == []


def test_exposure_imported_after_the_lock_counts_when_it_was_recorded_before_it(work):
    """A reading locked here, then an investigation imported that the reviewer made before the
    lock: the report lists it. What was recorded after the lock leaves the reading blind."""
    queued(work, MAIN, {**BOUND, "reveals": {"lean": [], "author": []}})
    s = session(work)
    for uid in ("spec:Ex.main", "spec:Ex.inverse_bound"):
        s.read(uid)
        s.lock(uid, "The statement holds for every case, as printed.")
        s.show(uid)
        s.decide(uid, "faithful", "The Lean states it.")
        s.author(uid)
        assert s.work["drafts"][uid]["revealed_by"] == []
    ws = wsp.new(WHO, "independent", wid="ws-00000000aaaa")
    ws["exposure"] = [
        {"what": ["Lean"], "claims": ["P:thm:main"], "at": "2000-01-01T00:00:00Z", "how": "earlier"},
        {"what": ["Lean"], "claims": ["P:lem:bound"], "at": "2999-01-01T00:00:00Z", "how": "later"}]
    wsp.import_(work, ws, snap_of(work), WHO["id"])
    assert s.submit("spec:Ex.main", "none")["reading"]["revealed_by"] == [
        {"unit": "workspace ws-00000000aaaa (earlier)", "what": "Lean"}]
    assert s.submit("spec:Ex.inverse_bound", "none")["reading"]["revealed_by"] == []


def test_review_work_imported_from_elsewhere_is_what_the_reviewer_had_seen(work, tmp_path):
    """The reviewer's review work from another copy, imported here: a unit they reached step 2
    of there, and a unit whose step 3 there showed this one's author's review, are exposure;
    their report of other Lean of a unit is an earlier review, as a reopened review is here."""
    queued(work, MAIN, BOUND)
    ws = wsp.new(WHO, "independent", wid="ws-00000000bbbb")
    old = reviewed(session(work), "spec:Ex.main")
    (wsp.store(work) / "human_A-Auditor.json").unlink()
    ws["review"]["reports"] = [{**old, "pins": {**old["pins"], "fingerprint": "fp:main-0"}}]
    assert session(work).revealed_by(MAIN) == []
    wsp.import_(work, ws, snap_of(work), WHO["id"])
    assert session(work).revealed_by(MAIN) == []        # a review of earlier Lean
    ws["review"]["drafts"] = {"spec:Ex.main": {"stage": "compare", "reading": "r",
                                               "locked_at": "2026-01-01T00:00:00Z"},
                              "spec:Ex.inverse_bound": {"stage": "author", "reading": "r",
                                                        "locked_at": "2026-01-01T00:00:00Z",
                                                        "decided_at": "2026-01-01T00:01:00Z",
                                                        "author_shown_at": "2026-01-01T00:02:00Z"}}
    wsp.save_review(wsp.find(work, ws["id"]), ws["review"])
    assert session(work).revealed_by(MAIN) == [
        {"unit": "spec:Ex.main (workspace ws-00000000bbbb)", "what": "Lean"},
        {"unit": "spec:Ex.inverse_bound (workspace ws-00000000bbbb)", "what": "author's review"}]
    assert session(work, OTHER).revealed_by(MAIN) == []


def test_independent_review_work_is_kept_and_upgraded(work):
    legacy = {"reviewer": WHO, "drafts": {"spec:Ex.main": {"stage": "compare", "reading": "r",
                                                           "locked_at": "2026-01-01T00:00:00Z"}},
              "reports": []}
    path = wsp.store(work) / "human_A-Auditor.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(legacy))
    queue = {"release": "v-1", "units": [{"id": "spec:Ex.main", "kind": "spec", "name": "Ex.main",
                                          "claims": [{"id": "P:thm:main"}], "state": "open"}]}
    (work / "site" / "data" / "review-queue.json").write_text(json.dumps(queue))
    s = rc.Session(types.SimpleNamespace(out_dir=work), WHO)
    assert s.work["drafts"]["spec:Ex.main"]["stage"] == "compare"
    assert s.revealed_by(s.unit("spec:Ex.main")) == []        # an independent workspace
    # Its records survive a save of the review protocol, and the protocol's lock still holds.
    wsp.update(path, [EVIDENCE[2]], snap_of(work))
    with pytest.raises(rc.ReviewError, match="already locked"):
        s.read("spec:Ex.main")
    s.save()
    ws = wsp.read(path)
    assert ws["schema"] == wsp.SCHEMA and "e-main" in ws["records"]
    assert ws["review"]["drafts"]["spec:Ex.main"]["locked_at"] == "2026-01-01T00:00:00Z"


def test_import_reports_what_does_not_resolve_and_keeps_both_versions(work, tmp_path):
    p = opened(work)
    wsp.update(p, EVIDENCE + FINDINGS, snap_of(work))
    data = wsp.export(p)
    data["records"]["e-gone"] = {**data["records"]["e-main"], "id": "e-gone", "claim": "P:thm:gone"}
    data["records"]["f-main"] = {**data["records"]["f-main"], "note": "Edited elsewhere."}
    res = wsp.import_(work, data, snap_of(work), "human:B-Auditor")
    assert res["added"] == ["e-gone"]
    assert [c["id"] for c in res["conflicts"]] == ["f-main"]
    assert any("P:thm:gone" in x["problem"] for x in res["problems"])
    ws = wsp.read(p)
    assert ws["records"]["f-main"]["note"] == "Direct."
    assert ws["conflicts"][-1]["proposed"]["note"] == "Edited elsewhere."


# -- the command line and the reader's interface --------------------------------------------

def test_cli_update_keeps_exact_text_and_resumes(work, monkeypatch, capsys, tmp_path):
    root = work.parent
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    monkeypatch.chdir(root)
    monkeypatch.setenv("MACHINECHECKED_REVIEWER", WHO["id"])
    note = 'The paper says "for all t ≥ 0";\nLean has ∀ᵐ ω, ∀ t — the order differs.\n'
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps({"ops": EVIDENCE[:2] + [
        put({"id": "q-order", "kind": "question", "claim": "Lemma 2.3",
             "text": note}),
        {"op": "resume", "state": {"claim": "lem:bound", "question": "q-order",
                                   "pinned": ["e-tri"]}}]}, ensure_ascii=False))
    cli.main(["workspace", "open", "--mode", "informed"])
    capsys.readouterr()
    cli.main(["workspace", "update", str(ops), "--dry-run"])
    dry = json.loads(capsys.readouterr().out)
    assert dry["dry_run"] and dry["records"]["q-order"]["text"] == note
    cli.main(["workspace", "update", str(ops)])
    assert json.loads(capsys.readouterr().out)["ok"]
    cli.main(["workspace", "show", "--json"])
    v = json.loads(capsys.readouterr().out)
    assert v["claims"]["P:lem:bound"]["questions"][0]["text"] == note
    assert v["resume"]["question"] == "q-order" and v["resume"]["pinned"] == ["e-tri"]
    # An invalid update says why, as JSON, and exits 1.
    ops.write_text(json.dumps([put({"kind": "evidence", "claim": "2.3",
                                    "ref": {"decl": "Ex.main"}})]))
    with pytest.raises(SystemExit) as e:
        cli.main(["workspace", "update", str(ops)])
    assert e.value.code == 1 and "names 2 claims" in json.loads(capsys.readouterr().out)["error"]


def _call(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_reader_and_the_cli_share_one_workspace(work, monkeypatch, capsys):
    httpd = make_server(work / "site", 0, api=wsp.api(work, work / "site" / "data", None))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/api/"
    try:
        code, v = _call(base + "workspace", {"action": "open", "reviewer": WHO["id"],
                                             "mode": "informed"})
        assert code == 200 and v["mode"] == "informed"
        wid = v["id"]
        code, ack = _call(base + "workspace", {"action": "update", "id": wid,
                                               "ops": EVIDENCE + FINDINGS, "op_id": "r1"})
        assert code == 200 and ack["revision"] == 1
        code, err = _call(base + "workspace", {"action": "update", "id": wid, "ops": [
            put({"kind": "evidence", "claim": "2.3", "ref": {"decl": "Ex.main"}})]})
        assert code == 400 and "names 2 claims" in err["error"]
        # The CLI resumes the same records and edits one; the reader's stale edit conflicts.
        p = wsp.find(work, wid)
        wsp.update(p, [put({"id": "f-main", "kind": "finding", "claim": "1", "coverage": "full",
                            "evidence": ["e-main"], "note": "CLI edit."}, base=1)],
                   snap_of(work))
        code, err = _call(base + "workspace", {"action": "update", "id": wid, "ops": [
            put({"id": "f-main", "kind": "finding", "claim": "1", "coverage": "related",
                 "evidence": ["e-main"], "note": "Reader edit."}, base=1)]})
        assert code == 409 and err["conflicts"][0]["current"]["note"] == "CLI edit."
        code, v = _call(base + f"workspace?id={wid}&claim=P:thm:main")
        assert code == 200 and list(v["claims"]) == ["P:thm:main"]
        assert v["claims"]["P:thm:main"]["findings"][0]["note"] == "CLI edit."
        code, ex = _call(base + f"workspace/export?id={wid}")
        assert code == 200 and ex["schema"] == wsp.SCHEMA and ex["mode"] == "informed"
        code, lst = _call(base + "workspaces")
        assert [w["id"] for w in lst["workspaces"]] == [wid]
    finally:
        httpd.shutdown()


def test_a_finding_uses_the_links_file_reading(work):
    """A finding records coverage and, separately, its basis with the same words as the links
    file; `composed` is recorded as full coverage by the auditor's composition."""
    p = opened(work, mode="informed")
    wsp.update(p, [
        put({"id": "f-comp", "kind": "finding", "claim": "1", "coverage": "composed",
             "argument": "Combine the two bounds.", "note": "n"}),
        put({"id": "f-bridge", "kind": "finding", "claim": "1", "coverage": "full",
             "basis": "checked_bridge", "bridge": {"theorem": "Ex.main", "target": "Ex.Spec"},
             "note": "n"}),
        put({"id": "f-open", "kind": "finding", "claim": "1", "coverage": "unresolved",
             "question": "Which norm?", "would_decide": "Section 2's conventions."})],
        snap_of(work))
    recs = wsp.read(p)["records"]
    assert (recs["f-comp"]["coverage"], recs["f-comp"]["basis"], recs["f-comp"]["argument"]) == \
        ("full", "reviewed_composition", "Combine the two bounds.")
    assert recs["f-bridge"]["bridge"] == {"theorem": "Ex.main", "target": "Ex.Spec"}
    assert (recs["f-open"]["question"], recs["f-open"]["would_decide"]) == \
        ("Which norm?", "Section 2's conventions.")
    assert "next_step" not in recs["f-comp"]


BRIDGELESS = {"f-none": {},
              "f-nope": {"bridge": {"theorem": "Nope.x", "target": "Nope.y"}}}


def test_a_finding_recorded_as_a_checked_bridge_needs_one_lean_checks(work, monkeypatch, capsys,
                                                                     tmp_path):
    """#271: a finding recorded with basis checked_bridge and no bridge, or with a bridge
    naming declarations that do not exist, reads as the auditor's composition, with what it was
    recorded as and why, in `workspace show` (text and JSON) and in an export, as the reader
    reads it. The record keeps what the auditor wrote."""
    from prooflens import published_work as pw
    from prooflens.config import Publish
    from prooflens.schemas import validate
    root = work.parent
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    monkeypatch.chdir(root)
    p = opened(work, mode="informed")
    for fid, extra in BRIDGELESS.items():
        wsp.update(p, [put({"id": fid, "kind": "finding", "claim": "Theorem 1",
                            "coverage": "full", "basis": "checked_bridge", "note": "n",
                            **extra}),
                       {"op": "submit", "id": fid, "base_rev": 1}], snap_of(work))
    recs = wsp.read(p)["records"]
    assert {recs[f]["basis"] for f in BRIDGELESS} == {"checked_bridge"}

    def basis(f):
        return f["basis"], f.get("recorded_basis"), f.get("basis_reason")

    # Without the Lean project, and with one that is not built.
    v = wsp.view(wsp.read(p), snap_of(work))
    got = {f["id"]: basis(f) for f in v["claims"]["P:thm:main"]["findings"]}
    assert got == {"f-none": ("reviewed_composition", "checked_bridge",
                              ["no bridge is recorded"]),
                   "f-nope": ("reviewed_composition", "checked_bridge",
                              ["no Lean project to check the bridge against"])}
    capsys.readouterr()
    cli.main(["workspace", "show", "--as", WHO["id"], "--json"])
    shown = json.loads(capsys.readouterr().out)["claims"]["P:thm:main"]["findings"]
    got = {f["id"]: basis(f) for f in shown}
    assert got["f-none"] == ("reviewed_composition", "checked_bridge", ["no bridge is recorded"])
    assert got["f-nope"][:2] == ("reviewed_composition", "checked_bridge")
    assert "not built" in got["f-nope"][2][0]
    nope, = [f for f in shown if f["id"] == "f-nope"]
    assert nope["bridge_check"]["state"] == "unchecked"
    assert nope["bridge"] == {"theorem": "Nope.x", "target": "Nope.y"}
    cli.main(["workspace", "show", "--as", WHO["id"]])
    out = capsys.readouterr().out
    assert "checked_bridge  [" not in out and "basis checked_bridge" not in out
    assert out.count("basis reviewed_composition") == 2
    assert "recorded as checked_bridge; no bridge Lean checks now: no bridge is recorded" in out
    assert out.count("Lean has not checked this combination") == 2

    # An export reads them the same way, and the published file is valid.
    rd, = pw.readings(work, snap_of(work), lambda cid: Publish(True, True, True, True),
                      {"P:thm:main"}, root)["P:thm:main"]
    validate({"schema": pw.SCHEMA, "release": "v-1", "claim": "P:thm:main", "readings": [rd]},
             "published-work")
    got = {f["id"]: basis(f) for f in rd["findings"]}
    assert got["f-none"] == ("reviewed_composition", "checked_bridge", ["no bridge is recorded"])
    assert got["f-nope"][:2] == ("reviewed_composition", "checked_bridge")
    assert rd["findings"][1]["bridge_check"]["state"] == "unchecked"

    # An imported finding is read the same way, though import keeps records as written: here
    # one recorded as a checked bridge through a composition that is not there.
    data = wsp.export(p)
    data["records"]["f-gone"] = {**data["records"]["f-none"], "id": "f-gone",
                                 "composition": "c-gone"}
    other = tmp_path / "elsewhere" / ".machinechecked"
    make_build(other)
    wsp.import_(other, data, snap_of(other))
    v = wsp.view(wsp.read(wsp.find(other, data["id"])), snap_of(other))
    got = {f["id"]: basis(f) for f in v["claims"]["P:thm:main"]["findings"]}
    assert got["f-gone"] == ("reviewed_composition", "checked_bridge",
                             ["its composition c-gone is not among these records"])
