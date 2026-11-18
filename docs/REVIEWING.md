# Reviewing paper-to-Lean correspondence

A correspondence review records whether a linked Lean statement says what the paper says. MachineChecked's **Review** view takes one unit at a time through three stages (read the paper, compare the Lean, read the author's review) and saves each judgement as a report for the maintainer.

The queue supports two settings: ordinary projects with linked statements, and projects with locked paper specifications, dependency-level definition reviews and an acceptance policy. It uses the same reader in both. In both, the steps of printed proofs have units of their own (see [Proof steps](#proof-steps)).

## One claim at a time

The queue prefers smaller review units and takes shared definitions into account. Choose a paper or section to avoid jumping between unrelated mathematics. You can skip a unit, undo the last decision and return to skipped units. **Review it**, in a claim's ⋯ menu, starts with that claim and records that its Lean was already shown.

Each review has three stages:

**1. Read the paper.** Before the Lean statement is revealed, write an independent interpretation of the setting, hypotheses, quantifiers, conclusion and any ambiguity. The app records a snapshot when you move on.

**2. Compare with Lean.** The page shows the comparison the reader shows: the paper's passage beside the unit's Lean in rows, each row's exact Lean beside it when there is room, the complete exact statement, and its definitions; a definition, a property of an object or another reference opens below its row with the passage and the statement still on the page. Inspect the elaborated Lean proposition, relevant definitions, quantifier order and whether its hypotheses can be met. This step is given the paper and the Lean as Lean gives them, and nothing a person recorded about the claim: no symbol link, alignment or pairing of rows, correspondence note, review (of the statement or of its definitions), finding, the route a proof step's author names, or the paper definition a declaration is linked to. They are left out of what the page loads and draws, not hidden on it, and after the verdict the page shows them. The outcome the author gives a locked statement is left out the same way: the theorems named to prove, refute or witness it, the author's name for its clause, the kind and reason of a correction, and the state the assessment gives the clause. A clause is named by its place among its claim's clauses (*clause 2 of T:prop:pred*); a correction or special case of a printed clause says so, naming that clause by its place. So *Refutation not valid* and the witness comparison are offered for every locked statement. A short checklist names what to compare (the setting, each hypothesis, quantifiers and their order, the definitions relied on, the conclusion, constants, and any result or axiom taken as an assumption; for a definition, the object, its parameters and its conventions at edge cases); marking each item *matches*, *differs* or *unsure* is optional and is kept in the report. Record how it compares with the paper. The review protocol has eight precise verdicts, grouped in the interface under *Matches*, *Problem* and *Cannot determine*. With the verdict you may record the coverage and its basis ([below](#coverage-with-the-verdict)).

**3. Read the author's review.** Only after recording your verdict does the queue show the existing author review, and the comparison what people recorded about the claim (its symbol links, published alignments, each finding at the rows it explains, and the `Correspondence:` field of a review of the proposition). For a locked statement it also shows the author's account of each clause it states: the clause's place and name, its state, the printed clause a correction corrects with the kind and reason given, and the theorems named to prove, refute or witness it (*refutation: Toy.Acceptance.prop_pred*). When a clause refutes the proposition you just judged, it says what that means for the claim, in one line: *This proposition is refuted by Toy.Acceptance.prop_pred: Lean checks that it proves the negation, so no proof of the proposition can follow* (or that Lean does not check the refutation). The exported report records it as `refuted_by`, and its text block as a `Refuted:` line. Record disagreements alongside your initial interpretation. If the author's account changes your judgement, say so in the same step: tick **My judgement changed after reading the author's review** (`submit --judgement-changed why.md`), give why, and, if you would now give another verdict, that verdict with its detail. Your blind verdict stays in the report as it was recorded, beside the later judgement, each with its time. Promotion never promotes such a report, and a published audit does not count it ([Maintainer acceptance](#maintainer-acceptance), [Publishing reports with an audit](#publishing-reports-with-an-audit)).

The report records the steps completed in this reader. The queue offers changed evidence first
and says why each unit comes where it does; **Order** chooses the paper's order or the informed
order instead ([Review order](#review-order)).

**From the command line.** The same three steps, with the same locks, for a reviewer without a browser (a scripted or batch reviewer, say). Name yourself with `--as human:NAME` or `--as llm:MODEL` (or `MACHINECHECKED_REVIEWER`); texts are files, or `-` for standard input:

```sh
machinechecked review next                          # the next unit to review, and why
machinechecked review read UNIT                     # step 1: the paper's statement only
machinechecked review read UNIT --context           # and the paper around it, as context
machinechecked review read UNIT --full              # a definition: its uses in full too
machinechecked review lock UNIT reading.md          # locks your reading
machinechecked review read UNIT --with UNIT2        # definitions of one passage: read it once
machinechecked review lock UNIT reading.md --with UNIT2   # one reading locked for them all
machinechecked review show UNIT                     # step 2 (refused before lock): the Lean
machinechecked review show UNIT --definitions       # step 2: only the definitions it uses, compactly
machinechecked review show UNIT --definitions --fold  # and one line for each already shown to you
machinechecked review decide UNIT VERDICT comparison.md [--detail detail.md] [--coverage C ...]
machinechecked review author UNIT                   # step 3 (refused before decide)
machinechecked review submit UNIT disagreements.md  # finishes the report
machinechecked review submit UNIT disagreements.md --judgement-changed why.md \
  [--revised-verdict VERDICT --revised-detail detail.md]  # your judgement changed after step 3
machinechecked review status
machinechecked review export --out reports.json     # for the maintainer
```

The commands work in both kinds of project. With a `machinechecked.toml` they review the full
assessment's queue; in any other Lean project they review the zero-configuration queue of the
last `machinechecked view` or `machinechecked build`, one unit per linked claim
(`link:<claim key>`). Each step refuses to run before the one it follows and is timestamped; the
reports are in the form the reader exports, and `review promote` checks them the same way. Steps 1
and 2 show nothing of the outcome the author gives a locked statement (above); step 3 gives the
author's account of it. Step 2 lists, under a locked statement, each operation Lean totalises in
it (a division, an inverse, a Bochner integral, a supremum, a root), with the sub-term where it
is applied and what Lean gives it outside its domain, so that the comparison can settle whether
the hypotheses exclude that case; the list is read from the Lean alone. Whether the engine finds
the hypotheses supply the operation's conditions, and any dismissal of the warning, come at
step 3. For a
refuted proposition, step 3 also shows the author's account of the refutation's scope: the
readings its counterexample is declared to cover and not to cover, and the class lemmas for the
paper's standing assumptions, each with its theorem's statement. The
work is kept in your workspace in the project's working directory (`review-work/`; see below).
In zero configuration, export into `machinechecked-reviews/` to publish the reports with the
audit.

**Many units at once.** `lock`, `decide` and `submit` take `--manifest FILE` (or `-` for
standard input) instead of a unit and its texts: a JSON list of entries, each with `unit` and that
step's fields. `lock` takes `reading`, and optionally `with` (below); `decide` takes `verdict`, `comparison`, and optionally
`detail`, `witness`, `coverage`, `basis`, `argument`, `bridge` (`[THEOREM, TARGET]`) and
`would_decide`; `submit` takes `disagreements`, and optionally `judgement_changed`,
`revised_verdict` and `revised_detail`. A text is given inline (`"comparison": "..."`) or
as a file (`"comparison_file": "cmp.md"`, relative to the manifest's directory), never both; a
field the step does not take refuses the entry. Each entry is the same step as the single
command, with the same refusals: every unit still needs its own `read` before its lock, and its
`author` before its report.

```json
[{"unit": "link:thm:odd-add", "verdict": "faithful", "comparison_file": "odd-add.md",
  "coverage": "full", "basis": "direct"},
 {"unit": "link:thm:σ-bound", "verdict": "broader", "comparison": "...", "detail_file": "σ.md"}]
```

The command prints one line per entry (`UNIT: what was recorded`, or `UNIT: refused (KIND):
why`); a refused entry does not stop the others, and the command then exits 2. With `--json` it
prints one document, `{"schema": "machinechecked/review-manifest@1", "ok", "entries": [{"entry",
"unit", "ok", "message" | "error": {"kind", "message"}}]}`; an entry taken also holds the fields
of its step's result, below.

**Definitions printed in one passage.** When several definitions are read from exactly the same
passages (a paragraph defining the time step, the grid times and the increments, say), `review read
UNIT --with UNIT2 --with UNIT3` shows the passages once and begins a draft for each, and `review
lock UNIT reading.md --with UNIT2 --with UNIT3` (or a manifest entry with `"with": [UNIT2, UNIT3]`)
locks one reading for them all, at one time. Both refuse units that are not definitions, or whose
passages differ in any way or are not complete in the build, naming the unit; the lock checks
every unit's step (each read, none locked or reported) before it records any, and records what you
had already seen of each unit. From step 2 on each unit is on its own: `review show` names it and
the units its reading was locked with, and shows its Lean alone, and it takes its own verdict and
its own report, pinned to its own definition, which the maintainer promotes or refuses and which a
change of that definition alone reopens. Each unit's draft names the units locked with it
(`locked_with`): what step 2 of one shows of another came after both readings were locked, though
a time to the second cannot tell, so it does not count as seen before the other's reading. Each
report names them too (`reading.locked_with`, and the report's text says "locked …, with …"), and
Undo keeps them. The review page still takes one unit at a time.

**Results as data.** `lock`, `decide` and `submit` of one unit take `--json` too, and print one
document: `{"schema": "machinechecked/review-step@1", "action", "ok": true, "unit", "message",
"step", ..., "workspace": {"id", "mode"}}`. `step` is the unit's step now (`compare` after a lock,
`author` after a verdict, `submitted` after the report), and the other fields say what the step
recorded: `locked_at` and `revealed_by` (what you had already seen of the unit's Lean or author's
review) for `lock`, with `locked_with` (each other unit, with its `revealed_by`) for a reading
locked with others; `verdict`, `group`, `decided_at`, `correspondence` (the coverage and its basis,
or null) and a structure's separate verdicts (`members`) for `decide`; `verdict`, `group`,
`submitted_at`, the report's `revealed_by` and its `changed_judgement` (or null) for `submit`.
`message` is the line the command
prints without `--json`. A refused step prints the refusal below, and so does a text file that
cannot be read (`invalid`).

**One review, in the browser or the terminal.** Under `machinechecked view`, the review page
keeps your work in the same workspace and makes each step through the same checks: the drafts,
the locked readings, the verdicts, the reports and what you had seen are those `machinechecked
review` reads. Begin a unit on the page and continue it in a terminal with `--as` naming you as
the page does (`human:Ada-Lovelace` for the name *Ada Lovelace*), or the other way round: the
page shows the unit at the step the terminal left it, and a verdict recorded in the terminal is
followed on the page by the author's review. What you type on the page is saved as you type. A
static copy of the site (an audit, a bundle) keeps the page's work in the browser instead.

The page and the commands without `--workspace` or `--mode` use your first workspace
(`review-work/<reviewer>.json`). `--workspace ID` names another of yours (`workspace list` gives
the ids), and `--mode informed` or `--mode independent` your workspace of that mode, opening one
if you have none. On the page, **Workspace** chooses among yours as `--workspace` does, and this
browser keeps the choice. A workspace's mode is chosen when it is opened; `review` never changes it
(a `mode` operation of `workspace update` does, and keeps what you had seen).

**Workspace files.** **Export workspace** on the review page saves your review work as a
workspace file (`prooflens/workspace@1`, the file `machinechecked workspace export` writes), and
**Import workspace** continues one. A static copy of the site writes and reads the file itself, so
work moves between a static copy, a terminal and `machinechecked view`: `machinechecked workspace
import` brings the file into a project's working directory, where `review --workspace ID` and the
review page continue it, and a file exported there continues on a static copy of the same site.
The drafts, the reports with their pins, the findings and the record of what you had seen travel
unchanged; under `view`, an imported workspace of yours is the one the page works in.

A file of a workspace already there (or, on a static copy, the browser's own) merges into it.
Reports, records and the record of what you had seen are added. Each review draft of the file is
added when there is none of its unit, and replaces the one there when it continues it: every
step that one has taken (the locked reading, the verdict, the author's review shown) is the same
in the file's, which has taken more. A draft is not applied, and the import says which and why,
when it is older than the one there, when a report there was made from it, or when it differs
only in what was typed at the same step; there the page asks first, and `workspace import
--replace-drafts` takes the file's. A draft whose reading was locked differently, or whose
verdict was recorded differently, is never applied. A draft that differed is kept with both
versions under the workspace's `conflicts`, and `--dry-run` shows what an import would do. So an
import never unlocks a reading or changes a recorded verdict, and a report lists what was
recorded as seen before its reading was locked, an import included. A file of another format or
a later version is refused with the reason, and so, on a static copy, are an informed
investigation (its reviews are independent) and, while the browser holds review work, another
workspace or another reviewer's.

A step is refused, with what to do instead, when it comes before the one it follows, when the
unit is not in the queue of the last build (your draft of it is kept), when the build changed
the unit's Lean since it was shown to you (look at it again, then record the verdict), or when
another window or terminal changed the unit's draft meanwhile (nothing is saved; look at it
again and repeat the step). With `--json`, a refused step prints `{"ok": false, "error": {"kind",
"message"}}`, with `kind` one of `order`, `unknown-unit`, `stale`, `conflict`, `reported`,
`invalid`, `workspace`, `no-build`, `snapshot` and `paper-source` ([Reviewing a project you did
not build](#reviewing-a-project-you-did-not-build)), and exits 2.

**A unit whose Lean another unit shows.** Step 2 of a statement shows the Lean of the
definitions it uses, and those definitions may be units of their own. `read` and `show` of the
statement name the units it will show (or has shown) whose reading you have not locked yet: lock
those readings first if you will review them. `lock` says at once when the unit's Lean or author's
review was already shown to you (by another unit's step 2, or in an informed workspace): the
reading is still recorded, the report lists what you had seen, and `review promote` refuses it
unless the maintainer passes `--allow-revealed`.

**A unit you have reported.** `show` of a unit you have reported shows the Lean you reviewed,
with the time of the report; `lock` refuses a new reading of it (a reading made after seeing the
Lean would not be blind). A unit whose Lean changed since your report is a new review.

**Resuming after an interruption.** `review status` lists each draft at its step with the times
of the steps it has taken: the reading locked, the Lean shown, the verdict recorded, the
author's review shown. With `--json`, `progress` gives them per draft (`locked_at`, `shown`,
`shown_at`, `decided_at`, `author_shown_at`). To resume a batch:

- a draft at step `read` has no locked reading: read the unit again and lock a reading;
- a draft at step `compare` whose Lean was not shown (`shown` false): run `show`; one whose Lean
  was shown may run `show` again (it shows the same Lean, and records nothing new) before
  `decide`;
- a draft at step `author`: the verdict is recorded and cannot be changed in independent review;
  run `author`, if its time is not recorded, then `submit`;
- a unit with no draft that `status` no longer lists as open is reported: `export` writes it.

Never write a second reading of a unit whose Lean you have seen: the report would claim a blind
reading it did not have.

`read` gives every passage of the unit in full: a statement stated in several places, or a
definition used by many claims, is read in all of them. Each passage says where it is, where its
text comes from (the LaTeX source, or text extracted from the PDF) and whether its position is
exact or approximate (approximate for a PDF's statements and for proof steps located by their
line). A passage the build does not hold is marked UNAVAILABLE with its source reference, and
PDF text cut by the extraction is marked INCOMPLETE: read those in the paper. The paper's
`\lean{...}` tags are removed from the reading, since they name declarations. A claim cut from a
longer passage (one display of a remark, one sentence of a paragraph) is marked: `read` prints
first the lines the unit states, its own pinned region, then the whole passage as context (in
JSON, `states`: its `file`, `start_line`, `end_line` and `text`). The mark is the claim's pin
alone, never a clause's name.

`read UNIT --context` gives each passage with the paper around it, read from the build's copy of
the paper's source: the headings of the sections that enclose it, the paragraph just before it
and the one just after (each kept to 12 lines), the labels inside it with the numbers the
compiled paper prints for them (from the build's `.aux` file), the numbered statements it cites
(`\ref` and its kin) with their passages, for a proof step the statement whose proof it belongs
to, and the numbered statements that cite one of its labels or, for a definition, use a term it
sets in `\emph` (each with its number and lines). Those last are found by the label a statement
cites or the word it prints, so a use in other words is not listed. The context is the paper's
alone, shown before the lock like the passage, and marked as context: it is not the unit's
pinned text, and the reading records only the passages. With `--json`, each passage holds it as
`surroundings`. A review of a snapshot has no copy of the paper's source, and says so: read the
context in the paper.

`next`, `status`, `read`, `show` and `author` take `--json`: one document holding only what
that step shows, in the form of `machinechecked compare` (below). `read` holds the paper;
`show` adds the Lean (complete statements, binders, the definitions they use, Lean's checks of
a linked declaration or of a locked proposition itself). A locked statement there has its
`position`, `{claim, clause}` with the clause counted from 1 in the inventory's order, and a
correction or special case its `correction`, `{relation, of_clause}`, the printed clause by
its place; `retrieval.withheld` lists the `outcome` it leaves out. `author` adds what has been
recorded about the correspondence (the author's review, notes, earlier reports, symbol links
and statuses) and the outcome: each locked statement's `clause` and `label` (the author's
name for it), `accept`, `refute`, `witness` and `proofs`, `corrects` or `restricts` and `kind`,
and `interpretations.account`, the author's account in the lines step 3 prints.

A definition unit reads every passage of every claim that names the definition. Each passage
has a role (`role` in `--json`): `defines` for the definition's own claim, the definition the
inventory maps to it (a clause listing it in `defs`), and `uses` for a claim that only names it.
The defining passages come first, in full; the uses follow, each abbreviated to its first 300
characters in the text of step 1 (`review read UNIT --full` prints them in full, and `--json`
gives each whole). With no definition claim mapped to it, every passage reads as a use, and step
1 says so.

`show --definitions` prints only the definitions the unit's Lean uses, for reading line by
line: each once, with its docstring, its signature, and its body, equations or fields (one per
line, with their full types); the constants Lean generates for one (a constructor, projections,
equation lemmas) are named under it. It is the text of `lean.definitions` in `show --json`. Both
list every constant of the project the listed definitions use, transitively, including those
only in a binder's or a field's type: each one a statement does not use directly says which
definition uses it, so the meaning of every name in the Lean is in the protocol.

When several units use the same definitions, `show --definitions --fold` gives one line for each
definition already shown to you unchanged with another unit of your workspace ("shown to you with
link:thm:a, unchanged since"), and prints in full each one never shown to you, or changed since
(it says with which unit you saw it before). Each draft and report records the definitions its
step 2 showed, at their fingerprints (`shown_definitions`), and the fold reads them: a unit's
own earlier showing folds nothing, and a definition shown on the review page of a static copy,
which keeps no such record, is printed in full. `show --definitions` without `--fold` lists
every definition in full. Folding is a display only: it records no definition as read, reviewed
or accepted, and changes nothing in your workspace.

**Informed investigation.** Outside the three steps, `machinechecked compare CLAIM` gives a
claim's passage, its linked statements, its definitions and everything recorded about it, and
`compare --query` answers targeted questions (see [AGENTS.md](AGENTS.md)). That is an informed
inspection: someone who has used it on a claim has seen its Lean and its interpretations, and a
later review of that claim is not blind. Say so in the reading, and record it in your
workspace (an `exposure` operation, below) so that the report lists it.

An informed investigation can also report through the review steps, in an informed workspace:

```sh
machinechecked review show UNIT --mode informed      # the Lean, with no reading locked first
machinechecked review lock UNIT reading.md --mode informed    # optional: your reading
machinechecked review decide UNIT VERDICT comparison.md --mode informed
machinechecked review author UNIT --mode informed
machinechecked review submit UNIT none.md --mode informed
```

No step is locked: the workspace records that you have seen the Lean and the earlier
interpretations of every claim. A reading is kept only when you record one, with the time you
recorded it, until the verdict; the verdict and the comparison may be recorded again until the
report is submitted, which needs a verdict. The report says `"mode": "informed"` and lists the
workspace's exposure in `reading.revealed_by`, so it counts as informed, never independent.
`review promote` applies its usual rules: a report with no reading, or with steps out of order,
is refused; one with a reading recorded before its verdict, and the author's review shown after
it, is refused as not blind unless the maintainer passes `--allow-revealed`.

## Reviewing a project you did not build

A review compares the paper's passages with the Lean as the project's build recorded it, so a
reviewer needs that record and no Lean, Lake or TeX. The project's author packs it as a review
snapshot. A project that keeps its snapshot in its repository is reviewed from a clone with the
usual commands; a snapshot sent as a file is reviewed with `--snapshot`.

**The author.** After `machinechecked view` or `machinechecked build` (with `-c` for a full
assessment, as for the other review commands):

```sh
machinechecked review pack                              # the snapshot the project keeps
machinechecked review pack --out review-snapshot.zip    # a file to send; --pdf adds the PDF
```

The snapshot holds the files of the last build's site data that the review steps read: the index,
the review queue, every claim record (the paper's passages), every declaration record (the Lean
statements and definitions), the stored expansions and, when the build has them, the reverse
references the informed order reads. Its manifest, `machinechecked-snapshot.json`, names the
release, the project's commit and repository, each paper's revision and PDF checksum and the
tool's version, with the SHA-256 of every file. `pack` prints what the snapshot holds, and
`--out DIR` writes it as a directory instead.

Your workspaces stay with you: no draft, report in progress or record of what anyone had seen is
packed, and neither are the two parts of the site data that come from your workspaces (the
semantic summary's count of their findings, and the counterparts of paper numbers their version
maps give). The PDF is packed only with `--pdf`. The rest is yours to publish: the paper's
passages as the build read them (its LaTeX source, or the text extracted from its PDF), the Lean,
and your reviews, which step 3 shows. Share the snapshot where those may go. A paper whose
`publish.source_text` is false has its text left out
([below](#a-paper-whose-text-may-not-be-redistributed)).

**Keeping the snapshot in the repository.** `review pack` with no `--out` writes the snapshot
the project keeps: the directory that `[review] snapshot` names in `machinechecked.toml`
(relative to the project's root, and inside it), else `review-snapshot/` at the project's root
(the configuration's directory, or the Lean project in zero configuration). Commit it where
its contents may be published.

```toml
[review]
snapshot = "review-snapshot"
```

`machinechecked build` then writes it again after each build, with the PDF when the snapshot
holds one. While the review material is unchanged, it leaves the snapshot as it is, although each
commit gives the build a new release, evidence record and time: the committed snapshot changes
only when what a reviewer reads changes, and it names the release it was written for. `build`
writes a snapshot only for a project that keeps one, configured or as a `review-snapshot/`
directory (an empty one starts it); a `review-snapshot/` that holds other files is left as it is.

Send a snapshot file to the reviewer, or attach it to a release of the project.

**The reviewer, in a clone.** Clone the repository and take the steps with no flag:

```sh
export MACHINECHECKED_REVIEWER=human:NAME
machinechecked review next
machinechecked review read UNIT                     # step 1: the paper only
machinechecked review lock UNIT ../reading.md
machinechecked review show UNIT                     # step 2: the Lean
machinechecked review decide UNIT VERDICT ../comparison.md
machinechecked review author UNIT                   # step 3: the author's review
machinechecked review submit UNIT ../disagreements.md
machinechecked review export --out ../reports.json
```

With no build in the clone, each step reviews the snapshot the project keeps, checked as below,
and says so in one line on standard error. Reading `machinechecked.toml` needs no Lean: nothing is
built. Your work is kept in `.machinechecked-review/` at the project's root, which Git ignores
(`--review-dir DIR` names another). A project with a build of its own is reviewed from that
build, and each step says that it did not use the snapshot.

**The reviewer, with a snapshot file.** In a directory of your own, with the snapshot and your
texts:

```sh
export MACHINECHECKED_REVIEWER=human:NAME
machinechecked review next --snapshot review-snapshot.zip
machinechecked review read UNIT --snapshot review-snapshot.zip       # step 1: the paper only
machinechecked review lock UNIT reading.md --snapshot review-snapshot.zip
machinechecked review show UNIT --snapshot review-snapshot.zip       # step 2: the Lean
machinechecked review decide UNIT VERDICT comparison.md --snapshot review-snapshot.zip
machinechecked review author UNIT --snapshot review-snapshot.zip     # step 3: the author's review
machinechecked review submit UNIT disagreements.md --snapshot review-snapshot.zip
machinechecked review export --out reports.json --snapshot review-snapshot.zip
```

Every step takes `--snapshot FILE`, a zip or a directory that `review pack` wrote, `status` and
`--manifest` included, and the tool keeps the steps, the locks and the refusals as in a review of
your own build. It reads no `machinechecked.toml` and no Lean project, and runs no Lean, Lake or
TeX. Your work is kept in `.machinechecked-review/` in the current directory (`--review-dir DIR`
names another), which Git ignores; a zip is extracted there, never beside it. The snapshot stays
as its author wrote it: a working directory inside it, or one that is a build's working
directory, is refused. Send `reports.json` to the maintainer.

Before each step the tool checks the snapshot, sent or kept, against its manifest: the
manifest's format, and every file with its digest. A file missing, changed or not in the
manifest, or a manifest of another format, refuses the step with kind `snapshot`, naming the
file; nothing is rebuilt. These digests catch an incomplete or inconsistent copy. They do not
authenticate the author, since whoever holds the files can write a new manifest; the check that
counts is the maintainer's.

**The reports.** A report made against a snapshot records what it was reviewed against, beside
its usual pins: `evidence`, `{"kind": "snapshot", "manifest_sha256", "release", "evidence_id",
"project", "papers", "created_at", "tool"}`. It was reviewed against supplied evidence, and
nothing was compiled or replayed for it. `review promote` checks it by the usual rules against the
maintainer's own release ([Maintainer acceptance](#maintainer-acceptance)), and its plan says
"reviewed against supplied evidence". The times a report records give the order in which the
steps were taken in the tool.

### A paper whose text may not be redistributed

When a paper's `publish.source_text` is false, `review pack` and `build` leave the text of its
source out of the snapshot. For each text the review steps show (a printed statement, a proof
step's context in its proof, each further passage and notation definition of a pin), the
snapshot records the file within the source, the byte range and the SHA-256 of the text. Its
manifest names the source (the arXiv record, the paper's folder in the project, or the commit of
its Git repository) with the SHA-256 of each file a passage comes from. The snapshot keeps where
each passage is (its file, line and page), which the public export leaves out under the same
setting. The typeset excerpts, which only the reader shows, are left out.

Before it writes anything, `pack` scans the snapshot against the paper's source as the public
export is scanned. A snapshot that still holds a line of the source (a docstring or a review
that quotes the paper, say) is not written, and the refusal names the file and field.
`--with-paper-text` keeps the text, for a snapshot you hand over privately; the snapshot the
project keeps always follows `publish.source_text`. A paper read only from its PDF keeps its
text, and `pack` says so. Zero configuration has no `publish` setting: its snapshot keeps the
text, as its published site does.

The reviewer's first step obtains the paper's source the way `build` does, and runs no TeX:

- for an arXiv source, a download into the reviewer's working directory, kept for later steps;
- in a clone of the project, the paper's folder there;
- otherwise, or instead, the copy given with `--paper-source [PAPER=]FILE`: the source's folder,
  or the file arXiv serves (`https://arxiv.org/e-print/ID`). It is kept for later steps.

Every file and every passage is checked against its digest before anything is shown, and the
steps then show exactly what a snapshot with the text shows. A source that cannot be obtained,
or that differs from the one the author built, refuses the step with kind `paper-source` and
says how to give it; nothing is shown. The snapshot does not name a Git source's repository,
which may be private: its reviewer gives the source with `--paper-source`.

## Review order

The queue suggests what to review next, and each unit says why it comes where it does. The order
changes no status and no review, and every unit keeps its three steps and their locks. Open units
come in this order:

1. **Reopened since the last release**: a review that the comparison with the previous release
   no longer counts ([What changed since the last release](ASSURANCE.md#what-changed-since-the-last-release)).
   The reason names what changed: a claim's passage or its context, the Lean statement, or the
   definition. `review next` also prints the question a new reading answers, and the review page
   lists it under the reason.
2. **Changed since the last release**: a unit with no review to reopen whose Lean statement, a
   definition that statement uses, its definition, or a passage it is read against changed. A
   change of a proof alone moves nothing: a review of a statement does not read its proof. Nor
   does an edit of a definition that leaves its statement and value as they were (a proof
   inside it, or the tactic of a tactic default).
3. The other units, in the queue's own order: less effort first, preferring units that many
   claims depend on.

Within each group, a unit whose Lean is used in the proof of another claim's Lean comes first
(*used in the proof of Theorem 2*), directly or through other declarations, from the reverse
references the zero-configuration build extracts. Ties keep the queue's order. A definition comes
just before the statement whose review shows its Lean, so that its own reading stays blind
(*comes before the review of Theorem 2, which shows its Lean*). The report records material
revealed by earlier units in `reading.revealed_by`, including shared author-review sections; in
the reader, this covers work saved in the current browser.

A missing record leaves the order as it was, never a guess. The full assessment extracts no
reverse references, so proof use plays no part in its order; the zero-configuration view keeps no
earlier release, so changes play no part in its order; a first release has nothing to compare
with. When modules of the project are not built,
uses in them are not traced, so a unit with no use found is not known to be unused. `review
status` names each record that was not read, and why. The reasons name the paper's claims and
never a Lean declaration, since you read them before the Lean is shown.

`review next` and `review status` take `--order`:

- `priority` (the default): the order above.
- `document`: the paper's order. Any unit can also be taken directly by its id (`review read
  UNIT`), and the reader keeps its choice of paper and section.
- `informed`: the order above, with what the auditors' workspaces in the working directory
  record. It reads each record against the last build, and what Lean read of the project before
  (it runs no Lean):
  1. **Findings due for review** come first: a finding in force that the build no longer
     supports (its passage, a passage it reads as context, the Lean it cites, or a record it was
     submitted with changed), or that a [version map](#saved-investigations) the workspace keeps
     to this release reopens. The reason says what changed, and each finding has its question
     (*Does finding f-1 still hold for the changed text of Theorem 2.6?*). A passage the map
     finds moved or renumbered is the same text and reopens nothing.
  2. The reopened and changed reviews above.
  3. **Out of date**: a requirement whose governing passages changed, an alignment with the Lean
     whose Lean or passages changed, a counterexample whose reading, governing passages or
     evidence changed.
  4. **Open questions**: an open obligation of a composition, such as compatible witness
     choices; a requirement that no step of a composition establishes; a finding that is
     unresolved or covers part of the claim; a candidate counterexample, not yet shown
     admissible, or an incomplete one; an open question.
  5. **Differences** that are not resolved: a recorded difference, such as a derivative order; a
     finding that the Lean states the claim differently; an admissible counterexample to a
     reading.
  6. **Hints**: a hypothesis of an aligned Lean statement that no requirement is aligned with; a
     passage proposed as governing a requirement and not yet accepted; a counterexample of
     numeric samples only; a finding not known to be current (the build cannot check what it
     rests on).

  Within each group, the paper's main results that a workspace saves (`workspace main`) come
  first, with the units their Lean uses: *a saved main result*, *used in the proof of Theorem 1,
  a saved main result*, or *used in the statement of …*, directly or through other declarations,
  from the zero-configuration build's reverse references. The full assessment extracts none, so
  there only a main result itself is marked, and `review status --order informed` says so. Then
  come the units another claim's proof uses, as above.

  A difference that is resolved or found to be none, a hint it settles, and a finding that a new
  reading supersedes no longer raise the claim; the workspace keeps their explanation. These records and the main-result selection are prior interpretations: asking for
  this order records in your workspace that you have seen them, for the claims it drew on (the
  units it moves and the main results it names). A later reading of those claims is then not
  blind, its report says so, and `review promote` refuses it without `--allow-revealed`.

The Overview's **Review next** lists the first open units of the build's queue in the priority
order, each with its reason, and opens the review page at the unit you select. It never uses the
informed order, whatever order the review page is set to, so it records no exposure and shows no
prior interpretation.

On the review page, **Order** offers the same three: *Priority*, *Paper order* and *Informed*,
with the reasons the command line gives. The build writes the first two into the queue, so every
copy of the site has them. The informed order reads the auditors' workspaces, so `machinechecked
view` offers it. Choosing it first says what it uses; once you accept, the page records in your
workspace that you have seen prior interpretations of the claims it draws on, and only then shows
the order. A reading of those claims that you lock afterwards lists *workspace ID
(interpretation-informed review order)* in `reading.revealed_by`. Each card lists, under its
reason, the questions a new reading answers, of a review or a finding a change reopened. A
reading you locked before choosing the informed order keeps the queue's reason and questions on
its card until you record its verdict, since the protocol shows interpretations only after the
verdict. The page keeps your choice of order, as it keeps your paper and part.

## Saved investigations

A workspace keeps an investigation of the paper against the Lean so that you, or another auditor
or agent, can continue it: the evidence chosen for each claim (and the candidates rejected), the
findings, the open questions, and where you stopped. It lives in the project's working directory
(`.machinechecked/review-work/`), survives rebuilds and browser restarts, and changes no status.
Its format is in [the data model](DATA_MODEL.md#workspace-prooflensworkspace1-written-by-the-reader-and-the-command-line);
[a worked investigation](AGENTS.md#a-worked-investigation) carries one through every step on the
toy example.

**In the reader.** Under `machinechecked view`, a claim page has an **Investigation** section:
start one under your name, record a finding (its coverage and note, citing the linked
declarations), ask a question, submit a draft finding. A claim page shows the Lean, so a
workspace started there is an *informed investigation*: it records that you saw the Lean and
earlier interpretations, and it has no blind reading. Independent review uses the review page or
`machinechecked review`, with the locks above. A piece of saved evidence opens beside the claim
from the section's **Evidence** list; the comparison's **Rows** can pair its rows with the
alignments of your investigation, and each finding of it, draft or submitted, is shown at the rows
its requirement is aligned with; and its pins are kept in the workspace's resume state
(`pinned`), each with the build it was made on, so resuming the investigation in another browser
opens them again on that build.

**From the command line.** The same records, with the same checks:

```sh
machinechecked workspace open --mode informed --as human:NAME   # start or resume
machinechecked workspace show [--claim "Lemma 2.3"] [--json]    # evidence, findings, questions
machinechecked workspace update ops.json [--dry-run]            # apply operations (- for stdin)
machinechecked workspace main "Theorem 1" [NAME...] [--clear]   # the paper's main results
machinechecked workspace export --out work.json                 # hand it on
machinechecked workspace import work.json [--dry-run]           # continue it elsewhere
```

An update file lists operations, applied together or not at all; claims may be named by id, key
or number:

```json
{"op_id": "2026-10-19-lemma-2.3", "ops": [
  {"op": "put", "record": {"id": "e-bound", "kind": "evidence", "claim": "Lemma 2.3",
   "ref": {"decl": "Example.inverse_bound"}, "role": "supports"}},
  {"op": "put", "record": {"id": "f-bound", "kind": "finding", "claim": "Lemma 2.3",
   "clause": "the bound", "coverage": "changed", "evidence": ["e-bound"],
   "note": "The bound needs one more derivative of the input."}},
  {"op": "resume", "state": {"claim": "Lemma 2.3"}}]}
```

To edit a record, `put` it again with `base_rev`, the revision `show --json` gave it. If someone
changed it meanwhile, nothing is written and both versions are returned (and kept under
`conflicts`); edits of different records are all kept. Repeating a request with the same `op_id`
changes nothing. A finding is a draft until `{"op": "submit", "id", "base_rev"}`; a submitted
finding is never edited, but `{"op": "supersede", "id", "base_rev", "reason", "record"}` records a
later one with its reason, and both remain.

**A definition's reading.** When the paper leaves a definition open (its "bounded" may mean
uniformly or eventually bounded), record the reading you choose once, on the definition's claim,
as a requirement of the form `reading choice`: the readings (each an `id` and its `text`), the one
`chosen` and the `reason`, and optionally the Lean declaration that states two of the readings
agree (`equivalence`: `theorem` and the two `readings`), which need not exist yet:

```json
{"op": "put", "record": {"kind": "requirement", "claim": "Definition 2.1", "local_id": "bounded",
  "form": "reading choice", "text": "what bounded means",
  "readings": [{"id": "uniform", "text": "bounded uniformly in time"},
               {"id": "eventual", "text": "bounded for all large times"}],
  "chosen": "uniform", "reason": "Lemma 3.2 uses the bound at every time.",
  "equivalence": {"theorem": "Example.uniform_iff_eventual", "readings": ["uniform", "eventual"]}}}
```

A claim depends on the choice only where one of its requirements or findings cites it:
`"reading_choices": [{"claim": "Definition 2.1", "choice": "bounded"}]`. `workspace show`, its
JSON (`reading_choices`, and `cites` on each citing requirement and finding) and the reader's
Investigation section show the choice on the definition and on each claim that depends on it,
with the link. A finding rests on each choice it cites and on those its requirements cite: when the
choice changes (its readings or the one chosen; its reason alone changes nothing), a submitted
finding is due for review, and it is never rewritten.

The equivalence is shown with its declaration's exact statement, and reads *pending NAME* until
the declaration is in the build, a theorem, proved, with only the allowed axioms, then
*discharged by NAME*. `check` asks Lean (`workspace show` and the reader use what Lean last
answered), and lists each choice with its equivalence and the claims that depend on it (in
`--json`, `reading_choices`). A discharged equivalence moves no verdict from one reading to the
other: what it justifies is what its statement proves.

The choice is a prior interpretation. The read and compare steps of independent review never
show it; `review author` shows the choices the working directory's workspaces record on the
unit's claims, or that the unit's claims cite, with the counterexamples recorded on the
requirements that cite them (`interpretations.reading_choices` in `--json`).

**Main results.** `workspace main NAME...` saves which claims (each standing for its linked Lean)
and declarations are the paper's main results (in an update file: `{"op": "main-results", "main":
[NAME, ...]}`); without names it shows them, or, when none are saved, the suggestion: the
declarations linked to the paper's theorems. Each name is checked against the build when saved.
`compare --query impact NAME` then traces NAME from them and says whose selection it used, when it
was saved and against which project commit; `--main` names others for one query, and
`--workspace ID` chooses between several workspaces' selections. A later build that no longer has
a claim or a declaration of the selection lists it under `problems`, in `workspace show` and in
the impact answer. A replaced selection is kept in the workspace's provenance. The informed
review order puts the main results, and the units their Lean uses, ahead of the rest ([Review
order](#review-order)). The selection changes no status.

The reader's Overview has a **Main results** panel. Under `machinechecked view` it shows a
workspace's saved selection (who saved it, when, the release and project commit it was checked
against, and each entry's problem) or, when it saves none, the suggestion; you add a claim or a
declaration by name, remove one, clear them or save the suggestion, each through the same
`main-results` operation, and a name the engine refuses is shown with its reason as the engine
gives it. An edit saves only over the selection shown: if it changed elsewhere meanwhile, the
panel shows the new one and saves nothing. A published audit shows each workspace's selection
read-only, with what its data cannot name counted.

**What a difference affects at a use.** A difference between a lemma and its Lean can matter at
one use and not at another: a fifth derivative where the paper prints four is harmless to a
construction that needs only some finite number of derivatives, and not to a consumer that uses
the four-derivative bound itself. Record it at the use, as a finding of the claim whose Lean makes
the application, with an `impact`:

```json
{"op": "put", "record": {"kind": "finding", "claim": "Theorem 1", "requirement": "r2",
 "impact": {"difference": "f-diff", "use": "e-use", "outcome": "sufficient for this use",
            "why": "the construction needs some finite number of derivatives; n + 5 is finite"}}}
```

`difference` is the finding that records the difference, `use` an evidence record citing the
application (`{"app": {"callee": NAME, "id": APP_ID}}`, as `compare --query uses` or `impact`
gives it), `requirement` what the consumer needs there, and `outcome` one of *sufficient for this
use*, *not sufficient*, *a separate scope question* or *unresolved*, with your explanation. The
difference stays recorded as it is; the impact explains its consequence at that one application
and says nothing of another. It reads as changed when the application changes (a change to the
caller's proof alone does it, while the comparison of statements stays current), when the
difference is superseded or changes, or when the requirement changes. `compare --query impact
NAME` lists the impacts recorded at NAME's applications and the applications with none; the reader
shows each beside its application under **Used by** and with the findings of its claim. An impact
is your reading, attributed to you, and changes no status.

**Facts inside a proof.** An exported theorem can prove more than it states. Under `view`, a linked
theorem has **Facts inside the proof**: *Read the proof* asks Lean for the propositions its proof
establishes along the way, each with the hypotheses it needs and the case of the proof it lies in,
and each theorem the proof applies with the local that supplies each of its hypotheses (`compare
--query proof-facts NAME` gives the same in a terminal, with the reference that cites each fact,
as `compare --query uses` gives one for each application). Lean reads the facts a page at a time;
*Read more* adds the next page, and each fact keeps its number on every page. In a terminal,
`--after` reads the next page and `--in AT` the facts inside one application, by its position
`at`. *Cite in the investigation* saves a fact
as evidence; it keeps its basis, established inside that proof under that context, so a finding
resting on it records the coverage as your composition, not as direct coverage. A `have` the
source states but the compiled proof does not keep is shown as source text only.

**Compositions.** A claim is often covered by several results together: one produces an object,
another gives a property of it, a third transports it to the paper's form. Record the argument
as a `composition`: its steps in order, the evidence each one rests on (a declaration, an
application of one from `compare --query uses`, or a fact inside a proof), the substitutions,
which objects of different steps are the same, and what remains open:

```json
{"ops": [
  {"op": "put", "record": {"id": "e-exists", "kind": "evidence", "claim": "Theorem 1",
   "ref": {"decl": "Comp.exists_pos_even"}, "role": "supports"}},
  {"op": "put", "record": {"id": "e-sum", "kind": "evidence", "claim": "Theorem 1",
   "ref": {"app": {"callee": "Comp.even_add", "id": "app:Comp.pos_double_even:0"}},
   "role": "supports"}},
  {"op": "put", "record": {"id": "c1", "kind": "composition", "claim": "Theorem 1",
   "coverage": "full", "steps": [
     {"id": "s1", "establishes": "a positive even n", "uses": ["e-exists"]},
     {"id": "s2", "establishes": "n + n is even", "uses": ["e-sum"], "after": ["s1"],
      "requirements": ["r1"], "substitutions": [{"variable": "a", "value": "n"}]}],
   "identifications": [{"left": {"step": "s1", "object": "n"},
                        "right": {"step": "s2", "object": "a"}, "how": "retained witness"}]}},
  {"op": "put", "record": {"id": "f1", "kind": "finding", "claim": "Theorem 1",
   "coverage": "full", "basis": "reviewed_composition", "composition": "c1",
   "note": "The sum rule is applied to the witness the existence theorem produces."}}]}
```

Full coverage is recorded only when every requirement of the claim is established by a step and
no obligation is open; two separate existence results leave a `compatible witnesses` obligation
open until a step or evidence discharges it. The reader shows **Every clause, by an argument combining
Lean results**, the steps, and the next step: state the combination as one Lean result. When you
have done that, attach it as the composition's `bridge`, `{"theorem": NAME, "target": SPEC}`, with
`SPEC` a proposition stated as a definition that you have read against the paper. Lean checks it
when it is saved, and refuses a theorem whose type is not exactly the target. The composition then
reads **Every clause, through a checked bridge** while the check holds; a change to the target, a
definition it uses or the claim's passage puts it out of date, and it reads as your composition
again. `workspace show` and `compare --query composition CLAIM` print the argument; no status
changes either way. A finding with basis `checked_bridge` reads so while it rests on such a
composition and the check holds; any other reads as your composition, saying what it was recorded
as and why, in `workspace show`, the reader and an export.

**Connections between objects.** When one result's object is another's (the profile a
preparation returns and the correction consumes, a function equal to another on the horizon, the
class of a function), record how, exactly, as a `connection` evidence reference. Its ends are
objects of Lean results: a variable of a statement (`{"decl": D, "var": "x"}`, by name or
number), a sub-term (`{"decl": D, "at": ID}`), a declaration (`{"decl": D}`), an application's
argument (`{"app": {...}, "param": "W"}`) or a local of a fact inside a proof (`{"fact": {...},
"local": "x"}`). Its relation is one of `definitional` (with the definitions that `unfolds`),
`projection` (with its `field`), `equal`, `equal on a domain` (with its `domain`), `eventually
equal` (`along` a filter), `equal as classes` (`modulo` an equivalence, its measure named),
`restriction` (to a `domain`), `coercion`, `transformation` (with the property it `preserves`)
or `shared witness`; `conditions` say when it holds and `support` names the theorems,
applications or facts that state it:

```json
{"op": "put", "record": {"id": "e-uv", "kind": "evidence", "claim": "Theorem 1",
 "role": "supports", "ref": {"connection": {
   "from": {"decl": "Syn.u"}, "to": {"decl": "Syn.v"}, "relation": "equal on a domain",
   "domain": "[0, T]", "conditions": ["T > 0"], "support": [{"decl": "Syn.u_eq_v_on"}]}}}}
```

A type, a definition or a declaration both ends' statements use is refused as support: sharing
them relates nothing. Two witnesses of separate existence results are separate choices: a
`shared witness` between them needs a result that relates them, other than the existence results
themselves; calling both witnesses `x` changes nothing. A single result `∃ x, P x ∧ Q x` gives
one witness, and a connection at its one binder needs nothing further. A composition's
identification cites connections as its `evidence`, and its relation must fit theirs. Identifying
two objects as the same through an equality that holds only on a domain (or along a filter, or
between classes) leaves the composition a `local to global` (or `equality transport`) obligation,
open until a step or other evidence extends it; identify them as a `restriction` where the
equality holds, and nothing is left open. Each connection is pinned to its ends and its support:
when one of them changes, or the build numbers an end's binder or sub-term otherwise, that
connection reads as changed since, and the others stay current. `compare --query connections
CLAIM` lists them, and the informed comparison (`compare CLAIM --workspace ID`) carries them; the
read and compare stages of an independent review do not. An export publishes the connections a
submitted finding or its composition cites; their ends' Lean text, scope and conditions only with
the Lean. A connection changes no status.

In the reader, each connection is beside the row of each object it joins: the row where the
statement binds the variable or holds the sub-term, or the declaration as a whole for a
declaration, an application's argument or a fact's local. It reads with its relation, scope,
conditions and support, and with its source: recorded by an auditor (a published reading or your
investigation), or computed from Lean's terms (the claim record's `computed_connections`), marked
apart. **Chain to another object** shows the fewest connections that join an object of the row to
another object, each step as its source gives it; connections that have not changed are used
first. A connection that changed since it was recorded is listed with the whole claim, with what
changed, and never placed at a row, since the object it names may now be another. The read and
compare stages of an independent review show none.

**Requirements and the passages that govern them.** A claim's meaning can depend on sentences
outside its display: "for every ε > 0" before an estimate, "with C independent of ε" after it, a
standing assumption at the start of a section. Break the claim into requirements, each with the
passages it comes from, and align them with the Lean:

```json
{"ops": [
  {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "r1",
   "form": "there is", "binds": ["C"], "independent_of": ["ε"], "text": "a constant C, independent of ε"}},
  {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "r1.1",
   "parent": "r1", "form": "for every", "binds": ["ε"], "text": "for every ε > 0"}},
  {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "r1.1",
   "role": "quantifier domain", "region": {"file": "paper.tex", "start_line": 6}}},
  {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "r1",
   "role": "constant dependence", "region": {"file": "paper.tex", "start_line": 10}}},
  {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "r1.1",
   "role": "later use", "region": {"file": "paper.tex", "start_line": 13}}},
  {"op": "put", "record": {"kind": "alignment", "claim": "Equation (3)",
   "requirements": ["r1.1"], "lean": [{"decl": "Example.estimate", "binder": "hε"}]}}]}
```

A region is checked against the build's copy of the paper's source and keeps the exact lines
it was attached with. A later use (a choice of ε < 1 further on) is shown as a use; it never
changes the reading of the quantifier it uses. `machinechecked workspace suggest --claim C
--requirement r1.1` proposes nearby passages (add `--apply` to save them as proposals); accept
one by putting it with `"state": "accepted"`, or remove it with `"state": "removed"` and
`why_removed`, which keeps who removed it and why. An alignment may name particular passages
(`"fragments": [ids]`) rather than whole requirements: one passage can align with several parts
of the Lean, and several passages (the display, its quantifier, the dependence of its constant)
with one. Its targets may be parts of a definition a claim only defines, of a definition
expanded at its arguments, or of any equation of a definition. In the reader, the Investigation
section shows the requirements with their passages and alignments, and offers **Add a
requirement**, **Suggest nearby context**, **Accept**, **Remove** and **Align with the Lean**:
tick the requirements (and, if you like, only some of their passages), add the expression you
selected in the Lean or a whole declaration, and save; an alignment can be removed there too. When a governing passage changes, its
requirement goes stale even if the display itself did not change; in a full assessment,
`machinechecked changes --workspace ID` lists the stale requirements, passages and alignments
with the other records. `machinechecked compare CLAIM
--workspace ID` adds the requirements to the informed packet; the read and compare stages of an
independent review withhold them. A requirement and its alignments are your reading: they
change no status.

**Estimates, differences and counterexamples.** Give a quantifier's variables their `domain`
(`"ε > 0"`) and a constant its allowed dependence (`independent_of`, or `depends_on` for a
constant chosen after a variable). The reading then shows each estimate as an obligation in the
order its variables are chosen: "for every ε > 0, … with C independent of ε" reads "there is C;
for every ε > 0: …". A difference from the Lean is a finding on the affected requirement:

```json
{"op": "put", "record": {"kind": "finding", "claim": "Equation (3)", "requirement": "r1.1.1",
 "difference": {"feature": "derivative order", "paper": "m + 4", "lean": "n + 5",
                "outcome": "difference"}, "note": "one more derivative"}}
```

`feature` is one of `domain`, `quantifier order`, `constant dependence`, `derivative order`,
`norm`, `power`, `weight`, `index offset`, `additional assumption`, `lost case`, `stronger
conclusion`, `representation`, `other`; `outcome` is `open`, `difference`, `resolved` (with a
`resolution`: `common extension`, `checked bridge`, `argument`, `inherited assumption` or
`renaming`, and its `text`) or `no difference` (with `why`). A resolution may name the
difference's `conditions` it resolves (`resolution.conditions`); the others stay open, and the
difference reads as resolved in part. A checked bridge names its `theorem` and the `target`
proposition its type states exactly (and, when the difference has conditions, the ones it
resolves). Lean checks it when you record it, as a certificate is checked: a bridge Lean does
not check is refused. The record keeps the checked type, the target's fingerprint and the claim's
passage. It reads as resolving the difference only while Lean checks it now; once the target or
the passage changes, or without the Lean project, it reads "recorded as resolved by a checked
bridge; Lean does not check it now", with why, in `show`, the reader and a published audit. A
domain, representation or additional-assumption difference names the `transport` you inspected
first (a common extension, a bridge, the full theorem), so that a change of representation is not
recorded as a defect. The reading lists the Lean hypotheses no requirement is aligned with as
hints to inspect; a hypothesis aligned with a requirement that a standing assumption governs is
shown as inherited from it.

**Computed hints of quantity.** An alignment may name the paper's `expression`, exactly as the
source writes it in a passage that governs the alignment (a passage it names, or an accepted
passage of its requirements); the alignment goes out of date when no such passage prints it any
more. With a Lean target that is an expression (the conclusion, a hypothesis or a sub-term,
inside a definition expanded at its arguments too), the reading compares the two:

```json
{"op": "put", "record": {"kind": "alignment", "claim": "Theorem 17", "requirements": ["m.h"],
 "expression": "m + 4", "lean": [{"decl": "Example.jet_lower", "binder": "h"}]}}
```

Both are put in one normal form, a polynomial with rational coefficients (a quotient by a monomial
is a negative power; an absolute value or a norm is a variable of its own), and a difference is a
hint: an `offset` (feature `index offset`: `m + 4` against `JetBound f S (n + 5) C`, naming the
definition, the argument the expression stands in and its expansion), a `coefficient` (`weight`:
`2(a + b)` against `a + b`), a `power` or other `terms`. The paper's variables are matched with
the Lean's only through an alignment of a requirement's variable (`binds`) with a Lean variable
(`var`) and through symbol links, so a rename gives no hint, and neither does an equal form
(`2(a + b)` against `2a + 2b`); a variable matched with none gives `not compared`, never a
difference. A bounded TeX reader reads the paper's side (`+`, `-`, `\cdot`, `/`, juxtaposition,
`\frac`, `^`, numerals, identifiers with sub- or superscripts, brackets of any size, `|·|` and
`\|·\|`). Anything else, and a Lean operation that is not this arithmetic (a subtraction in ℕ,
cut off at 0, or a division in ℕ or ℤ), is `not compared`, with the reason and both exact texts.
A hint is a pointer to inspect: record what you conclude as a difference, and dismiss a hint by
naming it in that difference (`"hint": {"alignment": ID, "kind": KIND}`); the reading then lists
it apart, with your outcome and reason. Hints show in `workspace show`, in `compare CLAIM
--workspace ID` at the informed stage, and in `check --json`, attributed to the workspace and
auditor whose alignment gives them. They change no status or review record, the semantic summary
does not count them, a published audit does not carry them, and the stages of an independent
review show none.

**Computed hints of quantifier order.** Once your requirements' variables are aligned with Lean
variables (`binds` with a `var` target, or a symbol link), the reading compares the order in
which each is chosen. The paper's order is your reading's, as the estimate shows it: a "there is"
may depend on what is chosen before it, unless it is stated independent of it. The Lean's is the
scope in its statement: a "there is" may depend on every variable bound around it, whatever its
type mentions. A `quantifier order` hint points out `∃ C, ∀ n` against `∀ n, ∃ C` in either
direction, and a domain chosen once before every stage against one chosen per stage (feature
`constant dependence` when you stated the independence, else `quantifier order`); a
`quantifier` hint points out a variable one side produces and the other takes as given. A
variable the Lean binds inside a hypothesis, a negation or an alternative, and a variable of
such a pair that no alignment matches, give `not compared`. Agreeing orders give none. Each hint
is shown beside the row of the witness's alignment, and is dismissed as the others are
(`"hint": {"alignment": ID, "kind": "quantifier order"}`).

In the reader, **Align with the Lean** offers the mathematics of the passages that govern the
alignment (the inside of each `$…$` or display, and each side of a relation in it) to pick as
the **Paper expression**, which you can then trim. When the comparison's rows follow your
investigation, each hint is beside the row of its Lean target, marked **Computed hint**, a
pointer to inspect and not a finding, with the paper's and the Lean's expressions as written and
their normal forms. **Dismiss**, in the Investigation, asks for your reason and records it as a
draft finding: a difference on the alignment's requirement with outcome `no difference` that
names the hint. The hint is then listed under **Dismissed hints**, with who dismissed it and why,
both in the Investigation and beside its row. Review's Compare stage pairs no rows with an
investigation and shows no hint.

A counterexample is a record of its own against one reading of a requirement:

```json
{"op": "put", "record": {"kind": "counterexample", "claim": "Equation (3)",
 "requirement": "r1.1.1", "specialisation": {"assign": {"ε": "C + 1"}, "zero": ["f"]},
 "reduced": "1 ≤ C/ε", "violation": "C/(C + 1) < 1 for every C ≥ 0",
 "admissibility": [{"obligation": "f = 0 is admissible", "state": "verified",
                    "method": "checked against Definition 2"}], "evidence": ["e-cert"]}}
```

A value may be symbolic: `ε = C + 1` gives a family over the constant, so it can show that no
choice of C works; a value fixed for a constant, or `samples` from a numeric sweep, show only the
values tried. The reading says which: an admissible counterexample (a family, or an instance
when the reading chooses no constant, with every admissibility obligation verified), a
candidate (an obligation still open), not admissible, incomplete (a variable without a value,
or a value using a variable chosen after it) or numeric samples only. `reading` lists the
corrections it is read with; each correction gives a reading of its own, beside the printed one,
with its own evidence. A Lean certificate is evidence with `"ref": {"certificate": {"theorem",
"target", "certifies"}}`: Lean checks that the theorem's type is exactly the target (`proves`) or
its negation (`refutes`), a proposition stated as a definition, with no `sorry` and the standard
axioms, and the record keeps the checked type, the target's statement and fingerprint, the source
file's hash, the Lean version and the Lake manifest's hash. It certifies that proposition only,
not the reading it is attached to. A counterexample is pinned to its reading and to the evidence
it cites: changing a quantifier, a domain, a constant's dependence or a passage that governs
them, or the certificate, makes it `stale`, and so the finding that cites it
(`"counterexamples": [ID]`). A refuted printed step is a finding on the step, with `"verdict":
"false as printed"`; its enclosing result keeps its own evidence and status.

When a declaration that evidence cites changes (its statement, a definition's equations, or a
definition its statement uses), `show` marks that evidence `stale`; a quoted passage of the paper
is stale once the claim's passage changes. Evidence also records each definition its statement
expands at its arguments, with that definition's fingerprint: when the definition changes, the
change names the expansion as you read it and as the build prints it now (`compare --query
expansion KEY` shows each). A finding is checked through what it rests on: the
claim's passage; the requirement it names, with those it sits inside, the passages that govern
them and their alignments; the evidence it cites, and that its composition and counterexamples
cite; its composition; and, for a checked bridge (its basis, or its difference's resolution), the
bridge. A submitted finding records these parts with the version of each when you submit it
(`dependencies`, with the kinds of evidence it uses: statement comparison, object
correspondence, composition, proof route, checked bridge);
`show --json` gives them, a draft's as its records give them now. A finding is `stale` when one
of its parts changed, and only then: an edit to a theorem's proof leaves a statement comparison
of that theorem current and reopens a finding that cites a fact or an application inside that
proof, and a finding on the whole claim is reopened by a changed passage of context only through
its own evidence or composition. It is `unchecked`, never
current, when a part cannot be identified or checked: evidence recorded without the definitions
its statement uses, a source line, a finding's own bridge, Lean that has not looked, a
declaration the build shows no version of. `show` and the reader say why and what would let a
build check it (for example that its module is not built, or that the build ran no Lean). Re-pin a
record with `"repin": true` once you have checked it again: a draft that cites it follows it,
while a submitted finding keeps the versions it was submitted with and reads `stale`, naming the
record, until you supersede it. In a full assessment, `machinechecked changes --workspace ID`
lists them beside the review markers the new release reopened, each with what changed
([What changed since the last release](ASSURANCE.md#what-changed-since-the-last-release)).

When the paper itself is revised, `machinechecked changes --map --workspace ID` judges each
finding through the version map, which follows every passage by its text. A passage that only
moved or was renumbered leaves a statement comparison current. A changed or removed passage
reopens exactly the findings that read it, and so does a change of what a passage is read with:
the definition of a macro it uses, the prose opening its section, a claim it refers to, or a
passage you attached to a requirement. A definition claim that the claim's Lean relies on
reopens only a finding that cites a declaration whose statement uses that definition. Each
reopened finding names the change (with the diff), the part it rests on and a question to
answer; a claim the map leaves ambiguous reads `unchecked` until the maintainer resolves it with
`--match`. The Lean side is checked against the later release's site and listed apart. With
`--save` the workspace keeps the map: the reader's Details page then lists the findings by
claim (affected ones first, unaffected ones as still current), and `workspace show` and the
workspace's export and import carry it. A kept map also gives each reference in the Lean to a
paper number of the earlier revision its counterpart: `check`, the claim page and `compare` show
it on every build of the later revision, naming who kept the map. The informed review order
offers the reopened findings first, with their questions ([Review order](#review-order)). Nothing is moved to another claim: supersede a reopened
finding once you have read the new text. A cited fact inside a proof is `stale` once that proof
changes, even when the theorem's statement does not; it, a cited application and a certificate
read `unchecked` while Lean cannot look at them (their module is not built, a request failed). A
published audit shows them as `show` does, checked against the Lean its release was built from,
and as `unchecked` once that Lean has changed. Changing to independent mode, or importing, keeps what the workspace records you had seen,
so an informed investigation never becomes a blind review. A report made with `machinechecked
review` lists the exposure of every workspace in the working directory that you (the reviewer
`--as` names) opened, imported or recorded work in, and the units whose Lean or author's review
your review work in them showed. Exposure that an import brings after you lock a reading counts
when it was recorded before the lock. `review promote` refuses the report without
`--allow-revealed`.

**Findings due for review.** `view`, `build` and `check` count the submitted findings in force
of the workspaces in the working directory, by whether each is current for the build, due for
review or not known to be current, as the Changes view judges them (through a kept version map to
this release, otherwise against the build as `workspace show` checks them). The Overview shows
the counts under **Findings in force** and filters the claims by them; `check` prints them per
unit (`findings in force: 3 current; 1 due for review`); `check --json` gives them in the
[semantic summary](DATA_MODEL.md#semantic-summary-prooflenssemantic-summary1-derived)
(`finding_currency`). A published audit counts the findings it publishes. A draft is not
counted, and no count changes a status.

**What a published audit carries.** `machinechecked export` (and `build --site`, `check --site`)
publishes, for each claim, the records you have accepted: the requirements, the passages
accepted as governing them, the alignments with Lean, and the submitted findings (superseded ones
too, with the reason) with the evidence and counterexamples they cite and what each finding
rests on. Each keeps its author, its pins and whether it is current against the published build.
Each version map you kept is published on the claims it concerns: the claim's earlier and later
numbers, and which of your findings the revision reopened, with the question each asks. The
main results you saved are published too, with who
saved them, when, the project commit they were checked against and what the published build no
longer has of them. Proposed and removed passages, draft findings, evidence
no submitted finding cites, questions, exposure and the review protocol's drafts stay in the
workspace. The paper's `publish` settings apply: a passage's text and lines, and a version map's
places, diffs and reasons, appear only when the source text is published; the Lean's text only
when the Lean is; and your notes and reasons only when reviews are. The reader shows the
records read-only on the claim, under **Auditors' readings**, and each finding in the comparison,
at the rows it explains; they change no status.

**Placing a finding at a clause.** The comparison shows a finding at a row of the Lean only
through your own reading: give the finding its `requirement`, and align that requirement with the
Lean it concerns (a variable, a binder, a sub-term, or the conclusion). One finding may concern
several rows, and its explanation is written once. A finding on no requirement is a finding on the
whole claim, and one whose alignment names Lean that has changed since stays there until you
align the requirement again: the reader never moves a finding to an expression that merely looks
the same. A difference of a proof step's equation belongs to that step's own claim, not to the
theorem it is a step of.

```json
{"ops": [
  {"op": "put", "record": {"kind": "requirement", "claim": "Proposition 2.3", "local_id": "pos",
   "form": "assumption", "text": "n is positive"}},
  {"op": "put", "record": {"kind": "alignment", "claim": "Proposition 2.3", "requirements": ["pos"],
   "relation": "additional assumption", "lean": [{"decl": "Toy.PaperSpec.prop_pred_pos", "binder": 1}]}},
  {"op": "put", "record": {"kind": "finding", "claim": "Proposition 2.3", "requirement": "pos",
   "note": "The correction adds 0 < n; the printed claim has no such condition."}}]}
```

## What a verdict means

| Verdict | What its detail explains |
|---|---|
| Faithful | No detail: the comparison shows that all material assumptions and conclusions match |
| Faithful with representation choices | Why each representation difference is harmless |
| Broader | The instantiation that recovers the printed claim |
| Faithful to the correction | No detail: offered only for a correction or a special case of a printed clause (shown with the Lean, beside the passage, naming the printed clause by its place), it says the proposition is the printed claim with a correction, and otherwise as printed; the correction its author declares is shown after the verdict |
| Narrower | Extra hypotheses or cases excluded by Lean |
| Mismatched | What the Lean statement actually establishes |
| Vacuous | Why hypotheses fail to hold, or a witness is inadequate |
| Refutation not valid | How the proposition is stronger than the printed claim, so that a refutation of it would not refute the printed claim; offered for every locked statement, since whether one is refuted is shown after the verdict |
| Cannot determine | The open question, and what evidence would settle it |

The comparison says how the Lean compares with the paper, item by item; the detail says what the
verdict itself needs. Every verdict needs a detail except *Faithful* and *Faithful to the
correction*, and `decide` refuses one without it. The review page asks for it under the verdict,
and `machinechecked review decide --help` lists each verdict with the same question (`--detail`,
or `detail` in a manifest). For a definition, and for other cases where a verdict is easy to get
wrong, see [Difficult cases](#difficult-cases).

A saved report carries an issue draft for the maintainer: an explanatory note for representation
choices or a broader statement, a defect for a problem verdict, and an open question for *Cannot
determine*, with the reviewer's question and what would decide it. The review page and the
command line write the same drafts.

### Coverage with the verdict

With the verdict, record how far the unit's Lean states the claim and, separately, how that is
supported, in the words of the links file and of a workspace finding. The coverage agrees with
the verdict:

| Verdict | Coverage |
|---|---|
| *Matches* | `full` (every clause) or `partial` (part of the claim) |
| *Problem* | `partial`, `changed` (stated differently) or `related` (a related result, not this claim) |
| *Cannot determine* | `unresolved`: the verdict's detail is the open question |

The basis is `direct` (one Lean statement), `reviewed_composition` (your argument combining the
unit's declarations, which Lean has not checked) or `checked_bridge` (one of the unit's theorems
whose type Lean checks is exactly a target proposition you read against the paper). Both are
optional, and both are recorded before the author's review is shown:

```sh
machinechecked review decide link:thm:four broader comparison.md --detail detail.md \
  --coverage full --basis reviewed_composition --argument argument.md
machinechecked review decide link:thm:three faithful comparison.md \
  --coverage full --basis checked_bridge --bridge Cover.three_even Cover.Spec.three_even
machinechecked review decide link:thm:double "cannot determine" comparison.md \
  --detail question.md --coverage unresolved --would-decide decide.md
```

The review page offers the same choices under the verdict. A report records them as its
`correspondence`; a report without one records no coverage, and none is read from its verdict.
A review of a proof step records whether the step holds, and no coverage. Coverage and basis
change no status, and promotion writes the same marker with them or without them.

A review can start before a theorem is proved, once its formal statement exists. The queue lists the claims that still await one.

## Difficult cases

These examples cover cases where a verdict is easy to get wrong. Each says what to compare, and
uses the verdicts and coverage above: write what you find in the comparison (in an investigation,
as a finding). They add no verdict, field or required answer. The review page lists them at step
2 under **Difficult cases**, and `review decide --help` names them.

### A definition: the objects it admits

A synthetic paper defines

> **Definition 2.** A *control* is a measurable function u : [0, T] → ℝ.

and later states *Corollary 5. For every control u of linear growth, …*. Compare the objects each
side admits, not only the words:

| Lean | Objects it admits | Verdict and detail | Coverage of the definition |
|---|---|---|---|
| `{u : Set.Icc 0 T → ℝ // Measurable u}` | the paper's | *Faithful* | `full`, although a theorem that uses controls also uses a cost and a dynamics, each a unit of its own |
| `Set.Icc 0 T → ℝ` | more: functions that are not measurable | *Broader*: restricting to measurable functions gives the paper's | `partial`: say that measurability is missing |
| `{u : Set.Icc 0 T → ℝ // Measurable u ∧ ∃ C, ∀ t, abs (u t) ≤ C * (1 + t)}` | fewer: no control of faster growth | *Narrower*: the growth bound is Corollary 5's hypothesis, not part of Definition 2 | `partial`: say which controls are excluded |

The coverage is of the definition itself: a complete definition of one ingredient covers its unit
in full, whatever else the theorems using it need. Whether a difference matters to a theorem is
for that theorem's review, which reads the definitions it uses: a theorem for every control is
stronger over the broader type, one that asserts a control exists is weaker.

### A value outside the intended domain

The paper defines g(t) = f(t)/t for t in (0, T]; the Lean defines `g (t : ℝ) : ℝ := f t / t`,
which also gives g 0 = 0, since Lean's x / 0 is 0. That is *Faithful with representation
choices* only with a detail that says why the value at 0 never matters where the paper uses g,
for example that every statement using g evaluates it at t > 0. When a statement reads g at 0 (a
supremum over [0, T], continuity on [0, T]), the extra value enters it: record *Mismatched*, with
what the Lean states instead, or *Cannot determine*, with the open question.

### A supremum or infimum of an empty or unbounded set

Lean gives every set of reals a supremum and an infimum: on ℝ, `sSup ∅ = 0`, and the supremum
of a set not bounded above is 0 as well (likewise `sInf`). An indexed supremum `⨆ t ∈ s, f t` is
`⨆ t, ⨆ (_ : t ∈ s), f t`, whose inner supremum has an empty index for every t outside s, so on
ℝ it counts 0 there: `⨆ t ∈ Set.Icc 0 1, (-1 : ℝ)` is 0, not −1. A bound
`⨆ t ∈ Set.Icc 0 T, |X t| ≤ C` therefore holds for every C ≥ 0 when X is unbounded on [0, T],
where the paper's supremum is infinite. In `ℝ≥0∞` every set has its least upper bound, possibly
`⊤`, and `sInf ∅ = ⊤`. Check the value on the type the Lean uses, in the case the paper excludes:
a bound that holds there only because the supremum is 0 does not state the paper's (*Mismatched*),
unless a hypothesis of the Lean rules that case out.

### Hypotheses that must hold together

`∀ x, P x → Q x → R x` says nothing when no x meets both P and Q, even if each can be met. A
witness exhibiting one x that meets both shows that the hypotheses hold together; an example of P
and another of Q do not. The witness Lean gives is shown with the statement at step 2 (the review
page's **Witness comparison**); compare it there. The author's account of a witness (why it is not
trivial, or one argued in prose) comes with the author's review, after your verdict.

When the scope of a quantifier is ambiguous ("for every ε > 0 there is δ > 0 such that … whenever
|x − y| < δ": may δ depend on x?), say in the comparison which reading the Lean states and why you
take the paper to mean it. A counterexample under one reading is worth recording: in the comparison,
or in an investigation as a counterexample against that reading ([Estimates, differences and
counterexamples](#saved-investigations)).

### A grid in place of continuous time

The paper says that M is a martingale on [0, T]: E[M_t | F_s] = M_s for all 0 ≤ s ≤ t ≤ T. A Lean
statement on the grid t_k = kT/N, schematically `∀ j k, j ≤ k → k ≤ N → μ[M (t k) | F (t j)]
=ᵐ[μ] M (t j)`, tests the condition at grid times only. The process equal to 0 at every grid time
and to 1 between them meets it, and is not a martingale: at s between two grid times,
E[M_t | F_s] = 0 for the next grid time t, while M_s = 1. Record in the comparison which
condition between grid times is lost and where it is used: assumed only at grid times, it makes
the statement stronger; concluded only at grid times, weaker. The grid condition is the paper's
own only when the paper's object is the discrete one.

## Structures

A structure is one review unit with the constants Lean generates for it: its constructor, the
projections of the fields it declares and the projections to its parents. Their content is the
structure's fields as written, so they have no units of their own (`def:Pair` covers `Pair.mk`,
`Pair.x` and `Pair.y`; a field it inherits belongs to its parent's unit). The unit lists the
constants it covers (`lean` and `members` in the queue) and the claims that use any of them; it
is reviewed once all of them have a current review. Step 2 shows the structure's fields with
their names, types and docstrings, and `show --json` carries its authored source
(`lean_source`), as for a definition. A unit of its own for one of them, from a queue before
this, is the structure's: having reached its step 2 counts as having seen the structure's Lean.

One reading and one verdict review them all. A field can still be given a separate verdict,
recorded with the verdict (`verdict.members` in the report):

```sh
machinechecked review decide def:Pair faithful comparison.md --member Pair.y narrower y-detail.md
```

Promotion archives the one report as one record and writes a `def-review` marker for each
constant it covers, each in the form the acceptance checker reads and after its own `Review by`
line linking that record, after that constant's last marker. Each must still be one of the
structure's, at the version the report pinned. A constant whose separate verdict is not one
recorded as a review gets no marker and stays unreviewed; the report's text block (`review
reports`) lists the constants covered and each separate verdict. In `check`, the obligation to review a
definition is listed once, with the claims that need it, and a structure's with its constructor
and projections.

## Proof steps

An equation or passage inside a printed proof has its own unit in the queue (`step:<claim id>`),
whether or not any Lean is linked to it. Its question is whether the printed step holds, in its
context: step 1 shows the step and the proof up to it and the sentence after it (a step outside
any proof environment has no proof to show: `read --context` adds the paragraph before it, the
statement it belongs to and the statements it cites); step 2 shows the
Lean linked as establishing it and the formal route used instead, if any. The checklist covers
what the proof has fixed before the step, its premises, the ranges and order of its quantifiers,
its constants and its conclusion. A context longer than 20000 characters is kept in part: the
reader marks it **(cut)**, says where it was cut and how much it shows, and the rest is read in
the paper. Its verdicts are its own:

| Verdict | What its detail explains |
|---|---|
| Holds as printed | No detail |
| Holds, with a gap in the argument | The argument the printed proof leaves out |
| False as printed | The counterexample or the failing case, and what would repair the step |
| Cannot determine | What would decide it |

**A step with no Lean.** Step 1 says whether Lean is linked to the step, naming none:
`review read` says so in a line, `review read --json` gives `unit.lean_linked` (Lean linked as
establishing the step) and `unit.route_linked` (a different formal route used instead), and
`review status` lists each proof step left to review with it (`steps` in `--json`). A step with no
Lean linked is judged on the mathematics alone: read it in its context and lock the reading, then
record the verdict with the argument you checked as the comparison ("No Lean is linked. The
step follows from the bound before it by the triangle inequality, with constant 2."), and the
gap, the counterexample or the open question in its detail. Step 2 has no Lean to show, so
`review decide` may follow the lock directly. A step with only a formal route used instead is
judged the same way: the route does not state the step.

**An author's proposed verdict.** The author of a formalisation may propose a verdict on a printed
step while formalising it, with the step verdicts above and a note: a gap, its repair, a
counterexample. The step's entry records it as `proposed` (in the inventory, or in the links file
under the step's label), optionally naming a Lean theorem that proves the step or refutes it,
which is the author's and not checked by Lean here:

```json
"proposed": {"verdict": "false as printed", "note": "At k = 0 it reads n <= 0.",
             "theorem": "Toy.Acceptance.bound_range_counterexample", "by": "human:A-Author"}
```

The build writes it apart from the step's record (`data/proposals/`), so a review receives it only
after its verdict: `read` and `show` never hold it, and the review page fetches it at step 3, where
it is shown beside the author's review (`review author` prints it too). The step's own page shows
it under its review. A proposal completes no review and changes no status, neither the step's
review nor its enclosing result's: a reviewer who reaches another conclusion says so in the
response to the author's review or in a finding. A bundle, which holds every file from the start,
and a published audit carry no proposal; a review snapshot does.

A report on a step pins the hash of the step's source text, and follows the same protocol as
any other: reading locked before the Lean is shown, verdict recorded before the author's review.
In a full assessment, `review promote` turns an accepted step report into a marker, with the same
refusals (out-of-order steps, an author of the statements, a reading that was not blind, a
manuscript at another revision), and refuses a report whose step's source changed since, or
whose verdict is *cannot determine*:

```
<!-- step-review: T:eq:bound-range <source sha256> verdict=false by=a.referee -->
```

The marker is stored evidence: the assessment records the step's review from it (its last
marker, current while its hash is the step's source hash). In zero configuration, put the report
in `machinechecked-reviews/` and build again. Either way the step shows its finding beside the
equation and lists its earlier reviews; a review made on other text is kept and shown, and the
step reads **source changed**. The scope decision `proof-step` records
formal coverage only; it is never a reading of the step, so a step with no report reads
**not reviewed**. A step's finding belongs to the step: the enclosing result's status and review
are unchanged by it. An issue draft names the step and its proof (“Equation (3) in the proof of
Theorem 2.5: false as printed”).

## Review records and identity

The reviewer supplies their name or model identity, and the report records it as **self-declared**.

Under `machinechecked view`, drafts and reports are saved in your workspace in the project's
working directory, which `machinechecked review` continues; on a static copy of the site they are
saved in this browser's local storage. **Export reports** to share your work with the
maintainer. The JSON contains your interpretation, comparison, verdict, source revision, the
Lean fingerprints the verdict was recorded against, the mode of the review and reviewer
attribution. **Export workspace** saves the drafts too, to continue them elsewhere
([Workspace files](#one-claim-at-a-time)).

The maintainer reads the report and decides whether to promote its review markers.

## Publishing reports with an audit

In zero configuration, put exported report files in the project's `machinechecked-reviews/`
folder and build again. Each statement shows its reports under its links: the verdict, the
coverage recorded with it, the reviewer as recorded, the comparison and the locked reading. A
report pins the text of the statement it read; it is marked when the paper now prints another
text, when it pins none, or when the claim now links other declarations or their statements
changed since it was recorded. A report's checked bridge reads as one while the report is
current, the claim's links record the same bridge, Lean checks it and its target is the version
the reviewer was shown; otherwise it reads as the reviewer's composition, saying what it was
recorded as and why. Reports are shown as their reviewers wrote them and change no status;
`check --json` lists them per claim, with their coverage.

A report whose reviewer changed their judgement after the author's account is not counted: it
adds no coverage and no **Reviews by** reading, and the claim reads as it would without it. The
claim's audit details list it under **Reports not counted**, with the blind verdict and the
later judgement, each with its date, and `check --json` lists it under `reviews_not_counted`.

The Overview and the audit's [semantic summary](DATA_MODEL.md#semantic-summary-prooflenssemantic-summary1-derived)
count each reviewer's latest report of each statement as a set of readings of its own (**Reviews
by** the reviewer): its coverage, its basis, and whether it is current. A report that records no
coverage counts as **Reviewed, coverage not recorded**; one made for another text or other Lean as
**Out of date**. Two reviewers' readings are never combined. A report is counted as independent
when it records that nothing of the Lean or the author's review had been shown to its reviewer
before the reading was locked (`reading.revealed_by` is empty), and as informed otherwise.
A workspace's finding on a clause or a requirement is a reading of that part: the Overview lists
it under the claim, filters by it (**Clauses and requirements**) and links to the declaration it
concerns in the claim's comparison.

## Maintainer acceptance

In a project with formal review markers, a maintainer can evaluate saved reports with:

```sh
machinechecked review promote machinechecked-reviews-....json
```

A directory of reports may be given instead of the files: it stands for the `*.json` files directly in it, in name order.

Promotion checks that the manuscript, the passages read (their digests, pinned when the reading was locked) and the formal statements still match the review pins, that the review stages were recorded in the required order, and that the verdict is eligible. A *Broader* verdict on a proposition that a clause refutes is not: the printed claim can hold while a more general proposition fails, so promotion refuses it unless the clause declares its refutation outside the paper's standing assumptions (a refutation of the proposition only). An open question stays open: a report whose verdict is *Cannot determine*, or whose coverage is unresolved, records neither a review nor a defect, and promotion refuses it, as it refuses a coverage the protocol does not write. It displays the planned changes, with each report's coverage and each marker's file and place (a first marker's file is the one `[review.promote]` names, or follows the rule in [Record reviews](ASSURANCE.md#record-reviews)), and requires the maintainer's decision. Author and model-family restrictions still apply (below). A report whose reading was not blind is refused unless the maintainer passes `--allow-revealed`. A report whose reviewer changed their judgement after the author's review is always refused: the plan shows its blind verdict and the later judgement, each with its time and the reason, and no option accepts it. Ask for a fresh independent review, or record the later judgement as an informed review (`--mode informed`), which promotion accepts only with `--allow-revealed`. A report made against a review snapshot is checked by the same rules, against the maintainer's release; the plan says it was reviewed against supplied evidence and names the snapshot ([Reviewing a project you did not build](#reviewing-a-project-you-did-not-build)).

Promotion records the maintainer’s decision for the reviewed proposition or definition. The marker it writes records the digests of the paper passages read, so a later change to that text reopens the review. A passage the manuscript no longer matches reads as unread until it is pinned again, and promotion refuses a report on it (see [Evidence policy](EVIDENCE_POLICY.md#a-review-is-a-reading-of-a-text), which also says how markers written before the digests were recorded are read, and how to add the digests to them).
Acceptance also requires the claim’s proofs and all other required checks.

For each report it accepts, promotion keeps one record: the report as exported, in `reports/STEM.json` beside the review files (`STEM` is the unit, the reviewer and the time of the report). The record holds the locked reading, the comparison and verdict, the coverage, the reviewer, the time of each stage and the pins the marker is checked against. The line promotion writes before the marker, ``Review by REVIEWER: VERDICT (report `reports/STEM.json`).``, links it. A later review of the same unit, after its statement changed, is another record beside the first, and the earlier one stays. To read the reports as text, in the protocol's form, write them from the records:

```sh
machinechecked review reports              # into reports/ in the output directory (.machinechecked/)
machinechecked review reports --out DIR    # or into DIR
```

The text is generated: it can be deleted, and the command writes it again, the same.

**Model reviewers and the same-family rule.** A model reviewer declares its family relative to the statements' author with `--same-family yes|no|unknown` (the review page asks the same), and each report records the declaration (`reviewer.same_family_as_author`); `unknown` is the default. `review next` and `review status` say once which declaration is in force and whether the rule applies (`reviewer.same_family_rule` in `--json`). Promotion refuses the report of a model reviewer declared of the statements' author's family, or of unknown family, unless the maintainer passes `--accept-same-family`. A report accepted so keeps its declaration as given, and says it was accepted over the rule wherever it is shown:

- its record holds `promotion.same_family_accepted: true`, and its text says "accepted by the maintainer over the same-family rule";
- its line reads ``Review by REVIEWER: VERDICT; a model of unknown family, accepted by the maintainer over the same-family rule (report `reports/STEM.json`).`` (or "a model of the same family as the statements' author"), and the assessment reads the declaration back from it (`accepted_family`, `yes` or `unknown`, on the review record, on `rests_on` and on the clause's review evidence);
- `check` lists such reviews in a note and in `--json` (`same_family_accepted`), and the reader shows the declaration beside the review and on the clause's review evidence;
- the semantic summary counts such a claim apart from independent ones: *Current, by a model of the author's family* or *Current, by a model of unknown family*, never as the other known answer. In zero configuration, which promotes nothing, a current blind report by a model so declared is counted the same way, and the reader and `check --claim` show each report's declaration.

The statuses do not change: the rule is promotion's, and a review accepted over it counts as a review, as it did before.

Promotion in version 0.1.25 and earlier also wrote that text as `reports/STEM.md` beside the record, and its line links the `.md` file. Such a project keeps working as it is: the line is read the same either way, and the assessment, `check` and the reader do not read the `.md` files. They can be deleted safely, keeping the `.json` file of each; the record of a link `reports/STEM.md` is `reports/STEM.json`, and `machinechecked review reports --out reviews/reports` (the directory that holds them) writes the text files back where the links name them.

For details of the acceptance states, see [Evidence policy](EVIDENCE_POLICY.md). For the required configuration and review-marker format, see [Full assessment](ASSURANCE.md).
