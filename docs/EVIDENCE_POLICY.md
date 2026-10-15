# Evidence policy

What each piece of evidence means, and what it does not.

## The levels of a claim

A claim of a paper is in the inventory with a scope. Out-of-scope claims (`expository`,
`literature`, `empirical`, `proof-step`, `part-of`, `duplicate`) are listed with the reason. A
`formal` claim has clauses; a `definition` claim has Lean definitions.

A formal claim's status, from strongest to weakest:

| Status | Meaning |
|---|---|
| `formal: accepted` | every clause: a closed proposition, a theorem whose type is exactly it, only allowed axioms, and a current review of the proposition and of every project definition it depends on by a reviewer who did not write the statements |
| `formal: proved, author-reviewed` | as accepted, but some review is only by an author of the statements |
| `formal: proved, review pending` | proved, but some review is missing or stale |
| `refuted as printed[; corrected statement proved][; other clauses open]` | a theorem proves the negation of the printed claim |
| `formal: open` | a proposition is written, a proof is missing |
| `formal: unspecified` | no proposition is written yet |
| `formal: malformed` | the inventory gives corrections but no original clause |

A proof that fails a check (wrong type, disallowed axiom,
`sorry`, missing declaration) does not count, so its clause is open; the failure is a violation
and fails the paper's consistency check.

Every definition in the closure of a proposition needs its own review, including the auxiliary
declarations Lean generates (`match_1`, `_f`): they are part of the definition's meaning.

## Gates

| Gate | Passes when |
|---|---|
| Consistency check | no violation: every check ran and nothing contradicts the inventory |
| Release gate (per paper) | the source compiled and its hashes checked; consistency passes; every scope decision reviewed; every formal claim accepted and every definition claim reviewed by an independent reviewer; no printed clause refuted; every witness valid; a Comparator log shows a kernel replay of every proof of the paper |

A paper can pass the consistency check with every claim open: the check says nothing about the
paper as a whole.

## The evidence ladder

Each clause shows its rungs separately. One rung passing says nothing about another.

| Rung | Mechanical? | Passes when |
|---|---|---|
| locked statement | yes | the proposition is a definition of type `Prop` in the specification layer, over allowed axioms |
| exact statement | yes | the acceptance theorem's type is exactly the proposition (or its negation), and it has no `sorry`; checked on the build the probe ran on, which may be a restored cache |
| axioms | yes | its axioms are among the allowed (`propext`, `Classical.choice`, `Quot.sound` by default) |
| kernel replay | yes | a structured Comparator record (`comparator_log`: JSON with the full project `commit` and the exact names of the `replayed` theorems) covers this proof for this commit; without one the rung is `not run`, never `failed`; a record of another commit, or a text log, is `unverified` |
| witness | yes, for the theorem; the fit to the paper is reviewed | a proposition with hypotheses has a theorem meeting them |
| regimes | yes, for the theorems; the fit is reviewed | each regime the paper intends to cover has its witness |
| review | no | the proposition and its definitions have current reviews; `author` if only by an author |
| source | yes | the claim was located in the compiled paper and its source hash matches the inventory; `pdf-only` if there is no LaTeX |

## What evidence is not

- **`#print axioms`-clean is the trust base, not coverage.** A theorem over unconstrained
  hypotheses can be axiom-clean and say nothing about the paper.
- **A fingerprint shows structure, not meaning.** Two different fingerprints may be equivalent
  mathematically. Two equal fingerprints are the same expression up to binder names, metadata and
  proofs.
- **A review marker is a self-declared record.** Nothing in a Markdown file authenticates who
  wrote it. Its provenance is shown as `self-declared` until a stronger attestation exists.
- **A witness only shows the hypotheses can be met.** Whether it is an instance the paper intends
  (nonzero jumps, infinite activity, nontrivial law dependence) is a regime obligation and a
  review judgement.
- **A dismissed warning is a recorded opinion,** bound to the fingerprint it was made on.

## Provenance of a release

Every evidence record contains:
- the tool version and fingerprint version;
- the Lean version and commit;
- the project commit and whether the tree was dirty;
- the toolchain and lake-manifest hash, and every dependency revision;
- for each paper: the source kind, revision, mode, root, compiled and committed PDF hashes, and
  the files read during compilation;
- the hashes of the review files.

`prooflens build --reuse-lean` reuses stored probe records only when a SHA-256 over every Lean input
(the project's and every path dependency's sources, lakefiles, manifest and toolchain) and the
probe itself are unchanged. `prooflens reassess` applies new reviews and dismissals to stored
evidence, and refuses when the claim inventory changed.

Evidence records are content-addressed and never rewritten. A release name, once given, keeps its
evidence.
