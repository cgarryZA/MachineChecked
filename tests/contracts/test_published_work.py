"""The workspace records a published audit carries (#143, #99): the requirements, accepted
passages, alignments and submitted findings (with their evidence and supersession) of each
claim, attributed; nothing the auditor has not accepted; the paper's publication settings
applied; the site's loader reading them; and no status changed by them."""

import copy
import json

import pytest

from conftest import build, edit, needs_lean, needs_tex
from test_workspace import make_build

from prooflens import config as cfgmod
from prooflens import published_work as pw
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.export import export
from prooflens.published import AuditError, load_published_audit
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def investigate(work, snap, claim, region=None):
    """A workspace on `claim` with one record of each kind, accepted and not."""
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    src = {"region": region} if region else {"passage": {"claim": claim}}
    wsp.update(p, [
        put({"id": "q-req", "kind": "requirement", "claim": claim, "local_id": "r1",
             "form": "condition", "text": "the synthetic condition"}),
        put({"id": "p-yes", "kind": "fragment", "claim": claim, "requirement": "r1",
             "role": "statement", **src}),
        put({"id": "p-maybe", "kind": "fragment", "claim": claim, "requirement": "r1",
             "role": "context", "state": "proposed", "passage": {"claim": claim},
             "suggestion": {"rule": "sentence before the passage", "by": "machinechecked"}}),
        put({"id": "p-no", "kind": "fragment", "claim": claim, "requirement": "r1",
             "role": "later use", "state": "removed", "why_removed": "WITHDRAWN-PASSAGE",
             "passage": {"claim": claim}}),
        put({"id": "e-cited", "kind": "evidence", "claim": claim,
             "ref": {"paper": {"claim": claim, "quote": "QUOTED-WORDS"}}, "role": "supports"}),
        put({"id": "e-rejected", "kind": "evidence", "claim": claim,
             "ref": {"paper": {"claim": claim, "quote": "x"}}, "role": "rejected",
             "reason": "REJECTED-CANDIDATE"}),
        put({"id": "e-candidate", "kind": "evidence", "claim": claim,
             "ref": {"paper": {"claim": claim, "quote": "y"}}}),
        put({"id": "f-first", "kind": "finding", "claim": claim, "coverage": "partial",
             "requirement": "r1", "evidence": ["e-cited"], "note": "FIRST-FINDING-NOTE"}),
        put({"id": "f-draft", "kind": "finding", "claim": claim, "coverage": "full",
             "note": "DRAFT-FINDING-NOTE"}),
        put({"id": "q-open", "kind": "question", "claim": claim, "text": "WORKING-QUESTION"}),
    ], snap)
    wsp.update(p, [{"op": "submit", "id": "f-first", "base_rev": 1}], snap)
    wsp.update(p, [{"op": "supersede", "id": "f-first", "base_rev": 2,
                    "reason": "SUPERSEDING-REASON",
                    "record": {"id": "f-second", "coverage": "full", "evidence": ["e-cited"],
                               "note": "SECOND-FINDING-NOTE"}}], snap)
    return p


LOCAL_ONLY = ("p-maybe", "p-no", "WITHDRAWN-PASSAGE", "e-rejected", "REJECTED-CANDIDATE",
              "e-candidate", "f-draft", "DRAFT-FINDING-NOTE", "q-open", "WORKING-QUESTION",
              "informed investigation")


