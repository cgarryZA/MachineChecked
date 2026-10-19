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

/-- `n` is a multiple of `m` with a quotient of at least `b`; `m` is written implicitly. -/
def MultipleAbove (b : Nat) {m : Nat} (n : Nat) : Prop := ∃ q, b ≤ q ∧ n = m * q

/-- The Fibonacci numbers, by recursion with three equations. -/
def fib : Nat → Nat
  | 0 => 0
  | 1 => 1
  | n + 2 => fib n + fib (n + 1)

/-- A path starting at `d`. -/
structure Base (d : Nat) where
  path : Nat → Nat
  start : path 0 = d

/-- A solution for the datum `d`: a path from `d` with a bound it never exceeds. Its fields are
data (`path`, `bound`) and properties (`start`, inherited from `Base`, and `le_bound`). -/
structure Solution (d : Nat) extends Base d where
  bound : Nat
  le_bound : ∀ n, path n ≤ bound

/-- A datum small enough to have a solution. -/
def Admissible (d : Nat) : Prop := d ≤ 10

/-- A solution whose bound is at most `d + 10`. -/
def Good {d : Nat} (s : Solution d) : Prop := s.bound ≤ d + 10

/-- A supplied solution: its fields are part of what is given. -/
theorem supplied (d : Nat) (s : Solution d) (h : s.bound ≤ 5) : s.path 0 ≤ 5 :=
  Nat.le_trans (s.le_bound 0) h

/-- An assumed existence of solutions: the solution belongs to the assumption. -/
theorem assumed (h : ∀ d, Admissible d → ∃ s : Solution d, Good s) :
    ∃ s : Solution 0, Good s :=
  h 0 (Nat.zero_le 10)

/-- An established existence of solutions: the solution is produced by the statement. -/
theorem produced : ∀ d, Admissible d → ∃ s : Solution d, Good s :=
  fun d _ => ⟨⟨⟨fun _ => d, rfl⟩, d, fun _ => Nat.le_refl d⟩, Nat.le_add_right d 10⟩

/-- A positive number: positivity is part of the subtype. -/
theorem positive (p : {n : Nat // 0 < n}) : 1 ≤ p.val := p.property

/-- A type with exactly one element, as a class with a law. -/
class Single (α : Type) extends Inhabited α where
  uniq : ∀ a : α, a = default

/-- An input with one element: the class's law is part of what is given; `Subsingleton` says
there is at most one element, and the conclusion says there is one and only one. -/
theorem single (T : Type) [Single T] : Subsingleton T ∧ ∃ x : T, ∀ y : T, y = x :=
  ⟨⟨fun a b => (Single.uniq a).trans (Single.uniq b).symm⟩, ⟨default, Single.uniq⟩⟩

/-- A measurable space with a measure: a family of measurable sets closed under complement, and
a measure of sets with the empty set of measure zero. -/
class MeasureData (Ω : Type) where
  measurable : (Ω → Prop) → Prop
  measurable_compl : ∀ A, measurable A → measurable (fun ω => ¬ A ω)
  measure : (Ω → Prop) → Nat
  measure_empty : measure (fun _ => False) = 0

/-- The whole space has measure one. -/
class IsProbability (Ω : Type) [MeasureData Ω] : Prop where
  measure_univ : MeasureData.measure (fun _ : Ω => True) = 1

/-- A measure space is supplied; that it is a probability space is an additional assumption. -/
theorem probability (Ω : Type) [MeasureData Ω] [IsProbability Ω] :
    MeasureData.measure (fun _ : Ω => True) = 1 :=
  IsProbability.measure_univ

/-- Inside a negation, a solution and its properties are local to the negated claim. -/
theorem none_large : ¬ ∃ s : Solution 0, s.bound < 0 :=
  fun ⟨_, h⟩ => Nat.not_lt_zero _ h

/-- An assumed conjunction is one assumption with two parts. -/
theorem both (a b : Nat) (h : a ≤ b ∧ b ≤ a) : a = b :=
  Nat.le_antisymm h.1 h.2

end Shape
