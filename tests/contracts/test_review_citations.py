"""#178: the declarations and files review text cites in backticks are resolved, and those that
nothing resolves are listed with their file and line. A warning never changes a status."""

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from conftest import ROOT, build, findings, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens.assess import Assessor
from prooflens.probe import lean_session, parse_records
from prooflens.review_citations import citations, classify, file_fingerprint, unresolved

REVIEW = """## A synthetic review

`Foo.Bar` is the closure of the span of the generators: `Foo.bar_eq_span` identifies the two
(see `notes/span.md`). The constant `C_rel` and the index `x_i` are notation; `a.referee`
reviewed it, and `n + 1` is an expression.

```lean
example : `not_a_citation := rfl
```

Review by a.referee: faithful (report `reports/gone.json`).
<!-- spec-review: Foo.spec 0123456789abcdef0123456789abcdef by=a.referee -->
"""


def test_tokens_that_look_like_names_and_paths_are_cited(tmp_path):
    assert classify("Foo.bar_eq_span") == classify("bar_eq_span") == "name"
    assert classify("notes/span.md") == classify("T.md") == classify("Lib/Sub/") == "path"
    for t in ("n + 1", "x", "Foo", "https://example.org/a.md", "2.5", "∀ x, P x", "e₁/2",
              "a/b"):
        assert classify(t) is None, t
    f = tmp_path / "reviews.md"
    f.write_text(REVIEW)
    got = [(c["line"], c["kind"], c["token"]) for c in citations([f], tmp_path)]
    assert got == [(3, "name", "Foo.Bar"), (3, "name", "Foo.bar_eq_span"),
                   (4, "path", "notes/span.md")]
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "span.md").write_text("x")
    cites = citations([f], tmp_path)
    names = {"checked": ["Foo.Bar", "Foo.bar_eq_span"], "unresolved": ["Foo.bar_eq_span"]}
    assert [c["token"] for c in unresolved(cites, names, [tmp_path])] == ["Foo.bar_eq_span"]
    # A name the probe did not check is not reported; a path is checked without Lean.
    (tmp_path / "notes" / "span.md").unlink()
    assert [c["token"] for c in unresolved(cites, None, [tmp_path])] == ["notes/span.md"]
    # The configured patterns replace the default ones.
    assert "C_rel" in [c["token"] for c in citations([f], tmp_path, ignore=[])]
    # A path resolves relative to any folder of the project (a library root, a package).
    (tmp_path / "pkg" / "notes").mkdir(parents=True)
    (tmp_path / "pkg" / "notes" / "span.md").write_text("x")
    assert unresolved(cites, None, [tmp_path]) == []


def test_notation_in_code_spans_is_not_cited(tmp_path):
    f = tmp_path / "reviews.md"
    f.write_text("`X'_T`, `μ.law`, `C.h`, `ab_n` and `x_i` are notation; `Foo.baz` is not.\n")
    assert [c["token"] for c in citations([f], tmp_path)] == ["Foo.baz"]


# A synthetic re-pin (#270): its removal record and archived markers name the declarations that
# were removed, which must be named there; a live reading around them cites names too.
REPIN = """## Re-pin to rev2

**Clauses removed.** `Foo.Spec.old_claim` (`X:sec2:thing`): the sentence it stated is deleted at
rev2; the proposition is removed with `Foo.Acc.old_claim` and its witness.

The live reading below still cites `Foo.Spec.live_gap`.

<!-- archived at rev2 (a passage read here is deleted): spec-review-record: Foo.Spec.old_claim
by=a.referee, read with `Foo.old_lemma` and ```Foo.old_fenced``` -->
<!-- ARCHIVED AT rev1: `Foo.Spec.first_claim` -->

- **Retired at rev2.** `Foo.Spec.old_item`, with
  - `Foo.Spec.old_nested`
- `Foo.Spec.live_item` is read against the new passage.

**Removed:**
1. `Foo.Spec.old_listed`

The reading of `Foo.Spec.new_claim` uses `Foo.Spec.older` (removed at rev1) and
`Foo.Spec.oldest` (Retired), and `Foo.Spec.live_missing`.

**Note.** `Foo.removed_lemma_name` is cited by a live reading.

<!-- spec-review: Foo.Spec.new_claim 0123456789abcdef0123456789abcdef by=a.referee -->
"""


