import Carriers.Algebra
/-!
# Side conditions, without a library

The conditions the rules of totalised operations need, declared at the root as a larger
project's library declares them: bounds and nonemptiness of a family or a set, integrability of
a function for a measure, finiteness of an extended number, and a property holding almost
everywhere.
-/

universe u v

instance : LE Real where
  le a b := a.val ≤ b.val

/-- `s` has an upper bound. -/
def BddAbove {α : Type u} [LE α] (s : Set α) : Prop := ∃ b, ∀ a, s a → a ≤ b

/-- `s` has a lower bound. -/
def BddBelow {α : Type u} [LE α] (s : Set α) : Prop := ∃ b, ∀ a, s a → b ≤ a

/-- `s` has an element. -/
def Set.Nonempty {α : Type u} (s : Set α) : Prop := ∃ a, s a

/-- A top element. -/
class Top (α : Type u) where
  top : α

instance : Top ENNReal := ⟨⟨none⟩⟩

/-- Nonnegative numbers, standing in. -/
structure NNReal where
  val : Nat

/-- A nonnegative number as an extended one. -/
def ENNReal.ofNNReal (r : NNReal) : ENNReal := ⟨some r.val⟩

namespace MeasureTheory

/-- `f` is integrable for `μ`, standing in. -/
def Integrable {α : Type u} {G : Type v} (_f : α → G) (_μ : Measure α) : Prop := True

/-- The restriction of `μ` to `s`, standing in. -/
def Measure.restrict {α : Type u} (μ : Measure α) (_s : Set α) : Measure α := μ

/-- `f` is integrable on `s` for `μ`. -/
def IntegrableOn {α : Type u} {G : Type v} (f : α → G) (s : Set α) (μ : Measure α) : Prop :=
  Integrable f (μ.restrict s)

end MeasureTheory

/-- `p` holds almost everywhere for `μ`, standing in. -/
def AE {α : Type u} (_μ : MeasureTheory.Measure α) (_p : α → Prop) : Prop := True
