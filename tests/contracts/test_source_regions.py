"""Source bounds, raw fingerprints and original-revision migration use synthetic manuscripts."""

from copy import deepcopy
import hashlib
import json

import pytest

from prooflens.source_regions import (
    SCHEME, RegionError, collect, extract, matches, migration_plan, write_plan,
)

REV = "a" * 40


def claim(**overrides):
    return {"id": "T:eq:sample", "paper": "T", "commit": REV,
            "location": "paper.tex:1", **overrides}


def paper(tmp_path, text):
    (tmp_path / "paper.tex").write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("env", ["equation", "align", "gather", "multline", "alignat", "flalign"])
@pytest.mark.parametrize("star", ["", "*"])
def test_complete_environment_and_edit_detection(tmp_path, env, star):
    env += star
    original = f"\\begin{{{env}}}\nx = 1\\label{{eq:sample}}\n\\end{{{env}}}\nNext claim.\n"
    root = paper(tmp_path, original)
    region = extract(root, claim())
    assert region.text == original.split("\nNext claim.")[0]
    assert region.end_line == 3 and region.kind == "environment"
    c = claim(source_hash_scheme=SCHEME, source_sha256=region.sha256)
    assert matches(c, {"regions": collect({"claims": [c]}, "T", root)})
    paper(tmp_path, original.replace("x = 1", "x = 2"))
    assert not matches(c, {"regions": collect({"claims": [c]}, "T", root)})


def test_comments_escaped_commands_and_nested_environment(tmp_path):
    text = (r"\begin{equation}" + "\n" + r"% \end{equation}" + "\n"
            + r"\begin{aligned} x&=1\\ y&=2\end{aligned}" + "\n"
            + r"\verb|\end{equation}|" + "\n"
            + r"\text{\% literal} \\end{equation}" + "\n" + r"\end{equation}")
    region = extract(paper(tmp_path, text), claim())
    assert region.text == text and region.end_line == 6


@pytest.mark.parametrize("text", [r"\begin{equation} x=1", r"\begin{equation} x=1\end{align}",
                                  r"\begin{align}\begin{aligned}x=1\end{align}",
                                  r"\begin{equation", r"\begin{custom}x\end{custom}",
                                  "", "% only a comment\n"])
def test_malformed_source_is_not_hashable(tmp_path, text):
    root = paper(tmp_path, text)
    with pytest.raises(RegionError):
        extract(root, claim())
    rec = collect({"claims": [claim()]}, "T", root)[claim()["id"]]
    assert rec.get("error") and "sha256" not in rec
    assert not matches(claim(source_sha256="f" * 64, source_hash_scheme=SCHEME),
                       {"regions": {claim()["id"]: rec}})


def test_explicit_prose_ends_mid_line_and_does_not_include_next_claim(tmp_path):
    root = paper(tmp_path, "Let x be positive.\nThen x+x is positive. Next claim.\n")
    c = claim(source_region={"end_line": 2, "end_column": 22})
    region = extract(root, c)
    assert region.text == "Let x be positive.\nThen x+x is positive."
    assert "Next" not in region.text


def test_distinct_spans_starting_on_same_line_do_not_collide(tmp_path):
    root = paper(tmp_path, "Alpha. Beta.\nGamma.\n")
    a = claim(id="T:first", source_region={"end_line": 1, "end_column": 7})
    b = claim(id="T:second", source_region={"end_line": 2})
    records = collect({"claims": [a, b]}, "T", root)
    assert records[a["id"]]["sha256"] != records[b["id"]]["sha256"]


@pytest.mark.parametrize("span", [{"end_line": 0}, {"end_line": 3}, {"end_line": True},
                                   {"end_line": 1, "start_column": 5, "end_column": 3},
                                   {"end_line": 1, "end_column": 100},
                                   {"end_line": 1, "unexpected": 1}, {}])
def test_invalid_explicit_bounds_fail_closed(tmp_path, span):
    with pytest.raises(RegionError):
        extract(paper(tmp_path, "Alpha.\nBeta.\n"), claim(source_region=span))


