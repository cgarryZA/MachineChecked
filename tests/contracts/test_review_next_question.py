"""The informed order asks the next question from the workspaces' records (#477): a finding a
change reopened comes first, with the question a new reading answers, whether a later build or a
version map of the paper the workspace keeps reopened it; requirements, alignments and
counterexamples that are out of date, what each counterexample shows, passages proposed and not
accepted, findings not known to be current; and, in zero configuration, the main results a
workspace saves and what they use. All of it is prior interpretation: only the informed order
reads it, asking for it is recorded as exposure, and the queue's own order and the independent
steps show none of it. Every build here is synthetic, so no Lean runs."""

import json

import pytest

from prooflens import cli
from prooflens import reopen as ro
from prooflens import review_cli as rc
from prooflens import review_queue as rq
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

import test_reopen as rev
from test_review_priority import (AUDITOR, CHANGED, ESTIMATE, FULL, REFEREE, USE, WITNESS,
                                  build_of, ids, investigate, put, queue, session, unit,
                                  uses_index, write_site)

SPEC = {c: "spec:" + s for c, _, s in (CHANGED, WITNESS, ESTIMATE, FULL, USE)}


def revise(work, cid, sha="9" * 64):
    """A later build of the paper in which the passage of claim `cid` changed."""
    data = work / "site" / "data"
    f = data / "claims" / (cid.replace(":", "_") + ".json")
    chunk = json.loads(f.read_text())
    f.write_text(json.dumps({**chunk, "source_sha256": sha}))


def relean(work, cid, fingerprint):
    """A later build in which the proposition of claim `cid` changed."""
    data = work / "site" / "data"
    f = data / "claims" / (cid.replace(":", "_") + ".json")
    chunk = json.loads(f.read_text())
    chunk["clauses"][0]["statement"]["fingerprint"] = fingerprint
    f.write_text(json.dumps(chunk))


def signals_of(u, kind):
    return [s for s in u["priority"]["signals"] if s["kind"] == kind]


def referee_workspace(work):
    return work / "review-work" / "human_B-Referee.json"


# -- findings a later build reopens ----------------------------------------------------------

def test_a_finding_a_later_build_reopens_leads_the_informed_order_with_its_question(tmp_path):
    work = write_site(tmp_path)
    p = investigate(work)
    # A passage that governs Lemma 3's requirement, read when the finding on it was recorded;
    # Theorem 4's finding is submitted.
    wsp.update(p, [put({"id": "p-e", "kind": "fragment", "claim": ESTIMATE[0],
                        "requirement": "r1", "role": "statement",
                        "passage": {"claim": ESTIMATE[0]}}),
                   {"op": "submit", "id": "f-f", "base_rev": 1}], build_of(work))
    before = [u["id"] for u in session(work).open_units("informed")]
    assert before[0] == SPEC[CHANGED[0]]
    # The paper is revised: Theorem 4's passage and Lemma 3's change.
    revise(work, FULL[0])
    revise(work, ESTIMATE[0], "8" * 64)
    s = session(work)
    out = s.open_units("informed")
    by = {u["id"]: u for u in out}
    # The reopened findings lead, ahead of the review the build reopened; ties keep the queue's
    # order (Theorem 4 comes first in it).
    assert ids(out)[:3] == [SPEC[FULL[0]], SPEC[ESTIMATE[0]], SPEC[CHANGED[0]]]
    full = by[SPEC[FULL[0]]]
    assert full["priority"]["tier"] == "reopened finding"
    assert full["reason"] == ("A recorded finding is due for review: the passage of Theorem 4 "
                              "changed; short statement")
    sig, = signals_of(full, "reopened finding")
    assert sig["claims"] == [FULL[0]]
    assert sig["questions"] == ["Does finding f-f still hold now that the passage of Theorem 4 "
                                "changed?"]
    est = by[SPEC[ESTIMATE[0]]]
    assert est["reason"] == (
        "A recorded finding is due for review: the passage of Lemma 3 changed; a recorded "
        "requirement is out of date: the passage of Lemma 3 changed; a recorded difference "
        "(derivative order); short statement")
    q, = signals_of(est, "reopened finding")[0]["questions"]
    assert q == "Does finding f-e (on r1) still hold now that the passage of Lemma 3 changed?"
    # The words name claims, never a declaration: they are read before the Lean is shown.
    assert not any("Ex." in u["reason"] for u in out)
    assert not any("Ex." in q for u in out for s in u["priority"]["signals"]
                   for q in s.get("questions") or [])
    # The claims it drew on are recorded as seen (Theorem 4's only now that a finding on it is
    # due), and no status, state or stored queue changed.
    first, now = wsp.read(referee_workspace(work))["exposure"]
    assert {first["how"], now["how"]} == {rc.ORDER_EXPOSURE}
    assert FULL[0] not in first["claims"] and FULL[0] in now["claims"]
    assert {ESTIMATE[0], WITNESS[0], USE[0]} <= set(now["claims"])
    assert {u["state"] for u in out} == {"pending"}
    assert json.loads((work / "site/data/review-queue.json").read_text())["units"] == \
        s.queue["units"]
    # A new reading supersedes the reopened finding, which is kept; the question goes.
    f = wsp.read(p)["records"]["f-f"]
    wsp.update(p, [{"op": "supersede", "id": "f-f", "base_rev": f["rev"],
                    "reason": "the new text says the same", "record": {"coverage": "full",
                                                                       "note": "Still direct."}}],
               build_of(work))
    nxt = session(work).open_units("informed")
    assert not signals_of({u["id"]: u for u in nxt}[SPEC[FULL[0]]], "reopened finding")
    assert wsp.read(p)["records"]["f-f"] == f


