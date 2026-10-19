/-!
# A synthetic example of uses and applications

`half_lt` has an extra condition, `Good n`. One caller assumes it, another proves it for the
number it constructs. A specialised helper is used by a general wrapper in `Uses.Paper`.
-/

namespace Uses

/-- A natural number is good when it is even. -/
def Good (n : Nat) : Prop := ∃ k, n = 2 * k

/-- The good numbers, as a set: a reference to `Good` in a definition's body. -/
def goodSet : Nat → Prop := Good

theorem good_double (n : Nat) : Good (2 * n) := ⟨n, rfl⟩

/-- The general lemma: a good positive number exceeds its half. -/
theorem half_lt (n : Nat) (h : Good n) (hpos : 0 < n) : n / 2 < n :=
  Nat.div_lt_self hpos (by decide)

/-- The first caller assumes the extra condition. -/
theorem caller_assumes (m : Nat) (hm : Good m) (hp : 0 < m) : m / 2 < m :=
  half_lt m hm hp

/-- The second caller proves the condition for the number it constructs. -/
theorem caller_proves (m : Nat) : 2 * (m + 1) / 2 < 2 * (m + 1) :=
  half_lt (2 * (m + 1)) (good_double (m + 1)) (by omega)

/-- A statement that mentions `Good` without using `half_lt`. -/
theorem good_zero : Good 0 := ⟨0, rfl⟩

/-- Two applications whose arguments are both printed `x`, bound in different scopes. -/
theorem twice : (∀ x : Nat, Good (2 * x)) ∧ (∀ x : Nat, Good (2 * x)) :=
  ⟨fun x => good_double x, fun x => good_double x⟩

/-- An implicit type, an instance and a premise about a local list. -/
theorem length_pos {α : Type} [Inhabited α] (xs : List α) (x : α) (h : x ∈ xs) :
    0 < xs.length := by
  cases xs with
  | nil => cases h
  | cons _ _ => simp

theorem uses_instance (ys : List Nat) (y : Nat) (hy : y ∈ ys) : 0 < ys.length :=
  length_pos ys y hy

/-- A specialised helper: the lemma at four. -/
theorem half_lt_four : 4 / 2 < 4 := half_lt 4 (good_double 2) (by decide)

end Uses
