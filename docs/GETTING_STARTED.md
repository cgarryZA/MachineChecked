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

## Open a PDF or a paper at a URL

A paper can be a URL: `machinechecked view https://…/paper.pdf` downloads it once into `.machinechecked/papers/`.

LaTeX environments supply statement boundaries. For PDFs, MachineChecked detects bold numbered
headings and estimates each statement’s end at the next proof, section or statement. PDF detection
requires a text layer and recognisable headings. The reader marks these locations as approximate.

## Use a formalization.yaml

MachineChecked reads an existing [`formalization.yaml`](https://github.com/mathlib-initiative/formalization.yaml):

- its formalised sources are offered as papers;
- the mappings in its `alignment` (in the shape `statements: [{source, lean}]`) become links, labelled *formalization.yaml*: attributed to the project; a row's `note` is shown beside the claim's links as the project's note;
- its review status and counts appear as the project’s reported metadata.

When the file names several sources, a mapping is used for a paper only if it names that paper by a word distinctive to its title.
A library whose namespace the file maps only to other papers is not indexed for this paper: its
suggestions, search and paper-number checks cover the paper's own libraries, and the reader's
notes name the libraries left out. A module of such a library is still indexed when it could
hold a name the paper links: its source uses one of the name's words (a part of the name between
dots, or the start of one up to an underscore, in any case) or an attribute that renames
declarations, such as `to_additive`. Every library is indexed when a linked name is one Lean
gives an instance (`inst…`), or when the project defines its own commands. A link into the
other library is therefore checked there, and a name both libraries hold reads ambiguous, as
with every library indexed ([evidence policy](EVIDENCE_POLICY.md) names the case this does not
detect). `machinechecked compare --query search TEXT --all-libraries` searches every library,
and `machinechecked inspect NAME` reaches any declaration.

Build the Lean project to check its linked declarations.

## Select a claim

The reader opens on the paper. Select a numbered statement in the contents or its margin marker.
The panel shows **Paper**, **Readable Lean** and **Exact Lean**. **Expand comparison** gives
these representations the full workspace, keeping every hypothesis visible. On a phone they
follow one another in reading order. The exact statement comes directly from Lean; rebuilding
an older audit adds it.

An object whose type is a subtype, structure or class shows the properties its type carries,
as they apply to it, with the field and structure each comes from: for a given object they are
part of what is given, for a witness they are established with it, and for an object inside an
assumption, a negation or one alternative they stay inside it. An assumption that is a class of
propositions shows what its fields state. **Exact Lean** lists each carried property as the Lean
term that gives it (`s.start : s.path 0 = d`) with its field's declaration; many fields are
folded under a summary.

Click a variable to see its type and conditions. Click an expression to select it; further clicks
widen the selection. Dotted names open short mathematical notes. A Lean declaration name opens
its complete definition; **Back** and browser Back restore the claim view and reading position.
Definition links can be copied or opened in another tab.

A definition shows what it says: its parameters, in their order and as they are written, and its
body; a definition by pattern matching or recursion shows the equations Lean derives for it
(its equation theorems), each under its own variables. **Exact Lean** shows the authored source
of the definition, the exact statement of each equation theorem and the elaborated value; the
compiled form of a recursive definition is folded under **Compiled value**.

A definition applied in a statement expands where it stands: after the expression, **expand**
lists its applications of the project's definitions. Choosing one shows the arguments, by the
definition's parameters, and the definition at those arguments: its body with them substituted,
or the equations that apply to them with any case condition and the equation theorem's name.
Lean performs the substitution and checks it. Applications inside an expansion expand in turn.

**Used by**, under a declaration, lists the declarations that refer to it and how (in their
statement, proof or definition body); a user opens like any declaration, so a specialised lemma
leads to the general result that applies it. In the reader `view` serves, **Show each
application** asks Lean for every application: the argument supplied for each binder, whether
the caller assumes each premise or proves it (and with what), and the conclusion obtained. From
a terminal: `machinechecked inspect NAME --used-by`, or `machinechecked compare --query uses
NAME --json`.

