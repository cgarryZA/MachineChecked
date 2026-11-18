"""Before the verdict a reviewer is not shown the outcome the author gives a locked proposition
(#758): the theorems that prove, refute or witness it, the author's names for its clauses, the
kind and reason of a correction, the state each clause is assessed in. Steps 1 and 2 (`read`,
`lock`, `show`, in text and JSON) name a clause by its place among its claim's clauses, and say
that a correction is one, with the place of the printed clause it corrects; step 3 (`author`)
gives the author's account. The same holds for a project's own build, a snapshot sent as a file
and the snapshot a project keeps. Nothing here builds Lean."""

import json
import shutil
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import compare as cmp
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from prooflens import review_snapshot as rs
from test_compare import seg, statement, write_site

SPEC = "Syn.PaperSpec.p"
FIXED_SPEC = "Syn.PaperSpec.p_pos"
REFUTE = "Syn.Acceptance.p_false"
ACCEPT = "Syn.Acceptance.p_pos"
WITNESS = "Syn.Acceptance.p_pos_hypotheses"
PRINTED = "as printed, under the author's disputed reading"
FIXED = "corrected: the author's added hypothesis"
REASON = "AUTHOR-REASON: the printed claim fails at n = 0."
EXPECTED = "AUTHOR-EXPECTATION: the counterexample is n = 0."
MARKER = "AUTHOR-MARKER: the proposition states the claim as printed."
# What steps 1 and 2 never show, and step 3 does.
OUTCOME = (REFUTE, ACCEPT, WITNESS, PRINTED, FIXED, REASON, EXPECTED, MARKER)
UNIT, FIXED_UNIT = f"spec:{SPEC}", f"spec:{FIXED_SPEC}"
WHO = ["--as", "human:Blind-Referee"]
TEXTS = {"reading.md": "For every natural number n the synthetic property holds, with no "
                       "condition on n.",
         "comparison.md": "The proposition states the property for every n, as printed.",
         "none.md": "none"}


def clause(name, spec, text, state, checks, **more):
    """A clause of a claim's record as the build writes it (`manifest.build`)."""
    return {"name": name, "label": name, "spec": spec,
            "statement": {**statement(text), "fingerprint": f"fp-{spec}",
                          "legacy_hash": "0" * 32},
            "checks": {"spec": {"ok": True, "errors": []}, **checks}, "state": state,
            "review": "pending", "def_reviews": {},
            "spec_review": {"state": "pending", "source_sha256": {"S:prop:p": "sha-p"},
                            "current": [{"by": "author", "text": MARKER, "file": "reviews/S.md",
                                         "line": 3}]},
            **more}


def write_spec_site(tmp: Path) -> Path:
    """A synthetic full assessment: Proposition 1 printed false, refuted, beside a proved
    correction of it with a witness, and its review queue as the build writes it."""
    data = tmp / "work" / "site" / "data"
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    ok = {"ok": True, "errors": [], "axioms": ["propext"], "sorry": False}
    printed = clause(PRINTED, SPEC, "Syn.P n", "refuted", {"refute": ok},
                     refute=REFUTE, refute_ok=True, expect="refute", expect_reason=EXPECTED,
                     refutation_does_not_cover=["the reading with the constant chosen after n"],
                     proofs={"refute": {"name": REFUTE, "module": "Syn.Acceptance", **ok}})
    fixed = clause(FIXED, FIXED_SPEC, "0 < n → Syn.P n", "proved",
                   {"accept": ok, "witness": {**ok, "type": None}},
                   accept=ACCEPT, accept_ok=True, witness=WITNESS, corrects=PRINTED,
                   corrects_label=PRINTED, kind="added-hypothesis", reason=REASON,
                   proofs={"accept": {"name": ACCEPT, "module": "Syn.Acceptance", **ok}},
                   witness_record={"type": seg("0 < 1 ∧ Syn.P 1")})
    ch = {"id": "S:prop:p", "key": "prop:p", "paper": "S", "number": "Proposition 1",
          "kind": "proposition", "heading": None, "location": "main.tex",
          "anchor": {"kind": "exact", "file": "main.tex", "line": 12, "label": "prop:p",
                     "begin": [1, 0, 0], "end": [1, 0, 1],
                     "statement": "\\label{prop:p} For every $n$, $P(n)$ holds."},
          "statement_tex": "\\label{prop:p} For every $n$, $P(n)$ holds.",
          "source_sha256": "sha-p", "status": "refuted as printed; corrected statement proved",
          "status_code": "formal.refuted", "class": "refuted", "links": [], "suggestions": [],
          "clauses": [printed, fixed], "decls": {}, "findings": [], "blockers": [],
          "reviews": [], "symbols": []}
    (data / "claims" / "S_prop_p.json").write_text(json.dumps(ch))
    index = {"schema": "prooflens/manifest@1", "mode": "assurance", "release": "v-synthetic",
             "evidence": "e" * 64, "project": {"name": "syn", "commit": "c" * 40},
             "papers": [{"id": "S", "title": "Synthetic", "revision": "c" * 40}],
             "claims": [{"id": "S:prop:p", "paper": "S", "number": "Proposition 1",
                         "title": "", "file": "S_prop_p.json", "status": ch["status"],
                         "class": "refuted", "kind": "proposition"}]}
    (data / "index.json").write_text(json.dumps(index))
    queue = rq.assurance_queue(index, {"S_prop_p.json": ch}, {}, ["author"])
    (data / "review-queue.json").write_text(json.dumps(queue))
    return data


