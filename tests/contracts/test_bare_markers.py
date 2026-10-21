"""#177: a review marker with no review text before it records no reading. It never counts as a
review, the assessment lists it with its file and line, and the claim reads review pending,
unless the configuration allows bare markers by that reviewer."""

from types import SimpleNamespace

from prooflens.assess import Assessor
from prooflens.reviews import parse_file

H_SPEC, H_DEF = "0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210"

# A synthetic review file whose markers were copied without the reviews they closed.
BARE = f"""## Foundations

<!-- spec-review: Foo.spec {H_SPEC} by=a-referee -->
<!-- def-review: Foo.Bar {H_DEF} by=a-referee -->
"""

READ = f"""## Foundations

`Foo.spec` states the printed bound with its hypotheses in order; `Foo.Bar` is the closure of
the span of the generators, as Definition 1 prints it.

<!-- spec-review: Foo.spec {H_SPEC} by=a-referee -->
<!-- def-review: Foo.Bar {H_DEF} by=a-referee -->
"""


def assess(tmp_path, text, **cfg):
    f = tmp_path / "reviews.md"
    f.write_text(text)
    reviews = parse_file(f, [], tmp_path)
    clause = {"name": "main", "spec": "Foo.spec", "accept": "Foo.accept"}
    inv = {"claims": [{"id": "P:a", "paper": "P", "scope": "formal", "scope_reviewed": True,
                       "clauses": [clause]}]}
    lean = {"specs": {"Foo.spec": {"legacy_hash": H_SPEC, "errors": [], "closure": ["Foo.Bar"],
                                   "binders": [], "consts": []}},
            "proofs": {"accept:Foo.accept:Foo.spec": {"errors": [], "sorry": False,
                                                      "axioms": []}},
            "decls": {"Foo.Bar": {"legacy_hash": H_DEF}}, "defs": {}, "layering": []}
    config = SimpleNamespace(statement_authors=[], papers=[], lean_root=None, **cfg)
    return Assessor(config, inv, lean, {}, reviews, []).run()


def test_a_marker_with_text_counts(tmp_path):
    out = assess(tmp_path, READ)
    assert out["claims"][0]["status_code"] == "formal.accepted"
    assert not [f for f in out["findings"] if f["code"] == "review-without-reading"]


def test_a_bare_marker_is_listed_and_does_not_count(tmp_path):
    out = assess(tmp_path, BARE)
    claim = out["claims"][0]
    assert claim["status_code"] == "formal.review-pending"
    clause = claim["clauses"][0]
    assert clause["spec_review"]["state"] == "stale"
    assert clause["spec_review"]["why"] == "no-reading"
    assert clause["spec_review"]["marker"] == {"file": "reviews.md", "line": 3}
    assert clause["def_reviews"]["Foo.Bar"]["why"] == "no-reading"
    assert "the proposition's review marker records no reading (no review text)" in \
        claim["blockers"]
    assert "1 definition its meaning depends on have a review marker that records no " \
        "reading" in claim["blockers"]
    listed = [f for f in out["findings"] if f["code"] == "review-without-reading"]
    assert [(f["subject"], f["file"], f["line"], f["tier"]) for f in listed] == [
        ("Foo.spec", "reviews.md", 3, "obligation"), ("Foo.Bar", "reviews.md", 4, "obligation")]
    assert "reviews.md:3" in next(f for f in out["findings"]
                                  if f["code"] == "spec-review")["message"]


def test_a_later_marker_with_text_replaces_a_bare_one(tmp_path):
    out = assess(tmp_path, BARE + "\n" + READ)
    assert out["claims"][0]["status_code"] == "formal.accepted"
    assert not [f for f in out["findings"] if f["code"] == "review-without-reading"]


def test_the_configuration_may_allow_bare_markers_by_a_named_reviewer(tmp_path):
    out = assess(tmp_path, BARE, bare_markers_by=["a-referee"])
    assert out["claims"][0]["status_code"] == "formal.accepted"
    assert not [f for f in out["findings"] if f["code"] == "review-without-reading"]
    out = assess(tmp_path, BARE, bare_markers_by=["someone-else"])
    assert out["claims"][0]["status_code"] == "formal.review-pending"
