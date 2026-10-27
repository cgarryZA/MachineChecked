"""The review queue's investigation order (#128): changed evidence first, then the open questions,
differences and hints the auditors' workspaces record (only when the reviewer asks for that
order, which is recorded as exposure), with use in another claim's proof as a further signal.
Each unit says why it comes where it does; without a record the queue's order stands.

Every test here is synthetic: two releases' evidence records, a reverse-reference index and a
small site, so none runs Lean."""

import json

import pytest

from prooflens import changes as chg
from prooflens import cli
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from prooflens import workspace as wsp

H = {k: k * 64 for k in "abcdef"}
AUDITOR = rc.parse_reviewer("human:A-Auditor")
REFEREE = rc.parse_reviewer("human:B-Referee")


def unit(uid, claims, state="pending", reason="Short statement", **kw):
    kind, _, name = uid.partition(":")
    return {"id": uid, "kind": kind, "name": name, "state": state, "reason": reason,
            "claims": [{"id": c, **({"number": n} if n else {})} for c, n in claims],
            "reveals": {"lean": [], "author": []}, "author_review": [], **kw}


def queue(units, mode="assurance"):
    return {"schema": rq.SCHEMA, "release": "r-2", "mode": mode, "authors": [],
            "units": units, "needs_statement": []}


def ids(units):
    return [u["id"] for u in units]


# -- two releases, compared by changes.py --------------------------------------------------------

def region(sha, start):
    return {"file": "p.tex", "start_line": start, "end_line": start, "start_column": 1,
            "end_column": 9, "kind": "line", "scheme": "tex-region-v1", "sha256": sha}


def claim(cid, number, sha, start, spec):
    return {"id": cid, "paper": "P", "number": number, "kind": "theorem", "scope": "formal",
            "location": f"p.tex:{start}", "source_hash_scheme": "tex-region-v1",
            "source_sha256": sha, "source_line_sha256": [sha],
            "clauses": [{"name": "statement", "spec": spec}]}


def marker(name, fp, cid, sha, target):
    return {"by": "a.referee", "kind": "human", "provenance": "self-declared",
            "file": "reviews.md", "line": 3, "hash": fp, "name": name, "target": target,
            "source": {cid: sha}, "text": "A reading."}


def rv(state, current=None, why=None):
    out = {"state": state, "current": [current] if current else [], "stale": [],
           "source_sha256": {}}
    if why:
        out["why"] = why
    return out


def decl(name, fp, text):
    return {"name": name, "kind": "def", "fingerprint": fp, "legacy_hash": fp[-8:],
            "signature": {"text": "Nat → Prop"}, "value": {"text": text}}


def record(eid, claims, assessed, decls, specs, regions, lean_inputs):
    return {"id": eid, "created": "2026-10-21T00:00:00+00:00", "body": {
        "inventory": {"claims": claims},
        "assessment": {"claims": assessed, "findings": [], "gates": {}},
        "lean": {"decls": {d["name"]: d for d in decls}, "specs": specs, "defs": {}},
        "tex": {"P": {"mode": "latex", "regions": regions, "anchors": []}},
        "provenance": {"project": {"commit": "c1", "dirty": False},
                       "lean_inputs_sha256": lean_inputs,
                       "papers": {"P": {"revision": "r1", "mode": "latex"}}}}}


MAIN, TWO, THREE, DEF = "Ex.Spec.main", "Ex.Spec.two", "Ex.Spec.three", "Ex.Bounded"