def test_review_text_that_records_a_removal_cites_nothing(tmp_path):
    f = tmp_path / "reviews.md"
    f.write_text(REPIN)
    cites = citations([f], tmp_path)
    live = ["Foo.Spec.live_gap", "Foo.Spec.live_item", "Foo.Spec.new_claim",
            "Foo.Spec.live_missing", "Foo.removed_lemma_name"]
    assert [c["token"] for c in cites] == live
    assert [c["line"] for c in cites] == [6, 14, 19, 20, 22]
    # Every name the probe finds nowhere: only those of live readings are reported.
    gone = live + ["Foo.Spec.old_claim", "Foo.Acc.old_claim", "Foo.old_lemma",
                   "Foo.Spec.old_item", "Foo.Spec.old_nested", "Foo.Spec.old_listed",
                   "Foo.Spec.older", "Foo.Spec.oldest", "Foo.Spec.first_claim"]
    names = {"checked": gone, "unresolved": gone}
    assert [c["token"] for c in unresolved(cites, names, [tmp_path])] == live
    # The same names cited outside a removal record are reported.
    f.write_text("A reading that cites `Foo.Spec.old_claim` and `Foo.old_lemma`.\n")
    assert [c["token"] for c in unresolved(citations([f], tmp_path), names, [tmp_path])] == [
        "Foo.Spec.old_claim", "Foo.old_lemma"]


LIVE = "<!-- spec-review: Foo.spec 0123456789abcdef0123456789abcdef -->"
RETIRED = "<!-- retired def-review: Foo.Bar fedcba9876543210fedcba9876543210 -->"
UNNAMED = f"A reading of `Foo.bar` by `referee.one`.\n{LIVE}\n{RETIRED}\n"


def test_a_marker_without_attributes_names_no_reviewer(tmp_path):
    """#363: a marker may have no attributes. Its review text is read, and it names no reviewer
    whose name the citations skip."""
    f = tmp_path / "reviews.md"
    f.write_text(UNNAMED)
    assert [c["token"] for c in citations([f], tmp_path)] == ["Foo.bar", "referee.one"]
    # The reviewer that a live or a retired marker names is skipped.
    for marker in (LIVE, RETIRED):
        f.write_text(UNNAMED.replace(marker, marker.replace(" -->", " by=referee.one -->")))
        assert [c["token"] for c in citations([f], tmp_path)] == ["Foo.bar"]


# Two readings that cite the same missing name (#510): an earlier one kept for the record,
# closed by a retired marker, and the current reading of another declaration.
TWO_READINGS = """## An earlier reading, kept for the record

It relied on `Foo.old_lemma`.

<!-- retired spec-review: Foo.first 0123456789abcdef0123456789abcdef by=a.referee -->

## The current reading of another declaration

The bound follows from `Foo.old_lemma`,
and the estimate from `Foo.old_lemma` again.

<!-- spec-review: Foo.second fedcba9876543210fedcba9876543210 by=a.referee -->
"""

FIRST = "spec-review: Foo.first 0123456789abcdef0123456789abcdef"
SECOND = "spec-review: Foo.second fedcba9876543210fedcba9876543210"


def cited(root, dismissals=(), strict=False, missing=("Foo.old_lemma",)):
    """The review-citation findings of an assessment of the review file `reviews.md` under
    `root`, with the probe finding the names `missing` nowhere."""
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None, root=root,
                          reviews=[root / "reviews.md"], review_citations_strict=strict)
    lean = {"names": {"checked": list(missing), "unresolved": list(missing)}, "layering": []}
    out = Assessor(cfg, {"claims": []}, lean, {}, [], list(dismissals)).run()
    return [f for f in out["findings"] if f["code"] == "review-citation"]


def dismissal(f, **kw):
    return {"code": "review-citation", "subject": f["subject"], "trigger": f["trigger"],
            "at": f["at"], "fingerprint": f["fingerprint"], "rationale": "kept for the record",
            "by": "auditor", **kw}


