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
`message`); they do not change the exit code.

In a project with a `machinechecked.toml` (the full assessment), the document also has
`findings` (totals per tier, dismissed warnings left out) and `finding_details`: each finding
with its `tier` (`violation`, `obligation`, `warning`), `code`, `subject` (the claim or clause,
for example `T:thm:bound#0`), `message`, and `dismissed` (who and why) when a warning was
dismissed. A warning with code `module-doc-name` is a name a module docstring lists that nothing
declares: its `subject` is the module, its `trigger` the name, and it has `file` and `line`.
Report the violations and obligations by subject and message; they are what blocks a
claim from being accepted. `replay` is null when no Comparator replay counts; otherwise it
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
  nobody has confirmed. `lean.definitions` are the definitions the statements use, with their
  type and value; `generated_for` marks the equations Lean generated for one of them.
- `interpretations` (stage `informed`, the default): the correspondence note, review reports,
  author's review markers, symbol links, the status and the assessment's findings.
- `retrieval`: what is `included`, what the stage `withheld`, what is `unavailable` because it
  is not extracted yet (with the issue that owns it), what a targeted query gives `on_request`
  (`uses`, which runs Lean), and the cursor of the definitions list.

`--stage read` holds the paper only and `--stage compare` adds the Lean without any recorded
interpretation; the review protocol's `--json` output uses the same stages. Passages and linked
statements are never shortened; `--limit N` pages the definitions, and `--after ID` (the
`retrieval.definitions.next` it returns) continues them.

Targeted queries have one shape (`machinechecked/query@1`: `op`, `target`, `context`,
`results`, `provenance`, `retrieval`):

```sh
machinechecked compare --query definition Toy.triangle --json   # its type, value, equations
machinechecked compare --query mentions Toy.triangle --json     # statements that use it
machinechecked compare --query dependencies Toy.Acceptance.thm_bound --json   # runs inspect
machinechecked compare --query uses Toy.IsEven --json          # where it is used, and how
```

`mentions` searches the statements of the build in full and the project's index by a preview
of each type (`complete: false` on such a result: get its statement with `dependencies`).

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
answers until a Lean input changes. The queries `proof-facts`, `composition` and `impact`
answer `available: false` with the issue that owns their extraction. An error is `{"ok": false, "error": {kind, message,
candidates}}` with exit 1 (exit 2, kind `no-build`, when there is no build to read: run
`view` or `build`); `candidates` lists the claims or declarations you may have meant.

A complete inspection, in the toy example:

```sh
cd examples/toy-paper && machinechecked build
machinechecked compare thm:bound --json > packet.json      # read paper.passages[0].text
machinechecked compare --query definition Toy.triangle      # what T_n is in Lean
machinechecked compare --query mentions Toy.triangle        # other results about T_n
```

The passage says there is one constant `C` for every `n`; the locked statement's text is
`∃ (C : Nat), ∀ (n : Nat), Toy.triangle n ≤ C * (n * n)`, which chooses `C` before `n`, and
`Toy.triangle` is the recursion `T_(n+1) = T_n + n + 1`. A finding records that, quoting the
`snapshot` and the declaration's `fingerprint`; as a review it goes through `machinechecked
review` (below), which keeps the protocol's order.

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
`unchecked`) and the `resume` point. A workspace started in informed mode records that the Lean
was seen; `{"op": "exposure", "what": "external material"}` records anything else you read.

## A note for your project's AGENTS.md or CLAUDE.md

```md
## Paper and formalisation

This project formalises `paper/main.tex`. To see which claims are linked to Lean and what Lean
establishes about them, run `machinechecked check --json` after `lake build`
(install: `pip install machinechecked`, or run it with `uvx machinechecked`).
Links are in `machinechecked.links.json` and `\lean{}` tags. Report proof results for the
formal statement, and correspondence reviews with their recorded provenance.
```