def test_only_accepted_records_are_published_attributed_and_current(tmp_path):
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    p = investigate(work, snap, "P:lem:bound")
    # The published data is a copy of the build's data.
    import shutil
    data = tmp_path / "out" / "data"
    shutil.copytree(work / "site" / "data", data)
    written = pw.write(data, work, lambda cid: EVERYTHING)
    assert list(written) == ["P:lem:bound"]
    chunk = json.loads((data / "claims" / "lem_bound.json").read_text())
    assert chunk["work"] == "work/lem_bound.json" == written["P:lem:bound"]
    raw = (data / "work" / "lem_bound.json").read_text()
    body = json.loads(raw)
    from prooflens.schemas import validate
    validate(body, "published-work")
    assert body["claim"] == "P:lem:bound" and body["release"] == "v-1"
    (rd,) = body["readings"]
    ws = wsp.read(p)
    assert rd["workspace"] == ws["id"] and rd["mode"] == "informed"
    assert rd["reviewer"] == {"id": "human:A-Auditor", "kind": "human", "name": "A Auditor",
                              "identity": "self-declared"}
    for word in LOCAL_ONLY:
        assert word not in raw, word
    assert [r["local_id"] for r in rd["requirements"]] == ["r1"]
    assert [f["id"] for f in rd["fragments"]] == ["p-yes"]
    assert [e["id"] for e in rd["evidence"]] == ["e-cited"]
    assert rd["evidence"][0]["ref"]["paper"]["quote"] == "QUOTED-WORDS"
    first, second = rd["findings"]
    assert (first["id"], first["in_force"], second["id"], second["in_force"]) == \
        ("f-first", False, "f-second", True)
    assert second["supersedes"] == "f-first" and second["reason"] == "SUPERSEDING-REASON"
    assert first["note"] == "FIRST-FINDING-NOTE" and first["requirement"] == "r1"
    rec = ws["records"]["f-second"]
    assert (second["created_by"], second["submitted_at"]) == ("human:A-Auditor",
                                                              rec["submitted_at"])
    assert all(r["currency"]["state"] == "current" for k in ("requirements", "fragments",
                                                            "findings") for r in rd[k])
    # Against a build where the claim's printed text changed, what rests on it is stale.
    make_build(work, sha_bound="s-bound-2", release="v-2")
    shutil.rmtree(data.parent)
    shutil.copytree(work / "site" / "data", data)
    pw.write(data, work, lambda cid: EVERYTHING)
    rd = json.loads((data / "work" / "lem_bound.json").read_text())["readings"][0]
    assert rd["fragments"][0]["currency"]["state"] == "stale"
    assert rd["requirements"][0]["currency"]["state"] == "stale"
    assert {f["id"]: f["currency"]["state"] for f in rd["findings"]} == {
        "f-first": "stale", "f-second": "stale"}


def test_publication_settings_withhold_text_and_prose(tmp_path):
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    investigate(work, snap, "P:lem:bound")
    closed = Publish(pdf=False, source_text=False, lean=False, reviews=False)
    found = pw.readings(work, snap, lambda cid: closed, {"P:lem:bound"})
    raw = json.dumps(found)
    for word in ("QUOTED-WORDS", "FIRST-FINDING-NOTE", "SECOND-FINDING-NOTE",
                 "SUPERSEDING-REASON"):
        assert word not in raw, word
    rd = found["P:lem:bound"][0]
    assert rd["evidence"][0]["ref"] == {"paper": {"claim": "P:lem:bound"}}
    assert rd["findings"][1]["coverage"] == "full" and rd["findings"][1]["supersedes"]
    # The requirement is the auditor's reading, not the paper's text: it is published.
    assert rd["requirements"][0]["text"] == "the synthetic condition"


def test_the_loader_reads_the_records_and_refuses_what_is_not_published(tmp_path):
    import published_fixture as pf
    cid = "T:one"
    fname = next(c["file"] for c in pf.files()["data/index.json"]["claims"] if c["id"] == cid)
    data = pf.with_work(pf.files(), cid)
    got = pf.snapshot(data)
    rec = next(c["record"] for c in got["claims"] if c["id"] == cid)
    assert rec["work"]["readings"][0]["alignments"][0]["lean"] == [{"decl": "Synthetic.bound"}]
    # The status is the claim's own, with or without the records.
    plain = pf.snapshot()
    assert [(c["id"], c["status_code"]) for c in got["claims"]] == \
        [(c["id"], c["status_code"]) for c in plain["claims"]]
    # A draft finding is not publishable; nor are records of another claim or elsewhere.
    bad = copy.deepcopy(data)
    bad[f"data/work/{fname}"]["readings"][0]["findings"][0]["state"] = "draft"
    with pytest.raises(AuditError, match="published-work"):
        pf.snapshot(bad)
    bad = copy.deepcopy(data)
    bad[f"data/work/{fname}"]["claim"] = "T:prose"
    with pytest.raises(AuditError, match="disagree"):
        pf.snapshot(bad)
    bad = copy.deepcopy(data)
    bad[f"data/claims/{fname}"]["work"] = "claims/" + fname
    with pytest.raises(AuditError, match="where the claim names"):
        pf.snapshot(bad)


