# Reviewing paper-to-Lean correspondence

**A linked Lean theorem is not automatically a faithful formalisation of the paper.** MachineChecked's Review view helps a mathematician examine the correspondence one unit at a time and record a reproducible judgement.

The queue supports two settings: ordinary projects with linked statements, and projects with locked paper specifications, dependency-level definition reviews and an acceptance policy. It uses the same reader in both.

## One claim at a time

The queue prefers smaller review units and takes shared definitions into account. Choose a paper or section to avoid jumping between unrelated mathematics. You can skip a unit, undo the last decision and return to skipped units.

Each review has three stages:

**1. Read the paper.** Before the Lean statement is revealed, write an independent interpretation of the setting, hypotheses, quantifiers, conclusion and any ambiguity. The app records a snapshot when you move on.

**2. Compare with Lean.** Inspect the elaborated Lean proposition, relevant definitions, quantifier order and witnesses. A short checklist names what to compare (the setting, each hypothesis, quantifiers and their order, the definitions relied on, the conclusion, constants, and any result or axiom taken as an assumption; for a definition, the object, its parameters and its conventions at edge cases); marking each item *matches*, *differs* or *unsure* is optional and is kept in the report. Record how it compares with the paper. The review protocol has eight precise verdicts, grouped in the interface under *Matches*, *Problem* and *Cannot determine*.

**3. Read the author's review.** Only after recording your verdict does the queue show the existing author review. Record disagreements alongside your initial interpretation.

The report records the steps completed in this reader.

**Review order.** The queue puts definitions before statements that use them. It records material
revealed by earlier units in `reading.revealed_by`, including shared author-review sections.
This record covers work saved in the current browser.

**From the command line.** The same three steps, with the same locks, for a reviewer without a browser (a scripted or batch reviewer, say). Name yourself with `--as human:NAME` or `--as llm:MODEL` (or `MACHINECHECKED_REVIEWER`); texts are files, or `-` for standard input:

```sh
machinechecked review next                          # the next unit to review
machinechecked review read UNIT                     # step 1: the paper's statement only
machinechecked review lock UNIT reading.md          # locks your reading
machinechecked review show UNIT                     # step 2 (refused before lock): the Lean
machinechecked review decide UNIT VERDICT comparison.md [--detail detail.md]
machinechecked review author UNIT                   # step 3 (refused before decide)
machinechecked review submit UNIT disagreements.md  # finishes the report
machinechecked review status
machinechecked review export --out reports.json     # for the maintainer
```

Each step refuses to run before the one it follows and is timestamped; the reports are in the form the reader exports, and `review promote` checks them the same way. The work is kept in the project's working directory (`review-work/`).

## What a verdict means

| Verdict | What the reviewer must explain |
|---|---|
| Faithful | All material assumptions and conclusions match |
| Faithful with representation choices | Why each representation difference is harmless |
| Broader | The instantiation that recovers the printed claim |
| Narrower | Extra hypotheses or cases excluded by Lean |
| Mismatched | What the Lean statement actually establishes |
| Vacuous | Why hypotheses fail to hold, or a witness is inadequate |
| Refutation not valid | Why the formal refutation does not refute the printed claim |
| Cannot determine | The open question, and what evidence would settle it |

A saved report carries an issue draft for the maintainer: an explanatory note for representation
choices or a broader statement, a defect for a problem verdict, and an open question for *Cannot
determine*, with the reviewer's question. The review page and the command line write the same
drafts.

A review may be useful before a theorem is proved, provided the formal specification exists. Claims without a formal statement cannot yet undergo comparison; the queue lists them separately.

## Review records and identity

The reviewer supplies their name or model identity. On a standalone HTML bundle, identity is **self-declared**; a Git name or a typed username is not proof of authorship.

Drafts are saved in this browser’s local storage. **Export reports regularly** to keep a durable
copy and share your work. The JSON contains your interpretation, comparison, verdict, source
revision, Lean fingerprints and reviewer attribution.

The maintainer reads the report and decides whether to promote its review markers.

## Publishing reports with an audit

In zero configuration, put exported report files in the project's `machinechecked-reviews/`
folder and build again. Each statement shows its reports under its links: the verdict, the
reviewer as recorded, the comparison and the locked reading. A report is marked when the claim
now links other declarations, or their statements changed, since it was recorded. Reports are
shown as their reviewers wrote them and change no status; `check --json` lists them per claim.

## Maintainer acceptance

In a project with formal review markers, a maintainer can evaluate saved reports with:

```sh
machinechecked review promote machinechecked-reviews-....json
```

Promotion checks that the manuscript and formal statements still match the review pins, that the review stages were recorded in the required order, and that the verdict is eligible. It displays the planned changes and requires the maintainer's decision. Model-family and author restrictions still apply. A report whose reading was not blind is refused unless the maintainer passes `--allow-revealed`.

Promotion records the maintainer’s decision for the reviewed proposition or definition.
Acceptance also requires the claim’s proofs and all other required checks.

For details of the acceptance states, see [Evidence policy](EVIDENCE_POLICY.md). For the required configuration and review-marker format, see [Full assessment](ASSURANCE.md).

Reports and drafts are saved in this browser. **Export reports** downloads the reports for sharing
with the maintainer. **Review it** starts with the selected claim and records prior Lean exposure
when opened from the reader.
