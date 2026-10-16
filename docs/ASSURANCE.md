# Full assessment

Most projects need only `machinechecked view paper.tex`. **Full assessment is optional**, for a formalisation that wants to distinguish a kernel-checked theorem from a reviewed correspondence to a specific paper.

It requires a stable claim inventory, closed Lean specifications written from the paper, acceptance theorems, and review records. Existing systems can integrate without changing their Lean code.

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

Sources can also be a pinned Git revision (`source = { git = "owner/repo", rev = "<commit>" }`, of which only that revision is fetched) or a versioned arXiv record. When the audited revision is not itself the published paper, say which public record it corresponds to with `published` (an arXiv identifier with version such as `"arXiv:2601.01234v2"`, a DOI, or a URL) and how it differs with `note` (for example `"This revision corrects Proposition 2.3."`); both go into `audit.json` and the reader, and change no status. With multiple root TeX files, specify `root`. Without LaTeX, MachineChecked falls back to the paper's PDF and labels the weaker source evidence.

Under `[project]`, `author` is the name the audit is published under, `issues` the GitHub repository where Raise issue opens reports, `site_url` the published reader's address, and `repository` the GitHub repository of the Lean source when it is not the project's `origin` remote. `repository_private = true` keeps the repository's name out of the reader's text; its Lean source links still name it, and open only for people with access.

Optional configuration includes `dismissals` (documented advisory warnings), `comparator_log` (a structured replay record) and `display` (a text-only display overlay). Display changes never alter verification results.

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

This is one claim entry inside `claims.json`. The acceptance theorem must have the **exact closed proposition** of the specification as its type, not a convenient approximation of the paper's theorem.

Other clause fields include `refute` (a proof of the printed proposition's negation), `corrects` (which original clause a correction addresses), and `defs` for a definition claim.

Out-of-scope labels such as `part-of`, `proof-step`, `duplicate`, `literature` and `empirical` require explicit reasons. Exclusion is a reviewable decision, not a means of declaring something verified.

## Record reviews

Reviews are ordinary Markdown, followed by a marker naming the checked declaration and its fingerprint:

```md
## Theorem 2.1

Reviewer's independent interpretation, comparison and verdict.

<!-- spec-review: MyPaper.PaperSpec.thm_main HASH by=reviewer kind=human -->
```

For definitions use `def-review`. The hash records the declaration version reviewed; relevant definition changes reopen the obligation. Reviewer identity is a record, not authenticated proof of identity.

The Review queue exports reports. The maintainer evaluates those reports before invoking `machinechecked review promote FILE.json`; review submission alone never adds acceptance markers. The maintainer may also request further review.

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

`reassess` re-evaluates current reviews and dismissals against compatible stored evidence. `export` assembles only explicitly permitted public fields and scans the result for private-content leakage. With several papers in one configuration, `export --paper ID` exports one of them: its claims, the declarations they depend on, and their reviews. The export is then also scanned for what belongs to the other papers alone (their claim ids, the declarations only they use and their Lean text, their reviews, and their manuscripts unless published), except a paper whose source and Lean the configuration publishes in full. The export is a complete site, reader included; with `--data-only` it holds only the audit's descriptor and data, for a site that reads it with its own reader (machinechecked.org opens it as `https://machinechecked.org/read/?audit=<its address>`).

## What the evidence says

A **consistency check** ensures the recorded claims and the machine checks do not contradict one another. It can pass with unproved claims.

The stronger **release gate** requires every applicable claim and scope decision to meet the configured acceptance conditions, including current independent reviews and any required independent kernel replay.

A separate replay record is identified by the exact project commit and theorem declarations; a build-cache hit or a plain text log does not replace that evidence.

Read [Evidence policy](EVIDENCE_POLICY.md), [Data model](DATA_MODEL.md), and [Publication policy](PUBLICATION_POLICY.md) for the precise semantics.

## Private projects

A private project keeps its configuration, inventory, reviews and site in its own repository. `machinechecked bundle` writes the site as one HTML file carrying its data and PDFs, to commit there and open with a double click; nothing is hosted. Nothing of a private project belongs in the MachineChecked repository: `scripts/check_public.py` refuses a push containing any term of a private denylist or any line of the project's Lean or LaTeX sources.
