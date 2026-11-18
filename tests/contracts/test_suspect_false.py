"""A broader statement its reviewer suspects false (#637): `review decide` takes the reason or a
counterexample with a broader verdict on a statement (`--suspect-false FILE`, `suspect_false` in
a manifest and from the review page), the report records it and groups the verdict apart from
the matches, its issue draft says so, Undo gives it back, and the reader, the claim's lines and
promotion's `Review by` line name it "broader, suspected false". Another verdict, a definition
or an empty reason is refused, and nothing is recorded.

The site is the synthetic zero-configuration build of `test_compare.write_site`, with one more
unit copied from its first. Nothing here builds Lean."""

import copy
import json

import pytest

from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import simple
from prooflens import workspace as wsp
from test_compare import write_site

UNIT = "link:thm:t0"
OTHER = "link:thm:other"
WHO = "human:Suspecting-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
WHY = "For a function that is not measurable the lower integral can exceed 1."
DETAIL = "Restrict to measurable functions to recover the printed claim."


@pytest.fixture
def work(tmp_path, monkeypatch):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text(encoding="utf-8"))
    u = copy.deepcopy(q["units"][0])
    u["id"] = OTHER
    q["units"].append(u)
    (data / "review-queue.json").write_text(json.dumps(q), encoding="utf-8")
    work = data.parent.parent
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    return work


def run(capsys, *args, code=None):
    """What the command prints on standard output (one JSON document with --json), after
    checking how it exited."""
    if code is None:
        cli.main(["review", *args, "--as", WHO])
    else:
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args, "--as", WHO])
        assert e.value.code == code
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in args else out