def test_a_dismissal_covers_the_block_it_names_and_no_other(tmp_path):
    """#510: each review block (the text a marker closes) that cites a missing name is its own
    warning, listing every line that cites it; a dismissal names its block (`at`)."""
    (tmp_path / "reviews.md").write_text(TWO_READINGS)
    first, second = cited(tmp_path)
    assert [(f["at"], f["line"], f["lines"]) for f in (first, second)] == [
        (FIRST, 3, [3]), (SECOND, 9, [9, 10])]
    assert first["message"] == (
        "reviews.md:3 (before the retired marker of Foo.first at line 5): the review cites "
        "Foo.old_lemma, which is no declaration of the project, its dependencies or Lean")
    assert second["message"].startswith("reviews.md:9, 10 (before the marker of Foo.second at "
                                        "line 12): ")
    assert first["fingerprint"] != second["fingerprint"] and first["id"] != second["id"]
    # Dismissing the record leaves the current reading's citation open.
    first, second = cited(tmp_path, [dismissal(first)])
    assert first["dismissed"] == {"rationale": "kept for the record", "by": "auditor"}
    assert not second.get("dismissed") and not second.get("dismissal_stale")
    assert not first.get("dismissal_stale")
    # Each block dismissed by its own dismissal: neither reads as stale because of the other.
    both = [dismissal(f) for f in cited(tmp_path)]
    assert all(f.get("dismissed") and not f.get("dismissal_stale")
               for f in cited(tmp_path, both))


def test_a_dismissal_lapses_when_its_block_cites_the_token_again(tmp_path):
    """#510: a dismissal covers the lines it was given for. A further citation of the token in
    its block, or an edit of a line that cites it, reopens the warning as stale; text added
    around the block, or elsewhere in it, does not."""
    path = tmp_path / "reviews.md"
    path.write_text(TWO_READINGS)
    d = dismissal(cited(tmp_path)[1])
    path.write_text("# Reviews\n\nAn introduction.\n\n" + TWO_READINGS.replace(
        "again.\n", "again.\nA sentence that cites nothing.\n"))
    second = cited(tmp_path, [d])[1]
    assert second["lines"] == [13, 14] and second["dismissed"]["by"] == "auditor"
    path.write_text(TWO_READINGS.replace("again.\n", "again.\nAnd `Foo.old_lemma` once more.\n"))
    second = cited(tmp_path, [d])[1]
    assert second["lines"] == [9, 10, 11]
    assert not second.get("dismissed") and second["dismissal_stale"]
    path.write_text(TWO_READINGS.replace("The bound", "The sharp bound"))
    second = cited(tmp_path, [d])[1]
    assert not second.get("dismissed") and second["dismissal_stale"]


def test_a_dismissal_follows_its_marker(tmp_path):
    """#510: the block is named by the marker that closes it: retiring the marker keeps the
    dismissal, and another hash in the marker (a new reading) lapses it, so that the warning
    reads as stale rather than silently dismissed or silently open."""
    path = tmp_path / "reviews.md"
    path.write_text(TWO_READINGS)
    d = dismissal(cited(tmp_path)[1])
    path.write_text(TWO_READINGS.replace("<!-- spec-review: Foo.second",
                                         "<!-- retired spec-review: Foo.second"))
    second = cited(tmp_path, [d])[1]
    assert second["at"] == SECOND and second["dismissed"]["by"] == "auditor"
    assert "(before the retired marker of Foo.second at line 12)" in second["message"]
    path.write_text(TWO_READINGS.replace("fedcba9876543210fedcba9876543210",
                                         "00112233445566778899aabbccddeeff"))
    first, second = cited(tmp_path, [d])
    assert second["at"] == "spec-review: Foo.second 00112233445566778899aabbccddeeff"
    assert not second.get("dismissed") and second["dismissal_stale"]
    assert not first.get("dismissed") and not first.get("dismissal_stale")


def test_a_dismissal_written_before_blocks_covers_the_first_block_only(tmp_path):
    """#510: a dismissal without `at` was given for the warning at the token's first citation in
    the file. It keeps covering that block, says so (`form`: `file`), and every other block it
    used to cover reads as stale."""
    (tmp_path / "reviews.md").write_text(TWO_READINGS)
    old = {"code": "review-citation", "subject": "reviews.md", "trigger": "Foo.old_lemma",
           "fingerprint": file_fingerprint("reviews.md", "Foo.old_lemma"),
           "rationale": "kept for the record", "by": "auditor"}
    first, second = cited(tmp_path, [old])
    assert first["dismissed"] == {"rationale": "kept for the record", "by": "auditor",
                                  "form": "file"}
    assert not second.get("dismissed") and second["dismissal_stale"]
    # A dismissal of the second block too leaves nothing open.
    first, second = cited(tmp_path, [old, dismissal(second)])
    assert first["dismissed"]["form"] == "file" and "form" not in second["dismissed"]
    assert not second.get("dismissal_stale")
    # One whose fingerprint is not the file and token's covers nothing.
    first, _ = cited(tmp_path, [{**old, "fingerprint": file_fingerprint("other.md", "x_y")}])
    assert not first.get("dismissed") and first["dismissal_stale"]


