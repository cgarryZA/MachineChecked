# Development

MachineChecked has a Python engine and a static Svelte reader. The reader is compiled and shipped inside the Python package; ordinary users do not need Node.

## Work locally

```sh
pip install -e '.[test]'
pytest -q
(cd web && npm ci && npm run build)
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
| `engine/python/prooflens/data/ProofLensProbe.lean` | Elaborated Lean declarations and dependency data |
| `engine/python/prooflens/assess.py` | Full-assessment states and findings |
| `engine/python/prooflens/review_queue.py` | Review units and queue ordering |
| `engine/python/prooflens/promote.py` | Maintainer-controlled review promotion |
| `engine/python/prooflens/manifest.py` | Data for the static reader |
| `engine/python/prooflens/bundle.py` | Portable HTML |
| `engine/python/prooflens/export.py` | Explicitly approved public exports |
| `web/src/` | Browser reader |
| `site/index.html` | Product landing page |

## How a full assessment flows

```
acquire (credentials, no execution) -> extract and verify (sandboxed, no credentials)
    -> evidence store (content-addressed, append-only)
    -> release policy (allowlist, redaction, provenance)
    -> presentation manifest (chunked per claim) -> web reader / bundle / export
```

- **Hashes.** A legacy 128-bit structural hash is kept (`legacy_hash`) so that existing review markers keep matching; a versioned SHA-256 fingerprint (`pl-fp-v1`) of a canonical serialisation is computed beside it. Both detect structural change; neither shows that two expressions are mathematically equivalent.
- **Findings come in three tiers.** A `violation` is a mechanical contradiction and can fail CI; a `warning` is a heuristic and can be dismissed with a rationale bound to a fingerprint; an `obligation` needs a reviewer's judgement.
- **Kernel checking.** Comparator is the high-assurance replay; a build-cache hit or a text log is not a replay record.
- **Build cache** (`scripts/lean_cache.py`): a restore at a different path rebuilds no module, a one-file change rebuilds exactly its dependants, and corrupt or mismatched archives are refused.

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

Full-assessment users can use `reassess` (new reviews without a Lean re-probe), `site` (regenerate the reader from stored evidence), `bundle` (single-file HTML), `export` (approved public data) and `review promote` (maintainer approval).
