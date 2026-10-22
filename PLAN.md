# MachineChecked: plan of record

MachineChecked displays a mathematical paper beside its Lean formalisation. The engine assesses
proofs, reviews, source verification and replay; the reader presents those results and their provenance.

## Two products

| Product | Repository | Responsibility |
|---|---|---|
| Tool | `cgarryZA/MachineChecked` | Reads papers, probes compiled Lean, records reviews and writes portable audits on the researcher’s machine or CI |
| Site | `cgarryZA/machinechecked.org` | Indexes papers and displays published audit data in the package’s reader |

## The site

**Three levels per paper.**

| Level | What the site knows | What a visitor sees |
|---|---|---|
| Paper | arXiv (or a curated entry) identifies it | its metadata and a link to the original |
| Lean repository linked | a repository states that it formalises the paper | "This repository states that it formalises this paper", and the repository |
| Audit published | someone published a MachineChecked audit of that repository | the interactive reader: claims, Lean, statuses, reviews |

Listings cite the repository’s `formalization.yaml`; audits name their authors and revisions.
Project-supplied counts and review descriptions carry project attribution. Search results link to
external papers; the registry is built from formalisation declarations and curated entries.

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

**One page per paper, and it is the paper.** A paper's page is the reader showing the paper itself (its PDF from its source), whether or not anything about it is formalised; what is known about its formalisations sits in a panel beside it, and an audit adds its claims to the same reader. A selector chooses whose formalisation is shown; changing it
changes the evidence beside each claim, never the paper or its numbering.

**Several audits of one version.** A page opens on its default audit: the one whose repository has
the most GitHub stars (counts the site records when it builds; without a count for every audit, the
registry's order). Each claim shows that audit's evidence. A claim it does not map shows the
evidence of the next audit, by stars, that maps it, labelled with that audit's author, repository
and commit. Choosing one project in the selector shows only its evidence, and flags each claim its
audit does not map. Audits are drawn on together only when they pin the same paper version, since
claim numbers can differ between versions. Statuses from different audits are never combined into
one, and claims proved in different projects are never one proof.

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
- **Proof steps are targets of their own** (#125): an equation or passage of a printed proof has
  its own links (the Lean that establishes it, or the different formal route used instead) and
  its own review, apart from its enclosing result. A `proof-step` scope decision is about formal
  coverage only, never a reading of the step.
- **Provenance is shown, never upgraded.** A Markdown marker is self-declared; a review by an
  author of the statements is never independent; human or AI review is recorded.
- **Links are pinned to a release** (`#/r/<release>/…`): an older link shows a banner, never newer
  evidence silently.
- **Expensive builds run on the user's resources**: a build cache (`machinechecked cache
  save|restore`) and a workflow template they copy into their own repository. MachineChecked's own
  infrastructure never builds a third party's Lean.

## Order

The aim of the next steps is that a stranger, or the coding agent helping them, can find
MachineChecked, install it with one command, and use it without asking anyone.

| Step | Work | Done when |
|---|---|---|
| 0 ✓ | Short README and guides; this plan; landing page with a preview of the demo reader | the docs match the code, including the limits of PDF reading |
| 1 ✓ | The audit descriptor, written by `build --site` and `export`; the reader loads an audit from its address as untrusted data | an audit loads from another address; HTML in it is shown as text |
| 2 ✓ | For agents: `check --json`, the Agent Skill (`skills/machinechecked`), `docs/AGENTS.md`; PyPI metadata and a release workflow | an agent can run an audit and report it without misreading a status |
| 3 ✓ | First PyPI release (`uvx machinechecked view`); GitHub description, topics and a versioned release | `pip install machinechecked` works on a clean machine |
| 4 ✓ | The site moves to `cgarryZA/machinechecked.org`, reusing the reader; the demo is the toy audit published by the tool's CI | the site deploys with no Lean or TeX installed |
| 5 ✓ | Registry and **crawlable paper pages**: plain HTML per paper (`/papers/<arxiv id>/`) with title, authors, identifiers and the linked repositories and audits, then the interactive reader; `sitemap.xml`, `robots.txt` allowing search crawlers, a short `llms.txt`; Navier–Stokes as a curated entry | a paper page is found by a search engine and shows two repositories and one audit |
| 6 | The `machinechecked cache` commands (save, publish, restore) and a workflow template for anyone's own repository (`audit.yml`), done; then the Navier–Stokes case: built under WSL2 with them, audited, published from a fork and registered; the landing page links it | a reader can go from a claim in the paper to its Lean and raise an issue |
| 7 ✓ | Listing: the daily `formalization.yaml` job, the report button, `delisted.json`; search by arXiv identifier and OpenAlex | a repository that names an arXiv paper appears with no one approving it |
| 8 ✓ | Reader polish: collapsible contents, adjustable split, the margin label no longer covering text; README badge ("audit available") | an outside audit links back with a badge |

**Launch** (people, not code): once steps 3, 5 and 6 are live, show it on the Lean Zulip and to
the mathlib-initiative `formalization.yaml` maintainers, approach about ten researchers with a
paper and a Lean repository, then a Show HN with the Navier–Stokes case. No paid advertising.

Deferred: claim fallback across projects and combined coverage; issue counts; a registration
form; an MCP server (the CLI and the skill come first); drift reports between releases; a Verso
Blueprint adapter; live Lean; accounts, newsletters, community features.

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