def comparison():
    """Theorem 1's proposition uses a definition whose value changes, so its definition review
    is reopened; Theorem 2's passage is edited, with no review to reopen; Lemma 3 is unchanged."""
    specs = {MAIN: {"fingerprint": "fp:main", "closure": [DEF], "exact": {"text": "∀ m, B m"}},
             TWO: {"fingerprint": "fp:two", "closure": [], "exact": {"text": "T"}},
             THREE: {"fingerprint": "fp:three", "closure": [], "exact": {"text": "L"}}}
    spec_m = marker(MAIN, "fp:main", "P:main", H["a"], "spec")
    def_m = marker(DEF, "fp:def-1", "P:main", H["a"], "def")

    def assessed(def_review):
        return [{"id": "P:main", "status": "s", "status_code": "formal.accepted", "clauses": [
                    {"name": "statement", "spec": MAIN, "spec_review": rv("reviewed", spec_m),
                     "def_reviews": {DEF: def_review}}]},
                *({"id": cid, "status": "s", "status_code": "formal.review-pending",
                   "clauses": [{"name": "statement", "spec": spec, "spec_review": rv("pending"),
                                "def_reviews": {}}]}
                  for cid, spec in (("P:two", TWO), ("P:three", THREE)))]

    def claims(two_sha):
        return [claim("P:main", "Theorem 1", H["a"], 1, MAIN),
                claim("P:two", "Theorem 2", two_sha, 5, TWO),
                claim("P:three", "Lemma 3", H["c"], 9, THREE)]

    stale = rv("stale", None, "declaration")
    stale["stale"] = [def_m]
    lean = [decl(n, "fp:" + n, "x") for n in (MAIN, TWO, THREE)]
    old = record("e1", claims(H["b"]), assessed(rv("reviewed", def_m)),
                 lean + [decl(DEF, "fp:def-1", "fun m => m + 5")], specs,
                 {"P:main": region(H["a"], 1), "P:two": region(H["b"], 5),
                  "P:three": region(H["c"], 9)}, "l1")
    new = record("e2", claims(H["d"]), assessed(stale),
                 lean + [decl(DEF, "fp:def-2", "fun m => m + 4")], specs,
                 {"P:main": region(H["a"], 1), "P:two": region(H["d"], 5),
                  "P:three": region(H["c"], 9)}, "l2")
    return chg.compare(old, "r-1", new, "r-2")


def assurance_units():
    """The queue's order before prioritising: less effort first, revealed units first."""
    return [unit("spec:" + THREE, [("P:three", "Lemma 3")]),
            unit("def:Ex.g", [("P:two", None)], reason="Short definition; used by 1 claim(s)"),
            unit("spec:" + TWO, [("P:two", "Theorem 2")], reveals={"lean": ["def:Ex.g"],
                                                                   "author": []}),
            unit("def:" + DEF, [("P:main", None)], reason="Short definition; used by 1 claim(s)",
                 source_sha256={"P:main": H["a"]}),
            unit("spec:" + MAIN, [("P:main", "Theorem 1")], state="reviewed")]


# -- without records -------------------------------------------------------------------------

def test_without_records_the_queue_keeps_its_order_and_reasons():
    units = assurance_units()
    for mode in ("assurance", "simple"):
        q = queue(units, mode)
        out = rq.prioritise(q)
        assert ids(out["units"]) == ids(units)
        assert [u["reason"] for u in out["units"]] == [u["reason"] for u in units]
        assert all(u["priority"]["signals"] == [] for u in out["units"])
        assert out["order"]["by"] == "effort"
        # A missing record is said to be missing, with why: never read as "nothing changed".
        for s in out["order"]["signals"].values():
            assert s["state"] == "not available" and s["why"]
        assert q["units"] == units  # the queue given is not changed
    # Records that say nothing about any unit leave the order as it was too.
    empty = {"from": {"release": "r-1"}, "to": {"release": "r-2"}, "claims": [],
             "declarations": []}
    out = rq.prioritise(queue(units), changes=empty, uses={"by_name": {}})
    assert ids(out["units"]) == ids(units) and out["order"]["by"] == "effort"
    assert out["order"]["signals"]["changes"] == {"state": "read", "from": "r-1", "to": "r-2"}


# -- changes since the last release ----------------------------------------------------------

