"""Pins of several passages (#185) and of macro definitions in another file (#183), on a
synthetic manuscript."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prooflens.rebound import parse_macro, parse_part, rebound_plan
from prooflens.repin import repin_plan
from prooflens.review_sources import marker_state
from prooflens.schemas import validate
from prooflens.source_regions import (
    MULTI, SCHEME, RegionError, changed_line, collect, extract, matches, migration_plan,
    part_texts, pin,
)
from test_source_regions import assessed

REV, NEW = "a" * 40, "b" * 40
MAIN = ("\\documentclass{article}\n\\input{values}\n\\begin{document}\n"         # 1-3
        "\\subsection{The estimator}\n"                                          # 4
        "The estimator is unbiased for every sample size, and its variance\n"   # 5
        "is of order $1/n$; it converges in $\\iterCount$ steps.\n"             # 6
        "A simulation design, its own claim.\n"                                  # 7
        "\\section{Discussion}\n"                                                # 8
        "It is not efficient when the noise has heavy tails.\n"                  # 9
        "\\end{document}\n")
VALUES = "% generated\n\\newcommand{\\iterCount}{42}\n"


def write(root, main=MAIN, values=VALUES):
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(main, encoding="utf-8")
    (root / "values.tex").write_text(values, encoding="utf-8")
    return root


def single(root):
    c = {"id": "X:est:properties", "paper": "X", "location": "main.tex:5",
         "source_region": {"end_line": 6}, "scope": "expository", "scope_reviewed": True,
         "clauses": []}
    r = extract(root, c)
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": r.sha256,
            "source_line_sha256": r.line_sha256}


def several(root):
    """The claim pinned at lines 5-6 and 9, and at the definition of its macro."""
    inv = {"papers": {"X": {"commit": REV[:7]}}, "claims": [single(root)]}
    result, _ = rebound_plan(inv, "X", root, REV, [{
        "claim": "X:est:properties", "start": 5, "end": 6,
        "parts": [parse_part("main.tex:9"), parse_macro("\\iterCount")]}])
    return result


def test_a_pin_lists_further_passages_and_a_macro_definition(tmp_path):
    root = write(tmp_path)
    inv = several(root)
    c = inv["claims"][0]
    assert c["source_hash_scheme"] == MULTI
    assert [p["location"] for p in c["source_parts"]] == ["main.tex:9", "values.tex:2"]
    assert c["source_parts"][1]["macro"] == "\\iterCount"
    assert all(len(p["sha256"]) == 64 and p["line_sha256"] for p in c["source_parts"])
    # The combined digest is not the digest of the claim's own passage.
    assert c["source_sha256"] != single(root)["source_sha256"]
    rec = collect(inv, "X", root)[c["id"]]
    assert rec["scheme"] == MULTI and [p["file"] for p in rec["parts"]] == ["main.tex",
                                                                              "values.tex"]
    assert matches(c, {"regions": {c["id"]: rec}})
    # The new pin reads in the inventory's schema.
    validate(inv, "inventory")
    # The passages are shown in order, the claim's own first.
    shown = part_texts(inv, "X", root)[c["id"]]
    assert [s["start_line"] for s in shown] == [5, 9, 2]
    assert shown[2]["text"] == "\\newcommand{\\iterCount}{42}"


@pytest.mark.parametrize("edit, where", [
    (lambda m, v: (m, v.replace("{42}", "{57}")), "part 2 (the definition of \\iterCount)"),
    (lambda m, v: (m.replace("heavy tails", "light tails"), v), "line 1 of part 1"),
    (lambda m, v: (m.replace("unbiased", "biased"), v), "line 1 of the passage"),
])
def test_a_change_to_any_passage_fails_the_source_check_and_says_which(tmp_path, edit, where):
    root = write(tmp_path)
    inv = several(root)
    c = inv["claims"][0]
    write(root, *edit(MAIN, VALUES))
    rec = collect(inv, "X", root)[c["id"]]
    assert not matches(c, {"regions": {c["id"]: rec}})
    assert where in changed_line(c, rec)
    result = assessed(root, {**c, "paper": "T", "id": "T:est"},
                      {"mode": "latex", "envs": [], "anchors": [],
                       "regions": {"T:est": rec}})
    found = [f for f in result["body"]["assessment"]["findings"] if f["code"] == "source-changed"]
    assert found and where in found[0]["message"]


def test_a_new_pin_reopens_exactly_the_readings_of_its_claim(tmp_path):
    root = write(tmp_path)
    before = {"papers": {"X": {"commit": REV[:7]}},
              "claims": [single(root), {**single(root), "id": "X:other"}]}
    after = several(root) | {}
    after["claims"].append(before["claims"][1])
    read = {c["id"]: c["source_sha256"] for c in before["claims"]}
    marker = SimpleNamespace(source=read)
    now = {c["id"]: c["source_sha256"] for c in after["claims"]}
    assert marker_state(marker, "X:est:properties", now["X:est:properties"]) == "changed"
    assert marker_state(marker, "X:other", now["X:other"]) == "current"
    assert after["claims"][0]["scope_reviewed"] is False


def test_a_macro_defined_outside_the_region_is_reported_until_it_is_pinned(tmp_path):
    root = write(tmp_path)
    c = single(root)
    rec = collect({"claims": [c]}, "X", root)[c["id"]]
    assert rec["macros"] == [{"macro": "\\iterCount", "defined": ["values.tex:2"]}]
    result = assessed(root, {**c, "paper": "T", "id": "T:est"},
                      {"mode": "latex", "envs": [], "anchors": [], "regions": {"T:est": rec}})
    warn = [f for f in result["body"]["assessment"]["findings"]
            if f["code"] == "source-macro-unpinned"]
    assert len(warn) == 1 and warn[0]["tier"] == "warning"
    assert warn[0]["trigger"] == "\\iterCount"
    assert "values.tex:2" in warn[0]["message"]
    # It is advisory: the claim's pin still matches.
    assert matches(c, {"regions": {c["id"]: rec}})
    inv = several(root)
    assert "macros" not in collect(inv, "X", root)[c["id"]]


def test_a_macro_part_must_define_its_macro(tmp_path):
    root = write(tmp_path)
    inv = several(root)
    bad = deepcopy(inv["claims"][0])
    write(root, MAIN, VALUES + "\\newcommand{\\other}{1}\n")
    bad["source_parts"][1]["location"] = "values.tex:3"
    with pytest.raises(RegionError, match="does not define"):
        pin(root, bad)
    assert "does not define" in collect({"claims": [bad]}, "X", root)[bad["id"]]["error"]
    with pytest.raises(RegionError, match="no definition"):
        rebound_plan(inv, "X", root, REV, [{"claim": bad["id"], "start": 5, "end": 6,
                                            "parts": [parse_macro("\\nothing")]}])


def test_rebound_keeps_replaces_or_removes_the_further_passages(tmp_path):
    root = write(tmp_path)
    inv = several(root)
    kept, ch = rebound_plan(inv, "X", root, REV, [{"claim": "X:est:properties", "start": 5,
                                                   "end": 6}])
    assert kept == inv and ch[0]["unchanged"]
    dropped, _ = rebound_plan(inv, "X", root, REV, [{"claim": "X:est:properties", "start": 5,
                                                     "end": 6, "parts": []}])
    c = dropped["claims"][0]
    assert "source_parts" not in c and c["source_hash_scheme"] == SCHEME
    assert c["source_sha256"] == single(root)["source_sha256"]
    # A further passage is checked like the claim's own: not a blank line.
    with pytest.raises(RegionError, match="part 1"):
        rebound_plan(inv, "X", root, REV, [{"claim": "X:est:properties", "start": 5, "end": 6,
                                            "parts": [parse_part("main.tex:7-8")]}])


def test_the_migration_verifies_every_passage(tmp_path):
    root = write(tmp_path)
    inv = several(root)
    assert migration_plan(inv, "X", root, REV)[1] == []
    write(root, MAIN, VALUES.replace("42", "57"))
    with pytest.raises(RegionError, match="frozen hash"):
        migration_plan(inv, "X", root, REV)


def test_repin_moves_every_passage_or_keeps_the_pin_of_a_changed_one(tmp_path):
    old = write(tmp_path / "old")
    inv = several(old)
    moved = write(tmp_path / "moved", MAIN.replace("\\begin{document}\n",
                                                   "\\begin{document}\nAdded.\n"),
                  "% generated\n% again\n" + VALUES.split("\n", 1)[1])
    result, report = repin_plan(inv, "X", old, moved, REV, NEW)
    e = report["claims"][0]
    assert e["class"] == "moved" and [p["class"] for p in e["parts"]] == ["moved", "moved"]
    c = result["claims"][0]
    assert c["location"] == "main.tex:6"
    assert [p["location"] for p in c["source_parts"]] == ["main.tex:10", "values.tex:3"]
    assert c["source_sha256"] == inv["claims"][0]["source_sha256"]
    assert matches(c, {"regions": collect(result, "X", moved)})

    changed = write(tmp_path / "changed", MAIN, VALUES.replace("42", "57"))
    result, report = repin_plan(inv, "X", old, changed, REV, NEW)
    e = report["claims"][0]
    assert e["class"] == "changed" and e["parts"][1]["class"] == "changed"
    assert "part 2" in e["where"]
    c = result["claims"][0]
    assert c["source_sha256"] == inv["claims"][0]["source_sha256"]
    assert c["commit"] == REV[:7]
    assert not matches(c, {"regions": collect(result, "X", changed)})

    twice = write(tmp_path / "twice", MAIN.replace("heavy tails.\n", "heavy tails.\n"
                                                   "It is not efficient when the noise has "
                                                   "heavy tails.\n"))
    _, report = repin_plan(inv, "X", old, twice, REV, NEW)
    assert report["claims"][0]["class"] == "ambiguous" and report["blocking"]


def test_the_reader_and_the_review_packet_show_every_passage(tmp_path):
    from prooflens.compare import passage
    from prooflens.export import public_claim
    from prooflens.manifest import build
    root = write(tmp_path)
    inv = several(root)
    c = {**inv["claims"][0], "id": "T:est", "paper": "T"}
    shown = part_texts({"claims": [{**c}]}, "T", root)
    rec = collect({"claims": [c]}, "T", root)
    record = assessed(root, c, {"mode": "latex", "envs": [], "anchors": [], "regions": rec,
                                "part_text": shown})
    _, chunks, _ = build(record, "synthetic")
    chunk = next(iter(chunks.values()))
    assert [p["start_line"] for p in chunk["source_parts"]] == [5, 9, 2]
    p = passage(chunk, "read")
    assert p["available"] and p["text"].startswith("The estimator is unbiased")
    assert [x["file"] for x in p["parts"]] == ["main.tex", "main.tex", "values.tex"]
    assert public_claim(chunk, SimpleNamespace(source_text=True, lean=True)).get(
        "source_parts")
    assert "source_parts" not in public_claim(chunk, SimpleNamespace(source_text=False,
                                                                     lean=True))