def test_newlines_are_not_collapsed_before_hashing(tmp_path):
    root = paper(tmp_path, "a% comment\nb\n")
    original = extract(root, claim(source_region={"end_line": 2}))
    paper(tmp_path, "a% comment b\n")
    changed = extract(root, claim())
    assert original.sha256 != changed.sha256


def test_whole_region_survives_relocation(tmp_path):
    text = "\\begin{gather}\nx=1\n\\end{gather}"
    root = paper(tmp_path, text)
    before = extract(root, claim())
    paper(tmp_path, "Intro.\n\n" + text)
    after = extract(root, claim(location="paper.tex:3"))
    assert before.sha256 == after.sha256
    assert after.start_line == 3


def test_path_traversal_and_symlink_escape(tmp_path):
    with pytest.raises(RegionError):
        extract(tmp_path, claim(location="../private.tex:1"))
    outside = tmp_path.parent / (tmp_path.name + "-outside.tex")
    outside.write_text("private", encoding="utf-8")
    (tmp_path / "paper.tex").symlink_to(outside)
    with pytest.raises(RegionError):
        extract(tmp_path, claim())


def inventory(root):
    paper(root, "\\begin{equation}\nx=1\n\\end{equation}\n")
    old = hashlib.sha256(r"\begin{equation}".encode()).hexdigest()
    return {"claims": [claim(source_sha256=old, scope="formal", clauses=[{"name": "main"}])],
            "note": "Synthetic inventory"}


def test_migration_uses_original_revision_and_changes_only_hash_fields(tmp_path):
    inv = inventory(tmp_path)
    before = deepcopy(inv)
    result, changes = migration_plan(inv, "T", tmp_path, REV)
    assert inv == before
    assert len(changes) == 1
    c = result["claims"][0]
    assert c["source_hash_scheme"] == SCHEME
    assert c["source_sha256"] == extract(tmp_path, c).sha256
    assert c["commit"] == REV and c["clauses"] == inv["claims"][0]["clauses"]
    again, changes = migration_plan(result, "T", tmp_path, REV)
    assert again == result and changes == []
    with pytest.raises(RegionError, match="original paper revision"):
        migration_plan(inv, "T", tmp_path, "b" * 40)


def test_migration_does_not_accept_missing_or_changed_legacy_baseline(tmp_path):
    inv = inventory(tmp_path)
    inv["claims"][0]["source_sha256"] = "f" * 64
    with pytest.raises(RegionError, match="legacy hash"):
        migration_plan(inv, "T", tmp_path, REV)
    del inv["claims"][0]["source_sha256"]
    with pytest.raises(RegionError, match="legacy hash"):
        migration_plan(inv, "T", tmp_path, REV)


def test_legacy_digest_alone_cannot_pass_new_scope_check(tmp_path):
    inv = inventory(tmp_path)
    c = inv["claims"][0]
    c["source_sha256"] = extract(tmp_path, c).sha256
    assert not matches(c, {"regions": collect(inv, "T", tmp_path)})


def test_atomic_write_rejects_changed_inventory(tmp_path):
    inv = inventory(tmp_path)
    path = tmp_path / "claims.json"
    before = json.dumps(inv).encode()
    path.write_bytes(before)
    result, _ = migration_plan(inv, "T", tmp_path, REV)
    path.write_text("Changed concurrently.")
    with pytest.raises(RegionError, match="inventory changed"):
        write_plan(path, before, result)
    assert path.read_text() == "Changed concurrently."
    assert not list(tmp_path.glob(".source-regions-*"))
    path.write_bytes(before)
    write_plan(path, before, result)
    assert json.loads(path.read_text()) == result
    assert not list(tmp_path.glob(".source-regions-*"))