def test_a_reopened_review_comes_first_then_a_changed_passage_with_its_reason():
    doc = comparison()
    out = rq.prioritise(queue(assurance_units()), changes=doc)
    units = {u["id"]: u for u in out["units"]}
    # The reopened definition review, then the changed statement (the definition its review
    # shows coming just before it), then the unchanged one; the reviewed unit stays last.
    assert ids(out["units"]) == ["def:" + DEF, "def:Ex.g", "spec:" + TWO, "spec:" + THREE,
                                 "spec:" + MAIN]
    d = units["def:" + DEF]
    assert d["reason"] == ("Reopened since the last release: this definition's Lean changed; "
                           "short definition; used by 1 claim(s)")
    assert d["priority"]["tier"] == "reopened"
    sig, = d["priority"]["signals"]
    assert sig["claims"] == ["P:main"]
    # The question a new reading answers, as the comparison asks it.
    assert sig["questions"] == [f"Does {DEF} still mean what Theorem 1 (P:main) needs, now "
                                "that its definition has changed?"]
    assert units["spec:" + TWO]["reason"] == ("Changed since the last release: the passage of "
                                              "Theorem 2; short statement")
    assert units["def:Ex.g"]["reason"] == ("Comes before the review of Theorem 2, which shows "
                                           "its Lean; short definition; used by 1 claim(s)")
    assert units["spec:" + THREE]["reason"] == "Short statement"
    assert units["spec:" + MAIN]["reason"] == "Short statement"
    # The words are read before the Lean is shown: they name claims, never a declaration.
    assert not any("Ex." in u["reason"] for u in out["units"])
    assert out["order"]["by"] == "priority"
    # The same records give the same order.
    assert rq.prioritise(queue(assurance_units()), changes=doc) == out


def definition_edit(fingerprint: str, source: str) -> dict:
    """Theorem 1's proposition uses a definition, and no review of either is current. In the
    later build the definition has `fingerprint` (its statement and value, proofs erased) and
    the digest `source` of its authored source; in the earlier one `fp:def-1` and `src-1`."""
    specs = {MAIN: {"fingerprint": "fp:main", "closure": [DEF], "exact": {"text": "∀ m, B m"}}}

    def build(eid, fp, src, inputs):
        assessed = [{"id": "P:main", "status": "s", "status_code": "formal.review-pending",
                     "clauses": [{"name": "statement", "spec": MAIN,
                                  "spec_review": rv("pending"),
                                  "def_reviews": {DEF: rv("pending")}}]}]
        return record(eid, [claim("P:main", "Theorem 1", H["a"], 1, MAIN)], assessed,
                      [decl(MAIN, "fp:main", "x"),
                       {**decl(DEF, fp, "fun m => m + 5"), "lean_source": {"sha256": src}}],
                      specs, {"P:main": region(H["a"], 1)}, inputs)
    return chg.compare(build("e1", "fp:def-1", "src-1", "l1"), "r-1",
                       build("e2", fingerprint, source, "l2"), "r-2")


def test_a_definition_whose_source_alone_changed_gives_no_signal():
    """#397: an edit of a definition's authored source that leaves its statement and value as
    they were (a proof inside it, the tactic of a tactic default) changes nothing a review of
    the statement that uses it, or of the definition, reads. A changed value does."""
    units = [unit("spec:" + MAIN, [("P:main", "Theorem 1")]),
             unit("def:" + DEF, [("P:main", None)], source_sha256={"P:main": H["a"]})]
    source = definition_edit("fp:def-1", "src-2")
    assert [d["change"] for d in source["claims"][0]["lean"][0]["definitions"]] == ["proof"]
    assert rq.change_signals(units, source) == {}
    value = definition_edit("fp:def-2", "src-2")
    assert [d["change"] for d in value["claims"][0]["lean"][0]["definitions"]] == ["statement"]
    got = rq.change_signals(units, value)
    assert [s["text"] for s in got["spec:" + MAIN]] == [
        "changed since the last release: a definition its Lean statement uses"]
    assert [s["text"] for s in got["def:" + DEF]] == [
        "changed since the last release: this definition's Lean"]