**How the main results use a declaration.** `machinechecked compare --query impact NAME` traces
NAME from each main result of the paper. The main results are the declarations linked to the
paper's theorems, shown as a suggestion; `--main` chooses them instead (a declaration, or a claim
for its linked declarations; repeat it for several). Each main result has its own answer: *used
by its proof*, *in its statement only*, *formalized separately: not used by this main result*,
or *not traced*. A use comes with the shortest path of Lean references from the main result to
NAME, direct or through other declarations, and with the applications of NAME at the end of a
proof's path: their arguments, each premise with how it is supplied, and the result. Importing a
module is not a use. A trace that reaches a module not built or not loaded reads *not traced*
and names the module. The answer also lists the claims whose linked Lean uses NAME: a difference
between NAME and the paper can matter only to these.

The trace is a fact about the Lean terms of the build. *Formalized separately* describes the
Lean: the declaration keeps its own correspondence review, and no status changes. Whether a
difference matters at a use (say the lemma's Lean needs one more derivative than the paper
prints, and the main proof needs only finitely many) is a reviewer's judgement: record it as a
finding in a workspace, attributed to you ([saved investigations](REVIEWING.md#saved-investigations)).

Click the evidence summary for proof checks, reviews and provenance. The ⋯ menu contains
**Copy link**, **Report issue** and **Review it**; reviewing opens the selected claim.

The paper toolbar provides page navigation, fit/zoom, text search and **Open original PDF**.
PDF text can be selected and copied. The claim markers occupy the margin.

## Connect a claim to Lean

MachineChecked suggests declarations by what they state. It compares the claim's printed
statement with every declaration of the project, linked or not: the complete Lean statement,
its docstring, its name and the definitions the statement uses. A docstring citing the claim's
number and a name resembling its label also count, for less. Each suggestion lists its reasons:
the terms it shares with the claim and where they occur, a citation of the claim's number, a
close match its proof uses (a wrapper of a helper, say), and a difference in the order of `∀`
and `∃`. Confirm a candidate to save the association.

You can:

- **Link** a suggested declaration;
- choose **Not this** to reject the suggestion;
- search the project's declarations by statement, symbols or name, or with **Search with this
  claim**, and link another. Open a result to read its complete statement.

The search box at the top of the reader finds declarations by their statements too.

### Paper numbers in the Lean

`view`, `build` and `check` read every reference to a numbered statement or section in the
project's docstrings, declaration names and module docstrings (`Theorem 2.1`, `lemma_3_4`), and
compare it with the paper read here:

- the paper has that statement;
- the number belongs to another kind of statement (`Lemma 3.3` where the paper's 3.3 is a
  proposition);
- this version of the paper has no statement with that number;
- the paper's numbering is not completely known (a PDF read by its headings), so it is not
  checked;
- the reference is to another work, or in a namespace the project maps to another paper.

A reference is to another work when a citation follows its number (`Theorem 4.1 of [Gauss]`,
`Lemma 9 [AB]`, `Lemma 9~\cite{AB}`, `Lemma 9 of ref. [3]`, `of *An Introduction*`), with a
work's authors (`Theorem 3 in Hardy and Wright`, `of Gauss (1801)`, `in Smith et al.`,
`in Serre's book`, `of Serre, *A Course in Arithmetic*`) or another paper (`of Paper B`), or
when a citation comes just before it: an open citation bracket (`[AB, Lemma 9]`), `et al.`, an
author's possessive (`Gauss's Lemma 4.22`, `[AB]'s Lemma 9`, `Smith et al.'s Theorem 3`), or a
chapter after a comma, as a book's citation gives it (`Hardy–Wright, *An Introduction*, Ch. IV,
Prop. 4.7`). A possessive of the paper, a part of it or the Lean (`the paper's Lemma 2.1`,
`Lean's Theorem 2.1`), a part of the paper or the Lean after the number
(`Lemma 7.7 in Section 7`, `from Appendix A`, `in Figure 2`, `in Eq. (4)`, `in Proof of
Lemma 3`, `in Lean`), the paper itself (`of the Paper`), a mathematical term or an ordinary
word after it (`in Hilbert spaces`, `in refined form`, `in reference to Lemma 2`), one name
alone with no year, title or citation (`in Rudin`), a possessive earlier in the sentence
(`By Gauss's lemma and Lemma 2.1`) and a chapter in prose (`In Chapter 4, Lemma 4.2`) leave
the reference checked against the paper. A citation after the part names another work
(`Lemma 4.1 in Section 4 of [AB]`).

