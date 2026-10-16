# MachineChecked

**Read a mathematical paper with its Lean formalisation beside it.**

MachineChecked opens a paper, finds its numbered statements and lets you explore the Lean declarations linked to them. See which proofs Lean accepts, which claims are unlinked or incomplete, and which paper-to-Lean correspondences still need a mathematician's review.

**A Lean proof establishes a formal statement—not automatically the claim in the paper.** MachineChecked keeps those two questions separate.

**MachineChecked runs locally, in your Lean project.** It reads your paper and your compiled Lean declarations, writes an interactive reader, and keeps its results on your computer: generated data in `.machinechecked/`, the links you confirm in `machinechecked.links.json`, and the reader as `MachineChecked.html` if you ask for one. No account, registration or upload is needed. Publishing an audit (on your own GitHub Pages, say, and listing it on machinechecked.org) is a separate step you choose to take.

[Try the demo](https://machinechecked.org/demo/) · [Website](https://machinechecked.org/) · [Installation and usage](https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md)

## Open your paper

From an existing **built** Lean project:

```sh
lake build
uvx machinechecked view
```

MachineChecked finds the paper and opens the reader in your browser. If the project contains several papers, it asks which one to use. You can also pass a file explicitly:

```sh
machinechecked view paper/main.tex
```

Requires Python 3.11+, the project's Lean toolchain and TeX Live for LaTeX compilation. No Node installation, handwritten configuration or separate acceptance framework is required.

A paper can also be a PDF on disk or at a URL (`machinechecked view https://…/paper.pdf`). From a PDF, MachineChecked tries to find the numbered statements by their bold headings; it can miss some, and their positions are drawn as approximate. If the project has a [`formalization.yaml`](https://github.com/mathlib-initiative/formalization.yaml), its sources are offered as papers and its mappings become links, labelled as the project's own. In a project that is not built, links read *Lean not checked*, never proved.

In the reader, select a theorem from the contents or the paper margin. MachineChecked displays the printed statement and its Lean counterpart. Links can come from `\lean{...}` tags, suggested matches or a declaration you select yourself. Confirmed links are saved in `machinechecked.links.json`.

**Linking a theorem is not reviewing it.** Suggested links, confirmed links, Lean proof results and mathematical reviews remain distinct.

## Share your paper

```sh
machinechecked build   # writes MachineChecked.html, readable without a server
machinechecked build --site public/   # or a directory to publish, with its audit.json
machinechecked check   # fails if a linked declaration is missing or unproved
```

The HTML bundle includes the paper and reader. Share it directly, commit it to a suitable repository, or host the generated site yourself. Check its contents before making it public: private papers and Lean statements can be included.

Every claim has **Copy link** and, when the audit names a repository for reports (`machinechecked view --issues owner/repo`), **Raise issue**: a GitHub issue draft in the audit's own repository, with the claim, its Lean declarations and the commits filled in. The reader sends nothing, and a report changes no status.

[Full guide: installation, links, sharing and troubleshooting →](https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md)

## With a coding agent

`machinechecked check --json` prints every claim's status and links as JSON, for scripts and agents. The [MachineChecked skill](https://github.com/cgarryZA/MachineChecked/blob/main/skills/machinechecked/SKILL.md) teaches Claude Code and other agents to run it and to report what the statuses do and do not mean; see [Using MachineChecked with a coding agent](https://github.com/cgarryZA/MachineChecked/blob/main/docs/AGENTS.md).

## Review mathematical correspondence

The optional **Review** view guides a reader through one claim at a time:

1. Read the paper and record an independent interpretation.
2. Reveal the Lean statement, compare the assumptions and conclusion, and record a verdict.
3. Compare with the author's review, then export a report.

A report does **not** mark a claim accepted. In projects with a formal acceptance policy, the maintainer decides whether to promote a submitted review. The review's provenance, version and scope remain visible.

[Review guide →](https://github.com/cgarryZA/MachineChecked/blob/main/docs/REVIEWING.md)

## More rigorous audits

An ordinary Lean repository needs no configuration. Projects that already maintain **locked mathematical specifications**, a claim inventory and independent review records can opt into the full assessment using `machinechecked.toml`.

This enables exact-type checks, definition-dependent review tracking, witnesses, refutations, per-claim evidence and optional independent kernel replay. It does not assume that a passing Lean build proves the manuscript is faithfully formalised.

[Full-assessment setup and configuration →](https://github.com/cgarryZA/MachineChecked/blob/main/docs/ASSURANCE.md)

## Documentation

- [Get started](https://github.com/cgarryZA/MachineChecked/blob/main/docs/GETTING_STARTED.md) — install, open, link, share and troubleshoot
- [With a coding agent](https://github.com/cgarryZA/MachineChecked/blob/main/docs/AGENTS.md) — the skill and `check --json`
- [Reviewing](https://github.com/cgarryZA/MachineChecked/blob/main/docs/REVIEWING.md) — how the review queue records mathematical judgements
- [Full assessment](https://github.com/cgarryZA/MachineChecked/blob/main/docs/ASSURANCE.md) — configuration, claim inventory and acceptance
- [Evidence policy](https://github.com/cgarryZA/MachineChecked/blob/main/docs/EVIDENCE_POLICY.md) — what each check does and does not establish
- [Data model](https://github.com/cgarryZA/MachineChecked/blob/main/docs/DATA_MODEL.md) · [Publication policy](https://github.com/cgarryZA/MachineChecked/blob/main/docs/PUBLICATION_POLICY.md) · [Threat model](https://github.com/cgarryZA/MachineChecked/blob/main/docs/THREAT_MODEL.md)
- [Development and roadmap](https://github.com/cgarryZA/MachineChecked/blob/main/docs/DEVELOPMENT.md) · [Plan](https://github.com/cgarryZA/MachineChecked/blob/main/PLAN.md)

MachineChecked is an **open-source tool, not a certifying authority**. Each published audit presents its author's evidence and judgements; readers can inspect and challenge them. The website currently offers the tool and a synthetic demonstration, not an independently certified catalogue of papers.

Apache-2.0 licensed.