def test_text_no_marker_closes_and_markers_with_the_same_head(tmp_path):
    """#510: text after the last marker is a block of its own (`end of file`); a marker on the
    citation's line closes it only when it follows the citation; markers with the same kind,
    declaration and hash are told apart by their order."""
    (tmp_path / "reviews.md").write_text(
        "Cites `Foo.gone`. <!-- def-review: Foo.d 0123 by=r --> and `Foo.gone`.\n"
        "<!-- def-review: Foo.d 0123 by=s -->\n"
        "Later `Foo.gone`.\n"
        "<!-- def-review: Foo.d 0123 by=t -->\n"
        "Unclosed `Foo.gone`.\n")
    got = cited(tmp_path, missing=("Foo.gone",))
    assert [(f["at"], f["lines"]) for f in got] == [
        ("def-review: Foo.d 0123", [1]), ("def-review: Foo.d 0123 (2)", [1]),
        ("def-review: Foo.d 0123 (3)", [3]), ("end of file", [5])]
    assert got[3]["message"].startswith("reviews.md:5 (no marker follows): the review cites")
    assert len({f["id"] for f in got}) == 4


def test_strict_mode_gives_a_violation_for_each_block(tmp_path):
    (tmp_path / "reviews.md").write_text(TWO_READINGS)
    got = cited(tmp_path, strict=True)
    assert [(f["tier"], f["at"], f["lines"]) for f in got] == [
        ("violation", FIRST, [3]), ("violation", SECOND, [9, 10])]


@needs_lean
@pytest.mark.parametrize("toolchain", [None, "leanprover/lean4:v4.24.0"])
def test_the_probe_resolves_names_by_their_last_components(tmp_path, toolchain):
    root = tmp_path / "structure"
    shutil.copytree(ROOT / "tests" / "fixtures" / "structure", root)
    if toolchain:
        (root / "lean-toolchain").write_text(toolchain + "\n")
        if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                          text=True).stdout.find(toolchain) < 0:
            pytest.skip(f"{toolchain} is not installed")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    names = ["Shape.steps_pos", "steps_pos", "Expand.steps_pos", "Nat.add_comm", "Shape",
             "Shape.Expand", "Shape.no_such_lemma", "bar_eq_span", "Shape.steps_pos.extra"]
    query = {"scope_roots": ["Shape"], "spec_prefix": "Shape", "accept_prefix": "Shape",
             "allowed_axioms": [], "requests": [{"kind": "names", "name": "", "names": names}]}
    res = lean_session(root, ["Shape"], query, parse_records)
    assert res["names"]["checked"] == names
    assert res["names"]["unresolved"] == ["Expand.steps_pos", "Shape.no_such_lemma",
                                          "bar_eq_span", "Shape.steps_pos.extra"]


CITING = """
## A note on the bound

The bound follows from `Toy.Acceptance.thm_bound`, as `Nat.le_refl` and `thm_even_add_hypotheses`
show, together with `Toy.bound_of_span` (see `reviews/definitions.md` and `notes/missing.md`).

**Clauses removed.** `Toy.PaperSpec.thm_old` (`T:thm:old`): the sentence it stated is deleted
at rev2, with `Toy.Acceptance.thm_old`; `Toy.gone_def` (removed at rev2) went with it.

<!-- archived at rev2 (a passage read here is deleted): spec-review-record:
Toy.PaperSpec.thm_old, read with `Toy.old_lemma` -->

<!-- spec-review: Toy.PaperSpec.thm_even_add pl-fp-v1:551fc041080c4c0d6511fdb7ea708af7cdc3dd106c870a6619677829587f7ce8 by=a.referee kind=human source=T:thm:even-add@50d67d3f6936ce366dc5aef10344224a217e728079aafcaa78e2bc5a5e733b43 -->
"""