def _statuses(out):
    idx = json.loads((out / "data" / "index.json").read_text())
    chunks = {}
    for c in idx["claims"]:
        ch = json.loads((out / "data" / "claims" / c["file"]).read_text())
        ch.pop("work", None)
        chunks[c["id"]] = ch
    return [{k: c.get(k) for k in ("id", "status", "status_code", "class")}
            for c in idx["claims"]], chunks


def _toy_workspace(cfg):
    snap = Snapshot(cfg.out_dir / "site" / "data")
    tex = (cfg.out_dir / "sources" / "T" / "toy.tex").read_text(encoding="utf-8").splitlines()
    line = next(i for i, t in enumerate(tex, 1) if t.startswith("A natural number $n$ is"))
    p = investigate(cfg.out_dir, snap, "T:def:even",
                    {"file": "toy.tex", "start_line": line, "end_line": line})
    wsp.update(p, [put({"id": "a-even", "kind": "alignment", "claim": "T:def:even",
                        "requirements": ["r1"], "lean": [{"decl": "Toy.IsEven"}]})], snap)
    return p, tex[line - 1]


@needs_lean
@needs_tex
def test_an_export_carries_the_records_and_no_status_changes(toy, tmp_path):
    index, _, cfg = build(toy)
    before = export(cfg, tmp_path / "before")
    assert not (tmp_path / "before" / "data" / "work").exists()
    p, printed = _toy_workspace(cfg)
    after = export(cfg, tmp_path / "after")
    assert before["release"] == after["release"]
    assert _statuses(tmp_path / "before") == _statuses(tmp_path / "after")
    row = next(c for c in json.loads((tmp_path / "after" / "data" / "index.json").read_text())
               ["claims"] if c["id"] == "T:def:even")
    raw = (tmp_path / "after" / "data" / "work" / row["file"]).read_text()
    for word in LOCAL_ONLY:
        assert word not in raw, word
    rd = json.loads(raw)["readings"][0]
    ws = wsp.read(p)
    # Round trip: the published records are the saved ones, with their currency.
    frag = rd["fragments"][0]
    assert frag["region"]["text"] == ws["records"]["p-yes"]["region"]["text"]
    assert printed.strip() in frag["region"]["text"]
    assert frag["region"]["file"] == "toy.tex" and frag["currency"]["state"] == "current"
    (al,) = rd["alignments"]
    assert al["lean"][0]["decl"] == "Toy.IsEven" and al["currency"]["state"] == "current"
    assert al["lean"][0]["fingerprint"] == ws["records"]["a-even"]["lean"][0]["fingerprint"]
    assert [f["id"] for f in rd["findings"]] == ["f-first", "f-second"]
    # The site's loader accepts the export with its records.
    out = tmp_path / "after"
    desc = json.loads((out / "audit.json").read_text())
    idx = json.loads((out / "data" / "index.json").read_text())
    desc["formalisation"].update(repository="synthetic/toy", commit="a" * 40)
    idx["project"].update(repository="synthetic/toy", commit="a" * 40)
    desc["papers"][0].update(id="arxiv:2601.00002", revision="d" * 40)
    idx["papers"][0]["revision"] = "d" * 40
    (out / "audit.json").write_text(json.dumps(desc))
    (out / "data" / "index.json").write_text(json.dumps(idx))
    base = "https://audit.example/toy/"
    got = load_published_audit({"id": "arxiv:2601.00002", "links": {}},
                               {"repository": "synthetic/toy"}, {"url": base},
                               lambda url, limit: (out / url[len(base):]).read_bytes())
    rec = next(c["record"] for c in got["claims"] if c["id"] == "T:def:even")
    assert rec["work"]["readings"][0]["fragments"][0]["id"] == "p-yes"


