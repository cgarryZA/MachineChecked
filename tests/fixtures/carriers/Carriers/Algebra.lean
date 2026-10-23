import Carriers.Order
/-!
# Division, inverses, integrals and roots, without a library

The other operations whose value outside their intended domain depends on the type: division and
inverse in a group, in a group with zero (a field) and on the extended number line, an integral
of functions valued in a type with one element, and a sum on the extended number line. The names
are declared at the root, as a larger project's library declares them.
-/

universe u v

/-- A group: division and inverse have no exceptional case. -/
class Group (α : Type u) extends Div α, Inv α

/-- A group with zero, such as a field: `x / 0 = 0` and `0⁻¹ = 0`. -/
class GroupWithZero (α : Type u) extends Div α, Inv α

instance : GroupWithZero Real where
  div _ _ := ⟨0⟩
  inv _ := ⟨0⟩

instance : Div ENNReal where
  div _ _ := ⟨none⟩

instance : Inv ENNReal where
  inv _ := ⟨none⟩

instance : Inhabited Real := ⟨⟨0⟩⟩

instance : Inhabited ENNReal := ⟨⟨none⟩⟩

/-- Quarter turns of a circle: a group. -/
structure Turn where
  k : Nat

instance : Group Turn where
  div _ _ := ⟨0⟩
  inv _ := ⟨0⟩

instance : Div Plain where
  div _ _ := ⟨0⟩

namespace MeasureTheory

/-- A measure, standing in. -/
structure Measure (α : Type u) where
  mass : Nat

/-- The integral of `f` against `μ`, standing in for the Bochner integral. -/
def integral {α : Type u} {G : Type v} [Inhabited G] (_μ : Measure α) (_f : α → G) : G :=
  default

end MeasureTheory

/-- The sum of a family, standing in for an unconditional sum. -/
def tsum {α : Type u} {β : Type v} [Inhabited α] (_f : β → α) : α := default

/-- The square root, standing in. -/
def Real.sqrt (x : Real) : Real := x