def step(capsys, *args):
    cli.main(["review", *args, *WHO])
    return capsys.readouterr()


@pytest.fixture(params=["build", "snapshot", "kept snapshot"])
def surface(request, tmp_path, monkeypatch, capsys):
    """Where the review steps run, and what they are given: the project's own build, a
    snapshot sent as a file (`--snapshot`), or the snapshot a project keeps, in a clone."""
    data = write_spec_site(tmp_path)
    texts = tmp_path / "texts"
    texts.mkdir()
    for name, text in TEXTS.items():
        (texts / name).write_text(text)
    if request.param == "snapshot":
        rs.pack(data, tmp_path / "review-snapshot.zip")
        (tmp_path / "reviewer").mkdir()
        monkeypatch.chdir(tmp_path / "reviewer")
        return texts, ["--snapshot", str(tmp_path / "review-snapshot.zip")]
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "syn"\n')
    shutil.move(data.parent.parent, root / ".machinechecked")
    monkeypatch.chdir(root)
    if request.param == "kept snapshot":
        cli.main(["review", "pack"])
        capsys.readouterr()
        clone = tmp_path / "clone"
        shutil.copytree(root, clone, ignore=shutil.ignore_patterns(".machinechecked"))
        monkeypatch.chdir(clone)
    return texts, []


def withheld(text: str) -> None:
    for x in OUTCOME:
        assert x not in text, f"{x!r} is shown before the verdict"
    for word in ('"refuted"', '"proved"', '"added-hypothesis"'):
        assert word not in text, f"{word} is shown before the verdict"


def test_the_outcome_is_withheld_until_the_verdict_on_every_surface(surface, capsys):
    texts, snap = surface
    for uid in (UNIT, FIXED_UNIT):
        shown = [step(capsys, "read", uid, "--json", *snap).out, step(capsys, "read", uid, *snap).out]
        step(capsys, "lock", uid, str(texts / "reading.md"), *snap)
        shown += [step(capsys, "show", uid, "--json", *snap).out,
                  step(capsys, "show", uid, *snap).out,
                  step(capsys, "show", uid, "--definitions", *snap).out]
        for text in shown:
            withheld(text)
        pk = json.loads(shown[2])
        d, = pk["lean"]["declarations"]
        # The statement as Lean gives it, named by its place among its claim's clauses, with
        # the check of the proposition itself and nothing of its proofs.
        assert set(d) <= {"id", "name", "role", "position", "statement", "lean",
                          "correction"}, sorted(d)
        assert d["name"] == uid.split(":", 1)[1] and d["statement"]["text"]
        assert set(d["lean"]) == {"spec"}
        assert "outcome" in [w["section"] for w in pk["retrieval"]["withheld"]]
        assert "not shown at this stage: outcome" in shown[3]
        if uid == UNIT:
            assert d["position"] == {"claim": "S:prop:p", "clause": 1}
            assert "correction" not in d and "correction" not in pk["unit"]
        else:
            # A declared correction says so, and which printed clause, by its place.
            assert d["position"] == {"claim": "S:prop:p", "clause": 2}
            assert d["correction"] == pk["unit"]["correction"] == {
                "relation": "corrects", "of_clause": {"claim": "S:prop:p", "clause": 1}}
            assert ("This proposition is a correction of the printed clause 1 of S:prop:p. "
                    "Compare it with the passage") in shown[3]
        step(capsys, "decide", uid, "faithful to the correction" if uid == FIXED_UNIT
             else "faithful", str(texts / "comparison.md"), *snap)
        # After the verdict: the author's account, in JSON and in text.
        after = json.loads(step(capsys, "author", uid, "--json", *snap).out)
        d, = after["lean"]["declarations"]
        (acc,) = after["interpretations"]["account"]
        text = step(capsys, "author", uid, *snap).out
        assert MARKER in text and "The author's account of this proposition, for S:prop:p" in text
        if uid == UNIT:
            assert (d["clause"], d["refute"], d["accept"]) == (PRINTED, REFUTE, None)
            assert acc["lines"] == [f"clause 1 of S:prop:p, “{PRINTED}”: refuted",
                                    f"  refutation: {REFUTE}",
                                    f"  the author expects it to be refuted: {EXPECTED}"]
            assert f"refutation: {REFUTE}" in text
            assert "Scope of the refutation of S:prop:p" in text
        else:
            assert (d["clause"], d["accept"], d["witness"], d["corrects"], d["kind"]) == (
                FIXED, ACCEPT, WITNESS, PRINTED, "added-hypothesis")
            assert after["unit"]["correction"]["of"] == PRINTED
            assert after["unit"]["correction"]["reason"] == REASON
            assert acc["lines"] == [f"clause 2 of S:prop:p, “{FIXED}”: proved",
                                    f"  corrects clause 1, “{PRINTED}”, with an added hypothesis",
                                    f"  the reason given: {REASON}", f"  proof: {ACCEPT}",
                                    f"  witness: {WITNESS}"]
            assert f"witness: {WITNESS}" in text and REASON in text


