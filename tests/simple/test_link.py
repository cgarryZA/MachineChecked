"""`machinechecked link` (#123): links recorded from the command line are checked against the
last build, are the records the reader's buttons write, and run no Lean."""

import json
import shutil

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import authoring, cli, simple
from prooflens.simple import built_modules
from prooflens.targets import Snapshot

PLAIN = ROOT / "examples" / "plain-paper"
PAPER = "paper/main.tex"


@pytest.fixture
def plain(tmp_path, monkeypatch, capsys):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"),
        symlinks=True)
    if not built_modules(dst, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    monkeypatch.chdir(dst)
    cli.main(["build"])
    capsys.readouterr()
    return dst


def link(capsys, *args):
    """Run `link --json`; return its exit code and document."""
    try:
        cli.main(["link", *args, "--json"])
        code = 0
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def entry(root, key):
    e = dict(simple.load_links(root)["papers"][PAPER].get(key) or {})
    e.pop("at", None)
    return e


def reader(root, req):
    return authoring.from_reader(root, PAPER, Snapshot(root / ".machinechecked/site/data"), req)


@needs_lean
@needs_tex
def test_cli_and_reader_record_the_same_links(plain, capsys):
    code, out = link(capsys, "theorem 2", "Plain.oddSum_eq_sq")
    assert code == 0 and out["written"] and out["claim"]["id"] == "P:thm:sum-odd"
    assert out["declarations"] == [{"name": "Plain.oddSum_eq_sq", "module": "Plain.Sums",
                                    "build": "built"}]
    by_number = entry(plain, "thm:sum-odd")
    link(capsys, "P:thm:sum-odd", "--clear")
    assert "thm:sum-odd" not in simple.load_links(plain)["papers"][PAPER]
    link(capsys, "thm:sum-odd", "Plain.oddSum_eq_sq")
    by_key = entry(plain, "thm:sum-odd")
    link(capsys, "thm:sum-odd", "--clear")
    reader(plain, {"key": "thm:sum-odd", "lean": ["Plain.oddSum_eq_sq"]})
    assert by_number == by_key == entry(plain, "thm:sum-odd") == {"lean": ["Plain.oddSum_eq_sq"]}

    link(capsys, "3", "--reject", "Plain.sq_odd")
    by_cli = entry(plain, "thm:square")
    reader(plain, {"key": "thm:square", "lean": None})
    reader(plain, {"key": "thm:square", "reject": ["Plain.sq_odd"]})
    assert by_cli == entry(plain, "thm:square") == {"rejected": ["Plain.sq_odd"]}
    # Clearing the confirmed list keeps the claim's rejections.
    link(capsys, "thm:square", "Plain.odd_add_odd")
    link(capsys, "thm:square", "--clear")
    assert entry(plain, "thm:square") == {"rejected": ["Plain.sq_odd"]}


@needs_lean
@needs_tex
def test_unknown_names_are_refused_with_candidates_and_nothing_is_written(plain, capsys):
    code, out = link(capsys, "Theorem 9", "Plain.oddSum_eq_sq")
    assert code == 1 and not out["ok"] and not out["written"]
    assert {c["id"] for c in out["error"]["candidates"]} <= {"P:thm:odd-add", "P:thm:sum-odd",
                                                             "P:thm:square", "P:lem:open"}
    code, out = link(capsys, "Theorem 2", "oddSum_eq_sq")
    assert code == 1 and out["error"]["candidates"] == [{"name": "Plain.oddSum_eq_sq"}]
    code, out = link(capsys, "Theorem 2", "Plain.no_such_theorem")
    assert code == 1
    code, out = link(capsys, "Theorem 2", "--coverage", "mostly")
    assert code == 1 and "coverage" in out["error"]["message"]
    assert not simple.links_file(plain).exists()
    # A declaration from a dependency is accepted only when said so; Lean checks it at the
    # next build.
    code, out = link(capsys, "Theorem 2", "Nat.add_comm", "--external", "--dry-run")
    assert code == 0 and out["declarations"][0]["build"] == "external" and not out["written"]
    assert not simple.links_file(plain).exists()


@needs_lean
@needs_tex
def test_an_unbuilt_declaration_is_saved_with_its_build_state(plain, capsys):
    (plain / "Plain" / "Extra.lean").write_text(
        "namespace Plain\n\ntheorem extra_fact : True := trivial\n\nend Plain\n")
    code, out = link(capsys, "Lemma 4", "Plain.extra_fact")
    assert code == 0 and out["declarations"] == [{"name": "Plain.extra_fact",
                                                  "module": "Plain.Extra", "build": "unbuilt"}]
    view = simple.build_view(plain, plain / PAPER, plain / ".machinechecked", log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["key"] == "lem:open")
    assert [l["status_code"] for l in c["links"]] == ["link.module-unbuilt"]


@needs_lean
@needs_tex
def test_a_note_survives_exactly_and_editing_runs_no_lean(plain, capsys, monkeypatch, tmp_path):
    def no_lean(*a, **k):
        raise AssertionError("a link edit ran the Lean probe")
    probe = simple.run_simple_probe
    monkeypatch.setattr(simple, "run_simple_probe", no_lean)
    note = 'The paper writes "Σ_{i<n} (2i+1) = n²";\nLean recurses on n — the same sum.\n'
    f = tmp_path / "note.md"
    f.write_text(note, encoding="utf-8")
    code, out = link(capsys, "Theorem 2", "Plain.oddSum_eq_sq", "--coverage", "full",
                     "--confidence", "high", "--note-file", str(f), "--as", "A. Auditor")
    assert code == 0 and out["after"]["note"] == note
    assert entry(plain, "thm:sum-odd") == {"lean": ["Plain.oddSum_eq_sq"], "note": note,
                                           "coverage": "full", "confidence": "high",
                                           "by": "A. Auditor"}
    # Linking one more declaration keeps the note, no longer shown, under earlier_notes.
    link(capsys, "Theorem 2", "Plain.Odd", "--add")
    e = entry(plain, "thm:sum-odd")
    assert e["lean"] == ["Plain.oddSum_eq_sq", "Plain.Odd"] and "note" not in e
    assert e["earlier_notes"][0]["note"] == note
    assert e["earlier_notes"][0]["lean"] == ["Plain.oddSum_eq_sq"]
    monkeypatch.setattr(simple, "run_simple_probe", probe)
    link(capsys, "Theorem 2", "Plain.oddSum_eq_sq", "--note-file", str(f), "--coverage", "full")
    view = simple.build_view(plain, plain / PAPER, plain / ".machinechecked", log=lambda m: None)
    c = next(c for c in view["body"]["claims"] if c["key"] == "thm:sum-odd")
    assert c["correspondence"]["note"] == note.strip()


@needs_lean
@needs_tex
def test_a_stale_link_write_is_refused(plain):
    snap = Snapshot(plain / ".machinechecked/site/data")
    change = authoring.plan(plain, PAPER, snap, "Theorem 2", lean=["Plain.oddSum_eq_sq"])
    reader(plain, {"key": "thm:sum-odd", "lean": ["Plain.Odd"]})       # someone else, meanwhile
    with pytest.raises(authoring.LinkError) as e:
        authoring.write(plain, change)
    assert e.value.kind == "conflict" and e.value.candidates[0]["lean"] == ["Plain.Odd"]
    assert entry(plain, "thm:sum-odd")["lean"] == ["Plain.Odd"]


@needs_lean
@needs_tex
def test_a_reading_records_its_basis_and_keeps_every_field_when_retired(plain, capsys):
    code, out = link(capsys, "Theorem 2", "Plain.oddSum_eq_sq", "--coverage", "full",
                     "--basis", "reviewed_composition", "--argument", "Sum the two halves.",
                     "--as", "A. Auditor")
    assert code == 0
    assert entry(plain, "thm:sum-odd") == {"lean": ["Plain.oddSum_eq_sq"], "coverage": "full",
                                           "basis": "reviewed_composition",
                                           "argument": "Sum the two halves.", "by": "A. Auditor"}
    # Fields that do not belong to the reading are refused, and nothing is written.
    for args in (["--basis", "direct", "--argument", "x"],
                 ["--question", "Which?"],
                 ["--coverage", "full", "--basis", "direct", "--refs", "Plain.Odd"],
                 ["--coverage", "composed", "--basis", "direct"],
                 ["--coverage", "full", "--basis", "checked_bridge", "--bridge", "Plain.Odd",
                  "Plain.Spec"]):
        code, out = link(capsys, "Theorem 2", *args)
        assert code == 1 and not out["written"], args
    # Every field of the reading moves to earlier_notes when the list changes.
    link(capsys, "Theorem 2", "Plain.Odd", "--add")
    e = entry(plain, "thm:sum-odd")
    assert not {"coverage", "basis", "argument"} & set(e)
    old = e["earlier_notes"][0]
    assert (old["coverage"], old["basis"], old["argument"]) == \
        ("full", "reviewed_composition", "Sum the two halves.")
    # `composed` is recorded as full coverage by the auditor's composition.
    code, out = link(capsys, "Theorem 2", "--coverage", "composed", "--argument", "Combine.")
    assert code == 0
    e = entry(plain, "thm:sum-odd")
    assert (e["coverage"], e["basis"], e["argument"]) == ("full", "reviewed_composition",
                                                          "Combine.")
    # An unresolved reading keeps its question; changing the coverage drops the basis.
    code, out = link(capsys, "Theorem 2", "--coverage", "unresolved", "--question", "Which n?",
                     "--would-decide", "Section 1.")
    e = entry(plain, "thm:sum-odd")
    assert code == 0 and (e["question"], e["would_decide"]) == ("Which n?", "Section 1.")
    assert not {"basis", "argument"} & set(e)


def test_a_stored_composed_entry_is_written_back_as_full_by_composition(tmp_path):
    entry = {"lean": ["A.b"], "coverage": "composed", "note": "Chain the estimates."}
    authoring._tidy_reading(entry)
    assert entry == {"lean": ["A.b"], "coverage": "full", "basis": "reviewed_composition",
                     "argument": "Chain the estimates."}
