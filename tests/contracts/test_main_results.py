"""The main results an auditor saves in a workspace (#112): checked when saved, attributed and
pinned to the release and project commit, traced from by `compare --query impact` when `--main`
is not given (which says whose selection it traces from), reported when the build no longer has
what they name, carried by an import, and published with the audit. The synthetic records of
test_impact stand in for Lean; no Lean runs and no status changes."""

import copy
import json
import re
import shutil

import jsonschema
import pytest

from test_impact import RECORDS, by_name, lean, write_site  # noqa: F401 (`lean` is a fixture)

from prooflens import cli
from prooflens import compare as cmp
from prooflens import impact as im
from prooflens import published_work as pw
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.published import AuditError
from prooflens.schemas import schema
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
OTHER = rc.parse_reviewer("human:B-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
# Declarations the build indexes besides those with recorded references: one about to be
# removed, and one that two modules declare.
EXTRA = [("Syn.retired", "Syn.Main"), ("Syn.twin", "Syn.A"), ("Syn.twin", "Syn.B")]


def lean_index(data, extra=EXTRA):
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": r["name"], "kind": r["kind"], "module": r["module"]}
         for r in RECORDS if r["owner"] == r["name"]]
        + [{"name": n, "kind": "theorem", "module": m} for n, m in extra]))


@pytest.fixture
def work(tmp_path, lean):
    lean_index(write_site(tmp_path))
    return tmp_path / "work"


def data_of(work):
    return work / "site" / "data"


def save(work, lean, main, who=WHO, by=None):
    snap = Snapshot(data_of(work))
    p = wsp.open_for(work, who, "informed", sources=snap.sources())
    return p, wsp.update(p, [{"op": wsp.MAIN_OP, "main": main}], snap, lean["root"], by)


def ask(work, lean, target, main=None, workspace=None):
    q = cmp.query(cmp.Site(data_of(work)), "impact", target, root=lean["root"], main=main,
                  workspace=workspace)
    (doc,) = q["results"]
    assert doc["ok"]
    return doc


def test_main_results_are_checked_attributed_and_pinned_when_saved(work, lean):
    p, ack = save(work, lean, ["Theorem 1", "Syn.step", "Syn.A:Syn.twin", "S:thm:main"])
    assert ack["changed"] == ["main_results"]
    sel = wsp.read(p)["main_results"]
    assert sel["selected"] == [{"claim": "S:thm:main"},
                               {"decl": "Syn.step", "module": "Syn.Main", "build": "built"},
                               {"decl": "Syn.twin", "module": "Syn.A", "build": "built"}]
    assert sel["by"] == WHO["id"] and sel["at"]
    assert sel["pins"] == {"release": "v-synthetic", "commit": "c" * 40}
    # A name that resolves to nothing, or to several, is refused with the reason; nothing is
    # written.
    snap = Snapshot(data_of(work))
    before = p.read_bytes()
    for bad, why in (
            (["Syn.nothing"], "Syn.nothing is neither a claim of release v-synthetic nor a "
                              "declaration of the project"),
            (["S:thm:gone"], "S:thm:gone is neither a claim"),
            (["Syn.twin"], "Syn.twin is declared in several modules (Syn.A, Syn.B); name one as "
                           "MODULE:NAME"),
            ([{"claim": "Lemma 99"}], "no claim 'Lemma 99' in release v-synthetic"),
            ([""], "a main result is a claim or a declaration"),
            ("Theorem 1", "`main` is a list")):
        with pytest.raises(wsp.WorkspaceError, match=re.escape(why)):
            wsp.update(p, [{"op": wsp.MAIN_OP, "main": bad}], snap, lean["root"])
    with pytest.raises(wsp.WorkspaceError, match="checked against a build"):
        wsp.update(p, [{"op": wsp.MAIN_OP, "main": ["Theorem 1"]}], None, None)
    assert p.read_bytes() == before
    # The same selection, however named, changes nothing; another replaces it, and the one it
    # replaces is kept in the provenance; an empty one removes it.
    same = ["1", {"decl": "Syn.step"}, {"decl": "Syn.twin", "module": "Syn.A"}]
    assert wsp.update(p, [{"op": wsp.MAIN_OP, "main": same}], snap,
                      lean["root"])["changed"] == []
    save(work, lean, ["Lemma 3"], by=OTHER["id"])
    ws = wsp.read(p)
    assert ws["main_results"]["selected"] == [{"claim": "S:lem:apart"}]
    assert ws["main_results"]["by"] == OTHER["id"]
    assert ws["provenance"][-1]["event"] == "main results replaced"
    assert ws["provenance"][-1]["was"] == sel and ws["provenance"][-1]["by"] == OTHER["id"]
    assert OTHER["id"] in wsp.auditors(ws)
    save(work, lean, [])
    ws = wsp.read(p)
    assert "main_results" not in ws
    assert ws["provenance"][-1]["was"]["selected"] == [{"claim": "S:lem:apart"}]


