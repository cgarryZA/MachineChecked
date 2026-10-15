# ProofLens: plan of record

ProofLens shows a mathematical paper beside its Lean formalisation and says, for every claim of
the paper, exactly what has been established about it. It separates three things that a Lean
build alone does not:

1. **Evidence**: what the kernel, the acceptance checks and the source checks established.
2. **Interpretation**: whether the formal statements say what the paper says, which only a
   reviewer can judge.
3. **Presentation**: how a reader explores both without knowing Lean.

The views only display evidence. They cannot compute, change or upgrade a status.

## Architecture

```
acquire (credentials, no execution) -> extract and verify (sandboxed, no credentials)
    -> evidence store (content-addressed, append-only)
    -> release policy (allowlist, redaction, provenance)
    -> presentation manifest (chunked per claim) -> web reader / PDF / PR report
```

| Part | Where | Role |
|---|---|---|
| Lean probe | `engine/python/prooflens/data/ProofLensProbe.lean` | run inside a project with `lake env lean`; exact-type and axiom checks, unfolded statements, fingerprints |
| TeX anchors | `engine/python/prooflens/data/prooflens.sty` | injected before `\documentclass`; records number, label, source line and PDF position of every claim |
| Engine | `engine/python/prooflens/` | acquisition, compilation, assessment, evidence store, manifest, export |
| Schemas | `engine/python/prooflens/data/schema/` | inventory, evidence, manifest |
| Reader | `web/` | static Svelte app: Read, Coverage, Audit, Changes |
| Example | `examples/toy-paper/` | synthetic paper and Lean project; the public demo and the test fixture |
| Tests | `tests/` | contracts, seeded mutations, security |

The policies are in `docs/`: [threat model](docs/THREAT_MODEL.md),
[evidence policy](docs/EVIDENCE_POLICY.md), [data model](docs/DATA_MODEL.md),
[publication policy](docs/PUBLICATION_POLICY.md).

## Decisions

- **An existing acceptance system stays authoritative** until Phase 5. ProofLens reads its
  outputs and never modifies its tools. Integrations with real projects, their fixtures and
  baselines live in those projects' own (possibly private) repositories, pinned to exact commits.
  This public repository holds only generic code and synthetic examples, and nothing from any
  private repository.
- **Paper sources**: LaTeX first; if no LaTeX root is found, use the PDF from the same source.
  Git sources are pinned to a commit. Several candidate roots need an explicit `root`. A committed
  PDF is a pinned artifact, not a reproducible build.
- **Hashes**: a legacy 128-bit structural hash is kept (`legacy_hash`), so existing review
  markers keep matching. A versioned SHA-256 fingerprint (`pl-fp-v1`) of a canonical
  serialisation is computed beside it. Both detect structural change. Neither shows two expressions
  are mathematically equivalent.
- **Findings come in three tiers**:
  - `violation`: a mechanical contradiction; it can fail CI.
  - `warning`: a heuristic; it can be dismissed with a rationale bound to a fingerprint.
  - `obligation`: needs a reviewer's judgement.
- **Reviewer provenance** is shown, never upgraded. A Markdown marker is *self-declared*. A review
  by an author of the statements is never independent, whatever it declares. Whether a review was
  by a human or an AI is recorded.
- **Kernel checking**: Comparator stays the high-assurance release verifier. `leanchecker` will
  be added as a cheap diagnostic.
- **Links are release-pinned**: `#/r/<release>/...`. A link that names an older release shows a
  banner instead of silently showing newer evidence.
- **Verso Blueprint**: an optional adapter in Phase 6. It is never the acceptance authority.

## Progress

- **Phase 0**: done.
- **Phase 1**: done on a private project (its integration and baseline are recorded there).
- **Phase 2**: in progress. Done:
  - the evidence ladder with exact statement, axioms and kernel replay apart, and "why is
    this claim not accepted?";
  - a content-addressed declaration store;
  - search;
  - grouped warnings;
  - claims recorded by line located by SyncTeX (approximate, ambiguous when unsure) or by
    hand;
  - one-file bundles for private projects;
  - the Pages workflow for the toy demo.
- **Build cache** (`scripts/lean_cache.py`): done. A restore at a different path rebuilt no
  module; a one-file change rebuilt exactly its dependants; corrupt or mismatched archives are
  refused.

## Phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0 Foundations** | Policies; schemas; toy paper; probe (unfolded statements, exact types, axioms, both hashes); TeX anchors; evidence store; manifest; export with leak scan; reader; contract, mutation and security tests; CI; cloud setup | the toy paper works end to end in CI; schemas validate; a planted leak blocks the export; nothing private is committed |
| **1 Read-only integration** | Read an existing acceptance layer (inventory, statuses, review files, release-gate output, Comparator logs) at a pinned commit, from the project's own repository; the probe over every proposition | every claim and clause represented; statuses equal to the existing system's; every proposition inspectable; release gate shown apart from the consistency check; the existing tools unmodified |
| **2 Full reader** | The four views on real papers; correctable anchors; search; permalinks; toy demo published on Pages; private projects' sites stay private (`prooflens serve` or a private artifact) | every claim has a working permalink and its correct status; an anchor that may be wrong is flagged, not guessed; a mathematician audits a main theorem without opening Lean source |
| **3 Source correspondence** | Three-way extraction: source parser (compatibility authority for `source_sha256`), TeX instrumentation, `.fls` inventory audit; pinned-vs-displayed provenance; PDF-only mode with byte and text hashes | historical hashes reproduce exactly; macro-generated material surfaces as discrepancies; a PDF from another commit is a provenance mismatch |
| **4 Drift and assurance** | Release comparison; the drift types listed below; PR reports (no `pull_request_target`); more warning detectors with measured false-positive rates; `leanchecker` beside Comparator results; review attestations bound to (manuscript, spec, closure) fingerprints | the seeded-failure table below passes; false-positive rates measured on Papers A and B |
| **5 Reusable engine** | Generalised CLI and Lean package; reusable GitHub Action | semantic results agree with the existing acceptance system; its report reproduces byte for byte as a compatibility check; mutation suite passes on the port |
| **6 Publication and ecosystem** | Release approval per paper; immutable versioned public sites; "Paper with Formal Verification Audit" PDF; arXiv sources; hostile-input hardening; dependency X-ray; Blueprint adapter; notebook / live Lean last | no unapproved content can reach an export; release URLs stable; an unrelated repository adopts ProofLens |

The drift types for Phase 4:

- proof implementation changed;
- statement or definition changed;
- manuscript claim changed;
- presentation only;
- toolchain or foundation changed;
- branch ahead of the pin (informational).

### Seeded failures

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
| Manuscript and displayed PDF from different commits | provenance mismatch | Phase 3 |
| Quantifier reversal as an explicit finding between releases | drift finding | Phase 4 |
