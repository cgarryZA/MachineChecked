"""#288: a declaration's record is its last marker, reading the review files in order. When a
marker at the declaration's current hash read the current passage but a later marker at another
hash is the record, the review stays stale, and the review's `why`, the finding and the blocker
name both markers (file, line, hash, reviewer). The status is the one the engine computed
before: only the words change."""

from types import SimpleNamespace

from prooflens.assess import Assessor
from prooflens.reviews import Review, load_reviews

D = "d" * 64
# Legacy hashes of two versions of the proposition, which share their first 16 digits.
H1, H2 = "abcdef0123456789" + "1" * 16, "abcdef0123456789" + "2" * 16
HD = "pl-fp-v1:" + "7" * 64

# A synthetic proposition whose statement uses one definition, and the theorem that proves it.
LEAN = {
    "specs": {"Toy.spec_foo": {"fingerprint": H2, "errors": [], "binders": [],
                               "closure": ["Toy.bar"], "consts": []}},
    "proofs": {"accept:Toy.foo:Toy.spec_foo": {"errors": [], "sorry": False, "axioms": []}},
    "decls": {"Toy.spec_foo": {"name": "Toy.spec_foo", "fingerprint": H2, "uses": []},
              "Toy.bar": {"name": "Toy.bar", "fingerprint": HD, "uses": []}},
    "defs": {"Toy.bar": {"closure": []}},
    "layering": []}

CLAIM = {"id": "toy:foo", "paper": "toy", "number": "Theorem 1", "scope": "formal",
         "scope_reviewed": True, "source_sha256": D,
         "clauses": [{"name": "main", "spec": "Toy.spec_foo", "accept": "Toy.foo"}]}


def mark(name, h, file, line, target="spec", by="alice", source=None):
    return Review(target, name, h, by, "human", "self-declared", file, line,
                  "Read against the paper.", source={"toy:foo": D} if source is None else source)


DEF = mark("Toy.bar", HD, "reviews/a.md", 9, "def")


def run(reviews):
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)
    out = Assessor(cfg, {"claims": [CLAIM]}, LEAN, {}, reviews, []).run()
    claim, = out["claims"]
    return claim, [f for f in out["findings"] if f["subject"] == "toy:foo#0"]


def test_a_later_marker_at_another_hash_is_named_with_the_review_it_shadows(tmp_path):
    # The markers are read from the files, in name order: `b.md` after `a.md`.
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "a.md").write_text(
        "# Theorem 1\n\nRead against the paper today.\n\n"
        f"<!-- spec-review: Toy.spec_foo {H2} by=alice source=toy:foo@{D} -->\n")
    (tmp_path / "reviews" / "b.md").write_text(
        "# Theorem 1, an earlier reading\n\nRead against an earlier statement.\n\n"
        f"<!-- spec-review: Toy.spec_foo {H1} by=alice source=toy:foo@{D} -->\n")
    reviews, _ = load_reviews([tmp_path / "reviews"], [], tmp_path)
    assert [(r.file, r.hash) for r in reviews] == [("reviews/a.md", H2), ("reviews/b.md", H1)]

    claim, findings = run(reviews + [DEF])
    # The status is what it was: the record is the last marker, and it is not current.
    assert claim["status"] == "formal: proved, review pending"
    sr = claim["clauses"][0]["spec_review"]
    assert sr["state"] == "stale" and sr["current"] == []
    assert sr["why"] == "shadowed"
    assert sr["shadowed"] == {
        "reading": {"file": "reviews/a.md", "line": 5, "hash": H2, "by": "alice"},
        "record": {"file": "reviews/b.md", "line": 5, "hash": H1, "by": "alice"}}
    words = (f"at reviews/a.md:5 by alice records the current hash {H2}, but a marker later in "
             f"the review files, at reviews/b.md:5 by alice, records {H1} and is the record")
    assert claim["blockers"] == ["the proposition's review " + words,
                                 "Independent replay: not recorded (no Comparator record for "
                                 "this release)"]
    f, = [f for f in findings if f["code"] == "spec-review"]
    assert f["message"] == (f"the proposition Toy.spec_foo has no current review (its review "
                            f"{words}: record the review again after that marker, or retire "
                            "that marker)")
    assert f["reason"] == "shadowed" and f["record"]["file"] == "reviews/b.md"


def test_the_status_is_the_one_computed_without_the_earlier_reading():
    old = mark("Toy.spec_foo", H1, "reviews/b.md", 3)
    shadowed, _ = run([mark("Toy.spec_foo", H2, "reviews/a.md", 3), old, DEF])
    alone, _ = run([old, DEF])
    for key in ("status", "status_code", "class"):
        assert shadowed[key] == alone[key]
    assert shadowed["clauses"][0]["review"] == alone["clauses"][0]["review"] == "pending"
    # Without a reading at the current hash, the words are the ones for a changed proposition.
    sr = alone["clauses"][0]["spec_review"]
    assert sr["why"] == "declaration" and "shadowed" not in sr
    assert "the proposition changed after its last review" in alone["blockers"]
    # With the current reading recorded after the old marker, it is the record.
    after, _ = run([old, mark("Toy.spec_foo", H2, "reviews/c.md", 3), DEF])
    assert after["status"] == "formal: accepted"


def test_an_earlier_marker_that_did_not_read_the_current_passage_shadows_nothing():
    # At the current hash, but it read an earlier text of the passage: no review would count
    # without the later marker either, so nothing is shadowed.
    earlier_text = mark("Toy.spec_foo", H2, "reviews/a.md", 3, source={"toy:foo": "e" * 64})
    claim, _ = run([earlier_text, mark("Toy.spec_foo", H1, "reviews/b.md", 3), DEF])
    sr = claim["clauses"][0]["spec_review"]
    assert sr["why"] == "declaration" and "shadowed" not in sr


def test_a_shadowed_definition_review_is_named_in_the_blocker_and_the_finding():
    spec = mark("Toy.spec_foo", H2, "reviews/a.md", 3)
    later = mark("Toy.bar", "pl-fp-v1:" + "6" * 64, "reviews/b.md", 12, "def", by="bob")
    claim, findings = run([spec, DEF, later])
    assert claim["status"] == "formal: proved, review pending"
    r = claim["clauses"][0]["def_reviews"]["Toy.bar"]
    assert r["state"] == "stale" and r["why"] == "shadowed"
    words = (f"at reviews/a.md:9 by alice records the current hash {HD}, but a marker later in "
             f"the review files, at reviews/b.md:12 by bob, records pl-fp-v1:{'6' * 64} and is "
             "the record")
    assert "the review of the definition Toy.bar " + words in claim["blockers"]
    assert not [b for b in claim["blockers"] if "changed after their review" in b]
    f, = [f for f in findings if f["code"] == "def-review"]
    assert f["message"] == (f"the definition Toy.bar has no current review (its review {words}: "
                            "record the review again after that marker, or retire that marker)")
