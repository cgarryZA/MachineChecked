# Development

MachineChecked has a Python engine and a static Svelte reader. The reader is compiled and shipped inside the Python package; ordinary users do not need Node.

## Work locally

```sh
pip install -e '.[test]'
pytest -q
(cd web && npm ci && npm run build)
(cd web && node tests/reader.test.mjs)   # the built reader in a browser, laptop and phone widths (needs the engine installed)
```

The web build is committed under `engine/python/prooflens/web/`. When editing `web/src/`, rebuild the bundle and keep its output in the same commit. CI checks that the shipped assets match the sources.

To exercise the zero-configuration flow, use `examples/plain-paper/`. For the locked-specification flow, use `examples/toy-paper/`. These are synthetic; public tests and examples must never include private manuscript or Lean content.

## Code map

| Location | Responsibility |
|---|---|
| `engine/python/prooflens/simple.py` | Find a paper, scan ordinary Lean projects and manage links |
| `engine/python/prooflens/tex.py` | Compile LaTeX and extract claim positions |
| `engine/python/prooflens/pdfclaims.py` | Find numbered statements in a PDF by their bold headings |
| `engine/python/prooflens/formalization.py` | Read a project's `formalization.yaml` |
| `engine/python/prooflens/paper.py` | A paper page's data (the site's paper pages), in the reader's standard format |
| `engine/python/prooflens/data/ProofLensProbe.lean` | Elaborated Lean declarations and dependency data |
| `engine/python/prooflens/deps.py` | `inspect`: a declaration's statement and proof dependencies |
| `engine/python/prooflens/facts.py` | The facts store: extracted Lean facts kept between builds, `inspect` and `check` |
| `engine/python/prooflens/proof_facts.py` | `compare --query proof-facts`: the typed facts inside one proof (the probe's `proof-facts` request), kept in the facts store |
| `engine/python/prooflens/assess.py` | Full-assessment states and findings |
| `engine/python/prooflens/review_queue.py` | Review units and queue ordering |
| `engine/python/prooflens/promote.py` | Maintainer-controlled review promotion |
| `engine/python/prooflens/manifest.py` | Data for the static reader |
| `engine/python/prooflens/bundle.py` | Portable HTML |
| `engine/python/prooflens/export.py` | Explicitly approved public exports |
| `web/src/` | Browser reader |
| `.github/workflows/pages.yml` | Publishes the toy audit CI built (its data only) for machinechecked.org's demo; the site itself is the `cgarryZA/machinechecked.org` repository |

## How a full assessment flows

```
acquire (credentials, no execution) -> extract and verify (sandboxed, no credentials)
    -> evidence store (content-addressed, append-only)
    -> release policy (allowlist, redaction, provenance)
    -> presentation manifest (chunked per claim) -> web reader / bundle / export
```

- **Hashes.** A legacy 128-bit structural hash is kept (`legacy_hash`) so that existing review markers keep matching; a versioned SHA-256 fingerprint (`pl-fp-v1`) of a canonical serialisation is computed beside it. Both detect structural change; neither shows that two expressions are mathematically equivalent.
- **Findings come in three tiers.** A `violation` is a mechanical contradiction and can fail CI; a `warning` is a heuristic and can be dismissed with a rationale bound to a fingerprint; an `obligation` needs a reviewer's judgement.
- **Lean sessions.** Both modes run the probe through `probe.lean_session`, one Lean session per library (`probe.by_library`): two libraries may declare the same name, and Lean can load both and silently keep one. A name two sessions find as different declarations is reported ambiguous, an error, never a choice. Modules of one library are one session, importing them in the order configured. Each request, and each declaration of a closure or the index, has its own heartbeat budget; a request that fails, even by exhausting it or the recursion depth, emits its own `probe-error` record and the session goes on (`tests/simple/test_probe_budget.py`, on Lean 4.24 and 4.32). In the zero-configuration view a library whose session fails is split in halves, and the message says why the session failed.
- **Extracted Lean facts** (`prooflens.facts`, used by `simple.LeanFacts` and `deps.inspect`): zero configuration stores what the probe extracts in `.machinechecked/build/facts/`: each built module's index (with the names in its docstrings that its environment does not know; names the project's index declares are left out when the view is built, since a module re-indexed alone sees only what it imports), each linked or suggested declaration's record (per declaration and module, with the records of its closure stored once by content), each checked bridge's `accept` answer (with the environment of the bridge theorem's module and the target's), each `inspect` answer, and the modules that could not be loaded. Each entry records the environment it came from: the digest of every module of the project or a path dependency in it (its source and the size and time of its compiled files), found through the import graph the probe's `modules` request reports, together with the probe, the MachineChecked version, the libraries, the toolchain, the lakefiles and the Lake manifests. An entry is reused only while all of these are unchanged, so an edit outside Lean starts no Lean session and an edit to a module reopens only what its importers extracted; modules of other packages are pinned by the manifest and toolchain. A session that does not finish, or a request that fails, stores nothing. A module that fails to load is stored as failed only when Lean reports an error in it (it does not import or elaborate); out of memory, a time limit, a heartbeat budget, a killed process or an unfinished session is stored only as an attempt, so the next build loads the module again and its progress line says that the earlier attempt failed (`probe.failure_is_deterministic`). Writes are atomic and extraction holds the store's lock, so concurrent identical requests make one extraction. Progress lines say what is reused and why anything is extracted. Deleting the folder costs only time (`tests/simple/test_facts.py`).
- **Kernel checking.** Comparator is the high-assurance replay; a build-cache hit or a text log is not a replay record.
- **Build cache** (`prooflens.cache`, `machinechecked cache`; `scripts/lean_cache.py` keeps the old script's arguments): a restore into another checkout rebuilds no module, a one-file change rebuilds only what it affects, archives over 2 GiB are split, corrupt, mismatched or incomplete archives are refused, a restore without the disk space for it is refused before it downloads, a restore that fails part way leaves the build untouched, and an archive in the older layout restores into a folder whose name differs in case and writes nothing beside it (`tests/simple/test_cache.py`). The reusable workflow `.github/workflows/audit.yml` is run by CI on the plain example.

## Seeded failures

Each failure a full assessment must catch has a test, mostly in `tests/mutations/`.

| Seeded failure | Required response | Test |
|---|---|---|
| `sorry` in a transitive dependency | violation; claim malformed | `test_sorry_in_a_transitive_dependency` |
| Acceptance theorem with an extra hypothesis | exact-type violation | `test_proof_with_an_extra_hypothesis` |
| Definition changed after review | fingerprint changes; review stale; claim not accepted | `test_changed_definition_reopens_its_review` |
| `∃ C, ∀ n` reversed to `∀ n, ∃ C` | quantifier order recorded and shown; review reopened | `test_quantifier_reversal`, `test_a_reviewed_statement_that_changes_reopens_its_review` |
| Zero witness for a nondegenerate regime | witness passes; regime obligation stays open | `test_regime_without_a_nondegenerate_witness` |
| Macro-generated numbered theorem not in the inventory | inventory-gap violation | `test_macro_generated_theorem_missing_from_the_inventory` |
| Manuscript claim edited | source-changed violation | `test_changed_manuscript_claim` |
| Author review declared human | still author-reviewed | `test_author_review_declared_human_is_still_not_independent` |
| Justified totalised operation | warning dismissed; dismissal lapses when the statement changes | `test_dismissal_lapses_when_the_statement_changes` |
| A proposition, proof, witness or definition the probe cannot find (its module not in `modules`) | violation naming the declaration, and the module that declares it when the source shows one; clause open; no statement shown or queued | `test_a_module_left_out_of_modules`, `test_a_proposition_in_a_module_the_probe_does_not_load` |
| Specification layer imports acceptance layer | layering violation | `test_specification_layer_importing_the_acceptance_layer` |
| Private source or PDF in an export | export blocked | `test_export_with_a_leak_is_blocked`, `test_unapproved_pdf_is_blocked` |
| Shell escape or writes outside the build directory | refused | `test_shell_escape_is_off`, `test_tex_cannot_write_outside_its_build_directory` |

Not yet covered: a manuscript and a displayed PDF from different commits (a provenance mismatch), and a quantifier reversal reported as a finding between two releases.

## Design principles

- The paper is the primary view. The Lean statement is one click away.
- Suggested links are not reviews. A passing Lean check is not correspondence with the paper.
- Use straightforward language and keep technical evidence available without making it the default view.
- The viewer displays statuses from evidence; it does not upgrade them.
- Keep private research out of this public repository. Run the private-content check before pushing.
- Preserve downstream acceptance results when changing extraction, schemas, proof checking or review logic.

The detailed engineering rules live in [CLAUDE.md](../CLAUDE.md). The evolving product direction is in [PLAN.md](../PLAN.md).

## Advanced commands

The public command is `machinechecked`; `prooflens` remains an alias for compatibility. Most users need only `view`, `build` and `check`.

`inspect NAME [--dependencies] [--json]` reports what a declaration's statement mentions and, separately, what its proof uses, through the whole project (the probe's `deps` request; every other record stays proof-erased). `compare --query proof-facts NAME` walks one declaration's elaborated proof term (the probe's `proof-facts` request): `have`, `let` of a proposition, `show`, and applications of project theorems or of theorems to a local fact, each with its local context, the locals it needs, the case arguments of eliminators it lies under and its sub-expression position. The walk enters no generated `_proof_` lemma (it lists them), visits shared closed sub-terms once, and stops at 200,000 nodes or 200 facts (query fields `facts_nodes`, `facts_items`), saying so; each fact is printed with its own heartbeat budget, and a request that fails emits a `probe-error` for itself only. Statement fingerprints are unchanged: the request adds a record of its own. Full-assessment users can use `reassess` (new reviews without a Lean re-probe), `site` (regenerate the reader from stored evidence), `bundle` (single-file HTML), `export` (approved public data) and `review promote` (maintainer approval).

## Releasing

Bump `version` in `pyproject.toml` on `main`. The `Release` workflow then tags the commit
`v<version>`, creates the GitHub release and publishes the package to PyPI by trusted publishing;
a version that already has a tag is left alone. Run it by hand from the Actions tab if needed.
