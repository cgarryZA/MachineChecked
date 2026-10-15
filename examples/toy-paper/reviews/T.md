# Reviews of the statements of the toy paper

Synthetic reviews for the example. `a.referee` is a fictional independent reviewer used to show
the accepted state; `statement-author`, an AI, wrote the statements, so its reviews are not
independent.
Each marker records the hash of the proposition it reviewed; a change of the proposition makes
the review stale.

## Theorem 2.1: `Toy.PaperSpec.thm_even_add`

Manuscript: if `a` and `b` are even natural numbers, then `a + b` is even.

Proposition: for all `a b : Nat`, `IsEven a → IsEven b → IsEven (a + b)`.

Correspondence: both quantifiers, both hypotheses and the conclusion appear as printed. The
witness `thm_even_add_hypotheses` meets the hypotheses at `a = 2`, `b = 4`, which are nonzero.

Verdict: faithful.

<!-- spec-review: Toy.PaperSpec.thm_even_add pl-fp-v1:551fc041080c4c0d6511fdb7ea708af7cdc3dd106c870a6619677829587f7ce8 by=a.referee kind=human -->

## Theorem 2.2: `Toy.PaperSpec.thm_triangle`

Manuscript: for every natural number `n`, `2 T_n = n(n+1)`.

Proposition: `∀ n : Nat, 2 * triangle n = n * (n + 1)`.

Verdict: faithful.

<!-- spec-review: Toy.PaperSpec.thm_triangle ed839d34f480cba1019bea31a8dbac95 by=statement-author -->

## Proposition 2.3, as printed: `Toy.PaperSpec.prop_pred`

Manuscript: every natural number is strictly greater than its predecessor `n - 1`.

Proposition: `∀ n : Nat, n - 1 < n`, with Lean's truncated subtraction, which is the reading of
`n - 1` on the natural numbers. The proposition is false at `n = 0`, as the paper's Remark 2.4
says.

Verdict: faithful to the printed (false) claim.

<!-- spec-review: Toy.PaperSpec.prop_pred pl-fp-v1:1f792a761f744be03443162de08a0853013d66ba58adb124607d799d7b771ae3 by=statement-author -->

## Proposition 2.3, corrected: `Toy.PaperSpec.prop_pred_pos`

Proposition: `∀ n : Nat, 0 < n → n - 1 < n`, the correction stated in Remark 2.4.

Verdict: faithful to the correction.

<!-- spec-review: Toy.PaperSpec.prop_pred_pos pl-fp-v1:cd1578f08b39065fe86d850864b1b7befb7ff3d31a6ac1467335f3624671e2b8 by=statement-author -->
