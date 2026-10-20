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
