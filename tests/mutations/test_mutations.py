"""Seeded failures on the toy paper, each with the response it must produce."""

import json

from conftest import build, edit, findings, needs_lean, needs_tex, status

L = "lean/Toy/"


@needs_lean
@needs_tex
def test_sorry_in_a_transitive_dependency(toy):
    edit(toy / L / "Acceptance.lean", "theorem thm_triangle : PaperSpec.thm_triangle := by",
         "theorem helper : 1 = 1 := by sorry\n\ntheorem thm_triangle : PaperSpec.thm_triangle := by\n"
         "  have := helper")
    index, body, _ = build(toy)
    # A proof that fails its check is no proof: the claim is open, with a violation.
    assert status(index, "T:thm:triangle") == "formal: open"
    f = findings(body, "accept-axioms", "T:thm:triangle")
    assert f and "sorryAx" in f[0]["message"]
    # Theorem 2.5 uses Theorem 2.2's proof, so it inherits the axiom.
    assert status(index, "T:thm:bound") == "formal: open"
    assert not index["gates"]["T"]["consistency"]["pass"]


@needs_lean
@needs_tex
def test_proof_with_an_extra_hypothesis(toy):
    edit(toy / L / "Acceptance.lean", "theorem thm_triangle : PaperSpec.thm_triangle := by\n  intro n",
         "theorem thm_triangle (_h : 0 < 1) : PaperSpec.thm_triangle := by\n  intro n")
    edit(toy / L / "Acceptance.lean", "have h := thm_triangle n", "have h := thm_triangle (by decide) n")
    index, body, _ = build(toy)
    assert status(index, "T:thm:triangle") == "formal: open"
    assert findings(body, "accept-type-not-spec", "T:thm:triangle")


@needs_lean
@needs_tex
def test_changed_definition_reopens_its_review(toy):
    # Same mathematics, different definition: a fingerprint is structural, so the review of the
    # definition becomes stale and the claim built on it is no longer accepted.
    edit(toy / L / "Defs.lean", "def IsEven (n : Nat) : Prop := ∃ k, n = 2 * k",
         "def IsEven (n : Nat) : Prop := ∃ k, n = k + k")
    index, body, _ = build(toy)
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    assert status(index, "T:def:even") == "definition: review pending"
    ob = [f for f in findings(body, "def-review", "T:thm:even-add") if f["trigger"] == "Toy.IsEven"]
    assert ob
    clause = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")["clauses"][0]
    assert clause["def_reviews"]["Toy.IsEven"]["state"] == "stale"
    # What the reader shows of the definition is the new one (#97).
    d = body["lean"]["decls"]["Toy.IsEven"]
    assert d["body"]["text"] == "∃ (k : Nat), n = k + k"
    assert "∃ k, n = k + k" in d["lean_source"]["text"]


@needs_lean
@needs_tex
def test_quantifier_reversal(toy):
    edit(toy / L / "PaperSpec.lean",
         "def thm_bound : Prop := ∃ C : Nat, ∀ n : Nat, triangle n ≤ C * (n * n)",
         "def thm_bound : Prop := ∀ n : Nat, ∃ C : Nat, triangle n ≤ C * (n * n)")
    edit(toy / L / "Acceptance.lean", "  refine ⟨1, fun n => ?_⟩", "  intro n\n  refine ⟨1, ?_⟩")
    before = json.loads((toy / "claims.json").read_text())
    index, body, _ = build(toy)
    spec = body["lean"]["specs"]["Toy.PaperSpec.thm_bound"]
    assert [b["role"] for b in spec["binders"]] == ["forall", "exists"]
    assert status(index, "T:thm:bound") == "formal: proved, review pending"
    assert before  # the inventory is unchanged; only the statement moved


@needs_lean
@needs_tex
def test_a_reviewed_statement_that_changes_reopens_its_review(toy):
    edit(toy / L / "PaperSpec.lean",
         "def thm_even_add : Prop := ∀ a b : Nat, IsEven a → IsEven b → IsEven (a + b)",
         "def thm_even_add : Prop := ∀ a b : Nat, IsEven a → IsEven b → a + b = a + b")
    edit(toy / L / "Acceptance.lean",
         "  rintro a b ⟨j, rfl⟩ ⟨k, rfl⟩\n  exact ⟨j + k, by omega⟩", "  intro a b _ _\n  rfl")
    index, body, _ = build(toy)
    assert status(index, "T:thm:even-add") == "formal: proved, review pending"
    clause = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")["clauses"][0]
    assert clause["spec_review"]["state"] == "stale"


@needs_lean
@needs_tex
def test_regime_without_a_nondegenerate_witness(toy):
    # A witness at zero meets the hypotheses but does not show the nonzero regime.
    edit(toy / L / "Acceptance.lean", "theorem prop_pred_pos_hypotheses",
         "theorem thm_even_add_zero : IsEven 0 ∧ IsEven 0 := ⟨⟨0, rfl⟩, ⟨0, rfl⟩⟩\n\n"
         "theorem prop_pred_pos_hypotheses")
    inv = json.loads((toy / "claims.json").read_text())
    cl = next(c for c in inv["claims"] if c["id"] == "T:thm:even-add")["clauses"][0]
    cl["witness"] = "Toy.Acceptance.thm_even_add_zero"
    cl["regimes"][0]["witness"] = None
    (toy / "claims.json").write_text(json.dumps(inv))
    index, body, _ = build(toy)
    clause = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")["clauses"][0]
    assert clause["checks"]["witness"]["ok"]
    assert clause["regimes"][0]["discharged"] is False
    assert findings(body, "regime", "T:thm:even-add")


