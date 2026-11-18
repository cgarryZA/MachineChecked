"""One reading for several definitions printed in one passage (#616): `review read UNIT --with
UNIT ...` shows their passages once and begins each unit's draft, and `review lock UNIT READING
--with UNIT ...` locks one reading for them all, only when they are definitions read from exactly
the same complete passages, and only after every unit's order is checked. Each is then shown with
its own Lean and takes its own verdict and report, pinned to its own definition. The group is
these steps' alone. The site is synthetic; nothing here builds Lean."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from test_compare import seg

WHO = "human:Shared-Reviewer"
PASSAGE = (r"\begin{definition}\label{def:grid}" "\n"
           r"Fix $N \ge 1$, let $h = T / N$, $t_n = n h$ and $\Delta W_n = W_{t_{n+1}} - "
           r"W_{t_n}$." "\n" r"\end{definition}")
THEOREM = r"\begin{theorem}\label{thm:conv}The scheme converges on the grid $t_n$.\end{theorem}"
READING = ("The time step is T over N; the grid points are its multiples; the increments are "
           "those of the Brownian motion between consecutive grid points.")
SAME = ["def:Syn.step", "def:Syn.grid", "def:Syn.incr"]
OTHER = "def:Syn.mesh"


def claim(cid, kind, number, text, line):
    return {"id": cid, "key": cid.split(":", 1)[1], "paper": "S", "kind": kind,
            "number": number, "heading": None, "location": "main.tex",
            "anchor": {"kind": "exact", "file": "main.tex", "line": line,
                       "label": cid.split(":", 1)[1]},
            "statement_tex": text, "source_sha256": f"{line:064x}", "links": [], "clauses": [],
            "status": "reviewed by an author", "findings": [], "reviews": [], "symbols": []}


CLAIMS = [claim("S:def:grid", "definition", "Definition 1", PASSAGE, 3),
          claim("S:thm:conv", "theorem", "Theorem 2", THEOREM, 9)]
DEFS = {"Syn.step": "fun T N => T / N", "Syn.grid": "fun T N n => n * Syn.step T N",
        "Syn.incr": "fun W T N n => W (Syn.grid T N (n + 1)) - W (Syn.grid T N n)",
        "Syn.mesh": "fun T N => Syn.step T N"}


def legacy(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()


def unit(name, claims, **more):
    return {"id": f"def:{name}", "kind": "def", "name": name, "lean": [name],
            "claims": [{"id": c} for c in claims], "papers": ["S"], "state": "pending",
            "reason": "Short definition", "fingerprint": f"fp-{name}",
            "legacy_hash": legacy(name),
            "source_sha256": {c: next(x["source_sha256"] for x in CLAIMS if x["id"] == c)
                              for c in claims}, **more}


UNITS = [unit("Syn.step", ["S:def:grid"]),
         # Step 2 of the grid shows the time step's Lean too.
         unit("Syn.grid", ["S:def:grid"], reveals={"lean": ["def:Syn.step"]}),
         unit("Syn.incr", ["S:def:grid"]),
         unit("Syn.mesh", ["S:def:grid", "S:thm:conv"], reveals={"lean": ["def:Syn.step"]}),
         {"id": "link:thm:conv", "kind": "link", "name": "Syn.conv", "lean": ["Syn.conv"],
          "claims": [{"id": "S:thm:conv"}], "papers": ["S"], "state": "pending",
          "reason": "Short", "fingerprint": "fp-conv"}]


@pytest.fixture
def work(tmp_path, monkeypatch):
    work = tmp_path / "proj" / ".machinechecked"
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    for ch in CLAIMS:
        (data / "claims" / f"{ch['key']}.json").write_text(json.dumps(ch), encoding="utf-8")
    for i, (name, value) in enumerate(DEFS.items()):
        (data / "decls" / f"{i:024x}.json").write_text(json.dumps(
            {"name": name, "kind": "def", "module": "Syn.Grid", "fingerprint": f"fp-{name}",
             "signature": seg("ℝ → ℕ → ℝ"), "value": seg(value), "uses": []}),
            encoding="utf-8")
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "v-shared",
        "project": {"name": "syn"}, "papers": [{"id": "S", "title": "Synthetic"}],
        "claims": [{"id": ch["id"], "paper": "S", "number": ch["number"], "kind": ch["kind"],
                    "file": f"{ch['key']}.json"} for ch in CLAIMS]}), encoding="utf-8")
    (data / "review-queue.json").write_text(json.dumps({
        "schema": "prooflens/review-queue@1", "release": "v-shared", "mode": "simple",
        "units": UNITS}), encoding="utf-8")
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reading.md").write_text(READING, encoding="utf-8")
    (tmp_path / "cmp.md").write_text("The Lean definition is the printed one.", encoding="utf-8")
    (tmp_path / "none.md").write_text("none", encoding="utf-8")
    (tmp_path / "detail.md").write_text("It states the increment over two steps.",
                                        encoding="utf-8")
    return work


def run(capsys, *args):
    """A review step: its exit status, what it printed, and what it said on standard error."""
    try:
        cli.main(["review", *args, "--as", WHO])
        code = 0
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def drafts(work):
    return rc.Session(work, rc.parse_reviewer(WHO)).work["drafts"]


def together(*units):
    return [x for u in units for x in ("--with", u)]


def test_definitions_of_one_passage_are_read_once_and_locked_with_one_reading(work, capsys):
    code, text, _ = run(capsys, "read", SAME[0], *together(*SAME[1:]))
    assert code == 0
    assert text.startswith("The passages below are the whole of the reading material of "
                           "def:Syn.step, def:Syn.grid and def:Syn.incr. Read them once: "
                           "`review lock def:Syn.step READING --with def:Syn.grid --with "
                           "def:Syn.incr` locks one reading for them all.")
    assert text.count(r"\Delta W_n") == 1
    # Step 1 shows the paper only.
    assert "Syn.step T N" not in text and "fun T N" not in text
    doc = json.loads(run(capsys, "read", SAME[0], *together(*SAME[1:]), "--json")[1])
    assert doc["review"]["units"] == SAME and [u["id"] for u in doc["units"]] == SAME
    assert [p["claim"] for p in doc["paper"]["passages"]] == ["S:def:grid"]
    assert "lean" not in doc
    assert {u: d["stage"] for u, d in drafts(work).items()} == dict.fromkeys(SAME, "read")

    code, said, _ = run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]), "--json")
    assert code == 0
    res = json.loads(said)
    assert res["ok"] and [x["unit"] for x in res["locked_with"]] == SAME[1:]
    assert res["revealed_by"] == [] and all(x["revealed_by"] == [] for x in res["locked_with"])
    ds = drafts(work)
    assert {ds[u]["stage"] for u in SAME} == {"compare"}
    assert len({ds[u]["locked_at"] for u in SAME}) == 1
    assert {ds[u]["reading"] for u in SAME} == {READING}
    assert ds["def:Syn.grid"]["source_sha256"] == UNITS[1]["source_sha256"]

    # Each is shown with its own Lean, named; the grid's shows the time step's, whose reading
    # is already locked, so nothing is revealed.
    code, text, _ = run(capsys, "show", "def:Syn.grid")
    assert text.startswith("Your reading of def:Syn.grid was locked with that of def:Syn.incr "
                           "and def:Syn.step, from the same passages. This is the Lean of "
                           "def:Syn.grid alone")
    assert "NOTE" not in text and "fun T N n => n * Syn.step T N" in text
    pk = json.loads(run(capsys, "show", "def:Syn.incr", "--json")[1])
    assert pk["review"]["locked_with"] == ["def:Syn.grid", "def:Syn.step"]
    assert pk["review"]["reveals"] == []

    # A verdict of its own for each, and a report of its own, pinned to its definition.
    run(capsys, "show", "def:Syn.step")
    for u, verdict in zip(SAME, ("faithful", "faithful", "mismatched")):
        detail = ["--detail", "detail.md"] if verdict == "mismatched" else []
        assert run(capsys, "decide", u, verdict, "cmp.md", *detail)[0] == 0
        run(capsys, "author", u)
        assert run(capsys, "submit", u, "none.md")[0] == 0
    reports = {r["unit"]["id"]: r for r in rc.Session(work, rc.parse_reviewer(WHO))
               .work["reports"]}
    assert sorted(reports) == sorted(SAME)
    assert [reports[u]["verdict"]["value"] for u in SAME] == ["faithful", "faithful",
                                                              "mismatched"]
    assert [reports[u]["pins"]["fingerprint"] for u in SAME] == [f"fp-{u[4:]}" for u in SAME]
    assert {reports[u]["reading"]["text"] for u in SAME} == {READING}
    # The grid's step 2 showed the time step's Lean after both readings were locked, in the same
    # second: the time step's reading is still blind.
    assert all(reports[u]["reading"]["revealed_by"] == [] for u in SAME)
    # Each report is a report of its unit, which names the units its reading was locked with.
    assert reports["def:Syn.step"]["reading"]["locked_with"] == ["def:Syn.grid", "def:Syn.incr"]
    assert ("Phase 1 specification (locked " + reports["def:Syn.step"]["reading"]["locked_at"]
            + ", with def:Syn.grid, def:Syn.incr):") in pr.report_text(reports["def:Syn.step"])
    assert reports["def:Syn.step"]["unit"]["lean"] == ["Syn.step"]
    # Taken back and submitted again, the last report keeps its group, and its reading stays
    # blind.
    s = rc.Session(work, rc.parse_reviewer(WHO))
    assert s.undo()["locked_with"] == ["def:Syn.step", "def:Syn.grid"]
    assert run(capsys, "submit", SAME[2], "none.md")[0] == 0
    (again,) = [r for r in rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]
                if r["unit"]["id"] == SAME[2]]
    assert again["reading"]["revealed_by"] == [] and again["reading"]["locked_with"] == [
        "def:Syn.step", "def:Syn.grid"]


def test_a_definition_that_later_changes_is_the_only_one_reopened(work, capsys):
    run(capsys, "read", SAME[0], *together(*SAME[1:]))
    run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]))
    for u in SAME:
        run(capsys, "show", u)
        run(capsys, "decide", u, "faithful", "cmp.md")
        run(capsys, "author", u)
        run(capsys, "submit", u, "none.md")
    q = work / "site" / "data" / "review-queue.json"
    queue = json.loads(q.read_text())
    next(u for u in queue["units"] if u["id"] == "def:Syn.grid")["fingerprint"] = "fp-new"
    q.write_text(json.dumps(queue))
    s = rc.Session(work, rc.parse_reviewer(WHO))
    assert [u["id"] for u in s.open_units() if u["id"] in SAME] == ["def:Syn.grid"]


def evidence() -> dict:
    """The evidence promotion checks the reports against: the definitions, and the inventory's
    claims that use them, at the pins the queue gives."""
    pin = {c["id"]: c["source_sha256"] for c in CLAIMS}
    return {"lean": {"decls": {n: {"name": n, "kind": "def", "fingerprint": f"fp-{n}",
                                   "legacy_hash": legacy(n)} for n in DEFS}},
            "inventory": {"claims": [
                {"id": "S:def:grid", "paper": "S", "source_sha256": pin["S:def:grid"],
                 "clauses": [{"name": "main", "defs": list(DEFS)}]},
                {"id": "S:thm:conv", "paper": "S", "source_sha256": pin["S:thm:conv"],
                 "clauses": [{"name": "main", "defs": ["Syn.mesh"]}]}]},
            "tex": {}, "provenance": {"papers": {}}}


def test_the_maintainer_promotes_one_refuses_another_and_sees_which_changed(work, capsys,
                                                                           tmp_path):
    run(capsys, "read", SAME[0], *together(*SAME[1:]))
    run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]))
    for u, verdict in zip(SAME, ("faithful", "faithful", "mismatched")):
        run(capsys, "show", u)
        detail = ["--detail", "detail.md"] if verdict == "mismatched" else []
        run(capsys, "decide", u, verdict, "cmp.md", *detail)
        run(capsys, "author", u)
        run(capsys, "submit", u, "none.md")
    r = {x["unit"]["id"]: x for x in rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]}
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "definitions.md").write_text("# Definitions\n", encoding="utf-8")
    cfg = SimpleNamespace(reviews=[tmp_path / "reviews"], ai_reviewers=[], root=tmp_path,
                          statement_authors=["statement-author"])
    body = evidence()
    assert pr.check_report(r["def:Syn.step"], body, cfg, False) == []
    assert pr.check_report(r["def:Syn.grid"], body, cfg, False) == []
    assert pr.check_report(r["def:Syn.incr"], body, cfg, False) == [
        "verdict 'mismatched' is not one that is recorded as a review"]
    cur = pr.with_covers(r["def:Syn.step"], body["lean"]["decls"]["Syn.step"], body)
    (done,) = pr.apply(cfg, [(r["def:Syn.step"], cur)])
    text = (tmp_path / "reviews" / "definitions.md").read_text(encoding="utf-8")
    assert done["name"] == "Syn.step" and f"def-review: Syn.step {legacy('Syn.step')}" in text
    assert "Syn.grid" not in text and "Syn.incr" not in text
    # Later the grid's definition changes: its report no longer promotes; the others' do not move.
    body["lean"]["decls"]["Syn.grid"]["fingerprint"] = "fp-changed"
    assert pr.check_report(r["def:Syn.grid"], body, cfg, False) == [
        "the declaration changed since the review (fingerprint differs)"]
    assert pr.check_report(r["def:Syn.step"], body, cfg, False) == []


@pytest.mark.parametrize("units, why", [
    ([SAME[0], OTHER], "def:Syn.mesh is not read from exactly the passages of def:Syn.step: "
                       "review it on its own"),
    ([SAME[0], "link:thm:conv"], "link:thm:conv: only definitions are read together"),
    ([SAME[0], SAME[0]], "name two or more different units to read together"),
])
def test_only_definitions_of_exactly_the_same_passages_are_read_together(work, capsys, units,
                                                                          why):
    for step in (["read", units[0], *together(*units[1:])],
                 ["lock", units[0], "reading.md", *together(*units[1:])]):
        code, _, err = run(capsys, *step)
        assert code == 2 and why in err, err
    assert drafts(work) == {}


def test_a_shared_lock_checks_every_unit_s_order_before_recording_any(work, capsys):
    run(capsys, "read", SAME[0], *together(SAME[1]))
    code, _, err = run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]))
    assert code == 2 and "def:Syn.incr is at step 'not started'" in err, err
    assert {u: d["stage"] for u, d in drafts(work).items()} == {SAME[0]: "read", SAME[1]: "read"}
    # A reading already locked is not locked again with others.
    run(capsys, "read", SAME[2])
    run(capsys, "lock", SAME[2], "reading.md")
    code, _, err = run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]))
    assert code == 2 and "def:Syn.incr is at step 'compare'" in err, err
    assert {u: d["stage"] for u, d in drafts(work).items()} == {
        SAME[0]: "read", SAME[1]: "read", SAME[2]: "compare"}


def test_what_was_seen_of_one_unit_before_the_shared_lock_is_recorded_on_it(work, capsys):
    # Step 2 of another definition shows the time step's Lean before its reading is locked.
    run(capsys, "read", OTHER)
    run(capsys, "lock", OTHER, "reading.md")
    run(capsys, "show", OTHER)
    code, text, _ = run(capsys, "read", SAME[0], *together(*SAME[1:]))
    assert ("NOTE: you have already seen the Lean of def:Syn.step (in def:Syn.mesh). Your "
            "reading of def:Syn.step will not be blind") in text
    assert "reading of def:Syn.grid will not be blind" not in text
    code, _, err = run(capsys, "lock", SAME[0], "reading.md", *together(*SAME[1:]))
    assert code == 0 and "the reading of def:Syn.step is not blind" in err
    assert "def:Syn.grid is not blind" not in err
    ds = drafts(work)
    assert ds["def:Syn.step"]["revealed_by"] == [{"unit": OTHER, "what": "Lean"}]
    assert ds["def:Syn.grid"]["revealed_by"] == ds["def:Syn.incr"]["revealed_by"] == []


def test_a_lock_manifest_entry_names_the_units_locked_with_it(work, capsys, tmp_path):
    run(capsys, "read", SAME[0], *together(*SAME[1:]))
    (tmp_path / "m.json").write_text(json.dumps(
        [{"unit": SAME[0], "with": SAME[1:], "reading_file": "reading.md"}]))
    code, said, _ = run(capsys, "lock", "--manifest", "m.json", "--json")
    assert code == 0, said
    (e,) = json.loads(said)["entries"]
    assert e["ok"] and [x["unit"] for x in e["locked_with"]] == SAME[1:]
    assert {drafts(work)[u]["stage"] for u in SAME} == {"compare"}
    (tmp_path / "bad.json").write_text(json.dumps(
        [{"unit": OTHER, "with": "def:Syn.step", "reading": READING}]))
    code, said, _ = run(capsys, "lock", "--manifest", "bad.json")
    assert code == 2 and "with is a list of the units" in said


def test_the_ordinary_path_is_unchanged(work, capsys):
    run(capsys, "read", OTHER)
    assert run(capsys, "lock", OTHER, "reading.md")[0] == 0
    code, text, _ = run(capsys, "show", OTHER)
    assert code == 0 and "locked with" not in text
    assert "locked_with" not in json.loads(run(capsys, "show", OTHER, "--json")[1])["review"]
    run(capsys, "decide", OTHER, "faithful", "cmp.md")
    run(capsys, "author", OTHER)
    run(capsys, "submit", OTHER, "none.md")
    (r,) = rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]
    assert set(r["reading"]) == {"text", "locked_at", "revealed_by"}
