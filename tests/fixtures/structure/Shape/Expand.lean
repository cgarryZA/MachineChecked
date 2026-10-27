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

/-- A digit with seventy values: more than a declaration's record lists of its equations. -/
inductive Digit where
  | d0 | d1 | d2 | d3 | d4 | d5 | d6 | d7 | d8 | d9
  | d10 | d11 | d12 | d13 | d14 | d15 | d16 | d17 | d18 | d19
  | d20 | d21 | d22 | d23 | d24 | d25 | d26 | d27 | d28 | d29
  | d30 | d31 | d32 | d33 | d34 | d35 | d36 | d37 | d38 | d39
  | d40 | d41 | d42 | d43 | d44 | d45 | d46 | d47 | d48 | d49
  | d50 | d51 | d52 | d53 | d54 | d55 | d56 | d57 | d58 | d59
  | d60 | d61 | d62 | d63 | d64 | d65 | d66 | d67 | d68 | d69

/-- The value of a digit, by one equation for each of the seventy. -/
def Digit.val : Digit → Nat
  | .d0 => 0
  | .d1 => 1
  | .d2 => 2
  | .d3 => 3
  | .d4 => 4
  | .d5 => 5
  | .d6 => 6
  | .d7 => 7
  | .d8 => 8
  | .d9 => 9
  | .d10 => 10
  | .d11 => 11
  | .d12 => 12
  | .d13 => 13
  | .d14 => 14
  | .d15 => 15
  | .d16 => 16
  | .d17 => 17
  | .d18 => 18
  | .d19 => 19
  | .d20 => 20
  | .d21 => 21
  | .d22 => 22
  | .d23 => 23
  | .d24 => 24
  | .d25 => 25
  | .d26 => 26
  | .d27 => 27
  | .d28 => 28
  | .d29 => 29
  | .d30 => 30
  | .d31 => 31
  | .d32 => 32
  | .d33 => 33
  | .d34 => 34
  | .d35 => 35
  | .d36 => 36
  | .d37 => 37
  | .d38 => 38
  | .d39 => 39
  | .d40 => 40
  | .d41 => 41
  | .d42 => 42
  | .d43 => 43
  | .d44 => 44
  | .d45 => 45
  | .d46 => 46
  | .d47 => 47
  | .d48 => 48
  | .d49 => 49
  | .d50 => 50
  | .d51 => 51
  | .d52 => 52
  | .d53 => 53
  | .d54 => 54
  | .d55 => 55
  | .d56 => 56
  | .d57 => 57
  | .d58 => 58
  | .d59 => 59
  | .d60 => 60
  | .d61 => 61
  | .d62 => 62
  | .d63 => 63
  | .d64 => 64
  | .d65 => 65
  | .d66 => 66
  | .d67 => 67
  | .d68 => 68
  | .d69 => 69

/-- The last digit's value: the equation that applies is the seventieth. -/
theorem last_digit : Digit.val .d69 = 69 := rfl

end Shape