def assessed(root, c, tex):
    from types import SimpleNamespace
    from prooflens.assess import Assessor
    from prooflens.reviews import Review
    fp = "synthetic-fingerprint"
    c = {"scope": "formal", "scope_reviewed": True,
         "clauses": [{"name": "main", "spec": "Synthetic.spec", "accept": "Synthetic.accept"}],
         **c}
    cfg = SimpleNamespace(statement_authors=[], papers=[SimpleNamespace(id="T")], lean_root=root)
    lean = {"specs": {"Synthetic.spec": {"fingerprint": fp, "errors": [], "closure": [],
                                      "binders": [], "consts": []}},
            "proofs": {"accept:Synthetic.accept:Synthetic.spec": {"errors": [], "sorry": False,
                                                                 "axioms": []}},
            "decls": {}, "defs": {}, "layering": []}
    reviews = [Review("spec", "Synthetic.spec", fp, "synthetic-reviewer", "human",
                      "self-declared", "reviews.md", 1, "Synthetic review.")]
    inv = {"claims": [c]}
    result = Assessor(cfg, inv, lean, {"T": tex}, reviews, [],
                      json.dumps({"commit": REV, "replayed": ["Synthetic.accept"]}), REV).run()
    return {"id": "synthetic-evidence", "created": "2026-01-01", "body": {
        "inventory": inv, "lean": lean, "tex": {"T": tex}, "assessment": result,
        "provenance": {"project": {"name": "Synthetic"}, "tool": {"name": "machinechecked"},
                       "papers": {"T": {"mode": "latex", "title": "Synthetic"}}}}}


def test_source_edit_fails_gates_and_reader_source_match_not_the_lean_proof(tmp_path):
    from prooflens.manifest import build
    inv = inventory(tmp_path)
    migrated, _ = migration_plan(inv, "T", tmp_path, REV)
    c = {**migrated["claims"][0], "clauses": [{"name": "main", "spec": "Synthetic.spec",
                                             "accept": "Synthetic.accept"}], "scope_reviewed": True}
    tex = {"mode": "latex", "envs": [], "anchors": [],
           "regions": collect({"claims": [c]}, "T", tmp_path),
           "manual_anchors": {c["id"]: {"page": 1, "y0": 100, "y1": 150}}}
    before = assessed(tmp_path, c, tex)
    assert before["body"]["assessment"]["gates"]["T"]["release"]["pass"]
    paper(tmp_path, "\\begin{equation}\nx=2\n\\end{equation}\n")
    tex["regions"] = collect({"claims": [c]}, "T", tmp_path)
    after = assessed(tmp_path, c, tex)
    a = after["body"]["assessment"]
    assert a["claims"][0]["status"] == "formal: accepted"
    assert not a["gates"]["T"]["consistency"]["pass"]
    assert not a["gates"]["T"]["release"]["pass"]
    assert any(f["code"] == "source-changed" for f in a["findings"])
    _, chunks, _ = build(after, "synthetic-release")
    shown = next(iter(chunks.values()))
    assert shown["source_matches"] is False
    assert next(r for r in shown["clauses"][0]["ladder"] if r["rung"] == "source")["state"] == "fail"
    assert "regions" not in shown


def test_old_line_evidence_fails_closed_with_actionable_message(tmp_path):
    inv = inventory(tmp_path)
    c = inv["claims"][0]
    result = assessed(tmp_path, c, {"mode": "latex", "envs": [], "anchors": [],
                                   "lines": {c["location"]: c["source_sha256"]}})
    findings = result["body"]["assessment"]["findings"]
    assert any(f["code"] == "source-hash-scheme" and "original" in f["message"] for f in findings)


def test_display_overlay_does_not_repin_source_evidence(tmp_path):
    from prooflens.manifest import build
    inv = inventory(tmp_path)
    c = inv["claims"][0]
    record = assessed(tmp_path, c, {"mode": "latex", "envs": [], "anchors": [], "regions": {}})
    before = deepcopy(record)
    _, chunks, _ = build(record, "synthetic", {"claims": {c["id"]: {"title_tex": "Pretty title"}}})
    assert record == before
    assert next(iter(chunks.values()))["source_matches"] is False