@needs_lean
@needs_tex
def test_a_dangling_citation_is_a_warning_or_in_strict_mode_a_violation(toy):
    index, body, _ = build(toy)
    before = {c["id"]: c["status"] for c in index["claims"]}
    assert not findings(body, "review-citation")
    with open(toy / "reviews" / "T.md", "a") as f:
        f.write(CITING)
    index, body, _ = build(toy)
    # The names its removal record and archived marker cite (#270) are not reported.
    got = sorted((f["trigger"], f["file"], f["tier"]) for f in findings(body, "review-citation"))
    assert got == [("Toy.bound_of_span", "reviews/T.md", "warning"),
                   ("notes/missing.md", "reviews/T.md", "warning")]
    assert all(f["line"] > 60 for f in findings(body, "review-citation"))
    assert {c["id"]: c["status"] for c in index["claims"]} == before
    # A dismissal covers the block it names (#510): a later citation of the same name, in text
    # no marker closes, is warned about again.
    (w,) = [f for f in findings(body, "review-citation") if f["trigger"] == "Toy.bound_of_span"]
    assert w["at"].startswith("spec-review: Toy.PaperSpec.thm_even_add pl-fp-v1:")
    dpath = toy / "reviews" / "dismissals.json"
    dpath.write_text(json.dumps(json.loads(dpath.read_text()) + [
        {"code": "review-citation", "subject": w["subject"], "trigger": w["trigger"],
         "at": w["at"], "fingerprint": w["fingerprint"], "rationale": "named in the next release",
         "by": "a.referee"}]))
    with open(toy / "reviews" / "T.md", "a") as f:
        f.write("\nA later note relies on `Toy.bound_of_span` too.\n")
    index, body, _ = build(toy, reuse_lean=True)
    assert [(f["at"], bool(f.get("dismissed")), bool(f.get("dismissal_stale")))
            for f in findings(body, "review-citation")
            if f["trigger"] == "Toy.bound_of_span"] == [(w["at"], True, False),
                                                        ("end of file", False, False)]
    assert {c["id"]: c["status"] for c in index["claims"]} == before
    with open(toy / "machinechecked.toml") as f:
        txt = f.read()
    (toy / "machinechecked.toml").write_text(txt.replace(
        'statement_authors =', 'review_citations_strict = true\nstatement_authors =', 1))
    index, body, _ = build(toy, reuse_lean=True)
    assert {f["tier"] for f in findings(body, "review-citation")} == {"violation"}
    assert not index["gates"]["T"]["consistency"]["pass"]
    assert {c["id"]: c["status"] for c in index["claims"]} == before


# Two markers written without their attributes (#363): one with no review text, and one whose
# review text cites a name nothing declares.
NO_ATTRIBUTES = """
## A marker copied without its attributes

<!-- spec-review: Foo.spec 0123456789abcdef0123456789abcdef -->

## A reading recorded without its attributes

The reading cites `Toy.no_such_lemma`.

<!-- def-review: Foo.Bar fedcba9876543210fedcba9876543210 -->
"""


@needs_lean
@needs_tex
def test_a_marker_without_attributes_does_not_stop_the_build(toy):
    """#363: the build reads markers written without attributes. Each is recorded with no
    reviewer named, the one with no review text is listed as recording no reading, and the
    citations of the other's review text are checked."""
    path = toy / "reviews" / "T.md"
    with open(path, "a") as f:
        f.write(NO_ATTRIBUTES)
    lines = path.read_text().split("\n")
    at = {name: next(i for i, x in enumerate(lines, 1) if f"-review: {name} " in x)
          for name in ("Foo.spec", "Foo.Bar")}
    _, body, _ = build(toy)
    got = {r["name"]: (r["file"], r["line"], r["by"], r["kind"])
           for r in body["reviews"]["records"] if r["name"] in at}
    assert got == {name: ("reviews/T.md", line, "unknown", "unknown")
                   for name, line in at.items()}
    assert [(f["subject"], f["file"], f["line"]) for f in findings(body, "review-without-reading")
            ] == [("Foo.spec", "reviews/T.md", at["Foo.spec"])]
    assert [(f["trigger"], f["line"]) for f in findings(body, "review-citation")] == [
        ("Toy.no_such_lemma", at["Foo.Bar"] - 2)]
