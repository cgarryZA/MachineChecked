"""What a recorded difference affects at a use (#503; #112 acceptance 5 and 6, #111 A5): a
finding's `impact` names the difference finding, the use (an application), the requirement at
that use, the outcome and the reviewer's explanation. It is checked when it is written, goes
stale when the application, the difference or the requirement changes (a proof-only change
reopens it while the statement comparison stays current), is listed by `compare --query impact`
per application, and is published. A synthetic build stands in for site data, and the Lean's
answers about applications are given by the test, so no Lean is run.

The synthetic paper: Lemma 2's estimate needs `m + 4` derivatives of the data, and its Lean
(`Syn.inverse_estimate`) proves it with `n + 5`. Theorem 1's construction (`Syn.construct`)
applies it and needs only some finite number of derivatives; Theorem 3 (`Syn.sharp`) applies it
and needs the four-derivative bound; `Syn.third` applies it and nobody has looked."""

import json
import shutil

import pytest

from prooflens import cli
from prooflens import compare as cmp
from prooflens import impact as im
from prooflens import published_work as pw
from prooflens import review_cli as rc
from prooflens import uses as us
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.schemas import validate
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
CLOSED = Publish(pdf=False, source_text=False, lean=False, reviews=False)
LEMMA, CONSTRUCT, SHARP = "P:lem:inverse", "P:thm:construct", "P:thm:sharp"
DECLS = ("Syn.inverse_estimate", "Syn.construct", "Syn.sharp", "Syn.third", "Syn.other")


def make_build(work, fp=None, release="v-1"):
    fps = {n: f"fp:{n}-1" for n in DECLS} | (fp or {})
    data = work / "site" / "data"
    claims = [(LEMMA, "Lemma 2", "lemma", ["Syn.inverse_estimate"]),
              (CONSTRUCT, "Theorem 1", "theorem", ["Syn.construct"]),
              (SHARP, "Theorem 3", "theorem", ["Syn.sharp"])]
    (data / "claims").mkdir(parents=True, exist_ok=True)
    index = []
    for cid, number, kind, links in claims:
        key = cid.split(":", 1)[1]
        f = key.replace(":", "_") + ".json"
        (data / "claims" / f).write_text(json.dumps({
            "id": cid, "paper": "P", "number": number, "kind": kind, "key": key,
            "source_sha256": f"s-{key}", "suggestions": [], "clauses": [], "decls": {},
            "links": [{"name": n, "fingerprint": fps[n], "statement": {"closure": []}}
                      for n in links]}))
        index.append({"id": cid, "paper": "P", "number": number, "kind": kind, "file": f})
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "release": release,
        "project": {"name": "syn", "commit": "abc123"},
        "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123"}], "claims": index}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Syn.Main"} for n in DECLS]))
    return Snapshot(data)


def app(caller, callee="Syn.inverse_estimate", n=0, result="Syn.JetBound f (m + 5) C"):
    """An application as `compare --query uses` describes it, cited without the Lean project."""
    return {"callee": callee, "id": f"app:{caller}:{n}", "caller": caller, "module": "Syn.Main",
            "app_hash": f"h-{caller}-{n}", "arguments": [{"binder": "m", "value": "k"}],
            "premises": [{"binder": "hf", "statement": "Syn.Smooth f", "discharge": "proved",
                          "supplied": "by Syn.smooth_data"}],
            "result": result}


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


DIFFERENCE = {"feature": "derivative order", "paper": "m + 4", "lean": "n + 5",
              "outcome": "difference"}


def setup(tmp_path):
    work = tmp_path / ".machinechecked"
    snap = make_build(work)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        put({"id": "q-est", "kind": "requirement", "claim": LEMMA, "local_id": "r1",
             "form": "conclusion", "text": "the estimate with m + 4 derivatives of f"}),
        put({"id": "e-inv", "kind": "evidence", "claim": LEMMA, "role": "supports",
             "ref": {"decl": "Syn.inverse_estimate"}}),
        put({"id": "f-diff", "kind": "finding", "claim": LEMMA, "requirement": "r1",
             "difference": DIFFERENCE, "evidence": ["e-inv"],
             "note": "The Lean estimate uses one more derivative."}),
        {"op": "submit", "id": "f-diff", "base_rev": 1},
        put({"id": "q-fin", "kind": "requirement", "claim": CONSTRUCT, "local_id": "r2",
             "form": "condition", "text": "some finite number of derivatives of f"}),
        put({"id": "e-use", "kind": "evidence", "claim": CONSTRUCT, "role": "supports",
             "ref": {"app": app("Syn.construct")}}),
        put({"id": "q-four", "kind": "requirement", "claim": SHARP, "local_id": "r1",
             "form": "condition", "text": "the bound with exactly four derivatives"}),
        put({"id": "e-sharp", "kind": "evidence", "claim": SHARP, "role": "supports",
             "ref": {"app": app("Syn.sharp")}}),
        put({"id": "e-other", "kind": "evidence", "claim": CONSTRUCT, "role": "supports",
             "ref": {"app": app("Syn.construct", callee="Syn.other", n=1)}}),
    ], snap)
    return work, snap, p


