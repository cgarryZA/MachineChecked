# Result codes and display text

The engine selects `status_code` from evidence. `status` is the displayed sentence; `class`
is its coarse colour/filter group. Changing a label must not change any result or control.

`engine/python/prooflens/status.py` holds the codes, labels, classes and the claim-level
assessment selection. The existing proof/review policy is unchanged. Source consistency and
independent replay remain separate checks, not deductions from a claim's displayed sentence.

Simple links distinguish unbuilt projects, unbuilt or unloadable modules, ambiguous names,
missing declarations, definitions, incomplete proofs, additional axioms and checked proofs.
A failed inspection has no proof result; it must not appear as a checked definition.
`check --json`, reader manifests and public exports retain these codes.

A public paper page uses `published-audit` for another audit's recorded result. It shows the
author's original label and attribution without interpreting that wording as a local proof.
`link.no-audit` and `link.not-in-audit` do not imply that the repository was unbuilt.

`web/src/lib/status.js` supplies explanations and scope filters from codes and structured
clause checks. It never searches status sentences. Unknown codes have an explicit unavailable
explanation rather than a positive fallback. Rebuild generated data that lacks these codes;
there is no display-string compatibility parser.

The normal claim view omits an extra success sentence when it only repeats the status chip.
A refutation explanation says that Lean proves the negation of the **formal statement**;
matching that statement to the printed claim still depends on the recorded correspondence.
