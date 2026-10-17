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

end Shape