SUFFICIENT = {"id": "f-imp", "kind": "finding", "claim": CONSTRUCT, "requirement": "r2",
              "impact": {"difference": "f-diff", "use": "e-use",
                         "outcome": "sufficient for this use",
                         "why": "WHY-FINITE: the construction needs some finite number of "
                                "derivatives, and n + 5 is finite"}}
NOT_SUFFICIENT = {"id": "f-sharp", "kind": "finding", "claim": SHARP, "requirement": "r1",
                  "impact": {"difference": "f-diff", "use": "e-sharp",
                             "outcome": "not sufficient",
                             "why": "this consumer uses the four-derivative bound itself"}}


@pytest.fixture
def lean(monkeypatch, tmp_path):
    """The Lean's answers about applications: each current unless the test changes it."""
    state = {"stale": set(), "root": tmp_path / "lean"}
    state["root"].mkdir()

    def currency(root, ref, check_now=False):
        if ref.get("id") in state["stale"]:
            return {"state": "stale", "changes": [{"app": ref["id"], "was": ref.get("app_hash"),
                                                   "now": "h-new",
                                                   "reason": "the application changed"}]}
        return {"state": "current", "changes": []}

    monkeypatch.setattr(us, "app_currency", currency)
    return state


def states(p, snap, root):
    v = wsp.view(wsp.read(p), snap, root=root)
    return {f["id"]: f["currency"] for c in v["claims"].values() for f in c["findings"]}


def test_an_impact_records_the_difference_the_use_the_requirement_and_the_outcome(tmp_path, lean,
                                                                                 capsys):
    """#112 acceptance 5 and #111 A5: five derivatives against four, for a consumer that needs
    only a finite loss, is sufficient for this use; the difference stays recorded."""
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(SUFFICIENT), {"op": "submit", "id": "f-imp", "base_rev": 1}], snap)
    f = wsp.read(p)["records"]["f-imp"]
    imp = f["impact"]
    assert (imp["use"], imp["outcome"]) == ("e-use", "sufficient for this use")
    assert {k: imp["difference"][k] for k in ("finding", "claim", "requirement", "feature",
                                              "paper", "lean", "outcome")} == \
        {"finding": "f-diff", "claim": LEMMA, "requirement": "r1", "feature": "derivative order",
         "paper": "m + 4", "lean": "n + 5", "outcome": "difference"}
    # The use joins the evidence it rests on, and the difference is a dependency of its own.
    assert f["evidence"] == ["e-use"]
    deps = {it["dependency"]: it for it in f["dependencies"]["items"]}
    assert deps["difference"]["record"] == "f-diff" and deps["application"]["record"] == "e-use"
    assert deps["reading"]["requirement"] == "r2"
    cur = states(p, snap, lean["root"])
    assert (cur["f-imp"]["state"], cur["f-diff"]["state"]) == ("current", "current")
    # The difference is still a difference: the impact explains its consequence at one use.
    v = wsp.view(wsp.read(p), snap, root=lean["root"])
    d, = v["claims"][LEMMA]["findings"]
    assert d["difference"]["outcome"] == "difference"
    assert im.impact_words(imp) == "At a use: sufficient for this use"
    cli._print_workspace(v)
    assert "at the use e-use: sufficient for this use; the derivative order difference f-diff" \
        in capsys.readouterr().out
    assert im.difference_words(imp["difference"]) == \
        "the derivative order difference f-diff on P:lem:inverse r1 (paper m + 4; Lean n + 5)"


