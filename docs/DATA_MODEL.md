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

**Paper units.** A claim is a `statement` unless its `unit` says it is a `proof-equation` (a
display inside a proof) or a `proof-passage` (a selected stretch of a proof); a claim recorded by
line whose scope is `proof-step` and that gives no `unit` is a proof equation when its pinned
region is a display environment and a proof passage otherwise. A proof step names its enclosing
result in `parent`, and may record the Lean that establishes it and the different formal route
used instead:

```json
{"id": "T:eq:bound-range", "paper": "T", "kind": "equation", "number": "Equation (3)",
 "unit": "proof-equation", "parent": "T:thm:bound", "location": "toy.tex:75",
 "source_region": {"end_line": 78}, "source_hash_scheme": "tex-region-v1",
 "source_sha256": "…", "scope": "proof-step", "scope_reviewed": true, "clauses": [],
 "lean": ["…"], "coverage": "full", "basis": "direct", "note": "…", "by": "…",
 "route": {"lean": ["Toy.Acceptance.thm_bound"], "note": "…", "by": "…"}}
```

`lean` lists the declarations that state the step as printed, with `coverage` (`full`, `partial`,
`changed`, `related`, `unresolved`; a stored `composed` reads as `full`) and `basis` (`direct`,
`reviewed_composition`, `checked_bridge`). `route.lean` lists declarations that reach the parent
by another argument. The probe checks both (as `link` records, `lean.links` in the evidence).
None of these fields is an input to a status: a step's status is its scope decision's, and its
review is its own (below).

A claim's `location` is a file for a numbered environment, whose `source_sha256` is the hash of
the whitespace-normalised body of the environment, or `<file>:<line>` for a claim recorded by
line (an equation, a part of an environment, a prose claim), whose pin is the source region that
starts there, and may list further passages and macro definitions in `source_parts`
([SOURCE_REGIONS.md](SOURCE_REGIONS.md)).

## Reviews, written by people

Markdown files with markers:

```
<!-- spec-review: <proposition> <hash> by=<reviewer> [kind=human|ai] [source=<claim>@<sha256>]... -->
<!-- def-review: <definition> <hash> by=<reviewer> [kind=human|ai] [source=<claim>@<sha256>]... -->
<!-- step-review: <claim id> <source sha256> verdict=holds|gap|false|undetermined by=<reviewer> [source=<claim id>@<source sha256>] -->
```

