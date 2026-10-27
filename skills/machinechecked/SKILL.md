---
name: machinechecked
description: Audit how a mathematical paper corresponds to its Lean 4 formalisation with the MachineChecked CLI - find the paper's numbered statements, see which are linked to Lean declarations, whether Lean proves them (sorry, extra axioms, not found), and which links still need a mathematician's review; investigate whether Lean establishes a claim as printed (search, uses, facts inside proofs, compositions) and save the evidence for others to resume; write a shareable reader. Use when a user has a Lean project together with a paper (LaTeX, PDF, an arXiv URL, a leanblueprint, or a formalization.yaml) and asks which claims are formalised, whether the proofs compile, whether the Lean statements match the paper, or where and how the Lean covers a claim.
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
A link whose module is not built or could not be loaded, or whose name is ambiguous, also has
`status_detail`, naming the module or the modules that declare the name; for a module that could
not be loaded, it also gives the first lines of what Lean reported, and says when the module's
library could not be loaded in one session first.

| status | meaning |
|---|---|
| `linked: Lean proof checked` | Lean proves the linked declaration with the standard axioms |
| `linked: Lean proof incomplete (sorry)` | the proof, or something it uses, has `sorry` |
| `linked: Lean proof uses further axioms` | it depends on axioms beyond the standard three |
| `linked: Lean declaration not found` | the name does not exist in the built project |
| `linked: Lean definition` | the link names a definition |
| `linked: Lean not checked (the project is not built)` | Lean was not run |
| `linked: Lean not checked (module not built)` | the declaration's module is not built yet; build it to check |
| `linked: Lean not checked (module could not be loaded)` | the module failed to load; report the loading error its `status_detail` gives |
| `linked: Lean name is ambiguous` | several modules declare the name (e.g. a challenge statement and its solution); name the module in `formalization.yaml` |
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
violations and obligations by subject; `findings` holds only their totals. A violation saying
`machinechecked check --fix-modules` lists a module is a declaration whose module is missing from
`modules`: with the user's agreement, run `check --json --fix-modules`, which edits
`machinechecked.toml`, checks again and lists the modules it added in `modules_added`.

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
  answers for each main result (those `--main` names, else those saved with `machinechecked
  workspace main NAME...`, which `selection` attributes, else the declarations linked to the
  paper's theorems): used by its proof, in its statement only, formalized separately, or not
  traced, with the path of references and the applications of NAME at its end, and lists the
  claims whose linked Lean uses NAME. *Formalized separately* says only that this main
  result's Lean does not refer to NAME; *not traced* says the trace is incomplete, never that
  NAME is unused. Whether a difference in NAME matters at a use is your reading, for the user
  to judge.
- **Link a claim to a declaration**: the user does it in `machinechecked view` (Link / Not
  this); with the user's agreement, `machinechecked link "Theorem 2" Pkg.name --as NAME --json`
  records it (`--reject NAME`, `--clear`; `--dry-run` first), or a `\lean{Name}` tag in the
  LaTeX. An unknown or ambiguous claim or name is refused with candidates.
- **Does the Lean establish a claim as printed?** Investigate it (below) and save the evidence
  in a workspace.
- **What changed since the last build?** After a rebuild, `machinechecked workspace show
  --json` marks the saved records whose paper text, statement, proof or certificate changed
  `stale`, and the findings resting on them, each finding naming the part that changed (a
  definition its cited statement uses included). In a full assessment, `machinechecked changes --json` compares two releases claim by
  claim and names every review the later build no longer counts, with the dependency that
  changed; `--workspace ID` adds the workspace's records that are not current, of every
  kind: evidence, findings, questions, counterexamples, compositions, requirements, fragments
  and alignments. `--map` matches each claim of the earlier paper revision to the later one by
  its passage, with each release's own status; a shared number or id is only a proposal. With
  `--map --workspace ID`, each finding is reopened exactly when a passage it rests on changed
  (a moved or renumbered passage keeps it current), naming the change and the part, with a
  question; an ambiguous match is not known to be current.
- **A shareable report**: `machinechecked build` writes `.machinechecked/MachineChecked.html`
  (one file, opens from disk; Git ignores it there, and `--out` puts it elsewhere). `machinechecked build --site public/ --author "Name" --issues owner/repo` writes a
  directory to publish (for example on GitHub Pages) with `audit.json` describing it. Both
  contain the paper and Lean statements: check the user’s publication authorization.

## Investigate a claim

An investigation finds where and how the Lean covers each requirement of a claim and saves the
evidence, so that you or another agent can resume it. Open a workspace first
(`machinechecked workspace open --mode informed --as llm:MODEL`) and record each result as you
go (`workspace update`, with the records of
https://github.com/cgarryZA/MachineChecked/blob/main/docs/REVIEWING.md#saved-investigations).
https://github.com/cgarryZA/MachineChecked/blob/main/docs/AGENTS.md#a-worked-investigation
carries every step out on the toy example.

1. **Read the claim.** `compare CLAIM --stage read --json` gives its complete passage. Record
   each requirement (a quantifier with its domain, a constant with what it may depend on, a
   hypothesis, the conclusion) with the source `fragment` it comes from, standing assumptions
   and the sentences around a display included. `workspace suggest --claim C --requirement r1`
   proposes nearby passages; a proposal stays a guess until you accept it. A passage that uses
   the result later is a fragment with role `later use`, shown apart from the reading.
2. **Search by content.** `compare --query search CLAIM` ranks the project's declarations by
   what their statements say; `search 'EXPRESSION'` takes a formula or words, and `search NAME`
   finds the declarations like NAME, each with the hypotheses it does not assume or also
   assumes and whether its conclusion is the same (all read the build's content index). A paper number in a docstring or comment is a
   lead: `check --json` lists in `numbering` each number that names another kind of statement
   (`other-kind`), none (`absent`), or a declaration that reads closer to another claim
   (`stale_lead`), and a suggestion's `number` reason names the references it rests on
   (`references`). Under `pattern.drift`, treat each cited number as possibly stale and decide
   by content. Before concluding that a requirement has no support, look at the results
   that use the weaker ones (`--query uses`), the statements about the same objects (`--query
   mentions`) and the stronger wrappers a search reaches through a close match (`signal`
   `uses`).
3. **Inspect.** `compare CLAIM --json` gives each linked or suggested declaration's complete
   statement and the definitions it uses; `--query definition NAME` and `--query dependencies
   NAME --json` go further. Compare quantifier order, domains, hypotheses, definitions and the
   conclusion.
4. **Follow the objects.** `--query uses NAME` gives each application of NAME with the argument
   supplied to every binder, the origin of each premise (its `discharge`: `assumed` by the
   caller, `proved` in it, or `local`) and the object each premise and the conclusion are
   about (`objects`); `--in APP_ID` reads one application with its whole context. `--query proof-facts NAME` gives the facts a proof
   establishes on the way, each under its assumptions and case. Each prints the reference
   evidence cites: an application's `id`, a fact's position `at`.
5. **Assemble.** Cite declarations, applications (`{"app": {callee, id}}`) and proof facts
   (`{"fact": REF}`) as evidence, and combine them in a `composition` with its substitutions,
   the objects different steps share, and its open obligations. A `bridge` attached to it is
   checked by Lean when saved: it establishes that its theorem proves the target proposition
   exactly, and the target's agreement with the paper stays your reading.
6. **Compare estimates and steps.** Record a `difference` (its feature, the paper's and Lean's
   expressions, the outcome) on the requirement it affects, and a `counterexample` against one
   reading, with a Lean certificate as evidence when you have one. A printed proof step is a
   claim of its own (`compare "Equation (3)"`), with its own verdict, such as `false as
   printed`. `--query impact NAME` says whether each main result uses NAME (`--main NAME`
   chooses them for one query; `workspace main NAME...` saves the user's choice in the
   workspace, with your name and the project commit) and lists the claims whose Lean uses it: a
   difference between NAME and the paper can matter only to those.
7. **Conclude.** A finding gives the coverage and its basis: `direct` (one Lean statement),
   `reviewed_composition` (your argument) or `checked_bridge` (a composition whose bridge Lean
   checks; any other reads as your argument). It is your reading, attributed
   to you, and changes no status. Save what remains open as a `question` and set the `resume`
   point. Submit the findings that are final; `build --site DIR` publishes them with the audit.
8. **Resume.** `workspace export` and `workspace import` hand a workspace on; `workspace show
   --json` gives its `resume` point and each record's `currency` against the current build. A
   submitted finding records the parts it rests on with their versions (`dependencies`): it
   reads `stale` naming the part that changed, or `unchecked` with `currency.unknown` when a
   part is not known, never `current`; re-pinning a record does not refresh it, superseding does.

Each answer says what it covers. `retrieval.unavailable` in a `compare` packet lists what is not
extracted yet, with the issue that owns it; a query answers `available: false` with its
`reason` when its kind is not available here; `complete: false` (a passage, a list, a `uses`
scope with modules not built, a proof walk that reached its limit) marks a partial answer, and
`retrieval.next` with `--after` fetches the rest.

## Report and act precisely

- Lead with the mathematical finding. Then give the exact declarations, applications (`app` id)
  and proof facts it rests on, the connecting argument, and the `snapshot` (release, project
  commit, paper revision) it was read from.
- When a search finds nothing, say where it looked: the query, the modules searched (`scope`),
  and anything not built.
- Name the formal proposition and proof result. Attribute mathematical correspondence to reviews
  with their recorded scope and provenance; report an author's review as the author's.
- Present your interpretation of the paper as yours: it is saved under your name and stays
  editable. An informed investigation has seen the Lean; an independent review goes through
  `machinechecked review`, which records that exposure. `review next --order informed` also
  ranks the units by what auditors' workspaces record as open, and records that you have seen
  those prior interpretations, so a later reading of those claims is not blind.
- In a non-interactive session, use `check --json` and `build`. `view` starts a local browser session.
- Save links through the reader, `machinechecked link` or an authorized source tag, preserving who
  made the association.
- Write concise, affirmative prose. Explain what happened or what the user can do next.

More: https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md