def test_impact_traces_from_the_saved_main_results_and_says_whose_they_are(work, lean):
    data = data_of(work)
    before = {f: f.read_bytes() for f in data.rglob("*") if f.is_file()}
    p, _ = save(work, lean, ["Lemma 3", "Syn.step", "Lemma 7"])
    wid = wsp.read(p)["id"]
    doc = ask(work, lean, "Syn.used")
    sel = doc["selection"]
    assert (sel["basis"], sel["workspace"], sel["reviewer"], sel["by"]) == (
        "saved", wid, WHO["id"], WHO["id"])
    assert sel["pins"] == {"release": "v-synthetic", "commit": "c" * 40} and sel["at"]
    assert sel["selected"][0] == {"claim": "S:lem:apart"} and sel["problems"] == []
    assert sel["unlinked_claims"] == ["S:lem:none"] and "note" not in sel
    assert "workspace main" in sel["edit"]
    mains = by_name(doc)
    assert list(mains) == ["Syn.apart", "Syn.step"]
    assert mains["Syn.apart"]["selected"] == ["S:lem:apart"]
    assert mains["Syn.step"]["selected"] == ["named"]
    assert mains["Syn.apart"]["use"] == "proof" and mains["Syn.step"]["direct"] is True
    t = im.text(doc)
    assert (f"Main results (saved in workspace {wid} by human:A-Auditor at {sel['at']}, "
            "against project commit ccccccc):") in t
    assert "S:lem:none: no Lean is linked to this claim" in t
    # `--main` names others for one question; the saved selection stays as it was.
    doc = ask(work, lean, "Syn.used", main=["Syn.main"])
    assert doc["selection"]["basis"] == "given" and list(by_name(doc)) == ["Syn.main"]
    assert "Main results (named with --main):" in im.text(doc)
    assert wsp.read(p)["main_results"]["selected"][0] == {"claim": "S:lem:apart"}
    # The build is read, never written: no status changes.
    assert {f: f.read_bytes() for f in data.rglob("*") if f.is_file()} == before


def test_what_the_build_no_longer_has_is_reported_not_dropped(work, lean):
    p, _ = save(work, lean, ["Theorem 5", "Syn.retired", "Syn.B:Syn.twin", "Theorem 1"])
    # A later build: Theorem 5 is gone, Syn.retired is declared nowhere, Syn.twin only in
    # Syn.A, and the project is at another commit.
    data = data_of(work)
    idx = json.loads((data / "index.json").read_text())
    idx["claims"] = [c for c in idx["claims"] if c["id"] != "S:thm:second"]
    idx["project"]["commit"] = "d" * 40
    (data / "index.json").write_text(json.dumps(idx))
    lean_index(data, [("Syn.twin", "Syn.A")])
    doc = ask(work, lean, "Syn.used")
    sel = doc["selection"]
    assert sel["problems"] == [
        {"claim": "S:thm:second", "problem": "no claim S:thm:second in release v-synthetic"},
        {"decl": "Syn.retired", "module": "Syn.Main",
         "problem": "Syn.retired is not declared in Syn.Main in this build"},
        {"decl": "Syn.twin", "module": "Syn.B",
         "problem": "Syn.twin is not declared in Syn.B in this build; it is declared in Syn.A"}]
    assert sel["note"] == "saved against project commit ccccccc; this build is of commit ddddddd"
    # A declaration stays a main result, not traced; the selection is not quietly narrowed.
    mains = by_name(doc)
    assert list(mains) == ["Syn.retired", "Syn.twin", "Syn.main"]
    assert mains["Syn.retired"]["use"] == "not traced" and doc["complete"] is False
    t = im.text(doc)
    assert "S:thm:second: saved as a main result, but no claim S:thm:second in release " \
           "v-synthetic" in t
    assert "(saved against project commit ccccccc; this build is of commit ddddddd)" in t
    # `workspace show` reports the same against the build.
    v = wsp.view(wsp.read(p), Snapshot(data), None, lean["root"])
    assert v["main_results"]["problems"] == sel["problems"]


