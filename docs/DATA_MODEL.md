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
`reviewed_composition`, `checked_bridge`). A step with no `lean` keeps only an `unresolved`
coverage, whose open question may be whether any Lean states the step, and no basis.
`route.lean` lists declarations that reach the parent by another argument. The probe checks both (as `link` records, `lean.links` in the evidence).
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
says; one with `source=none` (which an earlier `inventory retire` wrote, and which
`inventory retire --markers` repairs from the history) read none of the passages. A marker written `<!-- retired spec-review: ... -->` (`inventory retire`) records no
review and still closes its review text. The section the
marker closes is the text of the review. The last marker of a declaration, reading the files in
order (a directory's `.md` files by name), is its current record. When it is at another hash
and an earlier marker would count, the review's state is `stale` with `why` `shadowed`, and
`shadowed` gives both markers (`reading` and `record`, each `{file, line, hash, by}`).

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

A report's `correspondence` is the coverage its reviewer recorded with the verdict (at
`comparison.decided_at`), or `null`; an older report has none, and its coverage is not recorded.
It has `coverage` (the links file's words, agreeing with the verdict's group: `full` or
`partial` for a match, `partial`, `changed` or `related` for a problem, `unresolved` for *cannot
determine*), and optionally `basis` (`direct`; `reviewed_composition`, with an optional
`argument`; `checked_bridge`, with `bridge: {theorem, target, target_fingerprint}`, the theorem
one of `unit.lean`) and, when unresolved, `would_decide`. The open question is
`verdict.detail`. `target_fingerprint` is the target's version in the build the reviewer was
shown (`correspondence.bridge.current` of the claim, below), or `null` when the claim's links
record no such bridge. A proof step's report has none. `review promote` refuses a report whose
`correspondence` is not one the protocol writes, or whose coverage is unresolved, and writes the
same marker with or without one. In zero configuration, each report a passport lists
(`reviews[]`) carries it as `correspondence`, in the form of the claim's own (`{coverage, basis,
refs, argument, next_step, bridge, question, would_decide}`), or `null`; a checked bridge
reads as one while the report is current, the claim's links record the same bridge, Lean checks
it and `target_fingerprint` is the target's current version, and otherwise as
`reviewed_composition`, with `recorded_basis` and `basis_reason`.

Dismissals of warnings (`dismissals.json`):
`[{"code", "subject", "trigger", "fingerprint", "rationale", "by"}]`. A dismissal of a
totalisation warning about one application also has `at` (the warning's `at`), and its
`fingerprint` is the application's (`pl-occ-v1:…`); without `at` it names the operation in the
whole proposition and its `fingerprint` is the proposition's ([ASSURANCE.md](ASSURANCE.md)).

## Evidence (`evidence.schema.json`), written by the engine

`.machinechecked/releases/<release>.json` names a release: `{release, evidence, created}`.
`.machinechecked/release-log.jsonl` has one line `{release, evidence, at}` per build or
reassessment, for the release it produced or reproduced (a build that stores evidence an earlier
build stored names that build's release again, and so does a reassessment that changes
nothing, whose record would differ from the one it read only in `reassessed_from`). The
latest release is the release of the last line whose release still names that evidence; in a
store without the log, the release created last. The release before a release, which
`changes` and a site's `data/changes.json` compare it with, is the last release with other
evidence among those built before its last build; when the log names none, the last release
with other evidence created before it. Releases are ordered by
`created`, and those created in the same second by the log, then by name; no file time is read,
so copying or restoring `.machinechecked/` changes no command's release.

`.machinechecked/evidence/<id>.json` (`.prooflens/` in older projects), with `id` the SHA-256 of the canonical JSON of `body`:

| Field of `body` | Content |
|---|---|
| `provenance` | tool, Lean, project and dependency revisions, each paper's source and PDF hashes |
| `inventory` | the inventory as read |
| `reviews` | the review files' hashes and every parsed marker |
| `dismissals` | as read |
| `lean` | the probe records: specifications (the statement's tree, binders, conclusion, closure, constants, hashes), proofs (exact-type check, axioms), declarations (signature, value, definition content, authored source, doc, hashes, `proposition`: whether the type is a proposition, null when Lean could not tell; `auto_param`: whether it is the tactic script of a tactic default), layering |
| `tex` | per paper: mode, page size, anchors (env, number, labels, file:line, begin/head/end positions, source hash), files read, source regions, the text of the passage of each claim located by line (`region_text`), and the display excerpts of its claims (`excerpts`, [SOURCE_REGIONS.md](SOURCE_REGIONS.md#display-excerpts)) |
| `assessment` | per claim: status and clauses (for a proof step, also its `step_review` from its markers); all findings; `unlisted_modules` (when there are any): each declaration the probe did not find that project modules missing from `modules` declare, with those modules, which `check --fix-modules` reads |

A pretty-printed Lean term (a binder's type, a conclusion, a signature) is `{text, segments}`:
each segment is a piece of the text, with `ref` when it names a constant and, when it is an
occurrence of a variable, `at`, the identity of that occurrence (its position, as for a sub-term
below), and `var` when the variable is one of the statement's own (its number, below). A term
also lists its sub-terms as `terms`, ranges `{from, to}` of its segments (outer before inner; none
for a very large term), so that a reader can select a whole sub-term.

A statement record holds the whole proposition as one tree, `tree`. Its `binders` (the binders
that open it, each `{role, name, id, type, binder, supplies}`, `role` one of `forall`,
`hypothesis`, `instance`, `exists`) and its `conclusion` (the rest, printed whole) are read off the
same tree. A node of the tree is a connective `{op, id, args}` (`and`, `or`, `iff`, `not`, or
`implies` with its premise and its conclusion), a leaf `{leaf: term}`, or a binder `{op, name, var,
id, binder, supplies, type, scope, within, after, args}` whose one part is its body. The binders
that open the statement come first, each with its role as `op` and its place in `binders` as
`var`. A binder inside the conclusion or inside a hypothesis is a `forall` or an `exists`, numbered
after them, those of the conclusion first, so that two variables of the same name never share a
number. `binder` is how it is written (`explicit`, `implicit`, `strict-implicit`, `instance`) and
`supplies` whether it binds an object (`data`) or a proof (`proposition`). `scope` is how it
stands, decided by the nearest negation, alternative, equivalence, premise or hypothesis that
encloses it (`denied`, `alternative`, `equivalent`, `assumed`); outside all of them a `there is`
is `produced` (the statement establishes it) and any other binder is `given`. `within` lists the
connectives around it, outermost first (`and`, `or`, `iff`, `not`, `if` and `then` for the two
sides of an implication, `assume` inside a hypothesis), and `after` the numbers of the objects
bound around it: those it may depend on. A hypothesis whose proposition has a connective or a
quantifier at its head has that proposition's tree as `logic` (a failure is `logic_error`), whose
nodes stand inside it. The tree and the terms are for display: no status, fingerprint or hash reads
them. Records written before the tree give the conclusion's shape as `conclusion.logic` and the
objects inside a hypothesis as `objects`; the reader and `symbols.tree` rebuild the tree from them.

An object of a statement whose type is a subtype, structure or class with a field that is a
proposition (a binder of the tree that binds an object) has `properties` on its node: every field
of its type, inherited ones included and each once, projected from
the object, as `{field, kind, basis, structure, declared_in, inherited, via, projection, module,
range, term, depends, type}`. `kind` is `data` or `proposition`; `type` is the field's type at the
object (for a proposition, what it states), with identities prefixed by the object's identity
and the field (`<id>#<field>:`). `declared_in` is the structure whose declaration states the
field (followed through a parent whose fields are copied because they overlap an earlier
parent's), `via` the parent projections from the object's structure to it, and `depends` the
numbers of the statement's variables its statement mentions. `basis` says why it holds of the
object: `type` (included in the object's type). At most 32 are listed (`properties_omitted`
counts the rest); a failed extraction is `properties_error`. A hypothesis whose type is a
structure of propositions (a class such as `[IsProbability Ω]`; not a conjunction or an
equivalence) has the same `properties`, with basis `premise`: what its fields state. The reader shows a given object's properties as included in
its type, a witness's as established with it, an object's inside a hypothesis as inside that
hypothesis, and any other object's (one `denied`, `alternative` or `equivalent`, or under a
premise) as local to the clause that contains it.

