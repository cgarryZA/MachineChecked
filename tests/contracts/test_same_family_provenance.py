"""A model reviewer's declared family, before review and beside a promoted result (#613).
`review next` and `status` say once which declaration is in force and whether promotion's
same-family rule applies. A report the maintainer accepts over the rule keeps its declaration and
says so: in its record, in its `Review by` line, on the review records the assessment reads back,
in `check`, in the reader's review evidence and in the semantic summary, which counts it apart
from independent reviews. The three answers stay apart: an unknown family is never read as either
known one. The sites and evidence are synthetic; one test builds the toy paper."""

import json
from types import SimpleNamespace

import pytest

from prooflens import cli
from prooflens import export as ex
from prooflens import manifest as mf
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import semantic as sem
from prooflens.reviews import load_reviews
from test_read_context import work  # noqa: F401  (the site, as a fixture)
from test_structure_unit import hexes

MODEL = {"id": "llm:some-model", "kind": "model", "name": None, "model": "some-model",
         "identity": "self-declared"}


def model(family):
    return {**MODEL, "same_family_as_author": family}


HUMAN = {"id": "human:Ada", "kind": "human", "name": "Ada", "model": None,
         "same_family_as_author": "no", "identity": "self-declared"}


# -- before review ---------------------------------------------------------------------------

def run(capsys, *args):
    cli.main(["review", *args])
    return capsys.readouterr()


@pytest.mark.parametrize("who, family, rule, words", [
    ("llm:some-model", "unknown", "applies", "a model of unknown family (self-declared; "
                                             "--same-family yes|no|unknown declares it). "
                                             "`review promote` refuses"),
    ("llm:some-model", "yes", "applies", "a model of the same family as the statements' author "
                                         "(self-declared; --same-family"),
    ("llm:some-model", "no", "does not apply", "a model of a different family from the "
                                               "statements' author (self-declared): promotion's "
                                               "same-family rule does not apply"),
    ("human:Ada", "unknown", "does not apply", None),
])
def test_next_and_status_say_once_which_declaration_is_in_force(work, capsys, who, family,  # noqa: F811
                                                                 rule, words):
    flags = ["--as", who, "--same-family", family]
    plain = run(capsys, "next", "--as", "human:Someone-Else").out
    out = run(capsys, "next", *flags)
    # What scripts read is unchanged; the declaration is said once, apart from it.
    assert out.out == plain
    status = run(capsys, "status", *flags).out
    if words is None:
        assert "You review as" not in out.err + out.out + status
    else:
        assert out.err.count("You review as") == 1 and words in out.err
        assert "You review as" not in out.out
        assert status.count("You review as") == 1 and words in status
    for step in ("next", "status"):
        doc = json.loads(run(capsys, step, *flags, "--json").out)
        assert doc["reviewer"]["same_family_rule"] == rule
        assert doc["reviewer"]["same_family_as_author"] == (
            "no" if who.startswith("human") else family)


def test_the_three_answers_stay_apart():
    assert [rc.family_of(model(f)) for f in ("yes", "no", "unknown")] == ["yes", "no", "unknown"]
    # Anything else reads as unknown, never as a known answer; a person has no family.
    assert rc.family_of(model("maybe")) == rc.family_of(model(None)) == "unknown"
    assert rc.family_of(HUMAN) is None
    assert [rc.same_family_rule(x) for x in (model("yes"), model("unknown"), model("maybe"),
                                              model("no"), HUMAN)] == [True] * 3 + [False] * 2
    # The words are the reader's too.
    vocab = json.loads((rc.Path(rc.__file__).parent / "data/semantic.json").read_text())
    assert rc.FAMILY == {k: v["label"] for k, v in vocab["family"].items()}


# -- promotion --------------------------------------------------------------------------------

NAME = "Toy.other"
UNIT = {"id": f"def:{NAME}", "kind": "def", "name": NAME, "lean": [NAME], "claims": [],
        "papers": []}


def report(reviewer: dict) -> dict:
    return {"schema": "prooflens/review-report@1", "unit": dict(UNIT),
            "pins": {"release": "r1", "legacy_hash": hexes(NAME), "fingerprint": f"fp-{NAME}",
                     "fingerprints": None, "source_sha256": {}, "manuscripts": {}},
            "reviewer": reviewer,
            "reading": {"text": "A natural number, nothing more.",
                        "locked_at": "2026-01-01T10:00:00Z"},
            "comparison": {"text": "It matches.", "decided_at": "2026-01-01T10:05:00Z"},
            "verdict": {"group": "matches", "value": "faithful", "detail": ""},
            "author_review": {"shown_at": "2026-01-01T10:05:00Z", "disagreements": "none"},
            "submitted_at": "2026-01-01T10:06:00Z"}