def test_ties_keep_the_queue_order():
    """Two units with the same signal keep their order, whichever order they come in."""
    doc = {"from": {"release": "r-1"}, "to": {"release": "r-2"}, "declarations": [],
           "claims": [{"claim": c, "number": n, "paper_change": {"class": "changed"},
                       "lean": [], "evidence": []}
                      for c, n in (("P:x", "Lemma 1"), ("P:y", "Lemma 2"))]}
    a, b, c = (unit("spec:Ex.x", [("P:x", "Lemma 1")]), unit("spec:Ex.y", [("P:y", "Lemma 2")]),
               unit("spec:Ex.z", [("P:z", "Lemma 3")]))
    for units in ([c, a, b], [c, b, a]):
        out = rq.prioritise(queue(units), changes=doc)
        assert ids(out["units"]) == ids(units[1:]) + ["spec:Ex.z"]


# -- use in another claim's proof ------------------------------------------------------------

def uses_index(edges):
    by = {}
    for name, user, refs in edges:
        by.setdefault(name, [{"module": "Ex.M", "users": []}])[0]["users"].append(
            {"name": user, "module": "Ex.M", "refs": refs})
    return {"schema": "machinechecked/uses-index@1", "by_name": by}


def test_a_lemma_used_in_another_claims_proof_comes_first():
    units = [unit("link:thm:main", [("P:thm:main", "Theorem 3")], lean=["Ex.main"]),
             unit("link:lem:b", [("P:lem:b", "Lemma 2")], lean=["Ex.b"]),
             unit("link:lem:c", [("P:lem:c", "Lemma 4")], lean=["Ex.c"]),
             unit("link:lem:a", [("P:lem:a", "Lemma 1")], lean=["Ex.a"])]
    uses = uses_index([
        ("Ex.a", "Ex.main", ["proof"]),            # directly, in the proof
        ("Ex.b", "Ex.main", ["statement"]),        # only in its statement: not a proof use
        ("Ex.c", "Ex.helper", ["statement"]),      # through a helper the proof applies
        ("Ex.helper", "Ex.main", ["proof"]),
        ("Ex.a", "Ex.unlinked", ["proof"])])       # a use by no claim's Lean says nothing
    out = rq.prioritise(queue(units, "simple"), uses=uses)
    assert ids(out["units"]) == ["link:lem:c", "link:lem:a", "link:thm:main", "link:lem:b"]
    by = {u["id"]: u for u in out["units"]}
    assert by["link:lem:a"]["reason"] == "Used in the proof of Theorem 3; short statement"
    assert by["link:lem:c"]["priority"]["signals"][0]["claims"] == ["P:thm:main"]
    assert by["link:lem:b"]["reason"] == "Short statement"
    assert out["order"]["signals"]["proof use"] == {"state": "read"}
    # A changed unit still comes before one that is only used.
    doc = {"from": {"release": "r-1"}, "to": {"release": "r-2"}, "declarations": [],
           "claims": [{"claim": "P:lem:b", "number": "Lemma 2", "lean": [], "evidence": [],
                       "paper_change": {"class": "context-changed"}}]}
    out = rq.prioritise(queue(units, "simple"), changes=doc, uses=uses)
    assert ids(out["units"])[0] == "link:lem:b"
    assert out["units"][0]["reason"].startswith("Changed since the last release: the context "
                                                "of Lemma 2's passage")


def test_an_incomplete_trace_is_unknown_not_unused():
    units = [unit("link:lem:a", [("P:lem:a", "Lemma 1")], lean=["Ex.a"]),
             unit("link:thm:main", [("P:thm:main", "Theorem 3")], lean=["Ex.main"])]
    out = rq.prioritise(queue(units, "simple"), uses=uses_index([]), unbuilt=2)
    sig = out["order"]["signals"]["proof use"]
    assert sig["state"] == "incomplete" and "2 module(s)" in sig["why"]
    # No unit is said to be unused, and the order stands.
    assert ids(out["units"]) == ids(units) and out["order"]["by"] == "effort"
    assert not any("used" in u["reason"] for u in out["units"])


# -- a site, workspaces and the command line -----------------------------------------------------