A private declaration is the project's like any other. Records name it as Lean stores it
(`_private.<module>.0.<name>`, in `name`, `uses`, `closure`, `ref` and expansions); the probe
tells it from a generated helper by the name its author wrote (Lean's `privateToUserName`); and
the reader shows that name. Lean prints it with a mark outside its module (`Shape.margin✝`).

A declaration record of a structure (a class included) has `structure`: `{class, params,
parents, fields, fields_omitted}`, its parameters (as a definition's `params`, identities
prefixed `type:`), its parents (`{structure, projection, subobject}`, in the order of its
`extends`) and every field, inherited ones once, in the form of `properties` above, stated of an
object `self` of the structure at its parameters (identities prefixed `self#<field>:`; the
parameters are the variables `0`, `1`, … and `self` the last). The fields `declared_in` the
structure itself are those it adds to its parents (`compare` groups them as `declares` and
`inherits`). A definition of data whose value is an object of such a structure (a construction)
has `result_properties`: the fields of its value at its parameters (identities prefixed
`result#<field>:`), with basis `definition`, since its value proves them. A failure is
`structure_error` or `result_properties_error`. Display only.

`compare` lists, for each statement, its objects (`statement.objects`, `objects.objects`): each
variable it binds to data, with its position (`given`, `produced`, `assumed` inside an
assumption, `premise` inside the premise of an implication, `denied`, `alternative`,
`equivalent`) and what the statement says about it, each part with its basis: `type` and
`premise` as above, `premise` also for a hypothesis or a premise that mentions it,
`conclusion` for a part of the conclusion (or of its clause) that mentions it, `definition` for a
definition applied to it (by its expansion), and `theorem` for a result a workspace's evidence
cites for that object (`object: {decl, var, id, name, type}`, pinned to the binder's identity).

A declaration record of a definition of data or of a predicate (not a proposition, an instance or
a generated helper) also says what the definition says. `defined_by` is `body` or `equations`.
With `body`: `params` (the leading `fun` binders of its value, each `{name, binder, id, type,
proposition}`), `body` (the term under them, with the sub-term identities it has in `value`) and
`result` (its type, identities prefixed `type:`). `equations` lists the equation theorems Lean
derives (`Lean.Meta.getEqnsFor?`), each `{name, statement, params, equation}`: the theorem's exact
statement, and its variables and the equation under them; their identities are prefixed by the
theorem's name. At most 1024 are read from Lean; `equations_omitted` counts the rest and
`equation_names` names all of them. In the reader's data and the export, a record lists the first
64; the others are in pages of 64 stored on their own (`data/expansions/<key>.json`,
`{definition, equations}`), to which `equations_more` refers in order as `{name, key}`, `name`
the theorem of the page's first equation; the reader fetches them when asked. A failed
extraction is recorded in `definition_error` and stops nothing else.
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
`equations_not_applying` names the others and `equations_omitted` counts those not compared
(every equation read from Lean is compared).
An expansion's own applications expand once more; a failure is `error` on that expansion only.
Only what is printed is searched (explicit arguments, not implicit or instance ones), up to
4000 nodes of a term; at most 16 applications of one term are expanded and `expansions_omitted`
counts the rest.
Expansions are display only and are exported with the statement, so only with the Lean.
In the reader's data, each expansion is a file of its own, `data/expansions/<key>.json`, where
`key` is the first 24 hex digits of the SHA-256 of its canonical JSON; a statement, declaration
or expansion refers to it as `{at, id, name, key}`, and the reader fetches it when it is opened.
The stored expansion also has `fingerprint`, the fingerprint of the definition it expands, so a
changed definition gives its expansions other keys even where they print the same. An
expansion that recurs is written once. A published audit's loader fetches every expansion and
page of equations its claims and declarations refer to and checks each against its key.

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
| `lean[]` | per clause: `clause`, `in` (`both`, `earlier`, `later`), `proposition`, `definitions` (those that changed; the tactic scripts of tactic defaults are left out), `definitions_unchanged`, `proofs` (with `role` and `check`); each `{name, change, from, to}` with each build's `fingerprint`, `legacy_hash`, `source_sha256` and `text` |
| `evidence[]` | per review: `target` (`spec`, `def`, `step`), `name`, `clause`, `from` and `to` (`state`, `marker`: `by`, `kind`, `file`, `line`, `hash`, `source`; `"same"` for a kept marker), `outcome`, and `because`, `question`, `caveat`, `kept_through` |
| `declarations[]` | every project declaration whose statement or proof changed, or that one release has alone, other than the tactic scripts of tactic defaults: `name`, `change`, `from`, `to`, `claims` |
| `counts` | per paper class, per evidence outcome and per declaration change, and `status_changed` |
| `workspace` | with `--workspace`: the workspace's records that are not current, of every kind, the claim's requirements, fragments and alignments included (`id`, `kind`, `claim`, `state`, `changes`, `pinned_release`; `unknown` for a finding not known to be current; `submitted` for a submitted finding, `proposed` for a proposed fragment) |

The export keeps a passage's places and text only when its paper publishes its source text, the
Lean `text` only when every paper publishes its Lean, and a marker's `file` and `line` only
with the reviews.

## Version map (`prooflens/version-map@1`), derived

`machinechecked changes --map --json` (`engine/python/prooflens/version_map.py`). It matches the
claims of one paper between two releases' revisions by their passages
([SOURCE_REGIONS.md](SOURCE_REGIONS.md#comparing-two-revisions-the-version-map)) and is derived
from the two releases' evidence and the two manuscripts alone; no status, fingerprint or gate
reads it, and the export does not carry it. A workspace may keep it (`changes --map --workspace
ID --save`, below).

| Field | Content |
|---|---|
| `paper` | the paper's id |
| `from`, `to` | each release: `release`, `evidence`, `revision`, `paper_version` (the audit's version identifier, as `audit.json` gives it), `manuscript` (where its text was read) and `checked` (how many of its claims' recorded digests the manuscript was checked against) |
| `counts` | how many entries of each class |
| `claims[]` | one entry per earlier claim, then one `new` entry per later claim no earlier claim is matched to |
| `numbers[]` | per earlier claim with a number: `old`, `new` (the later numbers: one for a match, each candidate's for an ambiguous claim, none for a removed one) and `match` (`class`, `by`, `from`, `to`) |
| `references` | the later release's references to paper numbers that disagree with its paper, each with `current` from the map (below); null when that build has no paper-number check |
| `new_passages` | labels the later revision has and the earlier has not, with their places |
| `passages` | with `--workspace`: each region of the paper the workspace attaches to a requirement (below) |

An entry of `claims` has `class` (`unchanged`, `moved`, `context-changed`, `changed`,
`removed`, `ambiguous`, `unknown`, `new`), `reason`, and `from` and `to`, each side's own record
of the claim, or null: `claim`, `number` (as that build's compiled paper prints it, else the
inventory's), `kind`, `label`, `scope`, `location`, `bounds` (`file`, `start_line`, `end_line`,
and `start_column`, `end_column` for a region), `sha256` (its own passage as printed),
`pin_sha256` (the digest of all the passages its pin lists, when there are several), `pin`
(`matches`, `differs`, `none`: the inventory's pin against that text), or `error` when the
passage cannot be read; and `recorded`, what that release's build recorded: `status`,
`status_code`, `source_matches_pin` and `reviews` (each `{target, name, clause, state, by,
kind}`). The two sides are never combined.

`by` lists how the match was found: `text`, `label`, `overlap` (the later claim is pinned
across the place found), `maintainer` (`--match`), and the proposals `line-diff`, `number` and
`id`. A match also has `renumbered` and `moved` when they hold, `change` (`where`, `diff`) for
a changed passage, `context` for what it is read with that changed (each `{what, change, from,
to}`, with `what` one of `passage`, `macro definition`, `macro`, `standing assumption`,
`definition`, `reference`; a macro or standing assumption has its `diff`, a claim relied on
its `claim`, `number`, `via` and the Lean `names`), `surroundings_changed`, and `resolved`
(`by`, `was`, `reason`, `candidates`) for the maintainer's. An unmatched entry has
`candidates` (each `{claim, by}`), `printed_at` (where its text or label occurs in the later
revision) and the repin plan's `proposed` bounds for a span; a `new` entry has
`candidate_for`.

The paper-number check reads `numbers` as a version map (`numbering.resolve`, with
`numbering_map` giving its `source`: the schema, paper and both releases). A reference to an
earlier number that disagrees with the later paper (`absent`, `other-kind`, or a possibly stale
lead) gets `current`: `reference` and `claims` for one counterpart (with `proposed` when its
claim is ambiguous), `ambiguous` for several, or `none` for a removed claim, with `source` and
`matches` (the map's entries for the number). Its status stays its own.

An entry of `passages` follows one region a workspace attached (a fragment's `region`, or one a
finding rests on as it was submitted): `region` (`paper`, `file`, `start_line`, `end_line`,
columns, `sha256`), `class` and `reason`. The repin planner looks for its text in the later
revision, as for a claim: `unchanged` or `moved` (with `to`: `location`, `bounds`),
`context-changed` when a macro it uses is defined otherwise (`context`), `changed` when no
passage has its text and the line diff of its file maps it to other text (`to` with `proposed`,
and `change`: `where`, `diff`), `removed` when it maps it to nothing, `ambiguous` when its text
occurs more than once (`candidates`); `later` when the earlier revision does not print its text
and the later one does at its place (it was attached at the later revision), else `unknown`.

## Findings across a revision (`prooflens/reopened@1`), derived

`machinechecked changes --map --workspace ID --json` gives it as `workspace`; `workspace show
--json` gives one per version map the workspace keeps to the build's release, under
`revisions.maps` (`engine/python/prooflens/reopen.py`). It judges the workspace's findings in
force through the map. No status, fingerprint or gate reads it.

| Field | Content |
|---|---|
| `workspace`, `paper`, `from`, `to` | the workspace, and the map's paper and revisions |
| `build_checked` | whether the build of the later release was there to check the Lean side |
| `counts` | how many findings are `reopened`, `unchecked`, `current` |
| `findings[]` | each finding of the workspace that rests on a passage of this paper |
| `evidence[]`, `passages[]` | each evidence record quoting the paper, and each passage attached to a requirement (not removed), judged as a finding's part is |
| `map` | under `revisions`: the kept map's `paper`, `from`, `to`, `kept_at`, `kept_by` |

A finding has `id`, `claim`, `finding` (what it records: `coverage`, `basis` as `workspace show`
gives it, `requirement`, `note` and the like), `kinds`, `earlier` and `later` (the claim's
`claim`, `number`, `location` on each side, from the map), `class` (the map's), `state`, `paper`
and, when the later build was checked, `build`. Each entry of `paper` is one paper part it rests
on: `dependency` (the item of its `dependencies`), `text` (in words), `earlier`, `later`, `class`
and `state`:

- `current`, with `note`: the map finds the same text (moved and renumbered or not), or the part
  was read at the later revision; or the context changed only in what the finding does not rest
  on;
- `reopened`, with `change` (`class`, `reason`, and `diff`, `where`, `context` as the map gives
  them; a claim relied on carries its own change as `claim_change`, and `through` names the cited
  declarations whose statements use its definitions) and `question`;
- `unchecked`, with `why` (and `candidates` for an ambiguous claim): the map cannot follow it,
  the part read another text than the earlier revision prints, or it records no version.

A definition claim the claim's Lean relies on (`via: ["lean"]`) concerns only a finding that
cites a declaration whose statement uses one of its definitions, and is unknown when the
finding cites one whose definitions were not recorded. `build` is `dependencies.check` against
the later build for the parts the map does not judge: `state`, `changes` (each with `words`,
`question`, and `statement`, `{from, to}`, when both releases are stored) and `unknown`. The
finding's `state` is `reopened` when a part is reopened or the build part is `stale`, else
`unchecked` when one is, else `current`.

## Manifest (`manifest-index.schema.json`, `manifest-claim.schema.json`), derived

The current format is `prooflens/manifest@1`; older display data must be rebuilt.
See [the structured status contract](STATUS_CONTRACT.md) for the complete code inventory.

`data/index.json` lists the papers, every claim's `status_code`, derived status/class and anchor, the summary and the
findings counts, and the [semantic summary](#semantic-summary-prooflenssemantic-summary1-derived); a published audit's index also has the auditors' `main_results`
([below](#published-workspace-records-prooflenspublished-work1-written-by-the-export)). `data/claims/<file>.json` holds one passport: the printed statement
(`statement_tex`: a statement environment's body, or the pinned passage of a claim located by
line, each read from the source file that holds it, also when the main file `\input`s or
`\include`s its sections; and its display `excerpt`, when the paper publishes its source text), each
clause's unfolded statement, proofs, witness, regimes, reviews and structured `evidence`, the
declarations of its closure, and its findings. A clause also lists `witness_defs`, the
declarations only its witnesses use that carry data (proofs and the tactic scripts of tactic
defaults are left out) and have no current review (`{name, witnesses, state}`),
and a definition claim's clause `witness_candidates`, the witness-only declarations that use a
definition it maps (`{name, uses, witnesses}`). A claim is loaded only when it is opened.
In zero configuration a passport also has `correspondence` (or `null`): the mapper's reading of how
far the linked declarations state the claim, `{source, coverage, basis, refs, argument, next_step,
bridge, question, would_decide, confidence, note, by}`, where `source` is `confirmed` (the
auditor's, from `machinechecked.links.json`) or `formalization.yaml` (the project's row notes).
`coverage` is `full`, `partial`, `changed`, `related`, `unresolved` or `null`; `basis`, how the
coverage is supported, is `direct`, `reviewed_composition`, `checked_bridge` or `null`
(unspecified), with `refs` the linked declarations it rests on; a claim with no declaration
linked keeps only an `unresolved` reading, with no basis. A reviewed composition has the
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
it, kept to its first 20000 characters. A context cut there has `context_cut`: the `file`, the
`line` holding the first character left out, the context's last line (`end_line`), and the
characters `kept` of its `chars`. A parent's passport lists its steps (`steps`: id, number, unit, status, review state, linked
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

The site may give each audit of the registry entry its semantic summary (`semantic` on the
audit, as machinechecked.org reads and checks it from that audit's own index): `state`
(`loaded`, or why it is not shown, with `detail`), `url`, `schema`, `digest`, and, loaded, the
`release` and `commit` it names, the sets of readings (`sets`, `selected`) and the counts of the
audited paper (`paper`: the blocks a paper has in the [semantic summary](#semantic-summary-prooflenssemantic-summary1-derived)).
The paper panel shows it under that audit's line, each count linked to that audit's Overview
filtered to it (`/read/?audit=…#/r/<release>/overview?set=…&unit=…&coverage=…`), and says why
when it is not shown. It shows no count the summary does not give, and never another audit's.

`audit_order` lists the page's loaded audits that pin the same version as the first, in the order
the reader draws on them, and `audit_order_by` says what orders them: `stars` (the site's GitHub
star count for every one, given to `write_paper_site` as `stars` and kept in `stars`; most first,
ties in listing order) or `listing` (the registry's order). The first is the default audit, whose
status is each claim's top-level `status`. With several, the reader shows each claim through the
first audit that maps it (whose record of the claim is in `by_project`), labelled with that audit;
choosing one project shows only its evidence, and a claim its audit does not map is marked. A
claim's statuses from different projects are never combined.

When the site cannot show the PDF an audit read (the audit names no version, or a manuscript's
audit carries no PDF), it joins the statements found in the page's PDF to the audit's entries by
printed number and records each such join on the claim's audit record (`by_project[repo].audit`)
as `matched`: `by` (`number`), `number` (the printed number), `revision` (the revision the audit
read) and `version` (the label of the version the audit pins, when it has one). The reader says
so beside the audit's status ("Matched by its printed number to the audit's entry for Latest
manuscript (commit abc1234): the audit read another PDF of the paper than the one shown here").
The status is the audit's, unchanged.

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
`label` (its source pin) and `statement` (its text). It compares statements without their
`\label` commands and with white space collapsed. It matches a claim by its label, when each
version has one claim with it; else by its statement text, when each version has one such claim
not matched by a label; else by its number, when each version has one claim there not matched
before and neither has a label the other version gives a claim. A matched claim is `same`,
`renumbered` or `changed`; a match with no statement text on one side is left out, since nothing
says whether it changed. A claim is `removed` (or `new`) only when the other version certainly
has no counterpart: the claim has a label, no claim of the other version has that label, and none
there under its number is unmatched or lacks a statement text; any other unmatched claim is left
out, and the claim view shows nothing for it. It maps only claims that have a statement, and
never infers a split. `check_claim_map` refuses a change that does not fit its claims.

Each claim a map names gets `counterparts` on its row of `index.json`, provided the page offers
the other version. Each counterpart gives `version`, `later` (whether the other version is the
later one), `change` and `claims` (`id`, `number` on the other page). The claim view shows it,
for example "Theorem 3 in Latest manuscript (commit abc1234), statement changed", and links
the number to that claim on the other version's page. A claim the map does not name shows
nothing. A map never changes a status.

## Semantic summary (`prooflens/semantic-summary@1`), derived

`data/index.json` has `semantic`, one summary of the semantic work the audit records, and each
claim row has `semantic`, what the summary counts of that claim. `engine/python/prooflens/semantic.py`
computes both from the records the data holds (the claim records, and the published workspace
records they name); the words for every key are in `data/semantic.json`. A published audit's
summary (`export`, `build --site`, `check --site`) is computed again from the records it
publishes, so a record the export leaves out is not counted. `check --json` gives the same
summary as `semantic` and each claim's facts as its `semantic`; `check` and `build` print it
in short. The reader's Overview and machinechecked.org show its counts as they are. It makes no
verdict, score or percentage, no count is added to another, and it is never an input to a
status.

A site loading a published audit (`load_published_audit`) checks the summary and the claim rows'
facts apart from the rest of the index, which is validated as strictly as before. The loaded
record carries them as `semantic_summary`: `{state: "loaded", summary}`, or, for a summary in a
format this version does not read or one that is not valid, `{state: "set-aside", reason, detail,
format}` (`reason` is `unsupported` or `invalid`), and the claim rows then carry no facts. Either
way the audit's statuses and claims load as they would without a summary.

**Units.** Every count names its unit: `statements` (a claim whose unit is `statement`, other
than notation), `notation` (a statement whose kind is `notation`) and `proof_steps` (a proof
equation or passage). A claim's declarations are those that state it: its links (zero
configuration, and a proof step's links), or its clauses' propositions and definitions (a full
assessment); a declaration linked twice to one claim counts once.

**Sets of readings.** A reading says how far the Lean states a claim. `sets` lists the sets the
summary counts, each counted apart and never combined, and `selected` is the one shown first,
`audit`:

| Set | Its readings |
|---|---|
| `audit` | the audit's own: the coverage the links file records with a claim's links (an unlinked claim keeps an `unresolved` reading), or the inventory with a proof step's (an unlinked step likewise); `by` lists their authors |
| `review:<reviewer id>` | one reviewer's latest report of each statement, with the coverage it records with its verdict (zero configuration); `reviewer` as the report records it |
| `workspace:<id>` | one published workspace's latest submitted finding in force that records a coverage of the whole statement; `mode` and `reviewer` as the workspace records them |

A finding on a clause or a requirement is not a reading of the whole statement: a claim whose
workspace has only those is counted as `clauses_only`, never as `full`.

| Field | Content |
|---|---|
| `audit` | `author`, `release`, `evidence` and `project` (`repository`, `commit`) of the audit summarised |
| `papers.<id>` | per paper: its `revision` and `paper_version` (an identifier), and the counts below |
| `inventory` | per unit: `records`, `linked` (with a declaration), `links` (claim and declaration pairs) and `declarations` (distinct); and `proof_equations`, `proof_passages` |
| `formal` | per unit, how many claims have each `status_code`: the formal status, with its own meaning |
| `coverage` | per set and unit, each claim once: `full`, `partial`, `changed`, `related`, `unresolved`; `not_recorded` (a review that records no coverage); `stale` (a reading made for another text of the claim or other Lean); `clauses_only`; `not_assessed` |
| `basis` | per set and unit, the claims counted under one of the five relations, each once: `direct`, `reviewed_composition`, `checked_bridge`, `unspecified` |
| `currency` | per set and unit, the claims with a reading: `current` (pinned to this build), `unchecked` (this build could not check it), `unpinned` (a links-file reading, which records no version of what it read), `stale` |
| `review` | per unit, each claim once: for statements and notation `independent`, `author`, `informed`, `stale`, `unchecked`, `none` (no current review of everything it needs); for proof steps the step's review as printed |
| `findings` | per unit, how many claims have a recorded finding of each kind: `open-question`, `quantitative-difference`, `input-restriction`, `representation`, `other-difference`, `printed-step`; a claim may have several kinds, so these are never added |
| `digest` | the SHA-256 of the summary's counts and every claim's facts, without the audit's identity: two builds of the same records have the same digest, and it changes whenever a reading, a review or a finding changes, also when the Lean and the statuses do not |

A checked bridge counts as `checked_bridge` only while Lean checks it and the target and passage
are those the auditor read; a bridge Lean does not check counts as `reviewed_composition`, and the
claim's reading says it was recorded as a checked bridge (`recorded_basis`); a links-file bridge
whose target or passage changed counts as `stale`. In a full assessment a statement's review is
read from its clauses' review states (`independent` only when every clause is `reviewed`,
`stale` when one is pending and a review it needs is stale), in zero configuration from each
reviewer's latest report: `independent` when a current one records that nothing of the Lean or
the author's review was shown before its reading was locked (`reading.revealed_by`), `informed`
when the current ones do not. The finding kinds read: an `unresolved` reading, a *cannot
determine* report, an `undetermined` step and a difference still `open` (open questions); a
workspace difference by its feature (constant dependence, derivative order, norm, power, weight
or index offset; domain, additional assumption or lost case; representation, with its
resolution; any other); a *faithful with representation choices* report; a *broader*,
*narrower*, *mismatched*, *vacuous* or *refutation not valid* report (other differences); a step
false as printed or with a gap. Readings and reports out of date are not counted as findings.

A claim row's `semantic` is `{unit, declarations, readings, review, findings}`. Each reading is
`{set, coverage, basis, currency, count}` (`count` is the coverage key it is counted under), with
`recorded_basis`, `by`, `provenance` (`independent` or `informed`), `verdict`, `question` and,
for `clauses_only`, `clauses` (how many findings) when they apply. The Overview filters by these
keys, and its address names the filter: `#/r/<release>/overview?set=…&unit=…&coverage=…&basis=…&review=…&finding=…&status=…`.

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
| `resume` | where to continue: `claim`, `clause`, `question`, `pinned` references, `at`, `by`; kept apart from the evidence. The reader's pins are `{token, at, ident, label, release, repo}`: the inspection (a declaration's name, or `property:`, `fact:`, `application:`, `evidence:` with its identity), the comparison row it is beside, the identity of what it shows, and the release and project it was made on; the reader reopens a pin only on that release and project, for the same object |
| `main_results` | the paper's main results as the auditor chose them (`workspace main`), which `compare --query impact` traces from: `selected` (each `{claim}`, standing for the claim's linked Lean, or `{decl, module, build}`, a project declaration), `by`, `at`, and `pins` (`release`, project `commit` and `repository` of the build they were checked against); absent until chosen |
| `review` | the review protocol's `drafts` (locked reading, verdict, author-review step) and submitted `reports` (`prooflens/review-report@1`) |
| `version_maps` | the version maps the auditor keeps (`changes --map --workspace ID --save`): each the map without `references`, with `kept_at` and `kept_by`; one per paper and pair of releases; absent until one is kept |
| `conflicts` | refused edits, each with the saved record (`current`) and the proposal (`proposed`) |
| `provenance` | upgrades, mode changes, imports and replaced main results (`was`), with time and person |
| `ops` | acknowledgements of requests by their `op_id`, so a repeated request changes nothing (not exported) |

Every record has `id`, `kind`, `claim` (a claim id, resolved from a key or a number when written),
optional `clause` and `note`, `rev`, `created_at`/`created_by`, `updated_at`/`updated_by`, and
`pins` (`release`, `statement_sha256`: the claim's printed-text hash when written).

- **`evidence`**: `ref` is one of `{decl, module, build, fingerprint, digest}` (a declaration of
  the selected build; `build` is `built`, `unbuilt`, `not loaded` or `external`; a `module` given
  is the only one searched, and a declaration it does not declare is refused with the modules
  that do, as is an alignment's target), with `closure` (each project definition its statement
  uses, for a definition its value's too, with its digest as below, or null when the build shows
  none; from its statement record, else by following what the build's declaration records use,
  with `closure_complete: false` when a record is missing) and `expansions` (the applications of
  definitions it prints, as the build expanded them: `{at, name, key}`, `key` naming the stored
  expansion, `data/expansions/<key>.json`), `{source:
  {file, line}}`, `{paper: {claim, quote, sha256}}` (`sha256` the claim's passage pin when it was
  quoted), `{app: {...}}`: an application of a declaration, as
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
  changes. Each of these three is `unchecked`, never `stale`, while Lean cannot look: its
  module is not built or could not be loaded, the request failed, or, for an application not
  found, a module was not searched. `role` is `candidate` (the default), `supports`,
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
  bridge, and full coverage needs the composition complete (checked again at `submit`). Shown,
  a `checked_bridge` finding reads as `reviewed_composition` (with `recorded_basis` and the
  reasons, `basis_reason`) unless a bridge Lean checks now supports it: its composition's, or
  else its own `bridge`, checked as a composition's is (`bridge_check`). A finding's own bridge
  records no version of the target or of the passage the auditor read, so Lean's check of it
  reads as out of date; a finding with no bridge reads as `reviewed_composition` too. A finding
  may also record a `difference` on its `requirement`
  (`{feature, paper, lean, outcome, conditions, transport, resolution, why, hint}`), a `verdict`
  on a printed step (`holds as printed`, `holds, with a gap in the argument`, `false as
  printed`, `cannot determine`) and the `counterexamples` it rests on (pinned by digest); such a
  finding is submitted without a coverage. `state` is `draft`
  or `submitted` (`submitted_at`). A submitted finding is never edited or deleted: a later
  finding names it in `supersedes`, with its `reason`, and both are kept. A finding records what
  it rests on when it is submitted (`dependencies`, below).
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
  Lean), optional `fragments` (the ids of particular passages of them, accepted and of the same
  claim, when the alignment concerns those passages rather than the whole requirement; their
  requirements are added to `requirements`), `lean` (targets: `{decl}`, or a part of its
  statement as the build prints it: `var`, `binder` (a variable's type or a hypothesis), `at` (a
  sub-term's identity, inside a definition expanded at its arguments and an equation on a later
  page included) or `conclusion`; for a claim that only defines, a part of one of its
  definitions: a parameter (`var`) or a sub-term of its body or equations (`at`); each with
  `build`, `fingerprint`, `digest`, the `closure` of its declaration's statement (as for
  evidence) and the `target` text) and `relation` (`corresponds`, `additional assumption`,
  `changed`, `alternative representation`). A requirement may have several alignments and a
  target may serve several requirements; one passage may align with several targets and several
  passages with one. A passage an alignment names is not deleted while it does (it is marked
  removed instead).
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
`record`), `resume`, `mode`, `exposure`, `main-results` and `version-map` (`{"op":
"version-map", "map": {...}}` keeps a version map, replacing one of the same paper and
releases). An edit made from an older revision of a record is a conflict: nothing is applied,
and the answer (and `conflicts`) holds both versions; edits of different records are both kept.
Writes replace the file atomically under a lock file beside it.

`{"op": "main-results", "main": [...]}` replaces the main results: each entry a claim (its id,
key or number) or a declaration (`NAME`, `MODULE:NAME` when several modules declare it, or
`{decl, module}`), read as a claim first. It needs a build: a claim must be in its release and a
declaration must be one the project declares (built, or in a module not built or not loaded), or
the whole update is refused. The selection replaced is kept in `provenance`; an empty list
removes it. Against a later build, `workspace show`, `workspace main` and `compare --query impact`
list what the build no longer has under `problems` (a claim not in its release, a declaration not
declared, or not in the module recorded); a build that keeps no index of the project's
declarations cannot tell, and lists none for a declaration it holds no record of. A selection
changes no status.

**Currency.** Evidence on a declaration is pinned to its `fingerprint` and to a `digest` of that
fingerprint with those of the constants Lean generated for it (`N._f`, `N.match_1`, `N.eq_1`), which
carry a definition's equations, and of the tactic script of each tactic default its type has,
and to the digest of each definition its statement uses (`closure`). Against a later build,
evidence whose digest changed, or one of whose definitions' digests changed (the change names
the definition and the declaration that uses it), is `stale`, and so is every question that
cites it; the others stay `current` (`unchecked` when the build shows no fingerprint, or no
version of a definition it uses, or when its definitions were not recorded: re-pin it). An
unchecked declaration's `reason` says why the build shows no version of it and what would let a
build check it: there is no build, the build ran no Lean (or the view has no Lean index), it is
outside the project, its module is not built or could not be loaded, the project no longer
declares it, or the build records no version of it (a full assessment records the declarations
its inventory's clauses name and those their statements use, naming the module when
`modules` does not list it; a view, those its claims link and use); or that it was cited
without a version, to re-pin. An alignment's target gives the same reasons. A quoted
passage is stale once its claim's passage pin changes, and unchecked when it records none. A
claim's passage has also changed when the build's source check finds that the paper no longer
prints the text the inventory pins (`source_matches` false: the text changed and the inventory
was not pinned again): whatever read that passage (a quoted passage, a fragment, a question, a
composition, a finding, a bridge) is then `stale`, saying so, although the pin is the same. A
fragment whose region of the source now reads differently (the lines that changed are listed),
or whose claim's passage changed, is `stale`, and so is an alignment whose declaration, or a
definition its statement uses, changed, or one of whose named passages changed or no longer
governs the reading (removed, or not published: `{fragment, was, now}`), and every requirement
they belong to, and every question that names that requirement. A finding's currency is that of its dependencies (below). The saved
records are not re-pinned silently: a `put` with `repin: true` re-pins a record to the current
build.

**Dependencies of a finding.** `engine/python/prooflens/dependencies.py`. A finding rests on the
parts below, each an item with `dependency` (its kind), `record` (the record it comes from, when
it is one), `via` (the composition or counterexample it is cited through) and its content
identity:

| `dependency` | Part | Identity |
|---|---|---|
| `passage` | the claim's printed passage | `claim`, `sha256` (the finding's pin) |
| `reading` | a requirement it rests on: the one it names, or its counterexamples concern, with those it sits inside, and each that a step of its composition establishes, with those inside it | `requirement`, `sha256` (`reading_sha256`) |
| `context` | a passage governing one of those requirements (accepted, not a later use) | `requirement`, `role`, `origin`, and `region` (its location, `sha256`, `line_sha256`) or `passage` (`claim`, `sha256`) |
| `object` | an alignment of one of those requirements | `requirements`, `relation`, `lean` (each target's place, `target` text, `fingerprint`, `digest`, `closure`) |
| `declaration`, `application`, `fact`, `certificate`, `paper`, `source` | evidence it cites, or that its composition or counterexamples cite | `role` and `ref`: the reference's identifying fields and pins (a declaration's `closure` and `expansions` included) |
| `composition` | the composition it rests on | `sha256`: a digest of its statement, steps (their evidence, requirements, substitutions and inferences), identifications, obligations, coverage and bridge pins |
| `bridge` | for a finding recorded as a checked bridge: its composition's bridge, or its own | `theorem`, `target`, and for a composition's, `target_fingerprint` and `source_sha256` |
| `counterexample` | a counterexample it cites | `sha256` (the finding's pin of it) |

`dependencies` is `{kinds, items, unknown, at}`: `kinds` the evidence kinds it uses
(`statement comparison`: a declaration's statement or a certificate; `object correspondence`:
alignments or a composition's identifications; `composition`; `proof route`: applications or
facts inside a proof; `checked bridge`), and `unknown` the parts that cannot be identified, each
with `why` (a finding recorded without a build, whose passage version is not known; a finding's
own bridge, which records no version of its target or of the passage; a record it names that the
workspace lacks). A finding on the whole claim names no requirement: it rests on one only through
its composition. A submitted finding records `dependencies` when it is submitted (a superseding
one when it is recorded) and keeps them; `workspace show` gives a draft's as its records give
them now. Against a build, each item is checked as its record would be (the passage against the
claim's pin, a context passage and an alignment as above, evidence as above, a bridge as
`bridge_check`, a counterexample against its pin and its own currency). The finding is `stale`
when an item changed, or, for a submitted finding, when a record it rests on is not the version
it recorded (edited, re-pinned, removed: the change names the record), so re-pinning evidence
brings a draft up to date and leaves a submitted finding stale until it is superseded. Otherwise
it is `unchecked` when an item is unknown or cannot be checked now (`currency.unknown`, each
`{dependency, record, why}`), including a finding submitted before findings recorded their
dependencies; else `current`. Dependencies are workspace records: the export of a workspace
carries them, a published audit does not, and no status reads them. Across a revision of the
paper, a version map judges the paper parts by their text instead
([Findings across a revision](#findings-across-a-revision-prooflensreopened1-derived)).

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
`workspace import` keeps its id, authors, pins, mode and exposure, and each submitted finding's
dependencies as recorded. Into a workspace already
present, it adds the records that are missing (and the main results, when it has none, and the
version maps it lacks) and keeps a record, main results or a version map both hold in different
versions as it is, listing the other under `conflicts`; a version map of another form is left
out and reported. A kept map judges the findings without the manuscripts, so the findings it
reopens travel with the workspace. References the current build cannot resolve, main results included, are reported as
`problems`. A published audit carries the accepted records and the main results of every
workspace in the working directory, below; the workspace itself stays local.

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
`basis` stay). A cited fact's, application's or certificate's currency is checked against the
Lean project the release was built from, as `workspace show` checks it (asking Lean when the
facts store has no answer); it is published as `unchecked` when there is no such project (no Lean
was built, or a Lean input changed since the build), or when Lean could not look (the module is
not built or could not be loaded, the request failed). An `app` reference keeps its arguments,
premises and result only with `lean`. A composition keeps its steps' ids, requirements, evidence and order, its
identifications' steps and how they are known, and its obligations' kinds, states and discharges;
its objects and substitutions only with `lean`; its statement, what each step establishes, the
inferences, obligation texts and notes only with `reviews`. Its basis is `checked_bridge` only when
the bridge is checked at export against the project's facts store; otherwise
`reviewed_composition`, and a finding recorded as `checked_bridge` on it reads the same way. A
finding recorded as `checked_bridge` without a composition reads as `reviewed_composition` (with
`recorded_basis`, `basis_reason` and, for its own bridge, `bridge_check`) unless that bridge is
checked at export. Without `reviews`, `note`,
`argument`, `question`, `would_decide`, `reason` and `why_rejected` are left out. The export
scans these files with the rest. A claim file larger than 2 MB is refused.

The main results each workspace saves are in the data index, `main_results`: one entry per
workspace, with `workspace`, `mode`, `reviewer`, the `selected` claims and declarations, `by`,
`at`, `pins` (the release and project `commit` and `repository` they were checked against, which
may be earlier than the audit's own) and `problems` (what the published build no longer has, as
above). An entry the published data cannot name (a claim of a paper the export leaves out, or a
declaration it neither records nor indexes) is counted in `left_out` (`{count, why}`), never
named. They are readings: no status depends on them. The index's semantic summary counts each
workspace's published findings as a set of readings of its own.

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
