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

In a project with a `machinechecked.toml` (the full assessment), the document also has
`findings` (totals per tier, dismissed warnings left out) and `finding_details`: each finding
with its `tier` (`violation`, `obligation`, `warning`), `code`, `subject` (the claim or clause,
for example `T:thm:bound#0`), `message`, and `dismissed` (who and why) when a warning was
dismissed. Report the violations and obligations by subject and message; they are what blocks a
claim from being accepted.

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
  "coverage": "full", "basis": "direct", "evidence": ["e-1"],
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
