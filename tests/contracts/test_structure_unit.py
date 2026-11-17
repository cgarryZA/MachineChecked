"""A structure is one review unit with the constants Lean generates for it (#610): its constructor
and projections have no unit of their own, one reading and one verdict cover them, and promotion
archives the report once and writes one marker per declaration in the form the acceptance
checker reads. A reviewer can still give one field a separate verdict.

The structure is the synthetic `Toy.Pair` (fields `x`, `y`, constructor `Toy.Pair.mk`); nothing
here builds Lean (`test_structure_unit_lean.py` does, on the toy paper)."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from prooflens.reviews import load_reviews
from test_compare import seg, write_site
from test_promote import CHECKER

S, MK, X, Y = "Toy.Pair", "Toy.Pair.mk", "Toy.Pair.x", "Toy.Pair.y"
WHO = "human:Pair-Reviewer"
READING = "A pair of natural numbers, its first and second coordinates, nothing more."


def hexes(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()


def field(f: str) -> dict:
    return {"field": f, "kind": "data", "declared_in": S, "inherited": False, "via": [],
            "projection": f"{S}.{f}", "type": seg("Nat")}


def decls(review: dict | None = None) -> dict:
    """The structure's records, by name, as the probe and the assessment give them; a field's
    docstring is its projection's."""
    st = {"class": False, "params": [], "parents": [], "fields": [field("x"), field("y")]}
    out = {
        S: {"name": S, "kind": "inductive", "module": "Toy.Defs", "signature": seg("Type"),
            "doc": "A pair of natural numbers.", "uses": [MK], "structure": st,
            "lean_source": {"file": "Toy/Defs.lean", "line": 3, "end_line": 7,
                            "text": "structure Pair where\n  x : Nat\n  y : Nat",
                            "sha256": "s" * 64}},
        MK: {"name": MK, "kind": "ctor", "module": "Toy.Defs",
             "signature": seg("Nat → Nat → Toy.Pair"), "uses": [S]},
        X: {"name": X, "kind": "def", "module": "Toy.Defs", "signature": seg("Toy.Pair → Nat"),
            "doc": "The first coordinate.", "uses": [S]},
        Y: {"name": Y, "kind": "def", "module": "Toy.Defs", "signature": seg("Toy.Pair → Nat"),
            "doc": "The second.", "uses": [S]},
        "Toy.other": {"name": "Toy.other", "kind": "def", "module": "Toy.Defs",
                      "signature": seg("Nat"), "uses": []},
    }
    for n, r in out.items():
        r.update(fingerprint=f"pl-fp-v1:{hexes(n)}", legacy_hash=hexes(n))
        if review is not None:
            r["review"] = dict(review)
    return out


def queue_of(names_per_claim: list[list[str]], state: str = "pending") -> dict:
    """The queue of a synthetic assessment: a proposition per claim, its closure the names
    given."""
    recs = decls({"state": state, "current": [], "source_sha256": {}})
    for n, r in recs.items():
        # A declaration in no closure has no review state, and no unit.
        if not any(n in names for names in names_per_claim):
            r["review"] = None
    store = {hexes(n)[:24]: r for n, r in recs.items()}
    claims, chunks = [], {}
    for i, names in enumerate(names_per_claim):
        f = f"c{i}.json"
        claims.append({"id": f"T:thm:{i}", "paper": "T", "number": f"Theorem {i}",
                       "title": "", "file": f, "status": "open", "class": "formal"})
        chunks[f] = {"decls": {n: hexes(n)[:24] for n in names},
                     "clauses": [{"name": "statement", "spec": f"Toy.spec_{i}",
                                  "statement": {"closure": names, "fingerprint": f"fp{i}",
                                                "legacy_hash": hexes(f"spec{i}")},
                                  "def_reviews": {n: {"state": state} for n in names}}]}
    return rq.assurance_queue({"release": "r1", "claims": claims}, chunks, store, [])