@pytest.mark.parametrize("change, why", [
    ({"requirement": None}, "names the requirement at the use"),
    ({"impact": {**SUFFICIENT["impact"], "outcome": "fine"}}, "outcome at this use 'fine'"),
    ({"impact": {**SUFFICIENT["impact"], "why": " "}}, "explanation"),
    ({"impact": {**SUFFICIENT["impact"], "difference": "q-fin"}}, "not a finding of this "
                                                                    "workspace that records"),
    ({"impact": {**SUFFICIENT["impact"], "use": "q-fin"}}, "not an evidence record citing an "
                                                            "application"),
    ({"impact": {**SUFFICIENT["impact"], "use": "e-sharp"}}, "evidence for P:thm:sharp"),
    ({"impact": {**SUFFICIENT["impact"], "use": "e-other"}}, "applies Syn.other, but the "
                                                              "difference f-diff is about"),
    ({"impact": {**SUFFICIENT["impact"], "extra": 1}}, "no field extra"),
    ({"coverage": "full"}, "a finding of its own"),
    ({"difference": DIFFERENCE}, "a finding of its own"),
])
def test_an_impact_is_refused_when_it_does_not_hold_together(tmp_path, change, why):
    work, snap, p = setup(tmp_path)
    rec = {k: v for k, v in {**SUFFICIENT, **change}.items() if v is not None}
    with pytest.raises(wsp.WorkspaceError, match=why):
        wsp.update(p, [put(rec)], snap)
    assert "f-imp" not in wsp.read(p)["records"]


def test_one_use_says_nothing_of_another(tmp_path, lean, monkeypatch):
    """#112 acceptance 6: a consumer that needs the sharper bound is not sufficient, and an
    application nobody has looked at has no impact."""
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(SUFFICIENT), put(NOT_SUFFICIENT),
                   {"op": "submit", "id": "f-imp", "base_rev": 1},
                   {"op": "submit", "id": "f-sharp", "base_rev": 1}], snap)
    found = im.recorded(work, snap, "Syn.inverse_estimate", lean["root"])
    assert {(r["use"]["id"], r["outcome"], r["requirement"], r["claim"]) for r in found} == {
        ("app:Syn.construct:0", "sufficient for this use", "r2", CONSTRUCT),
        ("app:Syn.sharp:0", "not sufficient", "r1", SHARP)}
    assert im.recorded(work, snap, "Syn.other", lean["root"]) == []

    # `compare --query impact` lists them by application, and the one with none as such.
    refs = [{"record": "refs", "name": n, "owner": n, "module": "Syn.Main", "kind": "theorem",
             "value_kind": "proof", "statement": [], "value": v}
            for n, v in (("Syn.construct", ["Syn.inverse_estimate"]),
                         ("Syn.sharp", ["Syn.inverse_estimate"]),
                         ("Syn.third", ["Syn.inverse_estimate"]),
                         ("Syn.inverse_estimate", []), ("Syn.other", []))]
    apps = [{**app(c), "available": True, "params": [], "result": {"text": "Syn.JetBound"}}
            for c in ("Syn.construct", "Syn.sharp", "Syn.third")]
    monkeypatch.setattr(us, "uses", lambda root, name, module=None, log=None, **k: {
        "schema": us.SCHEMA, "name": name, "ok": True, "status": "found",
        "declaration": {"name": name, "module": "Syn.Main", "kind": "theorem"},
        "scope": {"libraries": ["Syn"], "modules": 1, "unbuilt": [], "failed": {}},
        "complete": True, "answer": "used", "users": [], "further": [],
        "imports_without_use": [], "applications": apps, "applications_complete": True,
        "applications_note": None})
    monkeypatch.setattr(us, "reference_records", lambda root: {
        "records": refs, "built": ["Syn.Main"], "unbuilt": [], "missing": []})
    site = cmp.Site(work / "site" / "data")
    q = cmp.query(site, "impact", "Syn.inverse_estimate", root=lean["root"],
                  main=["Syn.construct", "Syn.sharp"])
    doc, = q["results"]
    assert [r["finding"] for r in doc["recorded"]] == ["f-imp", "f-sharp"]
    mains = {m["name"]: m for m in doc["main_results"]}
    assert [x["outcome"] for x in mains["Syn.construct"]["impacts"]] == \
        ["sufficient for this use"]
    assert [x["outcome"] for x in mains["Syn.sharp"]["impacts"]] == ["not sufficient"]
    text = im.text(doc)
    assert "app:Syn.construct:0 in Syn.construct: sufficient for this use, for r2 of " \
           "P:thm:construct (some finite number of derivatives of f)" in text
    assert "app:Syn.sharp:0 in Syn.sharp: not sufficient" in text
    assert "no impact recorded at: app:Syn.third:0" in text


