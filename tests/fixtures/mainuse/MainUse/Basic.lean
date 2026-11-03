/-!
# A variant the main proof uses, beside the paper's lemma as printed

The paper's lemma bounds `n + n` for `n ≤ 5`. The main proof uses `bound_variant`, which writes
the sum as `2 * n`; `bound_faithful` states the lemma as printed and is proved from the variant,
and the main result does not use it. `le_ten` is used by the variant's proof.
-/

namespace MainUse

theorem le_ten (n : Nat) (h : n ≤ 5) : 2 * n ≤ 10 := by omega

/-- The variant the main proof uses. -/
theorem bound_variant (n : Nat) (h : n ≤ 5) : 2 * n ≤ 10 := le_ten n h

/-- The paper's lemma as printed, proved from the variant. -/
theorem bound_faithful (n : Nat) (h : n ≤ 5) : n + n ≤ 10 := by
  have := bound_variant n h
  omega

end MainUse
