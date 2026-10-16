# Using MachineChecked with a coding agent

MachineChecked is a command-line tool, so a coding agent (Claude Code, Codex, Cursor and others)
can run it like any other. Two things help it do so well.

## Install the skill

[`skills/machinechecked/SKILL.md`](../skills/machinechecked/SKILL.md) is an
[Agent Skill](https://agentskills.io): it tells an agent when to use MachineChecked, which
commands to run, how to read their output, and what the statuses do and do not mean. Copy the
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
not proved, and 2 when the check could not run (a missing program such as `lake`, no Lean
project, a paper that cannot be read, a failed Lean probe). In that last case the document has
`"ok": false` and an `error` (`kind`: `missing-tool` with the `tool`, `error`, or `internal`;
`message`) and no claims: nothing is known about them. Progress goes to stderr, so stdout is only
the JSON.

## A note for your project's AGENTS.md or CLAUDE.md

```md
## Paper and formalisation

This project formalises `paper/main.tex`. To see which claims are linked to Lean and what Lean
establishes about them, run `machinechecked check --json` after `lake build`
(install: `pip install machinechecked`, or run it with `uvx machinechecked`).
Links are in `machinechecked.links.json` and `\lean{}` tags; they say which declaration
corresponds to a claim, not that it says what the paper says. Do not describe a claim as
verified on the strength of a "Lean proof checked" status.
```
