"""A paper renumbered after its formalisation was written (#126, #127), on the synthetic project
tests/fixtures/renumbered: the Lean's docstrings and names follow the earlier numbering. The
stale references are reported with their sources, content search still finds each claim's
declaration, and nothing is linked and no status changes."""

import json
import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import compare as cmp
from prooflens.simple import build_view, write_view_site

SRC = ROOT / "tests" / "fixtures" / "renumbered"

# Each claim of the current version, and the declaration that states it.
EXPECTED = {"Definition 1.1": "Renum.triangle", "Theorem 2.1": "Renum.add_le_two_mul_max",
            "Lemma 2.2": "Renum.aux_one", "Theorem 3.1": "Renum.triangle_bound",
            "Lemma 3.2": "Renum.two_mul_triangle", "Proposition 3.3": "Renum.triangle_succ",
            "Corollary 3.4": "Renum.triangle_le_const"}


def project(tmp_path, toolchain=None):
    root = tmp_path / "renumbered"
    shutil.copytree(SRC, root, ignore=shutil.ignore_patterns(".lake", ".machinechecked"))
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


@needs_lean
@needs_tex
def test_stale_numbers_are_reported_and_content_finds_each_claim(tmp_path, capsys):
    root = project(tmp_path)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    body = view["body"]
    claims = {c["number"]: c for c in body["claims"]}
    assert set(claims) == set(EXPECTED)

    # Content search: the declaration stating each claim is among its suggestions.
    hits = {n: [s["name"] for s in c["suggestions"]] for n, c in claims.items()}
    ok = sum(EXPECTED[n] in hits[n][:3] for n in EXPECTED)
    with capsys.disabled():
        print(f"\nrenumbered paper: the stating declaration is suggested for {ok} of "
              f"{len(EXPECTED)} claims")
    assert ok == len(EXPECTED)
    # Theorem 3.1 was Theorem 2.1: its theorem is found by content, and the stale citation of
    # "Theorem 2.1" does not put it first for the new Theorem 2.1.
    assert hits["Theorem 3.1"][0] == "Renum.triangle_bound"
    assert hits["Theorem 2.1"][0] == "Renum.add_le_two_mul_max"
    cited = next(s for s in claims["Theorem 2.1"]["suggestions"]
                 if s["name"] == "Renum.triangle_bound")
    num = next(r for r in cited["reasons"] if r["signal"] == "number")
    assert num["basis"] == "a possibly stale lead" and "reads closer to Theorem 3.1" in num["text"]
    # The citation rests on the docstring's reference, which the numbering lists.
    stale = [o for o in body["numbering"]["references"] if o["id"] in num["references"]]
    assert [(o["source"]["declaration"], o["reference"], o["status"], o["stale_lead"])
            for o in stale] == [("Renum.triangle_bound", "Theorem 2.1", "exact", True)]
    # Corollary 3.4 reverses the quantifiers of Theorem 3.1: both are candidates, the
    # difference is said, and neither is linked.
    cor = {s["name"]: s for s in claims["Corollary 3.4"]["suggestions"]}
    assert "Renum.triangle_bound" in cor
    assert any(r["signal"] == "structure" for r in cor["Renum.triangle_bound"]["reasons"])

    # The references, each with its source and status.
    refs = {(o["source"].get("declaration") or o["source"]["module"], o["reference"]): o
            for o in body["numbering"]["references"]}
    st = {k: (o["status"], bool(o.get("stale_lead"))) for k, o in refs.items()}
    assert st[("Renum.triangle", "Definition 1.1")] == ("exact", False)
    assert st[("Renum.triangle_succ", "Lemma 3.3")] == ("other-kind", False)
    assert st[("Renum.two_mul_triangle", "Lemma 2.2")] == ("exact", True)
    assert st[("Renum.triangle_bound", "Theorem 2.1")] == ("exact", True)
    assert st[("Renum.triangle_le_const", "Corollary 2.4")] == ("absent", False)
    assert st[("Renum.lemma_2_5", "Lemma 2.5")] == ("absent", False)
    assert st[("Renum.gauss_sum", "Theorem 4.1")] == ("other-source", False)
    assert st[("Renum.Bounds", "Section 2")] == ("exact", False)
    # An author's possessive and a book's chapter before the number cite another work; the
    # paper's own possessive after an unrelated one is still checked (#287).
    assert st[("Renum.Bounds", "Lemma 4.22")] == ("other-source", False)
    assert st[("Renum.Bounds", "Proposition 4.7")] == ("other-source", False)
    assert st[("Renum.Bounds", "Lemma 2.6")] == ("absent", False)
    # A part of the paper after the number leaves the reference checked (#308).
    assert st[("Renum.Bounds", "Lemma 2.5")] == ("absent", False)
    # An ordinary word starting "ref" after the number cites no other work (#329).
    assert st[("Renum.Bounds", "Lemma 2.7")] == ("absent", False)
    # A capitalised term or a figure after the number names no other work (#349).
    assert st[("Renum.Bounds", "Lemma 2.8")] == st[("Renum.Bounds", "Lemma 2.9")] \
        == ("absent", False)
    # Source comments are read too, each on its declaration: one in a proof cites, one just
    # before a declaration names what it states.
    comments = [(o["source"]["declaration"], o["reference"], o["source"]["line"], o["role"],
                 o["status"]) for o in body["numbering"]["references"]
                if o["source"]["where"] == "comment"]
    assert comments == [
        ("Renum.triangle_le_sq", "Theorem 4.1", 25, "cited", "other-source"),
        ("Renum.triangle_le_sq", "Corollary 2.3", 25, "cited", "absent"),
        ("Renum.lemma_2_5", "Lemma 2.5", 48, "statement", "absent")]
    o = refs[("Renum.two_mul_triangle", "Lemma 2.2")]
    assert o["source"]["file"] == "Renum/Basic.lean" and o["source"]["line"] == 17
    assert o["content"]["closer"]["number"] == "Lemma 3.2"
    p = body["numbering"]["pattern"]
    assert p["drift"] and p["inventory"]["complete"]
    assert any("appear to follow another version" in n for n in body["notes"])

    # Nothing is linked, no links file is written, and the statuses are those of unlinked
    # claims with or without suggestions.
    assert not (root / "machinechecked.links.json").exists()
    assert all(c["links"] == [] for c in body["claims"])
    assert {c["status_code"] for c in body["claims"]} == {"link.suggested"}

    # The reader's data and `compare` carry the same reference basis and search.
    write_view_site(view, root / ".machinechecked" / "site", None, root)
    data = root / ".machinechecked" / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    assert index["retrieval"] == "data/retrieval.json" and index["numbering"]["drift"]
    chunk = json.loads((data / "claims" / next(c["file"] for c in index["claims"]
                                                if c["number"] == "Theorem 2.1")).read_text())
    sug = next(s for s in chunk["suggestions"] if s["name"] == "Renum.triangle_bound")
    assert sug["reasons"] == cited["reasons"]
    assert any(r["id"] == refs[("Renum.triangle_bound", "Theorem 2.1")]["id"]
               for r in chunk["references"])
    site = cmp.Site(data)
    pk = cmp.claim_packet(site, "Theorem 2.1", "compare")
    assert [c["name"] for c in pk["lean"]["candidates"]] == hits["Theorem 2.1"]
    assert pk["lean"]["numbering"]["drift"]
    found = cmp.query(site, "search", "Theorem 3.1")
    assert found["results"][0]["name"] == "Renum.triangle_bound"
    assert found["scope"]["declarations"] == len(body["index"])


