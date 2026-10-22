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
declarations Lean generates (`match_1`, `_f`): they are part of the definition's meaning. A
declaration that only a witness's statement uses needs no review; it is listed while it has
none, and a project can require its review (`require_witness_def_reviews`), which can only hold
a status back.

## A review is a reading of a text

A review compares a Lean declaration with the paper's text, so it counts only for the text that was
read. A marker with no review text before it records no reading and does not count (unless the
configuration allows bare markers by its reviewer, `bare_markers_by`). A review of a proposition
reads the passages of every claim whose clauses state it; a review of a definition reads the
passages of the definition claims that name it. A definition that only occurs in a closure has no
passage of its own.

- **Recorded digests.** A marker records, for each claim whose passage was shown to the
  reviewer, the digest of that passage as read (`source=CLAIM@DIGEST`, the claim's source pin
  `source_sha256`, scheme `tex-region-v1` for a claim located by line, `tex-regions-v1` for a pin
  of several passages or of macro definitions, whose digest covers each of them). `review promote` writes
  them from the report. A reading counts for a claim only while the digest it records for that
  claim is the claim's current pin. Otherwise the claim reads `review pending`, with a finding
  that names the claim and says that its text changed since the reading (or that the reading
  did not record its passage). The review of the declaration for another claim whose passage
  is unchanged stands. When the passage uses notation macros the configuration lists
  (`notation_macros`), the digest also covers their definitions, so a changed definition
  reopens the reading too, and a reading that did not record them does not count
  ([notation macros](SOURCE_REGIONS.md#notation-macros)). A definition's review in the closure of a statement must have read the
  current passage of every claim that names the definition, in one reading: readings of the
  passages made in separate reviews do not combine, and the finding names the marker that read
  each. A definition claim's review is the last marker at the definition's current hash that
  read that claim's passage; the assessment records it (`rests_on`), and a warning
  (`def-review-other-claim`) names one whose review text names another claim that names the
  definition, and not this one.
- **The manuscript must match the pin.** A reading counts against the text the paper prints.
  When the source check finds that the manuscript no longer matches a claim's pin (its
  passage, a further passage in `source_parts`, or a pinned macro definition: a
  `source-changed` violation), the claim's passage reads as unread for every review that read
  it, whatever digest the marker records: the claim reads `review pending`, with a finding
  (`source-unpinned`) that names the passage and where it differs. Pin the passage again
  (`inventory repin`, or `rebound` at the pinned revision) and record a reading at the new pin
  to restore the review; `review promote` refuses a report on such a passage. A paper read only
  from its PDF has no source check, and its readings count against the pin.
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
- **A reading of a passage that no longer uses the declaration.** When the inventory moves a
  clause to another claim, a marker's reading of the old claim's passage is no reading of a
  passage that uses the declaration now. `inventory retire` lists such readings and, with
  `--write`, removes exactly them: it never rewrites one to the new claim and adds none, and a
  marker left with no reading records `source=none`, so that the history rule above does not
  apply to it. The claims that now use the declaration read as unread until someone reads them
  ([moving a clause](SOURCE_REGIONS.md#moving-a-clause-to-another-claim)). A marker retired whole
  (`<!-- retired spec-review: ... -->`) records no review; it keeps its review text in the file.

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
- **Changes between releases:** `machinechecked changes` reports, from two releases' evidence,
  what changed in each claim's passage and Lean and which reviews the later build no longer
  counts, with the dependency that changed. It reports each build's own statuses and changes
  none; a change can only leave evidence due for review, and a review is never carried to
  another declaration or claim.
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
declarations to check, with the reason. `machinechecked build --refresh` uses no stored fact: it
extracts again everything the build reads and stores it in place of what was kept. Reuse never
changes what is assessed: for the same sources, a build from stored facts and a refreshed one
give the same statuses. A paper's build leaves out of its index the libraries formalization.yaml
maps only to other papers, and its notes say so. A module of such a library is indexed all the
same when it could hold a linked name: its source uses one of the name's words (a component of
the name, or its start up to an underscore, in any case) or an attribute that renames
declarations (`to_additive`, `to_dual`). Every library is indexed when a linked name is one Lean
gives an instance (`inst…`) or the project defines commands. A link into another library is
then checked by Lean there, and a name two libraries hold reads ambiguous without its module, as
when every library is indexed. A dependency's command that names a declaration with words its
call does not contain is not detected ([DEVELOPMENT.md](DEVELOPMENT.md)).

Evidence records are content-addressed and never rewritten. A release name, once given, keeps its
evidence.
