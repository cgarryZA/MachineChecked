"""How the selected main results use each link (#551), on synthetic records: in zero
configuration, `check --json` and the site data say, for each link and each main result, whether
its proof uses it (directly or through other declarations), its statement only, neither
(formalized separately), or whether that is not traced; the answer states whose main results
they are. It is read from the references the facts store holds, on one graph, and starts no
Lean. A full assessment says it is not available (#480).

The references, as Lean's terms would make them: `Syn.main`'s proof applies `Syn.variant`, a
variant of the paper's lemma, through `Syn.step`; `Syn.faithful` states the lemma as printed and
is proved from the variant, and nothing the main result uses applies it. `Syn.main`'s statement
uses `Syn.Scale`, and its proof does not. `Syn.second`'s proof reaches `Syn.gone`, whose module's
references are not recorded.
"""

import json
from pathlib import Path

import pytest

from test_impact import ref

from prooflens import compare as cmp
from prooflens import impact as im
from prooflens import review_cli as rc
from prooflens import uses as us
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

RECORDS = [
    ref("Syn.main", ["Syn.Scale"], ["Syn.step"]),
    ref("Syn.step", [], ["Syn.variant"]),
    ref("Syn.variant", [], []),
    ref("Syn.faithful", [], ["Syn.variant"]),
    ref("Syn.Scale", kind="def"),
    ref("Syn.second", [], ["Syn.gone"], module="Syn.Second"),
]
BUILT = ["Syn.Gone", "Syn.Main", "Syn.Second"]
CLAIMS = [
    ("thm:main", "theorem", "Theorem 1", ["Syn.main"]),
    ("lem:bound", "lemma", "Lemma 2", ["Syn.faithful", "Syn.variant"]),
    ("lem:step", "lemma", "Lemma 3", ["Syn.step"]),
    ("def:scale", "definition", "Definition 4", ["Syn.Scale"]),
    ("thm:second", "theorem", "Theorem 5", ["Syn.second"]),
    ("lem:outside", "lemma", "Lemma 6", ["Other.lemma"]),
    ("lem:none", "lemma", "Lemma 7", []),
]
WHO = rc.parse_reviewer("human:A-Auditor")


def write_site(tmp: Path, mode="simple") -> Path:
    data = tmp / "work" / "site" / "data"
    (data / "claims").mkdir(parents=True)
    index = []
    for key, kind, number, links in CLAIMS:
        cid = f"S:{key}"
        ch = {"id": cid, "key": key, "paper": "S", "number": number, "kind": kind,
              "status": "linked: Lean proof checked", "status_code": "link.checked",
              "links": [{"name": n} for n in links], "clauses": [], "suggestions": []}
        f = f"S_{key.replace(':', '_')}.json"
        (data / "claims" / f).write_text(json.dumps(ch))
        index.append({"id": cid, "paper": "S", "number": number, "file": f,
                      "status": ch["status"]})
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": mode, "release": "v-synthetic",
        "evidence": "e" * 64, "project": {"name": "syn", "commit": "c" * 40},
        "papers": [{"id": "S", "title": "Synthetic"}], "claims": index}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": r["name"], "kind": r["kind"], "module": r["module"]} for r in RECORDS]))
    return data


@pytest.fixture
def lean(tmp_path, monkeypatch):
    """The references the facts store holds; asking Lean anything fails the test."""
    root = tmp_path / "lean"
    for m in BUILT:
        p = root / Path(*m.split(".")).with_suffix(".lean")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    (root / "Syn" / "Gone.lean").write_text("namespace Syn\ntheorem gone : True := trivial\n"
                                            "end Syn\n")
    reads = []

    def refs(root_):
        reads.append(root_)
        return {"records": list(RECORDS), "built": BUILT, "unbuilt": [], "missing": ["Syn.Gone"]}

    def no_lean(*a, **k):
        raise AssertionError("Lean was asked")
    monkeypatch.setattr(us, "reference_records", refs)
    monkeypatch.setattr(us, "uses", no_lean)
    return {"root": root, "reads": reads}


def uses_of(doc, claim, link):
    return {e["main"]: e for e in doc["claims"][f"S:{claim}"][link]}


