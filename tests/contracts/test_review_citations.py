"""#178: the declarations and files review text cites in backticks are resolved, and those that
nothing resolves are listed with their file and line. A warning never changes a status."""

import shutil
import subprocess

import pytest

from conftest import ROOT, build, findings, needs_lean, needs_tex, status
from prooflens import config as cfgmod
from prooflens.probe import lean_session, parse_records
from prooflens.review_citations import citations, classify, unresolved

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
    with open(toy / "machinechecked.toml") as f:
        txt = f.read()
    (toy / "machinechecked.toml").write_text(txt.replace(
        'statement_authors =', 'review_citations_strict = true\nstatement_authors =', 1))
    index, body, _ = build(toy, reuse_lean=True)
    assert {f["tier"] for f in findings(body, "review-citation")} == {"violation"}
    assert not index["gates"]["T"]["consistency"]["pass"]
    assert {c["id"]: c["status"] for c in index["claims"]} == before
