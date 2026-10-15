"""The toy paper builds to exactly the statuses its inventory and reviews determine."""

import json

from conftest import ROOT, build, findings, needs_lean, needs_tex, status
from prooflens import manifest as mf
from prooflens.schemas import validate

EXPECTED = {
    "T:def:even": "definition: author-reviewed",
    "T:thm:even-add": "formal: accepted",
    "T:thm:triangle": "formal: proved, author-reviewed",
    "T:prop:pred": "refuted as printed; corrected statement proved",
    "T:rem:pred": "out of scope: part-of",
    "T:thm:bound": "formal: proved, review pending",
    "T:cor:even-triangle": "formal: open",
    "T:rem:history": "out of scope: literature",
}


@needs_lean
@needs_tex
def test_statuses_findings_and_schemas(toy):
    index, body, cfg = build(toy)
    assert {c["id"]: c["status"] for c in index["claims"]} == EXPECTED
    assert [f for f in findings(body) if f["tier"] == "violation"] == []
    # The only warning left is the truncated subtraction of the printed (false) claim; the one of
    # the corrected statement is dismissed with a rationale.
    warns = [f for f in findings(body, "totalised")]
    assert {(f["subject"], bool(f.get("dismissed"))) for f in warns} == {
        ("T:prop:pred#0", False), ("T:prop:pred#1", True)}
    validate(json.loads((cfg.out_dir / "evidence" / f"{index['evidence']}.json").read_text()),
             "evidence")
    validate(index, "manifest-index")
    for c in index["claims"]:
        validate(json.loads((cfg.out_dir / "site" / "data" / "claims" / c["file"]).read_text()),
                 "manifest-claim")


@needs_lean
@needs_tex
def test_statement_inspection(toy):
    index, body, _ = build(toy)
    spec = body["lean"]["specs"]["Toy.PaperSpec.thm_bound"]
    # The quantifier prefix is read in order: one constant for every n.
    assert [(b["role"], b["name"]) for b in spec["binders"]] == [("exists", "C"), ("forall", "n")]
    assert spec["conclusion"]["text"] == "Toy.triangle n ≤ C * (n * n)"
    add = body["lean"]["specs"]["Toy.PaperSpec.thm_even_add"]
    assert [b["role"] for b in add["binders"]] == ["forall", "forall", "hypothesis", "hypothesis"]
    assert [b["name"] for b in add["binders"]][2:] == ["h1", "h2"]
    assert add["closure"] == ["Toy.IsEven"]


@needs_lean
@needs_tex
def test_hashes(toy):
    _, body, _ = build(toy)
    spec = body["lean"]["specs"]["Toy.PaperSpec.thm_triangle"]
    # The first half of the legacy hash is the hash of the type `Prop`, shared by every closed
    # proposition.
    assert spec["legacy_hash"].startswith("ed839d34f480cba1")
    assert spec["fingerprint"].startswith("pl-fp-v1:") and len(spec["fingerprint"]) == 9 + 64


@needs_lean
@needs_tex
def test_build_is_reproducible(toy):
    i1, _, _ = build(toy)
    i2, _, _ = build(toy)
    assert i1["evidence"] == i2["evidence"]


@needs_lean
@needs_tex
def test_anchors_locate_every_numbered_claim(toy):
    index, body, _ = build(toy)
    anchors = body["tex"]["T"]["anchors"]
    assert [(a["env"], a["number"], a["label"]) for a in anchors] == [
        ("definition", "1.1", "def:even"), ("theorem", "2.1", "thm:even-add"),
        ("theorem", "2.2", "thm:triangle"), ("proposition", "2.3", "prop:pred"),
        ("remark", "2.4", "rem:pred"), ("theorem", "2.5", "thm:bound"),
        ("corollary", "2.6", "cor:even-triangle"), ("remark", "3.1", "rem:history")]
    for a in anchors:
        assert a["begin"][0] == 1 and a["head"][2] > a["begin"][2] - 1
    assert all(c["anchor"] for c in index["claims"])


def test_status_classes_are_total():
    for s in ["formal: accepted", "formal: proved, author-reviewed", "formal: open",
              "refuted as printed; other clauses open", "definition: review pending",
              "out of scope: literature", "formal: unspecified", "formal: malformed"]:
        assert mf.status_class(s) in {"accepted", "proved", "refuted", "open", "malformed",
                                      "out-of-scope", "unspecified"}


@needs_lean
@needs_tex
def test_replay_is_not_run_without_a_log_and_blockers_explain(toy):
    import json
    index, body, cfg = build(toy)
    acc = next(c for c in index["claims"] if c["id"] == "T:thm:even-add")
    chunk = json.loads((cfg.out_dir / "site" / "data" / "claims" / acc["file"]).read_text())
    rungs = {r["rung"]: r["state"] for r in chunk["clauses"][0]["ladder"]}
    assert rungs["exact statement"] == "pass" and rungs["axioms"] == "pass"
    assert rungs["kernel replay"] == "not-run"
    # Accepted, but the release still lacks an independent replay: that is its only blocker.
    assert chunk["status"] == "formal: accepted"
    assert chunk["blockers"] == ["no independent kernel replay: no Comparator log for this release"]
    bound = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:bound")
    assert "the proposition has no review" in bound["blockers"]
    assert next(c for c in body["assessment"]["claims"] if c["id"] == "T:rem:history")["blockers"] == []


@needs_lean
@needs_tex
def test_declaration_store_is_content_addressed_and_complete(toy, tmp_path):
    import json
    from prooflens import config as cfgmod
    from prooflens.export import export
    from prooflens.manifest import record_key
    index, body, cfg = build(toy)
    export(cfg, tmp_path / "public")
    for site in (cfg.out_dir / "site", tmp_path / "public"):
        data = site / "data"
        idx = json.loads((data / "index.json").read_text())
        seen = 0
        for c in idx["claims"]:
            chunk = json.loads((data / "claims" / c["file"]).read_text())
            for name, key in chunk["decls"].items():
                rec = json.loads((data / "decls" / f"{key}.json").read_text())
                assert rec["name"] == name and record_key(rec) == key
                seen += 1
            names = set()
            for cl in chunk["clauses"]:
                names |= set(((cl.get("statement") or {}).get("closure")) or [])
                names |= set(cl.get("defs") or [])
            assert names <= set(chunk["decls"])
        assert seen


@needs_lean
@needs_tex
def test_bundle_is_one_self_contained_file(toy, tmp_path):
    import json
    import re
    from prooflens.bundle import bundle
    _, _, cfg = build(toy, web_dist=ROOT / "web" / "dist")
    if not (cfg.out_dir / "site" / "index.html").exists():
        import pytest
        pytest.skip("web app not built")
    res = bundle(cfg.out_dir / "site", tmp_path / "b.html")
    html = (tmp_path / "b.html").read_text()
    assert res["pdfs"] == 1 and res["files"] > 10
    assert not re.search(r'(src|href)="\./assets/', html)  # nothing left to fetch
    data = json.loads(re.search(r"window.__PROOFLENS__ = (.*?);</script>", html).group(1)
                      .replace("<\\/", "</"))
    assert "data/index.json" in data
