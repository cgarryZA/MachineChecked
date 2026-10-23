# Using MachineChecked with a coding agent

MachineChecked is a command-line tool, so a coding agent (Claude Code, Codex, Cursor and others)
can run it like any other. Two things help it do so well.

## Install the skill

[`skills/machinechecked/SKILL.md`](../skills/machinechecked/SKILL.md) is an
[Agent Skill](https://agentskills.io): it tells an agent when to use MachineChecked, which
commands to run, how to read their output, and what each status establishes. Copy the
`skills/machinechecked` folder into the agent's skills directory; for Claude Code that is
`.claude/skills/` in a project, or `~/.claude/skills/` for every project:

```sh
mkdir -p ~/.claude/skills
curl -sSfL https://raw.githubusercontent.com/cgarryZA/MachineChecked/main/skills/machinechecked/SKILL.md \
  --create-dirs -o ~/.claude/skills/machinechecked/SKILL.md
```

Then ask, in a Lean project with its paper: *"Which of the paper's claims are formalised, and
does Lean prove them?"*

## Machine-readable output

```sh
machinechecked check --json
```

prints one JSON document (`machinechecked/check@1`) with every claim's number, status, links
and suggestions. It exits 0 when every linked declaration is proved, 1 when one is missing or
not proved, and 2 when the check could not run (a missing program such as `lake`, missing Lean
project, unreadable paper or failed Lean probe). In that last case the document has
`"ok": false` and an `error` (`kind`: `missing-tool` with the `tool`, `error`, or `internal`;
`message`) and an empty claims list: report the execution error. Progress goes to stderr, so stdout is only
the JSON. `version` is MachineChecked's version, and `release` identifies the evidence the
statuses come from (it changes when the paper, the links or the Lean change). Each `status_code` is a stable machine-readable result; `status` is its display label.
`class` is only its coarse group for colouring (`proved`, `open`, `malformed`,
`unspecified`), and the skill explains both.
Without a `machinechecked.toml`, `warnings` lists names in module docstrings that the project
and its dependencies do not declare (`kind` `module-doc-name`, with `file`, `line`, `name` and
`message`; the message says when a short name reaches only a module or a namespace), and
references to the paper's numbers that disagree with the paper read here
(`kind` `paper-reference`, with `file`, `line`, `reference`, `status`, `id` and `message`);
they do not change the exit code. `numbering` holds every such reference
(`numbering.references`: `reference`, its exact `text` and `context`, its `source` with
declaration, module, file, line and `where` it is, and `status`: `exact`, `other-kind`,
`absent`, `unchecked` or `other-source`; `stale_lead` and `content.closer` when an exact
reference's declaration reads closer to another statement) and the project-level `pattern`
(counts by status, `drift`, and whether the paper's numbering is complete). Each suggestion
has `reasons`: `signal` (`content`, `uses`, `number`, `lexical`, `structure`) and `text`; a
`number` reason has `basis` "a lead" or "a possibly stale lead".

In a project with a `machinechecked.toml` (the full assessment), the document also has
`findings` (totals per tier, dismissed warnings left out) and `finding_details`: each finding
with its `tier` (`violation`, `obligation`, `warning`), `code`, `subject` (the claim or clause,
for example `T:thm:bound#0`), `message`, and `dismissed` (who and why) when a warning was
dismissed. A warning with code `module-doc-name` is a name a module docstring lists that nothing
declares: its `subject` is the module, its `trigger` the name, and it has `file` and `line`.
A warning with code `review-citation` is a name or file that review text cites and nothing
resolves: its `subject` is the review file, its `trigger` the token, with `file` and `line`.
A warning with code `totalised` names the operation in `trigger`. For a supremum, an infimum, a
division, an inverse, an integral, a sum, a root, a logarithm, a derivative or a conditional
expectation it also has `occurrences`: each application of that operation the probe read in the
statement, with `operation`, its `type` (as Lean prints it; null when it could not be read) and
`type_head` (the type's head constant), `structure` (what decides the rule: `complete-lattice`,
`conditionally-complete-lattice`, `group`, `group-with-zero`, `one-element`, `unknown` when Lean
finds none of those, or null when the rule does not depend on one), `state` (`applies`, `none`
when the type gives the operation no exceptional case, or `unresolved`), `rule` (what the
operation gives there, when it applies) and `at` (its positions in the proposition, the `id`s of
the printed sub-terms). Each application whose rule applies or is unresolved is its own warning:
its `occurrences` holds that one record, `at` is its first position (the finding's `id` ends in
`@` and that position) and `fingerprint` identifies it in its scope (what a dismissal of it
records, with `at`). A warning about the applications a statement too large to read did not
reach has empty `occurrences` and `occurrences_complete: false`. A dismissed warning has
`dismissed` (`by`, `rationale`, and `form: "statement"` when the dismissal names the operation in
the whole statement rather than one application); `dismissal_stale` marks one whose dismissal no
longer applies. The site data and `export` carry the same fields.
When the configuration has one paper and the project is built, the document
also has `warnings` with the `paper-reference` warnings and `numbering`, as in zero
configuration; with several papers they are absent. Report the violations and obligations by
subject and message; they are what blocks a claim from being accepted. `replay` is null when no Comparator replay counts; otherwise it
gives the record's `guard` (`guarded`, `unguarded`, or `unrecorded` for an older record), the
number of proofs `replayed`, and a `message` when they were not shown to run under the sandbox
guard.

### What a declaration rests on

```sh
machinechecked inspect NAME --dependencies --json
```

prints one JSON document (`machinechecked/inspect@1`) about one declaration: its `declaration`
(kind, module, file, source `range`, `doc`, `statement`, `axioms`, `sorry`); the project's
declarations its statement mentions (`statement_dependencies`) and, kept apart, those its proof
or definition body uses (`proof_dependencies`; `value_kind` says which); the constants outside
the project it uses (`external_dependencies`); and a `closure` summary (`declarations`,
`deepest`, external constants per package). With `--dependencies`, `closure.members` lists every
project declaration reachable through statements and proofs, each with its own two lists and its
`depth` from NAME. Compiler-generated constants (`_proof_1`, `match_1`, equation lemmas) are
followed but not listed: `closure.generated` counts them.

The other records MachineChecked keeps erase proofs, so that fingerprints see statements only;
`inspect` is the one place proof dependencies appear, and it changes no status. `status` is
`found`, `ambiguous` (two modules declare the name: pass `--module`, and `modules` lists them),
`not built` (its module is not built), or `not found`. It exits 0 when found, 1 for any other
answer, and 2 when it could not run (with an `error`, as `check --json`). The answer is cached in
`.machinechecked/build/inspect/` until a Lean input or built module changes (`cache.hit`). A
dependency identifies the constants used by Lean’s terms.

### A claim beside its Lean

```sh
machinechecked compare "Theorem 2.5" --json
```

prints one JSON document (`machinechecked/compare@1`) for one claim, read from the last
`view` or `build` (it runs no Lean and changes nothing). The claim is named by its id
(`T:thm:bound`), its key (`thm:bound`) or its printed number. The document holds:

- `snapshot`: the release and evidence it was read from, the project's commit, and each paper's
  revision and PDF checksum. Quote them with anything you conclude.
- `paper.passages`: the complete printed passage, with `source` (file, line, label, pages,
  `position` exact or approximate) and `quality` (`LaTeX source`, or `text extracted from the
  PDF`). `available: false` means the build holds no text for it; `complete: false` means the
  PDF extraction cut it. Read those in the paper.
- `lean.declarations`: every linked declaration (or locked statement) with its complete
  statement: `statement.text` exactly as Lean prints it, `binders` and `conclusion` with their
  expression ids, and Lean's checks (axioms, sorry, errors). `lean.candidates` are suggestions
  nobody has confirmed, with their reasons. `lean.definitions` are the definitions the
  statements use, with their type and value; `generated_for` marks the equations Lean generated
  for one of them. `lean.references` are the references to the paper's numbers that concern
  the claim, and `lean.numbering` their project-level pattern (as in `check --json`).
- `interpretations` (stage `informed`, the default): the correspondence note, review reports,
  author's review markers, symbol links, the status and the assessment's findings.
- `retrieval`: what is `included`, what the stage `withheld`, what is `unavailable` because it
  is not extracted yet (with the issue that owns it), what a targeted query gives `on_request`
  (`uses`, which runs Lean), and the cursor of the definitions list.

`--stage read` holds the paper only and `--stage compare` adds the Lean without any recorded
interpretation; the review protocol's `--json` output uses the same stages. Passages and linked
statements are never shortened; `--limit N` pages the definitions, and `--after ID` (the
`retrieval.definitions.next` it returns) continues them.

A proof step (`machinechecked compare "Equation (3)"`, or the review unit `step:<claim id>`) is a
claim of its own: its passage carries `step` (its parent and the question, whether the printed
step holds) and `context` (the proof up to it and the sentence after it); from the compare stage
its declarations have the role `establishes the step` or `formal route used instead`, and at the
informed stage `interpretations.step` holds its correspondence, route and review.

Targeted queries have one shape (`machinechecked/query@1`: `op`, `target`, `context`,
`results`, `provenance`, `retrieval`):

```sh
machinechecked compare --query definition Toy.triangle --json   # its type, value, equations
machinechecked compare --query mentions Toy.triangle --json     # statements that use it
machinechecked compare --query dependencies Toy.Acceptance.thm_bound --json   # runs inspect
machinechecked compare --query search "Theorem 2" --json       # declarations stating a claim
machinechecked compare --query search 'n ≤ C * n ^ 2' --json   # ... or an expression, or words
machinechecked compare --query proof-facts Example.bound --json  # facts inside its proof
machinechecked compare --query proof-facts Example.bound --match "C * h"   # ranked by symbols
machinechecked compare --query uses Toy.IsEven --json          # where it is used, and how
machinechecked compare --query impact Toy.triangle --json      # which main results use it
```

`search` ranks every declaration of the project's built modules, linked or not, by how much of
the query its complete statement, docstring, name and used definitions carry. A claim as the
target searches with its printed statement, over declarations of its sort, and says when a
result orders `∀` and `∃` differently. Each result has its complete `statement`, its `score`
and its `reasons`; a result reached through a close match it uses says so (`signal` `uses`,
with `via`). It is the search the suggestions and the reader use, from the build's content
index (`data/retrieval.json`), with no Lean session; `--limit` and `--after` page it. The
zero-configuration build writes that index; on a full assessment's build `search` answers
`available: false`. Nothing people recorded (links, rejections, notes) enters it. In zero
configuration, `mentions` reads the complete statements of that index; with an older build it
reads previews (`complete: false` on such a result: get its statement with `dependencies`).

`uses` (also `machinechecked inspect NAME --used-by`) answers with one document
(`machinechecked/uses@1`) read from Lean's elaborated terms:

- `users`: the declarations that refer to it, each with how (`statement`, `proof`, `definition
  body`); a constant Lean generated is named under `via` beside the declaration it belongs to.
  `claims` lists the claims a user is linked to.
- `further`: the declarations that reach it through its users, nearest first, with the user
  each one goes `through`; a general result that uses a specialised helper is found here.
- `imports_without_use`: modules that import its module and use none of it (not uses).
- `applications`: each application inside a user's proof or body. `params` pairs every binder
  of the declaration (implicit and instance binders included) with the argument supplied and its
  instantiated type; a premise's `origin` says where its proof comes from (the caller's
  hypothesis, a hypothesis introduced in the proof, a theorem applied there, a constructor, a
  projection of a structure, an instance, or a term built in place) and `discharge` sums it up:
  `assumed` by the caller, `proved` in the caller, or `local`. `result` is the conclusion the
  application obtains; `unsupplied` the binders it leaves open. Printed expressions mark each
  variable by its index in `locals`, whose `id` is the position of its binder, so two variables
  printed alike in different scopes stay distinct. `location.path` is the application's
  position in the elaborated term; its line is the enclosing declaration's.
- `scope`, `complete` and `answer`: the modules searched, those not built or not loaded, and
  `used`, `no use found in this scope`, or `not traced` when some modules were not searched.

The first `uses` query after a change runs Lean once over the project; later queries reuse the
answers until a Lean input changes.

`impact NAME` traces the same references and answers whether each main result uses NAME, with
one result (`machinechecked/impact@1`):

- `selection`: which main results are traced. By default (`basis` `suggested`) they are the
  declarations linked to the paper's theorems; `--main NAME`, repeated, names them instead
  (`basis` `given`), each a declaration or a claim standing for its linked Lean, and
  `unlinked_claims` lists a named claim that has none.
- `main_results`: for each, `use` (`proof`, `definition body`, `statement` when it is in the
  statement only, `none`, `not traced`, or `itself`), the `answer` in words ("used by its proof,
  directly; also in its statement", "formalized separately: not used by this main result") and
  `paths`: for each kind of use, the shortest path of references (`steps`, each with `from`,
  `to` and `refs`, and `via` for a constant Lean generated), with the ids of the `applications`
  of NAME at the end of the proof's path.
- `claims`: every claim with linked Lean, its `relation` (`linked`, `uses`, `not traced`,
  `none`) and each declaration's `use`, `answer` and `paths`. A difference between NAME and the
  paper can matter only to the claims that use it.
- `applications` as `uses` gives them (with `applications_complete`), `imports_without_use`,
  `locations` (the module, kind and line of each declaration on a path), `scope`, and
  `complete: false` when an answer is `not traced`.

*Formalized separately* says only that this main result's Lean does not refer to NAME; *not
traced* gives what is missing and never means unused. The answer changes no status.

`proof-facts NAME` asks Lean, for that one declaration, for the propositions its proof establishes
along the way: each `have` (and `let` of a proposition), each goal a `show` states, and each
application of a theorem of the project or of a theorem to a local fact. Each result has its
`type`, the locals it needs (`assumptions`: the hypotheses and variables its type and its proof
mention), the `cases` of the proof it lies in (a branch of a case split, a witness of an
`obtain`), the `premises` of an applied theorem with the local that supplies each, `used_by`, its
`source` line (`located` says how it was found) and its `ref`, the reference a workspace cites.
`subject` holds the exported statement (`basis: "exported theorem"`), the proof's hash and what
was inspected, `source_only` (a `have` or `show` of the source with no typed counterpart, for
instance inside a lemma Lean generated, listed under `proof.auxiliary` and asked about by its own
name), and `proof.complete: false` when the walk reached its limit (200,000 nodes, 200 facts). A
fact's `basis` is always "established inside this proof under this context": it is not an
exported theorem, and `--match` ranks facts by shared symbols without deciding that one bound
gives another. Lean runs once per declaration; the answer is kept in the facts store, like
`inspect`'s, and reused until the declaration's module or a module it imports changes.
`--query composition CLAIM` gives the compositions the workspaces record for the claim (one
workspace's with `--workspace ID`), each as `workspace show` gives it: its steps, `basis`, `gaps`,
`next_step` and `bridge_check`. They are prior interpretations (`subject.contains`). A query
kind whose extraction is not built yet, or that this build cannot answer, gives `available:
false` with its `reason`, which names the issue that owns it when there is one. An error is `{"ok": false, "error":
{kind, message, candidates}}` with exit 1 (exit 2, kind `no-build`, when there is no build to
read: run `view` or `build`); `candidates` lists the claims or declarations you may have meant.

### Partial answers and paging

Every document says how much it holds; read these fields before concluding that something is
absent:

- `compare`: a passage with `available: false` is not in the build (read it in the paper at its
  `source`), and `complete: false` marks PDF text the extraction cut. `retrieval.unavailable`
  names what is not extracted yet, each with the issue that owns it and, where there is one,
  the query that gives it on `request`; `retrieval.on_request` lists the targeted queries.
- Lists: the packet's `retrieval.definitions` and the `retrieval` of a query give `total`,
  `returned` and `complete`; `--limit N` pages them, and `--after` with the `next` they return
  continues. A `mentions` result with `complete: false` holds a preview: get its statement with
  `dependencies`.
- `uses`: `scope` gives the libraries and the number of modules searched, the modules
  `unbuilt` and those that `failed` to load; `complete: false` says that some were not
  searched, so an `answer` of `not traced` (no use in the modules searched) leaves the others
  open. `applications_complete` says whether every application was read.
- `proof-facts`: `subject.proof.complete: false` (with `cut`) when the walk reached its limit;
  `auxiliary` lists the lemmas Lean generated for parts of the proof, each to be asked about by
  its own name, and `not_inspected` what the walk does not read.
- `inspect`: `closure.generated` counts the compiler-generated constants it followed without
  listing.

A search that finds nothing describes the scope it searched. Report the query, the scope and
what was not built.

### What changed since the last release

In a project with a `machinechecked.toml`, `machinechecked changes --json` compares the latest
release with the one before it (`--from R1 --to R2` for any two) and prints one document,
`prooflens/changes@1`:

- `from` and `to`: each release's identity (evidence, project commit, Lean inputs, each paper's
  revision); `paper_changed` per paper and `lean_changed` say which side changed.
- `claims`: one entry per claim of either build, with `paper_change.class` (`unchanged`,
  `moved`, `changed`, `context-changed`, `removed`, `new`, `ambiguous`, `unknown`), its
  `reason`, the `context` passages or notation that changed, `proposed` or `candidates` for a
  removed claim whose text another claim now has (never applied), and `pin` when the inventory
  still pins the earlier text; `status.from` and `status.to`, each build's own status; `lean`,
  per clause, the `proposition`, the changed `definitions` and the `proofs`, each with its
  `change` (`statement`, `proof`, `removed`, `new`, `renamed`) and both builds' `text`; and
  `evidence`, every review with its `outcome` (`reopened`, `dropped`, `replaced`,
  `newly-current`, `kept`, `open`), and for a reopened one `because` (the dependency: a Lean
  declaration with both fingerprints and texts, or a paper passage with both digests and its
  changed context) and the `question` a new reading answers.
- `declarations`: every project declaration whose statement or proof changed, with the claims
  that depend on it.

Report the reopened reviews by claim, with their question; `kept` means the later build still
counts the same marker. A review that read a passage the manuscript no longer matches is
reopened (`because` names the passage), and a `caveat` marks one that a build counted
against a pinned earlier text before such reviews were reopened.
Nothing in the document is a status: report `status.to` as the claim's status. `--workspace ID`
adds `workspace.records`: the saved investigation's evidence, findings, questions,
counterexamples and compositions that are not current, each with its `state` and `changes`
(`workspace show --json` gives the currency of its requirements and passages).

### Reviewing from the terminal

`machinechecked review next|read|lock|show|decide|author|submit|status|export` takes a unit of
the review queue through the protocol in both kinds of project (see
[REVIEWING.md](REVIEWING.md)). In a project with no `machinechecked.toml`:

```sh
export MACHINECHECKED_REVIEWER=llm:MODEL
machinechecked build
machinechecked review next --json            # {"unit": {"id": "link:thm:odd-add", ...}}
machinechecked review read link:thm:odd-add --json    # the paper only
machinechecked review lock link:thm:odd-add reading.md
machinechecked review show link:thm:odd-add --json    # and the Lean
machinechecked review decide link:thm:odd-add faithful comparison.md
machinechecked review author link:thm:odd-add          # what was recorded before
machinechecked review submit link:thm:odd-add none.md
machinechecked review export --out machinechecked-reviews/my-reviews.json
```

Run `compare` on a claim only after its review, or say in the reading that you had: its default
stage shows the Lean and what others recorded. The steps are saved in your workspace
(`review-work/`, below); record an informed `compare` there before reviewing the same claim with
`{"op": "exposure", "what": ["Lean", "prior interpretations"], "claims": ["thm:bound"],
"how": "compare"}`, so the report lists it.

`review next` and `review status` take `--order` ([Review order](REVIEWING.md#review-order)):
`priority` (the default), `document` (the paper's order), or `informed`, which also ranks the
units by what the auditors' workspaces in the working directory record as open. `next --json`
gives the `order` and the unit's `priority`: its `base` reason in the queue, the `signals` that
move it (each with `kind`, `text` and `claims`: `reopened`, with the `questions` a new reading
answers, and `changed` since the last release; `open question`, `difference` and `hint` from the
workspaces; `proof use` when another claim's proof uses its Lean), and its `tier`, the strongest
signal other than `proof use`, or null. `reason` puts them in words. `status --json` gives the
`open` units in that order and `order`: the order asked (`by`) and the queue's own record
(`queue`, with each signal's `state`, `read` or `not available` with `why`). On the toy example,
with Theorem 2.5 linked and an open question another auditor recorded on it, `review next
--order informed --json` gives (release and mode left out):

```json
{"schema": "machinechecked/review-next@1", "order": "informed",
 "unit": {"id": "link:thm:bound", "kind": "link",
          "reason": "An open question is recorded; short statement",
          "priority": {"base": "Short statement",
                       "signals": [{"kind": "open question", "text": "an open question is recorded",
                                    "claims": ["P:thm:bound"]}],
                       "tier": "open question"}}}
```

The workspaces' records are prior interpretations. Asking for the `informed` order records in
your workspace that you have seen them, for the claims it drew on (`workspace show`: "had seen:
prior interpretations of P:thm:bound (interpretation-informed review order, …)"). A later
reading of those claims is then not blind, and its report says so.

### Recording links and findings

```sh
machinechecked link "Theorem 2" Plain.oddSum_eq_sq --coverage full --note-file note.md \
  --as "llm:MODEL" --json
```

checks the claim and the declarations against the last build (no Lean runs) and prints one
JSON document (`machinechecked/link@1`): the resolved `claim` (`id`, `key`, `number`), each
declaration's `build` state (`built`, `unbuilt`, `not loaded`, `external`), the links-file entry
`before` and `after`, and `written`. An unknown or ambiguous claim, or a name the project does not
declare, exits 1 with `ok: false` and `error.candidates`, and writes nothing. `--dry-run` writes
nothing.

Evidence, findings and open questions for a claim or a clause go into a workspace
(`machinechecked workspace`, described in [Reviewing](REVIEWING.md#saved-investigations)):

```sh
machinechecked workspace open --mode informed --as llm:MODEL
machinechecked workspace update - --as llm:MODEL <<'JSON'
{"op_id": "req-1", "ops": [
 {"op": "put", "record": {"id": "e-1", "kind": "evidence", "claim": "Theorem 2",
  "ref": {"decl": "Plain.oddSum_eq_sq"}, "role": "supports"}},
 {"op": "put", "record": {"id": "f-1", "kind": "finding", "claim": "Theorem 2",
  "coverage": "full", "evidence": ["e-1"],
  "note": "The recursion states the paper's sum."}}]}
JSON
machinechecked workspace show --json
```

`update` prints the acknowledgement (`changed`, `revisions`, `revision`) or `ok: false` with the
`error` (exit 1); an edit of a record changed since its `base_rev` returns `conflicts` with both
versions. Repeat a request with its `op_id` after a lost answer: it changes nothing. `show
--json` gives every record with its `currency` (`current`, `stale` with the `changes`, or
`unchecked`) and the `resume` point. To cite a fact inside a proof, put its `ref` from
`compare --query proof-facts` as `"ref": {"fact": REF}`; a finding resting on it takes basis
`reviewed_composition` (it is not `direct` coverage), and `show` marks it `stale` once that proof
changes. Requirements of a claim (`requirement`), the passages that govern each one
(`fragment`: a region of the paper's source with its role, origin and scope) and their
association with Lean (`alignment`) are records of the same workspace; `show --json` gives each
claim's `reading`, `workspace suggest --claim C --requirement r1 [--apply]` proposes nearby
passages, and `compare C --workspace ID --json` carries the reading in
`interpretations.requirements` (and that workspace's compositions in
`interpretations.compositions`). An argument that combines several results is a `composition`
record ([Reviewing](REVIEWING.md#saved-investigations)); a step can cite an application from
`compare --query uses` as `"ref": {"app": {"callee": NAME, "id": APP_ID}}`. Differences from the
Lean are findings with a `difference` on the affected requirement; a counterexample
(`counterexample`: a specialisation, its reduction and violation, its admissibility obligations)
is read against its requirement's quantifiers, and a Lean certificate is evidence
`{"certificate": {theorem, target, certifies}}` that Lean checks when it is recorded. A
workspace started in informed mode records that the Lean was seen; `{"op": "exposure", "what":
"external material"}` records anything else you read.

## A worked investigation

This investigation asks whether the toy paper's Theorem 2.5 is formalised as printed: "There
is a constant $C$, independent of $n$, such that $T_n \le C n^2$ for every natural number $n$."
It runs in zero configuration, as in an ordinary Lean project, on a copy of the toy example's
Lean project with its paper inside (the example's own directory is a full assessment, whose
build holds no content index for `search`). Every command below runs as shown; `MODEL` stands
for your model's name.

```sh
cp -r examples/toy-paper/lean toy && mkdir toy/paper && cp examples/toy-paper/paper/toy.tex toy/paper/
cd toy && lake build Toy ToyAudit
export MACHINECHECKED_REVIEWER=llm:MODEL
machinechecked check --json > check.json
machinechecked build
```

**1. Read the claim and record its requirements.** `machinechecked compare "Theorem 2.5"
--stage read --json` gives the passage alone. The claim asks for one constant chosen before
every `n`. Record that reading, each requirement with the lines of the build's copy of the
source (`.machinechecked/sources/P/toy.tex`) it comes from:

```sh
machinechecked workspace open --mode informed
machinechecked workspace update - <<'JSON'
{"op_id": "t25-reading", "ops": [
 {"op": "put", "record": {"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c",
  "form": "there is", "binds": ["C"], "independent_of": ["n"],
  "text": "a constant C, independent of n"}},
 {"op": "put", "record": {"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c.1",
  "parent": "c", "form": "for every", "binds": ["n"], "domain": "n ≥ 0",
  "text": "for every natural number n"}},
 {"op": "put", "record": {"kind": "requirement", "claim": "Theorem 2.5", "local_id": "c.1.1",
  "parent": "c.1", "form": "conclusion", "text": "T_n ≤ C n²"}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Theorem 2.5", "requirement": "c",
  "role": "constant dependence", "region": {"file": "toy.tex", "start_line": 66}}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Theorem 2.5", "requirement": "c.1",
  "role": "quantifier domain", "region": {"file": "toy.tex", "start_line": 66}}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Theorem 2.5", "requirement": "c.1.1",
  "role": "statement", "passage": {"claim": "Theorem 2.5"}}}]}
JSON
machinechecked workspace show --claim "Theorem 2.5"
```

`show` prints the reading, including `witness C: the claim produces it; chosen before n;
independent of n`.

**2. Find the Lean by its mathematics.**

```sh
machinechecked compare --query search "Theorem 2.5" --limit 3
machinechecked compare --query search 'triangle n ≤ C * n ^ 2' --limit 3
```

The claim's own search returns `ToyAudit.bound_range_corrected_holds`,
`Toy.Acceptance.thm_bound` and `ToyAudit.bound_range_at_one_false`, each with the terms it
shares. The expression search ranks `Toy.Acceptance.thm_triangle` first and reaches
`Toy.Acceptance.thm_bound` through it: "its proof uses Toy.Acceptance.thm_triangle, a close
match". The paper numbers in the Lean are leads. In `check.json`, Theorem 2.5's first
suggestion is `ToyAudit.bound_range_corrected_holds`, with a `number` reason from a module
docstring that cites Theorem 2.5 for a step of its proof; and `warnings` says that the
docstring of `Toy.PaperSpec.thm_bound` cites "Theorem 2.4", where the paper's 2.4 is Remark 2.4
(`numbering` gives that reference `status: other-kind`).

**3. Inspect the statement and its definitions.**

```sh
machinechecked compare "Theorem 2.5" --json > packet.json
machinechecked compare --query definition Toy.triangle
machinechecked compare --query dependencies Toy.Acceptance.thm_bound --json > deps.json
```

`lean.candidates` in `packet.json` gives both suggestions with their complete statements.
`ToyAudit.bound_range_corrected_holds` states `∀ (n k : Nat), 1 ≤ k → n ≤ k * n ^ 2`, a bound
on `n` for each `k`, with no triangular number. `Toy.Acceptance.thm_bound` states `∃ (C : Nat),
∀ (n : Nat), Toy.triangle n ≤ C * (n * n)`: `C` is chosen before `n`, as the paper
requires. `Toy.triangle` is a recursion (`T_0 = 0`, `T_(n+1) = T_n +
(n + 1)`, in `Toy.triangle._f`), the paper's sum in another representation. `deps.json` lists
`Toy.Acceptance.thm_triangle` among the proof's dependencies. With the user's agreement, record
the link and build again, so that a requirement can name a part of the linked statement:

```sh
machinechecked link "Theorem 2.5" Toy.Acceptance.thm_bound --as llm:MODEL --json
machinechecked build
```

**4. Follow the objects through the proof.**

```sh
machinechecked compare --query uses Toy.Acceptance.thm_triangle
machinechecked compare --query proof-facts Toy.Acceptance.thm_bound --match "n ≤ n * n"
machinechecked compare --query impact Toy.triangle
```

`uses` finds one application, `app:Toy.Acceptance.thm_bound:0`: `parameter n : Nat := n (the
variable n introduced in the proof)`, giving `2 * Toy.triangle n = n * (n + 1)`. `proof-facts`
ranks first `f2`, `hn : n ≤ n * n` at `Toy/Acceptance.lean:44`, in the case `n : Nat`;
its basis is "established inside this proof under this context". `impact` traces from the main
result now linked to Theorem 2.5: `Toy.Acceptance.thm_bound` is "used by its proof, directly;
also in its statement" (through `Toy.PaperSpec.thm_bound`), and Theorem 2.5 is the one claim
whose Lean uses `Toy.triangle`.

**5. Assemble the evidence.** Cite the application and the fact, and combine them. The
composition's bridge asks Lean to check that `Toy.Acceptance.thm_bound` proves
`Toy.PaperSpec.thm_bound` exactly; that this target says what the paper says remains your
reading, and its review is separate.

```sh
machinechecked workspace update - <<'JSON'
{"op_id": "t25-evidence", "ops": [
 {"op": "put", "record": {"kind": "alignment", "claim": "Theorem 2.5", "requirements": ["c.1.1"],
  "lean": [{"decl": "Toy.Acceptance.thm_bound", "conclusion": true}]}},
 {"op": "put", "record": {"id": "e-gauss", "kind": "evidence", "claim": "Theorem 2.5",
  "role": "supports", "ref": {"app": {"callee": "Toy.Acceptance.thm_triangle",
                                      "id": "app:Toy.Acceptance.thm_bound:0"}}}},
 {"op": "put", "record": {"id": "e-square", "kind": "evidence", "claim": "Theorem 2.5",
  "role": "supports", "ref": {"fact": {"decl": "Toy.Acceptance.thm_bound", "at": "/1/1/2"}}}},
 {"op": "put", "record": {"id": "c-bound", "kind": "composition", "claim": "Theorem 2.5",
  "coverage": "full", "steps": [
   {"id": "s1", "establishes": "2 T_n = n(n + 1) for the n the proof fixes",
    "uses": ["e-gauss"], "substitutions": [{"variable": "n", "value": "n", "in": "e-gauss"}]},
   {"id": "s2", "establishes": "n ≤ n²", "uses": ["e-square"]},
   {"id": "s3", "establishes": "T_n ≤ 1 · n² for every n", "after": ["s1", "s2"],
    "requirements": ["c"], "inference": "2 T_n = n² + n ≤ 2 n²"}],
  "identifications": [{"left": {"step": "s1", "object": "n"},
                       "right": {"step": "s2", "object": "n"},
                       "how": "evidence", "evidence": ["e-gauss", "e-square"]}],
  "obligations": [{"id": "o1", "kind": "constant dependence", "text": "C = 1 is chosen before n",
                   "state": "discharged", "by": {"steps": ["s3"]}}],
  "bridge": {"theorem": "Toy.Acceptance.thm_bound", "target": "Toy.PaperSpec.thm_bound"}}},
 {"op": "put", "record": {"id": "f-bound", "kind": "finding", "claim": "Theorem 2.5",
  "coverage": "full", "basis": "checked_bridge", "composition": "c-bound",
  "note": "Gauss's identity at the proof's n and n ≤ n² give C = 1, chosen before n."}}]}
JSON
machinechecked compare --query composition "Theorem 2.5"
```

The fact's `at` is its position in the proof term, as `proof-facts` gives it in `ref`; the
workspace keeps the fact's hashes and type with it. The composition reads `every clause, through
a bridge Lean checks`.

**6. Compare the estimate and the printed proof.** The Lean writes `C * (n * n)` for `C n²`, a
difference of notation only. The proof's Equation (3), "for every natural number $k \ge 0$, $n
\le k n^2$", is a claim of its own: it fails at `k = 0`, `n = 1`, and the Lean proof uses
`n ≤ n * n` instead. `ToyAudit` holds a Lean certificate of the failure. Record the formal
route the Lean takes, then the difference, the step's reading, the counterexample and the
verdict:

```sh
machinechecked compare "Equation (3)"
machinechecked link "Equation (3)" Toy.Acceptance.thm_bound --route --as llm:MODEL
machinechecked build
machinechecked compare "Equation (3)" --json > step.json
machinechecked workspace update - <<'JSON'
{"op_id": "eq3", "ops": [
 {"op": "put", "record": {"id": "f-power", "kind": "finding", "claim": "Theorem 2.5",
  "requirement": "c.1.1", "note": "Lean writes n² as n * n.",
  "difference": {"feature": "power", "paper": "C n^2", "lean": "C * (n * n)",
                 "outcome": "no difference", "why": "n * n is n² in ℕ"}}},
 {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "n",
  "form": "for every", "binds": ["n"], "domain": "n ≥ 0", "text": "the n the proof fixes"}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "n",
  "role": "earlier choice", "region": {"file": "toy.tex", "start_line": 71}}},
 {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "n.k",
  "parent": "n", "form": "for every", "binds": ["k"], "domain": "k ≥ 0",
  "text": "for every natural number k ≥ 0"}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "n.k",
  "role": "quantifier domain", "region": {"file": "toy.tex", "start_line": 75}}},
 {"op": "put", "record": {"kind": "requirement", "claim": "Equation (3)", "local_id": "n.k.1",
  "parent": "n.k", "form": "conclusion", "text": "n ≤ k n²"}},
 {"op": "put", "record": {"kind": "fragment", "claim": "Equation (3)", "requirement": "n.k.1",
  "role": "statement", "passage": {"claim": "Equation (3)"}}},
 {"op": "put", "record": {"id": "e-refutes", "kind": "evidence", "claim": "Equation (3)",
  "role": "supports", "ref": {"certificate": {"theorem": "ToyAudit.bound_range_at_one_false",
                                              "target": "ToyAudit.bound_range_at_one",
                                              "certifies": "refutes"}}}},
 {"op": "put", "record": {"id": "x-zero", "kind": "counterexample", "claim": "Equation (3)",
  "requirement": "n.k.1", "specialisation": {"assign": {"n": 1, "k": 0}},
  "reduced": "1 ≤ k · 1²", "violation": "at k = 0 it reads 1 ≤ 0", "evidence": ["e-refutes"],
  "admissibility": [{"obligation": "the proof may fix n = 1", "state": "verified",
                     "method": "read from the proof"},
                    {"obligation": "k = 0 satisfies k ≥ 0", "state": "verified",
                     "method": "arithmetic"}]}},
 {"op": "put", "record": {"id": "f-step", "kind": "finding", "claim": "Equation (3)",
  "requirement": "n.k.1", "verdict": "false as printed", "counterexamples": ["x-zero"],
  "note": "It fails at k = 0, n = 1; the proof uses only k = 1, and the Lean proof uses n ≤ n * n."}}]}
JSON
machinechecked workspace show --claim "Equation (3)"
```

The first `compare` shows the step with the proof around it. In `step.json`,
`Toy.Acceptance.thm_bound` has the role `formal route used instead`: it does not state the
step. `show` reads the step as `for every n (n ≥ 0); for every k (k ≥ 0): n ≤ k n²` and the
counterexample as `an admissible counterexample to this reading`, with the certificate's scope:
it certifies `ToyAudit.bound_range_at_one` only, not the reading. Run before that fragment is
recorded, `workspace suggest --claim "Equation (3)" --requirement n.k` proposes the same line 75,
the sentence before the display, as the quantifier's domain; `--apply` saves it as a proposal,
and a `put` of it with `"state": "accepted"` accepts it.

**7. Record what is open, and hand the work on.**

```sh
machinechecked workspace update - <<'JSON'
{"op_id": "t25-question", "ops": [
 {"op": "put", "record": {"id": "q-domain", "kind": "question", "claim": "Theorem 2.5",
  "requirement": "c", "text": "Lean takes C : Nat; the paper does not say where C lives. Is a real constant intended?"}},
 {"op": "submit", "id": "f-bound", "base_rev": 1},
 {"op": "submit", "id": "f-power", "base_rev": 1},
 {"op": "submit", "id": "f-step", "base_rev": 1},
 {"op": "resume", "state": {"claim": "Theorem 2.5", "question": "q-domain"}}]}
JSON
machinechecked workspace export --out ../t25-work.json
machinechecked build --site ../site
```

Another agent, in its own copy of the project, runs `machinechecked workspace import
../t25-work.json --as llm:OTHER` and `machinechecked workspace show --id ws-… --json`: `resume`
names the claim and the open question, and each record's `currency` is `current` while the
paper and the Lean are those it was recorded against. It continues with `workspace update --id
ws-…`, under its own name. `../site/data/work/` holds the submitted findings, the composition
and the reading; the reader shows them on the claim under **Auditors' readings**, attributed to
`llm:MODEL`, informed investigation. Theorem 2.5 reads `linked: Lean proof checked`: a
finding changes no status. An independent review of the claim goes through `machinechecked
review`, whose report lists this workspace's exposure in `reading.revealed_by`.

**8. Resume after a change.** Change the claim in `paper/toy.tex` to "for every positive
natural number $n$" and run `machinechecked build`. `workspace show` marks the three
requirements, whose passages changed, `stale`, and with them the findings and the composition;
the bridge reads "out of date: the paper's passage is not the version the auditor read", so
`f-bound` reads as `reviewed_composition` again. The evidence in the Lean stays `current`.
Read the new text, then put each record again with its `base_rev` and `"repin": true` (here
`c.1` with `"domain": "n ≥ 1"` and its new text, and the three fragments as they were; `show
--json` gives their ids and revisions). A
composition that a submitted finding rests on is not edited: record a new one, which Lean
checks again with its bridge, and supersede the finding:

```json
{"op": "supersede", "id": "f-bound", "base_rev": 2,
 "reason": "the passage now says positive n; the argument covers every n",
 "record": {"id": "f-bound-2", "coverage": "full", "basis": "checked_bridge",
            "composition": "c-bound-2",
            "note": "The argument gives C = 1 for every n, positive or not."}}
```

Both findings remain, and `show` lists `f-bound-2` as current. In a full assessment,
`machinechecked changes --workspace ID` lists the stale evidence, findings, questions,
counterexamples and compositions beside the reviews the new release reopened.

## A note for your project's AGENTS.md or CLAUDE.md

```md
## Paper and formalisation

This project formalises `paper/main.tex`. To see which claims are linked to Lean and what Lean
establishes about them, run `machinechecked check --json` after `lake build`
(install: `pip install machinechecked`, or run it with `uvx machinechecked`).
Links are in `machinechecked.links.json` and `\lean{}` tags. Report proof results for the
formal statement, and correspondence reviews with their recorded provenance.
```
