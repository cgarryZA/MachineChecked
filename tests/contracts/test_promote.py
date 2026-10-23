"""From a reviewer's report to a review marker, end to end: the queue's units, a report as the
reader exports it, promotion, the marker in the acceptance checker's exact form, the claim's new
status, and a changed definition reopening the review."""

import json
import re

import pytest

from conftest import build, edit, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens import promote as pr
from prooflens.pipeline import reassess

# The marker grammar of the acceptance checker the markers are written for: a 32-digit
# lowercase hexadecimal hash, a `by=` attribute and, when the review reads a claim's passage,
# the digests of the passages read.
CHECKER = re.compile(r"<!--\s*(spec|def)-review:\s*(\S+)\s+([0-9a-f]{32})\s+by=(\S+)"
                     r"((?:\s+source=[^\s@]+@[0-9a-f]{64})*)\s*-->")


def report(index, unit, reviewer=None, verdict="faithful", detail="", times=None):
    t = times or ["2026-01-01T10:00:00Z", "2026-01-01T10:05:00Z", "2026-01-01T10:05:00Z",
                  "2026-01-01T10:06:00Z"]
    rv = reviewer or {"id": "human:Test-Referee", "kind": "human", "name": "Test Referee",
                      "model": None, "same_family_as_author": "no", "identity": "self-declared"}
    revs = {p["id"]: p.get("revision") for p in index["papers"]}
    return {
        "schema": "prooflens/review-report@1",
        "unit": {"id": unit["id"], "kind": unit["kind"], "name": unit["name"],
                 "lean": [unit["name"]], "claims": [c["id"] for c in unit["claims"]],
                 "papers": unit["papers"]},
        "pins": {"release": index["release"], "project_commit": None,
                 "manuscripts": {p: revs.get(p) for p in unit["papers"]},
                 "legacy_hash": unit["legacy_hash"], "fingerprint": unit["fingerprint"],
                 "fingerprints": None, "source_sha256": unit.get("source_sha256")},
        "reviewer": rv,
        "reading": {"text": "My reading of the claim, written before seeing the Lean.",
                    "locked_at": t[0]},
        "comparison": {"text": "Item by item, it matches.", "witness": "", "decided_at": t[1]},
        "verdict": {"group": "matches", "value": verdict, "detail": detail},
        "author_review": {"shown_at": t[2], "disagreements": "none"},
        "submitted_at": t[3], "issue_draft": None}


def queue(cfg):
    return json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())