`<hash>` is the `legacy_hash` or the `pl-fp-v1:` fingerprint the review was made at. Each
`source` names a claim whose passage the reviewer read (a claim that states the proposition, or a
definition claim that names the definition) and the digest of that passage as read, its
`source_sha256` pin; a declaration no claim names has none. The claim id is everything before the
last `@`, so an id may hold `@`; `build` refuses a claim id with white space or `-->`, which no
marker can carry, and zero configuration percent-encodes them in the ids it makes. A marker
without `source` is read as the [evidence policy](EVIDENCE_POLICY.md#a-review-is-a-reading-of-a-text)
says; one with `source=none` read none of the passages. A marker written
`<!-- retired spec-review: ... -->` (`inventory retire --markers`) records no review and still
closes its review text. The section the
marker closes is the text of the review. The last marker of a declaration, reading the files in
order (a directory's `.md` files by name), is its current record.

A `step-review` marker records a review of a printed proof step; its hash is the digest of the
step's source text as read, and `review promote`, which writes it from an accepted report of the
queue's unit `step:<claim id>` (whose `pins.fingerprints.source` is that digest), also writes it
as the marker's `source`. It is current by the same rule: while that digest is the step's current
pin. The assessment records each proof step's review from its markers (`step_review`); it is
never an input to a status. In zero configuration, a step's review is such a report kept in the
project's `machinechecked-reviews/` folder.

A review report (`prooflens/review-report@1`) pins the same digests as `pins.source_sha256`
(claim id to digest), taken when the reading is locked; `review promote` refuses a report whose
digests are missing or differ from the current ones.

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
| `assessment` | per claim: status and clauses (for a proof step, also its `step_review` from its markers); all findings |

A pretty-printed Lean term (a binder's type, a conclusion, a signature) is `{text, segments}`:
each segment is a piece of the text, with `ref` when it names a constant and `var` when it is an
occurrence of one of the statement's own variables (the index, in `binders`, of the binder that
introduced it). A conclusion that is a conjunction, disjunction or equivalence also has
`logic`, a tree of `{op, args}` whose leaves are `{leaf: {text, segments}}`. A term also lists its sub-terms as `terms`, ranges `{from, to}` of its segments (outer before inner; none for a very large term), so that a reader can select a whole sub-term. Both are for
display: no status, fingerprint or hash reads them.

An object of a statement whose type is a subtype, structure or class with a field that is a
proposition (a prefix binder that is not a hypothesis, or a `forall`/`exists` node of `logic`)
has `properties`: every field of its type, inherited ones included and each once, projected from
the object, as `{field, kind, structure, declared_in, inherited, projection, module, range, term,
type}`. `kind` is `data` or `proposition`; `type` is the field's type at the object (for a
proposition, what it states), with identities prefixed by the object's identity and the field
(`<id>#<field>:`). At most 32 are listed (`properties_omitted` counts the rest); a failed
extraction is `properties_error`. A hypothesis whose type is a structure of propositions (a
class such as `[IsProbability Ω]`; not a conjunction or an equivalence) has the same
`properties`: what its fields state. A hypothesis lists as `objects` the objects quantified inside it
whose type carries a property, each `{op, name, id, type, scope, properties}`, with the
connectives that enclose it (`scope`): they belong to the hypothesis. The reader shows a given
object's properties as included in its type, a witness's as established with it (an object under
a negation, an alternative, an equivalence or the premise of an implication keeps them local to
that clause), and an object inside a hypothesis inside that hypothesis.

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
In the reader's data, each expansion is a file of its own, `data/expansions/<key>.json`, where
`key` is the first 24 hex digits of the SHA-256 of its canonical JSON; a statement, declaration
or expansion refers to it as `{at, id, name, key}`, and the reader fetches it when it is opened.
An expansion that recurs is written once. A published audit's loader fetches every expansion
its claims and declarations refer to and checks each against its key.

## Changes between releases (`prooflens/changes@1`), derived

`machinechecked changes --json`, and `data/changes.json` of a site or an export whose release
has an earlier one (the index names it as `changes`). It compares two evidence records and is
derived from them alone; no status, fingerprint or gate reads it.

| Field | Content |
|---|---|
| `from`, `to` | each release: `release`, `evidence`, `created`, `project` (`commit`, `dirty`), `lean_inputs_sha256`, `lean`, and per paper its `revision`, `mode`, `pdf_sha256`, `paper_version` |
| `paper_changed`, `lean_changed` | per paper, and for the Lean project, whether the two releases differ |
| `claims[]` | per claim of either release: `claim`, `paper`, `number`, `kind`, `scope`, `status` (`from`, `to`: each `{status, status_code}` as its build computed it, or null), `paper_change`, `lean_changed`, `lean`, `evidence`, `due` |
| `paper_change` | `class`, `reason`, `context` (the further passages or notation definitions that changed: `what`, `change`, `from`, `to`), `repinned` (when the inventory's pin changed: `from`, `to`, `passage`, `context`), `proposed` or `candidates`, `pin`, and the passage of each build (`from`, `to`: `location`, `bounds`, `sha256`, `passage`, `parts`, `notation`, `pin`, `matches_pin`; `from` is `"same"` for an unchanged passage) |
| `lean[]` | per clause: `clause`, `in` (`both`, `earlier`, `later`), `proposition`, `definitions` (those that changed), `definitions_unchanged`, `proofs` (with `role` and `check`); each `{name, change, from, to}` with each build's `fingerprint`, `legacy_hash`, `source_sha256` and `text` |
| `evidence[]` | per review: `target` (`spec`, `def`, `step`), `name`, `clause`, `from` and `to` (`state`, `marker`: `by`, `kind`, `file`, `line`, `hash`, `source`; `"same"` for a kept marker), `outcome`, and `because`, `question`, `caveat`, `kept_through` |
| `declarations[]` | every project declaration whose statement or proof changed, or that one release has alone: `name`, `change`, `from`, `to`, `claims` |
| `counts` | per paper class, per evidence outcome and per declaration change, and `status_changed` |
| `workspace` | with `--workspace`: the workspace's records that are not current, of every kind, the claim's requirements, fragments and alignments included (`id`, `kind`, `claim`, `state`, `changes`, `pinned_release`; `submitted` for a submitted finding, `proposed` for a proposed fragment) |

The export keeps a passage's places and text only when its paper publishes its source text, the
Lean `text` only when every paper publishes its Lean, and a marker's `file` and `line` only
with the reviews.

## Manifest (`manifest-index.schema.json`, `manifest-claim.schema.json`), derived

The current format is `prooflens/manifest@1`; older display data must be rebuilt.
See [the structured status contract](STATUS_CONTRACT.md) for the complete code inventory.

`data/index.json` lists the papers, every claim's `status_code`, derived status/class and anchor, the summary and the
findings counts. `data/claims/<file>.json` holds one passport: the printed statement (and its
display `excerpt`, when the paper publishes its source text), each
clause's unfolded statement, proofs, witness, regimes, reviews and structured `evidence`, the
declarations of its closure, and its findings. A clause also lists `witness_defs`, the
declarations only its witnesses use that have no current review (`{name, witnesses, state}`),
and a definition claim's clause `witness_candidates`, the witness-only declarations that use a
definition it maps (`{name, uses, witnesses}`). A claim is loaded only when it is opened.
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

Every index row and passport has `unit` and `parent`, and the index has `units`: per paper and
per unit kind, how many claims have each status, so statements and proof steps are counted
apart. A proof step's row also has `step_review`. A proof step's passport has `step`:

| Field | What |
|---|---|
| `unit`, `parent` | its kind, and its enclosing result (`id`, `number`, `file`) |
| `source` | its `location`, `region` and `sha256`: the exact pinned source |
| `links` | the declarations that establish it, each with its `link.*` status and statement |
| `correspondence` | `{source, coverage, basis, confidence, note, by}` of those links, or null |
| `route` | `{links, note, by, source}`: the different formal route used instead, or null |
| `review` | `{state, finding, reports}`: `unreviewed`, `holds`, `gap`, `false`, `undetermined`, or `stale` when every report was made on other source text; `finding` is the latest report on the current text |

A step's passport also has its printed text (`statement_tex`) and its context in the proof
(`context_tex`): from the proof's opening (at most 40 lines before the step) to the sentence after
it. A parent's passport lists its steps (`steps`: id, number, unit, status, review state, linked
and route names). In zero configuration the links file holds a step's links under its label
(`lean`, with `coverage`, `basis`, `note`, `by`) and its formal route under `route`
(`{lean, note, by}`); a step whose only links are a formal route has the status
`link.other-route`. An export keeps all of this, the Lean statements only when the Lean is
published, the reviewers' texts only when reviews are, the source text and location only when the
source is.

A paper page (`prooflens.paper.write_paper_site`, used by machinechecked.org) is written in the
same format, with `mode: "paper"`: the paper's registry entry (`paper`), the Lean projects that
state they formalise it (`projects`, as `owner/repo`), and the statements found in its PDF, each
with its links (each naming its `repository`) and, per project, the status that project's links
give it (`by_project`). Without an audit nothing has run Lean, so a linked statement reads
"linked: Lean not checked here (no audit published)" (class `declared`). No statement text is
written.

`audit_order` lists the page's loaded audits that pin the same version as the first, in the order
the reader draws on them, and `audit_order_by` says what orders them: `stars` (the site's GitHub
star count for every one, given to `write_paper_site` as `stars` and kept in `stars`; most first,
ties in listing order) or `listing` (the registry's order). The first is the default audit, whose
status is each claim's top-level `status`. With several, the reader shows each claim through the
first audit that maps it (whose record of the claim is in `by_project`), labelled with that audit;
choosing one project shows only its evidence, and a claim its audit does not map is marked. A
claim's statuses from different projects are never combined.

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
| `audits` | the audits of that version: `url` (https), `author`, `repository`, `commit` (the audited project commit, 40 hex digits); optional |

`page_versions` checks the list and sets each `label` from `kind` and `id` ("arXiv v1", "Latest
manuscript (commit abc1234)"), ignoring a label the site gives. Every audit loaded for a page
must pin that page's version: load it with the listing's `version` (`load_published_audit`), and
`write_paper_site` refuses one that pins another. The reader shows a version drop-down beside the
project selector when there are several versions: choosing one opens that version's page, with
the chosen project and without the claim (claim numbers can differ between versions); a link to
a claim opens it in its own version's page. Statuses belong to each version's page, so switching
never changes one.

**Claim maps between versions.** `write_paper_site(..., claim_maps=[...])` takes maps that relate
the claims of two versions. Each map has `from` (the earlier version's `id`), `to` (the later
version's) and `claims`. Each entry of `claims` names claims on each side (`from` and `to`, lists
of `key` and `number`, where `key` is the claim's key on that page, such as `theorem-3`) and its
`change`:

| `change` | Claims (`from` → `to`) | What it says |
|---|---|---|
| `same` | 1 → 1 | the same statement, under the same number |
| `renumbered` | 1 → 1 | the same statement, under another number |
| `changed` | 1 → 1 | the statement changed |
| `split` | 1 → 2 or more | the claim became several |
| `removed` | 1 → 0 | the later version does not have it |
| `new` | 0 → 1 | the earlier version does not have it |

A listing can supply the map. `claim_map(earlier, claims, later, claims)` can also compute it
from the two versions' claim inventories, where each claim gives `key`, `number`, and optionally
`label` (its source pin) and `statement` (its text). It matches a claim by its label, or else by
its statement text when exactly one claim of the other version has that text. It maps only claims
that have a statement, and never infers a split. `check_claim_map` refuses a change that does not
fit its claims.

Each claim a map names gets `counterparts` on its row of `index.json`, provided the page offers
the other version. Each counterpart gives `version`, `later` (whether the other version is the
later one), `change` and `claims` (`id`, `number` on the other page). The claim view shows it,
for example "Theorem 3 in Latest manuscript (commit abc1234), statement changed", and links
the number to that claim on the other version's page. A claim the map does not name shows
nothing. A map never changes a status.

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
  {file, line}}`, `{paper: {claim, quote}}`, `{app: {...}}`: an application of a declaration, as
  `compare --query uses` gives it (`callee`, `module`, `id`, `caller`, `via`, the `arguments`
  and `premises` with how each is supplied, the `result`, and `app_hash`, a digest of them; it is
  `stale` once the caller elaborates it differently, `unchecked` until the uses are read again
  after a Lean change), or `{fact: {...}}`: a fact inside a proof, as
  `compare --query proof-facts` gives it (`decl`, `module`, `at` its position in the proof term,
  `fact_hash` its proposition with the locals it needs, `proof_hash` the whole proof, and to read
  it without Lean `kind`, `name` or `head`, `type`, `assumptions`, `variables`, `cases`, `source`
  and `basis`, always "established inside this proof under this context"). A cited fact is
  `stale` once the proof's hash changes, and `unchecked` until the proof is read again after a
  Lean change. `{certificate: {...}}` is a Lean certificate (`theorem`, `target`, `certifies`:
  `proves` when the theorem's type is exactly the target, `refutes` when it is its negation;
  checked by the probe when recorded, keeping `type`, `target_statement`, `target_fingerprint`,
  `file`, `file_sha256`, `axioms`, `lean`, `toolchain`, `manifest_sha256`, `result` and
  `reasons`); it is `stale` once its source file, its checked type, its target or the result
  changes. `role` is `candidate` (the default), `supports`,
  `context` or `rejected` (with `why_rejected`). A candidate is a candidate until the auditor
  gives it another role.
- **`finding`**: `coverage` (the links file's words: `full`, `partial`, `changed`, `related`,
  `unresolved`), optional `basis` (`direct`, `reviewed_composition` with an optional `argument`,
  or `checked_bridge` with `bridge: {theorem, target}`), optional `confidence`, `evidence` (ids
  of evidence records of the same claim, which the basis rests on) and, when unresolved,
  `question` and optional `would_decide`. A finding that rests on a fact inside a proof (a
  `supports` evidence with a `fact` reference) cannot have basis `direct`: that fact is not an
  exported statement. A `composed` coverage is recorded as `full` with basis
  `reviewed_composition`. A finding may rest on a `composition` of the same claim (its id): its
  basis is then `reviewed_composition`, or `checked_bridge` when the composition carries a
  bridge, and full coverage needs the composition complete (checked again at `submit`). Shown
  while the bridge is not checked, a `checked_bridge` finding reads as `reviewed_composition`
  (with `recorded_basis`). A finding may also record a `difference` on its `requirement`
  (`{feature, paper, lean, outcome, conditions, transport, resolution, why, hint}`), a `verdict`
  on a printed step (`holds as printed`, `holds, with a gap in the argument`, `false as
  printed`, `cannot determine`) and the `counterexamples` it rests on (pinned by digest); such a
  finding is submitted without a coverage. `state` is `draft`
  or `submitted` (`submitted_at`). A submitted finding is never edited or deleted: a later
  finding names it in `supersedes`, with its `reason`, and both are kept.
- **`question`**: `text`, `state` (`open`, `answered`, `withdrawn`), optional `answer` and
  `evidence`.
- **`requirement`**: one thing the claim demands, as the auditor reads it. `local_id` (unique
  under the claim, e.g. `r1.2`), `form` (`statement`, `object`, `assumption`, `conclusion`,
  `condition`, `for every`, `there is`, `and`, `or`, `not`, `implies`, `constant dependence`,
  `definition`, `other`), `text`, optional `parent` (the requirement it sits inside: its scope),
  `binds` (the variables a `for every`, `there is` or `constant dependence` introduces),
  `domain` (the values its variables range over, in words: `ε > 0`), `independent_of`
  (variables a constant or witness may not depend on: it is chosen before them), `depends_on`
  (variables a constant may depend on: it is chosen after them) and `origin`: `printed`,
  or `correction` with `corrects` naming the printed requirement, which stays as printed. A
  finding or a question may name a requirement in `requirement`.
- **`counterexample`**: an auditor's counterexample to one reading of a requirement
  (`estimates.py`). `requirement`, optional `reading` (the corrections it is read with),
  `specialisation` (`assign`: a value, number or expression, for each variable; `zero`,
  `dimensions`, `limits`, `other`), `reduced` (the obligation it reduces to), `violation`,
  `admissibility` (`{obligation, state: verified | open | fails, method}`), optional `samples`
  (numeric assignments, kept as samples) and `evidence`. The service pins `obligation_sha256`
  (the reading: the order of its variables, their domains, the constants' dependence, the
  requirements' texts and the pins of the passages that govern them) and `evidence_pins`; a
  change to either makes it `stale` until it is re-pinned.
- **`fragment`**: a passage a requirement comes from. `requirement` (its local id), `role`
  (`statement`, `quantifier domain`, `constant dependence`, `standing assumption`,
  `definition`, `earlier choice`, `cited result`, `context`, `later use`, `proposed
  correction`), `origin` (`printed`: the paper states it for this claim; `inferred`: an
  attachment the auditor or a suggestion infers; `correction`), optional `scope` (where it
  applies, in words) and `note`, and exactly one of `region` (`{paper, file, start_line,
  end_line, start_column, end_column}` in the build's snapshot of the paper's source,
  `<work dir>/sources/<paper>/`, with its `text`, `sha256` and `line_sha256` as
  `source_regions.py` computes them, recorded when written) or `passage` (`{claim, sha256}`: a
  claim's whole printed passage). `state` is `accepted` (the default), `proposed` (a
  suggestion, with `suggestion: {rule, by}`) or `removed` (with `why_removed`, kept);
  `state_by`/`state_at` record who set it. A `later use` is shown as a use and does not enter
  the requirement's reading.
- **`alignment`**: `requirements` (local ids; none only for an `additional assumption` of the
  Lean), `lean` (targets: `{decl}`, or a part of its statement as the build prints it: `var`,
  `binder` (a variable's type or a hypothesis), `at` (a sub-term's identity) or `conclusion`;
  each with `build`, `fingerprint`, `digest` and the `target` text) and `relation`
  (`corresponds`, `additional assumption`, `changed`, `alternative representation`). A
  requirement may have several alignments and a target may serve several requirements.
- **`composition`**: an argument that several results together cover the claim
  (`composition.py`). `steps`, in order, each `{id, establishes, requirements, uses, after,
  substitutions, inference, note}`: what it establishes, the requirements it establishes (with
  those inside them), the evidence it rests on (a `decl`, `app` or `fact` reference that is not
  rejected) and the earlier steps it follows from (one of them at least), the substitutions it
  makes (`{variable, value, in}`, `in` an evidence id of the step) and any inference of the
  auditor's own. `identifications` (`{left: {step, object}, right: {step, object}, relation,
  how}`; `relation` is `same object`, `equal`, `restriction`, `coercion` or `other`; `how` is
  `retained witness`, when the right step follows from the left, `evidence`, with the
  `evidence` that shows it, or `definition`). `obligations` (`{id, kind, text, state, by}`;
  `kind` is `compatible witnesses`, `local to global`, `equality transport`, `constant
  dependence`, `genericity`, `side condition` or `other`; `state` is `open` or `discharged`, with
  `by: {steps, evidence}`). `evidence` is computed: every evidence id it uses. Optional
  `statement` (the combined statement, in words) and `coverage`; `full` is refused while a
  printed requirement of the claim is established by no step, an obligation is open, or the
  claim has no requirements recorded. The basis is never written: `workspace show` gives it as
  `reviewed_composition`, with `next_step`, or `checked_bridge` while the `bridge` is checked,
  with `gaps` (`requirements`, `uncovered`, `open`) and `complete`. A `bridge` is `{theorem,
  target}`: Lean checks it when it is written (the probe's `accept` request, the links file's
  bridge check, answered from the facts store), and one whose type is not exactly the target, a
  proposition stated as a definition, with no `sorry` and only allowed axioms, is refused. It is
  kept with `module`, `type`, `axioms`, `checked_at` and its pins: `target_fingerprint` (the
  target and the definitions its statement uses) and `source_sha256` (the claim's passage).
  `bridge_check` says whether it is `checked`, `stale` (the target or the passage changed since)
  or `unchecked` (not read since the Lean last changed; `workspace show` asks Lean). A composition
  a submitted finding rests on is not edited: record a new one and supersede the finding.

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
changed; the others stay `current` (`unchecked` when the build shows no fingerprint). A fragment
whose region of the source now reads differently (the lines that changed are listed), or whose
claim's passage changed, is `stale`, and so is an alignment whose declaration changed, and every
requirement they belong to, and every finding or question that names that requirement. The saved
records are not re-pinned silently: a `put` with `repin: true` re-pins a record to the current
build.

**The reading.** `workspace show --json` gives each claim's `reading`: its requirements in
reading order (with `depth`, `children`, their fragments grouped as `governing`, `later_uses`,
`proposed` and `removed`, their alignments, `currency`, `questions` such as a requirement with no
source, and `reading_sha256`, a digest of the form, words and governing fragments' pins); the
`estimates` block (each requirement with a counterexample, a verdict or a difference: its
printed reading and each corrected one, as an obligation with its variables in order, the
counterexamples analysed against it (`form`: family, instance, fixed constants or incomplete;
`standing`), its findings and certificates, and specialisations to try from the domains; the
differences recorded, open apart from resolved; the computed hints, and the hypotheses inherited
from standing assumptions); the `witnesses` (each `there is`, its `scope`: `produced`, `assumed` inside an assumption,
`denied` inside a `not`, or `alternative` inside an `or`; the variables it is chosen `after` and
`before`; its `conditions`); and the `alignments`. `workspace suggest` proposes fragments from the
passage's neighbourhood (the sentence before and after it, quantifier or dependence wording
inside it, the prose opening its section, the claims it cites); a proposal is a guess until
accepted.

**Mode and exposure.** An informed workspace records at its creation that the Lean and prior
interpretations were open to its auditor; it has no locked reading. A mode change and an import
add exposure and never remove it. A workspace's exposure is that of everyone it records as having
worked in it: its `reviewer`, the authors of its records and of its edits (refused ones in
`conflicts` too), whoever set its `resume`, and the people its `provenance` names (who changed
its mode or imported it). A report made with `machinechecked review` lists, in `reading.revealed_by`, the exposure of
every workspace of the working directory its reviewer has worked in, and the units whose step 2
or 3 the reviewer's review work in any of their workspaces reached and whose material includes
the unit's; an entry an import brings after the reading was locked counts when its `at` is not
later than the lock. So `review promote` refuses the report unless the maintainer passes
`--allow-revealed`.

**Export and import.** `workspace export` writes the whole workspace (less `ops`) as one file;
`workspace import` keeps its id, authors, pins, mode and exposure. Into a workspace already
present, it adds the records that are missing and keeps a record both hold in different versions
as it is, listing the other under `conflicts`. References the current build cannot resolve are
reported as `problems`. A published audit carries the accepted records of every workspace in
the working directory, below; the workspace itself stays local.

## Published workspace records (`prooflens/published-work@1`), written by the export

`machinechecked export` (and `build --site`, `check --site`) writes, for each claim with any,
`data/work/<claim file>`, and the claim's passport names it in `work` (`"work/<claim file>"`).
`engine/python/prooflens/published_work.py` writes it; `published-work.schema.json` describes it.
The file is `{schema, release, claim, readings}`; each reading is one workspace's accepted
records for the claim:

| Field | Content |
|---|---|
| `workspace`, `mode` | the workspace id and its mode (`independent` or `informed`) |
| `reviewer` | `{id, kind, name, model, identity}` of the workspace's reviewer |
| `requirements` | every requirement of the claim, in reading order, with `depth` |
| `fragments` | the passages with `state` `accepted` (governing ones and later uses) |
| `alignments` | every alignment |
| `findings` | the submitted findings, superseded ones included, each with `in_force` |
| `evidence` | the evidence records those findings and compositions cite |
| `compositions` | the compositions those findings rest on, with `basis`, `gaps`, `complete`, `next_step` and `bridge_check` |

Each record keeps the workspace fields above (`id`, `kind`, `claim`, `clause`, `rev`,
`created_at`/`created_by`, `updated_at`/`updated_by`, `pins`, and its kind's fields) and gains
`currency` (`{state, changes}`: `current`, `stale` or `unchecked`), computed against the published
data over the published records alone. Proposed and removed fragments, draft findings, evidence
no submitted finding cites, questions, `exposure`, `resume`, `review`, `conflicts`,
`provenance` and `ops` are not published.

The paper's `publish` settings apply. Without `source_text`, a region keeps only `paper` and
`sha256` (no `text`, file or lines), a changed region's entry in `changes` loses its location,
and a `paper` evidence reference loses its `quote`. Without `lean`, an alignment target loses its
`target` text, a `source` evidence reference its file and line, and a `fact` evidence reference
its `type`, `assumptions`, `variables`, `cases` and `source` (its declaration, position, pins and
`basis` stay). A cited fact's (or application's) currency needs the Lean project, so it is
published as `unchecked`; an `app` reference keeps its arguments, premises and result only with
`lean`. A composition keeps its steps' ids, requirements, evidence and order, its
identifications' steps and how they are known, and its obligations' kinds, states and discharges;
its objects and substitutions only with `lean`; its statement, what each step establishes, the
inferences, obligation texts and notes only with `reviews`. Its basis is `checked_bridge` only when
the bridge is checked at export against the project's facts store; otherwise
`reviewed_composition`, and a finding recorded as `checked_bridge` on it reads the same way. Without `reviews`, `note`,
`argument`, `question`, `would_decide`, `reason` and `why_rejected` are left out. The export
scans these files with the rest. A claim file larger than 2 MB is refused.

A site loading an audit (`load_published_audit`) reads the file the passport names (only
`work/<the claim's file>`), checks it against the schema and that its `claim` and `release` are
the passport's, and puts it in the claim's record as `work`. The reader shows the readings on the
claim, read-only and attributed. They are never an input to a status.

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