def texts(tmp_path) -> dict:
    files = {"reading": READING, "cmp": "Item by item: Lean drops the measurability.",
             "none": "none", "detail": DETAIL, "why": WHY, "empty": "  \n"}
    for name, text in files.items():
        (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")
    return {name: str(tmp_path / f"{name}.md") for name in files}


def session(work):
    return rc.Session(work, rc.parse_reviewer(WHO))


def to_compare(work, uid=UNIT):
    s = session(work)
    s.read(uid)
    s.lock(uid, READING)
    s.show(uid)


def test_a_suspected_broader_statement_is_grouped_apart_from_the_matches(work, tmp_path,
                                                                          capsys):
    f = texts(tmp_path)
    to_compare(work)
    doc = run(capsys, "decide", UNIT, "broader", f["cmp"], "--detail", f["detail"],
              "--suspect-false", f["why"], "--json")
    assert (doc["verdict"], doc["group"], doc["suspect_false"]) == ("broader", "suspect", WHY)
    assert "broader, suspected false, grouped apart from the matches" in doc["message"]
    d = session(work).work["drafts"][UNIT]
    # The draft keeps the verdict's own group; the report's is `suspect`.
    assert (d["group"], d["suspect_false"]) == ("matches", WHY)
    session(work).author(UNIT)
    said = run(capsys, "submit", UNIT, f["none"])
    assert f"report recorded: {UNIT}, broader, suspected false;" in said
    r, = session(work).work["reports"]
    assert r["verdict"] == {"group": "suspect", "value": "broader", "detail": DETAIL,
                            "suspect_false": WHY}
    u = session(work).unit(UNIT)
    assert r["issue_draft"] == rc.issue_draft(u, "broader", DETAIL, r["correspondence"], WHY)
    assert r["issue_draft"]["kind"] == "explanatory note"
    assert r["issue_draft"]["title"].startswith(f"{u['name']}: broader, suspected false (Theorem 0")
    assert r["issue_draft"]["body"].endswith(f"{DETAIL}\n\n**Suspected false.** {WHY}")
    assert rc.SUSPECT_BODY in r["issue_draft"]["body"]
    # Undo gives back the draft with its suspicion, and the report saved again is the same.
    back = session(work).undo()
    assert (back["group"], back["suspect_false"]) == ("matches", WHY)
    again = session(work).submit(UNIT, "none")
    assert again["verdict"] == r["verdict"]


def test_the_suspicion_goes_with_a_broader_verdict_on_a_statement_and_says_why(work, tmp_path,
                                                                               capsys):
    f = texts(tmp_path)
    to_compare(work)
    for verdict, extra, said in (
            ("faithful", [], "goes with a broader verdict, not 'faithful'"),
            ("broader", ["--detail", f["detail"]], "say why you suspect the broader statement")):
        why = f["empty"] if verdict == "broader" else f["why"]
        doc = run(capsys, "decide", UNIT, verdict, f["cmp"], *extra, "--suspect-false", why,
                  "--json", code=2)
        assert doc["ok"] is False and doc["error"]["kind"] == "invalid", doc
        assert said in doc["error"]["message"]
        # Nothing is recorded: the unit is still at step 2.
        assert session(work).work["drafts"][UNIT]["stage"] == "compare"
    # A definition states nothing that can be false; a proof step has no broader verdict.
    assert rc.suspicion({"kind": "def"}, "broader", WHY) == (None, [
        "a definition states nothing that can be false: the suspicion goes with a broader "
        "statement"])
    assert rc.suspicion({"kind": "spec"}, "broader", WHY) == (WHY, [])
    assert rc.suspicion({"kind": "link"}, "broader", None) == (None, [])
    # Without it, a broader verdict is a match, as before.
    run(capsys, "decide", UNIT, "broader", f["cmp"], "--detail", f["detail"])
    d = session(work).work["drafts"][UNIT]
    assert d["group"] == "matches" and "suspect_false" not in d
    assert rc.report_group(d) == "matches"


def test_a_manifest_and_the_review_page_record_it_too(work, tmp_path, capsys):
    f = texts(tmp_path)
    to_compare(work)
    (tmp_path / "d.json").write_text(json.dumps([
        {"unit": UNIT, "verdict": "broader", "comparison_file": "cmp.md",
         "detail_file": "detail.md", "suspect_false_file": "why.md"}]), encoding="utf-8")
    doc = run(capsys, "decide", "--manifest", str(tmp_path / "d.json"), "--json")
    entry, = doc["entries"]
    assert (entry["group"], entry["suspect_false"]) == ("suspect", WHY), entry
    # The review page under `machinechecked view`: what it types is saved at step 2, and its
    # verdict records the suspicion through the same service.
    gets, posts = wsp.api(work, work / "site" / "data")
    page = posts["/api/review"]
    page({"reviewer": WHO, "action": "begin", "unit": OTHER})
    page({"reviewer": WHO, "action": "lock", "unit": OTHER, "reading": READING})
    st = page({"reviewer": WHO, "action": "edit", "unit": OTHER, "stage": "compare",
               "fields": {"verdict": "broader", "suspect_false": WHY[:10]}})
    assert "suspect_false" in st["editable"]["compare"]
    assert st["drafts"][OTHER]["suspect_false"] == WHY[:10]
    st = page({"reviewer": WHO, "action": "decide", "unit": OTHER, "verdict": "broader",
               "comparison": "c", "detail": DETAIL, "suspect_false": WHY, "show_author": True})
    assert st["drafts"][OTHER]["suspect_false"] == WHY
    st = page({"reviewer": WHO, "action": "submit", "unit": OTHER, "disagreements": "none"})
    assert st["report"]["verdict"]["group"] == "suspect"


def test_decide_s_help_names_it_under_broader(capsys):
    with pytest.raises(SystemExit):
        cli.main(["review", "decide", "--help"])
    out = capsys.readouterr().out
    assert "--suspect-\n" not in out and "--suspect-false FILE, for a" in out, \
        "the option is not split across lines"
    text = " ".join(out.split())
    assert ("broader State the instantiation that gives the printed claim. With --suspect-false "
            "FILE, for a statement: you suspect the broader statement false, and FILE says why; "
            "the report groups the verdict apart from the matches.") in text


def test_the_reader_and_promotion_name_it(work):
    to_compare(work)
    s = session(work)
    s.decide(UNIT, "broader", "c", DETAIL, suspect_false=WHY)
    s.author(UNIT)
    r = s.submit(UNIT, "none")
    # The claim's page in zero configuration, and the claim's lines of `check`.
    view = simple.review_view(r, [], {"id": r["unit"]["claims"][0]})
    assert view["verdict"] == {"group": "suspect", "value": "broader", "detail": DETAIL,
                               "suspect_false": WHY}
    assert simple.uncounted_view(r)["verdict"]["suspect_false"] == WHY
    assert "suspect_false" not in simple.review_view(
        {**r, "verdict": {"group": "matches", "value": "broader", "detail": DETAIL}}, [],
        {"id": "x"})["verdict"]
    assert rc.verdict_words(r["verdict"]) == "broader, suspected false"
    assert rc.verdict_words({"value": "broader"}) == "broader"
    # Promotion's line, which the reader shows as the review's text, and its text block.
    line = pr.review_by_line(r, r["unit"]["name"], "reports/r.json")
    assert line == f"Review by {WHO}: broader, suspected false (report `reports/r.json`)."
    from prooflens.reviews import PROMOTED
    assert PROMOTED.fullmatch(line)
    block = pr.report_text(r, {"legacy_hash": "0" * 32})
    assert f"Verdict: broader — {DETAIL}\nSuspected false: {WHY}\n" in block
