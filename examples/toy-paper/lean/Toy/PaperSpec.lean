import Toy.Defs

/-!
# Statements of the toy paper

Each claim of the toy paper, as a closed proposition written from the printed statement.
-/

namespace Toy.PaperSpec

open Toy

/-- Theorem 2.1: the sum of two even numbers is even. -/
def thm_even_add : Prop := ∀ a b : Nat, IsEven a → IsEven b → IsEven (a + b)

/-- Theorem 2.2: twice the `n`-th triangular number is `n (n + 1)`. -/
def thm_triangle : Prop := ∀ n : Nat, 2 * triangle n = n * (n + 1)

/-- Proposition 2.3, as printed: every natural number exceeds its predecessor. -/
def prop_pred : Prop := ∀ n : Nat, n - 1 < n

/-- Proposition 2.3, corrected: every positive natural number exceeds its predecessor. -/
def prop_pred_pos : Prop := ∀ n : Nat, 0 < n → n - 1 < n

/-- Theorem 2.4: one constant bounds the triangular numbers by `n²` for every `n`. -/
def thm_bound : Prop := ∃ C : Nat, ∀ n : Nat, triangle n ≤ C * (n * n)

/-- Corollary 2.5: the triangular number of a multiple of four is even. -/
def cor_even_triangle : Prop := ∀ n : Nat, IsEven (triangle (4 * n))

end Toy.PaperSpec
