namespace Shape

/-- The first `k` differences `f j` of `f` are bounded by `C` at every point of `S`. -/
def JetBound (f : Nat → Nat → Nat) (S : Nat → Prop) (k C : Nat) : Prop :=
  ∀ j, j ≤ k → ∀ x, S x → f j x ≤ C

/-- A bound of order `n + 5` gives one of order `n + 4`. -/
theorem jet_lower (f : Nat → Nat → Nat) (S : Nat → Prop) (n C : Nat)
    (h : JetBound f S (n + 5) C) : JetBound f S (n + 4) C :=
  fun j hj x hx => h j (Nat.le_trans hj (Nat.le_succ _)) x hx

/-- Every entry of `v` is at most `bound`, in a type with an order; the length is implicit. -/
def AllBelow {α : Type} [LE α] (bound : α) {n : Nat} (v : Fin n → α) : Prop :=
  ∀ i, v i ≤ bound

/-- `P` holds of every vector of `vs`. -/
def Every {n : Nat} (P : (Fin n → Nat) → Prop) (vs : List (Fin n → Nat)) : Prop :=
  ∀ v, v ∈ vs → P v

/-- A bound named like the definition's own bound variable. -/
theorem below_succ (i : Nat) (v : Fin 3 → Nat) (h : AllBelow i v) : AllBelow (i + 1) v :=
  fun k => Nat.le_succ_of_le (h k)

/-- A partial application: `AllBelow 7` still awaits its vector. -/
theorem every_below (vs : List (Fin 2 → Nat)) (h : Every (AllBelow 7) vs) :
    Every (AllBelow 8) vs :=
  fun v hv i => Nat.le_succ_of_le (h v hv i)

/-- The number of steps down to zero, by recursion with a case condition. -/
def steps (n : Nat) : Nat := if h : n = 0 then 0 else steps (n - 1) + 1
termination_by n
decreasing_by omega

/-- Overlapping patterns: the second equation holds when the first does not apply. -/
def pick : Nat → Nat → Nat
  | 0, _ => 0
  | _, 0 => 1
  | n + 1, m + 1 => pick n m

/-- Recursion at a successor. -/
theorem steps_pos (k : Nat) : 0 < steps (k + 3) := by
  rw [steps]; split <;> omega

/-- The overlapping case at a successor. -/
theorem pick_at (k : Nat) : pick (k + 1) 0 = 1 := rfl

end Shape
