# Structured status contract

The assessor selects `status_code`; the reader never classifies a label. The exact code is
carried through the assessment, manifest index, claim record, search index, CLI JSON and public
export. Simple links select their code where the probe or module resolver observes the result.
`status` and `class` are derived snapshots for CLI consumers, not inputs to browser logic.

`engine/python/prooflens/data/statuses.json` is the shared vocabulary. Python's `status.fields`
and the reader's small `presentation.js` read it directly. Unknown codes use a neutral
“Status unavailable” fallback, including when supplied with an apparently accepted label or
colour. The frontend never recomputes acceptance from the evidence dimensions.

## Status inventory

| Code | Label | Class |
|---|---|---|
| `unknown` | Status unavailable | `unspecified` |
| `formal.accepted` | formal: accepted | `accepted` |
| `formal.author-reviewed` | formal: proved, author-reviewed | `proved` |
| `formal.review-pending` | formal: proved, review pending | `proved` |
| `formal.open` | formal: open | `open` |
| `formal.unspecified` | formal: unspecified | `unspecified` |
| `formal.malformed` | formal: malformed | `malformed` |
| `formal.unchecked` | formal: unchecked | `unspecified` |
| `definition.unchecked` | definition: unchecked | `unspecified` |
| `definition.unstated` | definition: not yet stated | `unspecified` |
| `definition.review-pending` | definition: review pending | `open` |
| `definition.author-reviewed` | definition: author-reviewed | `proved` |
| `definition.reviewed` | definition: reviewed | `accepted` |
| `link.missing` | linked: Lean declaration not found | `malformed` |
| `link.definition` | linked: Lean definition | `proved` |
| `link.incomplete` | linked: Lean proof incomplete (sorry) | `open` |
| `link.axioms` | linked: Lean proof uses further axioms | `open` |
| `link.checked` | linked: Lean proof checked | `proved` |
| `link.unbuilt` | linked: Lean not checked (the project is not built) | `unspecified` |
| `link.module-unbuilt` | linked: Lean not checked (module not built) | `unspecified` |
| `link.module-failed` | linked: Lean not checked (module could not be loaded) | `unspecified` |
| `link.ambiguous` | linked: Lean name is ambiguous | `unspecified` |
| `link.no-audit` | linked: Lean not checked here (no audit published) | `declared` |
| `link.not-in-audit` | linked: Lean not checked here (the published audit does not list it) | `declared` |
| `link.suggested` | suggested link, not confirmed | `unspecified` |
| `link.none` | not linked | `unspecified` |
| `formal.refuted` | refuted as printed | `refuted` |
| `formal.refuted.open` | refuted as printed; other clauses open | `refuted` |
| `formal.refuted.corrected` | refuted as printed; corrected statement proved | `refuted` |
| `formal.refuted.corrected.open` | refuted as printed; corrected statement proved; other clauses open | `refuted` |
| `scope.expository` | out of scope: expository | `out-of-scope` |
| `scope.literature` | out of scope: literature | `out-of-scope` |
| `scope.empirical` | out of scope: empirical | `out-of-scope` |
| `scope.proof-step` | out of scope: proof-step | `out-of-scope` |
| `scope.part-of` | out of scope: part-of | `out-of-scope` |
| `scope.duplicate` | out of scope: duplicate | `out-of-scope` |
| `link.claim-audit` | linked: claim audit published | `declared` |
| `audit.unavailable` | Audit unavailable | `unspecified` |
| `audit.incompatible` | Audit update required | `unspecified` |

## Independent evidence

A clause's `evidence` is an object keyed by dimension, each containing a `state` and optional
observed `detail`/`errors`. Its required dimensions are `formal`, `review`, `replay` and `source`.
`locked-statement`, `exact-statement`, `axioms`, `witness` and `regimes` expose the existing
mechanical checks. Their complete state vocabularies are in `statuses.json` and the claim schema.

- `formal` reports the assessor's clause state, including proved, refuted, open and stated.
  Definitions use the `stated` state.
- `review` reports correspondence review independently of proof. The original `spec_review`
  and `def_reviews` retain individual stale/current reviews and self-declared provenance.
- `replay` reports passed, not run or unverified. A passed replay also has `guard`: `guarded`
  (under Comparator's sandbox guard), `unguarded` (shown as "replayed without the sandbox
  guard") or `unrecorded` (a record that does not state its conditions). The guard never changes
  the state.
- `source` records hash verification independently of `placement` (exact, approximate,
  manual, ambiguous or unlocated). For PDF-only sources, `pdf_integrity` separately records
  matched, mismatch, unpinned or unknown. PDF identity and location precision have independent values.

Claim records also carry `source_evidence`, including simple and public paper views. Public
paper pages copy a published claim's code, with attribution; they never assign that claim's
verdict to each named declaration or combine evidence from different projects.

## Rebuild and integration

The display schema is `prooflens/manifest@1`. Old display data is rejected with a rebuild
instruction. Old assessments need a new build or reassessment; labels are never reverse-parsed
as a compatibility mechanism. External audit adapters must forward `status_code`. Old or
unknown published audit codes remain unavailable until rebuilt.

Source-region matching and PDF heading extraction supply `source_matches`, locations and PDF pins.
The presentation contract consumes those facts under the existing acceptance policy.

Canonical paper pages import complete published records through `load_published_audit`.
The importer checks the public paper identifier and version, project commit, audit release,
claim chunks, declaration hashes and PDF bytes. It preserves reviews, evidence, source text,
refutations, corrections and additional inventory entries. Failed imports retain a visible state.
The original PDF remains the default; an explicit edition choice displays an audited revision
and its own anchors. Coordinates transfer to the original PDF when their SHA-256 values match.

## Regression coverage

`tests/contracts/test_status_contract.py` exercises contradictory evidence combinations,
copy independence, code coverage, source precision, exports and unknown audit codes.
`web/tests/presentation.test.mjs` covers every label and evidence state, including unknown and
prototype-named inputs. The browser suite generates synthetic engine data and compares
Coverage, Passport, evidence details and public paper views at desktop and phone widths.
