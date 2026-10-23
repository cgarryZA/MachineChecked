import Renum.Basic

/-!
# Bounds for triangle numbers

The bounds of Section 2 of the paper (Theorem 2.1 and Corollary 2.4).

The closed form is Gauss's Lemma 4.22, as in

* Hardy–Wright, *An Introduction*, Ch. IV, Prop. 4.7.

Gauss's lemma is classical; the paper's Lemma 2.6 is not formalised here.
-/

namespace Renum

/-- A triangle number is at most the square of its index. -/
theorem triangle_le_sq (n : Nat) : triangle n ≤ n ^ 2 := by
  have h := two_mul_triangle n
  rw [Nat.pow_two]
  have : n * (n + 1) ≤ 2 * (n * n) := by
    cases n with
    | zero => simp
    | succ k => rw [Nat.mul_add, Nat.mul_one, Nat.two_mul]; exact Nat.add_le_add_left
                  (Nat.le_mul_of_pos_right _ (Nat.succ_pos k)) _
  omega

/-- Theorem 2.1: triangle numbers are bounded by a multiple of the square of their index, with
one constant for every index. -/
theorem triangle_bound : ∃ C, ∀ n, triangle n ≤ C * n ^ 2 :=
  ⟨1, fun n => by rw [Nat.one_mul]; exact triangle_le_sq n⟩

/-- Corollary 2.4: each triangle number is bounded by some constant. -/
theorem triangle_le_const : ∀ n, ∃ C, triangle n ≤ C := fun n => ⟨triangle n, Nat.le_refl _⟩

/-- This is Theorem 4.1 of [Gauss]: the sum `0 + 1 + ⋯ + n` is `n * (n + 1) / 2`. -/
theorem gauss_sum (n : Nat) : triangle n = n * (n + 1) / 2 := by
  have h := two_mul_triangle n
  omega

theorem lemma_2_5 (n : Nat) : triangle n ≤ triangle (n + 1) := by
  rw [triangle_succ]; exact Nat.le_add_right _ _

end Renum
