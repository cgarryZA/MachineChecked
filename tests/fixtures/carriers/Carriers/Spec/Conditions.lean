import Carriers.Conditions

/-! Statements whose totalised operations have, or lack, the conditions their rules need. -/

namespace Carriers.Spec

open MeasureTheory

/-- A supremum of a family the statement bounds. -/
def supBounded : Prop := ∀ f : Nat → Real, BddAbove (Set.range f) → iSup f = iSup f

/-- A supremum of a family the statement does not bound. -/
def supUnbounded : Prop := ∀ f : Nat → Real, iSup f = iSup f

/-- A supremum of one family, with a bound for another. -/
def supOther : Prop := ∀ f g : Nat → Real, BddAbove (Set.range g) → iSup f = iSup f

/-- The bound is a later premise of the same statement. -/
def supLater : Prop := ∀ f : Nat → Real, iSup f = iSup f → BddAbove (Set.range f) → True

/-- A bound for every family of a sequence, used at one of them. -/
def supQuantified : Prop :=
  ∀ F : Nat → Nat → Real, (∀ n, BddAbove (Set.range (F n))) → ∀ n, iSup (F n) = iSup (F n)

/-- A bound that holds only under a further hypothesis. -/
def supConditional : Prop :=
  ∀ F : Nat → Nat → Real, (∀ n, n = 0 → BddAbove (Set.range (F n))) → iSup (F 1) = iSup (F 1)

/-- A bounded family over an index type that may be empty. -/
def supEmpty : Prop := ∀ (ι : Type) (f : ι → Real), BddAbove (Set.range f) → iSup f = iSup f

/-- A family the statement assumes unbounded. -/
def supRefuted : Prop := ∀ f : Nat → Real, ¬ BddAbove (Set.range f) → iSup f = iSup f

/-- An infimum and the supremum of a set, each with what it needs. -/
def infAndSet : Prop := ∀ (f : Nat → Real) (s : Set Real),
  BddBelow (Set.range f) → BddAbove s ∧ s.Nonempty → iInf f = iInf f ∧ sSup s = sSup s

/-- Integrals of `f` and `g` for `μ` and `ν`, with `f` integrable for `μ` only. -/
def integrable : Prop := ∀ (μ ν : Measure Nat) (f g : Nat → Real), Integrable f μ →
  integral μ f = integral μ f ∧ integral μ g = integral μ g ∧ integral ν f = integral ν f

/-- An integral over a set, with integrability on that set. -/
def integrableOn : Prop := ∀ (μ : Measure Nat) (s : Set Nat) (f : Nat → Real),
  IntegrableOn f s μ → integral (μ.restrict s) f = integral (μ.restrict s) f

/-- Finite parts of a value known finite, of one that is not, and of a nonnegative number. -/
def finite : Prop := ∀ (x y : ENNReal) (r : NNReal), x ≠ Top.top →
  x.toReal = y.toReal ∧ (ENNReal.ofNNReal r).toReal = (ENNReal.ofNNReal r).toReal

/-- A value finite almost everywhere, converted at one point. -/
def finiteAE : Prop := ∀ (μ : Measure Nat) (f : Nat → ENNReal), AE μ (fun n => f n ≠ Top.top) →
  (f 0).toReal = (f 0).toReal

end Carriers.Spec
