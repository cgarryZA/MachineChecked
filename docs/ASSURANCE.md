# Full assessment

Full assessment tracks formal proofs, correspondence reviews, source verification and independent
kernel replay for a pinned paper revision. Configure it with `machinechecked.toml`.

It requires a stable claim inventory, closed Lean specifications written from the paper, acceptance theorems, and review records. Existing acceptance systems can supply these records.

## Configure the project

Place `machinechecked.toml` in the working directory, or pass it with `-c`:

```toml
[project]
name = "my-paper"
lean_root = "."
modules = ["MyPaper"]
scope_roots = ["MyPaper"]
spec_prefix = "MyPaper.PaperSpec"
accept_prefix = "MyPaper.Acceptance"
inventory = "claims.json"
reviews = ["reviews/statements.md", "reviews/definitions.md"]
statement_authors = ["me"]
ai_reviewers = ["claude*"]
notation_macros = ["R", "E"]  # optional: notation whose definitions readings record

[review]
check = "python3 tools/check.py"  # optional post-promotion check

[[paper]]
id = "A"
title = "My paper"
source = { path = "paper" }
root = "main.tex"
publish = { pdf = false, source_text = false, lean = false, reviews = false }
```

`spec_prefix` and `accept_prefix` name the modules of the statement layer and of the proof layer. A project whose layers span several namespaces, for example its own and those of a formalisation it builds on, lists them: `spec_prefix = ["MyPaper.PaperSpec", "Base.PaperSpec"]`. A specification or acceptance theorem under any listed prefix is in its layer, and no statement module under any of them may import a proof module under any of them. List those namespaces in `scope_roots` too, so that the definitions they declare are hashed and reviewed.

The probe loads the modules listed in `modules` and what they import. A proposition, proof, witness or definition the inventory names outside them is a violation that names it, with the project module that declares it when its source shows one: list that module in `modules`, or import it from a listed one.

Sources can also be a pinned Git revision (`source = { git = "owner/repo", rev = "<commit>" }`, of which only that revision is fetched) or a versioned arXiv record (`source = { arxiv = "2601.01234v2" }`: its source is downloaded from arXiv once and kept in the working directory, so later builds work offline; the version is required). Say which public record the paper is with `published` (an arXiv identifier with version such as `"arXiv:2601.01234v2"`, a DOI, or a URL) and, if the audited revision differs from it, how with `note` (for example `"This revision corrects Proposition 2.3."`); both go into `audit.json` and the reader, and change no status.

**The version an audit pins.** An audit pins exactly one version of its paper, and `audit.json` names it (`paper_version`, see the [data model](DATA_MODEL.md)):

