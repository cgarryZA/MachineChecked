# Reviews of the definitions of the toy paper

Synthetic reviews for the example (see `T.md`).

## `Toy.IsEven`

Definition 1.1: `n` is even if `n = 2k` for some natural `k`. The definition is
`∃ k, n = 2 * k`.

<!-- def-review: Toy.IsEven pl-fp-v1:a2514da741fb42660e227ed84561ac546c4e4f8e59d16eacaaee94b6a6d2204e by=a.referee kind=human -->

## `Toy.triangle`

Definition 1.1: `T_n = 0 + 1 + ⋯ + n`. The definition is the recursion `T_0 = 0`,
`T_(n+1) = T_n + (n + 1)`.

<!-- def-review: Toy.triangle e46077ff10d20514656f6f13387c90e6 by=statement-author -->

## `Toy.triangle._f`, `Toy.triangle.match_1`

The functional and the pattern match Lean generates for the recursion of `Toy.triangle`; they are
part of its meaning, so each is reviewed with it.

<!-- def-review: Toy.triangle._f 95a8b8cdb96ee7e5bc9d3e48b1fe7104 by=statement-author -->
<!-- def-review: Toy.triangle.match_1 39be9c3f3ff3768c322be17b50fb7b55 by=statement-author -->
