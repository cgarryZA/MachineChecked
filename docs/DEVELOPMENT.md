# Development

MachineChecked has a Python engine and a static Svelte reader. The reader is compiled and shipped inside the Python package; ordinary users do not need Node.

## Work locally

```sh
pip install -e '.[test]'
pytest -q
pytest -q --shard 2/4                    # the second of CI's four shards of the suite
(cd web && npm ci && npm run build)
(cd web && node tests/reader.test.mjs)   # the built reader in a browser, laptop and phone widths (needs the engine installed)
```

The web build is committed under `engine/python/prooflens/web/`. When editing `web/src/`, rebuild the bundle and keep its output in the same commit. CI checks that the shipped assets match the sources.

CI runs the suite in four shards on parallel runners, and its `test` check passes when every shard does. `tests/shards.py` deals out whole test files, longest first, by their times in `tests/durations.json`; each collected test is in exactly one shard, and a file the times do not list counts at the mean time per test. When the shards' times drift apart, download the times of one or more CI runs (`gh run download RUN_ID -p 'test-times-*' -D run-a`) and run `python tests/shards.py run-*/test-times-*/test-times.json` to rewrite `tests/durations.json`. Runners differ in speed by a third or more, so a shard's time varies with its runner; two runs let the script fit each file's time on a runner of average speed.

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
| `engine/python/prooflens/uses.py` | `inspect --used-by` and `compare --query uses`: reverse references and applications with the source of each premise |
| `engine/python/prooflens/facts.py` | The facts store: extracted Lean facts kept between builds, `inspect` and `check` |
| `engine/python/prooflens/proof_facts.py` | `compare --query proof-facts`: the typed facts inside one proof (the probe's `proof-facts` request), kept in the facts store |
| `engine/python/prooflens/assess.py` | Full-assessment states and findings |
| `engine/python/prooflens/review_queue.py` | Review units and queue ordering |
| `engine/python/prooflens/promote.py` | Maintainer-controlled review promotion |
| `engine/python/prooflens/manifest.py` | Data for the static reader |
| `engine/python/prooflens/bundle.py` | Portable HTML |
| `engine/python/prooflens/export.py` | Explicitly approved public exports |
| `web/src/` | Browser reader |
| `.github/actions/browser/` | CI's Chromium: the browser of the pinned Playwright version and the system packages it needs, with bounded, retried downloads kept in caches |
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
- **Lean sessions.** Both modes run the probe through `probe.lean_session`, one Lean session per library (`probe.by_library`): two libraries may declare the same name, and Lean can load both and silently keep one. A name two sessions find as different declarations is reported ambiguous, an error, never a choice. Modules of one library are one session, importing them in the order configured. Each request, and each declaration of a closure or the index, has its own heartbeat budget; a request that fails, even by exhausting it or the recursion depth, emits its own `probe-error` record and the session goes on (`tests/simple/test_probe_budget.py`, on Lean 4.24 and 4.32). The probe flushes its output, ends with a `done` record giving the number of bytes before it, and exits with an error when a write fails. `lean_session` reads the output only when it ends with that record and the count matches; otherwise, or when a line does not decode, it raises `ProbeError` naming the file, the line and the free space of its file system (before and after the session). A full disk counts as a resource failure, never as an error in a module. With `MACHINECHECKED_KEEP_PROBE` set, the partial output is moved to the work directory (`tests/contracts/test_probe_output.py`, on Lean 4.24 and 4.32). In the zero-configuration view a library whose session fails is split in halves, and the message says why the session failed (its first error, as `simple.loading_error` gives it).
- **Extracted Lean facts** (`prooflens.facts`, used by `simple.LeanFacts` and `deps.inspect`): zero configuration stores what the probe extracts in `.machinechecked/build/facts/`: each built module's index (with the names in its docstrings that its environment does not know; when the view is built, a name the indexed modules hold is left out, as their index declares it or their `refs` records list it (every constant, those Lean generates included), since a module re-indexed alone sees only what it imports; a name that remains is looked for among the constants of the modules of a library left out of the paper's index whose sources could hold it, by the scope rule below, indexed for that question alone (`tests/simple/test_scope.py`)), each linked or suggested declaration's record (per declaration and module, with the records of its closure stored once by content), each checked bridge's `accept` answer (with the environment of the bridge theorem's module and the target's), each `inspect` answer, and the modules that could not be loaded (with the start and the end of what the session printed, and, for a module loaded on its own after its library's session failed, that library and its number of modules: a link's `status_detail`, the build's note, `uses`, `inspect`, proof facts and certificate checks give the first lines, `simple.loading_error`). Each entry records the environment it came from: the digest of every module of the project or a path dependency in it (its source and the size and time of its compiled files), found through the import graph the probe's `modules` request reports, together with the probe, the MachineChecked version, the libraries, the toolchain, the lakefiles and the Lake manifests. An entry is reused only while all of these are unchanged, so an edit outside Lean starts no Lean session and an edit to a module reopens only what its importers extracted; modules of other packages are pinned by the manifest and toolchain. A session that does not finish, or a request that fails, stores nothing. A module that fails to load is stored as failed only when Lean reports an error in it (it does not import or elaborate); out of memory, a time limit, a heartbeat budget, a killed process or an unfinished session is stored only as an attempt, so the next build loads the module again and its progress line says that the earlier attempt failed (`probe.failure_is_deterministic`). Writes are atomic and extraction holds the store's lock, so concurrent identical requests make one extraction. Progress lines say what is reused and why anything is extracted. Deleting the folder costs only time (`tests/simple/test_facts.py`).
- **A refresh** (`build --refresh`, `LeanFacts(refresh=True)`) uses a stored entry only if the same build wrote it, so every fact the build reads (each indexed module's index, each linked or suggested declaration's record, each bridge's answer, each recorded load failure) is extracted again and replaces the stored one; entries it does not read stay. A refresh and a build that reuses the stored facts give the same view (`tests/simple/test_facts.py`). In a full assessment, `--refresh` discards the stored module indexes and load failures before the build.
- **Index scope** (`simple.index_scope`): a paper's build indexes every built module except those of a library whose namespace formalization.yaml maps only to other papers (`formalization.foreign_roots`). A module of such a library is indexed all the same whenever it could hold a linked name, so that a name two libraries declare is found in both and a link never reads checked where indexing every library would make it ambiguous. Including a module costs only time; leaving out one that holds the name could round a status up. A module could hold a linked name when the file names it as a linked declaration's module; when its source contains, as a whole word and in any case, one of the name's words (`simple.name_words`: each component of the name, which is the last component of the name and of each of its prefixes, and each beginning of one at an underscore, with and without trailing primes); when its source uses an attribute that translates names (`to_additive`, `to_dual`); or when its source cannot be read. The words cover the names Lean generates, which extend a name some source declares or a namespace it enters: projections, constructors, recursors, equation lemmas and auxiliary definitions, and the names `simps`, `mk_iff` or `irreducible_def` append to. Every module is indexed, as before libraries were left out, when a linked name has a component starting with `inst` (Lean names instances itself, `deriving` included, and their fields, `instReprFoo.repr`), when it is written in `«»`, or when a source of the project defines commands, builds declarations in a quotation or runs code that adds them (`: command`, `` `(def … ``, `run_cmd`, `CommandElabM`, `addDecl`, `initialize`, …). Not detected: a command of a dependency other than these attributes that names its declarations with words its call does not contain. A linked name no module in scope holds is still looked for in the modules left out, and its answer is stored per session like any other. The index holds theorems, definitions, inductive types, opaque constants and axioms; the reverse references read in the same sessions (`refs` records) list every constant of each module, instances, constructors, recursors, equation lemmas and projections included. A linked name is checked in every module in scope whose index or `refs` records hold it, so a hand-written name that another library has only as a generated constant reads ambiguous and names both modules, with or without a scope (`tests/simple/test_generated_names.py`). A name the index sessions of a build answered is taken from them only when they loaded every module that holds it; otherwise those modules are loaded for it. The scope is read from sources alone; the view records it (`index_scope`, also in the site's `index.json`), and its note names the libraries left out. `compare --query search --all-libraries` searches the index of every built module (`simple.project_index`), indexing what the store does not hold; `inspect` never depended on the index (`tests/simple/test_scope.py`).
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
| Hypothesis hidden in an instance (`[Fact (1 < p)]`, `[NeZero 0]`) beside standard instances | witness obligation naming that binder; instance-only propositions get a low-signal warning | `test_a_premise_or_an_unlisted_class_keeps_the_obligation_and_names_its_binder` |
| Macro-generated numbered theorem not in the inventory | inventory-gap violation | `test_macro_generated_theorem_missing_from_the_inventory` |
| Manuscript claim edited | source-changed violation | `test_changed_manuscript_claim` |
| Claim pinned at its label line, or mid-sentence | `source-region` warning naming the paragraph; no status changes | `test_label_lines_partial_sentences_and_section_crossings`, `test_advice_is_a_dismissible_warning_that_changes_no_status` |
| Author review declared human | still author-reviewed | `test_author_review_declared_human_is_still_not_independent` |
| Justified totalised operation | warning dismissed; dismissal lapses when the statement changes | `test_dismissal_lapses_when_the_statement_changes` |
| Two suprema in one statement, one dismissed; one's type changed; both moved | two warnings, the other stays open; only the changed one's dismissal lapses; both dismissals follow; a dismissal of the old form dismisses both until the statement changes | `test_each_supremum_is_judged_by_its_type` (`each_occurrence_has_its_own_finding`) |
| A real supremum with or without its bound, a bound for another family, `Integrable f μ` beside `∫ g ∂μ` and `∫ f ∂ν`, finiteness almost everywhere | established and the warning resolved; unresolved, never refuted; only `∫ f ∂μ` established; unresolved | `test_each_supremum_is_judged_by_its_type` (`side_conditions`) |
| Review text citing a lemma or file that does not exist | warning with file and line (violation with `review_citations_strict`); no status changes | `test_a_dangling_citation_is_a_warning_or_in_strict_mode_a_violation` |
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

### Content search and paper numbers

`retrieval.py` indexes every user-facing declaration of the project's built modules from the
probe's `index` records: the complete statement, the docstring, the name, and the project
constants the statement mentions (`uses`) and the value uses (`value_uses`). A text's terms are
words (split at underscores and capitals, lower case, lightly stemmed), symbols (`\le`, `≤` and
`<=` are one term; `≥` is folded into `≤`), numerals and dotted constants. A declaration's
score is the share of the query's rarity-weighted terms it carries; the users of the ten best
matches join the results through them. The zero-configuration view writes the index to
`data/retrieval.json` with its word tables, and so does the full assessment (`content.py`: the
index of every built module from the facts store, with `LeanFacts.index`, and the paper-number
check of a one-paper configuration, kept in `<work>/content/<evidence id>.json` beside the
evidence record and never in it; a reassessed record shows the content of the record it was
reassessed from); `web/src/lib/retrieval.js` reads the tables from it
and implements the same scoring. `tests/fixtures/retrieval/make_cases.py` writes the cases both
must answer alike (`tests/contracts/test_retrieval.py` checks the file is current, and
`web/tests/retrieval.test.mjs` runs the reader's side): regenerate it after changing either.
The same test measures retrieval on a synthetic index of 40,000 declarations.

`numbering.py` finds references to numbered statements in docstrings, names and module
docstrings and checks them against the paper's claims and, from the compilation's table of
contents, its sections. `simple.suggest` combines content (weight 0.7), cited numbers (0.2,
less for a possibly stale lead) and names (0.1). The fixture `tests/fixtures/renumbered` is a
paper renumbered after its Lean was written.

`inspect NAME [--dependencies] [--json]` reports what a declaration's statement mentions and, separately, what its proof uses, through the whole project (the probe's `deps` request; every other record stays proof-erased). `inspect NAME --used-by` reports the other direction: the probe's `apps` request lists the declarations whose statement or value mentions NAME (`user` records) and describes each application of it in their values (`app` records: each binder with its actual argument, the instantiated premise, the origin of the proof supplied, and the type of the application). The search enters a value only along subterms that mention NAME, examines each shared subterm once (at most a million per user), describes at most 8 applications in each of at most 30 users, and prints a term above 600 nodes by its head only; `appscan` and `uses` records say what a bound left out. The `refs` request gives every declaration's references to the project's constants, from which `uses.py` derives further callers and the reader's `data/uses.json` (the zero-configuration build asks it in the indexing sessions and stores it per module with the index in the facts store; a `uses` answer is stored there too, reopened by an edit to any module of the project). `compare --query proof-facts NAME` walks one declaration's elaborated proof term (the probe's `proof-facts` request): `have`, `let` of a proposition, `show`, and applications of project theorems or of theorems to a local fact, each with its local context, the locals it needs, the case arguments of eliminators it lies under and its sub-expression position. The walk enters no generated `_proof_` lemma (it lists them), visits shared closed sub-terms once, and stops at 200,000 nodes or 200 facts (query fields `facts_nodes`, `facts_items`), saying so; each fact is printed with its own heartbeat budget, and a request that fails emits a `probe-error` for itself only. Statement fingerprints are unchanged: the request adds a record of its own. Full-assessment users can use `reassess` (new reviews without a Lean re-probe), `changes` (what changed between two releases, and the reviews it reopens, `changes.py`), `site` (regenerate the reader from stored evidence), `bundle` (single-file HTML), `export` (approved public data) and `review promote` (maintainer approval).

## Releasing

Bump `version` in `pyproject.toml` on `main`. The `Release` workflow then tags the commit
`v<version>`, creates the GitHub release and publishes the package to PyPI by trusted publishing;
a version that already has a tag is left alone. Run it by hand from the Actions tab if needed.
