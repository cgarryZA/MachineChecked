"""One review session for the browser and the terminal (#122): the review page under
`machinechecked view` takes its units through the steps of `machinechecked review` on the
reviewer's workspace (`review_cli.api`), so either resumes what the other began; the locks of
independent review hold through that service; a build or another window that changed the unit
meanwhile is refused with a structured error; and an informed session reports without a blind
reading it did not have.

The site is the synthetic zero-configuration build of `test_compare.write_site`: one unit,
`link:thm:t0`, stated in eight places. Nothing here builds Lean."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.server import make_server
from test_compare import write_site

UNIT = "link:thm:t0"
A = "human:Page-Reviewer"
B = "human:Terminal-Reviewer"
READING = "Every statement bounds the jet uniformly in n, for every natural number n."
PINS = {f"S:thm:t{i}": f"sha{i}" for i in range(8)}


@pytest.fixture
def work(tmp_path):
    data = write_site(tmp_path)
    q = json.loads((data / "review-queue.json").read_text())
    q["units"][0]["source_sha256"] = PINS
    (data / "review-queue.json").write_text(json.dumps(q))
    return data.parent.parent


def routes(work):
    gets, posts = wsp.api(work, work / "site" / "data")
    return gets["/api/review"], posts["/api/review"]


def page(work, who, action, **req):
    """A request of the review page, as the local server hands it to the service."""
    return routes(work)[1]({"reviewer": who, "action": action, **req})


def session(work, who, **kw):
    return rc.Session(work, rc.parse_reviewer(who), **kw)


def refused(kind, fn, *args, **kw):
    with pytest.raises(rc.ReviewError) as e:
        fn(*args, **kw)
    assert e.value.kind == kind, (e.value.kind, str(e.value))
    return e.value


def test_a_unit_begun_in_the_browser_is_finished_in_the_terminal(work):
    """The page's draft, its pins, the exposure it recorded and the verdict the terminal
    records all reach one report."""
    get, _ = routes(work)
    # "Review it" from the claim's page: its Lean was shown before the reading.
    page(work, A, "expose", claims=["S:thm:t0"], what=["Lean"], how="the claim's page")
    st = page(work, A, "begin", unit=UNIT)
    assert st["seen_before"] == [{"unit": f"workspace {st['workspace']['id']} (the claim's page)",
                                  "what": "Lean"}]
    assert st["drafts"][UNIT]["stage"] == "read" and st["workspace"]["mode"] == "independent"
    # What the page typed is saved as it is typed, and only the step's own fields.
    page(work, A, "edit", unit=UNIT, stage="read", fields={"reading": READING[:30]})
    refused("order", page, work, A, "edit", unit=UNIT, stage="read",
            fields={"verdict": "faithful"})
    st = page(work, A, "lock", unit=UNIT, reading=READING)
    d = st["drafts"][UNIT]
    assert (d["stage"], d["reading"], d["source_sha256"]) == ("compare", READING, PINS)
    refused("order", page, work, A, "edit", unit=UNIT, stage="read", fields={"reading": "x"})
    # The same reviewer in a terminal finds the draft where the page left it.
    s = session(work, A)
    assert s.path == wsp.store(work) / "human_Page-Reviewer.json"
    refused("order", s.read, UNIT)
    assert "Syn.big_bound_" in s.show(UNIT)
    s.decide(UNIT, "broader", "Same bound, stated for every jet.", detail="Take m = n.",
             coverage={"coverage": "full", "basis": "direct"})
    s.author(UNIT)
    # The page sees the terminal's verdict, and finishes the report.
    st = get({"reviewer": [A]})
    d = st["drafts"][UNIT]
    assert (d["stage"], d["verdict"], d["correspondence"]) == (
        "author", "broader", {"coverage": "full", "basis": "direct"})
    st = page(work, A, "submit", unit=UNIT, disagreements="none")
    r = st["report"]
    assert st["drafts"] == {} and st["reports"] == [r]
    assert (r["mode"], r["reading"]["text"], r["pins"]["source_sha256"]) == (
        "independent", READING, PINS)
    assert r["reading"]["locked_at"] == d["locked_at"] and r["verdict"]["value"] == "broader"
    assert r["pins"]["fingerprints"] == {s.unit(UNIT)["name"]: "fp-big"}
    assert r["reading"]["revealed_by"] == [
        {"unit": f"workspace {st['workspace']['id']} (the claim's page)", "what": "Lean"}]
    # The terminal exports what the page submitted.
    assert session(work, A).work["reports"] == [r]


def test_a_unit_begun_in_the_terminal_is_finished_in_the_browser(work, tmp_path):
    """The terminal's locked reading reaches the page; the page's verdict, checklist and
    unresolved coverage reach the report the terminal exports, with their meaning."""
    s = session(work, B)
    s.read(UNIT)
    s.lock(UNIT, READING)
    s.show(UNIT)
    get, _ = routes(work)
    d = get({"reviewer": [B]})["drafts"][UNIT]
    assert (d["stage"], d["reading"], d["source_sha256"]) == ("compare", READING, PINS)
    # The page cannot begin it again or change the locked reading.
    refused("order", page, work, B, "begin", unit=UNIT)
    page(work, B, "edit", unit=UNIT, stage="compare",
         fields={"comparison": "Draft", "checklist": {"setting": "matches"}})
    st = page(work, B, "decide", unit=UNIT, verdict="cannot determine",
              comparison="The constant's dependence is not stated.",
              detail="May C depend on n?", checklist={"constants": "unsure", "setting": None},
              coverage={"coverage": "unresolved", "would_decide": "The paper's Section 2."},
              shown={"fingerprints": {s.unit(UNIT)["name"]: "fp-big"}}, show_author=True)
    d = st["drafts"][UNIT]
    assert d["stage"] == "author" and d["author_shown_at"] >= d["decided_at"]
    assert d["checklist"] == {"constants": "unsure"}
    # Back in the terminal: the author's review was shown, so the report can be finished.
    r = session(work, B).submit(UNIT, "none")
    assert r["correspondence"] == {"coverage": "unresolved",
                                   "would_decide": "The paper's Section 2."}
    assert r["comparison"]["checklist"] == {"constants": "unsure"}
    assert r["issue_draft"]["kind"] == "unresolved question"
    assert "defect" not in json.dumps(r["issue_draft"])
    out = tmp_path / "reports.json"
    session(work, B).export(out)
    body = json.loads(out.read_text())
    assert body["reports"] == [r] and body["workspace"]["mode"] == "independent"


def test_the_independent_locks_hold_through_the_service(work):
    refused("order", page, work, A, "decide", unit=UNIT, verdict="faithful", comparison="c")
    page(work, A, "begin", unit=UNIT)
    refused("order", page, work, A, "author", unit=UNIT)
    refused("order", page, work, A, "submit", unit=UNIT, disagreements="none")
    refused("invalid", page, work, A, "lock", unit=UNIT, reading="too short")
    page(work, A, "lock", unit=UNIT, reading=READING)
    refused("order", page, work, A, "author", unit=UNIT)
    refused("order", page, work, A, "submit", unit=UNIT, disagreements="none")
    page(work, A, "decide", unit=UNIT, verdict="faithful", comparison="Same statement.")
    refused("order", page, work, A, "submit", unit=UNIT, disagreements="none")
    refused("order", page, work, A, "lock", unit=UNIT, reading=READING + " Changed.")
    refused("order", page, work, A, "decide", unit=UNIT, verdict="mismatched",
            comparison="c", detail="d")
    page(work, A, "author", unit=UNIT)
    st = page(work, A, "submit", unit=UNIT, disagreements="none")
    t = st["report"]
    assert t["reading"]["locked_at"] <= t["comparison"]["decided_at"] <= \
        t["author_review"]["shown_at"] <= t["submitted_at"]
    refused("reported", page, work, A, "begin", unit=UNIT)
    # Undo takes the report back to step 3, its reading and verdict as recorded.
    st = page(work, A, "undo")
    d = st["drafts"][UNIT]
    assert st["reports"] == [] and d["stage"] == "author"
    assert (d["reading"], d["verdict"], d["locked_at"]) == (
        READING, "faithful", t["reading"]["locked_at"])
    refused("order", page, work, A, "lock", unit=UNIT, reading=READING)


def test_a_changed_build_or_draft_is_refused_and_nothing_is_lost(work):
    page(work, A, "begin", unit=UNIT)
    page(work, A, "lock", unit=UNIT, reading=READING)
    # The page drew other Lean than the build now holds.
    e = refused("stale", page, work, A, "decide", unit=UNIT, verdict="faithful", comparison="c",
                shown={"fingerprints": {"Syn.other": "fp-old"}})
    assert e.to_json()["kind"] == "stale"
    # The terminal showed the Lean; the build changed it since.
    s = session(work, A)
    s.show(UNIT)
    data = work / "site" / "data"
    q = json.loads((data / "review-queue.json").read_text())
    q["units"][0]["fingerprints"] = {q["units"][0]["name"]: "fp-new"}
    (data / "review-queue.json").write_text(json.dumps(q))
    refused("stale", session(work, A).decide, UNIT, "faithful", "Same.")
    assert session(work, A).draft(session(work, A).unit(UNIT))["reading"] == READING
    session(work, A).show(UNIT)
    # A unit the build no longer has keeps its draft.
    q["units"][0]["id"] = "link:thm:renamed"
    (data / "review-queue.json").write_text(json.dumps(q))
    e = refused("unknown-unit", session(work, A).decide, UNIT, "faithful", "Same.")
    assert "your draft of it is kept" in str(e)
    assert UNIT in wsp.read(wsp.store(work) / "human_Page-Reviewer.json")["review"]["drafts"]
    q["units"][0]["id"] = UNIT
    (data / "review-queue.json").write_text(json.dumps(q))
    # Two windows: the one that read the draft before the other moved it on saves nothing.
    late = session(work, A)
    session(work, A).decide(UNIT, "faithful", "Same statement.")
    e = refused("conflict", late.decide, UNIT, "broader", "Wider.", detail="Take m = n.")
    (c,) = e.conflicts
    assert c["current"]["verdict"] == "faithful" and c["proposed"]["verdict"] == "broader"
    assert session(work, A).draft(late.unit(UNIT))["verdict"] == "faithful"


def test_the_local_server_answers_a_refusal_with_its_kind(work):
    httpd = make_server(work / "site", 0, api=wsp.api(work, work / "site" / "data"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/api/review"

    def post(body):
        req = urllib.request.Request(base, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    try:
        with urllib.request.urlopen(base + "?reviewer=" + A, timeout=10) as r:
            assert json.loads(r.read())["drafts"] == {}
        assert post({"reviewer": A, "action": "begin", "unit": UNIT})["ok"]
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"reviewer": A, "action": "author", "unit": UNIT})
        assert e.value.code == 400
        got = json.loads(e.value.read())
        assert got["kind"] == "order" and "needs step 'author'" in got["error"]
        with pytest.raises(urllib.error.HTTPError) as e:
            post({"reviewer": A, "action": "begin", "unit": "link:nothing"})
        assert json.loads(e.value.read())["kind"] == "unknown-unit"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_an_informed_session_reports_without_a_blind_reading(work):
    """No step is locked; the report keeps no reading the reviewer did not give, lists the
    informed investigation's exposure, and says it is informed."""
    s = session(work, A, mode="informed")
    assert s.informed and s.path.exists()
    assert "Syn.big_bound_" in s.show(UNIT)          # no lock first
    assert "AUTHOR-MARKER" in s.author(UNIT)          # nor a verdict
    refused("order", s.submit, UNIT, "none")          # a report needs a verdict
    s.decide(UNIT, "faithful", "Same statement.", coverage={"coverage": "full",
                                                            "basis": "reviewed_composition",
                                                            "argument": "Chain the bounds."})
    s.decide(UNIT, "faithful", "Same statement, read again.")   # editable until submitted
    r = s.submit(UNIT, "none")
    wid = s.workspace["id"]
    assert r["mode"] == "informed"
    assert (r["reading"]["text"], r["reading"]["locked_at"]) == ("", None)
    assert {(x["unit"], x["what"]) for x in r["reading"]["revealed_by"]} == {
        (f"workspace {wid} (informed investigation)", "Lean"),
        (f"workspace {wid} (informed investigation)", "author's review")}
    assert r["comparison"]["text"] == "Same statement, read again."
    # The same reviewer's independent workspace is another one, and its reading is not blind
    # either: the reviewer worked in the informed one, and reported the unit there.
    ind = session(work, A, mode="independent")
    assert ind.path != s.path and not ind.informed
    _, seen = ind.begin(UNIT)
    assert {x["unit"] for x in seen} == {f"workspace {wid} (informed investigation)",
                                         f"{UNIT} (workspace {wid})"}
    # A mode is chosen when a workspace is opened, not by naming it again.
    refused("workspace", session, work, A, workspace=wid, mode="independent")
    refused("workspace", session, work, B, workspace=wid)