@needs_lean
@needs_tex
def test_a_paper_that_keeps_its_source_private_publishes_no_passage_text(toy, tmp_path):
    index, _, cfg = build(toy)
    _toy_workspace(cfg)
    edit(toy / "machinechecked.toml",
         "publish = { pdf = true, source_text = true, lean = true, reviews = true }",
         "publish = { pdf = true, source_text = false, lean = true, reviews = true }")
    cfg = cfgmod.load(toy / "machinechecked.toml")
    export(cfg, tmp_path / "out")
    row = next(c for c in json.loads((tmp_path / "out" / "data" / "index.json").read_text())
               ["claims"] if c["id"] == "T:def:even")
    rd = json.loads((tmp_path / "out" / "data" / "work" / row["file"]).read_text())["readings"][0]
    reg = rd["fragments"][0]["region"]
    assert set(reg) == {"paper", "sha256"} and reg["sha256"]
    assert rd["evidence"][0]["ref"] == {"paper": {"claim": "T:def:even"}}
    assert rd["requirements"][0]["text"] == "the synthetic condition"
    assert rd["findings"][1]["note"] == "SECOND-FINDING-NOTE"


def test_a_cited_fact_inside_a_proof_is_published_with_its_basis(tmp_path):
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    claim = "P:lem:bound"
    fact = {"decl": "Syn.bound", "module": "Syn.Main", "at": "/1/1/1", "fact_hash": "a" * 16,
            "proof_hash": "b" * 16, "kind": "have", "name": "strong",
            "type": "LEAN-FACT-TYPE", "assumptions": ["hx : LEAN-HYPOTHESIS"]}
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        put({"id": "e-fact", "kind": "evidence", "claim": claim, "role": "supports",
             "ref": {"fact": fact}}),
        put({"id": "f-fact", "kind": "finding", "claim": claim, "coverage": "full",
             "basis": "reviewed_composition", "evidence": ["e-fact"], "note": "n"})], snap)
    wsp.update(p, [{"op": "submit", "id": "f-fact", "base_rev": 1}], snap)
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {claim})[claim]
    ref = rd["evidence"][0]["ref"]["fact"]
    assert ref["basis"] == "established inside this proof under this context"
    assert (ref["decl"], ref["at"], ref["type"]) == ("Syn.bound", "/1/1/1", "LEAN-FACT-TYPE")
    # Its currency needs the Lean project: it is not published as current.
    assert rd["evidence"][0]["currency"]["state"] == "unchecked"
    closed = Publish(pdf=False, source_text=False, lean=False, reviews=False)
    rd, = pw.readings(work, snap, lambda cid: closed, {claim})[claim]
    raw = json.dumps(rd)
    assert "LEAN-FACT-TYPE" not in raw and "LEAN-HYPOTHESIS" not in raw
    assert rd["evidence"][0]["ref"]["fact"]["basis"].startswith("established inside")


# -- Lean-checked evidence at export (#272) ----------------------------------------------------

