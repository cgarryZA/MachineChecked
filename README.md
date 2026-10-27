# MachineChecked

**Read a mathematical paper beside its Lean formalisation.**

Select a statement to inspect its Lean counterpart, proof results and correspondence reviews.
MachineChecked runs locally in your Lean project and saves the links you choose.

[Try the demo](https://machinechecked.org/demo/) · [Browse papers](https://machinechecked.org/papers/) · [Setup guide](docs/GETTING_STARTED.md)

## Open your paper

From your Lean project's directory:

```sh
lake build
uvx machinechecked view
```

MachineChecked finds the paper and opens the reader. You can also name a LaTeX file, PDF or URL:

```sh
uvx machinechecked view paper/main.tex
```

Requires Python 3.11+, your project's Lean toolchain, and TeX Live for LaTeX or Poppler for PDFs.
The web reader is included. For a persistent command, run `uv tool install machinechecked`;
then use `machinechecked` directly.

Select a claim from the contents or paper margin: its paper passage and its Lean are compared
side by side, the Lean row by row with its exact Lean, and a definition opens beside the row that
uses it. **Expand comparison** gives them the full width. Follow existing `\lean{...}` tags, confirm a
suggestion, or choose a declaration. The reader saves your choices in `machinechecked.links.json`.
Projects with a `formalization.yaml` supply their paper sources and declared links automatically.

## Read the evidence

A Lean proof establishes a formal proposition. A correspondence review compares that proposition
and its definitions with the paper. Source checks identify the audited text; independent kernel
replay checks the proof again. The reader shows each result and its provenance in **Audit details**.

The optional **Review** view guides you through three steps:

1. Read the paper and record your interpretation.
2. Compare the Lean statement's assumptions and conclusion; record a verdict.
3. Read the author's review, save your report in the browser, and export it.

The maintainer evaluates reports and promotes reviews into the project's acceptance records.
[Review guide →](docs/REVIEWING.md)

## Share the reader

```sh
uvx machinechecked build                 # .machinechecked/MachineChecked.html
uvx machinechecked build --site public/  # a static site with audit.json
uvx machinechecked check                 # check linked declarations for automation
```

The HTML file opens directly in a browser. It includes the paper, Lean statements and audit data;
review those contents before publishing. Host the site directory on GitHub Pages or another static
host. Published audits carry their author's name, project commit and paper revision.

**Copy link** shares a claim. **Report issue** opens a draft in the audit's GitHub repository,
with the claim identifier, declarations and commits filled in. Set that repository with
`--issues owner/repo`.

## With a coding agent

`machinechecked check --json` prints structured results for scripts and agents. The
[MachineChecked skill](skills/machinechecked/SKILL.md) covers commands, status codes and evidence.
[Agent guide →](docs/AGENTS.md)

## Full assessment

Projects with locked specifications, a claim inventory and review records can configure
`machinechecked.toml`. Full assessment adds exact-type checks, definition-dependent reviews,
witnesses, refutations and independent kernel replay.
[Configuration guide →](docs/ASSURANCE.md)

## Documentation

- [Get started](docs/GETTING_STARTED.md) — install, open, link, share and troubleshoot
- [Reviewing](docs/REVIEWING.md) — record mathematical judgements
- [Full assessment](docs/ASSURANCE.md) — configuration and acceptance
- [Evidence policy](docs/EVIDENCE_POLICY.md) — what each check establishes
- [Data model](docs/DATA_MODEL.md) · [Publication policy](docs/PUBLICATION_POLICY.md) · [Threat model](docs/THREAT_MODEL.md)
- [Development](docs/DEVELOPMENT.md) · [Plan](PLAN.md)

Apache-2.0 licensed.
