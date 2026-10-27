import Shape.Analysis

/-!
# Statements to read as mathematics

Synthetic statements for the readable presentation of a statement: the two orders of a constant
and a "for every", a linear isometry with representatives unique almost everywhere, and a
statement with an alternative, two witnesses of one name, coercions and a quantified
assumption.
-/

namespace Shape

open MeasureTheory

/-- One constant for every `n`: it is chosen once, above the "for every". -/
theorem bound_once : ∃ C : Nat, ∀ n : Nat, n ≤ C * (n * n) + n :=
  ⟨0, fun n => Nat.le_add_left n _⟩

/-- A constant for each `n`: it is chosen after `n`, and may depend on it. -/
theorem bound_each : ∀ n : Nat, ∃ C : Nat, n ≤ C * (n * n) + n :=
  fun _ => ⟨0, Nat.le_add_left _ _⟩

/-- On σ-finite measure spaces, a linear isometry from the square-integrable classes for the
product measure onto three-dimensional Euclidean space; each class has a representative, unique
almost everywhere for the product measure. -/
theorem isometry_classes {Ω₁ Ω₂ : Type} [MeasurableSpace Ω₁] [MeasurableSpace Ω₂]
    (μ : Measure Ω₁) (ν : Measure Ω₂) [SigmaFinite μ] [SigmaFinite ν]
    (Φ : Lp ℝ 2 (μ.prod ν) ≃ₗᵢ[ℝ] EuclideanSpace ℝ (Fin 3)) :
    ∀ F : Lp ℝ 2 (μ.prod ν), (Φ F).coords 0 = (Φ F).coords 0 ∧
      (∃ g : Ω₁ × Ω₂ → ℝ, Filter.Eventually (fun x => g x = F x) (ae (μ.prod ν))) ∧
      ∀ g h : Ω₁ × Ω₂ → ℝ, Filter.EventuallyEq (ae (μ.prod ν)) g F →
        Filter.EventuallyEq (ae (μ.prod ν)) h F → Filter.EventuallyEq (ae (μ.prod ν)) g h :=
  fun F => ⟨rfl, ⟨fun x => F x, .intro⟩, fun _ _ _ _ => .intro⟩

/-- An alternative whose two witnesses are both named `x`, a number taken as a real number, and
an assumption about every number up to `n`. -/
theorem alternatives (n : Nat) (b : ℝ) (h : ∀ m : Nat, m ≤ n → (m : ℝ) ≤ b) :
    (∃ x : ℝ, (n : ℝ) < x) ∨ ∃ x : Nat, 2 * x = n :=
  Or.inl ⟨⟨n + 1⟩, Nat.lt_succ_self n⟩

end Shape