- **A published version**: `published = "arXiv:2601.01234v1"` (or an arXiv source). It is labelled "arXiv v1". The inventory is pinned to it by its identifier: `"papers": {"T": {"commit": "2601.01234v1"}}`, or a claim's `"commit"`.
- **An unpublished manuscript**: `version = "manuscript"` with the manuscript's commit as the source's `rev` (`source = { git = "owner/manuscript", rev = "<commit>" }`; a folder in the project may state its `rev`, checked against the folder's history when it is a repository of its own). It is labelled "Latest manuscript (commit abc1234)", never with a version number, even when `published` names the paper's earlier arXiv version. The inventory is pinned to that commit.

`build` refuses an audit whose inventory is pinned to another version than the one it declares (for example `published` says arXiv v1 while the claims are pinned to a later manuscript commit), before Lean runs. A paper that declares no version is described by its source's commit when the inventory agrees, and by nothing otherwise. To publish an audit of each version, see [several audits of one repository](GETTING_STARTED.md#several-audits-of-one-repository).

With multiple root TeX files, specify `root`. Without LaTeX, MachineChecked falls back to the paper's PDF and labels the weaker source evidence.

A paper published as a PDF is configured with `source = { path = "…" }` and `pdf = "paper.pdf"` (no `root`); its numbered statements are found by their bold headings, and any the headings miss can be placed by hand in `anchors.json`. To meet the release gate's source condition, pin the PDF with `pdf_sha256 = "<its SHA-256>"`: the gate then checks the hash, requires every claim in scope to be found, and states that the source is a PDF with approximate claim positions.

Under `[project]`, `author` is the name the audit is published under, `issues` the GitHub repository where Raise issue opens reports, `site_url` the published reader's address, and `repository` the GitHub repository of the Lean source when it is not the project's `origin` remote. `repository_private = true` keeps the repository's name out of the reader's text; its Lean source links still name it, and open only for people with access.

Optional configuration includes `dismissals` (documented advisory warnings), `comparator_log` (a structured replay record) and `display` (a text-only display overlay). `machinechecked replay CONFIG` runs Comparator with its configuration (`lake env comparator CONFIG`, so Comparator must be installed) on a commit whose Lean inputs have no uncommitted changes, and writes the record to `comparator_log`: the commit, the Lean version and the Lake manifest's hash, whether it passed, and the theorems it replayed. Comparator's trust model also asks for a checking environment in which the solution was not compiled before, `landrun` on `PATH`, and the whole run under the sandbox guard `systemd-run --user --property=RestrictAddressFamilies=~AF_UNIX`. `replay` starts that guard itself when the machine has `systemd-run` and a user systemd manager that applies it (it checks that a Unix socket cannot be opened inside the guard), and runs Comparator directly when it is already under the guard; `--no-guard` opts out. A replay without the guard still counts as replay evidence: the reader shows it as "replayed without the sandbox guard", and `check`, `build` and exports say so too. A record made before `replay` recorded its conditions shows "sandbox guard not recorded". The record's `conditions` say how the run went: `guard` (`RestrictAddressFamilies=~AF_UNIX` or `none`), `guard_mode` (`started` by `replay`, `inherited` from the calling process, `unavailable` on this machine, or `opted-out`), the systemd unit, the kernel's Landlock ABI, and the path, SHA-256 and (for Comparator built in its checkout) commit of `comparator`, `landrun`, `lean4export` and, when enabled, `nanoda_bin`. `replay` notes an unguarded run, or a missing `landrun`, on its output. The assessment counts it for that commit and environment, and for a later commit when the record's commit is its ancestor and no Lean input (sources, lakefile, manifest, toolchain) changed since, so the record can be committed to the project; a CI checkout then needs enough history to show it (`fetch-depth: 0`). Display overlays control presentation; the inventory and evidence control assessment.

## Map claims to specifications

The claim inventory lists each printed claim, its pinned source, scope and clauses. Example:

```json
{
  "id": "A:thm:main",
  "paper": "A",
  "kind": "theorem",
  "number": "Theorem 2.1",
  "title": "Main result",
  "label": "thm:main",
  "location": "main.tex",
  "source_sha256": "<hash>",
  "scope": "formal",
  "scope_note": "",
  "scope_reviewed": true,
  "clauses": [
    {
      "name": "as printed",
      "spec": "MyPaper.PaperSpec.thm_main",
      "accept": "MyPaper.Acceptance.thm_main",
      "witness": "MyPaper.Acceptance.thm_main_hypotheses"
    }
  ]
}
```

This is one claim entry inside `claims.json`. The acceptance theorem must have the specification’s **exact closed proposition** as its type.

Other clause fields include `refute` (a proof of the printed proposition's negation), `corrects` (which original clause a correction addresses), and `defs` for a definition claim.

A proposition with hypotheses and no `witness` (a theorem that meets them) carries a `witness` obligation, which names the hypotheses that need it. Instances of standard classes over the proposition's own variables (`[MeasurableSpace Ω]`, `[IsProbabilityMeasure P]`, `[InnerProductSpace ℝ F]`, `[NeZero N]`) have canonical instances, so a proposition whose only hypotheses are such instances gets a low-signal warning instead (code `witness-instances`), which lists the classes and can be dismissed like any warning. An instance of `Fact`, of a class of the project, or of a class applied to anything but a variable bound before it or a number system (`[NeZero 0]`) still needs a witness. `inhabited_classes` under `[project]` replaces the built-in list of classes treated as inhabited (`assess.INHABITED_CLASSES`); `inhabited_classes = []` raises the obligation for every instance. Neither finding changes a status.

A proposition that uses an operation Lean totalises (division, `0⁻¹`, the Bochner integral, a supremum, `∞.toReal`) gets a warning (code `totalised`, the operation as `trigger`) that says what the operation gives where the paper's would be undefined, so a reviewer can check the statement's side conditions; a dismissal records why the use is justified. A supremum or infimum is judged by the type it is taken in, which the probe reads from each application: in a complete lattice (a join of σ-algebras, a supremum in `ℝ≥0∞`) every family has one and there is no warning; in `ℝ` an empty or unbounded family gets 0; in another conditionally complete type it gets a default value, named with the type; when Lean finds neither lattice structure on the type (a type the statement quantifies over), the warning says the question is unresolved, as it does when the statement is too large for the probe to read the type of every application. A division or an inverse is judged the same way: in `ℕ` and `ℤ` division rounds and `n / 0 = 0`; in a field (a group with zero) `x / 0 = 0` and `0⁻¹ = 0`; in `ℝ≥0∞` `x / 0 = ∞` for `x ≠ 0` and `0⁻¹ = ∞`; in a group neither has an exceptional case and there is no warning; in a type with none of these structures the warning says the question is unresolved. The Bochner integral of functions into a type with one element, and a sum in `ℝ≥0∞`, get no warning, since every such function is integrable and every such family summable; in any other type, or when the probe could not read every application, they keep theirs. A conversion `ENNReal.toReal`, a root, a logarithm, a derivative and a conditional expectation keep their warnings. Evidence recorded before the probe read these types leaves a supremum's or a division's question unresolved. The warning lists each application it read with its type and what the type gives, and the reader marks it in the clause's statement (Audit details, Show in the statement); `check --json` and exports carry the same records. The warning changes no status.

A witness is only as good as the declarations that choose its instance. When a witness's statement uses a project declaration that no proposition's closure includes and no definition claim maps (an `abbrev` holding the paper's example values, say), `check` lists it while it has no current `def-review` (a warning, code `witness-def-review`, subject the declaration, trigger the witnesses; a dismissal lapses when the declaration changes), `check --json` gives the list under each claim (`witness_defs`), and the claim's audit details show it. A definition claim's audit details list the witness-only declarations whose type or body uses a definition it maps, as candidates for its mapping (`witness_candidates`). The list changes no status. `require_witness_def_reviews = true` under `[project]` asks a review of each such declaration, as of the definitions a proposition depends on: until it has one, the claim reads review pending.

Out-of-scope labels such as `part-of`, `proof-step`, `duplicate`, `literature` and `empirical` require explicit reasons. Each scope decision is recorded for review.

## Record reviews

Reviews are ordinary Markdown, followed by a marker naming the checked declaration and its fingerprint:

```md
## Theorem 2.1

Reviewer's independent interpretation, comparison and verdict.

<!-- spec-review: MyPaper.PaperSpec.thm_main HASH by=reviewer kind=human source=MyPaper:thm:main@DIGEST -->
```

For definitions use `def-review`. The hash records the declaration version reviewed; relevant definition changes reopen the obligation. `source` records, per claim, the digest of the paper passage read (the claim's `source_sha256` pin); a change to that text reopens the obligation too. A claim id may hold `@` (the digest follows the last one); `build` refuses one with white space or `-->`, since a marker cannot carry it. A definition claim counts as reviewed only through a marker that read its own passage, so a later reading of another passage that names the same definition does not change it; its audit details name the marker its state rests on (`rests_on` in the assessment), and `check` warns when that marker's review text names another such claim and not this one (code `def-review-other-claim`). A definition in a statement's closure needs one review that read every passage naming it: separate readings do not combine, and the finding says where each passage was read. Reviewer identity is a record, not authenticated proof of identity. A section that reviews several declarations ends with one marker for each, and every marker carries the section's text.

A marker records a reading, so one with no review text before it (a heading followed only by markers, as when markers are copied without their reviews) counts as no review: the declaration reads as not reviewed, its claim as review pending, and `build` lists each such marker with its file and line (an obligation, code `review-without-reading`). `bare_markers_by = ["reviewer"]` under `[project]` lets the markers of the reviewers it names count without text.

The Review queue exports reports. The maintainer evaluates those reports before invoking `machinechecked review promote FILE.json`; promotion writes each acceptance marker after the declaration's last marker, preceded by a line ``Review by REVIEWER: VERDICT (report `FILE`).``. That line is the text of the reviewer's marker; every other marker of the section, including one added later, keeps the section's text. The maintainer may also request further review.

## Run checks and generate a site

```sh
machinechecked build
machinechecked view
machinechecked check
```

Additional full-assessment commands:

```sh
machinechecked build --reuse-lean
machinechecked reassess
machinechecked site
machinechecked bundle --out audit.html
machinechecked export --out public-audit/
machinechecked changes
```

`build --site DIR` builds and then writes the same export to `DIR` in one step (as the reusable audit workflow does); it refuses a directory that is the project or holds anything but a previous site.

Without `--reuse-lean`, every build asks Lean for its probe records afresh. `build --refresh` also discards the module indexes and load failures kept in the Lean facts store, so whatever the build reads from that store is extracted again.

`symbol add` links a symbol of a claim's printed statement to a variable (or a binder's type) of its Lean statement, under your name; the reader marks it in the claim's text and highlights each side from the other. A link is an assertion, pinned to the statement and the text and shown as stale when either changes; no status reads it (docs/SYMBOL_LINKS.md).

`check` and `build` also warn about each name a module docstring of the project lists that nothing declares (a dotted name such as `Widget.foo_le_bar`, or the name a list item begins with under a "Main …" heading), with its file and line: prose that advertises a result the project does not contain. Only the project's own modules are checked (those whose file is in the project; a dependency's docstrings are its own audit's). A name is resolved as Lean resolves an identifier: inside each namespace the file enters or declares into, and with every namespace the file opens (`open`, anywhere in the file except `open … in`), so `Widget.area_nonneg` under `open Example.Shapes` names `Example.Shapes.Widget.area_nonneg`. A module or namespace written in full (`Example.Shapes.Widget`) is accepted wherever it appears. A shorter name counts only when it reaches a declaration: one that reaches only a module or a namespace through the file's namespaces is listed as such ("names `Widget`, which is the module `Example.Shapes.Widget`, not a declaration"), as the name of a declaration that is gone often does. A name is also accepted when a module of the same library declares it, or is that module, though the project does not import it: the library's sources are read for it, since the probe loads only the modules the project imports. It is a finding of the `warning` tier (code `module-doc-name`): it never changes a status or a gate, the reader lists it under the header, and an auditor can dismiss it with a written reason in the `dismissals` file, as any warning (`code`, the module as `subject`, the name as `trigger`, the finding's `fingerprint`, `rationale`, `by`).

`build` also resolves what review text cites in backticks: each token that looks like a Lean name (no spaces, and an `_` or a `.`) against the declarations, namespaces and modules of the project, its dependencies and Lean's library, where a name also resolves as the last components of a declaration's name (`bar_eq_span` for `Foo.bar_eq_span`), and a name in a module the audited modules do not import is looked up in the Lean sources of the project and its Lake packages; and each token that looks like a path (with a file extension, or a folder ending in `/`) against the files and folders of the project and its Lake packages, relative to any of their folders. What nothing resolves is listed with its file and line, as a warning (code `review-citation`, the review file as `subject`, the token as `trigger`), dismissible like any other: the marker's hash protects the declaration reviewed, not the result a review relies on. Fenced code blocks, the `Review by` lines promotion writes, reviewers' names and notation are skipped; `review_citations_ignore` under `[project]` replaces the patterns of notation (by default a letter, perhaps primed, followed by a subscript or a field, such as `x_i`, `C_rel`, `X'_T` or `μ.law`, and two letters with a short subscript), and `review_citations_strict = true` makes each unresolved citation a violation. Names are resolved when the probe runs, so `build --reuse-lean` and `reassess` check only the names the last probe saw.

`reassess` re-evaluates current reviews and dismissals against compatible stored evidence. `export` assembles only explicitly permitted public fields and scans the result for private-content leakage.

With several papers in one configuration, `export --paper ID` exports one of them: its claims, the declarations they depend on, and their reviews. The export is then also scanned for what belongs to the other papers alone (their claim ids, the declarations only they use and their Lean text, their reviews, and their manuscripts unless published), except a paper whose source and Lean the configuration publishes in full.

The export is a complete site, reader included; with `--data-only` it holds only the audit's descriptor and data, for a site that reads it with its own reader (machinechecked.org opens it as `https://machinechecked.org/read/?audit=<its address>`).

## What changed since the last release

Each build is a release. When the paper or the Lean changes, compare the new release with the
one before it:

```sh
machinechecked changes                       # the latest release against the one before it
machinechecked changes --from R1 --to R2     # any two releases
machinechecked changes --json                # the same, as one document (prooflens/changes@1)
```

For each claim it shows:

- **the paper**: whether its passage is `unchanged`, `moved`, `changed`, `context-changed` (its
  own passage is the same, and a further passage of its pin or the definition of a notation
  macro it uses changed), `removed` or `new`; `unknown` when a build has no digest of the
  passage (a passage it could not locate, or a paper read from its PDF). A removed claim whose
  text a new claim now has is offered as a proposed match, and two such claims make it
  `ambiguous`: a match carries no evidence over. When the inventory still pins the earlier text,
  the comparison says so: the source check reports the difference, and the reviews that read
  the passage are due until it is pinned again and read at the new pin.
- **the Lean**: for each clause, whether its proposition, each project definition its meaning
  depends on, and each of its proofs changed, with both statements as Lean prints them. A
  definition can change while its name and type stay the same; a proof can change while its
  statement stays the same.
- **both statuses**, each as its own build computed it.
- **the evidence**: every review the earlier build counted, and what became of it in the later
  build: *still current*, *due for review* (with the change it depends on and the question a new
  reading answers), *no longer applies* (the claim no longer depends on that declaration; the
  review is never moved to another declaration), or *a new reading*.

A review of a statement reads the paper and the statement, never a proof: a proof that changed
leaves it current, and the comparison says that it stands through that change. A review of a
definition reopens when the definition changes, and with it every claim whose meaning depends
on it. A review of a passage reopens when the passage is pinned again with other text, and the
question names the changed context (for example the sentence before a display that fixes its
quantifier). The text of a changed further passage is shown from the builds' own records; add
`--from-source DIR` and `--to-source DIR`, the manuscript folders of the two revisions, to show
a claim's own changed passage too (a folder's text is shown only when it is the text the build
recorded).

`--workspace ID` adds the records of a saved investigation that are no longer current against
the later release ([Saved investigations](REVIEWING.md#saved-investigations)), of every kind
(the claim's requirements, the passages that govern them and their alignments included), each
with the change that made it stale; an unchecked record is listed too, since it is not known
to be current. The terminal output lists them after the claims.

The reader shows the same comparison on its **Details** page, and `export` publishes it with
what each paper's `publish` settings allow (its passages' places and text only with its source
text, the Lean statements only with its Lean). The comparison changes no status and writes
nothing: a reopened review needs a new reading at the new revision, and the earlier reading
stays in the review files as it was. The review queue offers the reopened reviews first, with
their questions ([Review order](REVIEWING.md#review-order)).

## What the evidence says

A **consistency check** ensures the recorded claims and the machine checks do not contradict one another. It can pass with unproved claims.

The stronger **release gate** requires every applicable claim and scope decision to meet the configured acceptance conditions, including current independent reviews and any required independent kernel replay.

Independent replay requires a structured record naming the project commit and theorem declarations.

Read [Evidence policy](EVIDENCE_POLICY.md), [Data model](DATA_MODEL.md), and [Publication policy](PUBLICATION_POLICY.md) for the precise semantics.

## Private projects

A private project keeps its configuration, inventory, reviews and site in its own repository. `machinechecked bundle` writes the site as one HTML file carrying its data and PDFs, to commit there and open with a double click; nothing is hosted. Nothing of a private project belongs in the MachineChecked repository: `scripts/check_public.py` refuses a push containing any term of a private denylist or any line of the project's Lean or LaTeX sources. An allow file (`--allow`) lists exact strings already published, such as a public paper's title; a denylisted term inside one of them passes, and anywhere else is still refused.
