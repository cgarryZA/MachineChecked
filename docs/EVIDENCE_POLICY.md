# Evidence policy

What each check establishes and how claims reach acceptance.

The [structured status contract](STATUS_CONTRACT.md) lists the machine-readable codes and
independent evidence dimensions. Labels never control acceptance or reader behaviour.

## The levels of a claim

A claim of a paper is in the inventory with a scope. Out-of-scope claims (`expository`,
`literature`, `empirical`, `proof-step`, `part-of`, `duplicate`) are listed with the reason. A
`formal` claim has clauses; a `definition` claim has Lean definitions.

A formal claim's status, from strongest to weakest:

| Status | Meaning |
|---|---|
| `formal: accepted` | every clause: a closed proposition, a theorem whose type is exactly it, only allowed axioms, and a current review of the proposition and of every project definition it depends on by a reviewer who did not write the statements |
| `formal: proved, author-reviewed` | as accepted, with author provenance for at least one required review |
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

## A review is a reading of a text

A review compares a Lean declaration with the paper's text, so it counts only for the text that
was read. A review of a proposition reads the passages of every claim whose clauses state it; a
review of a definition reads the passages of the definition claims that name it. A definition
that only occurs in a closure has no passage of its own.

- **Recorded digests.** A marker records the digests of the passages shown to the reviewer
  (`source=`, the claims' source pins `source_sha256`, scheme `tex-region-v1` for a claim
  located by line). `review promote` writes them from the report. A marker whose digests differ
  from the claims' current pins is not current: the claim reads `review pending`, with a finding
  that names the claim whose text changed since the reading. A claim added to those that state
  the proposition also reopens it.
- **Markers written before the digests were recorded.** Such a marker counts only while the
  project's Git history shows its passages unchanged since the marker was written: the commit
  that wrote the marker's line, and every later version of the inventory, keep each claim's pin
  (the same digest under the same scheme, or a legacy pin rehashed as `tex-region-v1` at the same
  paper revision and in the same file). A pin that changed reopens the review as above. When the
  history cannot show it (no Git repository, a shallow clone, a file not committed, a claim
  without a pin when the marker was written), the review is reported as *reviewed before source
  pins were recorded* and does not count.
- **Migration.** `python -m prooflens.review_sources --config FILE` lists the markers without
  digests and, with `--write`, adds the digests to those whose passages the history shows
  unchanged. It leaves every other marker as it is: those need a new reading.

## Gates

| Gate | Passes when |
|---|---|
| Consistency check | no violation: every check ran and nothing contradicts the inventory |
| Release gate (per paper) | the source compiled and its hashes checked, or, for a paper published only as a PDF, the PDF pinned by its SHA-256 (`pdf_sha256`) and matching, with every claim in scope found in it (the gate then states that the source is a PDF and claim positions are approximate); consistency passes; every scope decision reviewed; every formal claim accepted and every definition claim reviewed by an independent reviewer; no printed clause refuted; every witness valid; a Comparator log shows a kernel replay of every proof of the paper |

Consistency checks agreement between the inventory and evidence. Each claim’s status records
its proof and review results.

## The evidence ladder

Each clause reports a result for every evidence dimension.

| Rung | Mechanical? | Passes when |
|---|---|---|
| locked statement | yes | the proposition is a definition of type `Prop` in the specification layer, over allowed axioms |
| exact statement | yes | the acceptance theorem's type is exactly the proposition (or its negation), and it has no `sorry`; checked on the build the probe ran on, which may be a restored cache |
| axioms | yes | its axioms are among the allowed (`propext`, `Classical.choice`, `Quot.sound` by default) |
| kernel replay | yes | a structured Comparator record (`comparator_log`: JSON with the full project `commit` and the exact names of the `replayed` theorems, as `machinechecked replay` writes it) covers this proof for this commit, or for an ancestor of it with no Lean input changed since; without one the rung is `not run`, never `failed`; a record of another commit, of a run that did not pass, of a tree with uncommitted Lean changes, or of another Lean version or set of Lake dependencies (when it names them), or a text log, is `unverified` |
| witness | yes, for the theorem; the fit to the paper is reviewed | a proposition with hypotheses has a theorem meeting them (not needed for a clause whose refutation checks: a proof of ¬S exhibits an instance meeting S's hypotheses) |
| regimes | yes, for the theorems; the fit is reviewed | each regime the paper intends to cover has its witness |
| review | no | the proposition and its definitions have current reviews of their current Lean and paper text; `author` if only by an author |
| source | yes | the claim was located in the compiled paper and its source hash matches the inventory; `pdf-only` if there is no LaTeX |

## What each check establishes

- **Proof:** Lean establishes the formal proposition under its recorded axioms.
- **Correspondence:** reviewers compare the proposition and its definitions with the paper.
- **Review provenance:** markers record self-declared identities, the hashes reviewed and the
  digests of the paper passages read.
- **Witness:** a checked example establishes that the formal hypotheses can be met.
- **Source verification:** hashes identify the manuscript region or PDF being audited.
- **Replay:** a structured Comparator record identifies the proofs and build replayed.

## Provenance of a release

Every evidence record contains:
- the tool version and fingerprint version;
- the Lean version and commit;
- the project commit and whether the tree was dirty;
- the toolchain and lake-manifest hash, and every dependency revision;
- for each paper: the source kind, revision, mode, root, compiled and committed PDF hashes, and
  the files read during compilation;
- the hashes of the review files.

`machinechecked build --reuse-lean` reuses stored probe records only when a SHA-256 over every Lean input
(the project's and every path dependency's sources, lakefiles, manifest and toolchain) and the
probe itself are unchanged; otherwise it stops with exit code 2 and says to run `machinechecked
build` without `--reuse-lean`. `machinechecked reassess` applies new reviews and dismissals to stored
evidence, and refuses when the claim inventory changed.

Evidence records are content-addressed and never rewritten. A release name, once given, keeps its
evidence.