@needs_lean
@needs_tex
def test_promotion_end_to_end(toy, tmp_path):
    index, _, cfg = build(toy)
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"
    units = {u["name"]: u for u in queue(cfg)["units"]}
    names = ["Toy.PaperSpec.thm_triangle", "Toy.triangle", "Toy.triangle._f",
             "Toy.triangle.match_1"]
    good = [report(index, units[n]) for n in names]
    # A report may record the reviewer's coverage; the marker is the same with it or without.
    good[0]["correspondence"] = {"coverage": "full", "basis": "direct"}
    f = tmp_path / "reviews.json"
    f.write_text(json.dumps({"schema": "prooflens/review-reports@1", "reports": good}))

    # What promotion refuses.
    u = units["Toy.triangle"]
    bad = {
        "verdict": report(index, u, verdict="narrower", detail="adds a hypothesis"),
        "detail": report(index, u, verdict="broader"),
        "author": report(index, u, reviewer={"id": "statement-author", "kind": "model",
                                             "same_family_as_author": "yes"}),
        "family": report(index, u, reviewer={"id": "llm:some-model-2026-01-01", "kind": "model",
                                             "model": "some-model",
                                             "same_family_as_author": "unknown"}),
        "order": report(index, u, times=["2026-01-01T10:05:00Z", "2026-01-01T10:00:00Z",
                                         "2026-01-01T10:06:00Z", "2026-01-01T10:07:00Z"]),
        "stale": {**report(index, u), "pins": {**report(index, u)["pins"],
                                                "fingerprint": "pl-fp-v1:" + "0" * 64}},
        "revealed": {**report(index, u), "reading": {**report(index, u)["reading"],
                     "revealed_by": [{"unit": "spec:Toy.PaperSpec.thm_triangle", "what": "Lean"}]}},
        "text": {**report(index, u), "pins": {**report(index, u)["pins"],
                                               "source_sha256": {"T:def:even": "0" * 64}}},
        "no text": {**report(index, u), "pins": {**report(index, u)["pins"],
                                                  "source_sha256": None}},
        # An unresolved coverage is an open question, whatever the verdict says (#138).
        "open question": {**report(index, u, verdict="cannot determine", detail="Is T_0 = 0?"),
                          "correspondence": {"coverage": "unresolved"}},
        "unresolved": {**report(index, u), "correspondence": {"coverage": "unresolved"}},
        "coverage": {**report(index, u), "correspondence": {"coverage": "verified"}},
    }
    for k, r in bad.items():
        (_, _, why), = pr.plan(cfg, [r])
        assert why, k
    (_, _, why), = pr.plan(cfg, [bad["open question"]])
    assert why == ["verdict 'cannot determine' is not one that is recorded as a review: it "
                   "leaves an open question, and no defect"]
    (_, _, why), = pr.plan(cfg, [bad["unresolved"]])
    assert any("unresolved: an open question records no review, and no defect" in w for w in why)
    (_, _, why), = pr.plan(cfg, [bad["coverage"]])
    assert why == ["the report's coverage: coverage 'verified' is not one of: full, partial, "
                   "changed, related, unresolved"]
    (_, _, why), = pr.plan(cfg, [bad["text"]])
    assert why == ["the paper's text changed since the review (source digests differ)"]
    (_, _, why), = pr.plan(cfg, [bad["no text"]])
    assert len(why) == 1 and "does not record the paper text" in why[0]
    (_, _, why), = pr.plan(cfg, [bad["family"]], accept_same_family=True)
    assert not why
    (_, _, why), = pr.plan(cfg, [bad["revealed"]])
    assert any("not blind" in w for w in why)
    (_, _, why), = pr.plan(cfg, [bad["revealed"]], allow_revealed=True)
    assert not why

    # Promotion of the good reports writes markers the checker reads, at the current hashes.
    steps = pr.plan(cfg, pr.load_reports([f]))
    assert all(not why for _, _, why in steps)
    done = pr.apply(cfg, [(r, cur) for r, cur, _ in steps])
    assert len(done) == 4
    text = (toy / "reviews/T.md").read_text() + (toy / "reviews/definitions.md").read_text()
    found = {m.group(2): (m.group(3), m.group(4), m.group(5)) for m in CHECKER.finditer(text)
             if m.group(4) == "human:Test-Referee"}
    assert set(found) == set(names)
    for r in good:
        assert found[r["unit"]["name"]][0] == r["pins"]["legacy_hash"]
    # Each marker records the passage its review read: the proposition its theorem's, the
    # definition the definition claim's; the generated declarations no claim names, none.
    pins = {c["id"]: c["source_sha256"] for c in json.loads((toy / "claims.json").read_text())
            ["claims"]}
    assert found["Toy.PaperSpec.thm_triangle"][2] == \
        f" source=T:thm:triangle@{pins['T:thm:triangle']}"
    assert found["Toy.triangle"][2] == f" source=T:def:even@{pins['T:def:even']}"
    assert found["Toy.triangle._f"][2] == "" and found["Toy.triangle.match_1"][2] == ""
    # The report is kept beside the markers, in full and as the protocol's text block.
    reports = list((toy / "reviews/reports").glob("*.json"))
    assert len(reports) == 4 and len(list((toy / "reviews/reports").glob("*.md"))) == 4
    blocks = [p.read_text() for p in (toy / "reviews/reports").glob("*.md")]
    assert sum("Coverage (recorded with the verdict): every clause, in one Lean statement" in b
               for b in blocks) == 1
    assert sum("Coverage" in b for b in blocks) == 1

    res = reassess(cfg, log=lambda *a: None)
    assert status(res["index"], "T:thm:triangle") == "formal: accepted"

    # A change to a definition reopens its review, and the old report is refused.
    edit(toy / "lean/Toy/Defs.lean", "| n + 1 => triangle n + (n + 1)",
         "| n + 1 => (n + 1) + triangle n")
    index, _, cfg = build(toy)
    assert status(index, "T:thm:triangle") != "formal: accepted"
    q = {u["name"]: u for u in queue(cfg)["units"]}
    # (The recursion's body lives in the generated `Toy.triangle._f`, so that is what changed.)
    changed = [n for n in names if q[n]["state"] == "stale"]
    assert changed and all(q[n]["state"] == "reviewed" for n in names if n not in changed)
    for r in good:
        (_, _, why), = pr.plan(cfg, [r])
        assert any("changed" in w for w in why) == (r["unit"]["name"] in changed)


