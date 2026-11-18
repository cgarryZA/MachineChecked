"""#570: the source pin is what reopens a review when the paper's text changes. An inventory entry
of a paper read from its LaTeX source that has no pin (no `source_sha256`) is a violation naming
the claim, with the fields that pin its passage as the build's manuscript prints it, and no
review of its passage counts until it is pinned and read at the pin."""

import json
import subprocess
import sys
from types import SimpleNamespace

from conftest import needs_lean, needs_tex
from prooflens.assess import Assessor
from prooflens.probe import proof_key
from prooflens.reviews import Review

PIN, ENV, REGION = "a" * 64, "b" * 64, "c" * 64
SPECS = ("S.pinned", "S.env", "S.line", "S.legacy", "S.lost", "S.shared", "S.pdf")


def spec(name):
    return {"fingerprint": f"fp-{name}", "errors": [], "binders": [], "closure": [], "consts": []}


LEAN = {"specs": {n: spec(n) for n in SPECS},
        "decls": {n: {"name": n, "fingerprint": f"fp-{n}", "uses": []}
                  for n in (*SPECS, "D.x")},
        "proofs": {proof_key("accept", f"{n}_proof", n): {"errors": [], "sorry": False,
                                                           "axioms": []} for n in SPECS},
        "defs": {"D.x": {"closure": []}}, "layering": []}


def claim(cid, spec=None, paper="P", **extra):
    clauses = ([{"name": "statement", "spec": spec, "accept": spec + "_proof"}] if spec else
               [{"name": "definition", "spec": None, "defs": ["D.x"]}])
    return {"id": f"{paper}:{cid}", "paper": paper, "kind": "theorem" if spec else "definition",
            "number": cid, "label": cid, "location": "p.tex",
            "scope": "formal" if spec else "definition", "scope_reviewed": True,
            "clauses": clauses, **extra}


def anchor(label, sha, line):
    return {"id": f"a-{label}", "env": "theorem", "label": label, "number": label,
            "file": "p.tex", "line": line, "source_sha256": sha}


CLAIMS = [
    claim("pinned", "S.pinned", source_sha256=PIN),
    claim("env", "S.env"),
    # Located by line, with and without the region scheme, and no digest.
    claim("line", "S.line", location="p.tex:10", source_hash_scheme="tex-region-v1"),
    claim("legacy", "S.legacy", location="p.tex:20"),
    # Not found in the compiled paper: there is no digest to give.
    claim("lost", "S.lost"),
    claim("def"),
    # One proposition, stated by a pinned claim and by a claim with no pin.
    claim("shared-pinned", "S.shared", source_sha256=PIN),
    claim("shared-bare", "S.shared"),
    # A paper read only from its PDF has no source check.
    claim("pdf", "S.pdf", paper="Q"),
]
TEX = {"P": {"mode": "latex", "envs": ["theorem", "definition"],
             "anchors": [anchor("pinned", PIN, 1), anchor("env", ENV, 2), anchor("def", ENV, 3),
                         anchor("shared-pinned", PIN, 4), anchor("shared-bare", ENV, 5)],
             "regions": {cid: {"file": "p.tex", "start_line": line, "end_line": line,
                               "kind": "line", "scheme": "tex-region-v1", "sha256": REGION,
                               "line_sha256": [REGION]}
                         for cid, line in (("P:line", 10), ("P:legacy", 20))}},
       "Q": {"mode": "pdf", "anchors": [anchor("pdf", None, 1)]}}


def marker(target, name, line, source):
    return Review(target, name, f"fp-{name}", "reader", "human", "self-declared", "r.md", line,
                  "Read against the paper.", source=source)


# Each marker records the digest of every pinned passage it read; none can record a passage
# that has no pin.
REVIEWS = [marker("spec", "S.pinned", 1, {"P:pinned": PIN}),
           marker("spec", "S.shared", 2, {"P:shared-pinned": PIN})] + \
          [marker("spec", n, i, {}) for i, n in enumerate(SPECS[1:5] + ("S.pdf",), 3)] + \
          [marker("def", "D.x", 9, {})]


def assess(claims=CLAIMS, reviews=REVIEWS):
    cfg = SimpleNamespace(statement_authors=[], lean_root=None,
                          papers=[SimpleNamespace(id="P"), SimpleNamespace(id="Q")])
    return Assessor(cfg, {"claims": claims}, LEAN, TEX, reviews, []).run()