def test_a_structure_is_one_unit_with_its_constructor_and_projections():
    q = queue_of([[S, MK, X, Y]] * 3)
    defs = {u["id"]: u for u in q["units"] if u["kind"] == "def"}
    # Four declarations used by three claims: one unit, not four, and no twelve obligations.
    assert set(defs) == {"def:" + S}
    u = defs["def:" + S]
    assert u["lean"] == [S, MK, X, Y]
    assert [(m["name"], m["role"], m.get("field")) for m in u["members"]] == [
        (MK, "constructor", None), (X, "projection", "x"), (Y, "projection", "y")]
    assert u["fingerprints"] == {n: f"pl-fp-v1:{hexes(n)}" for n in (S, MK, X, Y)}
    assert u["fingerprint"] == f"pl-fp-v1:{hexes(S)}" and u["legacy_hash"] == hexes(S)
    assert [c["id"] for c in u["claims"]] == ["T:thm:0", "T:thm:1", "T:thm:2"]
    for spec in (x for x in q["units"] if x["kind"] == "spec"):
        # The statements reveal the structure's unit, and count it once as unreviewed.
        assert spec["reveals"]["lean"] == ["def:" + S]
        assert spec["unreviewed"] == 1


def test_the_unit_is_reviewed_only_when_every_member_is():
    recs = decls()
    states = {S: "reviewed", MK: "reviewed", X: "stale", Y: "reviewed"}
    for n, r in recs.items():
        r["review"] = {"state": states.get(n, "pending"), "current": [], "source_sha256": {}}
    u = rq._def_unit(S, recs[S], rq.structure_members(S, recs), recs, {}, {}, {})
    assert u["state"] == "stale"
    assert {m["name"]: m["state"] for m in u["members"]} == {MK: "reviewed", X: "stale",
                                                            Y: "reviewed"}


def test_a_definition_that_is_not_a_structure_is_unchanged():
    q = queue_of([["Toy.other"]])
    (u,) = [u for u in q["units"] if u["kind"] == "def"]
    assert u["id"] == "def:Toy.other"
    assert not {"lean", "members", "fingerprints"} & set(u)


# -- promotion --------------------------------------------------------------------------------

def report(unit: dict, members: dict | None = None, verdict: str = "faithful") -> dict:
    return {"schema": "prooflens/review-report@1",
            "unit": {"id": unit["id"], "kind": "def", "name": unit["name"],
                     "lean": unit.get("lean") or [unit["name"]], "claims": [], "papers": []},
            "pins": {"release": "r1", "legacy_hash": unit["legacy_hash"],
                     "fingerprint": unit["fingerprint"], "fingerprints": unit.get("fingerprints"),
                     "source_sha256": {}, "manuscripts": {}},
            "reviewer": {"id": WHO, "kind": "human", "same_family_as_author": "no"},
            "reading": {"text": READING, "locked_at": "2026-01-01T10:00:00Z"},
            "comparison": {"text": "Field by field it matches.",
                           "decided_at": "2026-01-01T10:05:00Z"},
            "verdict": {"group": "matches", "value": verdict, "detail": "",
                        **({"members": members} if members else {})},
            "author_review": {"shown_at": "2026-01-01T10:05:00Z", "disagreements": "none"},
            "submitted_at": "2026-01-01T10:06:00Z"}


def body() -> dict:
    return {"lean": {"decls": decls()}, "inventory": {"claims": []}, "tex": {},
            "provenance": {"papers": {}}}


def unit() -> dict:
    (u,) = [u for u in queue_of([[S, MK, X, Y]])["units"] if u["kind"] == "def"]
    return u


def project(tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "definitions.md").write_text(
        f"# Definitions\n\n## Other\n\nIts review.\n\n<!-- def-review: Toy.other "
        f"{hexes('Toy.other')} by=human:Someone -->\n", encoding="utf-8")
    return SimpleNamespace(reviews=[tmp_path / "reviews"], ai_reviewers=[], root=tmp_path,
                           statement_authors=["statement-author"])


def promote(cfg, r):
    b = body()
    assert pr.check_report(r, b, cfg, False) == []
    cur = pr.with_covers(r, b["lean"]["decls"][S], b)
    return cur, pr.apply(cfg, [(r, cur)])


