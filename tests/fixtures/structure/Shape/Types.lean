namespace Shape

/-! Properties carried by types, and where each comes from. -/

/-- A profile: a function with a bound on its values (the abstract definition). -/
structure Profile where
  f : Nat → Nat
  C : Nat
  bound : ∀ n, f n ≤ C

/-- A concrete profile: a profile that vanishes from `N` on and has period `p` below `N`. -/
structure Concrete extends Profile where
  N : Nat
  support : ∀ n, N ≤ n → f n = 0
  p : Nat
  periodic : ∀ n, n + p < N → f (n + p) = f n

/-- The zero profile below `N`: a construction whose value is a concrete profile. -/
def build (N : Nat) : Concrete :=
  { f := fun _ => 0, C := 0, bound := fun _ => Nat.le_refl 0, N := N,
    support := fun _ _ => rfl, p := 1, periodic := fun _ _ => rfl }

/-- The construction's recurrence, proved by a theorem of its own. -/
theorem build_rec (N n : Nat) : (build N).f (n + 1) = (build N).f n := rfl

/-- A helper accepting a concrete profile: its support is a condition on its input. -/
theorem vanishes (c : Concrete) (n : Nat) (h : c.N ≤ n) : c.f n = 0 :=
  c.support n h

/-- A family bounded at every scale, for a datum `d` and a weight `w`. -/
structure Scaled (d : Nat) (w : Nat → Nat) where
  g : Nat → Nat
  scale : ∀ k, ∃ m, ∀ n, k ≤ n → g n ≤ m * w k + d

/-- A scaled family that starts at `d`. -/
structure ScaledStart (d : Nat) (w : Nat → Nat) extends Scaled d w where
  start : g 0 = d

/-- A scaled family at `d` and `w`: its inherited field keeps both parameters and its nested
quantifiers. -/
theorem scaled (d : Nat) (w : Nat → Nat) (s : ScaledStart d w) : s.g 0 = d :=
  s.start

/-- A point with a positive first coordinate. -/
structure Anchor where
  x0 : Nat
  pos : 0 < x0

/-- An anchor with a left extent. -/
structure Left extends Anchor where
  l : Nat

/-- An anchor with a right extent at most its first coordinate. -/
structure Right extends Anchor where
  r : Nat
  r_le : r ≤ x0

/-- Both extents: `Anchor` is inherited along two paths, and its fields occur once. -/
structure Both extends Left, Right

/-- An object with both extents: its positivity is one field, inherited once. -/
theorem both_pos (b : Both) : 0 < b.x0 :=
  b.pos

end Shape
