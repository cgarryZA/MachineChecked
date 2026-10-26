"""Declarations the probe cannot find: each becomes a violation naming it, and the build completes."""

import json
import subprocess
import sys

from conftest import build, edit, findings, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens.promote import latest_record

L = "lean/Toy/"


@needs_lean
@needs_tex
def test_a_module_left_out_of_modules(toy):
    # Toy.Acceptance holds every proof and witness; without it the probe finds none of them.
    edit(toy / "machinechecked.toml", 'modules = ["Toy"]', 'modules = ["Toy.Defs", "Toy.PaperSpec"]')
    index, body, _ = build(toy)
    before = {c["id"]: c["status_code"] for c in index["claims"]}
    for cid, code in before.items():
        assert not code.startswith(("formal.accepted", "formal.author", "formal.review",
                                    "formal.refuted")), (cid, code)
    assert status(index, "T:thm:triangle") == "formal: open"
    f = findings(body, "accept-missing", "T:thm:triangle")
    assert f and f[0]["tier"] == "violation"
    assert f[0]["message"] == ("Toy.Acceptance.thm_triangle: not found by the probe; it is "
                               "declared in Toy.Acceptance, which is not listed in `modules` "
                               "(`machinechecked check --fix-modules` lists it)")
    w = findings(body, "witness-missing", "T:thm:even-add")
    assert w and "Toy.Acceptance.thm_even_add_hypotheses" in w[0]["message"]
    r = findings(body, "regime", "T:thm:even-add")
    assert r and "Toy.Acceptance.thm_even_add_hypotheses: not found" in r[0]["message"]
    assert not index["gates"]["T"]["consistency"]["pass"]


@needs_lean
@needs_tex
def test_a_proposition_in_a_module_the_probe_does_not_load(toy):
    # A new statement file that the listed modules do not import.
    (toy / L / "PaperSpec").mkdir()
    (toy / L / "PaperSpec" / "Extra.lean").write_text(
        "namespace Toy.PaperSpec\n\ndef extra_bound : Prop := ∀ n : Nat, n ≤ n * n + 1\n\n"
        "end Toy.PaperSpec\n")
    inv = json.loads((toy / "claims.json").read_text())
    claim = next(c for c in inv["claims"] if c["id"] == "T:thm:triangle")
    claim["clauses"].append({"name": "extra", "spec": "Toy.PaperSpec.extra_bound",
                             "accept": "Toy.Acceptance.extra_bound",
                             "witness": "Toy.Acceptance.extra_bound_hypotheses"})
    (toy / "claims.json").write_text(json.dumps(inv))
    edit(toy / "claims.json", '"Toy.IsEven"', '"Toy.IsEven", "Toy.no_such_definition"')
    index, body, cfg = build(toy)

    # A clause the probe cannot see is open, so the claim is open.
    assert status(index, "T:thm:triangle") == "formal: open"
    f = findings(body, "spec-missing", "T:thm:triangle")
    assert [x["message"] for x in f] == [
        "proposition Toy.PaperSpec.extra_bound: not found by the probe; it is declared in "
        "Toy.PaperSpec.Extra, which is not listed in `modules` (`machinechecked check "
        "--fix-modules` lists it)"]
    assert body["assessment"]["unlisted_modules"] == {
        "Toy.PaperSpec.extra_bound": ["Toy.PaperSpec.Extra"]}
    a = findings(body, "accept-missing", "T:thm:triangle")
    assert [x["message"] for x in a] == [
        "Toy.Acceptance.extra_bound: not found by the probe; is its module listed in `modules`?"]
    assert findings(body, "witness-missing", "T:thm:triangle")
    d = findings(body, "def-missing", "T:def:even")
    assert d and "Toy.no_such_definition: not found by the probe" in d[0]["message"]
    assert next(c["status_code"] for c in index["claims"]
                if c["id"] == "T:def:even") == "definition.review-pending"

    clause = next(c for c in body["assessment"]["claims"]
                  if c["id"] == "T:thm:triangle")["clauses"][-1]
    assert clause["state"] == "open" and clause["review"] == "pending"
    assert clause["def_reviews"] == {}
    # There is no statement to show or to review.
    ch = next(json.loads(p.read_text()) for p in (cfg.out_dir / "site/data/claims").glob("*.json")
              if json.loads(p.read_text())["id"] == "T:thm:triangle")
    assert ch["clauses"][-1]["statement"] is None
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    assert "spec:Toy.PaperSpec.extra_bound" not in {u["id"] for u in q["units"]}

    # `check` reports the violations and exits 1, the documented status for violations.
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check"], cwd=toy,
                       capture_output=True, text=True)
    assert r.returncode == 1, r.stderr
    assert "Toy.PaperSpec.extra_bound: not found by the probe" in r.stdout
    assert "Traceback" not in r.stderr


