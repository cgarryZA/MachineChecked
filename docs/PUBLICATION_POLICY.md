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
   With `lean = false`, it carries no Lean statements or declaration bodies. With
   `reviews = false`, it carries reviewers and states but not review texts.
2. **Assemble, then scan.** The export is assembled from allowed fields. Every file is then
   scanned against the private inputs, and any match blocks the export.
3. **Pin.** A public release names its evidence id, the project commit and every paper revision.
   For private sources, the release records the access required to reproduce it.
4. **Name the artifact.** A PDF with the audit appendix is a "Paper with Formal Verification Audit".
   Describe claim acceptance using the recorded per-claim results.
5. **The research repositories stay private** until their owner decides otherwise. Public
   MachineChecked development uses only the synthetic examples.
