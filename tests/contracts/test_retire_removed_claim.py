"""#566: after a claim is removed from the inventory, `inventory retire --markers` retires every
marker whose `source=` names it, of a proposition or of a definition, including the markers of a
definition no remaining entry names, whether or not a closure of the last build uses it. A
marker of that definition with no reading of the removed claim keeps its review."""

import json

from prooflens import config as cfgmod
from prooflens import evidence as ev
from prooflens import retire
from prooflens.reviews import load_reviews, parse_file
from test_retire import A, claim, committed, git, project, run

GONE = "9f" * 32
REVIEW = ("## Loss\n\nThe definition is the paper's.\n\n"
          "<!-- def-review: Lib.loss 0123abcd by=author -->\n"
          f"<!-- def-review: Lib.loss 0123abcd by=author source=X:sec:loss@{GONE} -->\n"
          f"<!-- def-review: Lib.loss 0123abcd by=auditor source=X:sec:loss@{GONE} -->\n\n"
          "## Main\n\nRead.\n\n"
          f"<!-- spec-review: X.main 0123 by=auditor source=X:sec:main@{A} "
          f"source=X:sec:loss@{GONE} -->\n")


def setup(tmp_path):
    # X:sec:loss, which named Lib.loss, is gone; X:sec:main states X.main.
    return project(tmp_path, [claim("X:sec:main", A, "X.main")], REVIEW)


def reviews(root):
    cfg = cfgmod.load(root / "machinechecked.toml")
    return load_reviews(cfg.reviews, [], root)[0]


def test_markers_of_a_removed_claim_s_definition_are_retired(tmp_path):
    root = setup(tmp_path)
    inv = json.loads((root / "claims.json").read_text())
    # With the last build's closures using Lib.loss, and with no build at all.
    for lean in ({"specs": {"X.main": {"closure": ["Lib.loss"]}}, "defs": {}, "proofs": {}},
                 None):
        res = retire.plan(inv, reviews(root), lean, True)
        assert [(m["line"], m["by"]) for m in res["markers"]] == [(6, "author"), (7, "auditor")]
        assert res["markers"][0]["reasons"] == {"X:sec:loss": "X:sec:loss is not in the inventory"}
        # The proposition's marker keeps its reading of the claim that remains.
        assert [(r["name"], r["retire"], r["keep"]) for r in res["readings"]] == [
            ("X.main", ["X:sec:loss"], ["X:sec:main"])]
        assert not [m for m in res["left"] if m["line"] in (6, 7)]


def test_the_command_leaves_no_live_marker_citing_the_removed_claim(tmp_path, capsys,
                                                                    monkeypatch):
    root = setup(tmp_path)
    lean = {"specs": {"X.main": {"closure": ["Lib.loss"]}}, "defs": {}, "proofs": {}}
    monkeypatch.setattr(ev, "latest", lambda out: {"evidence": "e"})
    monkeypatch.setattr(ev, "load", lambda out, eid: {"body": {"lean": lean}})
    assert run(root, "--markers", "--write") == 0
    capsys.readouterr()
    live = parse_file(root / "reviews" / "r.md", [], root)
    assert not [r for r in live if "X:sec:loss" in (r.source or {})]
    # The definition's marker with no reading keeps its review, with its text.
    assert [(r.name, r.by, r.source, r.text) for r in live] == [
        ("Lib.loss", "author", None, "The definition is the paper's."),
        ("X.main", "auditor", {"X:sec:main": A}, "Read.")]
    txt = (root / "reviews" / "r.md").read_text()
    assert txt.count("<!-- retired def-review: Lib.loss") == 2
    # A second run has nothing left to do.
    assert run(root, "--markers") == 0
    out = json.loads(capsys.readouterr().out)
    assert (out["readings"], out["markers"]) == ([], [])


def test_a_reading_recovered_from_the_history_retires_it_too(tmp_path, capsys):
    """A definition's marker an earlier version left as `source=none`, whose history shows a
    reading of the removed claim: it is retired whole with that reading, not given it back."""
    root = setup(tmp_path)
    git(root, "init", "-q")
    marker = "<!-- def-review: Lib.other 0123abcd by=auditor {} -->\n"
    committed(root, "## Other\n\nRead.\n\n" + marker.format(f"source=X:sec:loss@{GONE}"),
              "the review")
    committed(root, "## Other\n\nRead.\n\n" + marker.format("source=none"), "an earlier retire")
    assert run(root, "--markers", "--write") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["repairs"] == []
    (m,) = out["markers"]
    assert (m["name"], m["recovered"]) == ("Lib.other", {"X:sec:loss": GONE})
    assert "X:sec:loss, which is not in the inventory" in m["reason"]
    assert (root / "reviews" / "r.md").read_text().split("\n")[4] == \
        f"<!-- retired def-review: Lib.other 0123abcd by=auditor source=X:sec:loss@{GONE} -->"
