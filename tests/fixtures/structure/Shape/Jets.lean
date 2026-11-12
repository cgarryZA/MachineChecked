/-!
# Derivative bounds and norms that differ only in what they range over

Stand-ins for the estimates of analysis, without Mathlib. A table `D a b t x` stands for the
mixed derivative `∂ₜᵃ ∂ₓᵇ u` of a function `u` of time `t` and space `x`. The three jet bounds
bound the derivatives in space only, in time only, and in all variables; the two norms are the
largest value of a function of time and space over the points up to `N` at one time, and over
the times up to `N` at one point. Each differs from the others only in the variables or the
domain it ranges over.
-/

namespace Shape

/-- The derivatives in space of order at most `k` are bounded by `C`: `∂ₓᵇ u ≤ C` for `b ≤ k`. -/
def SpaceJet (D : Nat → Nat → Nat → Nat → Nat) (k C : Nat) : Prop :=
  ∀ b, b ≤ k → ∀ t x, D 0 b t x ≤ C

/-- The derivatives in time of order at most `k` are bounded by `C`: `∂ₜᵃ u ≤ C` for `a ≤ k`. -/
def TimeJet (D : Nat → Nat → Nat → Nat → Nat) (k C : Nat) : Prop :=
  ∀ a, a ≤ k → ∀ t x, D a 0 t x ≤ C

/-- Every derivative of total order at most `k`, in time and space together, is bounded by `C`:
`∂ₜᵃ ∂ₓᵇ u ≤ C` for `a + b ≤ k`. -/
def FullJet (D : Nat → Nat → Nat → Nat → Nat) (k C : Nat) : Prop :=
  ∀ a b, a + b ≤ k → ∀ t x, D a b t x ≤ C

/-- The largest of `g 0, …, g N`. -/
def maxUpTo (g : Nat → Nat) : Nat → Nat
  | 0 => g 0
  | N + 1 => max (maxUpTo g N) (g (N + 1))

/-- The norm in space at the time `t`: the largest value of `u t x` over the points `x ≤ N`. -/
def supSpace (u : Nat → Nat → Nat) (t N : Nat) : Nat := maxUpTo (u t) N

/-- The norm in time at the point `x`: the largest value of `u s x` over the times `s ≤ N`. -/
def supTime (u : Nat → Nat → Nat) (x N : Nat) : Nat := maxUpTo (fun s => u s x) N

/-- A bound on every derivative of total order at most `k` bounds the derivatives in space and
the derivatives in time of order at most `k`. -/
theorem full_jet_split (D : Nat → Nat → Nat → Nat → Nat) (k C : Nat) (h : FullJet D k C) :
    SpaceJet D k C ∧ TimeJet D k C :=
  ⟨fun b hb t x => h 0 b (by omega) t x, fun a ha t x => h a 0 (by omega) t x⟩

/-- A bound on the norm in space at the time `t` and one on the norm in time at the point `x`:
two bounds on two domains, each kept as it is. -/
theorem norm_bounds (u : Nat → Nat → Nat) (t x N C : Nat) (hs : supSpace u t N ≤ C)
    (ht : supTime u x N ≤ C) : supSpace u t N ≤ C ∧ supTime u x N ≤ C :=
  ⟨hs, ht⟩

end Shape
