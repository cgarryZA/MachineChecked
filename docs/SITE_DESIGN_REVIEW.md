# Site and reader design audit · October 2026

This is a product review of the tool and current landing page, not an audit of mathematical correctness. The public website presently has a synthetic demo; the separate `machinechecked.org` repository has not yet received the production site.

## What changed in this branch

- **First five seconds:** one headline and two routes, *Explore demo* (no install) or *Use it on your paper* (local CLI).
- **Actual product:** the existing light/dark reader screenshots become the lead visual; the previous repeated synthetic-proposition box is removed.
- **Trust:** *linked to Lean*, *checked in Lean* and *mathematically reviewed* are distinguished before mentioning a review queue or release gate.
- **Onboarding:** a copyable command, explicit prerequisites and clear caveats for PDF heuristics, existing Leanblueprint tags and self-declared `formalization.yaml`.
- **Publishing:** standalone HTML and author-hosted audit remain available; the public search catalogue is explicitly described as future work.
- **Discoverability:** canonical URL, social preview, SoftwareApplication metadata, sitemap, robots.txt, llms.txt and a useful 404.
- **Access:** semantic landmarks, keyboard skip link, visible focus rings, reduced-motion handling and mobile layout.

No Lean, review, acceptance or status computation code changes here.

## Product decisions to preserve

1. **Tool and hosting platform are separate.** MachineChecked's CLI works locally without registering a paper. The future website indexes externally hosted audits but does not compile third-party Lean.
2. **A paper is the primary object.** Multiple repositories may formalise it; never merge their proof status into one claim of verification.
3. **Names matter.** A confirmed link is not an independent mathematical correspondence review. A report from a reviewer is not automatically accepted by a maintainer.
4. **Reports go to the responsible project.** Claim-level issues should link to the formalisation/audit author, not a general website inbox.
5. **Privacy is deliberate.** Generated standalone HTML can include the complete paper and Lean details. The publishing instructions must not imply that the file is safe to post publicly without inspection.

## Remaining product issues (not implemented in this branch)

| Priority | Issue | Acceptance test |
|---|---|---|
| P0 | The reader becomes a cramped three-pane interface on laptops | Paper remains comfortably readable with a claim selected; split can be adjusted and contents collapsed |
| P0 | First-time links and edited links can trigger a full reader reload | A saved link updates the selected claim without losing the reader's scroll/selection |
| P1 | Long Lean statements and review cards still feel technical to non-experts | A first-time mathematician can explain *what Lean checked* within 30 seconds of opening a theorem |
| P1 | The review queue has a long protocol with many text fields | Progressive disclosure still preserves the read → compare → author-review order, with reliable save/export |
| P1 | Public hosting has no useful paper-level discovery yet | An arXiv paper page is crawlable, names each formalisation, and never implies MachineChecked endorsed it |
| P1 | Automatic PDF theorem extraction is heuristic | A visible test set records misses and incorrect anchors across several PDF styles |
| P2 | Publication is split between two repositories | A single website deployment source is active, with domain and asset URLs tested before switching DNS |

A passing CI build is not a substitute for real browser screenshots, a keyboard-only walkthrough, or a first-time-user test. Perform those against the deployed branch preview before merging.
