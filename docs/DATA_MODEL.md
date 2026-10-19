# Data model

Three documents, each with a JSON Schema in `engine/python/prooflens/data/schema/`, and the
files auditors write (reviews, the links file and workspaces), described below.

## Inventory (`inventory.schema.json`), written by people

The frozen list of claims, with the optional `label` of a claim and the `regimes` of a clause.

```json
{"claims": [{
  "id": "T:thm:even-add", "paper": "T", "kind": "theorem", "number": "Theorem 2.1",
  "title": "Closure under addition", "label": "thm:even-add", "location": "toy.tex",
  "source_sha256": "<sha256 of the whitespace-normalised environment body>",
  "scope": "formal", "scope_note": "", "scope_reviewed": true,
  "clauses": [{"name": "statement",
               "spec": "Toy.PaperSpec.thm_even_add",
               "accept": "Toy.Acceptance.thm_even_add",
               "witness": "Toy.Acceptance.thm_even_add_hypotheses",
               "regimes": [{"name": "nonzero summands", "description": "…",
                            "witness": "Toy.Acceptance.thm_even_add_hypotheses"}]}]}]}
```

A clause has `accept` or `refute`, not both. A corrected statement names the clause it
`corrects` (by clause name). A definition claim's clause has `defs` and no `spec`.

A claim's `location` is a file for a numbered environment, whose `source_sha256` is the hash of
the whitespace-normalised body of the environment, or `<file>:<line>` for a claim recorded by
line (an equation, a part of an environment, a prose claim), whose hash is the hash of that line.

## Reviews, written by people

Markdown files with markers:

```
<!-- spec-review: <proposition> <hash> by=<reviewer> [kind=human|ai] -->
<!-- def-review: <definition> <hash> by=<reviewer> [kind=human|ai] -->
```