def test_an_entry_without_a_pin_is_a_violation_with_the_fields_that_pin_it():
    found = {f["subject"]: f for f in assess()["findings"] if f["code"] == "source-pin-missing"}
    assert sorted(found) == ["P:def", "P:env", "P:legacy", "P:line", "P:lost", "P:shared-bare"]
    assert {f["tier"] for f in found.values()} == {"violation"}
    assert found["P:env"]["fix"] == {"source_sha256": ENV}
    assert found["P:line"]["fix"] == found["P:legacy"]["fix"] == \
        {"source_hash_scheme": "tex-region-v1", "source_sha256": REGION}
    assert "fix" not in found["P:lost"]
    msg = found["P:env"]["message"]
    assert msg.startswith("env (P:env) has no source pin")
    assert f'"source_sha256": "{ENV}"' in msg and "record a reading at the pin" in msg
    assert "does not locate its passage" in found["P:lost"]["message"]


def test_it_replaces_the_scheme_and_change_findings_of_a_line_located_entry():
    codes = {(f["code"], f["subject"]) for f in assess()["findings"] if f["tier"] == "violation"}
    for cid in ("P:line", "P:legacy"):
        assert ("source-changed", cid) not in codes
        assert ("source-hash-scheme", cid) not in codes
    # An entry the compiled paper does not hold is still reported as such.
    assert ("inventory-unanchored", "P:lost") in codes


def test_no_review_of_its_passage_counts_until_it_is_pinned():
    got = {c["id"]: c for c in assess()["claims"]}
    assert got["P:pinned"]["status_code"] == "formal.accepted"
    for cid in ("P:env", "P:line", "P:legacy", "P:shared-bare"):
        c = got[cid]
        assert c["status_code"] == "formal.review-pending", cid
        sr = c["clauses"][0]["spec_review"]
        assert (sr["state"], sr["why"], sr["source_claim"]) == ("stale", "source-no-pin", cid)
        assert any("has no source pin" in b for b in c["blockers"]), c["blockers"]
    # The claim whose passage is pinned keeps its review of the proposition they share.
    assert got["P:shared-pinned"]["status_code"] == "formal.accepted"
    assert got["P:def"]["status_code"] == "definition.review-pending"
    assert got["P:def"]["clauses"][0]["def_reviews"]["D.x"]["why"] == "source-no-pin"
    # A paper read only from its PDF has no source check, as before.
    assert got["Q:pdf"]["status_code"] == "formal.accepted"
    obligations = {f["subject"]: f["message"] for f in assess()["findings"]
                   if f["code"] == "spec-review"}
    assert "env (P:env) has no source pin" in obligations["P:env#0"]


def test_pinned_with_the_fields_given_a_review_that_read_the_pin_counts_again():
    fix = next(f["fix"] for f in assess()["findings"]
               if f["code"] == "source-pin-missing" and f["subject"] == "P:env")
    claims = [{**c, **fix} if c["id"] == "P:env" else c for c in CLAIMS]
    reviews = [marker("spec", "S.env", 3, {"P:env": fix["source_sha256"]})
               if r.name == "S.env" else r for r in REVIEWS]
    out = assess(claims, reviews)
    assert next(c for c in out["claims"] if c["id"] == "P:env")["status_code"] == \
        "formal.accepted"
    assert not [f for f in out["findings"] if f["subject"] == "P:env"]
    # A marker that recorded no digest for it does not count once it is pinned either.
    out = assess(claims)
    assert next(c for c in out["claims"] if c["id"] == "P:env")["status_code"] == \
        "formal.review-pending"


@needs_lean
@needs_tex
def test_the_toy_paper_names_an_entry_whose_pin_was_removed(toy):
    """The issue's reproduction: delete the pin of Theorem 2.1, whose proposition an
    independent reviewer read."""
    path = toy / "claims.json"
    inv = json.loads(path.read_text())
    entry = next(c for c in inv["claims"] if c["id"] == "T:thm:even-add")
    pin = entry.pop("source_sha256")
    path.write_text(json.dumps(inv, indent=1))

    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=toy,
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 1, run.stderr
    out = json.loads(run.stdout)
    claim = next(c for c in out["claims"] if c["id"] == "T:thm:even-add")
    assert claim["status"] == "formal: proved, review pending"
    assert claim["semantic"]["review"] != "independent"
    found = [f for f in out["finding_details"] if f["code"] == "source-pin-missing"]
    assert [(f["tier"], f["subject"]) for f in found] == [("violation", "T:thm:even-add")]
    # The digest it gives is the pin that was removed: the manuscript is unchanged.
    assert found[0]["fix"] == {"source_sha256": pin}

    entry.update(found[0]["fix"])
    path.write_text(json.dumps(inv, indent=1))
    run = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=toy,
                         capture_output=True, text=True, encoding="utf-8")
    out = json.loads(run.stdout)
    assert next(c for c in out["claims"] if c["id"] == "T:thm:even-add")["status"] == \
        "formal: accepted"
    assert not [f for f in out["finding_details"] if f["code"] == "source-pin-missing"]
