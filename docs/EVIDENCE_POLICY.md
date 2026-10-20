# Evidence policy

What each check establishes and how claims reach acceptance.

The [structured status contract](STATUS_CONTRACT.md) lists the machine-readable codes and
independent evidence dimensions. Labels never control acceptance or reader behaviour.

## The levels of a claim

A claim of a paper is in the inventory with a scope. Out-of-scope claims (`expository`,
`literature`, `empirical`, `proof-step`, `part-of`, `duplicate`) are listed with the reason.
A scope decision is about formal coverage: `proof-step` says the step is outside the formal proof
assessment, never that anyone read it. A proof step has its own links and its own review, shown
beside it and never taken from, or given to, its enclosing result; a step no report covers is
shown as not reviewed. Neither changes a status. A
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

A review compares a Lean declaration with the paper's text, so it counts only for the text that was
read. A marker with no review text before it records no reading and does not count (unless the
configuration allows bare markers by its reviewer, `bare_markers_by`). A review of a proposition
reads the passages of every claim whose clauses state it; a review of a definition reads the
passages of the definition claims that name it. A definition that only occurs in a closure has no
passage of its own.

- **Recorded digests.** A marker records, for each claim whose passage was shown to the
  reviewer, the digest of that passage as read (`source=CLAIM@DIGEST`, the claim's source pin
  `source_sha256`, scheme `tex-region-v1` for a claim located by line). `review promote` writes
  them from the report. A reading counts for a claim only while the digest it records for that
  claim is the claim's current pin. Otherwise the claim reads `review pending`, with a finding
  that names the claim and says that its text changed since the reading (or that the reading
  did not record its passage). The review of the declaration for another claim whose passage
  is unchanged stands. A definition's review in the closure of a statement must have read the
  current passage of every claim that names the definition.
- **Markers written before the digests were recorded.** Such a marker counts for a claim only
  while the project's Git history shows the claim's passage unchanged since the marker was
  written: the commit that wrote the marker's line, and every later version of the inventory,
  keep the claim's pin (the same digest under the same scheme, or a legacy pin rehashed as
  `tex-region-v1` at the same paper revision and in the same file). A pin that changed reopens
  the review as above. When the history cannot show it (no Git repository, a shallow clone, a
  file not committed, a claim without a pin when the marker was written), the review is reported
  as *reviewed before source pins were recorded* and does not count.
- **Migration.** `python -m prooflens.review_sources --config FILE` lists the markers without
  digests and, with `--write`, adds the digest of each claim whose passage the history shows
  unchanged. It adds nothing for any other claim: those need a new reading.

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
| kernel replay | yes | a structured Comparator record (`comparator_log`: JSON with the full project `commit` and the exact names of the `replayed` theorems, as `machinechecked replay` writes it) covers this proof for this commit, or for an ancestor of it with no Lean input changed since; without one the rung is `not run`, never `failed`; a record of another commit, of a run that did not pass, of a tree with uncommitted Lean changes, or of another Lean version or set of Lake dependencies (when it names them), or a text log, is `unverified`; a replay made without Comparator's sandbox guard still passes, and the rung says "replayed without the sandbox guard" (or "sandbox guard not recorded" for a record that does not state its conditions) |
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
- **Replay:** a structured Comparator record identifies the proofs and build replayed, and
  states whether the run was under Comparator's sandbox guard.
- **Suggestions and paper numbers:** a suggestion, a content search result or a check of the
  Lean's references to the paper's numbers names a candidate to inspect and why. It
  establishes nothing about correspondence and never makes a link: a claim with suggestions
  and no link reads `link.suggested`, unlinked and in the same class as `link.none`.

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

In zero configuration, every build reuses the Lean facts it extracted before (a module's index, a
linked declaration's record, an `inspect` answer) while the modules of the environment they came
from (the declaration's module and everything it imports, in the project and its path
dependencies), the probe, the toolchain, the lakefiles and the Lake manifest are unchanged, and
extracts again only what a change reopens. A link, a note or an edit to the paper extracts
nothing. `machinechecked build --reuse-lean` uses the stored facts alone: when they do not cover
the build it starts no Lean session, stops with exit code 2 and names the modules to index or the
declarations to check, with the reason.

Evidence records are content-addressed and never rewritten. A release name, once given, keeps its
evidence.