def test_each_link_says_how_each_main_result_uses_it(tmp_path, lean):
    data = write_site(tmp_path)
    doc = im.link_uses(cmp.Site(data), lean["root"])
    assert doc["schema"] == im.LINK_USE_SCHEMA and doc["available"] is True
    sel = doc["selection"]
    assert sel["basis"] == "suggested" and sel["rule"] == im.SUGGESTED
    assert [m["name"] for m in sel["main_results"]] == ["Syn.main", "Syn.second"]
    # The variant the main proof uses, beside the paper-faithful wrapper it does not.
    bound = doc["claims"]["S:lem:bound"]
    assert list(bound) == ["Syn.faithful", "Syn.variant"]
    v = uses_of(doc, "lem:bound", "Syn.variant")["Syn.main"]
    assert (v["use"], v["through"], v["path"]) == ("proof", 1, ["Syn.main", "Syn.step",
                                                                "Syn.variant"])
    assert v["answer"] == "used by its proof, through 1 other declaration"
    f = uses_of(doc, "lem:bound", "Syn.faithful")["Syn.main"]
    assert f == {"main": "Syn.main", "use": "none",
                 "answer": "formalized separately: not used by this main result"}
    d = uses_of(doc, "lem:step", "Syn.step")["Syn.main"]
    assert (d["use"], d["through"], d["answer"]) == ("proof", 0, "used by its proof, directly")
    s = uses_of(doc, "def:scale", "Syn.Scale")["Syn.main"]
    assert (s["use"], s["answer"]) == (
        "statement", "in its statement only, directly: not used by its proof")
    assert uses_of(doc, "thm:main", "Syn.main")["Syn.main"]["answer"] == \
        "this is the main result itself"
    # A main result whose trace reaches unrecorded references is not traced, never unused.
    second = uses_of(doc, "lem:bound", "Syn.faithful")["Syn.second"]
    assert second["use"] == "not traced" and "Syn.gone" in second["answer"]
    assert "formalized separately" not in second["answer"]
    # A link whose own references are not recorded is not looked for.
    out = uses_of(doc, "lem:outside", "Other.lemma")["Syn.main"]
    assert out["use"] == "not traced" and out["answer"].startswith("not traced: for Other.lemma, ")
    assert "S:lem:none" not in doc["claims"]
    assert doc["complete"] is False and doc["scope"]["without_references"] == ["Syn.Gone"]
    # One read of the stored references for every link; no Lean.
    assert len(lean["reads"]) == 1


def test_check_reads_the_same_from_the_view_it_computed(tmp_path, lean):
    data = write_site(tmp_path)
    body = {"commit": "c" * 40, "claims": [
        {"id": f"S:{k}", "number": n, "kind": kind, "links": [{"name": x} for x in links]}
        for k, kind, n, links in CLAIMS]}
    from_site = im.link_uses(cmp.Site(data), lean["root"])
    from_view = im.view_link_uses({"body": body}, lean["root"], tmp_path / "nowork")
    assert from_view == from_site


def test_the_saved_selection_is_traced_and_attributed(tmp_path, lean):
    data = write_site(tmp_path)
    work = data.parent.parent
    snap = Snapshot(data)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [{"op": wsp.MAIN_OP, "main": ["Lemma 3"]}], snap, lean["root"])
    doc = im.site_link_uses(data, lean["root"], work)
    sel = doc["selection"]
    assert (sel["basis"], sel["workspace"], sel["by"]) == ("saved", wsp.read(p)["id"], WHO["id"])
    assert sel["pins"] == {"release": "v-synthetic", "commit": "c" * 40} and sel["problems"] == []
    assert [m["name"] for m in sel["main_results"]] == ["Syn.step"]
    assert uses_of(doc, "lem:bound", "Syn.variant")["Syn.step"]["answer"] == \
        "used by its proof, directly"
    assert uses_of(doc, "lem:bound", "Syn.faithful")["Syn.step"]["use"] == "none"
    # Written beside the site data for the reader.
    written = im.write_link_uses(data, lean["root"], work)
    assert json.loads((data / im.MAIN_USE_FILE).read_text()) == written == doc
    # Two workspaces' selections are never merged: not available, naming both.
    q = wsp.open_for(work, rc.parse_reviewer("human:B-Auditor"), "informed",
                     sources=snap.sources())
    wsp.update(q, [{"op": wsp.MAIN_OP, "main": ["Theorem 1"]}], snap, lean["root"])
    doc = im.site_link_uses(data, lean["root"], work)
    assert doc["available"] is False and "several workspaces save main results" in doc["reason"]
    assert wsp.read(p)["id"] in doc["reason"] and wsp.read(q)["id"] in doc["reason"]


def test_a_full_assessment_says_it_is_not_available(tmp_path, lean):
    data = write_site(tmp_path, mode="full")
    doc = im.site_link_uses(data, lean["root"], data.parent.parent)
    assert doc == {"schema": im.LINK_USE_SCHEMA, "available": False,
                   "reason": im.FULL_UNAVAILABLE}
    assert "#480" in doc["reason"] and lean["reads"] == []
