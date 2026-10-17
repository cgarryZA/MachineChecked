# Linking symbols in the paper to Lean objects (design)

Status: proposed, for the owner to accept before any of it is built (issue #48).

The reader already links a claim to Lean declarations, and inside the Lean it highlights a
variable wherever it occurs (`var` in the probe's segments). This note covers the step between:
a reader selects a symbol in the paper, say ν or ℝʲ, and sees the Lean object or expression it
corresponds to, and the reverse.

## What a link is

Saying that the paper's ν is a given Lean variable is what a statement review checks. So a
symbol link is an **assertion by a named person**, recorded like a review and treated like one:

- it records who made it (`by`, self-declared, as review markers do);
- it is shown as theirs ("linked by …"), never as a property of the paper or of Lean;
- it changes no status, and no status reads it (EVIDENCE_POLICY: evidence, not opinion,
  changes a status; a link is not a review);
- it goes stale, and is then shown as stale or not at all, when what it relates changes.

## Data

A file beside the inventory, `symbols.json` (one per project), listed in `machinechecked.toml`:

```json
{"schema": "machinechecked/symbols@1",
 "links": [{
   "claim": "P:thm:sep",
   "symbol": {"tex": "\\nu", "occurrence": "all"},
   "lean": {"decl": "Foo.spec_sep", "var": 1},
   "by": "human:Ada-Lovelace",
   "pins": {"statement": "<fingerprint of Foo.spec_sep>", "source": "<sha256 of the claim's TeX>"}
 }, {
   "claim": "P:thm:sep",
   "symbol": {"tex": "\\mathbb R^j"},
   "lean": {"decl": "Foo.spec_sep", "binder": 4, "path": "type"},
   "by": "human:Ada-Lovelace",
   "pins": {"statement": "…", "source": "…"}
 }]}
```

- **One link per object within its scope**: a symbol is matched by its TeX within one claim's
  statement, and every occurrence there takes the link (`occurrence: "all"`), unless the link
  names occurrences by index. Two different ν (in two claims, or two scopes of one claim) are two
  links and are never merged.
- **The Lean side** is a variable (`var`, the binder index the probe already exports) or a whole
  sub-term: a binder's type (`binder`, `path: "type"`), or the conclusion. Selecting an arbitrary
  sub-term needs sub-expression identities from the probe, which do not exist yet (#46).
- **Pins**: the statement's fingerprint (it already covers the definitions the statement uses)
  and the hash of the claim's TeX source. When either differs, the link is stale.

## Display

- Only in mathematics the reader renders itself: the claim's TeX (KaTeX) in the panel, never the
  PDF. KaTeX output can carry an id per symbol; a PDF has glyphs, and positioned targets would
  need per-symbol anchors from the LaTeX (a macro in `prooflens.sty`), which is a later and
  separate decision, if ever.
- The same selection model as the Lean view: hovering a linked symbol highlights it and the Lean
  it is linked to, and the reverse; a click holds it, with "linked by NAME" beside it.
- A stale link is not drawn; the audit details list it as stale.
- Changing the selected Lean project shows that project's links only; the paper keeps its place.

## Who makes links

The local reader (`machinechecked view`), as it makes claim links: the author or a reviewer
selects a symbol and a Lean variable or sub-term, and the link is saved to `symbols.json` with
their name. A published audit shows the links its author recorded and never edits them.

## Not in scope

- Inferring links automatically (by matching names or glyphs): a guess shown as a link would read
  as an assertion nobody made.
- Any effect on statuses, reviews or the review queue.