@needs_lean
@needs_tex
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_the_index_holds_complete_statements_and_uses(tmp_path, toolchain):
    root = project(tmp_path, toolchain)
    view = build_view(root, root / "paper/main.tex", root / ".machinechecked", log=lambda m: None)
    # The view keeps previews; the content index holds the complete records from the store.
    idx = {d["name"]: d for d in view["retrieval"].docs}
    assert "Renum.triangle" in idx["Renum.triangle_bound"]["uses"]
    assert "Renum.triangle_le_sq" in idx["Renum.triangle_bound"]["value_uses"]
    assert "Renum.two_mul_triangle" in idx["Renum.gauss_sum"]["value_uses"]
    assert "Renum.triangle_bound" not in idx["Renum.triangle_bound"]["value_uses"]
    assert idx["Renum.triangle_bound"]["type"].startswith("∃ C, ∀ (n : Nat)")


@needs_lean
@needs_tex
def test_check_reports_the_references(tmp_path):
    root = project(tmp_path)
    r = subprocess.run(["python3", "-m", "prooflens", "check", "--json"], cwd=root,
                       capture_output=True, text=True, timeout=900)
    out = json.loads(r.stdout)
    warn = [w for w in out["warnings"] if w["kind"] == "paper-reference"]
    assert {(w["reference"], w["status"]) for w in warn} >= {
        ("Lemma 3.3", "other-kind"), ("Corollary 2.4", "absent"), ("Lemma 2.2", "exact"),
        ("Theorem 2.1", "exact")}
    assert all(w["file"] and w["line"] for w in warn)
    assert out["numbering"]["pattern"]["drift"]
    assert all(c["links"] == [] for c in out["claims"])
    text = subprocess.run(["python3", "-m", "prooflens", "check"], cwd=root,
                          capture_output=True, text=True, timeout=900).stdout
    assert "warning: the docstring of Renum.triangle_succ (Renum/Basic.lean:14) cites Lemma " \
           "3.3: the paper's 3.3 is Proposition 3.3, not a lemma" in text
