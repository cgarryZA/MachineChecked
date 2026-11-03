# Publication policy

## Three artifacts

| Artifact | Audience | Where |
|---|---|---|
| The demo | developers | GitHub Pages of this repository, built from the synthetic toy paper |
| A paper audit preview | the author and invited collaborators | `machinechecked serve` locally, or a private Actions artifact (retention is limited, so not an archive) |
| An approved paper release | referees and readers | a public, version-pinned static site produced by `machinechecked export` |

## Rules

1. **Everything defaults to private.** A paper's `publish` table must say explicitly
   `pdf = true`, `source_text = true`, `lean = true` or `reviews = true`. With
   `source_text = false`, the export carries no manuscript text, file paths or source locations.
   With `lean = false`, it carries no Lean text: no statement, declaration body, type or term
   the build printed, anywhere, findings included. A warning keeps what it says without quoting
   the Lean (a totalisation warning names its operation, the structure on its type and the
   state of each condition of its rule, and leaves out the type, the sub-terms and the
   premises). Text that quotes the Lean is published only with it: review texts, a step
   review's comparison and verdict, and a dismissal's rationale need both `reviews = true`
   and `lean = true` (a step review's reading of the paper, made before the Lean is shown,
   needs `reviews = true` only). With `reviews = false`, it carries reviewers and states but not
   review texts.
   The auditors' accepted workspace records, what each submitted finding rests on, and the
   version maps they kept follow the same settings
   ([data model](DATA_MODEL.md#published-workspace-records-prooflenspublished-work1-written-by-the-export)).
   Drafts, unaccepted suggestions, rejected candidates and working notes are never published.
   The published semantic summary names what the settings withhold, so a reader sees
   "withheld", never "not assessed", for it.
2. **Assemble, then scan.** The export is assembled from allowed fields. Every file is then
   scanned against the private inputs, and any match blocks the export.
3. **Pin.** A public release names its evidence id, the project commit and every paper revision.
   For private sources, the release records the access required to reproduce it.
4. **Name the artifact.** A PDF with the audit appendix is a "Paper with Formal Verification Audit".
   Describe claim acceptance using the recorded per-claim results.
5. **The research repositories stay private** until their owner decides otherwise. Public
   MachineChecked development uses only the synthetic examples.
