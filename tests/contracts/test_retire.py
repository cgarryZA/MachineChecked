"""#201: when the inventory moves a clause to another claim, `inventory retire` removes exactly
the readings markers record of passages that no longer use their declaration, and adds none; a
marker none of whose readings still applies is retired whole, keeping them (#395); on request it
retires whole the markers whose declaration no claim uses."""

import json

from prooflens import config as cfgmod
from prooflens import retire
from prooflens.reviews import MARKER, RETIRED, load_reviews, parse_file

A, B, C = "a" * 64, "b" * 64, "c" * 64


def project(tmp_path, claims, review):
    (tmp_path / "claims.json").write_text(json.dumps({"claims": claims}, indent=1))
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "r.md").write_text(review)
    (tmp_path / "machinechecked.toml").write_text(
        '[project]\nname = "x"\nlean_root = "."\nmodules = ["X"]\nscope_roots = ["X"]\n'
        'spec_prefix = "X"\naccept_prefix = "X"\ninventory = "claims.json"\n'
        'reviews = ["reviews"]\n\n[[paper]]\nid = "X"\ntitle = "X"\n'
        'source = { path = "paper" }\nroot = "main.tex"\n')
    return tmp_path


def claim(cid, sha, *specs, defs=()):
    return {"id": cid, "paper": "X", "scope": "formal", "source_sha256": sha,
            "clauses": [{"name": s, "spec": s} for s in specs]
            + ([{"name": "d", "defs": list(defs)}] if defs else [])}


REVIEW = ("## Part a\n\nThe statements say what the paper says.\n\n"
          f"<!-- spec-review: X.p 0123 by=reviewer source=X:sec:a@{A} -->\n"
          f"<!-- spec-review: X.q 0123 by=reviewer source=X:sec:a@{A} -->\n\n"
          "## Part b\n\nThe second half too.\n\n"
          f"<!-- spec-review: X.q 0123 by=other source=X:sec:a@{A} source=X:sec:b@{B} -->\n")


def run(root, *args):
    return retire.main(["--config", str(root / "machinechecked.toml"), *args])


def test_a_split_claim_retires_exactly_the_old_passage(tmp_path, capsys):
    # X:sec:a with clauses p and q is split: q moves to X:sec:b.
    root = project(tmp_path, [claim("X:sec:a", A, "X.p"), claim("X:sec:b", B, "X.q")], REVIEW)
    before = (root / "reviews" / "r.md").read_text()
    assert run(root) == 0
    out = json.loads(capsys.readouterr().out)
    assert not out["applied"] and (root / "reviews" / "r.md").read_text() == before
    assert [(r["line"], r["name"], r["retire"], r["keep"]) for r in out["readings"]] == [
        (12, "X.q", ["X:sec:a"], ["X:sec:b"])]
    assert out["readings"][0]["reasons"] == {"X:sec:a": "X:sec:a no longer states X.q"}
    # The first marker of q read only the old claim's passage: it is retired whole.
    assert [(m["line"], m["name"], m["reason"], m["reasons"]) for m in out["markers"]] == [
        (6, "X.q", "no passage it read still states X.q",
         {"X:sec:a": "X:sec:a no longer states X.q"})]

    assert run(root, "--write") == 0
    capsys.readouterr()
    p, q2 = parse_file(root / "reviews" / "r.md", [], root)
    # The reading of p stands; q's readings of the old claim are gone, never moved to X:sec:b.
    assert p.source == {"X:sec:a": A} and q2.source == {"X:sec:b": B}
    lines = (root / "reviews" / "r.md").read_text().split("\n")
    assert lines[5] == f"<!-- retired spec-review: X.q 0123 by=reviewer source=X:sec:a@{A} -->"
    # The review text is unchanged.
    assert p.text == "The statements say what the paper says."
    assert q2.text == "The second half too."
    # A second run has nothing left to do.
    assert run(root) == 0
    assert json.loads(capsys.readouterr().out)["readings"] == []


def test_a_marker_left_without_readings_is_not_read_through_its_history():
    """A marker that records `source=none` read no passage: it does not count for a claim by
    the history rule of markers written before readings were recorded."""
    from prooflens import review_sources as rs
    assert rs.parse("by=r source=none") == {}
    assert rs.parse("by=r") is None
    from prooflens.reviews import Review
    r = Review("spec", "X.q", "0123", "r", "human", "self-declared", "r.md", 1, "Text.",
               source=rs.parse("by=r source=none"))
    assert rs.marker_state(r, "X:sec:b", B) == "unread"


