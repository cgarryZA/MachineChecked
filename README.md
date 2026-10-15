# ProofLens

Read a mathematical paper beside its Lean formalisation, and see for every claim exactly what has
been established about it.

A Lean build says that the Lean theorems are proved. It does not say they are the paper's
theorems. ProofLens keeps three questions apart and answers each from evidence:

1. **Is the formal statement proved?** The acceptance theorem's type is exactly a locked,
   closed proposition, and its axioms are allowed. This is checked by the Lean kernel.
2. **Does the formal statement say what the paper says?** This needs a reviewer. ProofLens records
   who reviewed which proposition and definition, at which fingerprint, as which kind of reviewer.
   Any change reopens the review.
3. **Is every claim of the paper accounted for?** The compiled paper's numbered environments are
   compared with the claim inventory, and each claim's source is hashed.

The reader shows the paper with a status band over each claim. Selecting a claim opens its
passport:
- the claim as printed, cropped from the PDF;
- the locked statement, unfolded into its quantifiers, hypotheses and conclusion;
- the proof check, the witness and the regimes;
- the reviews and their provenance;
- the evidence ladder;
- the findings.

The status words are exactly those the engine computed. The site never rounds them up.

## Status

Phases 0 and 1 of [`PLAN.md`](PLAN.md) are done, and Phase 2 (the reader on real papers) is under
way. The engine reproduces an existing acceptance system's statuses claim for claim on a real
formalisation. The [toy paper](examples/toy-paper) is the public example and the test fixture.

## Try it

Requirements: Python ≥ 3.11, Node ≥ 20, [elan](https://github.com/leanprover/elan), and TeX Live
with `latexmk`. `scripts/cloud-setup.sh` installs all of them on Ubuntu.

```sh
pip install -e '.[test]'
(cd web && npm ci && npm run build)
cd examples/toy-paper
prooflens build              # probe the Lean project, compile the paper, assess, write the preview
prooflens serve              # http://127.0.0.1:8017
prooflens export --out site  # the public export: approved fields only, scanned for leaks
prooflens bundle --out ProofLens.html  # the whole site in one file that opens from disk
```

`prooflens site` rewrites the preview from stored evidence, and `prooflens reassess` assesses
stored evidence again (new rules, new reviews) without re-running Lean or LaTeX.

## Private projects

A private project keeps its configuration, inventory, reviews and site in its own repository.
`prooflens bundle` writes the site as one HTML file carrying its data and PDFs, so it can be
committed there and opened by double-clicking, with no server and nothing hosted. Nothing of a
private project belongs in this repository: `scripts/check_public.py` refuses a push containing
any term of a private denylist or any line of the project's Lean or LaTeX sources.

`pytest` runs the contract, seeded-mutation and security tests.

## Using it on a project

A project needs a `prooflens.toml`, a claim inventory and review files. It needs no Lean
dependency on ProofLens: the probe runs with the project's own toolchain through
`lake env lean`.

```toml
[project]
name = "my-paper"
lean_root = "."
modules = ["MyPaper"]
scope_roots = ["MyPaper"]
spec_prefix = "MyPaper.PaperSpec"       # closed propositions written from the paper
accept_prefix = "MyPaper.Acceptance"    # theorems whose type is exactly one of them
inventory = "claims.json"
reviews = ["reviews/statements.md", "reviews/definitions.md"]
statement_authors = ["me"]              # their reviews are never independent

[[paper]]
id = "A"
title = "My paper"
source = { git = "me/paper-repo", rev = "<commit>", token_env = "PAPER_TOKEN" }  # or { path = "paper" }
root = "paper/main.tex"                 # needed when several files have \documentclass
publish = { pdf = false, source_text = false, lean = false, reviews = false }  # the default
```

LaTeX is used when a root is found. Otherwise the source's PDF is used, and claims from it are
marked PDF-only.

## Documentation

- [Plan of record](PLAN.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Evidence policy](docs/EVIDENCE_POLICY.md)
- [Data model](docs/DATA_MODEL.md)
- [Publication policy](docs/PUBLICATION_POLICY.md)

## License

Apache-2.0
