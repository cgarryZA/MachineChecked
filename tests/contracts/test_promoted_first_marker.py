"""#608: `review promote` writes a `Review by` line and then the reviewer's marker. A marker
directly preceded by its `Review by` line has that line as its text, whatever comes before the
line: a review file's title (the first promotion into a new file), or an author's section left
without a marker, which keeps its text for the author's marker. Every project here is synthetic;
nothing builds Lean."""

from types import SimpleNamespace

import pytest

from prooflens import promote as pr
from prooflens.assess import Assessor
from prooflens.reviews import load_reviews, parse_file
from test_promote_target import WHO, cur, project, report

SPEC = "Toy.PaperSpec.thm_new"
H = "a" * 32
LEAN = {"specs": {SPEC: {"legacy_hash": H, "errors": [], "binders": [], "closure": [],
                         "consts": []}},
        "decls": {SPEC: {"name": SPEC, "legacy_hash": H, "uses": []}}, "proofs": {}, "defs": {},
        "layering": []}
AUTHOR = "The author's account of Theorem 1, which no marker closes yet."


def promoted(tmp_path, before: str):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "T.md").write_text(before, encoding="utf-8")
    cfg = project(tmp_path, ["reviews/T.md"])
    pr.apply(cfg, [(report("spec", SPEC), cur("spec"))])
    reviews, _ = load_reviews(cfg.reviews, [], cfg.root)
    return cfg, reviews


def assessed(cfg, reviews):
    claim = {"id": "T:thm:new", "paper": "T", "kind": "theorem", "scope": "formal",
             "scope_reviewed": True, "clauses": [{"name": "statement", "spec": SPEC}]}
    a = Assessor(SimpleNamespace(statement_authors=["author"], lean_root=None,
                                 papers=[SimpleNamespace(id="T")], root=cfg.root),
                 {"claims": [claim]}, LEAN, {}, reviews, [])
    return a.review_state("spec", SPEC, LEAN["specs"][SPEC], claim["id"])


@pytest.mark.parametrize("before", ["# Reviews\n", f"# Reviews\n\n## Theorem 1\n\n{AUTHOR}\n"])
def test_a_promoted_marker_reads_its_own_review_line(tmp_path, before):
    cfg, reviews = promoted(tmp_path, before)
    (r,) = [r for r in reviews if r.by == WHO]
    assert r.text.startswith(f"Review by {WHO}: faithful (report `")
    assert AUTHOR not in r.text
    # The review counts: a reading is recorded, and the proposition reads reviewed.
    state = assessed(cfg, reviews)
    assert state["state"] == "reviewed", state
    assert state["rests_on"]["by"] == WHO


def test_the_author_s_section_keeps_its_text_for_the_author_s_marker(tmp_path):
    cfg, _ = promoted(tmp_path, f"# Reviews\n\n## Theorem 1\n\n{AUTHOR}\n")
    path = tmp_path / "reviews" / "T.md"
    path.write_text(path.read_text(encoding="utf-8")
                    + f"<!-- spec-review: {SPEC} {H} by=author -->\n", encoding="utf-8")
    texts = {r.by: r.text for r in parse_file(path, [], tmp_path)}
    assert texts["author"] == AUTHOR
    assert texts[WHO].startswith(f"Review by {WHO}: ")


def test_a_review_line_of_another_reviewer_is_not_the_marker_s_text(tmp_path):
    path = tmp_path / "T.md"
    path.write_text(f"# Reviews\n\n## Theorem 1\n\n{AUTHOR}\n\nReview by {WHO}: faithful (report "
                    f"`reports/x.json`).\n<!-- spec-review: {SPEC} {H} by=author -->\n",
                    encoding="utf-8")
    (r,) = parse_file(path, [], tmp_path)
    assert r.text == AUTHOR