Digits that run together in a name (`lem41_bound`, or `Assumption22` written as an
identifier in a docstring) are read in every way the paper could mean them, `4.1` and `41`: the
reading the paper has a statement of that kind for is checked, a name whose readings the paper
has several of is left unchecked, and the name disagrees with the paper only when no reading
fits. A number written in prose (`Lemma 41`) is read as written.

A declaration's name and its docstring's opening citation (`/-- Theorem 3.1. … -/`) name what
the declaration states. When that number exists but the declaration reads much closer to
another statement, the reference is named as a possibly stale lead, with the closer statement.
A later citation in the docstring (`under Assumption 2.2`) names what the statement relies on,
and is checked only for the number and kind it cites. `check` prints each disagreement
with its file and line. When several references disagree, the reader's notes say that the Lean
appears to follow another version of the paper, and suggestions then rank content further
above cited numbers. None of this links a declaration or changes a status. A full assessment
(a project with a `machinechecked.toml`) checks the same references, each against the paper it
belongs to when there are several ([ASSURANCE.md](ASSURANCE.md)).

### Save and record links

The local reader saves your decisions in `machinechecked.links.json` at the repository root and refreshes the view. Commit that small file if you want the associations to travel with the project.

The same from a terminal, with the same checks and no Lean run (it resolves names against the
last `view` or `build`):

```sh
machinechecked link "Lemma 2.3" Example.inverse_bound Example.inverse_solves \
  --coverage changed --confidence high --note-file note.md --as "A. Auditor"
machinechecked link "Theorem 4" --coverage full --basis reviewed_composition \
  --argument-file argument.md          # also --bridge THEOREM TARGET, --question, --would-decide
machinechecked link "Lemma 2.3" --reject Example.other --reason "a different estimate"
machinechecked link "Lemma 2.3" --clear     # the paper's \lean tags apply again
```

A claim is named by its id, its key (`lem:bound`) or its number; a number two claims share, or a
name the build does not have, is refused with the candidates, and nothing is written. A
declaration whose module is not built is recorded and reads as such until it is built.
`--dry-run` shows the change and `--json` prints it as one document.

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

`coverage` says how far the claim and the declarations agree: `full` (every clause), `partial`
(some clauses have no counterpart), `changed` (a clause is stated with other hypotheses, bound or
setting), `related` (a comparable result) or `unresolved` (an open question). `confidence` is
`high`, `medium` or `low`. The reader shows the reading under the claim's status, as the
auditor's, and `check --json` reports it as the claim's `correspondence`. A reading changes no
status. It describes the declarations it was written for: when the list changes, it moves to
`earlier_notes` in the file and is no longer shown. A value other than these is ignored.

**How the coverage is supported.** The optional `basis` records it separately from the coverage
itself. Three claims of the synthetic project `tests/fixtures/coverage` show the three bases of
full coverage:

```json
"thm:two":   {"lean": ["Cover.even_add"], "coverage": "full", "basis": "direct"},
"thm:four":  {"lean": ["Cover.even_add"], "coverage": "full",
              "basis": "reviewed_composition",
              "argument": "Apply Cover.even_add to a and b, to c and d, then to the two sums."},
"thm:three": {"lean": ["Cover.three_even"], "coverage": "full", "basis": "checked_bridge",
              "bridge": {"theorem": "Cover.three_even", "target": "Cover.Spec.three_even",
                         "target_fingerprint": "…", "source_sha256": "…"}}
```

- `direct`: the linked declarations state the claim. The reader shows **States every clause**.
- `reviewed_composition`: the claim follows by combining the linked declarations through the
  auditor's `argument`. The reader shows **Every clause, by the auditor's composition**, with the
  argument, its author, and that Lean has not checked the combination. Beside it the reader and
  `check` give the next step: state the combination as one Lean result. A composition never reads
  as a direct result. A stored `"coverage": "composed"` reads as `full` with this basis, its note
  as the argument.
- `checked_bridge`: a linked theorem whose type Lean checks is exactly `target`, a proposition
  stated as a definition, which the auditor read against the paper. The reader shows **Every
  clause, through a checked bridge** only when that check passes, the proof has no `sorry` and only
  the standard axioms, and the target and the paper's passage are the versions the auditor read:
  `target_fingerprint` and `source_sha256` pin them, and `check --json` gives their current values
  (`correspondence.bridge.current`) to copy. A changed target, a change to a definition it uses, or
  a changed passage reads as out of date until the auditor reads it again and updates the pins.

