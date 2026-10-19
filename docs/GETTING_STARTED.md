# Getting started

MachineChecked opens your paper beside its Lean formalisation. It runs in your Lean project,
saves generated data in `.machinechecked/`, and records confirmed links in `machinechecked.links.json`.

Use `view` to explore, `build` to share a reader, and `check` to inspect proof results in automation.

## Before you start

You need a Lean project with a `lakefile`, Python 3.11 or later, and a working Lean toolchain (usually installed with [elan](https://github.com/leanprover/elan)). Build the Lean modules you want to inspect:

```sh
lake build
```

MachineChecked reads the built declarations and reports which modules need building.

For a LaTeX paper, install TeX Live with `latexmk`. Some papers also need `xelatex` or `lualatex`. For a PDF, install Poppler (`pdftohtml`, `pdfinfo`). The web reader is included.

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

After installing, pass a specific paper when useful. With `uvx`, prefix each command with `uvx`:

```sh
machinechecked view paper/main.tex
machinechecked view paper/main.pdf
```

MachineChecked looks for a root LaTeX document first, otherwise a PDF. If several candidates remain, it lets you choose. Leanblueprint projects can use their existing `\lean{...}` tags; `blueprint/src/print.tex` is the paper, and an engine the blueprint's `latexmkrc` names is used (the engine name is read from the file).

## Papers that are only a PDF, or at a URL

A paper can be a URL: `machinechecked view https://…/paper.pdf` downloads it once into `.machinechecked/papers/`.

LaTeX environments supply statement boundaries. For PDFs, MachineChecked detects bold numbered
headings and estimates each statement’s end at the next proof, section or statement. PDF detection
requires a text layer and recognisable headings. The reader marks these locations as approximate.

## Projects with a formalization.yaml

MachineChecked reads an existing [`formalization.yaml`](https://github.com/mathlib-initiative/formalization.yaml):

- its formalised sources are offered as papers;
- the mappings in its `alignment` (in the shape `statements: [{source, lean}]`) become links, labelled *formalization.yaml*: attributed to the project; a row's `note` is shown beside the claim's links as the project's note;
- its review status and counts appear as the project’s reported metadata.

When the file names several sources, a mapping is used for a paper only if it names that paper by a word distinctive to its title.

Build the Lean project to check its linked declarations.

The reader opens on the paper. Select a numbered statement in the contents or its margin marker.
The panel shows **Paper**, **Readable Lean** and **Exact Lean**. **Expand comparison** gives
these representations the full workspace, keeping every hypothesis visible. On a phone they
follow one another in reading order. The exact statement comes directly from Lean; rebuilding
an older audit adds it.

Click a variable to see its type and conditions. Click an expression to select it; further clicks
widen the selection. Dotted names open short mathematical notes. A Lean declaration name opens
its complete definition; **Back** and browser Back restore the claim view and reading position.
Definition links can be copied or opened in another tab.

Click the evidence summary for proof checks, reviews and provenance. The ⋯ menu contains
**Copy link**, **Report issue** and **Review it**; reviewing opens the selected claim.

The paper toolbar provides page navigation, fit/zoom, text search and **Open original PDF**.
PDF text can be selected and copied. The claim markers occupy the margin.

## Connect a claim to Lean

MachineChecked suggests declarations from `\lean{...}` tags, docstrings and similar names.
Confirm a candidate to save the association.

You can:

- **Link** a suggested declaration;
- choose **Not this** to reject the suggestion;
- search the project's declarations to choose another.

The local reader saves your decisions in `machinechecked.links.json` at the repository root and refreshes the view. Commit that small file if you want the associations to travel with the project.

A link records the declaration associated with a claim. A correspondence review compares their
assumptions, definitions and conclusion; see [Reviewing](REVIEWING.md).

**Coverage notes.** An auditor who has compared a claim with its declarations can say how far
they state it, in the claim's entry of `machinechecked.links.json`:

```json
"lemma-8.6": {"lean": ["Proj.inverse_bound", "Proj.inverse_solves"],
              "coverage": "changed", "confidence": "high",
              "note": "The bound needs n + 5 derivatives where (8.19) has m + 4.",
              "by": "A. Auditor"}
```

`coverage` is `full` (the declarations together state every clause), `partial` (some clauses
have no counterpart), `changed` (a clause is stated with other hypotheses, bound or setting) or
`related` (a comparable result); `confidence` is `high`, `medium` or `low`. The reader shows the
note under the claim's status, as the auditor's reading, and `check --json` reports it as the
claim's `correspondence`. A note changes no status, and linking other declarations in the reader
removes it, since it described the old ones.

## Read a claim

Select a claim to see the printed statement beside its Lean statement, set out as its variables, its hypotheses in order, and its conclusion. A “there is” inside the conclusion shows its witness with its type, and the parts that use that witness beneath it; two witnesses of the same name in different parts are different variables. When the project's repository is on GitHub, **Lean source** opens the declaration at the exact commit and line. Where a corrected statement stands beside the printed one, a box says what the correction changes: the hypotheses it adds or drops, and whether the conclusion is the same. **Review it** opens the review queue, and **Raise issue** a report to the audit's repository.

## Interpret the status

- **Not linked / suggested:** no confirmed correspondence.
- **Linked, proof checked:** Lean accepts the named formal theorem, subject to its axioms.
- **Linked, Lean definition:** the link is to a definition, which introduces a mathematical object.
- **Linked, Lean not checked:** the project, or the declaration's own module, is not built, so Lean has not been run on it here. A project can be partly built: what is built is checked, and each link says whether its module is.
- **Linked, Lean name is ambiguous:** several modules declare the same name (a statement left as a challenge and its solution, for instance). Name the intended module in the `formalization.yaml` row (`module: …`). Each Lean library is inspected in its own Lean session, so libraries that cannot be loaded together are handled; a module MachineChecked cannot load at all is reported as such, with the loading error.
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

The directory carries `audit.json`: the public paper identifier, audited revision, Lean project
commit, publisher and data location. Sites such as machinechecked.org use it to load the audit.
Review the exported paper and Lean statements before publishing.

To check the linked declarations in automation:

```sh
machinechecked check
```

The command exits with an error when a linked declaration is missing or unproved.

Generated files in `.machinechecked/` are Git-ignored. Use `--out` to save the HTML elsewhere.
The bundle contains the paper and Lean statements; share it with an appropriate audience.

## Build on your own CI, and save the build

A large project can take hours to build. Two things save that time, both on your own resources:

**A saved build.** After `lake build`, `machinechecked cache save` archives the build output (not Mathlib's, which `lake exe cache get` supplies) with a manifest: the commit, Lean version, platform, dependencies, and every file's SHA-256. `machinechecked cache publish OWNER/REPO` uploads it, with your project's `LICENSE` and `NOTICE`, to a `build-cache` prerelease of that repository; set `MACHINECHECKED_GH_TOKEN` to a token that can write releases there. Anyone can then restore it:

```sh
machinechecked cache restore OWNER/REPO --build    # minutes instead of hours
```

Restore picks a saved build with the same Lean inputs (whatever the clone's folder or history, shallow or rewritten), else the nearest one of an earlier commit (which needs the history: `fetch-depth: 0` with `actions/checkout`), always with the same Lean version, platform and dependencies; it checks every SHA-256 and unpacks it; `--build` then runs `lake build --rehash`, which rebuilds exactly what changed since. A mismatched, incomplete or corrupt archive is refused, and the build happens from source. Before downloading, restore checks that the archive and its unpacked build fit on the disk, and says how much space it needs if they do not; it unpacks into a staging folder and moves the files into place only when the whole archive is read, so a failed restore leaves the build as it was. `--from DIR` restores from a folder of saved archives instead. `machinechecked cache prune OWNER/REPO --keep N` deletes all but the newest `N` saved builds of each package, platform and Lean version. A restored build supplies compiled artifacts. Comparator supplies independent kernel replay.

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

The workflow uses your repository’s GitHub Actions runners and build cache.

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

This opens a prefilled GitHub issue *draft* with claim identifiers, relevant Lean names and revision details. Review the draft on GitHub and submit it there.

Both settings are saved in `machinechecked.links.json`; full assessments use `[project]`.
The configured `issues` repository receives reports. **Copy link** is available for every claim.

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