def test_an_impact_goes_stale_with_its_use_its_difference_or_its_requirement(tmp_path, lean):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(SUFFICIENT), put(NOT_SUFFICIENT),
                   {"op": "submit", "id": "f-imp", "base_rev": 1},
                   {"op": "submit", "id": "f-sharp", "base_rev": 1}], snap)
    root = lean["root"]
    # A proof-only change: the caller elaborates the application otherwise. Its impact is
    # reopened; the statement comparison and the other use stay current.
    lean["stale"] = {"app:Syn.construct:0"}
    cur = states(p, snap, root)
    assert {k: v["state"] for k, v in cur.items()} == \
        {"f-diff": "current", "f-imp": "stale", "f-sharp": "current"}
    assert any("application changed" in (c.get("reason") or "")
               for c in cur["f-imp"]["changes"])
    lean["stale"] = set()

    # The lemma's Lean changed: the difference is stale, and so is every impact of it.
    snap2 = make_build(work, fp={"Syn.inverse_estimate": "fp:changed"}, release="v-2")
    cur = states(p, snap2, root)
    assert {k: v["state"] for k, v in cur.items()} == \
        {"f-diff": "stale", "f-imp": "stale", "f-sharp": "stale"}
    assert cur["f-imp"]["changes"][0]["reason"] == "what the difference f-diff rests on changed"

    # The difference is superseded: its impacts read it no longer.
    snap = make_build(work)
    wsp.update(p, [{"op": "supersede", "id": "f-diff", "base_rev": 2,
                    "reason": "the Lean was read again",
                    "record": {"id": "f-diff2", "requirement": "r1", "evidence": ["e-inv"],
                               "difference": {**DIFFERENCE, "lean": "n + 6"},
                               "note": "Two more derivatives."}}], snap)
    cur = states(p, snap, root)
    assert cur["f-imp"]["state"] == "stale" and cur["f-diff2"]["state"] == "current"
    assert cur["f-imp"]["changes"][0]["reason"] == \
        "the difference f-diff the impact concerns is superseded by f-diff2"
    # A new impact names the difference in force; the superseded one is refused.
    with pytest.raises(wsp.WorkspaceError, match="superseded by f-diff2"):
        wsp.update(p, [put({**SUFFICIENT, "id": "f-imp2"})], snap)

    # The requirement at the use is edited: the submitted impact is reopened.
    work3 = tmp_path / "b"
    work3.mkdir()
    w3, s3, p3 = setup(work3)
    wsp.update(p3, [put(SUFFICIENT), {"op": "submit", "id": "f-imp", "base_rev": 1}], s3)
    q = wsp.read(p3)["records"]["q-fin"]
    wsp.update(p3, [put({k: q[k] for k in ("kind", "claim", "local_id", "form")}
                        | {"id": "q-fin", "text": "at most six derivatives of f"},
                        base=q["rev"])], s3)
    cur = states(p3, s3, root)
    assert cur["f-imp"]["state"] == "stale"
    assert any("requirement" in (c.get("reason") or "") for c in cur["f-imp"]["changes"])


def test_an_impact_is_published_with_its_difference_and_use(tmp_path, lean):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(SUFFICIENT), {"op": "submit", "id": "f-imp", "base_rev": 1}], snap)
    data = tmp_path / "out" / "data"
    shutil.copytree(work / "site" / "data", data)
    pw.write(data, work, lambda cid: EVERYTHING, root=lean["root"])
    body = json.loads((data / "work" / "thm_construct.json").read_text())
    validate(body, "published-work")
    rd, = body["readings"]
    f, = rd["findings"]
    assert f["impact"]["outcome"] == "sufficient for this use"
    assert f["impact"]["why"].startswith("WHY-FINITE")
    assert (f["impact"]["difference"]["paper"], f["impact"]["difference"]["lean"]) == \
        ("m + 4", "n + 5")
    assert [e["id"] for e in rd["evidence"]] == ["e-use"]
    assert any(it["dependency"] == "difference" for it in f["dependencies"]["items"])
    assert f["currency"]["state"] == "current"
    # The lemma's own reading publishes the difference, unchanged.
    lem = json.loads((data / "work" / "lem_inverse.json").read_text())
    assert lem["readings"][0]["findings"][0]["difference"]["outcome"] == "difference"
    # Without the reviews, the source text and the Lean: the outcome and the ids, no words.
    rd, = pw.readings(work, snap, lambda cid: CLOSED, {CONSTRUCT}, root=lean["root"])[CONSTRUCT]
    f, = rd["findings"]
    assert "WHY-FINITE" not in json.dumps(rd) and "impact.why" in f["withheld"]
    assert "paper" not in f["impact"]["difference"] and "lean" not in f["impact"]["difference"]
    assert (f["impact"]["outcome"], f["impact"]["use"], f["impact"]["difference"]["finding"]) == \
        ("sufficient for this use", "e-use", "f-diff")
    validate({"schema": pw.SCHEMA, "release": "v-1", "claim": CONSTRUCT, "readings": [rd]},
             "published-work")