def test_refutation_not_valid_is_offered_for_every_locked_proposition(tmp_path):
    """Whether a proposition is refuted is shown only after the verdict, so the verdict that a
    refutation would not refute the printed claim is not refused for one that is not refuted:
    the refusal would say which is. It stays a verdict on a locked proposition only."""
    work = write_spec_site(tmp_path).parent.parent
    for uid in (UNIT, FIXED_UNIT):
        s = rc.Session(work, rc.parse_reviewer(f"human:Referee-{uid[-1]}"))
        s.read(uid)
        s.lock(uid, TEXTS["reading.md"])
        s.show(uid)
        s.decide(uid, "refutation not valid", "Item by item.",
                 detail="A refutation of it would not refute the printed claim.")
        assert s.work["drafts"][uid]["verdict"] == "refutation not valid"
    link = write_site(tmp_path / "links").parent.parent
    s = rc.Session(link, rc.parse_reviewer("human:Referee"))
    s.read("link:thm:t0")
    s.lock("link:thm:t0", TEXTS["reading.md"])
    with pytest.raises(rc.ReviewError, match="only to a locked proposition"):
        s.decide("link:thm:t0", "refutation not valid", "Item by item.", detail="x")


def test_a_claim_packet_before_the_verdict_names_clauses_by_their_place(tmp_path):
    """`compare --stage compare` is the comparison independent review is given before its
    verdict: every clause of the claim, each named by its place, and no outcome."""
    site = cmp.Site(write_spec_site(tmp_path))
    pk = cmp.claim_packet(site, "Proposition 1", "compare")
    withheld(json.dumps(pk, ensure_ascii=False))
    withheld(cmp.packet_text(pk))
    assert [(d["name"], d["position"]["clause"], d.get("correction"))
            for d in pk["lean"]["declarations"]] == [
        (SPEC, 1, None),
        (FIXED_SPEC, 2, {"relation": "corrects", "of_clause": {"claim": "S:prop:p", "clause": 1}})]
    full = cmp.claim_packet(site, "Proposition 1")
    assert [(d["clause"], d["refute"], d["accept"]) for d in full["lean"]["declarations"]] == [
        (PRINTED, REFUTE, None), (FIXED, None, ACCEPT)]
    assert "outcome" not in [w["section"] for w in full["retrieval"]["withheld"]]


def test_a_queue_without_the_printed_clauses_place_names_none(tmp_path):
    """A queue written before it named a corrected clause by its place: the packet takes the
    place from the claim's record, and never the author's name for it."""
    data = write_spec_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text())
    for u in q["units"]:
        if u.get("correction"):
            u["correction"].pop("of_clause")
    (data / "review-queue.json").write_text(json.dumps(q))
    s = rc.Session(data.parent.parent, rc.parse_reviewer("human:Referee"))
    s.read(FIXED_UNIT)
    s.lock(FIXED_UNIT, TEXTS["reading.md"])
    pk = s.show(FIXED_UNIT, as_json=True)
    assert pk["unit"]["correction"] == {"relation": "corrects",
                                        "of_clause": {"claim": "S:prop:p", "clause": 1}}
    withheld(json.dumps(pk, ensure_ascii=False))
