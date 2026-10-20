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
machinechecked inventory regions --paper P
machinechecked inventory regions --paper P --write
machinechecked build --reuse-lean
```

(`python -m prooflens.source_regions --config machinechecked.toml ...` is the same command.)
The first command prints a plan only. A Git source must be pinned to a full commit, an arXiv
source to a versioned identifier. A manuscript read from a folder (`source = { path = ... }`, as
a copy vendored into the Lean project) is the revision recorded as `papers.P.commit` in the
inventory, or the one given with `--rev`; `--source DIR` (or `--source git:REV`, the configured
folder as committed at REV of the repository that holds it) reads another folder instead. The
revision is checked against each claim's recorded paper revision (an abbreviated commit hash of
at least seven digits names that commit), the old one-line hash is verified in that snapshot,
and the new region hash is calculated there. A branch name, a missing original revision or a
failed baseline check is refused, so a folder that does not hold the recorded revision is
refused too. No target-revision rehashing or fuzzy relocation is performed. The operation is
idempotent and the write is atomic; all claims must validate before anything is written. An
inventory edited during planning is not overwritten.

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

## Changing a region's bounds

A review may find that a pin covers less than its claim asserts, or more. Change the bounds at
the revision the claim is pinned at:

```sh
machinechecked inventory rebound --paper P --claim P:intro:rate --lines 40-42
machinechecked inventory rebound --paper P --claim P:intro:rate --lines 40-42 --write
```

`--lines A-B` selects lines A to B (inclusive); `--lines A` the line or display that starts on
line A, as a location alone does. `--file`, `--start-column` and `--end-column` (for one claim)
give another file or column bounds. Repeat `--claim ... --lines ...` to change several claims
in one write. The snapshot is read as for the migration (`--source`, `--rev`), and must be the
revision each claim is pinned at; the claim's present pin (a region, or a legacy line hash)
must match it there. The plan prints, per claim, the old and new bounds with the first and
last line of each. New bounds that start or end on a blank or comment-only line are refused,
and so are bounds that contain a sectioning command (`\part` to `\subsubsection`, or
`\appendix`) after their first line, unless `--across-sections` is given.

`--write` replaces `location`, `source_region`, `source_sha256` and `source_line_sha256`,
computed as above, and atomically. A new passage is new text: the claim's `scope_reviewed`
becomes `false`, and every review marker that recorded the claim's old digest reads it as
changed, so the reviews of the propositions and definitions it states reopen; readings of
other claims stand. Bounds that select the same text change nothing.

## Display excerpts

The reader shows a claim's statement typeset from the paper's source when the **whole** passage
can be typeset faithfully, and the PDF excerpt otherwise. A display excerpt is display only: no
status, finding or review reads it, and its fingerprint (`tex-excerpt-v1:…`) is separate from
`source_sha256`. A passage whose audited source no longer matches its pin is shown from the
PDF.

Which passage is shown:

- a theorem-like environment: its body (the heading is shown by the reader);
- a line-located claim whose audited region is a whole display or an explicit span: that region;
- otherwise, or to choose another passage, an `excerpt` entry in the display overlay:

```json
{"claims": {
  "P:eq:sample": {"excerpt": {"label": "eq:sample"}},
  "P:prop:sample": {"excerpt": {"location": "paper/main.tex:20", "end_line": 22, "end_column": 37}},
  "P:rem:sample": {"excerpt": false}}}
