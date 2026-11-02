"""A record that read a claim's passage is not current once the paper prints other text (#433).

A build of the full assessment pins each passage by the inventory's digest and checks that
digest against the manuscript (`source_matches`). When the text changes and the inventory is not
pinned again, the pin stays the same and the check fails: a finding, a quoted passage, a passage
attached to a requirement, a question and a composition that read the pinned text are `stale`,
naming why, never `current`. A build that shows no such check (the zero-configuration view,
whose pin is the digest of the printed text) is read as before. The toy paper's test builds TeX;
the others build nothing."""

import json

import pytest

from conftest import build, edit, needs_tex
from prooflens import cli
from prooflens import config as cfgmod
from prooflens import dependencies as dp
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
REASON = ("the paper now prints other text than the pin of P:thm:main: its passage changed, and "
          "the inventory has not pinned it again")


def make_build(work, matches):
    """One claim, pinned at `s-main`, whose build's source check gives `matches`."""
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True, exist_ok=True)
    link = {"name": "Ex.main", "fingerprint": "fp-main",
            "statement": {"binders": [], "closure": [],
                          "conclusion": {"text": "P", "segments": [{"t": "P"}], "terms": [],
                                         "id": "/"}}}
    claims = [{"id": "P:thm:main", "paper": "P", "number": "Theorem 1", "kind": "theorem",
               "key": "thm:main", "source_sha256": "s-main", "source_matches": matches,
               "links": [link], "suggestions": [], "clauses": [], "decls": {}},
              {"id": "P:thm:other", "paper": "P", "number": "Theorem 2", "kind": "theorem",
               "key": "thm:other", "source_sha256": "s-other", "source_matches": True,
               "links": [], "suggestions": [], "clauses": [], "decls": {}}]
    for c in claims:
        (data / "claims" / f"{c['key'].replace(':', '_')}.json").write_text(json.dumps(c))
    (data / "index.json").write_text(json.dumps(
        {"schema": "prooflens/manifest@1", "release": "v-1",
         "project": {"name": "ex", "commit": "abc123"},
         "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123"}],
         "claims": [{"id": c["id"], "paper": "P", "number": c["number"], "kind": c["kind"],
                     "file": f"{c['key'].replace(':', '_')}.json"} for c in claims]}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": "Ex.main", "kind": "theorem", "module": "Ex.Basic"}]))
    return Snapshot(data)


def put(rec):
    return {"op": "put", "record": rec}


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    snap = make_build(w, True)
    p = wsp.open_for(w, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        put({"id": "q-1", "kind": "requirement", "claim": "P:thm:main", "local_id": "r1",
             "form": "statement", "text": "the theorem"}),
        put({"id": "p-1", "kind": "fragment", "claim": "P:thm:main", "requirement": "r1",
             "role": "statement", "passage": {"claim": "P:thm:main"}}),
        put({"id": "e-quote", "kind": "evidence", "claim": "P:thm:other", "role": "context",
             "ref": {"paper": {"claim": "P:thm:main", "quote": "Every solution"}}}),
        put({"id": "f-main", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
             "note": "Read against the paper."}),
        put({"id": "f-req", "kind": "finding", "claim": "P:thm:main", "requirement": "r1",
             "coverage": "full", "note": "The statement."}),
        put({"id": "f-quote", "kind": "finding", "claim": "P:thm:other", "coverage": "partial",
             "evidence": ["e-quote"], "note": "Uses Theorem 1."}),
        put({"id": "f-other", "kind": "finding", "claim": "P:thm:other", "coverage": "full",
             "note": "Another claim."}),
        put({"id": "x-q", "kind": "question", "claim": "P:thm:main", "text": "Is n = 0 allowed?"}),
        put({"id": "e-main", "kind": "evidence", "claim": "P:thm:main", "role": "supports",
             "ref": {"decl": "Ex.main"}}),
        put({"id": "c-1", "kind": "composition", "claim": "P:thm:main", "steps": [
            {"id": "s1", "establishes": "the theorem", "uses": ["e-main"],
             "requirements": ["r1"]}]}),
    ], snap)
    wsp.update(p, [{"op": "submit", "id": f, "base_rev": 1}
                   for f in ("f-main", "f-req", "f-quote", "f-other")], snap)
    return w, p


