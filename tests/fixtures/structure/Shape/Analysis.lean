/-!
# Stand-ins for notions of analysis

Synthetic declarations under the names Mathlib gives them, each with the explicit arguments
Mathlib's has, so that the probe reads a statement written with them as it reads one written
with Mathlib's: real numbers, sets, σ-algebras, measures, almost everywhere, classes of functions
equal almost everywhere and their representatives, square-integrable classes, Euclidean spaces
and linear isometries. They model nothing beyond their shapes; the predicates hold trivially.
-/

universe u v w

/-- Real numbers (a stand-in). -/
structure Real where
  val : Nat

@[inherit_doc] notation "ℝ" => Real

instance : OfNat Real n := ⟨⟨n⟩⟩
instance : NatCast Real := ⟨fun n => ⟨n⟩⟩
instance : LE Real := ⟨fun a b => a.val ≤ b.val⟩
instance : LT Real := ⟨fun a b => a.val < b.val⟩

/-- Extended nonnegative reals (a stand-in). -/
structure ENNReal where
  val : Nat

@[inherit_doc] notation "ℝ≥0∞" => ENNReal

instance : OfNat ENNReal n := ⟨⟨n⟩⟩
instance : LE ENNReal := ⟨fun a b => a.val ≤ b.val⟩

/-- Sets of elements of `α`. -/
def Set (α : Type u) := α → Prop

instance : Membership α (Set α) := ⟨fun s a => s a⟩

/-- Functions from `F`, applied as functions from `α`. -/
class DFunLike (F : Sort u) (α : outParam (Sort v)) (β : outParam (α → Sort w)) where
  /-- `F` applied as a function. -/
  coe : F → ∀ a : α, β a

attribute [coe] DFunLike.coe

instance (priority := 100) DFunLike.hasCoeToFun {F α β} [DFunLike F α β] :
    CoeFun F (fun _ => ∀ a : α, β a) where
  coe := @DFunLike.coe _ _ β _

/-- A σ-algebra on `α`: the sets called measurable. -/
class MeasurableSpace (α : Type u) where
  /-- The measurable sets. -/
  MeasurableSet' : Set α → Prop
  measurableSet_empty : MeasurableSet' (fun _ => False)
  measurableSet_compl : ∀ s, MeasurableSet' s → MeasurableSet' (fun a => ¬ s a)

instance {α β : Type u} [MeasurableSpace α] [MeasurableSpace β] : MeasurableSpace (α × β) :=
  ⟨fun _ => True, trivial, fun _ _ => trivial⟩

/-- A filter on `α` (a stand-in). -/
structure Filter (α : Type u) where
  /-- The sets of the filter. -/
  sets : Set α → Prop

instance : Inhabited (Filter α) := ⟨⟨fun _ => True⟩⟩

/-- `p` holds eventually along `f` (a stand-in). -/
inductive Filter.Eventually {α : Type u} (p : α → Prop) (f : Filter α) : Prop
  | intro

/-- `f` and `g` agree eventually along `l` (a stand-in). -/
inductive Filter.EventuallyEq {α : Type u} {β : Type v} (l : Filter α) (f g : α → β) : Prop
  | intro

namespace MeasureTheory

/-- A measure on `α` (a stand-in): a function of sets, zero on the empty set and monotone. -/
structure Measure (α : Type u) [MeasurableSpace α] where
  /-- The measure of a set. -/
  measureOf : Set α → ℝ≥0∞
  empty : measureOf (fun _ => False) = 0
  mono : ∀ s t : Set α, (∀ a, s a → t a) → measureOf s ≤ measureOf t

instance {α : Type u} [MeasurableSpace α] : DFunLike (Measure α) (Set α) (fun _ => ℝ≥0∞) :=
  ⟨Measure.measureOf⟩

instance {α : Type u} [MeasurableSpace α] : Inhabited (Measure α) :=
  ⟨⟨fun _ => 0, rfl, fun _ _ _ => Nat.le_refl 0⟩⟩

/-- The product of two measures (a stand-in). -/
opaque Measure.prod {α β : Type u} [MeasurableSpace α] [MeasurableSpace β] (μ : Measure α)
    (ν : Measure β) : Measure (α × β)

/-- Almost everywhere for `μ` (a stand-in). -/
opaque ae {α : Type u} [MeasurableSpace α] (μ : Measure α) : Filter α

/-- `μ` is σ-finite: the space is covered by countably many sets (a stand-in). -/
class SigmaFinite {α : Type u} {m0 : MeasurableSpace α} (μ : @Measure α m0) : Prop where
  out' : ∃ s : Nat → Set α, ∀ a, ∃ n, s n a

/-- Functions from `α` to `β` up to equality `μ`-almost everywhere (a stand-in). -/
structure AEEqFun (α : Type u) (β : Type v) [MeasurableSpace α] (μ : Measure α) where
  /-- A representative of the class. -/
  cast : α → β

/-- The classes of functions from `α` to `E` with a finite `p`-norm for `μ` (a stand-in). -/
structure Lp {α : Type u} (E : Type v) {m : MeasurableSpace α} (p : ℝ≥0∞) (μ : @Measure α m) where
  /-- The class. -/
  toAEEqFun : @AEEqFun α E m μ

instance {α : Type u} {E : Type v} {m : MeasurableSpace α} {p : ℝ≥0∞} {μ : @Measure α m} :
    CoeFun (Lp E p μ) (fun _ => α → E) :=
  ⟨fun f => f.toAEEqFun.cast⟩

end MeasureTheory

/-- Tuples of scalars indexed by `n`, with the Euclidean norm (a stand-in). -/
structure EuclideanSpace (𝕜 : Type u) (n : Type v) where
  /-- The coordinates. -/
  coords : n → 𝕜

/-- A ring homomorphism (a stand-in). -/
structure RingHom (R : Type u) (S : Type v) where
  /-- The map. -/
  toFun : R → S

instance : Inhabited (RingHom R R) := ⟨⟨fun r => r⟩⟩

/-- The identity of `R` (a stand-in). -/
opaque RingHom.id (R : Type u) : RingHom R R

/-- A linear isometric equivalence (a stand-in): a bijection with its inverse. -/
structure LinearIsometryEquiv {R R₂ : Type u} (σ₁₂ : RingHom R R₂) (E : Type v) (E₂ : Type w) where
  /-- The map. -/
  toFun : E → E₂
  /-- Its inverse. -/
  invFun : E₂ → E
  left_inv : ∀ x, invFun (toFun x) = x

@[inherit_doc] notation:25 E " ≃ₗᵢ[" R:25 "] " E₂:0 => LinearIsometryEquiv (RingHom.id R) E E₂

instance {R R₂ : Type u} {σ : RingHom R R₂} {E : Type v} {E₂ : Type w} :
    DFunLike (LinearIsometryEquiv σ E E₂) E (fun _ => E₂) :=
  ⟨LinearIsometryEquiv.toFun⟩
