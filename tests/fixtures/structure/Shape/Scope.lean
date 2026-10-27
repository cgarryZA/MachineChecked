namespace Shape

/-- An assumption that contains a conditional existence claim: its `y` belongs to the
assumption, and the statement's own `y` is the one it establishes. -/
theorem conditional (A : Nat → Prop) (B : Nat → Nat → Prop) (h : ∀ x, A x → ∃ y, B x y)
    (a : Nat) (ha : A a) : ∃ y, B a y :=
  h a ha

/-- For every `x` there is `y` such that the bound holds for every `z`. -/
theorem alternating : ∀ x : Nat, ∃ y : Nat, ∀ z : Nat, x + z ≤ y + z :=
  fun x => ⟨x, fun _ => Nat.le_refl _⟩

/-- An existence established under a premise, an equivalence with an existence on one side, and
a witness in one alternative. -/
theorem premised (P Q : Prop) (hq : Q) :
    (P → ∃ x : Nat, x = 0) ∧ (Q ↔ ∃ n : Nat, n = n) ∧ ((∃ x : Nat, x = 1) ∨ Q) :=
  ⟨fun _ => ⟨0, rfl⟩, ⟨fun _ => ⟨0, rfl⟩, fun _ => hq⟩, Or.inr hq⟩

/-- A map from `G` to `H` over the scalars `K`. -/
structure Linear (K G H : Type) where
  toFun : G → H

/-- `G →[K] H`: a map from `G` to `H` over `K`. -/
notation:25 G " →[" K "] " H => Linear K G H

/-- One witness with two properties, whose type names its domain, codomain and scalars; each
assumption has a `Φ` of its own. -/
theorem one_map (G H : Type) (f : G → H) (A B : (G →[Nat] H) → Prop) (hA : ∀ Φ, A Φ)
    (hB : ∀ Φ, B Φ) : ∃ Φ : G →[Nat] H, A Φ ∧ B Φ :=
  ⟨⟨f⟩, hA _, hB _⟩

end Shape