@needs_lean
@needs_tex
def test_check_fix_modules_lists_the_modules_a_clause_needs(toy):
    # New files of statements and proofs that the listed modules do not import, and a
    # definition that two unlisted modules declare.
    (toy / L / "PaperSpec").mkdir()
    (toy / L / "PaperSpec" / "Extra.lean").write_text(
        "namespace Toy.PaperSpec\n\ndef extra_bound : Prop := ∀ n : Nat, n ≤ n * n + 1\n\n"
        "end Toy.PaperSpec\n")
    (toy / L / "Acceptance").mkdir()
    (toy / L / "Acceptance" / "Extra.lean").write_text(
        "import Toy.PaperSpec.Extra\n\nnamespace Toy.Acceptance\n\n"
        "theorem extra_bound : Toy.PaperSpec.extra_bound := by\n"
        "  intro n\n  have := Nat.le_mul_self n\n  omega\n\n"
        "/-- The proposition has no hypotheses; `n = 0` is an instance. -/\n"
        "theorem extra_bound_hypotheses : 0 ≤ 0 * 0 + 1 := by decide\n\n"
        "end Toy.Acceptance\n")
    (toy / L / "Scratch").mkdir()
    for f in ("One", "Two"):
        (toy / L / "Scratch" / f"{f}.lean").write_text(
            "namespace Toy\n\ndef twice (n : Nat) : Nat := 2 * n\n\nend Toy\n")
    inv = json.loads((toy / "claims.json").read_text())
    claim = next(c for c in inv["claims"] if c["id"] == "T:thm:triangle")
    claim["clauses"].append({"name": "extra", "spec": "Toy.PaperSpec.extra_bound",
                             "accept": "Toy.Acceptance.extra_bound",
                             "witness": "Toy.Acceptance.extra_bound_hypotheses"})
    (toy / "claims.json").write_text(json.dumps(inv))
    edit(toy / "claims.json", '"Toy.IsEven"', '"Toy.IsEven", "Toy.twice"')
    config = (toy / "machinechecked.toml").read_bytes()

    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--fix-modules"],
                       cwd=toy, capture_output=True, text=True)
    assert "Traceback" not in r.stderr
    # The two modules the violations name, after those listed; every other byte as it was.
    assert (toy / "machinechecked.toml").read_bytes() == config.replace(
        b'modules = ["Toy"]', b'modules = ["Toy", "Toy.Acceptance.Extra", "Toy.PaperSpec.Extra"]')
    assert ("--fix-modules: added to `modules` in machinechecked.toml:\n"
            "  Toy.Acceptance.Extra, which declares Toy.Acceptance.extra_bound, "
            "Toy.Acceptance.extra_bound_hypotheses\n"
            "  Toy.PaperSpec.Extra, which declares Toy.PaperSpec.extra_bound\n") in r.stdout
    ambiguous = ("Toy.twice is declared in Toy.Scratch.One and Toy.Scratch.Two, none of which "
                 "is listed in `modules`: list the one meant")
    assert f"--fix-modules: {ambiguous}" in r.stdout

    # The check that follows probes them: the new clause is proved and its witness checked. The
    # definition two modules declare is still a violation, so the check fails.
    assert r.returncode == 1, r.stderr
    report = r.stdout.split("--fix-modules: assessing again with them")[1]
    assert "not listed in `modules` (" not in report
    assert ("violation  T:def:even#0: definition Toy.twice: not found by the probe; it is "
            "declared in Toy.Scratch.One and Toy.Scratch.Two, none of which is listed in "
            "`modules`: list the one meant") in report
    body = latest_record(cfgmod.load(toy / "machinechecked.toml"))["body"]
    clause = next(c for c in body["assessment"]["claims"]
                  if c["id"] == "T:thm:triangle")["clauses"][-1]
    assert clause["state"] == "proved" and clause["checks"]["witness"]["ok"]
    assert body["assessment"]["unlisted_modules"] == {
        "Toy.twice": ["Toy.Scratch.One", "Toy.Scratch.Two"]}

    # Nothing left to add: the configuration stays as it is, and `--json` says so.
    fixed = (toy / "machinechecked.toml").read_bytes()
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json",
                        "--fix-modules"], cwd=toy, capture_output=True, text=True)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["modules_added"] == [] and (toy / "machinechecked.toml").read_bytes() == fixed
    assert "--fix-modules: nothing to add to `modules`" in r.stderr
    assert [f["code"] for f in out["finding_details"] if f["tier"] == "violation"] == [
        "def-missing"]
