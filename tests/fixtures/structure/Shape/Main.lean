namespace Shape

/-- `f` is bounded by `C`. -/
def Bounded (f : Nat → Nat) (C : Nat) : Prop := ∀ n, f n ≤ C

/-- A statement shaped to exercise the reader's layout: objects with conditions of their own
(`E` with an instance, `j` with `1 ≤ j`), a condition shared by two objects (`j ≤ k`), an
alternating prefix (for all `x` there is `C` such that for all `n`), and a conjunction. -/
theorem layout (E : Type) [Inhabited E] (j : Nat) (hj : 1 ≤ j) (k : Nat) (hjk : j ≤ k) :
    ∀ x : Nat, ∃ C : Nat, ∀ n : Nat, x ≤ C ∧ n + x ≤ n + C := by
  intro x
  exact ⟨x, fun n => ⟨Nat.le_refl x, Nat.le_refl _⟩⟩

/-- Two witnesses of the same name in sibling parts, each of its own type, and one witness
shared by the two parts of its body. -/
theorem witnesses (j : Nat) :
    (∃ x : Nat → Nat, x j = j ∧ j ≤ x j) ∧ (∃ x : Bool, x = true) :=
  ⟨⟨id, rfl, Nat.le_refl j⟩, ⟨true, rfl⟩⟩

/-- A negation, an alternative made of a "for every" and an implication whose conclusion is a
"there is", and an instance that supplies a proposition. -/
theorem shapes (E : Type) [Nonempty E] :
    (¬ ∃ x : Nat, x < 0) ∧ ((∀ n : Nat, 0 ≤ n) ∨ (1 = 1 → ∃ m : Nat, m = 1)) :=
  ⟨fun ⟨x, h⟩ => Nat.not_lt_zero x h, Or.inl fun n => Nat.zero_le n⟩

end Shape