def test_the_queue_s_own_order_and_the_independent_steps_show_none_of_it(tmp_path, capsys,
                                                                         monkeypatch):
    root = tmp_path / "proj"
    work = write_site(root)
    (root / "lakefile.toml").write_text('name = "ex"\n')
    investigate(work)
    revise(work, FULL[0])
    s = session(work)
    plain = s.open_units()
    assert [u["id"] for u in plain] == [u["id"] for u in s.queue["units"]
                                         if u["state"] != "reviewed"]
    words = json.dumps(plain)
    assert "due for review" not in words and "Does finding" not in words
    # Reading a unit shows the paper only: nothing of the workspaces' records.
    packet = s.read(SPEC[FULL[0]], as_json=True)
    assert "f-f" not in json.dumps(packet) and "due for review" not in json.dumps(packet)
    assert not referee_workspace(work).exists() or not wsp.read(referee_workspace(work)).get(
        "exposure")
    # The command line: the priority order asks nothing of the workspaces; the informed one
    # prints the question and says what it read.
    monkeypatch.chdir(root)
    who = ["--as", "human:B-Referee"]

    def run(*args):
        cli.main(["review", *args, *who])
        return capsys.readouterr().out

    assert "Does finding" not in run("next")
    assert not (referee_workspace(work).exists()
                and wsp.read(referee_workspace(work)).get("exposure"))
    out = run("next", "--order", "informed")
    assert out.splitlines() == [
        f"{SPEC[FULL[0]]}  (A recorded finding is due for review: the passage of Theorem 4 "
        "changed; short statement)",
        "  question: Does finding f-f still hold now that the passage of Theorem 4 changed?"]
    st = json.loads(run("status", "--order", "informed", "--json"))
    assert st["order"]["informed"] == {
        "workspaces": {"state": "read", "count": 2},
        "main result": {"state": "not available",
                        "why": "no workspace saves the paper's main results (`workspace main`)"}}
    assert "order: main result not available: no workspace saves the paper's main results" in \
        run("status", "--order", "informed")
    # A reading locked after it is not blind, and its report will say so.
    s = session(work)
    seen = s.revealed_by(s.unit(SPEC[FULL[0]]))
    assert seen and seen[0]["unit"].endswith(f"({rc.ORDER_EXPOSURE})")


# -- requirements, alignments, counterexamples and passages ----------------------------------

