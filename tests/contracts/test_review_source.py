"""#165: a review marker records the paper text it read, and a change to that text reopens the
review; a marker written before the record was kept counts only while the history shows the text
unchanged since it was written."""

import json
import re
import subprocess

from conftest import build, edit, findings, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens import review_sources as rs

EVEN_ADD = "If $a$ and $b$ are even natural numbers, then $a + b$ is even."
CHANGED = "If $a$ and $b$ are even natural numbers, then $a + b$ is even and so is $a b$."


def anchor_pin(body, label):
    """The digest of a statement's text in the compiled paper."""
    return next(a["source_sha256"] for a in body["tex"]["T"]["anchors"] if a.get("label") == label)


def repin(toy, cid, sha):
    """Pin a claim to new text, as a repin after a new revision of the paper does."""
    inv = json.loads((toy / "claims.json").read_text())
    next(c for c in inv["claims"] if c["id"] == cid)["source_sha256"] = sha
    (toy / "claims.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False) + "\n")


def change_text(toy):
    """Change the text of Theorem 2.1 and repin the inventory to it."""
    edit(toy / "paper/toy.tex", EVEN_ADD, CHANGED)
    _, body, _ = build(toy, reuse_lean=True)
    repin(toy, "T:thm:even-add", anchor_pin(body, "thm:even-add"))
    return build(toy, reuse_lean=True)


def strip_source(path, name):
    """The marker of `name` as it was written before markers recorded their passage."""
    txt = path.read_text()
    new = re.sub(r"(-review: " + re.escape(name) + r" [^>]*?) source=\S+", r"\1", txt)
    assert new != txt
    path.write_text(new)


def git(toy, *args):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", *args],
                   cwd=toy, check=True, capture_output=True)


def commit_all(toy, msg):
    git(toy, "add", "-A")
    git(toy, "commit", "-q", "-m", msg)


def init_git(toy):
    (toy / ".gitignore").write_text(".lake/\n.machinechecked/\n.prooflens/\n")
    git(toy, "init", "-q")
    commit_all(toy, "the toy paper")


@needs_lean
@needs_tex
def test_a_text_change_reopens_the_review_and_an_unchanged_passage_keeps_it(toy):
    index, body, _ = build(toy)
    assert status(index, "T:thm:even-add") == "formal: accepted"
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"
    clause = next(c for c in body["assessment"]["claims"]
                  if c["id"] == "T:thm:even-add")["clauses"][0]
    assert clause["spec_review"]["state"] == "reviewed"
    assert clause["spec_review"]["source_sha256"] == {"T:thm:even-add": next(
        c for c in body["inventory"]["claims"] if c["id"] == "T:thm:even-add")["source_sha256"]}

    index, body, _ = change_text(toy)
    # The inventory is pinned to the new text, so the source check passes; the review read the
    # old text, so it no longer counts.
    assert not findings(body, "source-changed")
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    sr = next(c for c in body["assessment"]["claims"]
              if c["id"] == "T:thm:even-add")["clauses"][0]["spec_review"]
    assert sr["state"] == "stale" and sr["why"] == "source-changed"
    assert sr["source_claim"] == "T:thm:even-add" and not sr["current"]
    f, = findings(body, "spec-review", "T:thm:even-add")
    assert f["reason"] == "source-changed" and f["source_claim"] == "T:thm:even-add"
    assert "the source text of Theorem 2.1 (T:thm:even-add) changed since its last reading" \
        in f["message"]
    row = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
    assert "the paper's text changed after the proposition's last review" in row["blockers"]
    # The other claims read passages that did not change: their reviews stand.
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"
    assert status(index, "T:def:even") == "definition: author-reviewed"

    # The queue offers the unit again, at the new text's digest.
    cfg = cfgmod.load(toy / "machinechecked.toml")
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    u = next(u for u in q["units"] if u["id"] == "spec:Toy.PaperSpec.thm_even_add")
    assert u["state"] == "stale" and u["source_sha256"] == sr["source_sha256"]

    # A reading of the new text, recorded with its digest, is current again.
    txt = (toy / "reviews/T.md").read_text()
    (toy / "reviews/T.md").write_text(re.sub(
        r"(thm_even_add \S+ by=a\.referee kind=human source=T:thm:even-add@)[0-9a-f]{64}",
        r"\g<1>" + sr["source_sha256"]["T:thm:even-add"], txt))
    index, _, _ = build(toy, reuse_lean=True)
    assert status(index, "T:thm:even-add") == "formal: accepted"