class FakeLean:
    """Lean's answers about one cited fact, application and certificate, as `proof_facts.extract`,
    `uses.uses` and `estimates.check` give them. The facts store holds nothing, so an answer
    exists only when Lean is asked (`cached_only=False`). `now` sets what Lean finds: `same`,
    `changed`, or one of the answers that say Lean did not look."""

    APP = {"id": "app:Syn.caller:0", "callee": "Syn.lemma", "caller": "Syn.caller",
           "available": True, "params": [], "result": "LEAN-APP-RESULT"}

    def __init__(self, monkeypatch):
        from prooflens import estimates as est
        from prooflens import proof_facts as pf
        from prooflens import uses as us
        self.now, self.asked = "same", []
        monkeypatch.setattr(pf, "extract", self.extract)
        monkeypatch.setattr(us, "uses", self.uses)
        monkeypatch.setattr(est, "check", self.check)
        self.app_hash = us.app_hash(self.APP)

    def _answer(self, what, cached_only, ok):
        self.asked.append((what, cached_only))
        if cached_only:
            return {"ok": False, "status": "not extracted", "reason": "not read since"}
        if self.now not in ("same", "changed"):
            return {"ok": False, "status": self.now, "modules": ["Syn.Main"]}
        return ok

    def extract(self, root, name, module=None, cached_only=False, **kw):
        return self._answer("fact", cached_only, {
            "ok": True, "status": "found",
            "proof": {"hash": "b" * 16 if self.now == "same" else "c" * 16},
            "facts": [{"at": "/1/1/1", "fact_hash": "a" * 16}]})

    def uses(self, root, name, module=None, cached_only=False, **kw):
        app = self.APP if self.now == "same" else {**self.APP, "result": "LEAN-OTHER-RESULT"}
        return self._answer("app", cached_only, {
            "ok": True, "status": "found", "complete": True, "applications_complete": True,
            "users": [{"name": "Syn.caller"}], "applications": [app]})

    def check(self, root, theorem, target, certifies, module=None, cached_only=False, **kw):
        return self._answer("certificate", cached_only, {
            "ok": True, "status": "checked", "type": "Syn.Spec", "result": "checked",
            "target_fingerprint": "d" * 16 if self.now == "same" else "e" * 16})


def _lean_cited(work, snap, claim, app_hash):
    """A submitted finding resting on a cited fact, an application and a certificate, recorded
    with the pins they carry without the Lean project."""
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        put({"id": "e-fact", "kind": "evidence", "claim": claim, "role": "supports",
             "ref": {"fact": {"decl": "Syn.caller", "module": "Syn.Main", "at": "/1/1/1",
                              "fact_hash": "a" * 16, "proof_hash": "b" * 16}}}),
        put({"id": "e-app", "kind": "evidence", "claim": claim, "role": "supports",
             "ref": {"app": {"callee": "Syn.lemma", "module": "Syn.Main",
                             "id": FakeLean.APP["id"], "caller": "Syn.caller",
                             "app_hash": app_hash}}}),
        put({"id": "e-cert", "kind": "evidence", "claim": claim, "role": "supports",
             "ref": {"certificate": {"theorem": "Syn.cert", "target": "Syn.Spec",
                                     "certifies": "proves", "module": "Syn.Main",
                                     "type": "Syn.Spec", "target_fingerprint": "d" * 16,
                                     "result": "checked"}}}),
        put({"id": "f-lean", "kind": "finding", "claim": claim, "coverage": "full",
             "basis": "reviewed_composition", "evidence": ["e-fact", "e-app", "e-cert"],
             "note": "n"})], snap)
    wsp.update(p, [{"op": "submit", "id": "f-lean", "base_rev": 1}], snap)
    return p


