import Cover.Basic

namespace Cover

/-- The sum of three even numbers is even. -/
def Spec.three_even : Prop :=
  ∀ a b c : Nat, Even a → Even b → Even c → Even (a + b + c)

theorem three_even : Spec.three_even :=
  fun _ _ _ ha hb hc => even_add (even_add ha hb) hc

end Cover
