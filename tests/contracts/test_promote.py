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
# lowercase hexadecimal hash and a single `by=` attribute.
CHECKER = re.compile(r"<!--\s*(spec|def)-review:\s*(\S+)\s+([0-9a-f]{32})\s+by=(\S+)\s*-->")


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
                 "fingerprints": None},
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
    }
    for k, r in bad.items():
        (_, _, why), = pr.plan(cfg, [r])
        assert why, k
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
    found = {m.group(2): (m.group(3), m.group(4)) for m in CHECKER.finditer(text)
             if m.group(4) == "human:Test-Referee"}
    assert set(found) == set(names)
    for r in good:
        assert found[r["unit"]["name"]][0] == r["pins"]["legacy_hash"]
    # The report is kept beside the markers, in full and as the protocol's text block.
    reports = list((toy / "reviews/reports").glob("*.json"))
    assert len(reports) == 4 and len(list((toy / "reviews/reports").glob("*.md"))) == 4

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
