---
name: machinechecked
description: Audit how a mathematical paper corresponds to its Lean 4 formalisation with the MachineChecked CLI - find the paper's numbered statements, see which are linked to Lean declarations, whether Lean proves them (sorry, extra axioms, not found), and which links still need a mathematician's review; write a shareable reader. Use when a user has a Lean project together with a paper (LaTeX, PDF, an arXiv URL, a leanblueprint, or a formalization.yaml) and asks which claims are formalised, whether the proofs compile, or whether the Lean statements match the paper.
---

# MachineChecked

MachineChecked runs locally in the user’s Lean project. It reads the paper and compiled Lean,
saves generated data in `.machinechecked/`, and records confirmed links in `machinechecked.links.json`.
`build` writes a shareable reader. Publish or share these files when the user authorizes it.
Review drafts stay in the current browser until exported.

Report what each check establishes: Lean proves the formal proposition; correspondence reviews
compare that proposition and its definitions with the paper. Attribute reviews to their recorded
reviewers. Source verification and independent kernel replay have their own results.

## Install and run

Run inside the Lean project (the directory with `lakefile.toml` or `lakefile.lean`):

```sh
lake build                                   # MachineChecked reads built declarations only
uvx machinechecked check --json
```

Needs Python 3.11+, the project's Lean toolchain (elan), TeX Live with `latexmk` for a LaTeX
paper, and poppler (`pdftohtml`) for a paper that is only a PDF. If the project is not built,
links read `linked: Lean not checked (the project is not built)`: build it, or report the build requirement. A large project can take hours to build: ask before starting one.

The paper is found automatically (a `.tex` with `\documentclass`, else a PDF). Pass it when
there are several or it is elsewhere: `machinechecked check --json paper/main.tex`, or a URL:
`machinechecked check --json https://arxiv.org/pdf/2601.01234v2`.

## Read the result

`check --json` prints one JSON document (progress goes to stderr). Exit 0: every linked
declaration is proved; 1: one is missing or not proved; 2: the check could not run. On exit 2 the
document has an `error` (`kind`, `message`, and `tool` when a program such as `lake` is missing)
and an empty claims list: report the execution error. `version` is the
MachineChecked version; `release` identifies the evidence the statuses were computed from (it
changes when the paper, the links or the Lean change), for quoting which run a report is about.
Per claim: `number` ("Theorem 2.1"), `status_code`, `status`, `links`
(each with `name`, `status`, `source`) and `suggestions` (unconfirmed candidates, with `why`).

| status | meaning |
|---|---|
| `linked: Lean proof checked` | Lean proves the linked declaration with the standard axioms |
| `linked: Lean proof incomplete (sorry)` | the proof, or something it uses, has `sorry` |
| `linked: Lean proof uses further axioms` | it depends on axioms beyond the standard three |
| `linked: Lean declaration not found` | the name does not exist in the built project |
| `linked: Lean definition` | the link names a definition |
| `linked: Lean not checked (the project is not built)` | Lean was not run |
| `linked: Lean not checked (its module M is not built)` | the declaration's module is not built yet; build it to check |
| `linked: Lean not checked (its module M could not be loaded)` | the module failed to load; report the loading error |
| `linked: Lean name is ambiguous (declared in A, B)` | several modules declare the name (e.g. a challenge statement and its solution); name the module in `formalization.yaml` |
| `suggested link, not confirmed` | a candidate awaiting confirmation |
| `not linked` | no Lean counterpart is known |

