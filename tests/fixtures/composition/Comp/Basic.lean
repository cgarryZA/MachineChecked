/-!
# Witnesses and even sums

A synthetic development for compositions: a claim that holds by combining an existence theorem
with a property of the witness it produces, two separate existence theorems whose witnesses
need not agree, and the sum rule for even numbers.
-/

namespace Comp

/-- `n` is even. -/
def Even (n : Nat) : Prop := ∃ k, n = 2 * k

/-- There is a positive even number. -/
theorem exists_pos_even : ∃ n, 0 < n ∧ Even n := ⟨2, by decide, 1, rfl⟩

/-- There is a positive number. -/
theorem exists_pos : ∃ n : Nat, 0 < n := ⟨1, by decide⟩

/-- There is an even number. -/
theorem exists_even : ∃ n, Even n := ⟨0, 0, rfl⟩

/-- The sum of two even numbers is even. -/
theorem even_add {a b : Nat} (ha : Even a) (hb : Even b) : Even (a + b) := by
  obtain ⟨i, rfl⟩ := ha
  obtain ⟨j, rfl⟩ := hb
  exact ⟨i + j, by omega⟩

end Comp