@needs_lean
@needs_tex
def test_a_unit_added_to_a_section_after_promotion_shows_the_section(toy, tmp_path):
    """#162: a section whose first unit was promoted, then given a second unit: the second
    unit's author review is the section's reading, not the reviewer's line promote wrote."""
    index, _, cfg = build(toy)
    units = {u["name"]: u for u in queue(cfg)["units"]}
    tri = "Toy.PaperSpec.thm_triangle"
    reading = units[tri]["author_review"][-1]["text"]
    assert reading.startswith("Manuscript:")
    steps = pr.plan(cfg, [report(index, units[tri])])
    assert all(not why for _, _, why in steps)
    pr.apply(cfg, [(r, cur) for r, cur, _ in steps])
    marker = next(m.group(0) for m in CHECKER.finditer((toy / "reviews/T.md").read_text())
                  if m.group(2) == tri and m.group(4) == "human:Test-Referee")
    h = units["Toy.PaperSpec.thm_bound"]["legacy_hash"]
    src = " ".join(f"source={c}@{d}"
                   for c, d in units["Toy.PaperSpec.thm_bound"]["source_sha256"].items())
    edit(toy / "reviews/T.md", marker,
         f"{marker}\n<!-- spec-review: Toy.PaperSpec.thm_bound {h} by=statement-author {src} -->")
    _, _, cfg = build(toy, reuse_lean=True)
    q = {u["name"]: u for u in queue(cfg)["units"]}
    assert q["Toy.PaperSpec.thm_bound"]["author_review"][-1]["text"] == reading
    assert q[tri]["author_review"][-1]["text"].startswith("Review by human:Test-Referee: faithful")


@needs_lean
@needs_tex
def test_promotion_needs_current_evidence(toy):
    index, _, cfg = build(toy)
    u = next(u for u in queue(cfg)["units"] if u["name"] == "Toy.triangle")
    edit(toy / "lean/Toy/Defs.lean", "/-!", "-- a comment\n/-!")
    with pytest.raises(pr.PromoteError, match="changed since the last build"):
        pr.plan(cfg, [report(index, u)])


@needs_lean
@needs_tex
def test_a_stale_inventory_is_refused_before_anything_is_written(toy, tmp_path, capsys):
    """#57: promotion checks the inventory with the Lean inputs, before writing a marker."""
    index, _, cfg = build(toy)
    units = {u["name"]: u for u in queue(cfg)["units"]}
    f = tmp_path / "reviews.json"
    f.write_text(json.dumps({"schema": "prooflens/review-reports@1",
                             "reports": [report(index, units["Toy.triangle"])]}))
    edit(toy / "claims.json", '"scope_note": ""', '"scope_note": "changed after the build"')
    before = (toy / "reviews/definitions.md").read_text()
    with pytest.raises(pr.PromoteError, match="machinechecked build --reuse-lean"):
        pr.plan(cfg, pr.load_reports([f]))
    from prooflens import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "promote", "--yes", "-c", str(toy / "machinechecked.toml"), str(f)])
    assert e.value.code == 2 and "Traceback" not in capsys.readouterr().err
    assert (toy / "reviews/definitions.md").read_text() == before
    assert not (toy / "reviews/reports").exists()
    # The command it names refreshes the evidence, and promotion then goes ahead.
    build(toy, reuse_lean=True)
    (_, _, why), = pr.plan(cfg, pr.load_reports([f]))
    assert not why


def test_a_directory_of_reports_stands_for_its_json_files(toy, tmp_path, capsys):
    """#103: a directory is read as the `*.json` files directly in it, in name order; a
    directory without any, a missing file or a file that is not JSON stops with one line."""
    d = tmp_path / "reports"
    (d / "nested").mkdir(parents=True)
    (d / "b.json").write_text(json.dumps({"schema": "prooflens/review-reports@1",
                                          "reports": [{"n": 2}, {"n": 3}]}))
    (d / "a.json").write_text(json.dumps({"n": 1}))
    (d / "notes.txt").write_text("not a report")
    (d / "nested" / "c.json").write_text(json.dumps({"n": 4}))
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps({"n": 0}))
    assert [r["n"] for r in pr.load_reports([extra, d])] == [0, 1, 2, 3]
    (tmp_path / "empty").mkdir()
    with pytest.raises(pr.PromoteError, match="no report files"):
        pr.load_reports([tmp_path / "empty"])
    with pytest.raises(pr.PromoteError, match="no such report file"):
        pr.load_reports([tmp_path / "missing.json"])
    with pytest.raises(pr.PromoteError, match="not a report file"):
        pr.load_reports([d / "notes.txt"])
    from prooflens import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "promote", "--yes", "-c", str(toy / "machinechecked.toml"),
                  str(tmp_path / "empty")])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "Traceback" not in err
    assert err.strip() == (f"machinechecked: {tmp_path / 'empty'} is a directory with no report "
                           "files (*.json) in it")