CHANGED, WITNESS, ESTIMATE, FULL, USE = (
    ("P:thm:changed", "Theorem 1", "Ex.Spec.changed"),
    ("P:thm:witness", "Theorem 2", "Ex.Spec.witness"),
    ("P:lem:estimate", "Lemma 3", "Ex.Spec.estimate"),
    ("P:thm:full", "Theorem 4", "Ex.Spec.full"),
    ("P:thm:use", "Theorem 5", "Ex.Spec.use"))
CLAIMS = (CHANGED, WITNESS, ESTIMATE, FULL, USE)


def write_site(root, order=(FULL, USE, ESTIMATE, WITNESS, CHANGED)):
    """A synthetic full-assessment site in `root/.machinechecked`: five claims, each stated by
    one proposition, in a queue that `prioritise` has ordered with the comparison of two
    releases, in which Theorem 1's proposition changed. Theorem 5's proposition has a
    hypothesis that an alignment may leave unmatched."""
    work = root / ".machinechecked"
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True)
    hyp = {"binders": [{"id": "/0", "name": "m", "role": "forall", "type": {"text": "Nat"}},
                       {"id": "/1", "name": "h", "role": "hypothesis",
                        "type": {"text": "Finite m"}}],
           "conclusion": {"text": "Bound m"}}
    for cid, number, spec in CLAIMS:
        f = cid.replace(":", "_") + ".json"
        (data / "claims" / f).write_text(json.dumps({
            "id": cid, "paper": "P", "number": number, "kind": "theorem", "links": [],
            "clauses": [{"name": "statement", "spec": spec,
                         "statement": hyp if cid == USE[0] else None}]}))
    claims = [{"id": c, "paper": "P", "number": n, "file": c.replace(":", "_") + ".json"}
              for c, n, _ in CLAIMS]
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "full", "release": "r-2",
        "project": {"name": "ex", "commit": "c" * 40},
        "papers": [{"id": "P", "title": "Synthetic", "revision": "c" * 40}],
        "claims": claims}))
    doc = {"from": {"release": "r-1"}, "to": {"release": "r-2"}, "declarations": [],
           "claims": [{"claim": CHANGED[0], "number": CHANGED[1], "lean": [],
                       "paper_change": {"class": "unchanged"},
                       "evidence": [{"target": "spec", "name": CHANGED[2], "outcome": "reopened",
                                     "because": [{"dependency": "lean", "name": CHANGED[2],
                                                  "now": "fp:2"}],
                                     "question": "Does it still state Theorem 1?"}]}]}
    q = rq.prioritise(queue([unit("spec:" + s, [(c, n)], fingerprint="fp:" + s)
                             for c, n, s in order]), changes=doc, claims=claims)
    (data / "review-queue.json").write_text(json.dumps(q))
    return work


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base else {})}


def investigate(work):
    """An auditor's informed investigation: Theorem 2 combines two existence results whose
    witnesses are not shown to agree; Lemma 3's estimate needs one more derivative in the Lean;
    Theorem 4 matches in full; Theorem 5's proposition assumes a finiteness condition its
    paper statement does not print, which the auditor explains by its use."""
    p = wsp.open_for(work, AUDITOR, "informed")
    w, e, f, u = WITNESS[0], ESTIMATE[0], FULL[0], USE[0]
    wsp.update(p, [
        put({"id": "r-w", "kind": "requirement", "claim": w, "local_id": "r1",
             "form": "there is", "binds": ["u"], "text": "a u that solves and is bounded"}),
        put({"id": "e-solves", "kind": "evidence", "claim": w, "role": "supports",
             "ref": {"decl": "Ex.solves"}}),
        put({"id": "e-bound", "kind": "evidence", "claim": w, "role": "supports",
             "ref": {"decl": "Ex.bound"}}),
        put({"id": "c-w", "kind": "composition", "claim": w, "steps": [
            {"id": "s1", "establishes": "some u solves", "uses": ["e-solves"]},
            {"id": "s2", "establishes": "some u is bounded", "uses": ["e-bound"],
             "requirements": ["r1"]}],
            "obligations": [{"id": "o1", "kind": "compatible witnesses",
                             "text": "the two results may choose different u"}]}),
        put({"id": "f-w", "kind": "finding", "claim": w, "coverage": "unresolved",
             "question": "Is the bounded u the one that solves?", "note": "Two witnesses."}),
        {"op": "submit", "id": "f-w", "base_rev": 1},
        put({"id": "r-e", "kind": "requirement", "claim": e, "local_id": "r1",
             "form": "conclusion", "text": "the bound with m + 4 derivatives"}),
        put({"id": "f-e", "kind": "finding", "claim": e, "requirement": "r1",
             "difference": {"feature": "derivative order", "paper": "m + 4", "lean": "m + 5",
                            "outcome": "difference"}, "note": "One more derivative."}),
        put({"id": "f-f", "kind": "finding", "claim": f, "coverage": "full", "note": "Direct."}),
        put({"id": "r-u", "kind": "requirement", "claim": u, "local_id": "r1",
             "form": "for every", "binds": ["m"], "text": "for every m"}),
        put({"id": "a-u", "kind": "alignment", "claim": u, "requirements": ["r1"],
             "lean": [{"decl": USE[2], "binder": 0}]})])
    return p


