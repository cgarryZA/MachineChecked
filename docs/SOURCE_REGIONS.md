# Pinning manuscript source regions

A `file:line` location identifies where a claim starts. It is not, by itself, the whole claim.
Line-located claims use `source_hash_scheme: "tex-region-v1"`, a `source_sha256` of their
selected original source text, and `source_line_sha256`, one digest per source line the passage spans (each whole
line, raw). The
whole-passage digest decides whether the passage matches; the line digests say where it
changed. A `source-changed` finding names the first changed line, by its place in the passage
and in the file, or says that lines were added or removed at its end. The evidence stores the
resolved bounds and digests per **claim**, so two passages that start on the same line do not
overwrite one another.

When the selected line opens `equation`, `align`, `gather`, `multline`, `eqnarray`, `flalign` or
`alignat` (including starred forms), the region runs from that opening command through its
matching close. Comments, escaped backslashes and inline `\verb` text do not close it. Nested
literal environments must balance. A missing or mismatched close is an error, not permission
to fingerprint the rest of the file.

For prose or a display with accompanying prose, specify its end:

```json
{
  "id": "P:eq:sample",
  "paper": "P",
  "location": "paper/main.tex:20",
  "source_region": {"end_line": 28, "end_column": 37},
  "source_hash_scheme": "tex-region-v1",
  "source_sha256": "<64-character SHA-256>",
  "source_line_sha256": ["<SHA-256 of line 1>", "…"]
}
```

Lines and columns are 1-based. `end_line` is inclusive; `end_column` is exclusive. Omit
`end_column` to include the whole last line. `start_column` defaults to 1. This allows a
passage to stop before the next claim even when both share a source line. Without an explicit
region or a recognised display opener, the selected nonblank line remains a single-line
claim: surrounding prose is **not** inferred to be covered. Choosing the right scope remains
a review responsibility.

The fingerprint preserves whitespace and comments in the selected text (line endings are
normalised when read as text). In particular, newlines are not collapsed before hashing:
a newline may end a TeX comment. Formatting changes can therefore require a new source pin.
The scanner does not execute TeX or prove that a passage captures every external macro or
assumption on which its meaning depends.

## Replacing a legacy opening-line hash

Do this while the configuration still names the **original frozen paper revision**:

```sh
python -m prooflens.source_regions --config machinechecked.toml --paper P
python -m prooflens.source_regions --config machinechecked.toml --paper P --write
machinechecked build --reuse-lean
```

The first command prints a plan only. It requires a full pinned Git commit or a versioned arXiv
source, checks it against each claim's recorded paper revision (an abbreviated commit hash of
at least seven digits names that commit), verifies the old one-line hash
in that snapshot, and calculates the new region hash there. A working folder, branch name,
missing original revision or failed baseline check is refused. No target-revision rehashing or
fuzzy relocation is performed. The operation is idempotent and the write is atomic; all
claims must validate before anything is written. An inventory edited during planning is
not overwritten.

Only `source_sha256`, `source_hash_scheme` and `source_line_sha256` change. A claim already on
`tex-region-v1` whose passage still matches gains its line digests. Paper revisions, Lean fingerprints,
review markers and historical evidence are not rewritten. The command does not grant a new
review or silently accept an enlarged mathematical scope. A genuinely changed statement
needs a new source review, not a migration against the changed version.

Existing generated line-only evidence must be rebuilt. Until then, a `source-hash-scheme` or
`source-changed` violation blocks consistency and release. The reader's source match uses
the same comparison as the assessor, even when the PDF excerpt was placed by hand. A failed
paper-source check does not change which proposition Lean proved; it prevents the new paper
passage being presented as the unchanged reviewed source.

This audited source pin is separate from any display excerpt or its rendering-context
fingerprint. Editing a display overlay cannot refresh an audited source check.
