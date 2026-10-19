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

Each step refuses to run before the one it follows and is timestamped; the reports are in the form the reader exports, and `review promote` checks them the same way. The work is kept in your workspace in the project's working directory (`review-work/`; see below).

## Saved investigations

A workspace keeps an investigation of the paper against the Lean so that you, or another auditor
or agent, can continue it: the evidence chosen for each claim (and the candidates rejected), the
findings, the open questions, and where you stopped. It lives in the project's working directory
(`.machinechecked/review-work/`), survives rebuilds and browser restarts, and changes no status.
Its format is in [the data model](DATA_MODEL.md#workspace-prooflensworkspace1-written-by-the-reader-and-the-command-line).

**In the reader.** Under `machinechecked view`, a claim page has an **Investigation** section:
start one under your name, record a finding (its coverage and note, citing the linked
declarations), ask a question, submit a draft finding. A claim page shows the Lean, so a
workspace started there is an *informed investigation*: it records that you saw the Lean and
earlier interpretations, and it has no blind reading. Independent review uses the review page or
`machinechecked review`, with the locks above.

**From the command line.** The same records, with the same checks:

```sh
machinechecked workspace open --mode informed --as human:NAME   # start or resume
machinechecked workspace show [--claim "Lemma 2.3"] [--json]    # evidence, findings, questions
machinechecked workspace update ops.json [--dry-run]            # apply operations (- for stdin)
machinechecked workspace export --out work.json                 # hand it on
machinechecked workspace import work.json                       # continue it elsewhere
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

When a declaration that evidence cites changes (its statement, or a definition's equations), or a
claim's printed text changes, `show` marks that evidence and the findings that cite it as
`stale`; the others stay current. Re-pin a record with `"repin": true` once you have checked it
again. Changing to independent mode, or importing, keeps what the workspace records you had seen,
so an informed investigation never becomes a blind review: a report made with `machinechecked
review` lists that exposure, and `review promote` refuses it without `--allow-revealed`.

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
| Cannot determine | What evidence would settle the question |

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

A directory of reports may be given instead of the files: it stands for the `*.json` files directly in it, in name order.

Promotion checks that the manuscript and formal statements still match the review pins, that the review stages were recorded in the required order, and that the verdict is eligible. It displays the planned changes and requires the maintainer's decision. Model-family and author restrictions still apply. A report whose reading was not blind is refused unless the maintainer passes `--allow-revealed`.

Promotion records the maintainer’s decision for the reviewed proposition or definition.
Acceptance also requires the claim’s proofs and all other required checks.

For details of the acceptance states, see [Evidence policy](EVIDENCE_POLICY.md). For the required configuration and review-marker format, see [Full assessment](ASSURANCE.md).

Reports and drafts are saved in this browser. **Export reports** downloads the reports for sharing
with the maintainer. **Review it** starts with the selected claim and records prior Lean exposure
when opened from the reader.