def test_several_saved_selections_are_chosen_between_never_merged(work, lean):
    p1, _ = save(work, lean, ["Theorem 1"])
    p2, _ = save(work, lean, ["Lemma 3"], who=OTHER)
    w1, w2 = wsp.read(p1)["id"], wsp.read(p2)["id"]
    with pytest.raises(cmp.CompareError) as e:
        ask(work, lean, "Syn.used")
    assert e.value.kind == "ambiguous" and sorted(e.value.candidates) == sorted([w1, w2])
    assert "--workspace ID" in str(e.value)
    doc = ask(work, lean, "Syn.used", workspace=w2)
    assert doc["selection"]["workspace"] == w2 and list(by_name(doc)) == ["Syn.apart"]
    # A workspace that saves none: the suggestion, saying so.
    w3 = wsp.read(wsp.open_for(work, rc.parse_reviewer("human:C-Auditor"), "informed"))["id"]
    sel = ask(work, lean, "Syn.used", workspace=w3)["selection"]
    assert sel["basis"] == "suggested" and sel["note"] == f"workspace {w3} saves no main results"
    with pytest.raises(cmp.CompareError) as e:
        ask(work, lean, "Syn.used", workspace="ws-000000000000")
    assert e.value.kind == "unknown-workspace"


def test_an_import_brings_the_main_results_and_keeps_a_different_selection(work, lean):
    p, _ = save(work, lean, ["Theorem 1"])
    body = wsp.export(p)
    snap = Snapshot(data_of(work))
    save(work, lean, [])
    res = wsp.import_(work, body, snap, WHO["id"])
    assert "main_results" in res["added"] and res["conflicts"] == []
    assert wsp.read(p)["main_results"]["selected"] == [{"claim": "S:thm:main"}]
    save(work, lean, ["Lemma 3"])
    res = wsp.import_(work, body, snap, WHO["id"])
    (c,) = res["conflicts"]
    assert c["id"] == "main_results" and c["proposed"]["selected"] == [{"claim": "S:thm:main"}]
    assert wsp.read(p)["main_results"]["selected"] == [{"claim": "S:lem:apart"}]
    body["main_results"]["selected"].append({"claim": "S:thm:gone"})
    res = wsp.import_(work, body, snap, WHO["id"])
    assert {"record": "main_results",
            "problem": "no claim S:thm:gone in release v-synthetic"} in res["problems"]


