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

[review]
check = "python3 tools/check.py"  # optional post-promotion check

[[paper]]
id = "A"
title = "My paper"
source = { path = "paper" }
root = "main.tex"
publish = { pdf = false, source_text = false, lean = false, reviews = false }
```

Sources can also be a pinned Git revision (`source = { git = "owner/repo", rev = "<commit>" }`, of which only that revision is fetched) or a versioned arXiv record (`source = { arxiv = "2601.01234v2" }`: its source is downloaded from arXiv once and kept in the working directory, so later builds work offline; the version is required). Say which public record the paper is with `published` (an arXiv identifier with version such as `"arXiv:2601.01234v2"`, a DOI, or a URL) and, if the audited revision differs from it, how with `note` (for example `"This revision corrects Proposition 2.3."`); both go into `audit.json` and the reader, and change no status.

**The version an audit pins.** An audit pins exactly one version of its paper, and `audit.json` names it (`paper_version`, see the [data model](DATA_MODEL.md)):

- **A published version**: `published = "arXiv:2601.01234v1"` (or an arXiv source). It is labelled "arXiv v1". The inventory is pinned to it by its identifier: `"papers": {"T": {"commit": "2601.01234v1"}}`, or a claim's `"commit"`.
- **An unpublished manuscript**: `version = "manuscript"` with the manuscript's commit as the source's `rev` (`source = { git = "owner/manuscript", rev = "<commit>" }`; a folder in the project may state its `rev`, checked against the folder's history when it is a repository of its own). It is labelled "Latest manuscript (commit abc1234)", never with a version number, even when `published` names the paper's earlier arXiv version. The inventory is pinned to that commit.

`build` refuses an audit whose inventory is pinned to another version than the one it declares (for example `published` says arXiv v1 while the claims are pinned to a later manuscript commit), before Lean runs. A paper that declares no version is described by its source's commit when the inventory agrees, and by nothing otherwise. To publish an audit of each version, see [several audits of one repository](GETTING_STARTED.md#several-audits-of-one-repository).

With multiple root TeX files, specify `root`. Without LaTeX, MachineChecked falls back to the paper's PDF and labels the weaker source evidence.

A paper published as a PDF is configured with `source = { path = "…" }` and `pdf = "paper.pdf"` (no `root`); its numbered statements are found by their bold headings, and any the headings miss can be placed by hand in `anchors.json`. To meet the release gate's source condition, pin the PDF with `pdf_sha256 = "<its SHA-256>"`: the gate then checks the hash, requires every claim in scope to be found, and states that the source is a PDF with approximate claim positions.

Under `[project]`, `author` is the name the audit is published under, `issues` the GitHub repository where Raise issue opens reports, `site_url` the published reader's address, and `repository` the GitHub repository of the Lean source when it is not the project's `origin` remote. `repository_private = true` keeps the repository's name out of the reader's text; its Lean source links still name it, and open only for people with access.

Optional configuration includes `dismissals` (documented advisory warnings), `comparator_log` (a structured replay record) and `display` (a text-only display overlay). `machinechecked replay CONFIG` runs Comparator with its configuration (`lake env comparator CONFIG`, so Comparator must be installed) on a commit whose Lean inputs have no uncommitted changes, and writes the record to `comparator_log`: the commit, the Lean version and the Lake manifest's hash, whether it passed, and the theorems it replayed. The assessment counts it for that commit and environment, and for a later commit when the record's commit is its ancestor and no Lean input (sources, lakefile, manifest, toolchain) changed since, so the record can be committed to the project; a CI checkout then needs enough history to show it (`fetch-depth: 0`). Display overlays control presentation; the inventory and evidence control assessment.

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

Out-of-scope labels such as `part-of`, `proof-step`, `duplicate`, `literature` and `empirical` require explicit reasons. Each scope decision is recorded for review.

## Record reviews

Reviews are ordinary Markdown, followed by a marker naming the checked declaration and its fingerprint:

```md
## Theorem 2.1

Reviewer's independent interpretation, comparison and verdict.

<!-- spec-review: MyPaper.PaperSpec.thm_main HASH by=reviewer kind=human -->
```

For definitions use `def-review`. The hash records the declaration version reviewed; relevant definition changes reopen the obligation. Reviewer identity is a record, not authenticated proof of identity.

The Review queue exports reports. The maintainer evaluates those reports before invoking `machinechecked review promote FILE.json`; promotion writes the acceptance markers. The maintainer may also request further review.

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
```

`build --site DIR` builds and then writes the same export to `DIR` in one step (as the reusable audit workflow does); it refuses a directory that is the project or holds anything but a previous site.

`symbol add` links a symbol of a claim's printed statement to a variable (or a binder's type) of its Lean statement, under your name; the reader marks it in the claim's text and highlights each side from the other. A link is an assertion, pinned to the statement and the text and shown as stale when either changes; no status reads it (docs/SYMBOL_LINKS.md).

`reassess` re-evaluates current reviews and dismissals against compatible stored evidence. `export` assembles only explicitly permitted public fields and scans the result for private-content leakage.

With several papers in one configuration, `export --paper ID` exports one of them: its claims, the declarations they depend on, and their reviews. The export is then also scanned for what belongs to the other papers alone (their claim ids, the declarations only they use and their Lean text, their reviews, and their manuscripts unless published), except a paper whose source and Lean the configuration publishes in full.

The export is a complete site, reader included; with `--data-only` it holds only the audit's descriptor and data, for a site that reads it with its own reader (machinechecked.org opens it as `https://machinechecked.org/read/?audit=<its address>`).

## What the evidence says

A **consistency check** ensures the recorded claims and the machine checks do not contradict one another. It can pass with unproved claims.

The stronger **release gate** requires every applicable claim and scope decision to meet the configured acceptance conditions, including current independent reviews and any required independent kernel replay.

Independent replay requires a structured record naming the project commit and theorem declarations.

Read [Evidence policy](EVIDENCE_POLICY.md), [Data model](DATA_MODEL.md), and [Publication policy](PUBLICATION_POLICY.md) for the precise semantics.

## Private projects

A private project keeps its configuration, inventory, reviews and site in its own repository. `machinechecked bundle` writes the site as one HTML file carrying its data and PDFs, to commit there and open with a double click; nothing is hosted. Nothing of a private project belongs in the MachineChecked repository: `scripts/check_public.py` refuses a push containing any term of a private denylist or any line of the project's Lean or LaTeX sources. An allow file (`--allow`) lists exact strings already published, such as a public paper's title; a denylisted term inside one of them passes, and anywhere else is still refused.
