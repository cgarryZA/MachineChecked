import Carriers.Algebra

/-! Statements with divisions, inverses, integrals, sums and roots in different types. -/

namespace Carriers.Spec

open MeasureTheory

/-- Division of natural numbers. -/
def divNat : Prop := ∀ a b : Nat, a / b = a / b

/-- Division on the number line, a field. -/
def divField : Prop := ∀ x y : Real, x / y = x / y ∧ x⁻¹ = x⁻¹

/-- Division on the extended number line. -/
def divExtended : Prop := ∀ x y : ENNReal, x / y = x / y

/-- Division and inverse in a group. -/
def divGroup : Prop := ∀ a b : Turn, a / b = a / b ∧ a⁻¹ = a⁻¹

/-- Division in a type with no group structure. -/
def divPlain : Prop := ∀ a b : Plain, a / b = a / b

/-- Division in a type the statement quantifies over. -/
def divPoly : Prop := ∀ (α : Type) [Div α] (a b : α), a / b = a / b

/-- An integral of numbers, and one of functions into a type with one element. -/
def integrals : Prop := ∀ (μ : Measure Nat) (f : Nat → Real) (g : Nat → Unit),
  integral μ f = integral μ f ∧ integral μ g = integral μ g

/-- An integral of functions into a type with one element only. -/
def integralUnit : Prop := ∀ (μ : Measure Nat) (g : Nat → Unit), integral μ g = integral μ g

/-- A sum on the extended number line. -/
def sumExtended : Prop := ∀ f : Nat → ENNReal, tsum f = tsum f

/-- A sum on the number line. -/
def sumReal : Prop := ∀ f : Nat → Real, tsum f = tsum f

/-- A square root, applied and as a function. -/
def roots : Prop := ∀ f : Nat → Real, (fun n => Real.sqrt (f n)) = fun n => (Real.sqrt ∘ f) n

end Carriers.Spec
