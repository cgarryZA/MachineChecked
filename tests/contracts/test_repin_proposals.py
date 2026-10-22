"""Bounds proposed from the line diff for a changed passage (#204), and the line references of
scope notes (#205), when an inventory moves to a new revision, on synthetic manuscripts."""

import json

import pytest

from prooflens.repin import LineDiff, note_references, repin_plan
from prooflens.source_regions import RegionError, collect, matches
from test_repin import NEW, OLD, commit, files, line_of, pinned, project, run, write  # noqa: F401

PARA = ("First line of the claim.\nSecond line.\nThird line.\nFourth line.\nFifth line.\n"
        "Sixth line.\nLast line of the claim.\n")
AFTER = "\nA later paragraph.\n"


def span_claim(root, cid="p", passage=PARA, **region):
    first = line_of(root, passage)
    end = first + passage.count("\n") - 1
    return pinned(root, cid, passage, source_region={"end_line": end, **region})


def test_a_rewritten_span_gets_bounds_from_the_line_diff(tmp_path):
    old = write(tmp_path / "old", "Before.\n\n", PARA, AFTER)
    claim = span_claim(old)
    new = write(tmp_path / "new", "Inserted one.\nInserted two.\n", "Before.\n\n",
                PARA.replace("Fourth line.", "Fourth line, rewritten."), AFTER)
    result, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    entry = report["claims"][0]
    assert entry["class"] == "not-found"
    start = line_of(old, PARA)
    p = entry["proposed"]
    assert p["location"] == f"paper.tex:{start + 2}"
    assert p["source_region"] == {"end_line": start + 8}
    assert p["where"] == f"line 4 of the passage (line {start + 5} of paper.tex) changed"
    assert "-Fourth line." in p["diff"] and "+Fourth line, rewritten." in p["diff"]
    assert "flagged" not in p and report["proposed"] == ["T:p"]
    # A proposal is advice: the claim keeps its place, digests and revision.
    kept = result["claims"][0]
    assert kept["location"] == claim["location"] and kept["source_region"] == \
        claim["source_region"]
    assert kept["source_sha256"] == claim["source_sha256"] and kept["commit"] == OLD
    # Taken explicitly, it gives the place only; the source check still reports the change.
    taken, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW, accept={"T:p"})
    c = taken["claims"][0]
    assert report["claims"][0]["proposed"]["accepted"] is True
    assert c["location"] == p["location"] and c["source_region"] == p["source_region"]
    assert c["source_sha256"] == claim["source_sha256"] and c["commit"] == OLD
    assert c["source_line_sha256"] == claim["source_line_sha256"]
    assert not matches(c, {"regions": collect(taken, "T", new)})


def test_a_labelled_span_whose_text_changed_gets_a_proposal(tmp_path):
    para = PARA.replace("Third line.", "Third line.\\label{eq:p}")
    old = write(tmp_path / "old", para, AFTER)
    claim = span_claim(old, passage=para)
    new = write(tmp_path / "new", "Inserted.\n", para.replace("Sixth", "Sixth, edited,"), AFTER)
    _, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    entry = report["claims"][0]
    assert entry["class"] == "changed" and "select the passage by hand" in entry["reason"]
    start = line_of(old, para)
    assert entry["proposed"]["location"] == f"paper.tex:{start + 1}"
    assert entry["proposed"]["source_region"] == {"end_line": start + 7}


def test_a_proposal_across_a_heading_is_flagged_and_not_taken(tmp_path):
    old = write(tmp_path / "old", PARA, AFTER)
    claim = span_claim(old)
    new = write(tmp_path / "new", PARA.replace("Fourth line.\n",
                                               "Fourth line.\n\\section{Next}\nMore.\n"), AFTER)
    _, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    p = report["claims"][0]["proposed"]
    assert p["source_region"]["end_line"] == line_of(old, PARA) + 8
    assert p["flagged"] == ["spans-section"]
    assert any(a["kind"] == "spans-section" for a in p["advice"])
    with pytest.raises(RegionError, match="cross a heading; set them by hand"):
        repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW, accept={"T:p"})


def test_a_proposal_that_cuts_an_environment_is_flagged(tmp_path):
    eq = "\\begin{equation}\nx = 1\n\\end{equation}\n"
    old = write(tmp_path / "old", PARA, eq)
    claim = span_claim(old)
    # The last line of the passage is rewritten together with the opening of the display, as
    # one block of another length: the proposal takes the whole block, and so the opening.
    new = write(tmp_path / "new", PARA.replace(
        "Last line of the claim.\n", "Last line, new.\nAnother line.\n"),
        "\\begin{equation}\\label{eq:n}\nx = 1\n\\end{equation}\n")
    _, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    p = report["claims"][0]["proposed"]
    assert "cuts-environment" in p["flagged"]


def test_no_proposal_for_a_removed_passage_or_an_unknown_claim(tmp_path):
    old = write(tmp_path / "old", "Before.\n\n", PARA, AFTER)
    claim = span_claim(old)
    new = write(tmp_path / "new", "Before.\n\n", AFTER)
    _, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    p = report["claims"][0]["proposed"]
    assert "location" not in p and "removed" in p["reason"] and report["proposed"] == []
    with pytest.raises(RegionError, match="removed or blanked"):
        repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW, accept={"T:p"})
    with pytest.raises(RegionError, match="T:q: no bounds are proposed"):
        repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW, accept={"T:q"})