`<hash>` is the `legacy_hash` or the `pl-fp-v1:` fingerprint the review was made at. The section
the marker closes is the text of the review. The last marker of a declaration, reading the files
in order (a directory's `.md` files by name), is its current record.

Dismissals of warnings (`dismissals.json`):
`[{"code", "subject", "trigger", "fingerprint", "rationale", "by"}]`.

## Evidence (`evidence.schema.json`), written by the engine

`.machinechecked/evidence/<id>.json` (`.prooflens/` in older projects), with `id` the SHA-256 of the canonical JSON of `body`:

| Field of `body` | Content |
|---|---|
| `provenance` | tool, Lean, project and dependency revisions, each paper's source and PDF hashes |
| `inventory` | the inventory as read |
| `reviews` | the review files' hashes and every parsed marker |
| `dismissals` | as read |
| `lean` | the probe records: specifications (binders, conclusion, closure, constants, hashes), proofs (exact-type check, axioms), declarations (signature, value, definition content, authored source, doc, hashes), layering |
| `tex` | per paper: mode, page size, anchors (env, number, labels, file:line, begin/head/end positions, source hash), files read, source regions, and the display excerpts of its claims (`excerpts`, [SOURCE_REGIONS.md](SOURCE_REGIONS.md#display-excerpts)) |
| `assessment` | per claim: status and clauses; all findings |

A pretty-printed Lean term (a binder's type, a conclusion, a signature) is `{text, segments}`:
each segment is a piece of the text, with `ref` when it names a constant and `var` when it is an
occurrence of one of the statement's own variables (the index, in `binders`, of the binder that
introduced it). A conclusion that is a conjunction, disjunction or equivalence also has
`logic`, a tree of `{op, args}` whose leaves are `{leaf: {text, segments}}`. A term also lists its sub-terms as `terms`, ranges `{from, to}` of its segments (outer before inner; none for a very large term), so that a reader can select a whole sub-term. Both are for
display: no status, fingerprint or hash reads them.

A declaration record of a definition of data or of a predicate (not a proposition, an instance or
a generated helper) also says what the definition says. `defined_by` is `body` or `equations`.
With `body`: `params` (the leading `fun` binders of its value, each `{name, binder, id, type,
proposition}`), `body` (the term under them, with the sub-term identities it has in `value`) and
`result` (its type, identities prefixed `type:`). `equations` lists the equation theorems Lean
derives (`Lean.Meta.getEqnsFor?`), each `{name, statement, params, equation}`: the theorem's exact
statement, and its variables and the equation under them; their identities are prefixed by the
theorem's name. At most 64 are listed; `equations_omitted` counts the rest and `equation_names`
names all of them. A failed extraction is recorded in `definition_error` and stops nothing else.
`lean_source` is the declaration's authored source, `{file, line, end_line, text, sha256}`, read
from the checkout the probe ran on (none for a declaration of a dependency). The export carries
these fields only when every paper publishes its Lean.

A printed term of a statement (a binder's type, a conclusion or one of its leaves) and the body
of a definition also carry `expansions`: each application of one of the project's definitions
inside it, expanded at its actual arguments. An expansion is `{at, id, name, args, defined_by,
checked}`: `at` is the identity of the application it expands, `id` (`at` followed by `=`)
prefixes the identities of its own sub-terms, and `args` are the arguments by the definition's
parameters (`{name, binder, value}`). With `body`, `params` are the parameters the application
does not supply and `body` is the definition's body with the arguments substituted
(`Expr.beta`, so no bound variable is captured) and checked by Lean to have the application's
type. With `equations`, `equations` lists each equation theorem whose left side matches the
application, specialised to it, `{name, statement, params, equation}`, with the variables and
case conditions that remain as `params` and the statement checked to follow from the theorem;
`equations_not_applying` names the others and `equations_omitted` counts those not compared.
An expansion's own applications expand once more; a failure is `error` on that expansion only.
Only what is printed is searched (explicit arguments, not implicit or instance ones), up to
4000 nodes of a term; at most 16 applications of one term are expanded and `expansions_omitted`
counts the rest.
Expansions are display only and are exported with the statement, so only with the Lean.

## Manifest (`manifest-index.schema.json`, `manifest-claim.schema.json`), derived

The current format is `prooflens/manifest@1`; older display data must be rebuilt.
See [the structured status contract](STATUS_CONTRACT.md) for the complete code inventory.

`data/index.json` lists the papers, every claim's `status_code`, derived status/class and anchor, the summary and the
findings counts. `data/claims/<file>.json` holds one passport: the printed statement (and its
display `excerpt`, when the paper publishes its source text), each
clause's unfolded statement, proofs, witness, regimes, reviews and structured `evidence`, the
declarations of its closure, and its findings. A claim is loaded only when it is opened.
In zero configuration a passport also has `correspondence` (or `null`): the mapper's reading of how
far the linked declarations state the claim, `{source, coverage, basis, refs, argument, next_step,
bridge, question, would_decide, confidence, note, by}`, where `source` is `confirmed` (the
auditor's, from `machinechecked.links.json`) or `formalization.yaml` (the project's row notes).
`coverage` is `full`, `partial`, `changed`, `related`, `unresolved` or `null`; `basis`, how the
coverage is supported, is `direct`, `reviewed_composition`, `checked_bridge` or `null`
(unspecified), with `refs` the linked declarations it rests on. A reviewed composition has the
auditor's `argument` and the `next_step`, stating the combination as one Lean result (a stored
`composed` coverage reads as `full` with this basis); a checked bridge has `bridge`, `{theorem,
target, state, reasons, pinned, current}`, where `state` is `checked`, `stale` or `unchecked` and
`pinned`/`current` hold the target's and the passage's digests (`target_fingerprint`,
`source_sha256`) as read and as now. An unresolved reading has its `question` and `would_decide`.
Values outside these are dropped. It is displayed beside the links and is never an input to a
status.

A paper page (`prooflens.paper.write_paper_site`, used by machinechecked.org) is written in the
same format, with `mode: "paper"`: the paper's registry entry (`paper`), the Lean projects that
state they formalise it (`projects`, as `owner/repo`), and the statements found in its PDF, each
with its links (each naming its `repository`) and, per project, the status that project's links
give it (`by_project`). Without an audit nothing has run Lean, so a linked statement reads
"linked: Lean not checked here (no audit published)" (class `declared`). The reader shows one
project at a time and never combines them. No statement text is written.

**Versions of a paper.** A paper with several versions (published `vN`, an unpublished
manuscript at a commit) has one page per version, each written by `write_paper_site` with its own
PDF, claims and audits, and with `versions` (every version) and `version` (this page's `id`).
The site supplies each version as:

| Field | What |
|---|---|
| `id` | the version's identifier, as an audit's `paper_version.id` gives it: `arxiv:2601.01234v1`, `manuscript:abc1234` |
| `kind` | `published` or `manuscript` |
| `revision` | a manuscript's commit (required for a manuscript) |
| `href` | the address of that version's page on the same site, such as `/papers/2601.01234/v1/` (absolute path or relative; never another site) |
| `pdf` | the version's PDF (https, or on the site); optional |
| `audits` | the audits of that version: `url` (https), `author`, `repository`; optional |

`page_versions` checks the list and sets each `label` from `kind` and `id` ("arXiv v1", "Latest
manuscript (commit abc1234)"), ignoring a label the site gives. Every audit loaded for a page
must pin that page's version: load it with the listing's `version` (`load_published_audit`), and
`write_paper_site` refuses one that pins another. The reader shows a version drop-down beside the
project selector when there are several versions: choosing one opens that version's page, with
the chosen project and without the claim (claim numbers can differ between versions); a link to
a claim opens it in its own version's page. Statuses belong to each version's page, so switching
never changes one.

## Audit descriptor (`audit.json`), written by the engine

At the root of every published reader (`machinechecked build --site`, `machinechecked export`):
`schema` (`machinechecked/audit@1`), `created`, `author` (the name the audit is published under,
as its author gives it), `papers` (title; `id` and `version` when the paper is an arXiv paper, for
example `arxiv:2601.01234` and `v2`, with `version` null when the audit pins an unpublished
manuscript; `url`; `revision`; `paper_version`, below), `formalisation` (`repository` as
`owner/repo` when the project's remote is on GitHub, `commit`, `toolchain`), `release`, `data` (the
path of the manifest index, inside the directory), `issues` and `site_url`. It records what its
author states; it is not evidence of anything by itself. A reader loading an audit from another
address takes every string in it and in its data as text, reads only files inside the audit's
directory, and never offers to edit it.

`paper_version` is the one version of the paper the audit pins (`versions.py`), or null when none
is known:

| Field | Published version | Unpublished manuscript |
|---|---|---|
| `kind` | `published` | `manuscript` |
| `id` | `arxiv:2601.01234v1` (or `doi:…`, or the URL) | `manuscript:<first 7 hex of the commit>` |
| `revision` | the commit of the source read, if known | the manuscript's commit |
| `label` | `arXiv v1` | `Latest manuscript (commit abc1234)` |

An arXiv version also has `arxiv` (`arxiv:2601.01234`) and `number` (`v1`). A manuscript is never
given a version number. `build` refuses an audit whose inventory pins (`papers.<id>.commit`, a
claim's `commit`) name another version: a published version is pinned by its identifier
(`2601.01234v1`), a manuscript by its commit. `checked` is true when every claim carries a pin and
the pins name this version (a zero-configuration audit reads its claims from the version itself, so
it is always true); false when some claim carries no pin, so the version is only as the configuration
states it. Readers show an unchecked version as declared by the author and not checked against the
claims. A site loading an audit (`load_published_audit`)
rebuilds the label from `kind` and `id`, checks that the descriptor and the data name the same
version, and, given a listing's `version`, refuses an audit that pins another one.

## Workspace (`prooflens/workspace@1`), written by the reader and the command line

An auditor's saved investigation: `<work dir>/review-work/<file>.json` (Git ignores the working
directory). The file's name is not its identity; `id` is. `engine/python/prooflens/workspace.py`
reads and writes it for `machinechecked workspace`, for the reader under `machinechecked view`
(`/api/workspace…` on the loopback server) and for `machinechecked review`, with one validation
path. A workspace records evidence and readings and is never an input to a status.

| Field | Content |
|---|---|
| `schema`, `id` | `prooflens/workspace@1`; `ws-` and 12 hex digits |
| `reviewer` | the reviewer record of the review protocol (`human:NAME` or `llm:MODEL`, self-declared) |
| `mode` | `independent` (blind reading first, through the review protocol) or `informed` |
| `exposure` | what the auditor had seen, append-only: `{what: ["Lean", "author's review", "prior interpretations", "external material"], claims: [ids] or null for every claim, at, how}` |
| `revision` | increases with each saved change |
| `selection`, `sources` | the paper and project selected; the build it was made against (`release`, project `commit`/`repository`, each paper's `revision` and `pdf_sha256`) |
| `records` | evidence, findings and questions, by record id (below) |
| `resume` | where to continue: `claim`, `clause`, `question`, `pinned` references, `at`, `by`; kept apart from the evidence |
| `review` | the review protocol's `drafts` (locked reading, verdict, author-review step) and submitted `reports` (`prooflens/review-report@1`) |
| `conflicts` | refused edits, each with the saved record (`current`) and the proposal (`proposed`) |
| `provenance` | upgrades, mode changes and imports, with time and person |
| `ops` | acknowledgements of requests by their `op_id`, so a repeated request changes nothing (not exported) |

Every record has `id`, `kind`, `claim` (a claim id, resolved from a key or a number when written),
optional `clause` and `note`, `rev`, `created_at`/`created_by`, `updated_at`/`updated_by`, and
`pins` (`release`, `statement_sha256`: the claim's printed-text hash when written).

- **`evidence`**: `ref` is one of `{decl, module, build, fingerprint, digest}` (a declaration of
  the selected build; `build` is `built`, `unbuilt`, `not loaded` or `external`), `{source:
  {file, line}}` or `{paper: {claim, quote}}`. `role` is `candidate` (the default), `supports`,
  `context` or `rejected` (with `why_rejected`). A candidate is a candidate until the auditor
  gives it another role.
- **`finding`**: `coverage` (the links file's words: `full`, `partial`, `changed`, `related`,
  `unresolved`), optional `basis` (`direct`, `reviewed_composition` with an optional `argument`,
  or `checked_bridge` with `bridge: {theorem, target}`), optional `confidence`, `evidence` (ids
  of evidence records of the same claim, which the basis rests on) and, when unresolved,
  `question` and optional `would_decide`. A `composed` coverage is recorded as `full` with basis
  `reviewed_composition`. `state` is `draft`
  or `submitted` (`submitted_at`). A submitted finding is never edited or deleted: a later
  finding names it in `supersedes`, with its `reason`, and both are kept.
- **`question`**: `text`, `state` (`open`, `answered`, `withdrawn`), optional `answer` and
  `evidence`.

An update is a list of operations applied together or not at all: `put` (create, or replace a
record's content, given `base_rev`, the revision it was read at), `delete` (a draft or an unused
record), `submit` (a draft finding), `supersede` (a submitted finding, with `reason` and the new
`record`), `resume`, `mode` and `exposure`. An edit made from an older revision of a record is a
conflict: nothing is applied, and the answer (and `conflicts`) holds both versions; edits of
different records are both kept. Writes replace the file atomically under a lock file beside it.

**Currency.** Evidence on a declaration is pinned to its `fingerprint` and to a `digest` of that
fingerprint with those of the constants Lean generated for it (`N._f`, `N.match_1`, `N.eq_1`), which
carry a definition's equations. Against a later build, evidence whose digest changed is `stale`,
and so is every finding or question that cites it, and every finding whose claim's printed text
changed; the others stay `current` (`unchecked` when the build shows no fingerprint). The saved
records are not re-pinned silently: a `put` with `repin: true` re-pins a record to the current
build.

**Mode and exposure.** An informed workspace records at its creation that the Lean and prior
interpretations were open to its auditor; it has no locked reading. A mode change and an import
add exposure and never remove it. A report made with `machinechecked review` lists that exposure in
`reading.revealed_by`, so `review promote` refuses it unless the maintainer passes
`--allow-revealed`.

**Export and import.** `workspace export` writes the whole workspace (less `ops`) as one file;
`workspace import` keeps its id, authors, pins, mode and exposure. Into a workspace already
present, it adds the records that are missing and keeps a record both hold in different versions
as it is, listing the other under `conflicts`. References the current build cannot resolve are
reported as `problems`. A workspace is not part of a published audit.

## Links file (`machinechecked.links.json`), written by people, the reader and `link`

Per paper key (the paper's path in the project, or its URL), per claim key: `lean` (the confirmed
list), `rejected` (suggestions declined) with optional `rejected_reasons` (`{name: {reason, by,
at}}`), the correspondence reading (`note`, `coverage`, `confidence`, `basis`, `refs`,
`argument`, `bridge`, `question`, `would_decide`; see above), `by` and `at`. When the confirmed
list changes, the reading written for the old list moves to `earlier_notes` (with the list it
described), where it is kept and no longer shown. `machinechecked link` and the reader's
buttons write it through the same checks (`authoring.py`), refusing a write when the claim's entry
changed after the request was prepared.

## Identifiers

- Claim: `<paper>:<label>`, else `<paper>:<env>-<number>`.
- Release: `r-<first 12 hex of the evidence id>` unless named.
- Permalink: `#/r/<release>/claim/<claim id>` or `#/r/<release>/read/<paper>/<claim id>`.