```

A `label` selects the innermost display or theorem-like environment carrying that label; the
label must occur exactly once. A `location` uses the bounds of an audited region
(`end_line`, `start_column`, `end_column`, as above), so prose can stop before the next claim on
the same line; its optional `revision` names the paper revision its lines belong to, and at any
other revision it selects nothing. `false` shows the PDF. A missing, ambiguous or reversed
selector is refused, and the claim is shown from the PDF.

The excerpt is read when the release is built, from the snapshot that was compiled, and stored
with that release's evidence: rebuilding an old release shows its original passage, and a
changed overlay or paper takes effect at the next `machinechecked build`. Each excerpt records
the source revision, file and bounds, the raw passage (newlines and comments kept), and its
rendering context:

- the paper's own `\newcommand`, `\renewcommand`, `\def`, `\gdef` and `\DeclareMathOperator`
  definitions **in effect at the passage**, read in the order TeX reads them, through `\input`,
  `\include` and the snapshot's own packages and class; a later `\renewcommand` replaces an
  earlier definition, and a definition after the passage does not apply to it;
- the printed numbers of `\ref`, `\eqref`, `\cite` (with its optional note) and of numbered
  equations, from the compilation's `.aux` files.

A comment ends with its line, so `% comment` followed by a new line keeps that line. The whole
passage falls back to the PDF when anything in it cannot be reproduced exactly; the reasons are
listed under the claim's audit details. The causes include: a text command or environment the
reader does not typeset; a macro used in the text (other than one that prints nothing); a
definition the passage uses that has an optional argument, delimited parameters, `\let`,
`\edef` or `xparse`, or that is made inside a group or a conditional; a passage that is not
part of the compiled document; a reference or citation that is not resolved, or that prints TeX
(an author–year citation style, `\cref`); a numbered equation row without a label (its number
is not recorded); `multline`, `flalign` and `eqnarray`; a citation of several works when the
paper loads a package that prints citations its own way (`cite`, `natbib`, `biblatex`); a
paper that loads a package giving standard mathematics commands another meaning (`physics`,
`unicode-math`, `mathabx`, `MnSymbol`). In the reader, every piece of
mathematics is typeset by KaTeX in strict mode under those definitions; one error shows the PDF
instead. Packages from the TeX distribution are not read: a command they define that KaTeX does
not know shows the PDF, and a package that changes the meaning of a standard command is not
detected.

`publish.source_text = false` leaves the excerpt out of the export, as it does the statement's
source text.

## Moving to a new revision of the paper

When the manuscript gains a revision, move the inventory to it:

```sh
machinechecked inventory repin --paper P --to NEW
machinechecked inventory repin --paper P --to NEW --write
machinechecked build
```

`NEW` is a Git commit of the paper's repository (a branch or tag is resolved to its commit) or
a versioned arXiv identifier. The configuration must name the original revision as a full Git
commit or a versioned arXiv identifier, and every line-located claim must already be on
`tex-region-v1` (migrate first, above). The first command prints a plan only.

Either snapshot can be given as a folder instead: `--from-source DIR` (with `--from-rev REV`
when the inventory does not record the revision as `papers.P.commit`) and `--to-source DIR`,
`--to` then naming the revision the folder holds. For a manuscript vendored into the Lean
project (`source = { path = "manuscript" }`), `git:REV` names the configured folder as
committed at REV of the project's repository, and the new snapshot is the folder itself by
default:

```sh
# the vendored copy as committed is the pinned revision; the working copy is the new one
machinechecked inventory repin --paper P --from-source git:HEAD --to NEW
```

The configuration of a folder has no revision to change: `--write` records the new one as
`papers.P.commit`. A folder is labelled by the revision it is given, so its claims are verified
against it exactly as an acquired snapshot is.

The command reads both snapshots. It first checks each claim's passage at the original
revision against its digests; a claim that does not match there stops the plan, and an
original revision that cannot be read is an error, not a reason to use another baseline.
It then looks for each passage's exact text in every `.tex` file of the new revision and
classifies the claim:

| Class | Meaning | What `--write` does |
|---|---|---|
| `unchanged` | the passage is found once, at the same place | takes the new revision |
| `moved` | the passage is found once, with the same text, elsewhere | takes the new place and revision; digests unchanged |
| `changed` | its text is not found, and its label leads to one passage with other text | takes the new place; keeps its digests and its revision (`commit`) |
| `removed` | its text is not found, and its label is not in the new revision | keeps its place, digests and revision |
| `not-found` | its text is not found, and it has no label to find a changed version by | keeps its place, digests and revision |
| `ambiguous` | its text or its label occurs more than once, or its text occurs only where the paper may not print it | nothing is written |
| `not-handled` | an environment pin this command cannot place (below) | nothing is written |
| `pending-review` | its pin is of another revision (a passage that changed in an earlier repin) | nothing |
| `unpinned` | it has no source pin | nothing |

The plan lists every claim of the paper. A claim pinned by its environment (a `location` that
names a file without a line, and the hash of the environment's body, as the compiled paper's
anchors give it) is found by its own `\label` in an environment of its `kind`: the same body
hash is `unchanged` (or `moved` to another file), another body is `changed` with a diff, and a
label that is gone is `removed`. A label that occurs twice is `ambiguous`, and so is a missing
label when one environment of the new revision has the claim's text under another label (the
match is shown, not taken). A claim the compiled paper finds only by its printed number, or
whose label is carried by several environments at the original revision, is `not-handled`:
numbers are computed by compiling, which this command does not do, so pin such a claim by hand.

A claim that keeps its revision records it in its own `commit`, so a later repin reports it
as `pending-review` rather than comparing it with text it was not pinned to.

A changed passage is reported with the first line that changed and a diff of the old and new
lines. It keeps the digests it was reviewed at, so the source check at the new revision
reports it (`source-changed`) until it is reviewed again and pinned to its new text by hand.
A label locates a changed passage; it never certifies its text. Two equally good places are
never chosen between, by the nearest line or otherwise: a repeated opening line is not a
match, an identical passage that occurs twice or a label that occurs twice is ambiguous, a
passage whose only copy is in a comment, an `\iffalse` block or a `comment` environment is
ambiguous, and an environment without its end is a change with no new place. A passage
found in another file is moved with a note to check that the paper still reads that file.
The plan also lists labels that are new in the new revision (`new_passages`): passages that
may need an inventory entry.

For an `unchanged` or `moved` passage the plan says whether the lines beside it changed
(`context_changed`). The audited text is the same; an excerpt, a description or a symbol link
that rests on the surrounding text needs checking. The plan counts the symbol links of each
claim that changed or whose surroundings changed; a symbol link keeps the printed text it was
made on and shows as stale in the reader when that text changes.

`--write` refuses while any claim is ambiguous or not handled. It writes atomically and only if neither the
inventory nor the configuration changed during planning. It changes only the selected paper's
claims (`location`, `source_region`, `commit`, and line digests a claim was pinned without),
the paper's `commit` under `papers`, and the paper's source revision in the configuration.
Reviews, clauses, dismissals, Lean and other papers are not touched; free text such as notes
or URLs naming the old revision is left to edit by hand. Rerunning the same command writes
nothing more. Evidence and releases built before the repin keep the snapshot they were
built from.

The display excerpts of the paper's claims ([above](#display-excerpts)) are handled
separately, under `excerpts` in the plan; the audited pins above do not depend on them. A
selector by `label` is read again at the next build (`follows-label`, or `label-not-unique`
when the label is missing or repeated in the new revision, and the claim is then shown from the
PDF). A selector by `location` is `moved` (or `unchanged`) when its text occurs exactly once,
where the paper prints it, in the new revision; `--write` gives it the new place, with
`context_changed` saying whether the lines beside it changed. Any other is `invalidated`:
`--write` adds the original revision to it, so it selects nothing at the new revision until it
is chosen again (`stale` in a later plan). The display overlay is written atomically with the
inventory, and only for the selected paper's claims.
