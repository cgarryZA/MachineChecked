import Carriers.Order

/-! Statements whose suprema are taken in different types. -/

namespace Carriers.Spec

/-- A join of a family of collections of sets. -/
def join : Prop := ∀ (Ω : Type) (F : Nat → MeasurableSpace Ω), iSup F = iSup F

/-- A supremum on the extended number line, then its finite part. -/
def extended : Prop := ∀ f : Nat → ENNReal, (iSup f).toReal = (iSup f).toReal

/-- A supremum on the number line. -/
def real : Prop := ∀ f : Nat → Real, iSup f = iSup f

/-- A supremum on the number line under another name. -/
def alias : Prop := ∀ f : Nat → Value, iSup f = iSup f

/-- A join and a supremum on the number line in one statement. -/
def both : Prop :=
  ∀ (Ω : Type) (F : Nat → MeasurableSpace Ω) (f : Nat → Real), iSup F = iSup F ∧ iSup f = iSup f

/-- The supremum of a set of numbers, and a bounded-index supremum. -/
def sets : Prop := ∀ (s : Set Real) (f : Nat → Real),
  sSup s = sSup s ∧ iInf (fun u => iInf (fun (_ : u ≤ 3) => f u)) = f 0

/-- A supremum in a type with no lattice structure. -/
def plain : Prop := ∀ f : Nat → Plain, iSup f = iSup f

/-- A supremum in a type the statement quantifies over. -/
def poly : Prop := ∀ (α : Type) [SupSet α] (f : Nat → α), iSup f = iSup f

end Carriers.Spec
