# ProofLens

Read a mathematical paper beside its Lean formalisation, and see for every claim what has been
established about it.

A Lean build says that the Lean theorems are proved. It does not say they are the paper's
theorems. ProofLens opens the paper, marks every numbered statement, and shows beside each one
the Lean declaration that formalises it, whether Lean proves it, and whether anyone has checked
that the two say the same thing. It never rounds a status up.

There are two ways to use it:

- **Zero configuration** (most projects): point it at a Lean project with a paper. Nothing to
  write except, as you confirm them, the links between claims and declarations.
- **Full assessment** (a project with a `prooflens.toml`): locked statements, a claim inventory,
  recorded reviews and an acceptance status per claim, reproducible and checkable in CI.

## Quick start

You need Python ≥ 3.11, the project's Lean toolchain ([elan](https://github.com/leanprover/elan)),
and, for a LaTeX paper, TeX Live with `latexmk` (and `xelatex` or `lualatex` if the paper needs
them). You do not need Node.

1. Build the Lean project as usual: `lake build`. ProofLens reads the built modules and never
   builds behind your back.
2. From anywhere inside the project:

   ```sh
   uvx --from git+https://github.com/cgarryZA/ProofLens prooflens view
   ```

   (or `pip install git+https://github.com/cgarryZA/ProofLens`, then `prooflens view`). It finds
   the paper (a `.tex` with `\documentclass`, else a PDF; if there are several it asks, or pass
   the path: `prooflens view paper/main.tex`), compiles it, and opens the reader in your browser.
3. In the reader, the contents list the numbered statements; click one, or its marker in the
   margin. The panel shows the statement as printed and, under **In Lean**:
   - links: a `\lean{Name}` tag in the paper's source is a link (a commented-out tag is not);
   - suggestions: a docstring citing the claim's number ("Theorem 3"), or a name resembling its
     label or title. **Link** confirms one, **Not this** rejects it, and the search box links any
     other declaration of the project.

   Links are saved to `prooflens.links.json` at the project root, and the page rebuilds.

Each claim then reads one of: *not linked*, *suggested link, not confirmed*, *linked: Lean proof
checked*, *linked: Lean proof incomplete (sorry)*, *linked: Lean proof uses further axioms*,
*linked: Lean definition*, *linked: Lean declaration not found*. A link says which declaration
formalises the claim and what Lean says about it. Whether the declaration says what the paper
says is a separate question, for a review (below).

### Share it

```sh
prooflens build          # writes ProofLens.html at the project root
```

One file with the paper, the data and the reader inside: it opens from disk with a double click,
needs no server, and can be committed to a private repository or sent by email.

### Check it in CI

```sh
prooflens check          # exits 1 if a linked declaration is missing or not proved
```

### What to commit

Commit `prooflens.links.json`. Ignore the working directory:

```gitignore
.prooflens/
```

and `ProofLens.html` too, unless you commit it on purpose to share it.

### Blueprints

A [leanblueprint](https://github.com/PatrickMassot/leanblueprint) works as it is: run
`prooflens view` in the project, and `blueprint/src/print.tex` is the paper (its `web.tex` is not
offered). Its `\lean{…}` tags become links, and an engine the blueprint's `latexmkrc` names
(usually XeLaTeX) is used; the `latexmkrc` is read as text, never run.

## Reviewing

The reader's **Review** page takes a reviewer through the queue one unit at a time: a locked
proposition, a definition its meaning depends on, or (in the zero-configuration view) a linked
claim. Each unit is reviewed once per fingerprint, in the order of a blind review:

1. **Read.** The printed claim only. The reviewer writes down what it says; the text is locked
   when the Lean is revealed.
2. **Compare.** The Lean statement and its definitions. The reviewer compares item by item and
   records a verdict: *matches* / *there's a problem* / *cannot determine*, then the precise one
   (faithful; with representation choices; broader; narrower; mismatched; vacuous; refutation
   not valid; cannot determine), with the detail it needs.
3. **Author's review.** Shown only now. Disagreements are recorded without changing the verdict.

Choose a paper and a section first to stay in one mathematical setting. Reports stay in the
browser (undo, skip, resume) and are exported with **Export reports** as a file, so a reviewer
needs nothing installed: the shared `ProofLens.html` works. Export often: a browser's storage is
not a safe place for an hour of work. The reviewer's identity is recorded as they state it.

A report marks nothing reviewed. In a full assessment the maintainer promotes it:

```sh
prooflens review promote prooflens-reviews-….json
```

Promotion refuses a report whose declaration, legacy hash or manuscript changed since the review,
whose steps are out of order, whose verdict is not faithful / with representation choices
(listed) / broader (with the instantiation), whose reviewer is an author of the statements, or
whose reviewer is a model of the author's family or of unknown family (unless
`--accept-same-family`). For the rest it shows what it will write, asks, archives the report next
to the review files, writes `<!-- spec-review: NAME HASH by=REVIEWER -->` (or `def-review`) after
the declaration's last marker, assesses again, and runs `[review] check` if the configuration
sets one.

## Full assessment

A project with a `prooflens.toml` in the directory you run from (or passed with `-c`) gets the
full assessment. It needs no Lean dependency on ProofLens: the probe runs with the project's own
toolchain through `lake env lean`. The [toy paper](examples/toy-paper) is a complete example.

