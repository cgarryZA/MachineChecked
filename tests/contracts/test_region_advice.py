"""#180: a source region that holds only a label line, or that starts or ends inside a sentence,
or runs into another section, is reported as advice naming the passage likely meant. The advice
is a dismissible warning and never changes a status."""

from prooflens.repin import repin_plan
from prooflens.source_regions import SCHEME, advice, advice_message, collect, extract
from test_repin import NEW, OLD, pinned, write
from test_source_regions import assessed

FIT = ("\\subsection{Fitting}\n\\label{X:app:fit}\n\n"
       "The rare event has probability $O(\\tau^2)$.\n"
       "Halving $\\tau$ therefore roughly quarters the count.\n\n")
RATE = ("On the test problem the estimator is consistent and converges at\n"
        "rate $n^{-1/2}$, uniformly over the compact parameter set\n"
        "(Theorem~\\ref{X:thm:rate}).\n\n")
STABLE = ("We fix the step size throughout. Under the stated\n"
          "assumptions the scheme is stable, and its error is\n"
          "of order $h$. The constant depends only on the data.\n\n")
CONCLUSION = "\\section{Conclusion}\nThe scheme converges at first order.\n"
WHOLE = "A sentence that is a paragraph of its own.\n\n"


def claim(root, cid, line, end=None):
    c = {"id": f"T:{cid}", "paper": "T", "location": f"paper.tex:{line}"}
    if end:
        c["source_region"] = {"end_line": end}
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": extract(root, c).sha256}


def kinds(root, c):
    region = extract(root, c)
    text = (root / "paper.tex").read_text().splitlines()
    return [(a["kind"], a.get("suggested") and (a["suggested"]["line"],
                                                a["suggested"]["end_line"]))
            for a in advice(text, region)]


def test_label_lines_partial_sentences_and_section_crossings(tmp_path):
    root = write(tmp_path / "p", FIT, RATE, STABLE, CONCLUSION, "\n", WHOLE)
    # Lines: 1-3 the preamble, 4 \subsection, 5 \label, 7-8 the paragraph, 10-12 the rate,
    # 14-16 the stability paragraph, 18 \section, 19 its text, 21 a one-line paragraph.
    assert kinds(root, claim(root, "fit", 5)) == [("label-only", (7, 8))]
    assert kinds(root, claim(root, "rate", 11)) == [("starts-mid-sentence", (10, 12)),
                                                    ("ends-mid-sentence", (10, 12))]
    assert kinds(root, claim(root, "stable", 15, 16)) == [("starts-mid-sentence", (14, 16))]
    assert kinds(root, claim(root, "stable2", 14, 15)) == [("ends-mid-sentence", (14, 16))]
    assert kinds(root, claim(root, "stable3", 14, 16)) == []
    assert ("spans-section", None) in kinds(root, claim(root, "discussion", 14, 19))
    assert kinds(root, claim(root, "whole", 21)) == []


def test_advice_is_a_dismissible_warning_that_changes_no_status(tmp_path):
    root = write(tmp_path / "p", FIT, WHOLE)
    for cid, line, expected in (("fit", 5, ["label-only"]), ("whole", 10, [])):
        c = claim(root, cid, line)
        tex = {"mode": "latex", "anchors": [], "envs": [],
               "regions": collect({"claims": [c]}, "T", root)}
        record = assessed(root, c, tex)
        found = [f for f in record["body"]["assessment"]["findings"]
                 if f["code"] == "source-region"]
        assert [f["trigger"] for f in found] == expected
        assert all(f["tier"] == "warning" for f in found)
        assert record["body"]["assessment"]["claims"][0]["status_code"] == "formal.accepted"
        if found:
            assert found[0]["suggested"] == {"file": "paper.tex", "line": 7, "end_line": 8}
            assert "holds only a label or heading" in found[0]["message"]
            assert "source_region end_line 8" in found[0]["message"]