def test_columns_are_kept_only_on_unchanged_lines(tmp_path):
    old = write(tmp_path / "old", PARA, AFTER)
    kept = span_claim(old, "k", end_column=11)
    new = write(tmp_path / "new", PARA.replace("Third", "Third, edited"), AFTER)
    _, report = repin_plan({"claims": [kept]}, "T", old, new, OLD, NEW)
    p = report["claims"][0]["proposed"]
    assert p["source_region"]["end_column"] == 11 and "columns" not in p
    new2 = write(tmp_path / "new2", PARA.replace("Last line of", "The last line of"), AFTER)
    _, report = repin_plan({"claims": [kept]}, "T", old, new2, OLD, NEW)
    p = report["claims"][0]["proposed"]
    assert "end_column" not in p["source_region"] and "whole line" in p["columns"]


def test_line_diff_maps_unchanged_and_rewritten_blocks():
    d = LineDiff("a\nb\nc\nd\ne", "x\na\nB\nC\nC2\nd\ne")
    assert d.same(1) == 2 and d.same(2) is None and d.same(4) == 6
    # Lines 2-3 were rewritten as three lines: a passage over them takes all three.
    assert d.first(2) == 3 and d.last(3) == 5
    assert d.first(3) == 3 and d.last(2) == 5


# -- scope notes (#205) ------------------------------------------------------------------------

def test_note_references_move_with_their_lines_or_are_listed(tmp_path):
    body = "".join(f"Sentence {k}.\n" for k in range(1, 13))
    old = write(tmp_path / "old", body)
    (old / "other.tex").write_text("o1\no2\no3\n", encoding="utf-8")
    first = line_of(old, "Sentence 6.")
    note = (f"the second sentence (lines {first + 1}–{first + 2}) is X:sec:b; "
            f"line {first + 4} holds the rate; see other.tex:2 and lines 1-2 of missing.tex")
    claim = pinned(old, "s", "Sentence 6.\n", scope_note=note)
    new = write(tmp_path / "new", "Ins 1.\nIns 2.\nIns 3.\nIns 4.\n",
                body.replace("Sentence 10.", "Sentence ten."))
    (new / "other.tex").write_text("o0\no1\no2\no3\n", encoding="utf-8")
    result, report = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW)
    assert report["claims"][0]["class"] == "moved"
    (row,) = report["notes"]
    refs = {r["text"]: r for r in row["references"]}
    r = refs[f"lines {first + 1}–{first + 2}"]
    assert r["class"] == "moved" and r["to"] == [first + 5, first + 6]
    assert r["file"] == "paper.tex"
    assert refs[f"line {first + 4}"]["class"] == "changed"
    assert refs[f"line {first + 4}"]["changed_lines"] == [first + 4]
    assert refs["other.tex:2"]["class"] == "moved" and refs["other.tex:2"]["to"] == [3, 3]
    assert refs["lines 1-2 of missing.tex"]["class"] == "unread"
    assert row["rewritten"] == (f"the second sentence (lines {first + 5}–{first + 6}) is "
                                f"X:sec:b; line {first + 4} holds the rate; see other.tex:3 and "
                                "lines 1-2 of missing.tex")
    # The note is rewritten only on request.
    assert result["claims"][0]["scope_note"] == note
    result, _ = repin_plan({"claims": [claim]}, "T", old, new, OLD, NEW, rewrite_notes=True)
    assert result["claims"][0]["scope_note"] == row["rewritten"]


def test_note_references_inside_and_across_insertions():
    files_old = {"a.tex": "1\n2\n3\n4\n"}
    files_new = {"a.tex": "1\n2\nnew\n3\n4\n"}
    refs, out = note_references("lines 2-3, line 1, line 4", "a.tex", files_old, files_new, {})
    assert [r["class"] for r in refs] == ["changed", "unchanged", "moved"]
    assert refs[0]["changed_lines"] == [] and "inserted" in refs[0]["reason"]
    assert out == "lines 2-3, line 1, line 5"
    refs, _ = note_references("line 3", None, files_old, files_new, {})
    assert refs[0]["class"] == "unread" and "names no file" in refs[0]["reason"]


def test_command_takes_bounds_and_rewrites_notes_only_when_asked(project, capsys):
    repo, proj, first = project
    old_rev = commit(repo, PARA, AFTER)
    start = line_of(repo, PARA)
    claim = span_claim(repo)
    claim["scope_note"] = f"lines {start}-{start + 1} state it"
    inv = {"papers": {"T": {"commit": old_rev[:7]}}, "claims": [claim]}
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    toml = proj / "machinechecked.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(first, old_rev), encoding="utf-8")
    second = commit(repo, "Inserted.\n", PARA.replace("Sixth", "Sixth, edited,"), AFTER)
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0
    written = json.loads((proj / "claims.json").read_text(encoding="utf-8"))["claims"][0]
    assert written["location"] == claim["location"]
    assert written["scope_note"] == claim["scope_note"]
    # Back to the original inventory and configuration, then with both options.
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    toml.write_text(toml.read_text(encoding="utf-8").replace(second, old_rev), encoding="utf-8")
    before = files(proj)
    code, out, _ = run(proj, "--to", second, "--accept-bounds", "T:p", "--rewrite-notes",
                       capsys=capsys)
    assert code == 0 and files(proj) == before, "a plan writes nothing"
    code, out, _ = run(proj, "--to", second, "--accept-bounds", "T:p", "--rewrite-notes",
                       "--write", capsys=capsys)
    assert code == 0
    written = json.loads((proj / "claims.json").read_text(encoding="utf-8"))["claims"][0]
    assert written["location"] == f"paper.tex:{start + 1}"
    assert written["source_region"] == {"end_line": start + 7}
    assert written["source_sha256"] == claim["source_sha256"]
    assert written["scope_note"] == f"lines {start + 1}-{start + 2} state it"
    code, _, err = run(proj, "--to", second, "--accept-bounds", "T:x", capsys=capsys)
    assert code == 2 and "T:x: no bounds are proposed" in err
