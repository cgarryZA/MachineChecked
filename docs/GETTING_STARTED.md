# Getting started

**MachineChecked runs locally, in your Lean project.** It reads your paper and your compiled Lean declarations, writes an interactive reader, and keeps its results on your computer: generated data in `.machinechecked/`, the links you confirm in `machinechecked.links.json`, and the reader as `.machinechecked/MachineChecked.html` if you ask for one. No account, registration or upload is needed. Publishing an audit (on your own GitHub Pages, say, and listing it on machinechecked.org) is a separate step you choose to take.

MachineChecked is a reader for mathematical papers and their Lean formalisation. You can use it without preparing a claim inventory or adopting a particular proof-review framework.

## Before you start

You need a Lean project with a `lakefile`, Python 3.11 or later, and a working Lean toolchain (usually installed with [elan](https://github.com/leanprover/elan)). Build the Lean modules you want to inspect:

```sh
lake build
```

MachineChecked reads the built declarations. It reports modules it cannot find; it does not quietly trigger a lengthy Lean build.

For a LaTeX paper, install TeX Live with `latexmk`. Some papers also need `xelatex` or `lualatex`. For a paper that is only a PDF, install poppler (`pdftohtml`, `pdfinfo`). You do not need Node or Vite.

## Open the reader

Run this inside the Lean project's directory:

```sh
uvx machinechecked view
```

Or install it once:

```sh
pip install machinechecked
machinechecked view
```

Pass a specific paper when useful:

```sh
machinechecked view paper/main.tex
machinechecked view paper/main.pdf
```

MachineChecked looks for a root LaTeX document first, otherwise a PDF. If several candidates remain, it lets you choose. Leanblueprint projects can use their existing `\lean{...}` tags; no conversion is needed: `blueprint/src/print.tex` is the paper, and an engine the blueprint's `latexmkrc` names is used (the file is read as text, never run).

## Papers that are only a PDF, or at a URL

A paper can be a URL: `machinechecked view https://…/paper.pdf` downloads it once into `.machinechecked/papers/`.

From LaTeX, MachineChecked knows every numbered statement exactly. From a PDF it can only **try**: it reads the PDF's text and takes a bold heading such as "**Lemma 8.6.**" as the start of a statement, which tells it apart from a mention of the lemma in the text. That is a heuristic, and its limits are real:

- a scanned PDF, with no text layer, yields no statements;
- a heading in unusual formatting (not bold, or split into several pieces of text) can be missed;
- where a statement ends is estimated (at "Proof", a section heading or the next statement), so its marker is drawn as approximate;
- numbers are read as printed, not from the source's labels.

The reader says how each such statement was found, so a missed or misplaced one is visible rather than hidden.

## Projects with a formalization.yaml

A project that describes itself with a [`formalization.yaml`](https://github.com/mathlib-initiative/formalization.yaml) needs nothing else:

- its formalised sources are offered as papers;
- the mappings in its `alignment` (in the shape `statements: [{source, lean}]`) become links, labelled *formalization.yaml*: they are the project's own statements, not a review;
- its review status ("self-assessed", "peer-reviewed", …) is shown as the project's description of itself. Figures in the file, such as a count of `sorry`s, are the project's report, not a check by MachineChecked.

When the file names several sources, a mapping is used for a paper only if it names that paper by a word distinctive to its title.

If the Lean project is not built, linked claims read **linked: Lean not checked (the project is not built)**, never proved.

The reader opens on the paper. The contents list shows numbered mathematical statements. Select one in the contents or click its margin marker to view its Lean associations. The claim's panel shows its status and then the comparison itself: **Paper**, the statement as printed, and **Lean**, the formal statement with its assumptions (a very long one folds, saying how many lines it hides, except when its quantifiers choose a value, since then the order is its meaning). Each object of the statement is shown with the conditions that directly follow it and concern it alone; a condition on several objects keeps its own row, and nothing changes order. A conclusion made of several parts lists them. Pointing at a variable highlights it wherever it occurs, and clicking it holds a small summary of its type and conditions. Clicking a Lean name opens that declaration in place of the claim, beside the paper's definition when a claim links it, and **Back** returns to the claim as you left it. The status opens the audit details: the evidence, reviews, checks still to record and provenance. **Report issue** drafts a report in the audit's repository; the ⋯ menu holds the rest (a link to the claim, existing reports, the audit details).

## Connect a claim to Lean

MachineChecked may suggest a declaration from a `\lean{...}` tag, a Lean docstring mentioning the theorem number, or a similar name. **A suggestion is not an established correspondence.**

You can:

- **Link** a suggested declaration;
- choose **Not this** to reject the suggestion;
- search the project's declarations to choose another.

The local reader saves your decisions in `machinechecked.links.json` at the repository root and refreshes the view. Commit that small file if you want the associations to travel with the project.

A link records an association, **not** a mathematical review. It is possible for Lean to accept the linked theorem while its hypotheses or conclusion fail to match the paper.

## Read a claim

Select a claim to see the printed statement beside its Lean statement, set out as its variables, its hypotheses in order, and its conclusion. When the project's repository is on GitHub, **Lean source** opens the declaration at the exact commit and line. Where a corrected statement stands beside the printed one, a box says what the correction changes: the hypotheses it adds or drops, and whether the conclusion is the same. That box describes the two Lean statements; it is not a judgement of either. **Review it** opens the review queue, and **Raise issue** a report to the audit's repository.

## Interpret the status

- **Not linked / suggested:** no confirmed correspondence.
- **Linked, proof checked:** Lean accepts the named formal theorem, subject to its axioms. It is not a certificate of correspondence with the paper.
- **Linked, Lean definition:** the link is to a definition, which has nothing to prove.
- **Linked, Lean not checked:** the project, or the declaration's own module, is not built, so Lean has not been run on it here. A project can be partly built: what is built is checked, and each link says whether its module is.
- **Linked, Lean name is ambiguous:** several modules declare the same name (a statement left as a challenge and its solution, for instance). Name the intended module in the `formalization.yaml` row (`module: …`); MachineChecked never picks one for you. Each Lean library is inspected in its own Lean session, so libraries that cannot be loaded together are handled; a module MachineChecked cannot load at all is reported as such, never as "not found".
- **Incomplete (`sorry`):** the formal proof has unfinished obligations.
- **Further axioms:** the proof relies on axioms beyond the default allowlist.
- **Definition / declaration not found:** the linked item is not a checked theorem or cannot be resolved from the built modules.

For projects with a separate acceptance framework, further statuses and evidence are available. [Read the evidence policy](EVIDENCE_POLICY.md) before interpreting them.

## Share or publish

```sh
machinechecked build
```

This produces `.machinechecked/MachineChecked.html` (or the file `--out` names). It includes the reader, the paper and its generated data, and opens directly from disk in a browser. It can be sent to another reader without requiring them to install anything.

To publish the reader on the web instead, write it as a directory and put that directory on any static host, such as GitHub Pages:

```sh
machinechecked build --site public/ --author "Your Name" --issues owner/repo
```

If the Lean repository is private, add `--private-repository`: the reader then labels its source links as private instead of naming the repository. The name is still inside the links and the data, and the links open only for people with access.

The directory carries `audit.json`, a short description of the audit: the paper (with its arXiv identifier and version when it was given by an arXiv URL), the Lean repository, commit and toolchain, who published it, where reports go, and where its data is. A site that lists audits, such as machinechecked.org, reads that file and the data beside it, and shows them as data: it runs nothing from the audit, and it does not endorse it. Check the directory before publishing it: like the HTML file, it contains the paper and the Lean statements.

To check the linked declarations in automation:

```sh
machinechecked check
```

This fails when a linked declaration is missing or not proved. It does **not** independently judge whether the association matches the mathematics in the paper.

Git ignores `.machinechecked/` by itself (it holds a `.gitignore`, as Lake's `.lake/` does), so a downloaded paper, the generated reader and `MachineChecked.html` are never committed by accident. To keep the file elsewhere, say where with `--out`: it embeds the paper, so committing it is a deliberate choice. A private paper bundled into HTML remains private content: do not publish it without checking the export.

## Build on your own CI, and save the build

A large project can take hours to build. Two things save that time, both on your own resources:

**A saved build.** After `lake build`, `machinechecked cache save` archives the build output (not Mathlib's, which `lake exe cache get` supplies) with a manifest: the commit, Lean version, platform, dependencies, and every file's SHA-256. `machinechecked cache publish OWNER/REPO` uploads it, with your project's `LICENSE` and `NOTICE`, to a `build-cache` prerelease of that repository; set `MACHINECHECKED_GH_TOKEN` to a token that can write releases there. Anyone can then restore it:

```sh
machinechecked cache restore OWNER/REPO --build    # minutes instead of hours
```

Restore picks a saved build with the same Lean inputs (whatever the clone's folder or history, shallow or rewritten), else the nearest one of an earlier commit (which needs the history: `fetch-depth: 0` with `actions/checkout`), always with the same Lean version, platform and dependencies; it checks every SHA-256 and unpacks it; `--build` then runs `lake build --rehash`, which rebuilds exactly what changed since. A mismatched, incomplete or corrupt archive is refused, and the build happens from source. `--from DIR` restores from a folder of saved archives instead. `machinechecked cache prune OWNER/REPO --keep N` deletes all but the newest `N` saved builds of each package, platform and Lean version. A restored build is trusted as built: Lake does not re-check its proofs; that is what a kernel replay (Comparator) is for.

**Your own workflow.** MachineChecked's reusable workflow builds your project on your GitHub Actions minutes, restoring a saved build when there is one, and uploads the audit (`build --site`) as an artifact you can publish:

```yaml
# .github/workflows/machinechecked.yml in your repository
on: { push: { branches: [main] }, workflow_dispatch: }
jobs:
  audit:
    uses: cgarryZA/MachineChecked/.github/workflows/audit.yml@main
    with:
      cache-repo: you/your-project   # optional
      paper: paper/main.tex          # optional
      tex: true                      # the paper is LaTeX
```

MachineChecked's own infrastructure never builds anyone's Lean.

## A badge for your README

Once your paper is listed on machinechecked.org (a repository whose `formalization.yaml` names an
arXiv paper is listed within a day), its page has a badge that says how far the site's knowledge
of it goes ("Lean repository linked", or "audit published"):

```md
[![MachineChecked](https://machinechecked.org/papers/2601.01234/badge.svg)](https://machinechecked.org/papers/2601.01234/)
```

Use your paper's arXiv identifier. The badge says what is listed, never that anything is
verified.

## Share a claim or report a problem

A claim has **Copy link**, which copies its permanent address when the site is hosted. On an unhosted local copy, it copies a claim reference instead.

To enable **Raise issue**, launch the reader with a repository for reports and the eventual public address:

```sh
machinechecked view --issues owner/repo --site-url https://example.org/audit/
```

This opens a prefilled GitHub issue *draft* with claim identifiers, relevant Lean names and revision details. The reader does not submit the issue, alter evidence, or include private statement text.

Both settings are saved in `machinechecked.links.json` (a full assessment sets `issues` and `site_url` under `[project]`). There is no default: reports go to the repository the audit names, which is the audit author's choice, and without one the reader offers only **Copy link**. A report is a question for the audit's author; it changes no status.

## Troubleshooting

| Problem | What to do |
|---|---|
| No Lake project found | Run the command inside the Lean repository (or one of its subdirectories). |
| Missing built modules | Run `lake build` for the necessary library targets and reopen the reader. |
| No paper found | Pass the exact `.tex` or `.pdf` path. |
| Multiple LaTeX roots | Choose the correct root or pass its path. |
| `lake` not found | Install elan and put `~/.elan/bin` on `PATH`. |
| On Windows | MachineChecked runs, but LaTeX then runs without the CPU-time and file-size limits it has on Linux and macOS (only a 30-minute timeout). For a paper you did not write, use WSL. |
| TeX compilation fails | The reader still opens from the paper's PDF if there is one, and names the LaTeX error. A paper that needs XeLaTeX should say so with `% !TEX program = xelatex`, a `latexmkrc`, or by loading `fontspec`/`unicode-math`. |
| A marker is approximate (dashed) | Numbered environments in LaTeX are placed exactly. Claims recorded by line are placed by SyncTeX, and claims from a PDF by their headings; both are approximate, and a claim whose place is ambiguous is left unplaced instead of guessed. |
| A PDF statement is missing | It probably has no bold heading the PDF reader recognises (see above); give the LaTeX source if you have it. |
| Reader is read-only | A hosted site or standalone HTML cannot save links to your local repository; run `machinechecked view` locally to edit. |

For independent review, continue with the [Review guide](REVIEWING.md). For locked specifications and formal acceptance policies, see [Full assessment](ASSURANCE.md).
