import Comp.Basic

namespace Comp

/-- Some positive number added to itself is even. -/
def Spec.pos_double_even : Prop := ∃ n : Nat, 0 < n ∧ Even (n + n)

/-- Some number added to itself is even. -/
def Spec.double_even : Prop := ∃ n : Nat, Even (n + n)

theorem pos_double_even : Spec.pos_double_even := by
  obtain ⟨n, hn, he⟩ := exists_pos_even
  exact ⟨n, hn, even_add he he⟩

theorem double_even : Spec.double_even := ⟨0, even_add ⟨0, rfl⟩ ⟨0, rfl⟩⟩

end Comp
