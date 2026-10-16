---
name: machinechecked
description: Audit how a mathematical paper corresponds to its Lean 4 formalisation with the MachineChecked CLI - find the paper's numbered statements, see which are linked to Lean declarations, whether Lean proves them (sorry, extra axioms, not found), and which links still need a mathematician's review; write a shareable reader. Use when a user has a Lean project together with a paper (LaTeX, PDF, an arXiv URL, a leanblueprint, or a formalization.yaml) and asks which claims are formalised, whether the proofs compile, or whether the Lean statements match the paper.
---

# MachineChecked

MachineChecked reads a paper beside its Lean project and reports, claim by claim, what Lean
establishes. It checks the Lean mechanically (the linked declaration exists, its proof has no
`sorry`, which axioms it uses). It does **not** check that a Lean statement says what the paper
says: that is a mathematical judgement. Never report a claim as "verified" or "correct" because
its link reads *Lean proof checked*; say that Lean proves the linked statement, and that whether
the statement matches the paper has not been reviewed unless a review says so.

## Install and run

Run inside the Lean project (the directory with `lakefile.toml` or `lakefile.lean`):

```sh
lake build                                   # MachineChecked reads built declarations only
uvx --from git+https://github.com/cgarryZA/MachineChecked machinechecked check --json
```

Needs Python 3.11+, the project's Lean toolchain (elan), TeX Live with `latexmk` for a LaTeX
paper, and poppler (`pdftohtml`) for a paper that is only a PDF. If the project is not built,
links read `linked: Lean not checked (the project is not built)`: build it, or say so; never
treat that as proved. A large project can take hours to build: ask before starting one.

The paper is found automatically (a `.tex` with `\documentclass`, else a PDF). Pass it when
there are several or it is elsewhere: `machinechecked check --json paper/main.tex`, or a URL:
`machinechecked check --json https://arxiv.org/pdf/2601.01234v2`.

## Read the result

`check --json` prints one JSON document (progress goes to stderr) and exits 1 if a linked
declaration is missing or not proved. Per claim: `number` ("Theorem 2.1"), `status`, `links`
(each with `name`, `status`, `source`) and `suggestions` (unconfirmed candidates, with `why`).

| status | meaning |
|---|---|
| `linked: Lean proof checked` | Lean proves the linked declaration with the standard axioms |
| `linked: Lean proof incomplete (sorry)` | the proof, or something it uses, has `sorry` |
| `linked: Lean proof uses further axioms` | it depends on axioms beyond the standard three |
| `linked: Lean declaration not found` | the name does not exist in the built project |
| `linked: Lean definition` | the link is to a definition (nothing to prove) |
| `linked: Lean not checked (the project is not built)` | Lean was not run |
| `suggested link, not confirmed` | only a candidate; nobody has linked it |
| `not linked` | no Lean counterpart is known |

Link `source` says who made the link: `paper` (a `\lean{}` tag), `formalization.yaml` (the
project's own mapping), or `confirmed` (saved in `machinechecked.links.json`).

## Typical tasks

- **Which claims are formalised?** Run `check --json`; group claims by `status`. Report the
  unlinked ones by number, and the suggestions as candidates only.
- **Do the proofs compile?** The `linked: …` statuses answer it for linked claims. Quote the
  declaration names that are incomplete, use further axioms, or are missing.
- **Does a Lean statement match the paper?** Read the claim in the paper and the Lean
  declaration's statement (`#check` it, or open its source), and compare hypotheses,
  quantifiers, definitions and conclusion. Present it as your reading, for the user to judge;
  the reader's Review page (`machinechecked view`, then Review) records such a review
  properly, and a report changes no status.
- **Link a claim to a declaration**: the user does it in `machinechecked view` (Link / Not
  this), or you add a `\lean{Name}` tag to the statement in the LaTeX if the user agrees.
- **A shareable report**: `machinechecked build` writes `MachineChecked.html` (one file, opens
  from disk). `machinechecked build --site public/ --author "Name" --issues owner/repo` writes a
  directory to publish (for example on GitHub Pages) with `audit.json` describing it. Both
  contain the paper and Lean statements: confirm the user may publish them.

## Do not

- Do not call a paper "verified", "machine-checked" or "correct" on the strength of these
  statuses, and give no percentages of verification.
- Do not run `machinechecked view` in a non-interactive session: it starts a local server and
  opens a browser. Use `check --json` and `build`.
- Do not edit `machinechecked.links.json` by hand to make a claim look linked; a link is a
  statement by the person who makes it.

More: https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md
