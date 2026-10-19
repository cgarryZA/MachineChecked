"""Declarations the probe cannot find: each becomes a violation naming it, and the build completes."""

import json
import subprocess
import sys

from conftest import build, edit, findings, needs_lean, needs_tex, status

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
                               "declared in Toy.Acceptance, which is not listed in `modules`")
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
        "Toy.PaperSpec.Extra, which is not listed in `modules`"]
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
