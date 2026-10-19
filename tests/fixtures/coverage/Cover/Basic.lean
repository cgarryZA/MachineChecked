/-!
# Even numbers

A synthetic development for the coverage readings of the reader: one theorem stating a claim
directly, one claim that follows only by combining a theorem with itself, and one claim stated
as a proposition with a theorem whose type is exactly it.
-/

namespace Cover

/-- `n` is even. -/
def Even (n : Nat) : Prop := ∃ k, n = 2 * k

/-- The sum of two even numbers is even. -/
theorem even_add {a b : Nat} (ha : Even a) (hb : Even b) : Even (a + b) := by
  obtain ⟨i, rfl⟩ := ha
  obtain ⟨j, rfl⟩ := hb
  exact ⟨i + j, by omega⟩

/-- Twice a number is even. -/
theorem even_two_mul (n : Nat) : Even (2 * n) := ⟨n, rfl⟩

end Cover