def test_markers_of_a_declaration_no_claim_uses_are_retired_whole(tmp_path, capsys):
    review = ("## P\n\nThe statement says what the paper says.\n\n"
              f"<!-- spec-review: X.p 0123 by=one source=X:sec:a@{A} -->\n"
              "Review by two: exact (report `r.md`).\n"
              f"<!-- spec-review: X.p 0123 by=two source=X:sec:a@{A} -->\n"
              f"<!-- spec-review: X.r 0123 by=one source=X:sec:a@{A} -->\n\n"
              "## D\n\nThe definition is the paper's.\n\n"
              f"<!-- def-review: X.gone 0123 by=one source=X:def@{C} -->\n"
              "<!-- def-review: X.inner 0123 by=one -->\n")
    # p leaves the claim at a new revision; r stays.
    root = project(tmp_path, [claim("X:sec:a", A, "X.r"), claim("X:def", C)], review)
    # Without --markers, the markers whose readings are all retired are: p's are retired whole;
    # the definition no claim names keeps its readings, which no claim's review reads.
    assert run(root) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["readings"] == [] and [m["name"] for m in out["markers"]] == ["X.p", "X.p"]
    assert [m["name"] for m in out["left"]] == ["X.gone"]
    cfg = cfgmod.load(root / "machinechecked.toml")
    reviews, _ = load_reviews(cfg.reviews, [], root)
    # The last build's closures hold X.inner, not X.gone.
    lean = {"specs": {"X.r": {"closure": ["X.inner"]}}, "defs": {}, "proofs": {}}
    res = retire.plan(json.loads((root / "claims.json").read_text()), reviews, lean, True)
    assert [(m["name"], m["by"]) for m in res["markers"]] == [
        ("X.p", "one"), ("X.p", "two"), ("X.gone", "one")]
    assert res["readings"] == [] and res["left"] == []
    # Without a build, a definition no claim names is left alone.
    res0 = retire.plan(json.loads((root / "claims.json").read_text()), reviews, None, True)
    assert [m["name"] for m in res0["markers"]] == ["X.p", "X.p"]
    assert [m["name"] for m in res0["left"]] == ["X.gone", "X.inner"]

    retire.apply(root, res)
    txt = (root / "reviews" / "r.md").read_text()
    assert txt.count("<!-- retired spec-review: X.p") == 2
    assert "<!-- retired def-review: X.gone" in txt
    left = parse_file(root / "reviews" / "r.md", [], root)
    # The retired markers record nothing; the others keep their own review text.
    assert [(r.name, r.text) for r in left] == [
        ("X.r", "The statement says what the paper says."),
        ("X.inner", "The definition is the paper's.")]


def test_a_reading_of_a_claim_id_with_an_at_sign_is_retired_exactly(tmp_path, capsys):
    review = ("## Q\n\nRead.\n\n"
              f"<!-- spec-review: X.q 0123 by=r source=X:sec:a@{A} source=X:sec:a@2@{B} -->\n")
    root = project(tmp_path, [claim("X:sec:a", A, "X.q"), claim("X:sec:a@2", B, "X.p")], review)
    assert run(root, "--write") == 0
    assert [r["retire"] for r in json.loads(capsys.readouterr().out)["readings"]] == [
        ["X:sec:a@2"]]
    q, = parse_file(root / "reviews" / "r.md", [], root)
    assert q.source == {"X:sec:a": A}


def test_a_marker_none_of_whose_readings_applies_is_retired_with_them(tmp_path, capsys):
    """#395: the passage a marker read no longer states its proposition, and another claim's
    does. The marker records a reading of the old passage only, which no longer applies: it is
    retired whole with that reading, never left as a marker that reads nothing, and the file
    parses as before."""
    review = ("## Foo\n\nRead beside the old passage.\n\n"
              f"<!-- spec-review: X.foo 0123 by=r source=X:old@{A} -->\n\n"
              "## Bar\n\nRead.\n\n"
              f"<!-- def-review: X.bar 0123 by=r source=X:old@{A} source=X:defs@{C} -->\n")
    root = project(tmp_path, [claim("X:old", A), claim("X:new", B, "X.foo"),
                              claim("X:defs", C, defs=["X.bar"])], review)
    assert run(root, "--write") == 0
    out = json.loads(capsys.readouterr().out)
    assert [(m["line"], m["name"]) for m in out["markers"]] == [(5, "X.foo")]
    assert [(r["name"], r["retire"], r["keep"]) for r in out["readings"]] == [
        ("X.bar", ["X:old"], ["X:defs"])]
    txt = (root / "reviews" / "r.md").read_text()
    assert "source=none" not in txt
    line = txt.split("\n")[4]
    assert line == f"<!-- retired spec-review: X.foo 0123 by=r source=X:old@{A} -->"
    assert RETIRED.fullmatch(line) and not MARKER.fullmatch(line)
    # The file parses: the retired marker records no review and still closes its text.
    cfg = cfgmod.load(root / "machinechecked.toml")
    reviews, _ = load_reviews(cfg.reviews, [], root)
    assert [(r.name, r.source, r.text) for r in reviews] == [("X.bar", {"X:defs": C}, "Read.")]
    assert run(root) == 0
    assert json.loads(capsys.readouterr().out) == {"applied": False, "readings": [],
                                                   "markers": [], "left": []}


def test_a_definition_no_claim_names_keeps_its_readings(tmp_path, capsys):
    """A definition no claim names any more has a review that reads no passage, which a
    closure may still count: its marker is not retired, and its readings, which no claim reads,
    stay as they were."""
    review = f"## D\n\nThe paper's.\n\n<!-- def-review: X.d 0123 by=r source=X:defs@{C} -->\n"
    root = project(tmp_path, [claim("X:defs", C, "X.p")], review)
    before = (root / "reviews" / "r.md").read_text()
    assert run(root, "--write") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["readings"] == [] and out["markers"] == []
    assert [(m["name"], m["reason"]) for m in out["left"]] == [
        ("X.d", "no claim names X.d: its review reads no passage, so the readings it records "
                "are inert")]
    assert (root / "reviews" / "r.md").read_text() == before