def states(w, p):
    return {k: v for k, v in wsp.currency(wsp.read(p), Snapshot(w / "site" / "data")).items()}


def test_records_that_read_a_passage_the_paper_no_longer_prints_are_stale(work):
    w, p = work
    assert {k: v["state"] for k, v in states(w, p).items()} == {
        "q-1": "current", "p-1": "current", "e-quote": "current", "e-main": "current",
        "f-main": "current", "f-req": "current", "f-quote": "current", "f-other": "current",
        "x-q": "current", "c-1": "current"}
    # The text of Theorem 1 changes; the inventory keeps its pin, and the build's source check
    # fails.
    make_build(w, False)
    cur = states(w, p)
    assert {k: v["state"] for k, v in cur.items()} == {
        "q-1": "stale", "p-1": "stale", "e-quote": "stale", "e-main": "current",
        "f-main": "stale", "f-req": "stale", "f-quote": "stale", "f-other": "current",
        "x-q": "stale", "c-1": "stale"}
    for k in ("p-1", "e-quote", "f-main", "f-req", "f-quote", "x-q", "c-1"):
        assert REASON in {c.get("reason") for c in cur[k]["changes"]}, k
    # The pin itself did not change: each change says so.
    (ch,) = [c for c in cur["f-main"]["changes"] if c.get("claim")]
    assert ch["was"] == ch["now"] == "s-main"
    assert dp.change_text(ch) == REASON


def test_a_build_without_the_source_check_is_read_as_before(work):
    """The zero-configuration view pins the printed text itself and shows no source check: a
    passage there is current while its digest is the one recorded."""
    w, p = work
    make_build(w, None)
    assert states(w, p)["f-main"]["state"] == "current"


def test_workspace_show_names_the_reason(work, monkeypatch, capsys):
    w, p = work
    make_build(w, False)
    root = w.parent
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    monkeypatch.chdir(root)
    cli.main(["workspace", "show", "--id", wsp.read(p)["id"]])
    out = capsys.readouterr().out
    assert "f-main  submitted: coverage full  [stale]" in out
    assert f"changed: {REASON}" in out


@needs_tex
def test_toy_paper_text_changed_without_pinning_again(toy, capsys):
    """The reproduction of #433 on the toy paper, built without Lean: findings on a theorem
    (located by its environment) and on a display (located by line) are recorded and submitted;
    the text of both changes and the inventory is not pinned again; built again, `workspace
    show` reads both findings as stale, with the reason."""
    _, _, cfg = build(toy, skip_lean=True)
    data = cfg.out_dir / "site" / "data"
    snap = Snapshot(data)
    p = wsp.open_for(cfg.out_dir, WHO, "informed", sources=snap.sources())
    wsp.update(p, [put({"id": "f-thm", "kind": "finding", "claim": "T:thm:bound",
                        "coverage": "full", "note": "n"}),
                   put({"id": "f-eq", "kind": "finding", "claim": "T:eq:bound-range",
                        "coverage": "full", "note": "n"})], snap)
    wsp.update(p, [{"op": "submit", "id": f, "base_rev": 1} for f in ("f-thm", "f-eq")], snap)
    tex = toy / "paper" / "toy.tex"
    edit(tex, "such that $T_n \\le C n^2$ for every", "such that $T_n \\le C n^2 + 1$ for every")
    edit(tex, "  n \\le k\\,n^2,", "  n \\le k\\,n^3,")
    build(toy, skip_lean=True)
    later = Snapshot(data)
    for cid in ("T:thm:bound", "T:eq:bound-range"):
        ch = later.chunk(cid)
        assert ch["source_sha256"] == snap.chunk(cid)["source_sha256"]
        assert ch["source_matches"] is False
    cur = wsp.currency(wsp.read(p), later)
    assert (cur["f-thm"]["state"], cur["f-eq"]["state"]) == ("stale", "stale")
    capsys.readouterr()
    cli.main(["workspace", "show", "-c", str(cfgmod.load(toy / "machinechecked.toml").path),
              "--id", wsp.read(p)["id"]])
    out = capsys.readouterr().out
    assert "changed: the paper now prints other text than the pin of T:thm:bound" in out
    assert "changed: the paper now prints other text than the pin of T:eq:bound-range" in out