def session(work, who=REFEREE):
    return rc.Session(work, who)


def test_the_documented_investigation_order(tmp_path):
    """A changed dependency, an open witness compatibility, a quantitative difference and an
    ordinary full match, in that order, whatever order the queue had them in."""
    for order in ((FULL, USE, ESTIMATE, WITNESS, CHANGED), (WITNESS, FULL, CHANGED, USE,
                                                             ESTIMATE)):
        root = tmp_path / str(len(list(tmp_path.iterdir())))
        work = write_site(root, order)
        investigate(work)
        s = session(work)
        # Without asking, the order uses the build's records only: the auditors' are not read.
        plain = s.open_units()
        assert plain[0]["id"] == "spec:" + CHANGED[2]
        assert [u["id"] for u in plain[1:]] == ["spec:" + x[2] for x in order if x != CHANGED]
        assert not (work / "review-work" / "human_B-Referee.json").exists()
        informed = s.open_units("informed")
        assert ids(informed) == ["spec:" + x[2] for x in (CHANGED, WITNESS, ESTIMATE, USE, FULL)]
        by = {u["id"]: u for u in informed}
        assert by["spec:" + CHANGED[2]]["reason"] == ("Reopened since the last release: its Lean "
                                                      "statement changed; short statement")
        assert by["spec:" + WITNESS[2]]["reason"] == (
            "An open obligation is recorded: compatible witness choices; a recorded finding "
            "leaves an open question; short statement")
        assert by["spec:" + ESTIMATE[2]]["reason"] == ("A recorded difference (derivative "
                                                       "order); short statement")
        assert by["spec:" + USE[2]]["reason"] == ("A hypothesis of its Lean statement is "
                                                  "aligned with no requirement; short statement")
        assert by["spec:" + FULL[2]]["reason"] == "Short statement"
        # No status, state or stored queue changes.
        assert {u["state"] for u in informed} == {"pending"}
        assert json.loads((work / "site/data/review-queue.json").read_text())["units"] == \
            s.queue["units"]


def test_an_informed_order_is_recorded_as_exposure(tmp_path):
    work = write_site(tmp_path)
    s = session(work)
    # With no recorded interpretation there is nothing to have seen, and nothing is written.
    s.open_units("informed")
    assert not (work / "review-work" / "human_B-Referee.json").exists()
    investigate(work)
    s = session(work)
    assert s.revealed_by(s.unit("spec:" + WITNESS[2])) == []
    s.open_units("informed")
    ws = wsp.read(work / "review-work" / "human_B-Referee.json")
    e, = ws["exposure"]
    assert e["what"] == ["prior interpretations"] and e["how"] == rc.ORDER_EXPOSURE
    assert e["claims"] == sorted([WITNESS[0], ESTIMATE[0], USE[0]])
    assert ws["mode"] == "independent"
    # A reading of such a claim is no longer blind, and its report will say so; the claim
    # the records said nothing about keeps its blind reading.
    seen = s.revealed_by(s.unit("spec:" + WITNESS[2]))
    assert seen and seen[0]["unit"].endswith(f"({rc.ORDER_EXPOSURE})")
    assert "will not be blind" in s.read("spec:" + WITNESS[2])
    assert s.revealed_by(s.unit("spec:" + FULL[2])) == []
    # Asking again records nothing new.
    session(work).open_units("informed")
    assert len(wsp.read(work / "review-work" / "human_B-Referee.json")["exposure"]) == 1


