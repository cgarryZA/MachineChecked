# Data model

Three documents, each with a JSON Schema in `engine/python/prooflens/data/schema/`.

## Inventory (`inventory.schema.json`), written by people

The frozen list of claims, with the optional `label` of a claim and the `regimes` of a clause.

```json
{"claims": [{
  "id": "T:thm:even-add", "paper": "T", "kind": "theorem", "number": "Theorem 2.1",
  "title": "Closure under addition", "label": "thm:even-add", "location": "toy.tex",
  "source_sha256": "<sha256 of the whitespace-normalised environment body>",
  "scope": "formal", "scope_note": "", "scope_reviewed": true,
  "clauses": [{"name": "statement",
               "spec": "Toy.PaperSpec.thm_even_add",
               "accept": "Toy.Acceptance.thm_even_add",
               "witness": "Toy.Acceptance.thm_even_add_hypotheses",
               "regimes": [{"name": "nonzero summands", "description": "…",
                            "witness": "Toy.Acceptance.thm_even_add_hypotheses"}]}]}]}
```

A clause has `accept` or `refute`, not both. A corrected statement names the clause it
`corrects` (by clause name). A definition claim's clause has `defs` and no `spec`.

A claim's `location` is a file for a numbered environment, whose `source_sha256` is the hash of
the whitespace-normalised body of the environment, or `<file>:<line>` for a claim recorded by
line (an equation, a part of an environment, a prose claim), whose hash is the hash of that line.

## Reviews, written by people

Markdown files with markers:

```
<!-- spec-review: <proposition> <hash> by=<reviewer> [kind=human|ai] -->
<!-- def-review: <definition> <hash> by=<reviewer> [kind=human|ai] -->
```

`<hash>` is the `legacy_hash` or the `pl-fp-v1:` fingerprint the review was made at. The section
the marker closes is the text of the review. The last marker of a declaration, reading the files
in order (a directory's `.md` files by name), is its current record.

Dismissals of warnings (`dismissals.json`):
`[{"code", "subject", "trigger", "fingerprint", "rationale", "by"}]`.

## Evidence (`evidence.schema.json`), written by the engine

`.machinechecked/evidence/<id>.json` (`.prooflens/` in older projects), with `id` the SHA-256 of the canonical JSON of `body`:

| Field of `body` | Content |
|---|---|
| `provenance` | tool, Lean, project and dependency revisions, each paper's source and PDF hashes |
| `inventory` | the inventory as read |
| `reviews` | the review files' hashes and every parsed marker |
| `dismissals` | as read |
| `lean` | the probe records: specifications (binders, conclusion, closure, constants, hashes), proofs (exact-type check, axioms), declarations (signature, value, definition content, authored source, doc, hashes), layering |
| `tex` | per paper: mode, page size, anchors (env, number, labels, file:line, begin/head/end positions, source hash), files read |
| `assessment` | per claim: status and clauses; all findings |

A pretty-printed Lean term (a binder's type, a conclusion, a signature) is `{text, segments}`:
each segment is a piece of the text, with `ref` when it names a constant and `var` when it is an
occurrence of one of the statement's own variables (the index, in `binders`, of the binder that
introduced it). A conclusion that is a conjunction, disjunction or equivalence also has
`logic`, a tree of `{op, args}` whose leaves are `{leaf: {text, segments}}`. A term also lists its sub-terms as `terms`, ranges `{from, to}` of its segments (outer before inner; none for a very large term), so that a reader can select a whole sub-term. Both are for
display: no status, fingerprint or hash reads them.

A declaration record of a definition of data or of a predicate (not a proposition, an instance or
a generated helper) also says what the definition says. `defined_by` is `body` or `equations`.
With `body`: `params` (the leading `fun` binders of its value, each `{name, binder, id, type,
proposition}`), `body` (the term under them, with the sub-term identities it has in `value`) and
`result` (its type, identities prefixed `type:`). `equations` lists the equation theorems Lean
derives (`Lean.Meta.getEqnsFor?`), each `{name, statement, params, equation}`: the theorem's exact
statement, and its variables and the equation under them; their identities are prefixed by the
theorem's name. At most 64 are listed; `equations_omitted` counts the rest and `equation_names`
names all of them. A failed extraction is recorded in `definition_error` and stops nothing else.
`lean_source` is the declaration's authored source, `{file, line, end_line, text, sha256}`, read
from the checkout the probe ran on (none for a declaration of a dependency). The export carries
these fields only when every paper publishes its Lean.

## Manifest (`manifest-index.schema.json`, `manifest-claim.schema.json`), derived

The current format is `prooflens/manifest@1`; older display data must be rebuilt.
See [the structured status contract](STATUS_CONTRACT.md) for the complete code inventory.

`data/index.json` lists the papers, every claim's `status_code`, derived status/class and anchor, the summary and the
findings counts. `data/claims/<file>.json` holds one passport: the printed statement, each
clause's unfolded statement, proofs, witness, regimes, reviews and structured `evidence`, the
declarations of its closure, and its findings. A claim is loaded only when it is opened.
In zero configuration a passport also has `correspondence` (or `null`): the mapper's note on how
far the linked declarations state the claim, `{source, coverage, confidence, note, by}`, where
`source` is `confirmed` (the auditor's, from `machinechecked.links.json`) or `formalization.yaml`
(the project's row notes). It is displayed beside the links and is never an input to a status.

A paper page (`prooflens.paper.write_paper_site`, used by machinechecked.org) is written in the
same format, with `mode: "paper"`: the paper's registry entry (`paper`), the Lean projects that
state they formalise it (`projects`, as `owner/repo`), and the statements found in its PDF, each
with its links (each naming its `repository`) and, per project, the status that project's links
give it (`by_project`). Without an audit nothing has run Lean, so a linked statement reads
"linked: Lean not checked here (no audit published)" (class `declared`). The reader shows one
project at a time and never combines them. No statement text is written.

## Audit descriptor (`audit.json`), written by the engine

At the root of every published reader (`machinechecked build --site`, `machinechecked export`):
`schema` (`machinechecked/audit@1`), `created`, `author` (the name the audit is published under,
as its author gives it), `papers` (title; `id` and `version` when the paper is an arXiv paper, for
example `arxiv:2601.01234` and `v2`; `url`; `revision`), `formalisation` (`repository` as
`owner/repo` when the project's remote is on GitHub, `commit`, `toolchain`), `release`, `data` (the
path of the manifest index, inside the directory), `issues` and `site_url`. It records what its
author states; it is not evidence of anything by itself. A reader loading an audit from another
address takes every string in it and in its data as text, reads only files inside the audit's
directory, and never offers to edit it.

## Identifiers

- Claim: `<paper>:<label>`, else `<paper>:<env>-<number>`.
- Release: `r-<first 12 hex of the evidence id>` unless named.
- Permalink: `#/r/<release>/claim/<claim id>` or `#/r/<release>/read/<paper>/<claim id>`.