def test_out_of_date_records_counterexamples_and_proposed_passages(tmp_path):
    work = write_site(tmp_path)
    p = investigate(work)
    u = USE[0]
    adm = [{"obligation": "m = 0 is a natural number", "state": "verified",
            "method": "arithmetic"}]
    wsp.update(p, [
        put({"id": "x-adm", "kind": "counterexample", "claim": u, "requirement": "r1",
             "specialisation": {"assign": {"m": 0}}, "reduced": "Bound 0",
             "violation": "Bound 0 fails", "admissibility": adm}),
        put({"id": "x-open", "kind": "counterexample", "claim": WITNESS[0], "requirement": "r1",
             "specialisation": {"assign": {"u": 0}}, "reduced": "u = 0",
             "violation": "not bounded",
             "admissibility": [{"obligation": "the u is admissible", "state": "open"}]}),
        put({"id": "x-part", "kind": "counterexample", "claim": u, "requirement": "r1",
             "specialisation": {"assign": {"k": 1}}, "reduced": "Bound m",
             "violation": "fails", "admissibility": adm}),
        put({"id": "r-f", "kind": "requirement", "claim": FULL[0], "local_id": "r1",
             "form": "conclusion", "text": "the bound"}),
        put({"id": "p-prop", "kind": "fragment", "claim": FULL[0], "requirement": "r1",
             "role": "statement", "state": "proposed", "passage": {"claim": FULL[0]}})],
        build_of(work))
    out = {u["id"]: u for u in session(work).open_units("informed")}
    assert "an admissible counterexample to a reading is recorded" in \
        [s["text"] for s in signals_of(out[SPEC[USE[0]]], "difference")]
    assert out[SPEC[WITNESS[0]]]["priority"]["tier"] == "open question"
    assert "a candidate counterexample is recorded, not yet shown admissible" in \
        [s["text"] for s in signals_of(out[SPEC[WITNESS[0]]], "open question")]
    # One that gives the variable of Theorem 5's reading no value is incomplete.
    assert [s["text"] for s in signals_of(out[SPEC[USE[0]]], "open question")] == [
        "an incomplete counterexample is recorded"]
    assert [s["text"] for s in signals_of(out[SPEC[FULL[0]]], "hint")] == [
        "a passage proposed as governing a requirement is not yet accepted"]
    # Theorem 5's proposition changes in a later build: its alignment with the Lean is out of
    # date, and the words do not name the Lean.
    relean(work, u, "fp:Ex.Spec.use-2")
    out = {x["id"]: x for x in session(work).open_units("informed")}
    use = out[SPEC[USE[0]]]
    assert [s["text"] for s in signals_of(use, "out of date")] == [
        "a recorded alignment with the Lean is out of date: the Lean it rests on changed"]
    assert use["priority"]["tier"] == "out of date"
    assert not any("Ex." in x["reason"] for x in out.values())


def test_a_resolution_that_does_not_hold_now_is_a_difference(tmp_path):
    """A resolution that leaves a condition open, and a checked bridge Lean does not check, keep
    their difference in the informed order (#499)."""
    work = write_site(tmp_path)
    p = investigate(work)
    e = ESTIMATE[0]
    wsp.update(p, [put({"id": "f-part", "kind": "finding", "claim": e, "requirement": "r1",
                        "difference": {"feature": "power", "paper": "p", "outcome": "resolved",
                                       "conditions": ["a", "b"],
                                       "resolution": {"by": "argument", "text": "t",
                                                      "conditions": ["a"]}},
                        "note": "n"})], build_of(work))
    # A checked bridge Lean did not check, as a hand-edited workspace file can hold one.
    ws = wsp.read(p)
    ws["records"]["f-bridge"] = {**ws["records"]["f-part"], "id": "f-bridge", "difference": {
        "feature": "domain", "paper": "p", "transport": "t", "outcome": "resolved",
        "resolution": {"by": "checked bridge", "theorem": "Ex.b", "target": "Ex.B", "text": "t"}}}
    with wsp._locked(p):
        wsp._write(p, ws)
    out = {u["id"]: u for u in session(work).open_units("informed")}
    assert [s["text"] for s in signals_of(out[SPEC[e]], "difference")] == [
        "a recorded difference (derivative order)",
        "a recorded difference (power), resolved in part",
        "a recorded difference (domain), recorded as resolved; Lean does not check its bridge now"]
    assert not any("Ex." in x["reason"] for x in out.values())


