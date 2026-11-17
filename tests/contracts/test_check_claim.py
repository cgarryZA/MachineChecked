"""`check --claim`, `--changed` and `--json-out`, and the stored assessment `check` reports when
nothing it reads has changed."""

import json
import subprocess
import sys

from conftest import build, needs_lean, needs_tex

from prooflens import config as cfgmod
from prooflens import evidence as ev
from prooflens.assess import Assessor
from prooflens.pipeline import check_inputs_digest


def _check(root, *args):
    return subprocess.run([sys.executable, "-m", "prooflens.cli", "check", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8")


def test_the_inputs_digest_follows_what_the_assessment_reads(toy):
    """A review file, the dismissals, the inventory, the paper and a Lean source change the
    digest; a file the assessment does not read leaves it as it was."""
    cfg = cfgmod.load(toy / "machinechecked.toml")
    first = check_inputs_digest(cfg)
    assert first and first == check_inputs_digest(cfg)
    (toy / "NOTES.txt").write_text("not an input\n")
    assert check_inputs_digest(cfg) == first
    seen = {first}
    for path in ("reviews/T.md", "reviews/dismissals.json", "claims.json", "paper/toy.tex",
                 "lean/Toy/PaperSpec.lean"):
        f = toy / path
        f.write_bytes(f.read_bytes() + b"\n")
        d = check_inputs_digest(cfg)
        assert d not in seen, path
        seen.add(d)


@needs_lean
@needs_tex
def test_each_clause_has_its_own_blockers(toy):
    """A clause's own blockers are the claim's blockers for that clause alone: for a claim of
    one clause they are the claim's (its scope's reason apart)."""
    _, body, cfg = build(toy)
    judge = Assessor(cfg, body["inventory"], body["lean"], body["tex"], [], [])
    inv = {c["id"]: c for c in body["inventory"]["claims"]}
    for c in body["assessment"]["claims"]:
        own = judge.clause_blockers(inv[c["id"]], c["clauses"])
        assert len(own) == len(c["clauses"])
        if len(c["clauses"]) == 1:
            assert own[0] == c["blockers"], c["id"]
    pred = next(c for c in body["assessment"]["claims"] if c["id"] == "T:prop:pred")
    printed, corrected = judge.clause_blockers(inv["T:prop:pred"], pred["clauses"])
    assert any("printed statement is false" in b for b in printed)
    assert not any("printed statement is false" in b for b in corrected)


@needs_lean
@needs_tex
def test_check_claim_reuses_an_unchanged_release(toy, tmp_path):
    """`check --claim` prints the claim's passage, clauses and findings with the statuses the
    assessment stored, and `--json-out` writes the same run's document. A second check with
    nothing changed reports the stored release without assessing again; a changed dismissal
    is assessed again, and `--changed` shows the claim it changed."""
    out = tmp_path / "pred.json"
    r = _check(toy, "--claim", "prop:pred", "--json-out", str(out))
    assert r.returncode == 0, r.stderr
    assert "reporting its stored assessment" not in r.stdout
    assert "T:prop:pred  Proposition 2.3" in r.stdout
    assert "clause “as printed”: refuted" in r.stdout
    assert "passage: toy.tex, line" in r.stdout
    assert "Theorem 2.1" not in r.stdout
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["schema"] == "machinechecked/check@1" and d["selected"] == ["T:prop:pred"]
    assert d["reused"] is False
    (c,) = d["claims"]
    cfg = cfgmod.load(toy / "machinechecked.toml")
    stored = next(x for x in ev.load(cfg.out_dir, ev.latest(cfg.out_dir)["evidence"])
                  ["body"]["assessment"]["claims"] if x["id"] == "T:prop:pred")
    assert c["status"] == stored["status"] and c["blockers"] == stored["blockers"]
    assert [cl["state"] for cl in c["clauses"]] == [cl["state"] for cl in stored["clauses"]]
    printed, corrected = c["clauses"]
    assert printed["refutation"] == "Toy.Acceptance.prop_pred" and printed["blocked_by"]
    assert corrected["corrects"] == "as printed" and corrected["witness"]
    assert {f["subject"].split("#")[0] for f in c["findings"]} == {"T:prop:pred"}
    assert {f["id"] for f in d["finding_details"]} == {f["id"] for f in c["findings"]}
    assert "spec:Toy.PaperSpec.prop_pred" in {u["id"] for u in c["review_units"]}

    again = _check(toy, "--json", "--claim", "Proposition 2.3")
    assert again.returncode == 0, again.stderr
    assert "reporting its stored assessment" in again.stderr
    d2 = json.loads(again.stdout)
    assert d2["reused"] is True and d2["release"] == d["release"]
    assert d2["claims"] == d["claims"]

    (toy / "reviews" / "dismissals.json").write_text("[]\n")
    changed = _check(toy, "--changed")
    assert changed.returncode == 0, changed.stderr
    assert "reporting its stored assessment" not in changed.stdout
    assert "T:prop:pred  Proposition 2.3" in changed.stdout
    assert "was: refuted as printed; corrected statement proved" in changed.stdout
    assert "Theorem 2.5" not in changed.stdout

    missing = _check(toy, "--claim", "no-such-claim")
    assert missing.returncode == 2 and "no claim" in missing.stderr
