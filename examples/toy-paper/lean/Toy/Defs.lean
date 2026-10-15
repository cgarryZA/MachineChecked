/-!
# Definitions of the toy paper

The objects the statements of `examples/toy-paper/paper/toy.tex` are written in.
-/

namespace Toy

/-- `n` is even: it is twice a natural number (Definition 1.1). -/
def IsEven (n : Nat) : Prop := ∃ k, n = 2 * k

/-- The triangular number `0 + 1 + ⋯ + n`. -/
def triangle : Nat → Nat
  | 0 => 0
  | n + 1 => triangle n + (n + 1)

end Toy
