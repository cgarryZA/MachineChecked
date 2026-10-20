/-!
# Triangle numbers

The definitions of Section 1 of the paper.
-/

namespace Renum

/-- Definition 1.1: the `n`-th triangle number, the sum `0 + 1 + ⋯ + n`. -/
def triangle : Nat → Nat
  | 0 => 0
  | n + 1 => triangle n + (n + 1)

/-- Lemma 3.3: the triangle number of `n + 1` adds `n + 1` to the triangle number of `n`. -/
theorem triangle_succ (n : Nat) : triangle (n + 1) = triangle n + (n + 1) := rfl

/-- Lemma 2.2 of the paper: twice the triangle number of `n` is `n * (n + 1)`. -/
theorem two_mul_triangle (n : Nat) : 2 * triangle n = n * (n + 1) := by
  induction n with
  | zero => rfl
  | succ k ih => rw [triangle_succ, Nat.mul_add, ih]; simp only [Nat.mul_add, Nat.add_mul]; omega

theorem aux_one (n : Nat) : n ≤ n ^ 2 := by
  rw [Nat.pow_two]
  cases n with
  | zero => exact Nat.le_refl 0
  | succ k => exact Nat.le_mul_of_pos_right _ (Nat.succ_pos k)

theorem add_le_two_mul_max (m n : Nat) : m + n ≤ 2 * max m n := by
  omega

end Renum