```toml
[project]
name = "my-paper"
lean_root = "."
modules = ["MyPaper"]                    # modules to import (the propositions and their proofs)
scope_roots = ["MyPaper"]                # whose definitions are the project's own
spec_prefix = "MyPaper.PaperSpec"        # closed propositions written from the paper
accept_prefix = "MyPaper.Acceptance"     # theorems whose type is exactly one of them
inventory = "claims.json"
reviews = ["reviews/statements.md", "reviews/definitions.md"]   # files, or directories of .md
statement_authors = ["me"]               # their reviews are never independent
ai_reviewers = ["claude*"]               # reviewers recorded as AI unless a marker says otherwise
dismissals = "reviews/dismissals.json"   # optional
comparator_log = "replay.json"           # optional: a kernel replay record
display = "display.json"                 # optional: what the site shows in place of the inventory's text

[review]
check = "python3 tools/check.py"         # optional: run after `review promote`

[[paper]]
id = "A"
title = "My paper"
source = { git = "me/paper-repo", rev = "<commit>", token_env = "PAPER_TOKEN" }  # or { path = "paper" }
root = "paper/main.tex"                  # needed when several files have \documentclass
publish = { pdf = false, source_text = false, lean = false, reviews = false }  # the default
```

LaTeX is used when a root is found; otherwise the source's PDF, and its claims are marked
PDF-only.

**The inventory** (`claims.json`) lists every claim of the paper with a stable id, where it is,
the hash of its source, and its scope. A formal claim has clauses, each naming its locked
proposition, and its proof or refutation:

```json
{ "id": "A:thm:main", "paper": "A", "kind": "theorem", "number": "Theorem 2.1", "title": "",
  "label": "thm:main", "location": "main.tex", "source_sha256": "…",
  "scope": "formal", "scope_note": "", "scope_reviewed": true,
  "clauses": [
    { "name": "as printed", "spec": "MyPaper.PaperSpec.thm_main",
      "accept": "MyPaper.Acceptance.thm_main",
      "witness": "MyPaper.Acceptance.thm_main_hypotheses" } ] }
```

A clause may instead have `refute` (a theorem proving the printed statement false) and a further
clause with `corrects` naming the clause it corrects. Scopes other than `formal` and `definition`
(`part-of`, `duplicate`, `proof-step`, `expository`, `literature`, `empirical`) record why a claim
needs no proof, and `scope_reviewed: false` marks a decision not yet checked by reading.

**Reviews** are Markdown files: the review's text, then a marker with the hash it was made at.

```markdown
## Theorem 2.1: `MyPaper.PaperSpec.thm_main`

The reviewer's reading, the comparison and the verdict.

<!-- spec-review: MyPaper.PaperSpec.thm_main <hash> by=a.referee kind=human -->
```

The last marker of a declaration is its current review; a changed declaration makes it stale.
A claim is *accepted* when every clause's proposition is proved over the allowed axioms, and the
proposition and every project definition its meaning depends on are reviewed at their current
hash by someone other than the authors of the statements.

**A kernel replay record** (`comparator_log`) is JSON:
`{"commit": "<full sha>", "replayed": ["<theorem>", …]}`. Without one, replay reads *not run*;
a record of another commit, or a text log, reads *unverified*.

**The display overlay** (`display`) changes what the site shows and nothing that is assessed:
`{"claims": {"<id>": {"title_tex": "…", "number": "…", "number_note": "…"}}, "clauses":
{"<clause name>": {"title_tex": "…"}}}`. Use it when the inventory's descriptions are plain text
(`$\mathcal D_\pi$` reads better than `Dpi`) or a recorded number is wrong.

The commands:

```sh
prooflens build [--reuse-lean]   # probe Lean (or reuse it if no Lean input changed), compile, assess
prooflens view                   # serve the site at http://127.0.0.1:8017
prooflens check                  # build, exit 1 on a violation
prooflens reassess               # assess stored evidence again (new reviews, rules), no Lean or LaTeX
prooflens site                   # rewrite the site from stored evidence
prooflens bundle --out F.html    # the site as one file
prooflens export --out DIR       # the public export: approved fields only, scanned for leaks
prooflens review promote F.json  # record review reports (above)
```

## Private projects

A private project keeps its configuration, inventory, reviews and site in its own repository.
`prooflens bundle` writes the site as one HTML file carrying its data and PDFs, to commit there
and open with a double click; nothing is hosted. Nothing of a private project belongs in this
repository: `scripts/check_public.py` refuses a push containing any term of a private denylist or
any line of the project's Lean or LaTeX sources.

## Troubleshooting

- **"the Lean project is not built"**: run `lake build`; modules not built are listed as such.
- **"`lake` not found"**: install elan and put `~/.elan/bin` on `PATH`.
- **The paper does not compile**: the reader still opens, from the paper's PDF if there is one;
  the message names the LaTeX error. A paper that needs XeLaTeX should say so with
  `% !TEX program = xelatex`, a `latexmkrc`, or by loading `fontspec`/`unicode-math`.
- **A marker is in the wrong place**: markers are exact for numbered environments, and
  approximate (dashed) for claims recorded by line; claims on several pages are left unplaced
  rather than guessed.

## Developing

```sh
pip install -e '.[test]'
pytest                                  # contracts, seeded mutations, security, zero-configuration
(cd web && npm ci && npm run build)     # rebuilds the reader into engine/python/prooflens/web
```

The built reader is committed, so that installing ProofLens needs no Node; CI checks that it is
the build of the committed sources. See [`CLAUDE.md`](CLAUDE.md) for the conventions and
[`PLAN.md`](PLAN.md) for the plan of record.

## Documentation

- [Plan of record](PLAN.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evidence policy](docs/EVIDENCE_POLICY.md)
- [Data model](docs/DATA_MODEL.md)
- [Publication policy](docs/PUBLICATION_POLICY.md)

## License

Apache-2.0