def test_the_command_line_saves_shows_and_traces_from_them(work, lean, tmp_path, monkeypatch,
                                                           capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "lakefile.toml").write_text('name = "syn"\n[[lean_lib]]\nname = "Syn"\n')
    shutil.copytree(work, proj / ".machinechecked")
    monkeypatch.chdir(proj)
    monkeypatch.setenv("MACHINECHECKED_REVIEWER", WHO["id"])
    cli.main(["workspace", "main"])
    out = capsys.readouterr().out
    assert "saves no main results; `compare --query impact` traces the suggestion" in out
    assert "  Syn.main  [S:thm:main]" in out
    cli.main(["workspace", "main", "Theorem 1", "Syn.step"])
    out = capsys.readouterr().out
    assert "main results saved by human:A-Auditor" in out
    assert "against release v-synthetic, project commit ccccccc:" in out
    assert "  S:thm:main (Theorem 1), its linked Lean" in out and "  Syn.step (Syn.Main)" in out
    cli.main(["workspace", "main", "--json"])
    j = json.loads(capsys.readouterr().out)
    assert j["main_results"]["selected"][1] == {"decl": "Syn.step", "module": "Syn.Main",
                                                "build": "built"}
    assert j["main_results"]["problems"] == [] and j["suggested"] is None
    cli.main(["compare", "--query", "impact", "Syn.used"])
    assert f"saved in workspace {j['workspace']} by human:A-Auditor" in capsys.readouterr().out
    cli.main(["workspace", "show"])
    assert "  main results: S:thm:main, Syn.step (saved by human:A-Auditor" in \
        capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["workspace", "main", "Syn.nothing"])
    err = capsys.readouterr().err
    assert e.value.code and "Syn.nothing is neither a claim" in err
    assert err.count("Syn.twin") == 1
    cli.main(["workspace", "main", "--clear"])
    assert "saves no main results" in capsys.readouterr().out


def test_a_published_audit_carries_each_saved_selection(work, lean, tmp_path):
    p, _ = save(work, lean, ["Theorem 1", "Syn.step", "Syn.retired"])
    data = tmp_path / "out" / "data"
    shutil.copytree(data_of(work), data)
    lean_index(data, EXTRA[1:])
    pw.write(data, work, lambda cid: EVERYTHING)
    idx = json.loads((data / "index.json").read_text())
    (m,) = idx["main_results"]
    jsonschema.validate(idx["main_results"],
                        schema("manifest-index")["properties"]["main_results"])
    ws = wsp.read(p)
    assert (m["workspace"], m["mode"], m["by"], m["at"]) == (
        ws["id"], "informed", WHO["id"], ws["main_results"]["at"])
    assert m["reviewer"] == {"id": "human:A-Auditor", "kind": "human", "name": "A Auditor",
                             "identity": "self-declared"}
    assert m["pins"] == {"release": "v-synthetic", "commit": "c" * 40}
    assert m["selected"] == ws["main_results"]["selected"]
    assert m["problems"] == [{"decl": "Syn.retired", "module": "Syn.Main",
                              "problem": "Syn.retired is not declared in Syn.Main in this build"}]
    assert "left_out" not in m
    plain = json.loads((data_of(work) / "index.json").read_text())
    assert idx["claims"] == plain["claims"]
    # Published data that cannot name an entry (a claim of a paper it does not publish, or a
    # declaration it neither records nor indexes) counts it and does not name it.
    raw = json.loads(p.read_text())
    raw["main_results"]["selected"].append({"claim": "Q:thm:other"})
    p.write_text(json.dumps(raw))
    other = tmp_path / "one" / "data"
    shutil.copytree(data_of(work), other)
    (other / "lean-index.json").unlink()
    pw.write(other, work, lambda cid: EVERYTHING)
    text = (other / "index.json").read_text()
    (m,) = json.loads(text)["main_results"]
    assert m["selected"] == [{"claim": "S:thm:main"}] and m["left_out"]["count"] == 3
    assert m["problems"] == [] and "Q:thm:other" not in text and "Syn.step" not in text
    # The site's loader accepts the index with them, and refuses a malformed entry.
    import published_fixture as pf
    files = pf.files()
    files["data/index.json"]["main_results"] = idx["main_results"]
    loaded = pf.snapshot(files)
    assert [c["status_code"] for c in loaded["claims"]] == \
        [c["status_code"] for c in pf.snapshot()["claims"]]
    bad = copy.deepcopy(files)
    del bad["data/index.json"]["main_results"][0]["pins"]
    with pytest.raises(AuditError, match="manifest-index"):
        pf.snapshot(bad)