@needs_lean
@needs_tex
def test_a_marker_without_digests_and_no_history_is_not_counted(toy):
    strip_source(toy / "reviews/T.md", "Toy.PaperSpec.thm_even_add")
    index, body, _ = build(toy)
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    sr = next(c for c in body["assessment"]["claims"]
              if c["id"] == "T:thm:even-add")["clauses"][0]["spec_review"]
    assert sr["state"] == "stale" and sr["why"] == "source-unrecorded"
    f, = findings(body, "spec-review", "T:thm:even-add")
    assert f["reason"] == "source-unrecorded"
    assert "made before source pins were recorded" in f["message"]
    row = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
    assert "the proposition was reviewed before source pins were recorded" in row["blockers"]
    # A declaration no claim names has no passage: its markers need no digest.
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"
    # Without a history, the migration adds nothing.
    add, keep = rs.migration(cfgmod.load(toy / "machinechecked.toml"))
    assert not add and [k["name"] for k in keep] == ["Toy.PaperSpec.thm_even_add"]


@needs_lean
@needs_tex
def test_a_marker_without_digests_counts_while_the_history_shows_its_text_unchanged(toy):
    strip_source(toy / "reviews/T.md", "Toy.PaperSpec.thm_even_add")
    strip_source(toy / "reviews/definitions.md", "Toy.IsEven")
    init_git(toy)
    index, _, cfg = build(toy)
    assert status(index, "T:thm:even-add") == "formal: accepted"

    # A later commit changes the text of Theorem 2.1 and repins it: the marker was written
    # before, so it no longer counts; the definition's passage did not change.
    index, body, _ = change_text(toy)
    commit_all(toy, "a new revision of Theorem 2.1")
    index, body, _ = build(toy, reuse_lean=True)
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    sr = next(c for c in body["assessment"]["claims"]
              if c["id"] == "T:thm:even-add")["clauses"][0]["spec_review"]
    assert sr["why"] == "source-changed" and sr["source_claim"] == "T:thm:even-add"
    assert status(index, "T:def:even") == "definition: author-reviewed"

    # The migration adds the digest where the passage is unchanged, and only there.
    before = (toy / "reviews/T.md").read_text()
    add, keep = rs.migration(cfg)
    assert [(a["name"], a["attribute"]) for a in add] == [
        ("Toy.IsEven", "source=T:def:even@" + next(
            c["source_sha256"] for c in body["inventory"]["claims"] if c["id"] == "T:def:even"))]
    assert [(k["name"], k["state"], k["claim"]) for k in keep] == [
        ("Toy.PaperSpec.thm_even_add", "changed", "T:thm:even-add")]
    assert rs.main(["--config", str(toy / "machinechecked.toml"), "--write"]) == 0
    assert (toy / "reviews/T.md").read_text() == before
    assert re.search(r"def-review: Toy\.IsEven \S+ by=a\.referee kind=human "
                     r"source=T:def:even@[0-9a-f]{64} "
                     r"-->", (toy / "reviews/definitions.md").read_text())
    index, _, _ = build(toy, reuse_lean=True)
    assert status(index, "T:def:even") == "definition: author-reviewed"
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"


def test_a_legacy_pin_rehashed_at_the_same_revision_keeps_its_passage():
    inv = {"papers": {"P": {"commit": "abcdef1"}}}
    old = {"id": "P:t", "paper": "P", "location": "s.tex", "source_sha256": "1" * 64}
    new = {"id": "P:t", "paper": "P", "location": "s.tex:12", "source_sha256": "2" * 64,
           "source_hash_scheme": "tex-region-v1"}
    assert rs.same_passage(old, inv, new, inv)
    # The same digest under one scheme is the same text at any revision.
    moved = {**new, "commit": "1234567", "location": "s.tex:40"}
    assert rs.same_passage(new, inv, moved, inv)
    # A new digest under the same scheme, a rehash at another revision or in another file is not.
    assert not rs.same_passage(new, inv, {**new, "source_sha256": "3" * 64}, inv)
    assert not rs.same_passage(old, inv, {**new, "commit": "1234567"}, inv)
    assert not rs.same_passage(old, inv, {**new, "location": "t.tex:12"}, inv)