def test_one_report_writes_a_marker_for_each_declaration_and_one_archive(tmp_path):
    cfg = project(tmp_path)
    r = report(unit())
    cur, done = promote(cfg, r)
    assert [d["name"] for d in done] == [S, MK, X, Y]
    text = (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8")
    found = {m.group(2): m.group(3) for m in CHECKER.finditer(text) if m.group(4) == WHO}
    assert found == {n: hexes(n) for n in (S, MK, X, Y)}
    # One canonical record: one archived report covering the four.
    (record,) = (tmp_path / "reviews" / "reports").iterdir()
    assert record.suffix == ".json"
    assert json.loads(record.read_text(encoding="utf-8"))["unit"]["lean"] == [S, MK, X, Y]
    assert f"Covers: {S}, {MK}, {X}, {Y}" in pr.report_text(r)
    # Each marker records a reading (its `Review by` line, linking the record), as the
    # assessment requires.
    reviews, _ = load_reviews(cfg.reviews, [], tmp_path)
    mine = {x.name: x.text for x in reviews if x.by == WHO}
    assert set(mine) == {S, MK, X, Y} and all(
        t.startswith(f"Review by {WHO}: faithful") and f"reports/{record.name}`" in t
        for t in mine.values())
    assert pr.already_promoted(cfg, r, cur)
    again = pr.apply(cfg, [(r, cur)])
    assert all(d["already"] for d in again)
    assert (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8") == text


def test_a_member_marker_goes_after_its_earlier_marker(tmp_path):
    cfg = project(tmp_path)
    f = tmp_path / "reviews" / "definitions.md"
    f.write_text(f"# Definitions\n\n## y\n\nOld review.\n\n<!-- def-review: {Y} {'0' * 32} "
                 "by=human:Someone -->\n\n## Other\n\nText.\n", encoding="utf-8")
    promote(cfg, report(unit()))
    reviews, _ = load_reviews(cfg.reviews, [], tmp_path)
    last = [x for x in reviews if x.name == Y][-1]
    assert last.hash == hexes(Y) and last.by == WHO and "with Toy.Pair" in last.text


def test_a_separate_verdict_on_one_field_leaves_it_without_a_marker(tmp_path):
    cfg = project(tmp_path)
    r = report(unit(), {Y: {"group": "problem", "value": "narrower",
                            "detail": "y is bounded by 10 in the paper"}})
    cur, done = promote(cfg, r)
    assert [d["name"] for d in done] == [S, MK, X]
    assert set(cur["left_out"]) == {Y}
    text = (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8")
    assert Y not in {m.group(2) for m in CHECKER.finditer(text)}
    (record,) = (tmp_path / "reviews" / "reports").iterdir()
    stored = json.loads(record.read_text(encoding="utf-8"))
    # The disagreement is recorded once, in the one report; the reading is not copied.
    assert stored["verdict"]["members"][Y]["value"] == "narrower"
    assert record.read_text(encoding="utf-8").count(READING) == 1
    block = pr.report_text(stored)
    assert f"Separate verdict on {Y}: narrower — y is bounded by 10 in the paper (no marker" \
        in block and f"Covers: {S}, {MK}, {X}\n" in block


def test_promotion_refuses_a_member_it_cannot_check(tmp_path):
    cfg = project(tmp_path)
    u = unit()
    stray = report({**u, "lean": [*u["lean"], "Toy.other"]})
    assert any("Toy.other is not a constructor or projection of Toy.Pair" in w
               for w in pr.check_report(stray, body(), cfg, False))
    changed = report({**u, "fingerprints": {**u["fingerprints"], X: "pl-fp-v1:" + "0" * 32}})
    assert any(f"{X}, reviewed with {S}, changed since the review" in w
               for w in pr.check_report(changed, body(), cfg, False))
    bad = report(u, {"Toy.other": {"value": "faithful"}, X: {"value": "narrower"}})
    why = pr.check_report(bad, body(), cfg, False)
    assert any("Toy.other is not a constructor or projection" in w for w in why)
    assert any("the verdict 'narrower' on Toy.Pair.x needs its detail" in w for w in why)
    # A unit without members takes no separate verdict.
    plain = report({"id": "def:Toy.other", "name": "Toy.other",
                    "legacy_hash": hexes("Toy.other"),
                    "fingerprint": f"pl-fp-v1:{hexes('Toy.other')}"}, {X: {"value": "faithful"}})
    b = body()
    assert any("is not a constructor or projection" in w for w in pr.covers(plain, b)[2])


# -- the review steps -------------------------------------------------------------------------

def site_with_pair(tmp_path, extra_work: dict | None = None):
    """The synthetic site of `test_compare` with the structure's records and its unit in the
    queue; returns the working directory."""
    data = write_site(tmp_path)
    recs = decls({"state": "pending", "current": [], "source_sha256": {}})
    for n, r in recs.items():
        (data / "decls" / f"{hexes(n)[:24]}.json").write_text(json.dumps(r))
    u = rq._def_unit(S, recs[S], rq.structure_members(S, recs), recs,
                     {n: hexes(n)[:24] for n in recs}, {S: {"S:thm:t0"}}, {"S:thm:t0": "S"})
    q = json.loads((data / "review-queue.json").read_text())
    q["units"].append({**u, "reveals": {"lean": [], "author": []}})
    (data / "review-queue.json").write_text(json.dumps(q))
    return data.parent.parent


def test_the_unit_shows_the_fields_their_docstrings_and_the_source(tmp_path):
    work = site_with_pair(tmp_path)
    s = rc.Session(work, rc.parse_reviewer(WHO))
    s.read("def:" + S)
    s.lock("def:" + S, READING)
    pk = s.show("def:" + S, as_json=True)
    (d,) = [d for d in pk["lean"]["declarations"] if d["name"] == S]
    assert d["lean_source"]["text"].startswith("structure Pair where")
    assert {f["field"]: f.get("doc") for f in d["structure"]["fields"]} == {
        "x": "The first coordinate.", "y": "The second."}
    gen = {x["name"]: x.get("generated_for") for x in pk["lean"]["definitions"]}
    assert gen[MK] == gen[X] == gen[Y] == S
    text = s.show("def:" + S)
    assert "x : Nat (data) — The first coordinate." in text


def test_a_member_is_reviewed_in_its_structure_unit(tmp_path):
    s = rc.Session(site_with_pair(tmp_path), rc.parse_reviewer(WHO))
    with pytest.raises(rc.ReviewError, match=f"reviewed with its structure, in unit def:{S}"):
        s.read("def:" + X)


def test_sight_of_a_member_earlier_is_sight_of_the_structure(tmp_path):
    """A draft on a projection as a unit of its own (from a queue before they were reviewed
    together) showed the structure's Lean: the structure's reading is not blind."""
    work = site_with_pair(tmp_path)
    s = rc.Session(work, rc.parse_reviewer(WHO))
    s.work["drafts"]["def:" + X] = {"stage": "compare", "reading": READING,
                                     "locked_at": "2026-01-01T09:00:00Z"}
    s.save()
    s = rc.Session(work, rc.parse_reviewer(WHO))
    assert s.revealed_by(s.unit("def:" + S)) == [{"unit": "def:" + X, "what": "Lean"}]


def test_a_separate_verdict_is_recorded_with_the_verdict(tmp_path):
    work = site_with_pair(tmp_path)
    s = rc.Session(work, rc.parse_reviewer(WHO))
    uid = "def:" + S
    s.read(uid)
    s.lock(uid, READING)
    s.show(uid)
    with pytest.raises(rc.ReviewError, match="needs its detail"):
        s.decide(uid, "faithful", "Field by field.", members={Y: {"verdict": "narrower"}})
    with pytest.raises(rc.ReviewError, match="is not a constructor or projection"):
        s.decide(uid, "faithful", "Field by field.", members={S: {"verdict": "faithful"}})
    s.decide(uid, "faithful", "Field by field.",
             members={Y: {"verdict": "narrower", "detail": "bounded in the paper"}})
    s.author(uid)
    r = s.submit(uid, "none")
    assert r["unit"]["lean"] == [S, MK, X, Y]
    assert r["pins"]["fingerprints"][Y] == f"pl-fp-v1:{hexes(Y)}"
    assert r["verdict"]["members"] == {Y: {"group": "problem", "value": "narrower",
                                           "detail": "bounded in the paper"}}
    # Undo gives the separate verdict back with the rest of the verdict.
    assert s.undo()["members"] == r["verdict"]["members"]


def test_check_lists_a_definition_review_once_with_its_claims():
    details = [{"tier": "obligation", "code": "def-review", "subject": f"T:thm:{i}#statement",
                "trigger": n, "message": f"the definition {n} has no current review"}
               for i in range(3) for n in (S, MK, X, Y)]
    details.append({"tier": "violation", "code": "axiom", "subject": "T:thm:0#statement",
                    "message": "uses sorryAx"})
    lines = cli._obligation_lines(details, decls())
    assert lines == [
        f"  obligation  the definition {S} has no current review; in the same review unit: "
        f"{MK}, {X}, {Y} (needed by 3: T:thm:0#statement, T:thm:1#statement, "
        "T:thm:2#statement)",
        "  violation  T:thm:0#statement: uses sorryAx"]
