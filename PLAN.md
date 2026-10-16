# MachineChecked: plan of record

MachineChecked shows a mathematical paper beside its Lean formalisation and says, claim by claim,
what is established. It keeps three things apart that a Lean build alone does not:

1. **Evidence**: what Lean and the mechanical checks established (exact statement types, axioms,
   fingerprints, proof status).
2. **Interpretation**: whether a Lean statement says what the paper says. No tool can check that;
   only a reviewer can judge it.
3. **Presentation**: how a reader explores both without knowing Lean. A view displays a status; it
   never computes, changes or upgrades one.

## Two products

| | Where | What it does | What it never does |
|---|---|---|---|
| **The tool** | `cgarryZA/MachineChecked`, command `machinechecked` | runs on a researcher's machine or in their own CI: reads the paper, probes the built Lean, links claims, records reviews, writes a reader and a portable audit | needs the website |
| **The site** | machinechecked.org (moving to its own repository, `cgarryZA/machinechecked.org`) | indexes papers and the Lean repositories that formalise them, and displays published audits | builds Lean, runs anyone's code, or endorses an audit |

The tool can be used without ever registering with the site, and the site without knowing Lean.

## The site

**Three levels per paper.**

| Level | What the site knows | What a visitor sees |
|---|---|---|
| Paper | arXiv (or a curated entry) identifies it | its metadata and a link to the original |
| Lean repository linked | a repository states that it formalises the paper | "This repository states that it formalises this paper", and the repository |
| Audit published | someone published a MachineChecked audit of that repository | the interactive reader: claims, Lean, statuses, reviews |

A link is not an audit, and an audit is not an endorsement. A search result does not enter the
registry. Figures a project reports about itself (a `sorry` count in `formalization.yaml`, its
review status) are shown as the project's own, never as a check by MachineChecked.

**Listing.** An arXiv paper is linked to a repository, with no approval, when the repository's
`formalization.yaml` names the paper with `relationship: formalizes`. A daily job finds these files,
checks that the arXiv identifier exists and that the repository is a Lean project, and rebuilds the
registry from scratch (a repository that stops naming a paper drops off). Each listing records the
file and commit that named the paper. Papers not on arXiv are curated by hand. Every listing has a
report button; a bad listing is removed with one line in `delisted.json`. More machinery
(a registration form, duplicate suppression) is added only when a real need appears.

**The registry is small.** Per paper: its identifier, and per formalisation the repository, the
commit, the paper version, and its audits as URLs. No Lean builds, caches or claim evidence are
stored centrally. Several audits of one repository are distinct from several formalisations.

**Audits live with their authors.** An audit is the tool's export plus a small descriptor
(schema, author, paper and version, repository and commit, data path, issues repository), hosted
where its author chooses (for example their GitHub Pages). The site loads it as data and treats
every string in it as untrusted; it never runs an audit's HTML or JavaScript. An audit the browser
cannot load is linked instead.

**One page per paper.** A selector at the top chooses whose formalisation is shown; changing it
changes the evidence beside each claim, never the paper or its numbering. Each project shows its
own claims. Showing another project's mapping where the selected one has none, and combined
coverage, come later, and only between audits that pin the same paper version: claim numbers can
differ between versions. Claims proved in different projects are never one proof, and projects are
not ranked.

**Reports.** Every claim has Raise issue: a pre-filled GitHub issue in the audit's own repository
(the audit author's choice), carrying identifiers and the claim's permanent link, never statement
text. Listing and site problems go to the site's repository. A report is a question, not a finding:
it changes no status. Counts of open issues per claim may later be added by a scheduled job.

**Papers are linked, not mirrored.** The site shows arXiv metadata and links to the PDF. Only an
audit whose terms allow it carries its pinned PDF.

## The tool

- **Zero configuration** in a built Lake project: the paper is found (LaTeX, else PDF, or a URL),
  `\lean{}` tags, `formalization.yaml` mappings and suggestions become links the user confirms,
  saved in `machinechecked.links.json`. From a PDF, statements are found by their bold headings, a
  heuristic whose anchors are drawn as approximate.
- **Full assessment** (optional, `machinechecked.toml`): a claim inventory, locked specifications,
  acceptance theorems with exact types, review markers bound to fingerprints, and statuses
  computed by `assess.py`. An existing acceptance system stays authoritative; MachineChecked reads
  its outputs and never modifies its tools.
- **Review queue**: reading locked before the Lean is shown, verdict recorded before the author's
  review; a report is exported, and only `machinechecked review promote` writes a marker.
- **Provenance is shown, never upgraded.** A Markdown marker is self-declared; a review by an
  author of the statements is never independent; human or AI review is recorded.
- **Links are pinned to a release** (`#/r/<release>/…`): an older link shows a banner, never newer
  evidence silently.
- **Expensive builds run on the user's resources**: a build cache (`machinechecked cache
  save|restore`) and a workflow template they copy into their own repository. MachineChecked's own
  infrastructure never builds a third party's Lean.

## Order

| Step | Work | Done when |
|---|---|---|
| 0 | Short README and guides; this plan; landing page with a preview of the demo reader | the docs match the code, including the limits of PDF reading |
| 1 | The audit descriptor, written by `build` and `export`; the reader loads an audit from a URL as untrusted data | the toy audit loads from another address; HTML in a manifest is shown as text |
| 2 | The site moves to `cgarryZA/machinechecked.org`, reusing the reader's components | the site deploys with no Lean or TeX installed; the demo is the toy audit published by the tool's CI |
| 3 | Registry and paper pages: the three levels, the selector; Navier–Stokes as a curated entry; collapsible contents and an adjustable split in the reader | a paper page shows two repositories and one audit |
| 4 | Search: arXiv identifier lookup and OpenAlex | an unregistered paper can be found without entering the registry |
| 5 | Listing: the daily `formalization.yaml` job, the report button, `delisted.json`, curated entries | a repository that names an arXiv paper appears with no one approving it |
| 6 | Raise issue on every claim of a published audit | a visitor reaches the audit's tracker with the claim filled in |
| 7 | The `machinechecked cache` commands (save, restore) and the workflow template | another researcher produces and hosts an audit with their own resources |
| 8 | The first real audit: OpenAI's Navier–Stokes formalisation, built under WSL2, cached, audited and published from a fork | its paper page gains an audit |

Deferred: claim fallback across projects and combined coverage; issue counts; a registration
form; README badges; drift reports between releases; a Verso Blueprint adapter; live Lean.

**Other formalisation platforms.** A Prove2Me mission (or another platform's project) can be one
more source of evidence for a paper's claims, read-only, beside GitHub repositories: its mission
and theorem identifiers, its pinned Lean environment, and its own proof state shown as reported
(a sketch that depends on open theorems is never shown as a completed proof). Review reports from
the queue could be attached to a mission's statements; the platform still decides what it
accepts. Built with the paper page's project selector; nothing is ever submitted automatically.

The policies are in `docs/`: [threat model](docs/THREAT_MODEL.md),
[evidence policy](docs/EVIDENCE_POLICY.md), [data model](docs/DATA_MODEL.md),
[publication policy](docs/PUBLICATION_POLICY.md). Engine internals and the seeded-failure tests are
in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).
