# Reviewing paper-to-Lean correspondence

**A linked Lean theorem is not automatically a faithful formalisation of the paper.** MachineChecked's Review view helps a mathematician examine the correspondence one unit at a time and record a reproducible judgement.

The queue supports two settings: ordinary projects with linked statements, and projects with locked paper specifications, dependency-level definition reviews and an acceptance policy. It uses the same reader in both. In both, the steps of printed proofs have units of their own (see [Proof steps](#proof-steps)).

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

The commands work in both kinds of project. With a `machinechecked.toml` they review the full
assessment's queue; in any other Lean project they review the zero-configuration queue of the
last `machinechecked view` or `machinechecked build`, one unit per linked claim
(`link:<claim key>`). Each step refuses to run before the one it follows and is timestamped; the
reports are in the form the reader exports, and `review promote` checks them the same way. The
work is kept in your workspace in the project's working directory (`review-work/`; see below).
In zero configuration, export into `machinechecked-reviews/` to publish the reports with the
audit.

`read` gives every passage of the unit in full: a statement stated in several places, or a
definition used by many claims, is read in all of them. Each passage says where it is and how it
was obtained (the LaTeX source, or text extracted from the PDF at an approximate position). A
passage the build does not hold is marked UNAVAILABLE with its source reference, and PDF text
cut by the extraction is marked INCOMPLETE: read those in the paper. The paper's `\lean{...}`
tags are removed from the reading, since they name declarations.

`next`, `status`, `read`, `show` and `author` take `--json`: one document holding only what
that step shows, in the form of `machinechecked compare` (below). `read` holds the paper;
`show` adds the Lean (complete statements, binders, the definitions they use, Lean's checks);
`author` adds what has been recorded about the correspondence: the author's review, notes,
earlier reports, symbol links and statuses.

**Informed investigation.** Outside the three steps, `machinechecked compare CLAIM` gives a
claim's passage, its linked statements, its definitions and everything recorded about it, and
`compare --query` answers targeted questions (see [AGENTS.md](AGENTS.md)). That is an informed
inspection: someone who has used it on a claim has seen its Lean and its interpretations, and a
later review of that claim is not blind. Say so in the reading, and record it in your
workspace (an `exposure` operation, below) so that the report lists it.

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

**Facts inside a proof.** An exported theorem can prove more than it states. Under `view`, a linked
theorem has **Facts inside the proof**: *Read the proof* asks Lean for the propositions its proof
establishes along the way, each with the hypotheses it needs and the case of the proof it lies in,
and each theorem the proof applies with the local that supplies each of its hypotheses (`compare
--query proof-facts NAME` gives the same in a terminal). *Cite in the investigation* saves a fact
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
open until a step or evidence discharges it. The reader shows **Every clause, by the auditor's
composition**, the steps, and the next step: state the combination as one Lean result. When you
have done that, attach it as the composition's `bridge`, `{"theorem": NAME, "target": SPEC}`, with
`SPEC` a proposition stated as a definition that you have read against the paper. Lean checks it
when it is saved, and refuses a theorem whose type is not exactly the target. The composition then
reads **Every clause, through a checked bridge** while the check holds; a change to the target, a
definition it uses or the claim's passage puts it out of date, and it reads as your composition
again. `workspace show` and `compare --query composition CLAIM` print the argument; no status
changes either way.

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
`why_removed`, which keeps who removed it and why. In the reader, the Investigation section
shows the requirements with their passages and alignments, and offers **Add a requirement**,
**Suggest nearby context**, **Accept** and **Remove**. When a governing passage changes, its
requirement goes stale even if the display itself did not change. `machinechecked compare CLAIM
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
`resolution`: `common extension`, `checked bridge` with its `theorem`, `argument`, `inherited
assumption` or `renaming`, and its `text`) or `no difference` (with `why`). A domain,
representation or additional-assumption difference names the `transport` you inspected first (a
common extension, a bridge, the full theorem), so that a change of representation is not
recorded as a defect. The reading lists the Lean hypotheses no requirement is aligned with as
hints to inspect; a hypothesis aligned with a requirement that a standing assumption governs is
shown as inherited from it.

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

When a declaration that evidence cites changes (its statement, or a definition's equations), or a
claim's printed text changes, `show` marks that evidence and the findings that cite it as
`stale`; the others stay current. In a full assessment, `machinechecked changes --workspace ID`
lists them beside the review markers the new release reopened, each with what changed
([What changed since the last release](ASSURANCE.md#what-changed-since-the-last-release)). A cited fact inside a proof is `stale` once that proof
changes, even when the theorem's statement does not. Re-pin a record with `"repin": true` once you have checked it
again. Changing to independent mode, or importing, keeps what the workspace records you had seen,
so an informed investigation never becomes a blind review: a report made with `machinechecked
review` lists that exposure, and `review promote` refuses it without `--allow-revealed`.

**What a published audit carries.** `machinechecked export` (and `build --site`, `check --site`)
publishes, for each claim, the records you have accepted: the requirements, the passages
accepted as governing them, the alignments with Lean, and the submitted findings (superseded ones
too, with the reason) with the evidence and counterexamples they cite. Each keeps its author, its pins and whether it
is current against the published build. Proposed and removed passages, draft findings, evidence
no submitted finding cites, questions, exposure and the review protocol's drafts stay in the
workspace. The paper's `publish` settings apply: a passage's text and lines appear only when the
source text is published, and your notes and reasons only when reviews are. The reader shows the
records read-only on the claim, under **Auditors' readings**; they change no status.

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

## Proof steps

An equation or passage inside a printed proof has its own unit in the queue (`step:<claim id>`),
whether or not any Lean is linked to it. Its question is whether the printed step holds, in its
context: step 1 shows the step and the proof up to it and the sentence after it; step 2 shows the
Lean linked as establishing it and the formal route used instead, if any. The checklist covers
what the proof has fixed before the step, its premises, the ranges and order of its quantifiers,
its constants and its conclusion. Its verdicts are its own:

| Verdict | What the reviewer must explain |
|---|---|
| Holds as printed | Nothing more |
| Holds, with a gap in the argument | The argument the printed proof leaves out |
| False as printed | The counterexample or the failing case, and what would repair the step |
| Cannot determine | What would decide it |

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

The reviewer supplies their name or model identity. On a standalone HTML bundle, identity is **self-declared**; a Git name or a typed username is not proof of authorship.

Drafts are saved in this browser’s local storage. **Export reports regularly** to keep a durable
copy and share your work. The JSON contains your interpretation, comparison, verdict, source
revision, Lean fingerprints and reviewer attribution.

The maintainer reads the report and decides whether to promote its review markers.

## Publishing reports with an audit

In zero configuration, put exported report files in the project's `machinechecked-reviews/`
folder and build again. Each statement shows its reports under its links: the verdict, the
reviewer as recorded, the comparison and the locked reading. A report pins the text of the
statement it read; it is marked when the paper now prints another text, when it pins none, or
when the claim now links other declarations or their statements changed since it was recorded.
Reports are shown as their reviewers wrote them and change no status; `check --json` lists them
per claim.

## Maintainer acceptance

In a project with formal review markers, a maintainer can evaluate saved reports with:

```sh
machinechecked review promote machinechecked-reviews-....json
```

A directory of reports may be given instead of the files: it stands for the `*.json` files directly in it, in name order.

Promotion checks that the manuscript, the passages read (their digests, pinned when the reading was locked) and the formal statements still match the review pins, that the review stages were recorded in the required order, and that the verdict is eligible. It displays the planned changes and requires the maintainer's decision. Model-family and author restrictions still apply. A report whose reading was not blind is refused unless the maintainer passes `--allow-revealed`.

Promotion records the maintainer’s decision for the reviewed proposition or definition. The marker it writes records the digests of the paper passages read, so a later change to that text reopens the review. A passage the manuscript no longer matches reads as unread until it is pinned again, and promotion refuses a report on it (see [Evidence policy](EVIDENCE_POLICY.md#a-review-is-a-reading-of-a-text), which also says how markers written before the digests were recorded are read, and how to add the digests to them).
Acceptance also requires the claim’s proofs and all other required checks.

For details of the acceptance states, see [Evidence policy](EVIDENCE_POLICY.md). For the required configuration and review-marker format, see [Full assessment](ASSURANCE.md).

Reports and drafts are saved in this browser. **Export reports** downloads the reports for sharing
with the maintainer. **Review it** starts with the selected claim and records prior Lean exposure
when opened from the reader.
