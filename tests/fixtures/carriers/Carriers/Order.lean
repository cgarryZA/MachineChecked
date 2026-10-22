/-!
# Order operations, without a library

A synthetic project with the shapes of suprema a formalisation meets: in a complete lattice (a
lattice of collections of sets, an extended number line), in a conditionally complete number
line, and in a type with neither structure. The names are declared at the root, as the order
library of a larger project declares them.
-/

universe u v

/-- Predicates on `α`, standing in for sets. -/
def Set (α : Type u) : Type u := α → Prop

class SupSet (α : Type u) where
  sSup : Set α → α

class InfSet (α : Type u) where
  sInf : Set α → α

export SupSet (sSup)
export InfSet (sInf)

/-- The values of a family. -/
def Set.range {α : Type u} {ι : Sort v} (f : ι → α) : Set α := fun a => ∃ i, f i = a

/-- The supremum of a family. -/
def iSup {α : Type u} {ι : Sort v} [SupSet α] (s : ι → α) : α := sSup (Set.range s)

/-- The infimum of a family. -/
def iInf {α : Type u} {ι : Sort v} [InfSet α] (s : ι → α) : α := sInf (Set.range s)

/-- Every family has a supremum and an infimum. -/
class CompleteLattice (α : Type u) extends SupSet α, InfSet α

/-- A bounded nonempty family has a supremum and an infimum. -/
class ConditionallyCompleteLattice (α : Type u) extends SupSet α, InfSet α

/-- A number line where only bounded families have a supremum. -/
structure Real where
  val : Int

instance : ConditionallyCompleteLattice Real where
  sSup _ := ⟨0⟩
  sInf _ := ⟨0⟩

/-- A number line with a top element, where every family has a supremum. -/
structure ENNReal where
  val : Option Nat

instance : CompleteLattice ENNReal where
  sSup _ := ⟨none⟩
  sInf _ := ⟨some 0⟩

/-- Its finite part, with `0` at the top. -/
def ENNReal.toReal (x : ENNReal) : Real := ⟨(x.val.getD 0 : Nat)⟩

/-- Collections of subsets of `Ω`, ordered by inclusion: a complete lattice. -/
structure MeasurableSpace (Ω : Type u) where
  sets : Set (Set Ω)

instance (Ω : Type u) : CompleteLattice (MeasurableSpace Ω) where
  sSup _ := ⟨fun _ => True⟩
  sInf _ := ⟨fun _ => False⟩

/-- Another name for the number line. -/
abbrev Value := Real

/-- A type with a supremum and no lattice structure. -/
structure Plain where
  n : Nat

instance : SupSet Plain where
  sSup _ := ⟨0⟩
