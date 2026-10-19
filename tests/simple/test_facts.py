"""The facts store (`prooflens.facts`): zero configuration reuses the Lean facts it extracted.

On a copy of the plain example (`Plain.Basic`, `Plain.Sums` importing it, and `Plain` importing
both), Lean sessions are counted by spying on the probe. An edit that does not touch Lean (a
note, a coverage, a reviewer's name, the order of links, the paper's layout, a link to a
declaration already extracted) starts no Lean session; a Lean change re-extracts what it
affects and nothing else, and the statuses always describe the Lean as it now is.
"""

import json
import shutil
import subprocess
import sys
import threading

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import facts, simple
from prooflens.simple import StaleLean, build_view, built_modules, save_link
from prooflens.util import content_id

PLAIN = ROOT / "examples" / "plain-paper"
PAPER = "paper/main.tex"
PROOF = """theorem oddSum_eq_sq (n : Nat) : oddSum n = n * n := by
  induction n with
  | zero => rfl
  | succ k ih => rw [oddSum, ih, Nat.add_mul, Nat.mul_add, Nat.one_mul, Nat.mul_one]; omega"""


@pytest.fixture
def plain(tmp_path, monkeypatch):
    """A built copy of the plain example, and the Lean sessions each build starts."""
    if not built_modules(PLAIN, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, symlinks=True, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"))
    sessions, real = [], simple.run_simple_probe

    def spy(root, modules, libs, requests, *a, **k):
        sessions.append({"modules": sorted(modules),
                         "links": {r["name"] for r in requests if r["kind"] == "link"},
                         "kinds": {r["kind"] for r in requests}})
        return real(root, modules, libs, requests, *a, **k)
    monkeypatch.setattr(simple, "run_simple_probe", spy)
    return dst, sessions


def view(root, said=None, **kw):
    return build_view(root, root / PAPER, root / ".machinechecked",
                      log=(said.append if said is not None else lambda m: None), **kw)


def statuses(v):
    return {c["number"]: c["status"] for c in v["body"]["claims"]}


def lake_build(root):
    r = subprocess.run(["lake", "build"], cwd=root, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr


def edit_links(root, key, **fields):
    p = root / "machinechecked.links.json"
    data = json.loads(p.read_text())
    data["papers"][PAPER][key].update(fields)
    p.write_text(json.dumps(data))


@needs_lean
@needs_tex
def test_an_edit_outside_lean_starts_no_lean_session(plain):
    root, sessions = plain
    save_link(root, PAPER, "thm:sum-odd", ["Plain.oddSum_eq_sq"])
    first = view(root)
    assert sessions and first["lean"]["sessions"] == len(sessions)
    st = statuses(first)
    assert st["Theorem 2"] == "linked: Lean proof incomplete (sorry)"

    edits = [
        # a note with its coverage and confidence, and the reviewer's name
        lambda: edit_links(root, "thm:sum-odd", note="States the sum.", coverage="full",
                           confidence="high", by="A. Reader"),
        # two links to declarations already extracted (one linked, one suggested), in turn
        # reordered
        lambda: save_link(root, PAPER, "thm:odd-add", ["Plain.odd_add_odd", "Plain.sq_odd"]),
        lambda: save_link(root, PAPER, "thm:odd-add", ["Plain.sq_odd", "Plain.odd_add_odd"]),
        # the paper's layout
        lambda: (root / PAPER).write_text((root / PAPER).read_text().replace(
            r"\section{Results}", "\\section{Results}\n\nThe results, briefly.\n\\medskip")),
    ]
    for change in edits:
        sessions.clear()
        change()
        v = view(root)
        assert sessions == [] and v["lean"]["sessions"] == 0
        assert statuses(v)["Theorem 2"] == st["Theorem 2"]
    c = next(c for c in v["body"]["claims"] if c["number"] == "Theorem 1")
    assert [l["name"] for l in c["links"]] == ["Plain.sq_odd", "Plain.odd_add_odd"]
    assert all(l["status"] == "linked: Lean proof checked" for l in c["links"])
    assert all(l["record"]["closure"] is not None for l in c["links"])


@needs_lean
@needs_tex
def test_a_new_link_loads_only_the_module_that_declares_it(plain):
    root, sessions = plain
    view(root)
    sessions.clear()
    save_link(root, PAPER, "lem:open", ["Plain.oddSum"])
    v = view(root)
    assert [(s["modules"], s["links"]) for s in sessions] == [(["Plain.Sums"], {"Plain.oddSum"})]
    assert statuses(v)["Lemma 4"] == "linked: Lean definition"
    sessions.clear()
    view(root)
    assert sessions == []


@needs_lean
@needs_tex
def test_a_lean_change_reextracts_what_it_affects_and_nothing_else(plain):
    root, sessions = plain
    save_link(root, PAPER, "thm:sum-odd", ["Plain.oddSum_eq_sq"])
    before = statuses(view(root))
    assert before["Theorem 2"] == "linked: Lean proof incomplete (sorry)"

    # Prove the theorem: its module and the module importing it are indexed again, and the new
    # record is shown; the facts of `Plain.Basic`, which imports neither, are reused.
    sums = root / "Plain" / "Sums.lean"
    sums.write_text(sums.read_text().replace(
        "theorem oddSum_eq_sq (n : Nat) : oddSum n = n * n := by\n  sorry", PROOF))
    lake_build(root)
    sessions.clear()
    said = []
    after = statuses(view(root, said))
    assert after["Theorem 2"] == "linked: Lean proof checked"
    assert {k: v for k, v in after.items() if k != "Theorem 2"} == \
        {k: v for k, v in before.items() if k != "Theorem 2"}
    assert sessions and all(set(s["modules"]) <= {"Plain", "Plain.Sums"} for s in sessions)
    asked = set().union(*(s["links"] for s in sessions))
    assert "Plain.oddSum_eq_sq" in asked
    assert not asked & {"Plain.odd_add_odd", "Plain.sq_odd"}
    assert any("changed: Plain.Sums" in m for m in said)

    # A change to an imported module reopens what its importers extracted.
    basic = root / "Plain" / "Basic.lean"
    basic.write_text(basic.read_text() + "\n-- a comment\n")
    lake_build(root)
    sessions.clear()
    assert statuses(view(root)) == after
    asked = set().union(*(s["links"] for s in sessions))
    assert {"Plain.oddSum_eq_sq", "Plain.odd_add_odd"} <= asked


@needs_lean
@needs_tex
def test_a_probe_change_reopens_every_record(plain, monkeypatch):
    root, sessions = plain
    first = statuses(view(root))
    sessions.clear()
    monkeypatch.setattr(facts, "probe_digest", lambda: "another probe")
    said = []
    assert statuses(view(root, said)) == first
    assert sessions and any("the Lean probe changed" in m for m in said)


@needs_lean
@needs_tex
def test_reuse_lean_starts_no_session_and_names_what_is_missing(plain):
    root, sessions = plain
    first = statuses(view(root))
    sessions.clear()
    assert statuses(view(root, reuse_only=True)) == first and sessions == []

    sums = root / "Plain" / "Sums.lean"
    sums.write_text(sums.read_text() + "\n-- a comment\n")
    lake_build(root)
    with pytest.raises(StaleLean) as e:
        view(root, reuse_only=True)
    assert sessions == []
    assert "module(s) to index" in str(e.value) and "Plain.Sums" in str(e.value)
    assert "without `--reuse-lean`" in str(e.value)

    # The command stops with exit code 2 and the same account.
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "build", "--reuse-lean"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 2 and "Plain.Sums" in r.stderr, r.stderr
    # Without the flag the build extracts what changed; then reuse alone suffices again.
    view(root)
    sessions.clear()
    assert statuses(view(root, reuse_only=True)) == first and sessions == []


@needs_lean
@needs_tex
def test_deleting_the_store_reproduces_the_same_facts(plain):
    root, sessions = plain
    save_link(root, PAPER, "thm:sum-odd", ["Plain.oddSum_eq_sq"])
    links = (root / "machinechecked.links.json").read_bytes()
    cold = view(root)["body"]
    warm = view(root)["body"]
    assert content_id(warm) == content_id(cold)
    shutil.rmtree(root / ".machinechecked" / "build" / facts.DIR)
    sessions.clear()
    again = view(root)["body"]
    assert sessions and content_id(again) == content_id(cold)
    assert (root / "machinechecked.links.json").read_bytes() == links


@needs_lean
@needs_tex
def test_a_module_that_fails_to_load_keeps_the_others_facts(plain, monkeypatch):
    root, sessions = plain
    real = simple.run_simple_probe

    def failing(root_, modules, *a, **k):
        if {"Plain", "Plain.Sums"} & set(modules):
            raise simple.ViewError("the Lean probe failed (1):\nerror: synthetic failure")
        return real(root_, modules, *a, **k)
    monkeypatch.setattr(simple, "run_simple_probe", failing)
    v = view(root)
    assert any("2 built module(s) could not be loaded" in n for n in v["body"]["notes"])
    assert statuses(v)["Theorem 1"] == "linked: Lean proof checked"

    # The failure is recorded with the facts that were extracted: the next build starts no
    # session, and still reports the modules it could not load.
    monkeypatch.setattr(simple, "run_simple_probe", real)
    sessions.clear()
    v = view(root)
    assert v["lean"]["sessions"] == 0
    assert any("2 built module(s) could not be loaded" in n for n in v["body"]["notes"])
    assert statuses(v)["Theorem 1"] == "linked: Lean proof checked"

    # Forgetting the recorded failures loads those modules again, and only those.
    facts.Store(root, [], root / ".machinechecked" / "build", []).drop("failed")
    spied = []
    monkeypatch.setattr(simple, "run_simple_probe",
                        lambda r, m, *a, **k: spied.append(sorted(m)) or real(r, m, *a, **k))
    v = view(root)
    assert not any("could not be loaded" in n for n in v["body"]["notes"])
    assert spied and all(set(m) <= {"Plain", "Plain.Sums"} for m in spied)


@needs_lean
def test_concurrent_identical_inspections_extract_once(plain, monkeypatch):
    from prooflens import deps
    root, _ = plain
    calls, real = [], deps.probe_modules

    def spy(*a, **k):
        calls.append(a[1])
        return real(*a, **k)
    monkeypatch.setattr(deps, "probe_modules", spy)
    out = [None, None]

    def ask(i):
        out[i] = deps.inspect(root, "Plain.oddSum_eq_sq")
    threads = [threading.Thread(target=ask, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1
    assert sorted(o["cache"]["hit"] for o in out) == [False, True]
    strip = lambda o: {k: v for k, v in o.items() if k != "cache"}
    assert strip(out[0]) == strip(out[1]) and out[0]["ok"]
