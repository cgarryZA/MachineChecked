/-!
# Bounds whose proofs establish more than they export

A synthetic example: integer bounds whose proofs first establish a sharper estimate and then
weaken it, or establish an estimate only under a case hypothesis or for a chosen witness.
-/

namespace Facts

/-- A bound by `C * h` gives a bound by `C * (h + h)` when `C` and `h` are not negative. -/
theorem weaken {x C h : Int} (hC : 0 ≤ C) (hh : 0 ≤ h) (hx : x ≤ C * h) :
    x ≤ C * (h + h) := by
  have hmono : C * h ≤ C * (h + h) := Int.mul_le_mul_of_nonneg_left (by omega) hC
  omega

/-- The exported bound is `C * (h + h)`; the proof first establishes the sharper `C * h`. -/
theorem bound (x C h : Int) (hC : 0 ≤ C) (hh : 0 ≤ h) (hx : x + 1 ≤ C * h) :
    x ≤ C * (h + h) := by
  have strong : x ≤ C * h := by omega
  show x ≤ C * (h + h)
  exact weaken hC hh strong

/-- Without a sign condition on `C` the sharper bound is all the proof establishes. -/
theorem bound_unsigned (x C h : Int) (hx : x + 1 ≤ C * h) : x ≤ C * h := by
  have strong : x ≤ C * h := by omega
  exact strong

/-- The doubled bound is established in the case `0 ≤ h` only, from that case's hypothesis. -/
theorem bound_cases (x C h : Int) (hC : 0 ≤ C) (hx : x + 1 ≤ C * h) :
    x ≤ C * (h + h) ∨ h < 0 := by
  by_cases hh : 0 ≤ h
  · have doubled : x ≤ C * (h + h) := weaken hC hh (by omega)
    exact Or.inl doubled
  · exact Or.inr (by omega)

/-- Each branch of a case split establishes its own bound. -/
theorem branches (x h : Int) (hx : x ≤ h ∨ x ≤ -h) : x ≤ h ∨ x ≤ -h := by
  rcases hx with hp | hn
  · have left_bound : x ≤ h := hp
    exact Or.inl left_bound
  · have right_bound : x ≤ -h := hn
    exact Or.inr right_bound

/-- Two witnesses obtained separately keep separate facts. -/
theorem witnesses (P : Nat → Prop) (h1 : ∃ n, P n) (h2 : ∃ m, P m) :
    (∃ n, P n) ∧ ∃ m, P m := by
  obtain ⟨n, hn⟩ := h1
  obtain ⟨m, hm⟩ := h2
  have first : P n := hn
  have second : P m := hm
  have : P n ∧ P m := ⟨first, second⟩
  exact ⟨⟨n, this.1⟩, ⟨m, this.2⟩⟩

/-- A number at least `n`. Lean moves the proof inside a definition to a lemma of its own. -/
def above (n : Nat) : {m : Nat // n ≤ m} :=
  ⟨n + 1, by
    have step : n ≤ n + 1 := Nat.le_succ n
    exact step⟩

end Facts