def test_marker_digests_are_read_per_claim(tmp_path):
    from prooflens.reviews import parse_file
    f = tmp_path / "r.md"
    f.write_text("## A\n\nText.\n\n<!-- spec-review: X.a " + "0" * 32 + " by=r source=P:b@"
                 + "b" * 64 + " source=P:a@" + "a" * 64 + " -->\n\n## B\n\nText.\n\n"
                 "<!-- spec-review: X.b " + "0" * 32 + " by=r -->\n")
    a, b = parse_file(f, [], tmp_path)
    assert a.source == {"P:a": "a" * 64, "P:b": "b" * 64} and a.by == "r"
    assert b.source is None
    assert rs.attribute(a.source) == f"source=P:a@{'a' * 64} source=P:b@{'b' * 64}"


def test_a_proposition_stated_by_two_claims_reopens_only_for_the_changed_one():
    """A review of a proposition two claims state counts for each claim whose passage it read
    as it now is: a change to one claim's text reopens that claim only."""
    from types import SimpleNamespace
    from prooflens.assess import Assessor
    from prooflens.reviews import Review
    fp = "synthetic-fingerprint"
    clause = {"name": "main", "spec": "S.spec", "accept": "S.accept"}
    inv = {"claims": [{"id": f"P:{x}", "paper": "P", "scope": "formal", "scope_reviewed": True,
                       "source_sha256": x * 64, "clauses": [clause]} for x in "ab"]}
    lean = {"specs": {"S.spec": {"fingerprint": fp, "errors": [], "closure": [], "binders": [],
                                 "consts": []}},
            "proofs": {"accept:S.accept:S.spec": {"errors": [], "sorry": False, "axioms": []}},
            "decls": {}, "defs": {}, "layering": []}
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)

    def run(source):
        r = Review("spec", "S.spec", fp, "a-referee", "human", "self-declared", "r.md", 1, "",
                   source=source)
        return {c["id"]: c for c in Assessor(cfg, inv, lean, {}, [r], []).run()["claims"]}

    both = run({"P:a": "a" * 64, "P:b": "b" * 64})
    assert {c: both[c]["status"] for c in both} == {"P:a": "formal: accepted",
                                                    "P:b": "formal: accepted"}
    changed = run({"P:a": "a" * 64, "P:b": "c" * 64})
    assert changed["P:a"]["status"] == "formal: accepted"
    assert changed["P:b"]["status"] == "formal: proved, review pending"
    assert changed["P:b"]["clauses"][0]["spec_review"]["why"] == "source-changed"
    # A reading that did not record a claim's passage does not count for it.
    one = run({"P:a": "a" * 64})
    assert one["P:a"]["status"] == "formal: accepted"
    sr = one["P:b"]["clauses"][0]["spec_review"]
    assert sr["why"] == "source-unread" and sr["source_claim"] == "P:b"
    assert "did not read this claim's passage" in " ".join(one["P:b"]["blockers"])


def test_a_step_marker_follows_the_same_rule(tmp_path):
    """A step-review marker's hash is the digest of the passage it read; a `source` attribute
    for the step must agree with it, and the marker is current by the rule of every marker."""
    from prooflens.reviews import parse_file
    from prooflens.steps import marker_review
    a, b = "a" * 64, "b" * 64
    f = tmp_path / "r.md"
    f.write_text(f"## S\n\nIt holds.\n\n<!-- step-review: P:eq:s {a} verdict=holds by=r -->\n\n"
                 f"## S again\n\nIt holds.\n\n<!-- step-review: P:eq:s {a} verdict=holds by=r "
                 f"source=P:eq:s@{a} -->\n\n## S, disagreeing\n\nIt holds.\n\n"
                 f"<!-- step-review: P:eq:s {a} verdict=holds by=r source=P:eq:s@{b} -->\n")
    plain, same, other = parse_file(f, [], tmp_path)
    assert plain.source == same.source == {"P:eq:s": a} and other.source == {}
    assert rs.marker_state(plain, "P:eq:s", a) == "current"
    assert rs.marker_state(plain, "P:eq:s", b) == "changed"
    assert rs.marker_state(other, "P:eq:s", a) == "unread"
    assert marker_review([plain], "P:eq:s", a)["state"] == "holds"
    assert marker_review([plain], "P:eq:s", b)["state"] == "stale"
    assert marker_review([plain, other], "P:eq:s", a)["state"] == "stale"
    # A step report pins its passage by claim like any report; an older one by its source hash.
    assert rs.report_digests({"unit": {"id": "step:P:eq:s"},
                              "pins": {"fingerprints": {"source": a}}}) == {"P:eq:s": a}
    assert rs.report_digests({"unit": {"id": "step:P:eq:s"},
                              "pins": {"source_sha256": {"P:eq:s": b},
                                       "fingerprints": {"source": a}}}) == {"P:eq:s": b}
