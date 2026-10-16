# MachineChecked — project instructions

MachineChecked (formerly ProofLens) shows a mathematical paper beside its Lean formalisation and says, per claim, what is
established. `README.md` is the short introduction and `docs/GETTING_STARTED.md`,
`docs/REVIEWING.md`, `docs/ASSURANCE.md` the user's guides; `docs/DEVELOPMENT.md` holds engine
internals and the seeded-failure tests; `PLAN.md` is the plan of record (keep it to what is being
built and the settled decisions, not a history); `docs/` also holds the threat model, evidence
policy, data model and publication policy. Read `docs/EVIDENCE_POLICY.md` before changing anything
that computes or displays a status. When a feature changes, update the guide that describes it.

## Rules that do not bend

- **This repository is public. Nothing of a private project goes into it**: no names, counts,
  declaration names, statements, review text or LaTeX/Lean lines from a private formalisation,
  in files, tests, fixtures or commit messages. Use the synthetic examples
  (`examples/toy-paper`, `examples/plain-paper`) or write a new synthetic one.
- **Before every commit that will be pushed**: stage first (`git add -A`), then run the
  private-content check, then commit only if it exits 0. The check is
  `scripts/check_public.py --denylist <file> --private-source <dir>`; the denylist and the
  private sources live outside this repository (a downstream project provides a wrapper script).
  Never pipe the check's output (`| tail` hides its exit status), and never run it before
  staging (new files are not scanned).
- **A status is never rounded up.** The words the reader shows are exactly those the engine
  computed (`assess.py`); a link is not a review, an author's review is not independent, a text
  log is not a replay record, an approximate anchor is drawn as approximate. When unsure,
  under-claim.
- **Evidence, not opinion, changes a status.** Displays (`display` overlay, headings, titles) may
  change what is shown, never what is assessed; there is a test for that
  (`tests/contracts/test_display.py`).
- **The review queue records, the maintainer decides.** A report never writes a marker;
  `prooflens review promote` does, after its refusals (`promote.py`). Keep the protocol order:
  reading locked before the Lean is shown, verdict recorded before the author's review.

- **MachineChecked is a tool and a host, not a certifier.** An audit says what its author linked,
  checked and recorded, under their name; the site never endorses it. Reports ("Raise issue") go
  to the repository the audit names, carry identifiers only (never statement text), and change no
  status. A paper has one page; several Lean projects are alternative sources of evidence for its
  claims and are never merged into one verdict (see `PLAN.md`).

## Tracking work

As things are suggested and agreed (by the owner, or in a review the owner accepts), log each item
as a GitHub issue in the repository it affects (`cgarryZA/MachineChecked`,
`cgarryZA/machinechecked.org`, or a downstream project's own repository): one issue per item, saying
what, why, and when it is done, with a label for its kind (`bug`, `enhancement`, `cleanup`,
`docs`). Each repository has its own GitHub Projects board as its kanban, whose auto-add
workflow picks up the repository's new issues (sessions cannot use the Projects API). Log first; do not start an
issue's work until it is agreed to be worked on, and close it with the commit that does it
(`Fixes #n`). Issues in public repositories follow the privacy rules above: nothing of a private
project, written generically.

## Names

The product, the command and the files are `machinechecked` (`machinechecked.toml`,
`machinechecked.links.json`, `.machinechecked/`); the older `prooflens` names are still read, and
`prooflens` is an alias of the command. The Python package directory is still
`engine/python/prooflens` and data schema ids are still `prooflens/...@N`: renaming them would
break stored evidence and exported reports for no user-visible gain.

## Layout

| Path | What |
|---|---|
| `engine/python/prooflens/` | the engine: `cli.py` (commands), `simple.py` (zero configuration), `pipeline.py` (full assessment), `assess.py` (statuses), `manifest.py` (site data), `tex.py` + `data/prooflens.sty` (LaTeX anchors), `paper.py` (the site's paper pages), `cache.py` (the Lean build cache), `data/ProofLensProbe.lean` (the Lean probe), `review_queue.py`, `promote.py`, `bundle.py`, `export.py` |
| `engine/python/prooflens/web/` | the **built** reader, committed (users need no Node) |
| `web/src/` | the reader's sources (Svelte 5, Vite, pdf.js 4.10, KaTeX) |
| `tests/` | `contracts/`, `mutations/`, `security/`, `simple/`; `conftest.py` copies the toy example per test |
| `examples/` | `toy-paper` (full assessment, the main fixture), `plain-paper` (zero configuration) |
| `scripts/` | `check_public.py`, `lean_cache.py` (the build cache's old arguments, for setup scripts), `cloud-setup.sh` |

## Commands

```sh
pip install -e '.[test]'
pytest -q                                   # ~4 min; needs elan + TeX Live for most tests
(cd examples/plain-paper && lake build)     # the zero-configuration tests need it built
(cd web && npm ci && npm run build)         # after any change under web/src: commit the result
(cd web && node tests/reader.test.mjs)      # the reader in a browser (CHROMIUM=/opt/pw-browsers/chromium in cloud sessions)
```

- After changing `web/src`, rebuild and commit `engine/python/prooflens/web/`; CI fails if the
  committed build differs from the sources. The build is deterministic.
- After changing `data/prooflens.sty` or `tex.py`, the zero-configuration TeX cache is keyed on
  them, so it rebuilds by itself.
- To see the reader: `prooflens build` in an example, then serve `.prooflens/site` or open the
  bundle; headless Chromium is at `/opt/pw-browsers/chromium` in cloud sessions.

## The Lean probe

`data/ProofLensProbe.lean` is compiled against the user's project (`lake env lean`), so it must
build on every Lean version users have, not only this repository's examples. Prefer stable core
APIs; test a change on a project with a different toolchain when you can. A request that fails
emits a `probe-error` record for that request instead of failing the whole probe.

## Regression against a real formalisation

A downstream private project runs this engine on its papers and compares every status with its
own acceptance checker (0 differences is the bar). Changes to `assess.py`, `manifest.py`,
`tex.py`, the probe or the review parsers must keep it at 0; that check is run from the
downstream project, and its results are reported without its content.

## Style

- Comments and docstrings say what the code does or why, in plain sentences; they do not narrate
  the session or the history of a change.
- Status words and user-facing messages are plain English, without jargon a mathematician would
  not know; no percentages of "verification".
- Keep the command surface small: `view`, `build`, `check` (and `review promote`); other
  commands (the full assessment's, and `cache`) stay out of the main command list.
