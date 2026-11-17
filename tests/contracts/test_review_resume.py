"""The review protocol tells a reviewer where they stand: a unit already reported is shown as it
was reviewed and never read again (#701); a unit whose Lean another unit's step 2 shows is named
before that happens, and a reading locked after it is flagged at the lock, not first at
promotion (#638); and `review status` gives the time of each step taken, for resuming (#699).

The site is the synthetic zero-configuration build of `test_compare.write_site`, with a second
unit whose Lean the first one's step 2 shows. Nothing here builds Lean."""

import copy
import json

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from test_compare import write_site

UNIT = "link:thm:t0"
OTHER = "link:thm:shown-by-t0"
WHO = "human:Resume-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."


@pytest.fixture
def work(tmp_path):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text())
    other = copy.deepcopy(q["units"][0])
    other["id"] = OTHER
    q["units"][0]["reveals"] = {"lean": [OTHER], "author": []}
    q["units"].append(other)
    (data / "review-queue.json").write_text(json.dumps(q))
    return data.parent.parent


def session(work):
    return rc.Session(work, rc.parse_reviewer(WHO))


def through(s, uid):
    s.read(uid)
    s.lock(uid, READING)
    s.show(uid)
    s.decide(uid, "faithful", "Item by item, the same bound.")
    s.author(uid)
    return s.submit(uid, "none")


def test_a_reported_unit_shows_its_lean_and_takes_no_new_reading(work):
    s = session(work)
    r = through(s, UNIT)
    s = session(work)
    shown = s.show(UNIT)
    assert "lock your reading first" not in shown
    assert f"{UNIT} is reported (submitted {r['submitted_at']}" in shown
    assert "Syn.big_bound_" in shown
    assert s.show(UNIT, as_json=True)["review"]["step"] == "reported"
    with pytest.raises(rc.ReviewError) as e:
        s.lock(UNIT, READING)
    assert e.value.kind == "reported" and "would not be blind" in str(e.value)
    # Nothing was started by either.
    assert session(work).work["drafts"] == {}


def test_a_unit_whose_lean_another_shows_is_named_before_and_flagged_at_the_lock(work):
    s = session(work)
    assert f"will show the Lean of {OTHER}" in s.read(UNIT)
    assert s.read(UNIT, as_json=True)["review"]["reveals"] == [OTHER]
    assert s.lock(UNIT, READING) == []
    s.show(UNIT)
    s = session(work)
    s.read(OTHER)
    assert {"unit": UNIT, "what": "Lean"} in s.lock(OTHER, READING)
    # Locked first, the other unit's reading is blind, and no note is given.
    s2 = rc.Session(work, rc.parse_reviewer("human:Careful-Reviewer"))
    s2.read(OTHER)
    assert s2.lock(OTHER, READING) == []
    assert "will show" not in s2.read(UNIT)


def test_the_lock_warning_is_printed_by_the_command(work, capsys):
    s = session(work)
    s.read(UNIT)
    s.lock(UNIT, READING)
    s.show(UNIT)
    session(work).read(OTHER)
    reading = work.parent / "reading.md"
    reading.write_text(READING)

    class A:
        unit, text = OTHER, str(reading)
    cli._review_lock(A, session(work))
    err = capsys.readouterr().err
    assert "this reading is not blind" in err and UNIT in err and "--allow-revealed" in err


def test_status_gives_the_time_of_each_step(work, capsys):
    s = session(work)
    s.read(UNIT)
    (p,) = s.progress()
    assert (p["step"], p["locked_at"], p["shown"]) == ("read", None, False)
    s.lock(UNIT, READING)
    (p,) = session(work).progress()
    assert p["step"] == "compare" and p["locked_at"] and not p["shown"]
    s = session(work)
    s.show(UNIT)
    (p,) = session(work).progress()
    assert p["shown"] and p["shown_at"] >= p["locked_at"]
    first = p["shown_at"]
    session(work).show(UNIT)
    (p,) = session(work).progress()
    assert p["shown_at"] == first

    class A:
        order, json = "priority", False
    cli._review_status(A, session(work))
    out = capsys.readouterr().out
    assert f"{UNIT}: at step 'compare' (locked " in out and f"Lean shown {first}" in out


def test_promoting_a_report_again_writes_nothing(tmp_path):
    """#622: the second promotion of a report finds its marker written and leaves the review
    file and the archive as they are."""
    from types import SimpleNamespace

    from prooflens import promote as pr
    (tmp_path / "reviews").mkdir()
    defs = tmp_path / "reviews" / "definitions.md"
    defs.write_text("# Definitions\n")
    cfg = SimpleNamespace(reviews=[tmp_path / "reviews"], ai_reviewers=[], root=tmp_path)
    r = {"unit": {"id": "def:Toy.x", "kind": "def", "name": "Toy.x", "claims": [],
                  "papers": []},
         "pins": {"source_sha256": None}, "reviewer": {"id": "human:Test-Referee", "kind": "human"},
         "reading": {"text": "r", "locked_at": "t0"}, "comparison": {"text": "c", "decided_at": "t1"},
         "author_review": {"shown_at": "t2"},
         "verdict": {"value": "faithful"}, "submitted_at": "2026-01-01T10:06:00Z"}
    cur = {"legacy_hash": "a" * 32}
    assert not pr.already_promoted(cfg, r, cur)
    (first,) = pr.apply(cfg, [(r, cur)])
    assert not first.get("already") and pr.already_promoted(cfg, r, cur)
    text = defs.read_text()
    archive = sorted(p.name for p in (tmp_path / "reviews" / "reports").iterdir())
    (again,) = pr.apply(cfg, [(r, cur)])
    assert again["already"]
    assert defs.read_text() == text and text.count(first["marker"]) == 1
    assert sorted(p.name for p in (tmp_path / "reviews" / "reports").iterdir()) == archive
