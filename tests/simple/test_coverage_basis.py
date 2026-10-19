"""Coverage and its basis (#138), on the synthetic project tests/fixtures/coverage: a claim a
theorem states directly, one that follows by the auditor's composition, one stated by a theorem
whose type is exactly a target proposition (a checked bridge), and an unresolved reading. Each
reading reaches the passport and `check --json` unchanged, and none of them changes a status."""

import json
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import build_view, correspondence, save_link, write_view_site

SRC = ROOT / "tests" / "fixtures" / "coverage"
PAPER = "paper/main.tex"
ARGUMENT = "Apply Cover.even_add to a and b, to c and d, then to the two sums."
QUESTION = "Does 'number' mean a natural number or an integer?"


def readings(bridge: dict | None = None) -> dict:
    return {
        "thm:two": {"lean": ["Cover.even_add"], "coverage": "full", "basis": "direct",
                    "by": "A. Auditor"},
        "thm:four": {"lean": ["Cover.even_add"], "coverage": "full",
                     "basis": "reviewed_composition", "argument": ARGUMENT, "by": "A. Auditor"},
        "thm:three": {"lean": ["Cover.three_even"], "coverage": "full", "basis": "checked_bridge",
                      "bridge": {"theorem": "Cover.three_even",
                                 "target": "Cover.Spec.three_even", **(bridge or {})},
                      "by": "A. Auditor"},
        "thm:double": {"lean": ["Cover.even_two_mul"], "coverage": "unresolved",
                       "question": QUESTION, "would_decide": "The paper's standing conventions.",
                       "by": "A. Auditor"}}


def write_links(root, entries):
    (root / "machinechecked.links.json").write_text(json.dumps(
        {"version": 1, "papers": {PAPER: entries}}))


def view(root):
    v = build_view(root, root / PAPER, root / ".machinechecked", log=lambda m: None)
    return v, {c["key"]: c for c in v["body"]["claims"]}


def statuses(claims):
    return {k: (c["status_code"], [(l["name"], l["status_code"]) for l in c["links"]])
            for k, c in claims.items()}


@pytest.fixture
def cover(tmp_path):
    root = tmp_path / "coverage"
    shutil.copytree(SRC, root)
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


@needs_lean
@needs_tex
def test_three_bases_of_full_coverage_and_an_unresolved_question(cover):
    # The same links with no reading: the statuses the readings must leave alone.
    write_links(cover, {k: {"lean": e["lean"]} for k, e in readings().items()})
    _, plain = view(cover)
    write_links(cover, readings())
    _, first = view(cover)
    pins = first["thm:three"]["correspondence"]["bridge"]["current"]
    write_links(cover, readings({"target_fingerprint": pins["target_fingerprint"],
                                 "source_sha256": pins["source_sha256"]}))
    v, claims = view(cover)
    assert statuses(claims) == statuses(plain) == statuses(first)
    cor = {k: c["correspondence"] for k, c in claims.items()}

    # The same mathematical coverage, three distinguishable bases with their references.
    assert {k: (cor[k]["coverage"], cor[k]["basis"]) for k in ("thm:two", "thm:four",
                                                               "thm:three")} == {
        "thm:two": ("full", "direct"), "thm:four": ("full", "reviewed_composition"),
        "thm:three": ("full", "checked_bridge")}
    assert cor["thm:two"]["refs"] == ["Cover.even_add"] and cor["thm:two"]["argument"] is None
    assert cor["thm:four"]["refs"] == ["Cover.even_add"]
    assert (cor["thm:four"]["argument"], cor["thm:four"]["by"]) == (ARGUMENT, "A. Auditor")
    assert cor["thm:four"]["next_step"] == "State the combination as one Lean result."
    assert cor["thm:two"]["next_step"] is None and cor["thm:three"]["next_step"] is None
    assert cor["thm:four"]["bridge"] is None
    b = cor["thm:three"]["bridge"]
    assert cor["thm:three"]["refs"] == ["Cover.three_even"]
    assert (b["theorem"], b["target"], b["state"], b["reasons"]) == \
        ("Cover.three_even", "Cover.Spec.three_even", "checked", [])

    # An unresolved reading keeps its question; it is not a difference and has no basis.
    assert (cor["thm:double"]["coverage"], cor["thm:double"]["basis"]) == ("unresolved", None)
    assert cor["thm:double"]["question"] == QUESTION
    assert cor["thm:double"]["would_decide"] == "The paper's standing conventions."

    # The passport and `check --json` carry the same reading.
    write_view_site(v, cover / ".machinechecked" / "site", None, cover)
    chunks = {}
    for f in (cover / ".machinechecked" / "site" / "data" / "claims").glob("*.json"):
        d = json.loads(f.read_text())
        chunks[d["key"]] = d
    assert {k: chunks[k]["correspondence"] for k in cor} == cor
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=cover,
                       capture_output=True, text=True)
    out = {c["number"]: c["correspondence"] for c in json.loads(r.stdout)["claims"]}
    assert sorted(out.values(), key=json.dumps) == sorted(cor.values(), key=json.dumps)
    # The plain `check` names the composition and its next step, and only that one.
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check"], cwd=cover,
                       capture_output=True, text=True)
    lines = [l for l in r.stdout.splitlines() if l.startswith("composition ")]
    assert len(lines) == 1 and "Lean has not checked" in lines[0] \
        and lines[0].endswith("Next step: State the combination as one Lean result.")

    # A change to the paper's passage leaves the bridge checked but the reading out of date.
    tex = cover / PAPER
    tex.write_text(tex.read_text().replace("three even natural numbers",
                                           "three even numbers"))
    _, claims = view(cover)
    b = claims["thm:three"]["correspondence"]["bridge"]
    assert b["state"] == "stale"
    assert b["reasons"] == ["the paper's passage is not the version the auditor read"]

    # So does a change to the target.
    spec = cover / "Cover" / "Spec.lean"
    spec.write_text(spec.read_text()
                    .replace("Even c → Even (a + b + c)", "Even c → 0 ≤ a → Even (a + b + c)")
                    .replace("fun _ _ _ ha hb hc =>", "fun _ _ _ ha hb hc _ =>"))
    subprocess.run(["lake", "build"], cwd=cover, check=True, capture_output=True, timeout=900)
    _, claims = view(cover)
    b = claims["thm:three"]["correspondence"]["bridge"]
    assert b["state"] == "stale"
    assert "the target is not the version the auditor read" in b["reasons"]
    assert b["current"]["target_fingerprint"] != pins["target_fingerprint"]


