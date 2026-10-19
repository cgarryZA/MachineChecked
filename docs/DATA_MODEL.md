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
| `lean` | the probe records: specifications (binders, conclusion, closure, constants, hashes), proofs (exact-type check, axioms), declarations (signature, value, doc, hashes), layering |
| `tex` | per paper: mode, page size, anchors (env, number, labels, file:line, begin/head/end positions, source hash), files read |
| `assessment` | per claim: status and clauses; all findings |

A pretty-printed Lean term (a binder's type, a conclusion, a signature) is `{text, segments}`:
each segment is a piece of the text, with `ref` when it names a constant and `var` when it is an
occurrence of one of the statement's own variables (the index, in `binders`, of the binder that
introduced it). A conclusion that is a conjunction, disjunction or equivalence also has
`logic`, a tree of `{op, args}` whose leaves are `{leaf: {text, segments}}`. A term also lists its sub-terms as `terms`, ranges `{from, to}` of its segments (outer before inner; none for a very large term), so that a reader can select a whole sub-term. Both are for
display: no status, fingerprint or hash reads them.

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
example `arxiv:2601.01234` and `v2`, with `version` null when the audit pins an unpublished
manuscript; `url`; `revision`; `paper_version`, below), `formalisation` (`repository` as
`owner/repo` when the project's remote is on GitHub, `commit`, `toolchain`), `release`, `data` (the
path of the manifest index, inside the directory), `issues` and `site_url`. It records what its
author states; it is not evidence of anything by itself. A reader loading an audit from another
address takes every string in it and in its data as text, reads only files inside the audit's
directory, and never offers to edit it.

`paper_version` is the one version of the paper the audit pins (`versions.py`), or null when none
is known:

| Field | Published version | Unpublished manuscript |
|---|---|---|
| `kind` | `published` | `manuscript` |
| `id` | `arxiv:2601.01234v1` (or `doi:…`, or the URL) | `manuscript:<first 7 hex of the commit>` |
| `revision` | the commit of the source read, if known | the manuscript's commit |
| `label` | `arXiv v1` | `Latest manuscript (commit abc1234)` |

An arXiv version also has `arxiv` (`arxiv:2601.01234`) and `number` (`v1`). A manuscript is never
given a version number. `build` refuses an audit whose inventory pins (`papers.<id>.commit`, a
claim's `commit`) name another version: a published version is pinned by its identifier
(`2601.01234v1`), a manuscript by its commit. A site loading an audit (`load_published_audit`)
rebuilds the label from `kind` and `id`, checks that the descriptor and the data name the same
version, and, given a listing's `version`, refuses an audit that pins another one.

## Identifiers

- Claim: `<paper>:<label>`, else `<paper>:<env>-<number>`.
- Release: `r-<first 12 hex of the evidence id>` unless named.
- Permalink: `#/r/<release>/claim/<claim id>` or `#/r/<release>/read/<paper>/<claim id>`.