def test_record_signals_word_each_record_once_per_kind():
    """Two out-of-date requirements of one claim are counted, with what changed in each."""
    ws = {"records": {
        "r1": {"id": "r1", "kind": "requirement", "claim": "P:a", "local_id": "r1"},
        "r2": {"id": "r2", "kind": "requirement", "claim": "P:a", "local_id": "r2"},
        "f1": {"id": "f1", "kind": "fragment", "claim": "P:a", "requirement": "r1",
               "state": "accepted"},
        "f2": {"id": "f2", "kind": "fragment", "claim": "P:a", "requirement": "r2"},
        "f3": {"id": "f3", "kind": "fragment", "claim": "P:a", "requirement": "r2",
               "state": "removed"}}}
    cur = {"f1": {"state": "stale", "changes": [{"passage": "P:a", "was": "x", "now": "y"}]},
           "f2": {"state": "stale", "changes": [{"region": "p.tex:4", "was": "x", "now": "y"}]},
           "f3": {"state": "stale", "changes": [{"decl": "Ex.hidden", "was": "x", "now": "y"}]}}
    got = []
    rq.record_signals(ws, cur, {}, {"P:a": "Theorem 1"}, lambda *a: got.append(a))
    assert got == [("P:a", "out of date", "2 recorded requirements are out of date: the passage "
                    "of Theorem 1 changed; a passage of the paper it reads changed")]
    assert rq.change_words([{"decl": "Ex.hidden", "was": "x", "now": "y",
                             "reason": "Ex.hidden changed"}], {}) == \
        "the Lean it rests on changed"


# -- findings a version map of the paper reopens ---------------------------------------------

def test_the_findings_a_kept_version_map_reopens_lead_with_its_questions(tmp_path):
    """The synthetic paper of `test_reopen` in two revisions: the workspace keeps the map from
    the earlier release to the later one, whose build the queue is of."""
    a, b = tmp_path / "a", tmp_path / "b"
    for root, later in ((a, False), (b, True)):
        root.mkdir()
        (root / "paper.tex").write_text(rev.manuscript(later))
    old, new = rev.inventories(a, b)
    work = tmp_path / ".machinechecked"
    rev.site(work, "r-1", old, a)
    p = rev.investigation(work, a)
    uses = {"T:thm:keep": {"T:def:bounded": ["Ex.Bounded"]}}
    doc = rev.vm.compare("T", rev.vm.Side(old, a, "r1", uses=uses, identity={"release": "r-1"}),
                         rev.vm.Side(new, b, "r2", uses=uses, identity={"release": "r-2"}),
                         regions=ro.regions_of(wsp.read(p), "T"))
    wsp.update(p, [{"op": "version-map", "map": doc}], Snapshot(work / "site" / "data"))
    rev.site(work, "r-2", new, b)
    data = work / "site" / "data"
    units = [unit("link:" + c["id"].split(":", 1)[1], [(c["id"], c["number"])],
                  lean=[rev.LINKS[c["id"]][0]] if c["id"] in rev.LINKS else [])
             for c in new]
    (data / "review-queue.json").write_text(json.dumps(rq.prioritise(queue(units, "simple"))))
    s = rc.Session(work, REFEREE)
    out = s.open_units("informed")
    by = {u["id"]: u for u in out}
    reopened = [u["id"] for u in out if u["priority"]["tier"] == "reopened finding"]
    assert reopened == ids(out)[:6]
    assert set(reopened) == {"link:thm:keep", "link:thm:moved", "link:thm:edit",
                             "link:thm:macro", "link:thm:standing", "link:eq:young"}
    edit = by["link:thm:edit"]
    assert edit["reason"] == ("A recorded finding is due for review: the passage of Theorem 2.3 "
                              "changed in the revision; short statement")
    assert signals_of(edit, "reopened finding")[0]["questions"] == [
        "Does finding f-edit still hold for the changed text of Theorem 2.3 (T:thm:edit)?"]
    macro = signals_of(by["link:thm:macro"], "reopened finding")[0]
    assert macro["questions"] == ["Does finding f-macro still hold for Theorem 2.4 "
                                  "(T:thm:macro) now that the definition of \\dimK changed?"]
    # Through the Lean, a changed definition the claim's Lean relies on: the question names
    # the claim it relies on, never the declaration that relies on it.
    keep = signals_of(by["link:thm:keep"], "reopened finding")[0]
    assert keep["questions"] and not any("Ex." in q for q in keep["questions"])
    assert "Definition 1.1" in " ".join(keep["questions"])
    # A moved and renumbered claim keeps its statement comparison current: only the finding
    # that quotes the changed Theorem 2.3 is due.
    moved, = signals_of(by["link:thm:moved"], "reopened finding")
    assert moved["questions"] == ["Does finding f-moved-quote still hold for the changed text of "
                                  "Theorem 2.3 (T:thm:edit)?"]
    # A passage the map finds moved is the same text: of Equation (3)'s two requirements, only
    # the one whose quantifier changed is out of date.
    young = by["link:eq:young"]
    assert [x["text"] for x in signals_of(young, "out of date")] == [
        "a recorded requirement is out of date: a passage that governs it changed in the "
        "revision"]
    assert signals_of(young, "reopened finding")[0]["questions"] == [
        "Does finding f-domain (on r1) still hold now that the passage it reads as the "
        f"quantifier domain of r1 (paper.tex:{rev.line_of(rev.manuscript(False), rev.QUANTIFIER_A)}"
        ") changed?"]
    # A finding whose Lean side the build cannot check is not known to be current.
    assert "a recorded finding is not known to be current" in \
        [x["text"] for x in signals_of(by["link:thm:keep"], "hint")]
    assert not any("Ex." in u["reason"] for u in out)