@needs_lean
@needs_tex
def test_a_bridge_is_checked_only_against_the_target_its_type_is(cover):
    entries = readings()
    # A theorem whose type is not the target.
    entries["thm:three"] = {"lean": ["Cover.even_add"], "coverage": "full",
                            "basis": "checked_bridge",
                            "bridge": {"theorem": "Cover.even_add",
                                       "target": "Cover.Spec.three_even"}}
    # A bridge theorem the claim does not link.
    entries["thm:two"] = {"lean": ["Cover.even_add"], "coverage": "full",
                          "basis": "checked_bridge",
                          "bridge": {"theorem": "Cover.three_even",
                                     "target": "Cover.Spec.three_even"}}
    write_links(cover, entries)
    _, claims = view(cover)
    b = claims["thm:three"]["correspondence"]["bridge"]
    assert (b["state"], b["reasons"]) == ("unchecked", ["its type is not exactly the target"])
    b = claims["thm:two"]["correspondence"]["bridge"]
    assert (b["state"], b["reasons"]) == \
        ("unchecked", ["the bridge theorem is not one of the claim's linked declarations"])
    assert claims["thm:two"]["correspondence"]["refs"] == []


def test_unknown_values_and_an_unspecified_basis():
    claim = {"key": "thm:x", "source_sha256": "0" * 64}
    # A value outside the supported ones is no value: neither a category nor a basis.
    assert correspondence(claim, {"lean": ["A.b"], "coverage": "verified"}) is None
    # A stored `composed` reads as full coverage by the auditor's composition, its note as the
    # argument; a basis given beside it does not override that.
    c = correspondence(claim, {"lean": ["A.b"], "coverage": "composed", "basis": "direct",
                               "note": "Chain the two estimates."})
    assert (c["coverage"], c["basis"], c["argument"], c["note"], c["next_step"]) == (
        "full", "reviewed_composition", "Chain the two estimates.", "",
        "State the combination as one Lean result.")
    c = correspondence(claim, {"lean": ["A.b"], "coverage": "full", "basis": "checked"})
    assert (c["coverage"], c["basis"], c["refs"]) == ("full", None, [])
    # Existing readings stay readable, with the basis unspecified; a declaration list does not
    # become a composition.
    c = correspondence(claim, {"lean": ["A.b", "A.c"], "coverage": "partial", "note": "n"})
    assert (c["coverage"], c["basis"], c["argument"], c["bridge"]) == ("partial", None, None,
                                                                       None)
    # A basis needs a coverage it supports; an argument outside a composition is not shown.
    assert correspondence(claim, {"lean": ["A.b"], "basis": "direct", "note": "n"})["basis"] \
        is None
    assert correspondence(claim, {"lean": ["A.b"], "coverage": "full", "basis": "direct",
                                  "argument": "x"})["argument"] is None
    # References are among the linked declarations.
    c = correspondence(claim, {"lean": ["A.b", "A.c"], "coverage": "full",
                               "basis": "reviewed_composition", "refs": ["A.c", "Z.z"]})
    assert c["refs"] == ["A.c"]


def test_linking_other_declarations_retires_the_whole_reading(tmp_path):
    """Every field of the reading leaves the entry and is kept, with the list it described,
    under `earlier_notes`."""
    (tmp_path / "machinechecked.links.json").write_text(json.dumps(
        {"version": 1, "papers": {PAPER: readings()}}))
    save_link(tmp_path, PAPER, "thm:three", ["Cover.even_add"])
    entry = json.loads((tmp_path / "machinechecked.links.json").read_text())["papers"][PAPER][
        "thm:three"]
    assert set(entry) == {"lean", "at", "by", "earlier_notes"}
    old = readings()["thm:three"]
    assert entry["earlier_notes"] == [{"coverage": "full", "basis": "checked_bridge",
                                       "bridge": old["bridge"], "lean": old["lean"],
                                       "by": "A. Auditor"}]
