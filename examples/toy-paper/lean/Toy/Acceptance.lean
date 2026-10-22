import Toy.PaperSpec

/-!
# Proofs of the statements of the toy paper

Each theorem has exactly a proposition of `Toy.PaperSpec` (or its negation) as its type.
-/

namespace Toy.Acceptance

open Toy

theorem thm_even_add : PaperSpec.thm_even_add := by
  rintro a b ⟨j, rfl⟩ ⟨k, rfl⟩
  exact ⟨j + k, by omega⟩

/-- The hypotheses of Theorem 2.1 hold at the nonzero instance `a = 2`, `b = 4`. -/
theorem thm_even_add_hypotheses : IsEven 2 ∧ IsEven 4 ∧ 2 ≠ 0 ∧ 4 ≠ 0 :=
  ⟨⟨1, rfl⟩, ⟨2, rfl⟩, by decide, by decide⟩

theorem thm_triangle : PaperSpec.thm_triangle := by
  intro n
  induction n with
  | zero => rfl
  | succ n ih =>
    simp only [triangle, Nat.mul_add, ih]
    simp only [Nat.add_mul, Nat.mul_one, Nat.one_mul]
    omega

theorem prop_pred : ¬ PaperSpec.prop_pred := fun h => by
  have := h 0
  omega

theorem prop_pred_pos : PaperSpec.prop_pred_pos := by
  intro n hn
  omega

/-- The hypothesis of the corrected Proposition 2.3 holds at `n = 1`. -/
theorem prop_pred_pos_hypotheses : 0 < 1 := by decide

theorem thm_bound : PaperSpec.thm_bound := by
  refine ⟨1, fun n => ?_⟩
  have h := thm_triangle n
  have hn : n ≤ n * n := Nat.le_mul_self n
  rw [Nat.mul_add, Nat.mul_one] at h
  omega

end Toy.Acceptance