# -- the main results a workspace saves ------------------------------------------------------

MAIN_CLAIMS = (("P:thm:main", "Theorem 1", "Ex.main"), ("P:lem:a", "Lemma 2", "Ex.a"),
               ("P:lem:c", "Lemma 3", "Ex.c"), ("P:def:d", "Definition 4", "Ex.D"),
               ("P:lem:e", "Lemma 5", "Ex.e"), ("P:lem:h", "Lemma 6", "Ex.h"))


def zero_config_site(root, uses=True):
    """A synthetic zero-configuration build: Theorem 1's proof uses Lemma 2's Lean directly and
    Lemma 3's through a helper, its statement uses Definition 4's; Lemma 5's is unrelated, and
    Lemma 6's is used by a helper no claim states."""
    work = root / ".machinechecked"
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True)
    rows = []
    for cid, number, name in MAIN_CLAIMS:
        key = cid.split(":", 1)[1]
        f = key.replace(":", "_") + ".json"
        (data / "claims" / f).write_text(json.dumps({
            "id": cid, "paper": "P", "number": number, "kind": "theorem", "key": key,
            "source_sha256": rev.sha256_text(cid),
            "links": [{"name": name, "fingerprint": "fp:" + name,
                       "statement": {"binders": [], "closure": [],
                                     "conclusion": {"text": "P"}}}], "clauses": []}))
        rows.append({"id": cid, "paper": "P", "number": number, "file": f})
    graph = uses_index([("Ex.a", "Ex.main", ["proof"]), ("Ex.c", "Ex.helper", ["statement"]),
                        ("Ex.helper", "Ex.main", ["proof"]),
                        ("Ex.D", "Ex.main", ["statement"]),
                        ("Ex.h", "Ex.other_main", ["proof"])])
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "r-1",
        "project": {"name": "ex", "commit": "c" * 40},
        "papers": [{"id": "P", "title": "Synthetic", "revision": "c" * 40}], "claims": rows,
        **({"uses": "data/uses.json"} if uses else {})}))
    if uses:
        (data / "uses.json").write_text(json.dumps(graph))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Ex.M"}
         for n in [*(x[2] for x in MAIN_CLAIMS), "Ex.helper", "Ex.other_main"]]))
    units = [unit("link:" + cid.split(":", 1)[1], [(cid, number)], lean=[name])
             for cid, number, name in reversed(MAIN_CLAIMS)]
    q = rq.prioritise(queue(units, "simple"), uses=graph if uses else None)
    (data / "review-queue.json").write_text(json.dumps(q))
    return work


def save_main(work, *names):
    p = wsp.open_for(work, AUDITOR, "informed")
    wsp.update(p, [{"op": "main-results", "main": list(names)}], build_of(work))
    return p


