# Threat model

What MachineChecked must not get wrong, and how each failure is kept out.

## What is protected

1. **The meaning of a status.** A reader must never be told a claim is established at a level it
   is not. This is the main asset, and the main risk is overstatement, not unsoundness.
2. **Private material.** Manuscript sources, unpublished statements, Lean sources and PDFs of
   private repositories must not reach a public export.
3. **The machine that builds.** Untrusted LaTeX or Lean must not run commands, read credentials or
   write outside its build directory.

## Overstatement

| Way it could happen | Defence |
|---|---|
| The reader computes or rounds a status | Statuses and findings are computed in `assess.py` only and copied into the manifest; the web app has no status logic |
| A Lean proof of a different statement counts as a proof of the claim | The acceptance theorem's type must be exactly the closed proposition (`.const spec`) |
| A proposition changes after review | Reviews are keyed to a hash of the proposition and of every definition it depends on; any change makes the review stale |
| A hypothesis cannot be met, so the proof is vacuous | A proposition with hypotheses needs a witness theorem; regimes the paper intends to cover need their own witnesses |
| The statement's author reviews it | Reviewers listed as `statement_authors` never count as independent, whatever a marker declares |
| An AI review passes for a human one | Each review records `kind` (human, AI, not recorded); AI reviewer patterns are configured |
| A heuristic is read as a verdict | Findings have tiers; only violations are mechanical; warnings can be dismissed with a recorded rationale that lapses when the statement changes |
| A paper claim silently has no counterpart | The compiled paper's numbered environments are compared with the inventory (`inventory-gap`, `inventory-unanchored`) |
| The manuscript changes under a frozen claim | Each claim's source hash is compared with the compiled paper (`source-changed`) |
| A link shows newer evidence than it was made for | Routes carry the release; a mismatch shows a banner |
| A PDF-only paper looks as checked as a LaTeX one | PDF-only claims get a `pdf-only` source rung and the paper is labelled |

## Private material

The export is built from fields each paper's `publish` settings allow, never by removing things
from the private preview. Every output file is then scanned: any line of at least 30 characters
from a private manuscript or Lean source, and any byte-identical private PDF, blocks the export
and deletes the partial output. GitHub Pages is public unless an enterprise access control says
otherwise. The default for every `publish` field is `false`.

## Untrusted builds

- **Acquisition** is the only stage with credentials (`token_env`, passed as an HTTP header,
  never written to disk or the evidence). It uses `git archive` into a snapshot and runs nothing.
- **Compilation** runs on a copy of the snapshot with:
  - `latexmk -norc`, so the source's rc files are ignored;
  - `shell_escape=f`;
  - `openout_any=p`, so nothing is written outside the build directory;
  - a CPU limit of 600 s and a file-size limit of 512 MB.

  A document that needs shell escape fails, and the PDF of the source is used instead; the
  sandbox is not weakened.
- **The Lean probe** runs in the project's own toolchain with `lake env lean`. Lean elaboration
  can run arbitrary code (`#eval`, macros), so the probe must only be run on projects trusted as
  much as building them. In CI it runs without publication credentials.
- **CI** never uses `pull_request_target`. A workflow that publishes reads only the export
  directory.

Hardening for third-party, untrusted repositories (containers, network isolation for compilation)
is Phase 6.
