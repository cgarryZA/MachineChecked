/-!
# Applications read in one declaration

`lt_double` has a condition. `from_fact` applies it at a number it constructs, with the condition
from a fact established earlier in its proof, and keeps another fact in the context that the
application does not use. `many` applies it nine times: more than a search of the whole project
describes in one declaration.
-/

namespace Uses

theorem lt_double (n : Nat) (h : 0 < n) : n < 2 * n := by omega

theorem from_fact (m : Nat) : m + 1 < 2 * (m + 1) := by
  have _other : m ≤ m + 1 := Nat.le_succ m
  have hpos : 0 < m + 1 := Nat.succ_pos m
  exact lt_double (m + 1) hpos

theorem many (m : Nat) (h : 0 < m) :
    m < 2 * m ∧ m < 2 * m ∧ m < 2 * m ∧ m < 2 * m ∧ m < 2 * m ∧ m < 2 * m ∧ m < 2 * m ∧
      m < 2 * m ∧ m < 2 * m :=
  ⟨lt_double m h, lt_double m h, lt_double m h, lt_double m h, lt_double m h, lt_double m h,
    lt_double m h, lt_double m h, lt_double m h⟩

end Uses