`refs` may list the linked declarations a basis rests on (all of them by default). Without a
`basis`, the reading reads **Every clause**, and its support is not recorded.

An `unresolved` reading records the question and what would decide it:

```json
"thm:double": {"lean": ["Cover.even_two_mul"], "coverage": "unresolved",
               "question": "Does 'number' mean a natural number or an integer?",
               "would_decide": "The paper's standing conventions."}
```

The reader shows **Unresolved** with the open question and what would decide it.

## Link a proof step

A numbered equation inside a printed proof is a target of its own. In zero configuration,
every numbered display with one `\label` inside a `proof` environment is listed as **Equation (n)**
under the result whose proof holds it (the result the proof's optional argument names, else the
statement just before the proof). Its passport shows the equation, its context in the proof and
its own review; the enclosing result lists its steps. A context kept only in part is marked
**(cut)**, with the line where it was cut.

A step is linked in two ways, kept apart:

- **Lean that establishes this step**: the declarations that state the step as printed, with the
  same `coverage`, `basis` and `note` as a statement's link;
- **Different formal route used instead**: the declarations that reach the enclosing result by
  another argument and do not state the step.

The local reader saves both in the step's entry of `machinechecked.links.json`:

```json
"eq:bound-range": {"route": {"lean": ["Toy.Acceptance.thm_bound"],
                             "note": "Lean bounds n by n * n and does not use the printed family.",
                             "by": "A. Auditor"}}
```

From the terminal, `machinechecked link` records both (the step by its label or number):

```sh
machinechecked link eq:bound-sum Toy.Acceptance.thm_triangle --coverage full
machinechecked link "Equation (3)" Toy.Acceptance.thm_bound --route --note "Lean bounds n by n * n."
machinechecked link eq:bound-range --route        # clears the recorded route
```

A row of `formalization.yaml` can name a step (`source: Equation (3)`) and, with
`route: different`, its formal route. A step linked only to a formal route reads **linked: a
different formal route** (in the warning colour: Lean reaches this by a different route than the
printed step); nothing is suggested for a step. A step never takes its enclosing
result's status, coverage or review: until a reviewer reports on it, it reads **not reviewed**.
In a full assessment, a step is an inventory entry with `unit` and `parent` (see the
[data model](DATA_MODEL.md)).

## Compare the printed and Lean statements

Select a claim to see the printed statement beside its Lean statement. For a LaTeX paper the statement is typeset from its source when the whole passage can be, under the paper's own macros and with its printed reference and equation numbers; otherwise it is the excerpt of the PDF, which is always available under **As printed in the PDF** ([what decides](SOURCE_REGIONS.md#display-excerpts)). The Lean statement is set out as its variables, its hypotheses in order, and its conclusion. A “there is” inside the conclusion shows its witness with its type, and the parts that use that witness beneath it; two witnesses of the same name in different parts are different variables. When the project's repository is on GitHub, **Lean source** opens the declaration at the exact commit and line. Where a corrected statement stands beside the printed one, a box says what the correction changes: the hypotheses it adds or drops, and whether the conclusion is the same. **Review it** opens the review queue, and **Report issue** a report to the audit's repository.

## Interpret the status

- **Not linked / suggested:** no confirmed correspondence.
- **Linked, proof checked:** Lean accepts the named formal theorem, subject to its axioms.
- **Linked, Lean definition:** the link is to a definition, which introduces a mathematical object.
- **Linked, Lean not checked:** the project, or the declaration's own module, is not built, so Lean has not been run on it here. A project can be partly built: what is built is checked, and each link says whether its module is.
- **Linked, Lean name is ambiguous:** several modules declare the same name (a statement left as a challenge and its solution, for instance). Name the intended module in the `formalization.yaml` row (`module: …`). Each Lean library is inspected in its own Lean session, so libraries that cannot be loaded together are handled; a module MachineChecked cannot load at all is reported as such, with the loading error.
- **Incomplete (`sorry`):** the formal proof has unfinished obligations.
- **Further axioms:** the proof relies on axioms beyond the default allowlist.
- **Definition / declaration not found:** the linked item is not a checked theorem or cannot be resolved from the built modules.