@needs_lean
@needs_tex
def test_macro_generated_theorem_missing_from_the_inventory(toy):
    edit(toy / "paper/toy.tex", "\\section{Discussion}",
         "\\newcommand{\\stated}[1]{\\begin{theorem}#1\\end{theorem}}\n"
         "\\stated{Every natural number is even or odd.}\n\n\\section{Discussion}")
    index, body, _ = build(toy)
    gap = findings(body, "inventory-gap")
    assert len(gap) == 1 and "Theorem 2.7" in gap[0]["message"]
    assert gap[0]["tier"] == "violation"


@needs_lean
@needs_tex
def test_changed_manuscript_claim(toy):
    edit(toy / "paper/toy.tex", "then $a + b$ is even.", "then $a + b$ is even and positive.")
    index, body, _ = build(toy)
    assert findings(body, "source-changed", "T:thm:even-add")


@needs_lean
@needs_tex
def test_author_review_declared_human_is_still_not_independent(toy):
    edit(toy / "reviews/T.md", "by=statement-author source=",
         "by=statement-author kind=human source=")
    index, _, _ = build(toy)
    assert status(index, "T:thm:triangle") == "formal: proved, author-reviewed"


@needs_lean
@needs_tex
def test_dismissal_lapses_when_the_statement_changes(toy):
    edit(toy / L / "PaperSpec.lean", "def prop_pred_pos : Prop := ∀ n : Nat, 0 < n → n - 1 < n",
         "def prop_pred_pos : Prop := ∀ n : Nat, 1 ≤ n → n - 1 < n")
    _, body, _ = build(toy)
    w = [f for f in findings(body, "totalised") if f["subject"] == "T:prop:pred#1"]
    assert w and not w[0].get("dismissed") and w[0].get("dismissal_stale")


@needs_lean
@needs_tex
def test_specification_layer_importing_the_acceptance_layer(toy):
    (toy / L / "PaperSpec").mkdir()
    (toy / L / "PaperSpec" / "Extra.lean").write_text("import Toy.Acceptance\n")
    edit(toy / "lean/Toy.lean", "import Toy.Acceptance", "import Toy.Acceptance\nimport Toy.PaperSpec.Extra")
    _, body, _ = build(toy)
    assert findings(body, "layering")


@needs_lean
@needs_tex
def test_a_witness_instance_in_an_unreviewed_declaration_is_listed(toy):
    # The instance of Theorem 2.1's witness moves into an abbreviation no proposition uses.
    edit(toy / L / "Acceptance.lean", "/-- The hypotheses of Theorem 2.1",
         "/-- The summands the paper's example uses. -/\n"
         "abbrev paperSummands : Prop := IsEven 2 ∧ IsEven 4\n\n"
         "/-- The hypotheses of Theorem 2.1")
    edit(toy / L / "Acceptance.lean", "theorem thm_even_add_hypotheses : IsEven 2 ∧ IsEven 4 ∧",
         "theorem thm_even_add_hypotheses : paperSummands ∧")
    edit(toy / L / "Acceptance.lean", "⟨⟨1, rfl⟩, ⟨2, rfl⟩, by decide, by decide⟩",
         "⟨⟨⟨1, rfl⟩, ⟨2, rfl⟩⟩, by decide, by decide⟩")
    index, body, cfg = build(toy)
    clause = next(c for c in body["assessment"]["claims"]
                  if c["id"] == "T:thm:even-add")["clauses"][0]
    record = body["lean"]["proofs"]["witness:Toy.Acceptance.thm_even_add_hypotheses:"]
    assert "Toy.Acceptance.paperSummands" in record["closure"]
    assert clause["witness_defs"] == [{"name": "Toy.Acceptance.paperSummands",
                                       "witnesses": ["Toy.Acceptance.thm_even_add_hypotheses"],
                                       "state": "pending"}]
    f = findings(body, "witness-def-review", "T:thm:even-add")
    assert len(f) == 1 and f[0]["tier"] == "warning"
    assert status(index, "T:thm:even-add") == "formal: accepted"
    # The definition claim of `IsEven` names it as a candidate for its mapping.
    defn = next(c for c in body["assessment"]["claims"] if c["id"] == "T:def:even")
    assert defn["clauses"][0]["witness_candidates"][0]["name"] == "Toy.Acceptance.paperSummands"
    # `check --json` gives both lists under their claims.
    from prooflens.cli import _witness_lists
    lists = _witness_lists(cfg, index["evidence"])
    assert lists["T:thm:even-add"]["witness_defs"][0]["clause"] == "statement"
    assert lists["T:def:even"]["witness_candidates"][0]["uses"] == ["Toy.IsEven"]
    # Required by the configuration, its missing review holds the claim back.
    edit(toy / "machinechecked.toml", 'inventory = "claims.json"',
         'inventory = "claims.json"\nrequire_witness_def_reviews = true')
    index, body, _ = build(toy)
    assert status(index, "T:thm:even-add") != "formal: accepted"
    assert any(f["trigger"] == "Toy.Acceptance.paperSummands"
               for f in findings(body, "def-review", "T:thm:even-add"))