Link `source` says who made the link: `paper` (a `\lean{}` tag), `formalization.yaml` (the
project's own mapping), or `confirmed` (saved in `machinechecked.links.json`).

`class` (`proved`, `open`, `malformed`, `unspecified`) is a coarse grouping of the status, used
for the reader's colours: `proved` for a proof checked or a definition, `open` for `sorry` or
further axioms, `malformed` for a declaration not found, `unspecified` for everything not checked
or not linked. A claim's class is that of its worst link. Branch on `status_code`; use `status` for presentation.
Report correspondence using its own review records.

With a `machinechecked.toml` (the full assessment), `finding_details` lists each finding
(`tier`, `code`, `subject`, `message`, and `dismissed` when a warning was dismissed): quote the
violations and obligations by subject; `findings` holds only their totals.

## Typical tasks

- **Which claims are formalised?** Run `check --json`; group claims by `status_code`. Report the
  unlinked ones by number, and suggestions as candidates.
- **Do the proofs compile?** The `linked: …` statuses answer it for linked claims. Quote the
  declaration names that are incomplete, use further axioms, or are missing.
- **Does a Lean statement match the paper?** `machinechecked compare CLAIM --json` (after
  `view` or `build`) gives the claim's complete passage, its linked declarations' complete
  statements and the definitions they use, with the release and commit they come from; compare
  hypotheses, quantifiers, definitions and conclusion. `compare --query definition NAME` and
  `compare --query mentions NAME` answer the next question. Present it as your reading, for
  the user to judge; `machinechecked review` (or the reader's Review page) records a review
  with source revisions and reviewer attribution, and shows the paper before the Lean.
- **Where is a paper statement proved, and what does a proof rest on?** `machinechecked
  inspect NAME --dependencies --json` prints the declaration's statement, axioms and source,
  what its statement mentions and, separately, what its proof uses, and every declaration of
  the project reachable through both, each with its own split and its distance from NAME.
  Start from the theorem that matches the paper's main result and follow its proof to find
  the lemmas a paper statement may correspond to; also search the rest of the project, since
  a lemma can be formalised without being used by that proof. If two modules declare the
  name, pass `--module`. A dependency identifies constants used by Lean terms.
- **Does the main result use this lemma?** `machinechecked compare --query impact NAME --json`
  answers for each main result (the declarations linked to the paper's theorems, or those
  `--main` names): used by its proof, in its statement only, formalized separately, or not
  traced, with the path of references and the applications of NAME at its end, and lists the
  claims whose linked Lean uses NAME. *Formalized separately* says only that this main
  result's Lean does not refer to NAME; *not traced* says the trace is incomplete, never that
  NAME is unused. Whether a difference in NAME matters at a use is your reading, for the user
  to judge.
- **Link a claim to a declaration**: the user does it in `machinechecked view` (Link / Not
  this); with the user's agreement, `machinechecked link "Theorem 2" Pkg.name --as NAME --json`
  records it (`--reject NAME`, `--clear`; `--dry-run` first), or a `\lean{Name}` tag in the
  LaTeX. An unknown or ambiguous claim or name is refused with candidates.
- **Record what establishes a clause**: `machinechecked workspace update FILE` with evidence and
  finding records (docs/REVIEWING.md, "Saved investigations"); `workspace show --json` resumes
  it. A finding is your reading, attributed to you; it changes no status.
- **Break a claim into requirements**: `requirement`, `fragment` and `alignment` records of the
  same workspace keep each requirement with the exact passages that govern it (a quantifier's
  domain, a constant's dependence, a standing assumption) and the Lean it corresponds to.
  `workspace suggest --claim C --requirement r1` proposes nearby passages; a proposal is a guess
  until accepted. A later use of a result is a use, never a change to its reading.
- **Combine several results**: a `composition` record lists the steps, the declaration,
  application or fact inside a proof each rests on, the substitutions, which objects are the
  same, and the open obligations. It reads as your composition, with the next step: state the
  combination as one Lean result. A `bridge` (a theorem whose type is exactly a target
  proposition) is checked by Lean when saved; `compare --query composition CLAIM` shows them.
- **A shareable report**: `machinechecked build` writes `.machinechecked/MachineChecked.html`
  (one file, opens from disk; Git ignores it there, and `--out` puts it elsewhere). `machinechecked build --site public/ --author "Name" --issues owner/repo` writes a
  directory to publish (for example on GitHub Pages) with `audit.json` describing it. Both
  contain the paper and Lean statements: check the user’s publication authorization.

## Report and act precisely

- Name the formal proposition and proof result. Attribute mathematical correspondence to reviews
  with their recorded scope and provenance.
- In a non-interactive session, use `check --json` and `build`. `view` starts a local browser session.
- Save links through the reader, `machinechecked link` or an authorized source tag, preserving who
  made the association.
- Write concise, affirmative prose. Explain what happened or what the user can do next.

More: https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md
