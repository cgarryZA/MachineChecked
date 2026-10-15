/-!
# Divisibility facts

A small Lean development written the ordinary way: theorems state the results directly.
-/

namespace Plain

/-- `n` is odd. -/
def Odd (n : Nat) : Prop := ∃ k, n = 2 * k + 1

/-- The sum of two odd numbers is even. -/
theorem odd_add_odd {a b : Nat} (ha : Odd a) (hb : Odd b) : ∃ k, a + b = 2 * k := by
  obtain ⟨i, rfl⟩ := ha
  obtain ⟨j, rfl⟩ := hb
  exact ⟨i + j + 1, by omega⟩

/-- Theorem 3 of the paper: the square of an odd number is odd. -/
theorem sq_odd {n : Nat} (h : Odd n) : Odd (n * n) := by
  obtain ⟨k, rfl⟩ := h
  refine ⟨2 * k * k + 2 * k, ?_⟩
  have h : (2 * k + 1) * (2 * k + 1) = 4 * (k * k) + 4 * k + 1 := by
    rw [Nat.add_mul, Nat.mul_add, Nat.mul_add, Nat.mul_assoc, Nat.mul_comm k (2 * k),
      Nat.mul_assoc]
    omega
  have h2 : 2 * k * k = 2 * (k * k) := Nat.mul_assoc 2 k k
  omega

end Plain