def test_the_saved_main_results_and_what_they_use_come_first(tmp_path):
    work = zero_config_site(tmp_path)
    plain = session(work).open_units()
    # The queue's own order knows proof use only.
    assert {u["id"]: u["reason"] for u in plain}["link:lem:a"] == \
        "Used in the proof of Theorem 1; short statement"
    save_main(work, "Theorem 1", "Ex.other_main")
    s = session(work)
    out = s.open_units("informed")
    by = {u["id"]: u for u in out}
    # Each main result, and each unit a main result uses, before the rest; among them the
    # queue's order stands (which puts first the lemmas another claim's proof uses).
    assert ids(plain) == ["link:lem:c", "link:lem:a", "link:lem:h", "link:lem:e", "link:def:d",
                          "link:thm:main"]
    assert ids(out) == ["link:lem:c", "link:lem:a", "link:lem:h", "link:def:d", "link:thm:main",
                        "link:lem:e"]
    assert by["link:thm:main"]["reason"] == "A saved main result; short statement"
    # The main result's use says what proof use said, and more: one signal, not two.
    assert by["link:lem:a"]["reason"] == ("Used in the proof of Theorem 1, a saved main result; "
                                          "short statement")
    assert [x["kind"] for x in by["link:lem:a"]["priority"]["signals"]] == ["main result"]
    sig, = by["link:lem:a"]["priority"]["signals"]
    assert (sig["use"], sig["claims"]) == ("proof", ["P:thm:main"])
    assert by["link:lem:c"]["reason"].startswith("Used in the proof of Theorem 1, a saved main "
                                                 "result")
    assert by["link:def:d"]["reason"] == ("Used in the statement of Theorem 1, a saved main "
                                          "result; short statement")
    # A main result named by a declaration no claim states is not named either.
    assert by["link:lem:h"]["reason"] == ("Used in the proof of a saved main result; short "
                                          "statement")
    assert by["link:lem:e"]["reason"] == "Short statement"
    assert all(u["priority"]["tier"] is None for u in out)
    assert s.order_record["main result"] == {"state": "read"}
    # The selection is an auditor's: the claims it drew on are recorded as seen.
    e, = wsp.read(referee_workspace(work))["exposure"]
    assert set(e["claims"]) == {"P:thm:main", "P:lem:a", "P:lem:c", "P:def:d", "P:lem:h"}


def test_without_reverse_references_a_main_result_itself_is_marked(tmp_path):
    work = zero_config_site(tmp_path, uses=False)
    save_main(work, "Theorem 1")
    s = session(work)
    out = s.open_units("informed")
    assert ids(out)[0] == "link:thm:main"
    assert [u["reason"] for u in out[1:]] == ["Short statement"] * (len(out) - 1)
    assert s.order_record["main result"] == {
        "state": "not available", "why": "this build extracted no reverse references: a saved "
                                         "main result itself is marked, not what it uses"}


def test_the_local_server_gives_the_page_the_same_order_and_writes_nothing(tmp_path):
    work = zero_config_site(tmp_path)
    p = save_main(work, "Theorem 1")
    before = wsp.read(p)
    got = rc.order_route(work, work / "site" / "data")({"order": ["informed"]})
    assert wsp.read(p) == before and len(wsp.list_all(work)) == 1
    assert got["signals"]["main result"] == {"state": "read"}
    cli_units = session(work).open_units("informed")
    assert got["units"] == [{k: u.get(k) for k in ("id", "reason", "priority")}
                            for u in cli_units]
    assert set(got["drawn"]) == {"P:thm:main", "P:lem:a", "P:lem:c", "P:def:d"}


@pytest.mark.parametrize("kind", rq.WORKSPACE_KINDS)
def test_every_workspace_signal_is_held_back_by_the_review_page(kind):
    """The review page holds back an informed reason from a reading locked without it
    (`holdsBack` in web/src/lib/review.js): it knows every kind the workspaces give."""
    from conftest import ROOT
    src = (ROOT / "web/src/lib/review.js").read_text()
    line = next(x for x in src.splitlines() if x.startswith("const WORKSPACE_SIGNALS"))
    assert json.dumps(kind) in line
