# Linking symbols in the paper to Lean objects (design)

Status: accepted and built (issues #48, #60). Links are made with `machinechecked symbol add`, or
by selection in the local reader.

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

A file beside the configuration, `symbols.json` by default (`symbols = "…"` in the `[project]`
table of `machinechecked.toml` names another):

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
  names occurrences by number. Two different ν (in two claims, or two scopes of one claim) are two
  links and are never merged. Occurrences are numbered from 1 in reading order, in the pieces of
  mathematics of the passage the link is made on (as the reader typesets them); a link that names
  some (`occurrence: [1, 2]`, with `of`, how many there were) says they are one object of the
  paper, which it names (`object`, the author's words: "n, the number defined"). Another object
  printed with the same symbol (the index of `T_n`) is linked apart, naming its own occurrences;
  two objects never share an occurrence, and a link of every occurrence leaves no room for
  another. A shared glyph alone never shares a link.
- **The Lean side** is a variable (`var`, the variable's number the probe exports), a
  binder's type (`binder`, `path: "type"`), or any expression (`at`), of one of the claim's
  propositions or, for a claim that only defines, of one of its definitions (its parameters are
  its variables; its body and equations its expressions). An expression is named by
  its identity: its position in the whole proposition (Lean's `SubExpr.Pos`, written like
  `/1/0/1`), which the probe records for every selectable sub-term (`terms[].id`) and for every
  occurrence of a variable (`segments[].at`), so one occurrence is named apart from the variable,
  whose number all its occurrences share. It depends only on the proposition, so no change in how
  the statement is printed or split for display moves it, and the same expression has the same
  identity in the readable statement and in the exact Lean, which is how a selection in one is
  shown in the other. A property an object's type carries has the identities of its statement
  at that object, prefixed by the object's identity and the field (`/1#start:/0`), so the same
  field of two objects is two targets; an equation of a definition has its own, prefixed by the
  equation theorem's name (`Foo.f.eq_2:/1`); an expression inside a definition expanded at the
  arguments of one of its applications extends the application's identity (`/1/0=/1`, and
  `/1/0=/1=/0` inside an expansion nested in it), and is found in the expansion the site stores
  on its own, as is an equation on a later page of a definition's equations. The scheme is versioned (`IDS` in `symbols.py`,
  now `subexpr-pos@1`).
- **Pins**: the statement's fingerprint (it already covers the definitions the statement uses),
  the hash of the claim's TeX source, the text of the Lean object as it was shown (`target`), the
  scheme of identities (`ids`) and, for a variable or a binder's type, the identity of its binder
  (`binder_id`). When any differs, the link is stale. The text matters because a variable's
  number depends on how the statement is split: a change in the display can renumber it while
  the statement stays the same, and the link must then go stale rather than point at another
  object; the binder's identity tells apart two variables of the same name. A link to an
  expression made without the text pin is stale, and so is a link recorded by place and number
  in an earlier display (`term` and `in`), which names nothing now.
  A link made while the reader typesets the claim's passage from its source
  ([display excerpts](SOURCE_REGIONS.md#display-excerpts)) is made on that passage: `source`
  is the hash of its text and `excerpt` its fingerprint, which covers the macros and reference
  numbers it is typeset with. Such a link is stale when the excerpt's fingerprint changes or the
  passage is shown from the PDF.
- A variable bound inside the conclusion or inside a hypothesis (a "there is", a "for every") is
  a variable too: the probe numbers it after the binders that open the statement, each its own
  number (the statement's tree, [DATA_MODEL.md](DATA_MODEL.md)), so `--var` and `--type-of`
  accept it by number, or by name (the first variable of that name).

## Display

- Only in mathematics the reader renders itself: the claim's passage typeset from its source
  (KaTeX) in the panel, never the PDF. KaTeX output can carry an id per symbol; a PDF has glyphs, and positioned targets would
  need per-symbol anchors from the LaTeX (a macro in `prooflens.sty`), which is a later and
  separate decision, if ever.
- The same selection model as the Lean view: hovering a linked symbol highlights it and the Lean
  it is linked to, and the reverse; a click holds it, with "linked by NAME" beside it.
- A stale link is not drawn. The build records why (`stale_because`: `statement`, `source`,
  `excerpt`, `missing`, `target`, `unpinned`, `positional`, `ids`), and the local reader lists
  it with the reason and asks to link it again or remove it.
- Choosing another claim, project or release clears the selected expression and the link being
  made: a selection names an expression of one claim's statements in one build.
- Changing the selected Lean project shows that project's links only; the paper keeps its place.

## Who makes links

The author or a reviewer, under their name, from the command line:

```sh
machinechecked symbol add P:thm:sep '\nu' Foo.spec_sep --var ν --as human:Ada-Lovelace
machinechecked symbol add P:def:even n Foo.IsEven --var n --occurrence 1 --occurrence 2 \
  --object 'n, the number defined' --as human:Ada-Lovelace     # two occurrences, one object
machinechecked symbol add P:thm:sep '\mathbb R^j' Foo.spec_sep --type-of f --as human:Ada-Lovelace
machinechecked symbol add P:thm:sep 'f' Foo.spec_sep --term c#2 --as human:Ada-Lovelace   # a sub-term, by place
machinechecked symbol add P:thm:sep 'f' Foo.spec_sep --at /1/1/0 --as human:Ada-Lovelace  # by identity
machinechecked symbol list
machinechecked symbol remove P:thm:sep '\nu'
machinechecked symbol remove P:def:even n --object 'n, the number defined'   # that object's only
```

`add` checks the link against the last build (the symbol occurs in the claim's mathematics, the
statement is the claim's, the binder exists) and pins it to that build; rebuild the site to show
it. `--term WHERE#K` is read in the last build and recorded by the sub-term's identity; `--var`
and `--type-of` take a variable's number, or a name (the first variable of that name).

In the local reader of a full assessment (`machinechecked view`), the paper section of a claim
offers **Link a symbol to the Lean**: choose one of the symbols found in the claim's mathematics,
click its variable in the Lean statement (or tick that the symbol is the variable's type, or click inside an expression to select a sub-term), give
your name, and save. A symbol printed several times can be linked at the occurrences you tick,
named as the object of the paper they are. A claim that only defines is linked into its
definitions the same way. The link goes through the same checks as `symbol add`, is written to the same
file, and the site is rewritten with it; existing links can be removed there. A published audit shows the
links its author recorded (when it publishes both the source text and the Lean) and never edits
them.

## Not in scope

- Inferring links automatically (by matching names or glyphs): a guess shown as a link would read
  as an assertion nobody made.
- Any effect on statuses, reviews or the review queue.