BODY = {"lean": {"decls": {NAME: {"name": NAME, "kind": "def", "fingerprint": f"fp-{NAME}",
                                  "legacy_hash": hexes(NAME)}}},
        "inventory": {"claims": []}, "tex": {}, "provenance": {"papers": {}}}


def project(tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "definitions.md").write_text("# Definitions\n", encoding="utf-8")
    return SimpleNamespace(reviews=[tmp_path / "reviews"], ai_reviewers=[], root=tmp_path,
                           statement_authors=["statement-author"])


@pytest.mark.parametrize("family, words", [
    ("unknown", "a model of unknown family"),
    ("yes", "a model of the same family as the statements' author")])
def test_a_report_accepted_over_the_rule_says_so_and_keeps_its_declaration(tmp_path, family,
                                                                           words):
    cfg = project(tmp_path)
    r = report(model(family))
    assert any("same family" in w for w in pr.check_report(r, BODY, cfg, False))
    assert pr.check_report(r, BODY, cfg, True) == []
    accepted = pr.accept_family(r)
    assert accepted["promotion"] == {"same_family_accepted": True}
    assert accepted["reviewer"]["same_family_as_author"] == family
    (done,) = pr.apply(cfg, [(accepted, BODY["lean"]["decls"][NAME])])
    text = (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8")
    assert (f"Review by llm:some-model: faithful; {words}, accepted by the maintainer over the "
            "same-family rule (report `reports/") in text
    (record,) = (tmp_path / "reviews" / "reports").iterdir()
    kept = json.loads(record.read_text(encoding="utf-8"))
    assert kept["promotion"] == {"same_family_accepted": True}
    assert kept["reviewer"]["same_family_as_author"] == family
    assert ("same model family as the author: " + family
            + "; accepted by the maintainer over the same-family rule") in pr.report_text(kept)
    # The assessment reads the declaration back from the line.
    reviews, _ = load_reviews(cfg.reviews, [], tmp_path)
    (rv,) = [x for x in reviews if x.name == NAME]
    assert rv.accepted_family == family and rv.to_json()["accepted_family"] == family


@pytest.mark.parametrize("reviewer", [model("no"), HUMAN])
def test_a_report_the_rule_does_not_meet_is_promoted_as_before(tmp_path, reviewer):
    cfg = project(tmp_path)
    r = report(reviewer)
    assert pr.check_report(r, BODY, cfg, False) == []
    # The maintainer's flag changes nothing for it.
    assert pr.accept_family(r) is r
    pr.apply(cfg, [(r, BODY["lean"]["decls"][NAME])])
    text = (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8")
    assert f"Review by {reviewer['id']}: faithful (report `reports/" in text
    assert "accepted by the maintainer" not in text
    reviews, _ = load_reviews(cfg.reviews, [], tmp_path)
    (rv,) = [x for x in reviews if x.name == NAME]
    assert rv.accepted_family is None and "accepted_family" not in rv.to_json()


def test_only_the_reviewer_s_own_line_gives_its_declaration(tmp_path):
    (tmp_path / "r.md").write_text(
        "# Other\n\nReview by llm:other: faithful; a model of unknown family, accepted by the "
        "maintainer over the same-family rule (report `reports/a.json`).\n"
        f"<!-- def-review: Toy.a {hexes('Toy.a')} by=llm:other -->\n\n# Mine\n\n"
        "Review by human:Ada: faithful (report `reports/b.json`).\n"
        f"<!-- def-review: Toy.b {hexes('Toy.b')} by=human:Ada -->\n", encoding="utf-8")
    reviews, _ = load_reviews([tmp_path / "r.md"], [], tmp_path)
    assert {r.name: r.accepted_family for r in reviews} == {"Toy.a": "unknown", "Toy.b": None}


# -- what the assessment's records show -----------------------------------------------------

def clause(*families):
    """A clause whose proposition's review and definitions' reviews rest on reviewers of these
    accepted families (None: not accepted over the rule)."""
    def rec(f):
        return {"state": "reviewed", "current": [], **({"accepted_family": f} if f else {})}
    return {"name": "main", "spec": "S.p", "state": "proved", "review": "reviewed",
            "checks": {}, "spec_review": rec(families[0]),
            "def_reviews": {f"S.d{i}": rec(f) for i, f in enumerate(families[1:])}}


@pytest.mark.parametrize("families, key, evidence", [
    ((None, None), "independent", None),
    (("unknown", None), "unknown_family", "unknown"),
    ((None, "yes", "unknown"), "same_family", "yes"),
])
def test_a_claim_s_review_is_as_independent_as_the_least_of_its_reviews(families, key,
                                                                        evidence):
    cl = clause(*families)
    assert sem.review_state({"clauses": [cl]}, "statements") == key
    ev = mf.clause_evidence(cl, None, None, None)["review"]
    assert ev == {"state": "reviewed", **({"accepted_family": evidence} if evidence else {})}


@pytest.mark.parametrize("reviewers, key", [
    ([HUMAN, model("unknown")], "independent"),
    ([model("no")], "independent"),
    ([model("yes"), model("unknown")], "unknown_family"),
    ([model("yes")], "same_family"),
    ([model("maybe")], "unknown_family"),
])
def test_zero_configuration_counts_a_model_s_report_by_its_declaration(reviewers, key):
    chunk = {"reviews": [{"reviewer": rv, "current": True, "revealed": [],
                          "submitted_at": f"2026-01-0{i + 1}"} for i, rv in enumerate(reviewers)]}
    assert sem.review_state(chunk, "statements") == key


def test_the_summary_has_words_for_each_key():
    for k in sem.REVIEW_KEYS:
        assert sem.VOCABULARY["review"][k]["label"]
    assert "unknown" in sem.VOCABULARY["review"]["unknown_family"]["label"]


def test_the_export_and_check_carry_the_declaration():
    rec = {"target": "def", "name": NAME, "hash": "h", "by": "llm:some-model", "kind": "unknown",
           "provenance": "self-declared", "accepted_family": "unknown", "text": "t"}
    out = ex._reviews({"state": "reviewed", "current": [rec], "stale": []}, False)
    assert out["current"][0]["accepted_family"] == "unknown"
    lines = cli._simple_claim_lines({
        "id": "P:thm:a", "number": "Theorem 1", "status": "linked", "links": [],
        "reviews": [{"reviewer": model("unknown"), "verdict": {"value": "faithful"},
                     "current": True},
                    {"reviewer": HUMAN, "verdict": {"value": "faithful"}, "current": False}]})
    assert "  review by llm:some-model (a model of unknown family, self-declared): faithful" \
        in lines
    assert "  review by human:Ada: faithful (not current)" in lines


# -- end to end, on the toy paper -------------------------------------------------------------

from conftest import build, needs_lean, needs_tex  # noqa: E402


@needs_lean
@needs_tex
def test_the_toy_s_review_accepted_over_the_rule_is_shown_apart(toy, tmp_path, capsys):
    from prooflens.pipeline import reassess
    from test_promote import queue, report as toy_report
    index, _, cfg = build(toy)
    units = {u["name"]: u for u in queue(cfg)["units"]}
    names = ["Toy.PaperSpec.thm_triangle", "Toy.triangle", "Toy.triangle._f",
             "Toy.triangle.match_1"]
    reports = [toy_report(index, units[n]) for n in names]
    # The proposition's review is by a model of unknown family.
    reports[0]["reviewer"] = {"id": "llm:some-model", "kind": "model", "model": "some-model",
                              "same_family_as_author": "unknown", "identity": "self-declared"}
    (_, _, why), = pr.plan(cfg, reports[:1])
    assert any("same family" in w for w in why)
    steps = pr.plan(cfg, reports, accept_same_family=True)
    assert all(not why for _, _, why in steps)
    assert steps[0][0]["promotion"] == {"same_family_accepted": True}
    assert all("promotion" not in r for r, _, _ in steps[1:])
    pr.apply(cfg, [(r, cur) for r, cur, _ in steps])
    res = reassess(cfg, log=lambda *a: None)
    (c,) = [c for c in res["index"]["claims"] if c["id"] == "T:thm:triangle"]
    # The status counts it as a review, as before; the summary counts it apart.
    assert c["status"] == "formal: accepted"
    assert c["semantic"]["review"] == "unknown_family"
    ch = json.loads((cfg.out_dir / "site/data/claims" / c["file"]).read_text())
    (cl,) = ch["clauses"]
    assert cl["spec_review"]["accepted_family"] == "unknown"
    assert cl["evidence"]["review"] == {"state": "reviewed", "accepted_family": "unknown"}
    assert cli._family_accepted(cfg, res["evidence"]) == [
        {"target": "spec", "name": "Toy.PaperSpec.thm_triangle", "by": "llm:some-model",
         "family": "unknown"}]