def test_an_export_checks_lean_evidence_against_its_lean_project(tmp_path, monkeypatch):
    """#272: a cited fact, application and certificate are published current when Lean finds
    them as recorded, stale when it finds them changed, and unchecked without the Lean project
    or when Lean did not look (a module not built, a module not loaded, a failed request)."""
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    claim = "P:lem:bound"
    lean = FakeLean(monkeypatch)
    _lean_cited(work, snap, claim, lean.app_hash)
    root = tmp_path / "lean"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "syn"\n[[lean_lib]]\nname = "Syn"\n')

    def states(root):
        rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {claim}, root)[claim]
        return {e["id"]: e["currency"]["state"] for e in rd["evidence"]} | \
            {f["id"]: f["currency"]["state"] for f in rd["findings"]}

    lean.now = "same"
    assert states(root) == {"e-fact": "current", "e-app": "current", "e-cert": "current",
                            "f-lean": "current"}
    # The facts store had no answer, so the export asked Lean, as `workspace show` does.
    assert {(what, cached) for what, cached in lean.asked} >= {
        ("fact", False), ("app", False), ("certificate", False)}
    lean.now = "changed"
    assert states(root) == {"e-fact": "stale", "e-app": "stale", "e-cert": "stale",
                            "f-lean": "stale"}
    for silent in ("not built", "not checked", "probe error", "ambiguous"):
        lean.now = silent
        assert {k: v for k, v in states(root).items() if k.startswith("e-")} == {
            "e-fact": "unchecked", "e-app": "unchecked", "e-cert": "unchecked"}, silent
    # Without the Lean project nothing is asked, and nothing reads as current or stale.
    lean.now, lean.asked = "same", []
    assert {k: v for k, v in states(None).items() if k.startswith("e-")} == {
        "e-fact": "unchecked", "e-app": "unchecked", "e-cert": "unchecked"}
    assert lean.asked == []
    # The published file says the same, and is valid.
    data = tmp_path / "out" / "data"
    import shutil
    shutil.copytree(work / "site" / "data", data)
    pw.write(data, work, lambda cid: EVERYTHING, root=root)
    body = json.loads((data / "work" / "lem_bound.json").read_text())
    from prooflens.schemas import validate
    validate(body, "published-work")
    assert {e["id"]: e["currency"]["state"] for e in body["readings"][0]["evidence"]} == {
        "e-fact": "current", "e-app": "current", "e-cert": "current"}


def test_an_application_lean_did_not_search_is_unchecked_not_gone(tmp_path, monkeypatch):
    """An application not found in a search that left modules out (not built, not loaded) or
    did not describe every application may only be out of sight: unchecked. Found nowhere in a
    complete search, it is gone: stale."""
    from prooflens import uses as us
    root = tmp_path / "lean"
    root.mkdir()
    ref = {"callee": "Syn.lemma", "module": "Syn.Main", "id": FakeLean.APP["id"],
           "caller": "Syn.caller", "app_hash": "x"}
    answer = {"ok": True, "status": "found", "complete": True, "applications_complete": True,
              "users": [], "applications": []}
    for doc, state in (({}, "stale"), ({"complete": False}, "unchecked"),
                       ({"applications_complete": False}, "unchecked"),
                       ({"applications": [{"id": ref["id"], "available": False}],
                         "users": [{"name": "Syn.caller"}]}, "unchecked"),
                       ({"complete": False, "users": [{"name": "Syn.caller"}]}, "stale")):
        monkeypatch.setattr(us, "uses", lambda *a, _d={**answer, **doc}, **k: _d)
        assert us.app_currency(root, ref, check_now=True)["state"] == state, doc


def test_the_lean_project_of_an_export_is_the_one_its_release_was_built_from(tmp_path):
    """The export checks Lean evidence only against the Lean its release was built from: no
    project when the build ran no Lean, or when a Lean input changed since."""
    import types
    from prooflens.export import built_lean_root
    from prooflens.pipeline import lean_inputs_digest
    root = tmp_path / "lean"
    (root / "Syn").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "syn"\n[[lean_lib]]\nname = "Syn"\n')
    (root / "Syn" / "Main.lean").write_text("theorem t : True := trivial\n")
    cfg = types.SimpleNamespace(lean_root=root)
    record = {"body": {"provenance": {"lean_inputs_sha256": lean_inputs_digest(cfg)}}}
    assert built_lean_root(cfg, record) == root
    assert built_lean_root(cfg, {"body": {"provenance": {"lean_inputs_sha256": None}}}) is None
    (root / "Syn" / "Main.lean").write_text("theorem t : True := by trivial\n")
    assert built_lean_root(cfg, record) is None
