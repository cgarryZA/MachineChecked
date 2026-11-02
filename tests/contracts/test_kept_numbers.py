"""A reference in the Lean to a paper number of an earlier revision shows its counterpart in this
one through the version maps the auditors' workspaces keep (#462, from #127): in `check`, on the
claim page and in `compare`. Only a map whose later side is this build applies; several maps that
disagree give several counterparts; the stored content and every status stay as they were. A
synthetic paper in two revisions and small synthetic builds stand in for real ones, so no Lean
runs."""

import copy
import json

from test_reopen import WHO, setting, site  # noqa: F401  (`setting` is a fixture)

from prooflens import cli
from prooflens import compare as cmp
from prooflens import content as cm
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot


def ref(rid, number, decl, status="exact", stale=False):
    """A reference of the Lean to a paper number, as the paper-number check gives it."""
    return {"id": rid, "kind": "theorem", "number": number.split()[-1], "reference": number,
            "status": status, "detail": f"a synthetic check of {number}",
            "source": {"where": "docstring", "declaration": decl, "file": "Ex/Basic.lean",
                       "line": 3},
            "paper": {"claims": []}, **({"stale_lead": True} if stale else {})}


def content():
    refs = [ref("n-moved", "Theorem 2.1", "Ex.moved", stale=True),
            ref("n-gone", "Theorem 2.4", "Ex.standing", stale=True),
            ref("n-absent", "Theorem 9.9", "Ex.edit", status="absent"),
            ref("n-exact", "Theorem 1.2", "Ex.keep")]
    for o in refs:
        o["message"] = f"the docstring of {o['source']['declaration']} cites {o['reference']}"
    return {"schema": cm.SCHEMA, "numbering": {"references": refs, "pattern": {"drift": False}}}


def kept(setting):
    """The map kept in the workspace, and the later release built."""
    p, work = setting["path"], setting["work"]
    wsp.update(p, [{"op": "version-map", "map": setting["map"]}],
               Snapshot(work / "site" / "data"))
    site(work, "r-2", setting["new"], setting["b"])
    return json.loads((work / "site" / "data" / "index.json").read_text())


def by_id(refs):
    return {o["id"]: o for o in refs}


def test_a_stale_number_shows_its_counterpart_through_a_kept_map(setting):
    index = kept(setting)
    work = setting["work"]
    before = content()
    got = cm.with_kept_maps(before, work, index)
    assert before == content(), "the stored content is not changed"
    r = by_id(got["numbering"]["references"])
    cur = r["n-moved"]["current"]
    assert (cur["reference"], cur["claims"]) == ("Theorem 2.2", ["T:thm:moved"])
    (src,) = cur["source"]["kept"]
    ws = wsp.read(setting["path"])
    assert (src["workspace"], src["kept_by"], src["paper"]) == (ws["id"], WHO["id"], "T")
    assert (src["from"]["release"], src["to"]["release"]) == ("r-1", "r-2")
    assert r["n-moved"]["message"].endswith(
        "; the version map kept by human:A-Auditor gives Theorem 2.2")
    # A removed claim has no counterpart; a number the map does not know, and one that agrees
    # with the paper, are left as they were.
    assert r["n-gone"]["current"]["none"] is True
    assert r["n-gone"]["message"].endswith(
        "; the version map kept by human:A-Auditor finds no counterpart of it in this version")
    assert "current" not in r["n-absent"] and "current" not in r["n-exact"]
    # `check` prints it.
    msgs = {w["id"]: w["message"] for w in cli._reference_warnings(got["numbering"])}
    assert msgs["n-moved"].endswith("gives Theorem 2.2")
    # The claim page: the claim whose Lean the reference is in shows it.
    chunk = json.loads((work / "site" / "data" / "claims" / "thm_moved.json").read_text())
    _, chunks = cm.apply(index, {"thm_moved.json": chunk}, got)
    (o,) = chunks["thm_moved.json"]["references"]
    assert o["current"]["reference"] == "Theorem 2.2"


def test_only_a_map_to_this_build_applies(setting):
    p, work = setting["path"], setting["work"]
    m = copy.deepcopy(setting["map"])
    m["to"] = {"release": "r-2", "revision": "rev-b"}
    wsp.update(p, [{"op": "version-map", "map": m}], Snapshot(work / "site" / "data"))
    site(work, "r-2", setting["new"], setting["b"])
    index = json.loads((work / "site" / "data" / "index.json").read_text())
    other = {**index, "release": "r-3",
             "papers": [{**x, "revision": "rev-c"} for x in index["papers"]]}
    before = content()
    assert cm.with_kept_maps(before, work, other) is before
    # A build of another release at the paper revision the map leads to: its numbers are those.
    same_paper = {**other, "papers": [{**x, "revision": "rev-b"} for x in index["papers"]]}
    got = cm.with_kept_maps(content(), work, same_paper)
    assert by_id(got["numbering"]["references"])["n-moved"]["current"]["reference"] == \
        "Theorem 2.2"


def test_maps_that_disagree_give_several_counterparts(setting):
    index = kept(setting)
    work = setting["work"]
    # Another auditor keeps a map from another earlier revision, where Theorem 2.1 is today's
    # Theorem 2.3.
    other = copy.deepcopy(setting["map"])
    other["from"] = {"release": "r-0", "revision": "r0"}
    other["numbers"] = [{"old": "Theorem 2.1", "new": ["Theorem 2.3"],
                         "match": {"class": "moved", "by": ["text"], "from": "T:thm:edit",
                                   "to": ["T:thm:edit"]}}]
    q = wsp.open_for(work, rc.parse_reviewer("human:B-Auditor"), "informed")
    wsp.update(q, [{"op": "version-map", "map": other}], Snapshot(work / "site" / "data"))
    got = cm.with_kept_maps(content(), work, index)
    o = by_id(got["numbering"]["references"])["n-moved"]
    assert o["current"]["ambiguous"] == ["Theorem 2.2", "Theorem 2.3"]
    assert len(o["current"]["source"]["kept"]) == 2
    assert o["message"].endswith("; the version maps kept by human:A-Auditor and "
                                 "human:B-Auditor give several: Theorem 2.2, Theorem 2.3")


def test_compare_shows_the_counterpart_from_the_maps_kept_now(setting):
    index = kept(setting)
    data = setting["work"] / "site" / "data"
    # The build was written before the map was kept: its chunk has the reference alone.
    p = data / "claims" / "thm_moved.json"
    chunk = json.loads(p.read_text())
    chunk["references"] = [content()["numbering"]["references"][0]]
    p.write_text(json.dumps(chunk))
    pk = cmp.claim_packet(cmp.Site(data), "T:thm:moved", "compare")
    (o,) = pk["lean"]["references"]
    assert o["current"]["reference"] == "Theorem 2.2"
    assert "the version map kept by human:A-Auditor gives Theorem 2.2" in cmp.packet_text(pk)
    # Reading the paper alone shows no Lean, so no reference.
    assert "lean" not in cmp.claim_packet(cmp.Site(data), "T:thm:moved", "read")
    assert index["release"] == "r-2"