def test_an_informed_reading_is_kept_with_its_time(work):
    s = session(work, A, mode="informed")
    s.show(UNIT)
    s.lock(UNIT, READING)
    d = s.draft(s.unit(UNIT))
    assert d["locked_at"] and d["revealed_by"]
    s.decide(UNIT, "faithful", "Same statement.")
    refused("order", s.lock, UNIT, READING + " Again.")   # the verdict was made with it
    s.author(UNIT)
    r = s.submit(UNIT, "none")
    assert (r["mode"], r["reading"]["text"]) == ("informed", READING)
    assert r["reading"]["locked_at"] <= r["comparison"]["decided_at"] <= \
        r["author_review"]["shown_at"]


def test_the_command_line_chooses_the_workspace_and_says_why_it_refuses(work, monkeypatch,
                                                                          capsys):
    root = work.parent
    (root / "lakefile.toml").write_text('name = "syn"\n')
    (root / ".machinechecked").symlink_to(work, target_is_directory=True)
    monkeypatch.chdir(root)
    who = ["--as", A]

    def run(*args):
        cli.main(["review", *args, *who])
        return capsys.readouterr().out

    # The reviewer's first workspace, which the review page uses too, is independent.
    assert json.loads(run("status", "--json"))["workspace"] == {"id": None, "mode": "independent"}
    run("read", UNIT)
    first = json.loads(run("status", "--json"))["workspace"]
    assert first["mode"] == "independent" and first["id"].startswith("ws-")
    # An informed one is opened beside it, and chosen by its mode or its id.
    st = json.loads(run("status", "--json", "--mode", "informed"))
    wid = st["workspace"]["id"]
    assert st["workspace"]["mode"] == "informed" and wid != first["id"]
    assert "Syn.big_bound_" in run("show", UNIT, "--workspace", wid)
    assert f"workspace {wid} (informed; your readings here are not blind)" in run(
        "status", "--mode", "informed")
    # In the first, the Lean is shown only after the lock; --json says why, as data.
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "show", UNIT, "--json", *who])
    assert e.value.code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["error"]["kind"] == "order"
    assert "lock your reading first" in out["error"]["message"]
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "read", "link:nothing", "--json", *who])
    assert json.loads(capsys.readouterr().out)["error"]["kind"] == "unknown-unit"