def test_resolving_a_premise_changes_the_next_question_and_keeps_the_history(tmp_path):
    work = write_site(tmp_path, (WITNESS, ESTIMATE, FULL))
    p = investigate(work)
    assert session(work).open_units("informed")[0]["id"] == "spec:" + WITNESS[2]
    before = wsp.read(p)["records"]["f-w"]
    # The auditor shows the two witnesses agree, and supersedes the unresolved finding.
    c = wsp.read(p)["records"]["c-w"]
    wsp.update(p, [
        put({k: c[k] for k in ("kind", "claim", "steps")} | {"id": "c-w", "obligations": [
            {"id": "o1", "kind": "compatible witnesses", "text": "the bound is for that u",
             "state": "discharged", "by": {"steps": ["s2"]}}]}, base=c["rev"]),
        {"op": "supersede", "id": "f-w", "base_rev": before["rev"],
         "reason": "the witnesses agree", "record": {"coverage": "full", "note": "One u."}}])
    nxt = session(work).open_units("informed")
    assert nxt[0]["id"] == "spec:" + ESTIMATE[2]
    assert nxt[-1]["reason"] == "Short statement"
    # The earlier finding is kept as it was submitted.
    after = wsp.read(p)["records"]
    assert after["f-w"] == before and any(r.get("supersedes") == "f-w" for r in after.values())


def test_a_resolved_difference_stops_the_hint_and_the_local_difference_stays(tmp_path):
    """The finite-loss case: the lemma's estimate needs one more derivative than printed; the
    theorem that uses it needs only finitely many. The lemma's difference stays; the theorem's
    extra hypothesis, explained by that use, is no longer offered as a new problem."""
    work = write_site(tmp_path, (USE, ESTIMATE, FULL))
    p = investigate(work)
    assert ids(session(work).open_units("informed")) == [
        "spec:" + ESTIMATE[2], "spec:" + USE[2], "spec:" + FULL[2]]
    wsp.update(p, [put({"id": "f-u", "kind": "finding", "claim": USE[0], "requirement": "r1",
                        "difference": {"feature": "additional assumption", "paper": "none",
                                       "lean": "Finite m", "outcome": "resolved",
                                       "hint": {"decl": USE[2], "binder": 1},
                                       "resolution": {"by": "argument", "text":
                                                      "the use needs only finitely many "
                                                      "derivatives"}},
                        "note": "Satisfied where it is used."})])
    out = session(work).open_units("informed")
    by = {u["id"]: u for u in out}
    assert ids(out) == ["spec:" + ESTIMATE[2], "spec:" + USE[2], "spec:" + FULL[2]]
    assert by["spec:" + USE[2]]["reason"] == "Short statement"
    assert by["spec:" + ESTIMATE[2]]["reason"].startswith("A recorded difference (derivative")
    # The explanation and the exact local difference are both kept in the workspace.
    recs = wsp.read(p)["records"]
    assert recs["f-u"]["difference"]["resolution"]["by"] == "argument"
    assert (recs["f-e"]["difference"]["paper"], recs["f-e"]["difference"]["lean"]) == \
        ("m + 4", "m + 5")


def test_document_order_and_explicit_selection_stay_available(tmp_path):
    work = write_site(tmp_path)
    s = session(work)
    doc = s.open_units("document")
    assert ids(doc) == ["spec:" + x[2] for x in CLAIMS]
    assert doc[0]["reason"] == ("In the paper's order; reopened since the last release: its "
                                "Lean statement changed; short statement")
    assert doc[1]["reason"] == "In the paper's order; short statement"
    # Any unit can still be taken directly, whatever the order.
    assert "Theorem 4" in s.read("spec:" + FULL[2])
    with pytest.raises(rc.ReviewError, match="not one of"):
        s.open_units("by-hunch")


