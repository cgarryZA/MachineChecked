/-!
# An auditor's certificates for the toy paper

Equation (3) of the toy paper, in the proof of Theorem 2.5, states `n ≤ k n²` for every natural
number `k ≥ 0`. These declarations are an auditor's evidence about that printed step. They are
outside the paper's statements (`Toy.PaperSpec`) and their proofs (`Toy.Acceptance`).
-/

namespace ToyAudit

/-- Equation (3) at `n = 1`: `1 ≤ k · 1²` for every natural number `k`. -/
def bound_range_at_one : Prop := ∀ k : Nat, 1 ≤ k * 1 ^ 2

/-- The choice `k = 0` violates Equation (3) at `n = 1`. -/
theorem bound_range_at_one_false : ¬ bound_range_at_one := fun h => absurd (h 0) (by decide)

/-- Equation (3) with `k ≥ 1`: `n ≤ k n²` for all natural numbers `n` and `k ≥ 1`. -/
def bound_range_corrected : Prop := ∀ n k : Nat, 1 ≤ k → n ≤ k * n ^ 2

/-- Equation (3) holds for every `k ≥ 1`. -/
theorem bound_range_corrected_holds : bound_range_corrected := by
  intro n k hk
  have h1 : n ≤ n * n := Nat.le_mul_self n
  have h2 : n * n ≤ k * (n * n) := Nat.le_mul_of_pos_left (n * n) hk
  rw [Nat.pow_two]
  exact Nat.le_trans h1 h2

end ToyAudit