def test_the_repin_plan_carries_the_advice_at_the_new_revision(tmp_path):
    old = write(tmp_path / "old", FIT)
    new = write(tmp_path / "new", "Added.\n\n", FIT)
    c = pinned(old, "fit", "\\label{X:app:fit}\n")
    _, report = repin_plan({"claims": [c]}, "T", old, new, OLD, NEW)
    e = report["claims"][0]
    assert e["class"] == "moved" and report["advice"] == ["T:fit"]
    assert [a["kind"] for a in e["advice"]] == ["label-only"]
    assert e["advice"][0]["suggested"]["line"] == 9


# #200: a whole-line region that holds the \begin or the \end of an environment without the other.
THEOREM = "\\newtheorem{theorem}{Theorem}\n"
CUT = ("\\begin{theorem}\\label{X:thm:rate}\n"
       "The error is $O(h)$.\n"
       "\\end{theorem}\n"
       "Hence the scheme converges:\n"
       "\\begin{equation}\\label{X:eq:bound}\n"
       "e_h \\le C h ,\n"
       "\\end{equation}\n"
       "uniformly in the data.\n\n")


def cuts(root, c):
    region = extract(root, c)
    text = (root / "paper.tex").read_text().splitlines()
    return [a for a in advice(text, region, {"theorem"}) if a["kind"] == "cuts-environment"]


def test_a_region_that_cuts_an_environment_names_it_and_bounds_that_fix_it(tmp_path):
    root = write(tmp_path / "p", THEOREM, CUT)
    # Lines: 1-3 the preamble, 4 \newtheorem, 5-7 the theorem, 8 the prose, 9-11 the display,
    # 12 the end of the sentence.
    (a,) = cuts(root, claim(root, "conv", 6, 10))
    assert a["environments"] == [{"name": "theorem", "line": 5, "end_line": 7},
                                 {"name": "equation", "line": 9, "end_line": 11}]
    assert a["suggested"] == {"file": "paper.tex", "line": 5, "end_line": 11}
    assert a["without"] == {"file": "paper.tex", "line": 8, "end_line": 8}
    message = advice_message("X:sec:conv", extract(root, claim(root, "conv", 6, 10)).record(), a)
    assert "the theorem at lines 5-7 and the equation at lines 9-11" in message
    assert "pin lines 5-11 of paper.tex to contain them whole" in message
    assert "or lines 8-8 to leave them out" in message
    # The prose with its display whole, the theorem whole, or a line inside either: no cut.
    for line, end in ((8, 12), (5, 7), (6, 6), (10, 10), (5, 12)):
        assert cuts(root, claim(root, "ok", line, end)) == [], (line, end)
    # Holding only the display's \begin: containing it runs to its \end; there is nothing
    # of the region's own text to keep without it beyond line 8.
    (a,) = cuts(root, claim(root, "open", 8, 9))
    assert a["suggested"]["end_line"] == 11 and a["without"]["end_line"] == 8
    # An environment the snapshot does not declare theorem-like (here, without \newtheorem)
    # is not judged; a display always is.
    region = extract(root, claim(root, "conv", 6, 10))
    text = (root / "paper.tex").read_text().splitlines()
    (a,) = [a for a in advice(text, region) if a["kind"] == "cuts-environment"]
    assert [e["name"] for e in a["environments"]] == ["equation"]


def test_the_cut_is_found_in_a_build_with_the_snapshots_theorems(tmp_path):
    root = write(tmp_path / "p", THEOREM, CUT)
    c = claim(root, "conv", 6, 10)
    regions = collect({"claims": [c]}, "T", root)
    (a,) = [a for a in regions["T:conv"]["advice"] if a["kind"] == "cuts-environment"]
    assert [e["name"] for e in a["environments"]] == ["theorem", "equation"]
    tex = {"mode": "latex", "anchors": [], "envs": [], "regions": regions}
    record = assessed(root, c, tex)
    found = [f for f in record["body"]["assessment"]["findings"]
             if f["code"] == "source-region" and f["trigger"] == "cuts-environment"]
    assert len(found) == 1 and found[0]["tier"] == "warning"
    assert found[0]["suggested"] == {"file": "paper.tex", "line": 5, "end_line": 11}
    assert record["body"]["assessment"]["claims"][0]["status_code"] == "formal.accepted"