def test_the_reader_has_the_paper_order_the_command_line_gives(tmp_path):
    """The build writes the paper's order into the queue for the reader's review page: the units,
    order and reasons of `review status --order document`."""
    work = write_site(tmp_path)
    stored = json.loads((work / "site/data/review-queue.json").read_text())
    doc = session(work).open_units("document")
    assert stored["orders"]["document"] == [{"id": u["id"], "reason": u["reason"]} for u in doc]
    assert stored["orders"]["document"][0]["reason"].startswith("In the paper's order; reopened")
    # The queue's own order and reasons are unchanged by it.
    assert ids(stored["units"]) == ids(session(work).open_units())
    assert "orders" not in rq.prioritise(queue([unit("spec:A", [("P:a", "Theorem 1")])]))


def test_the_local_server_gives_the_reader_the_informed_order_and_writes_nothing(tmp_path):
    """`GET /api/review-order?order=informed` of `machinechecked view`'s server gives the units,
    reasons and priority records of `review next --order informed`, and the claims it drew on.
    The review page records that exposure in the reviewer's browser, so the server writes no
    workspace."""
    import threading
    import urllib.error
    import urllib.request
    from prooflens.server import make_server
    work = write_site(tmp_path)
    p = investigate(work)
    before = wsp.read(p)
    httpd = make_server(work / "site", 0, api=wsp.api(work, work / "site" / "data"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/api/review-order"
    try:
        with urllib.request.urlopen(base + "?order=informed", timeout=10) as r:
            got = json.loads(r.read())
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(base + "?order=document", timeout=10)
        assert refused.value.code == 400
        assert "data/review-queue.json" in json.loads(refused.value.read())["error"]
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert (got["schema"], got["order"], got["release"]) == ("machinechecked/review-order@1",
                                                             "informed", "r-2")
    assert got["exposure"] == {"what": ["prior interpretations"], "how": rc.ORDER_EXPOSURE}
    assert [q for q, _ in wsp.list_all(work)] == [p] and wsp.read(p) == before
    s = session(work)
    cli_units = s.open_units("informed")
    assert got["units"] == [{k: u.get(k) for k in ("id", "reason", "priority")}
                            for u in cli_units]
    assert got["units"][1]["reason"].startswith("An open obligation is recorded")
    e, = wsp.read(work / "review-work" / "human_B-Referee.json")["exposure"]
    assert sorted(got["drawn"]) == e["claims"] == sorted([WITNESS[0], ESTIMATE[0], USE[0]])


def test_the_command_line_says_why_and_asks_the_question(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    work = write_site(root)
    (root / "lakefile.toml").write_text('name = "ex"\n')
    investigate(work)
    monkeypatch.chdir(root)
    who = ["--as", "human:B-Referee"]

    def run(*args):
        cli.main(["review", *args, *who])
        return capsys.readouterr().out

    out = run("next")
    assert out.splitlines() == [
        "spec:Ex.Spec.changed  (Reopened since the last release: its Lean statement changed; "
        "short statement)", "  question: Does it still state Theorem 1?"]
    nxt = json.loads(run("next", "--json"))
    assert nxt["order"] == "priority" and nxt["unit"]["priority"]["tier"] == "reopened"
    st = json.loads(run("status", "--json", "--order", "document"))
    assert st["order"]["by"] == "document" and st["open"][0] == "spec:" + CHANGED[2]
    assert st["order"]["queue"]["signals"]["changes"]["state"] == "read"
    assert "order: proof use not available" in run("status")
    assert not (work / "review-work" / "human_B-Referee.json").exists()
    out = run("next", "--order", "informed", "--json")
    assert json.loads(out)["order"] == "informed"
    assert wsp.read(work / "review-work" / "human_B-Referee.json")["exposure"]