MachineChecked keeps what Lean reported in `.machinechecked/`, so the next `view`, `build` or `check` asks Lean again only about modules that changed (and the modules that import them). Linking a claim, writing a note or editing the paper starts no Lean session. `machinechecked build --reuse-lean` builds from what is kept alone, and names what Lean must be asked when that is not enough. A module that Lean reports an error in stays unindexed until the project's Lean files, toolchain or Lake manifest change; a module that could not be loaded for want of memory or time, or because the Lean session was stopped, is tried again on the next build.
`machinechecked build --refresh` asks Lean again for everything the build reads (the index of
each module, the records of linked and suggested declarations, the modules recorded as failing
to load) and keeps the new answers in place of the old; `inspect` answers and the facts of other
papers' libraries stay. When nothing changed, it gives the statuses that reusing them gives.

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

The directory carries `audit.json`: the public paper identifier, the version of the paper it
pins, audited revision, Lean project commit, publisher and data location. Sites such as machinechecked.org use it to load the audit.
Review the exported paper and Lean statements before publishing.

To check the linked declarations in automation:

```sh
machinechecked check
```

The command exits with an error when a linked declaration is missing or unproved.

It also warns, with the file and line, about each name a module docstring lists that the project and its dependencies do not declare: a dotted name such as `Widget.foo_le_bar`, or the name a list item begins with under a "Main …" heading. A deleted or renamed declaration often leaves such a name behind. Names resolve as in Lean, through the namespaces the file enters and opens. A module or namespace written in full (`Example.Shapes.Widget`) is accepted; a shorter name that reaches only a module or a namespace gets its own warning. A declaration or module of the same library counts even when the project does not import it. A name Lean generates (a projection, a constructor, a derived instance) counts when a built module holds it, in a library the paper's index leaves out too. The reader's banner lists them too. A warning does not change the exit code.

Generated files in `.machinechecked/` are Git-ignored. Use `--out` to save the HTML elsewhere.
The bundle contains the paper and Lean statements; share it with an appropriate audience.

## Build in your own CI and save the build

A large project can take hours to build. Two things save that time, both on your own resources:

**A saved build.** After `lake build`, `machinechecked cache save` archives the build output (not Mathlib's, which `lake exe cache get` supplies) with a manifest: the commit, Lean version, platform, dependencies, and every file's SHA-256. `machinechecked cache publish OWNER/REPO` uploads it, with your project's `LICENSE` and `NOTICE`, to a `build-cache` prerelease of that repository; set `MACHINECHECKED_GH_TOKEN` to a token that can write releases there. Anyone can then restore it:

```sh
machinechecked cache restore OWNER/REPO --build    # minutes instead of hours
```

Restore picks a saved build with the same Lean inputs (whatever the clone's folder or history, shallow or rewritten), else the nearest one of an earlier commit (which needs the history: `fetch-depth: 0` with `actions/checkout`), always with the same Lean version, platform and dependencies; it checks every SHA-256 and unpacks it; `--build` then runs `lake build --rehash`, which rebuilds exactly what changed since. A mismatched, incomplete or corrupt archive is refused, and the build happens from source. Before downloading, restore checks that the archive and its unpacked build fit on the disk, and says how much space it needs if they do not; it unpacks into a staging folder and moves the files into place only when the whole archive is read, so a failed restore leaves the build as it was. An archive saved before archives were named after the Lake package unpacks into the project and its path dependencies whatever the case of their folders' names, and is refused if it holds anything else. `--from DIR` restores from a folder of saved archives instead. `machinechecked cache prune OWNER/REPO --keep N` deletes all but the newest `N` saved builds of each package, platform and Lean version. A restored build supplies compiled artifacts. Comparator supplies independent kernel replay.

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

## Publish an audit of each paper version

An audit pins one version of its paper: a published version (`published = "arXiv:2601.01234v1"`, labelled "arXiv v1") or an unpublished manuscript at a commit (`version = "manuscript"` with the source's `rev`, labelled "Latest manuscript (commit abc1234)"). The [full assessment guide](ASSURANCE.md) says how to declare it; `build` refuses an audit whose claim inventory is pinned to another version. When some claims carry no pin, the version is shown as declared by the author and not checked against the claims.

To publish an audit of each version side by side, keep the configuration of each on its own Lean ref (for example a branch `audit-v1` holding the published version's configuration, and `main` for the latest manuscript), and call the workflow once per audit with `ref` and `subpath`. Each call uploads its audit under that subpath; one deploy job merges them into one GitHub Pages site, at `/v1/` and `/latest/`:

```yaml
# .github/workflows/machinechecked.yml in your repository
on: { push: { branches: [main] }, workflow_dispatch: }
jobs:
  v1:
    uses: cgarryZA/MachineChecked/.github/workflows/audit.yml@main
    with: { ref: audit-v1, subpath: v1, tex: true }
  latest:
    uses: cgarryZA/MachineChecked/.github/workflows/audit.yml@main
    with: { subpath: latest, tex: true }
  deploy:
    needs: [v1, latest]
    runs-on: ubuntu-24.04
    permissions: { pages: write, id-token: write }
    environment: github-pages
    steps:
      - uses: actions/download-artifact@v8
        with: { pattern: machinechecked-audit*, merge-multiple: true, path: site }
      - uses: actions/upload-pages-artifact@v5
        with: { path: site }
      - uses: actions/deploy-pages@v5
```

A deploy replaces the whole site, so every run builds every audit; a saved build (`cache-repo`) keeps the frozen one quick. Each audit's `site_url` (in the configuration on its ref) is its own address, such as `https://you.github.io/project/v1/`.

A paper page that lists audits of several versions gives each version its own page, and the reader a drop-down beside the formalisation selector to switch between them ([data model](DATA_MODEL.md)). Each version keeps its own PDF, claim numbers and statuses.

When the site relates the claims of two versions, a claim says what it became in the other version and links to it: "Theorem 3 in Latest manuscript (commit abc1234), statement changed", "Lemma 1 in arXiv v1, renumbered", or "Removed in Latest manuscript (commit abc1234)".

In the panel beside the paper, each audit names the version it pins and its commit. **Open the audit** opens the audit of the version shown; audits of other versions link to their own version's page.

## Read a paper with several audits

On machinechecked.org, a paper version with audits from several Lean projects opens with all of them, under **All audits** in the formalisation selector:

- Each claim shows the evidence of the default audit: the audit whose repository has the most GitHub stars (or the first listed, when the site has no star counts).
- A claim the default audit does not map shows the evidence of the next audit, by stars, that maps it. The claim panel names that audit's author, repository and commit, and the contents list marks the claim with its repository.
- Each claim's status comes from one audit, named in the claim panel.
- Choosing one project shows only its evidence. A claim its audit does not map is marked **Not in this audit**.

Audits are shown together only on the page of the paper version they pin.

## Add a badge to your README

Once your paper is listed on machinechecked.org (a repository whose `formalization.yaml` names an
arXiv paper is listed within a day), its page has a badge that says how far the site's knowledge
of it goes ("Lean repository linked", or "audit published"):

```md
[![MachineChecked](https://machinechecked.org/papers/2601.01234/badge.svg)](https://machinechecked.org/papers/2601.01234/)
```

Use your paper's arXiv identifier.

## Share a claim or report a problem

A claim has **Copy link**, which copies its permanent address when the site is hosted. On an unhosted local copy, it copies a claim reference instead.

To enable **Report issue**, launch the reader with a repository for reports and the eventual public address:

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
| "the Lean probe's output is incomplete" | The probe's output was cut short, usually by a full disk; the message names the file, the line and the free space. Free space under `.machinechecked/build` and build again. To inspect the partial output, set `MACHINECHECKED_KEEP_PROBE=1`: it is then kept in `.machinechecked/build`. |
| On Windows | MachineChecked runs, but LaTeX then runs without the CPU-time and file-size limits it has on Linux and macOS (only a 30-minute timeout). For a paper you did not write, use WSL. |
| TeX compilation fails | The reader still opens from the paper's PDF if there is one, and names the LaTeX error. A paper that needs XeLaTeX should say so with `% !TEX program = xelatex`, a `latexmkrc`, or by loading `fontspec`/`unicode-math`. |
| A marker is approximate (dashed) | Numbered environments in LaTeX are placed exactly. Claims recorded by line are placed by SyncTeX, and claims from a PDF by their headings; both are approximate, and a claim whose place is ambiguous is left unplaced instead of guessed. |
| A PDF statement is missing | It probably has no bold heading the PDF reader recognises (see above); give the LaTeX source if you have it. |
| Reader is read-only | A hosted site or standalone HTML cannot save links to your local repository; run `machinechecked view` locally to edit. |

For independent review, continue with the [Review guide](REVIEWING.md). For locked specifications and formal acceptance policies, see [Full assessment](ASSURANCE.md).
