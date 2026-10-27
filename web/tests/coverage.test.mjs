// The words for a correspondence reading (src/lib/coverage.js): coverage and basis are shown
// separately, a composition never reads as a Lean statement, an unresolved reading keeps its
// question, and a value the reader does not know is shown as no value. Runs in Node.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { coverageView } from "../src/lib/coverage.js";

const base = { source: "confirmed", coverage: "full", basis: null, refs: [], argument: null, bridge: null,
               question: null, would_decide: null, confidence: null, note: "", by: "A. Auditor" };
const bridge = (state, reasons = []) => ({ theorem: "Cover.three_even", target: "Cover.Spec.three_even", state, reasons });
const text = (v) => [v.headline, ...v.lines.map((l) => [l.label, ...(l.names || []), l.text, l.note].filter(Boolean).join(" "))].join(" | ");

const direct = coverageView({ ...base, basis: "direct", refs: ["Cover.even_add"] });
const composed = coverageView({ ...base, basis: "reviewed_composition", refs: ["Cover.even_add"], argument: "Apply it twice." });
const bridged = coverageView({ ...base, basis: "checked_bridge", refs: ["Cover.three_even"], bridge: bridge("checked") });
// The same coverage, three bases, three headlines.
assert.deepEqual([direct, composed, bridged].map((v) => v.coverage), ["full", "full", "full"]);
assert.deepEqual([direct, composed, bridged].map((v) => v.basis), ["direct", "reviewed_composition", "checked_bridge"]);
assert.equal(direct.headline, "Every clause, in one Lean statement");
assert.equal(composed.headline, "Every clause, by an argument combining Lean results");
assert.equal(bridged.headline, "Every clause, through a checked bridge");
assert.equal(new Set([direct, composed, bridged].map((v) => v.headline)).size, 3);
// A composition shows the auditor's argument and is not drawn as a Lean result.
assert.match(text(composed), /The auditor's argument Apply it twice\. Lean has not checked this combination\. \| Next step State the combination as one Lean result\./);
// It never displays as equivalent to a direct result.
assert.notEqual(composed.tone, "full");
assert.notEqual(composed.tone, direct.tone);
assert.notEqual(composed.headline, direct.headline);
// A stored `composed` reads as full coverage by the auditor's composition.
const old = coverageView({ ...base, coverage: "composed", argument: "Apply it twice." });
assert.deepEqual([old.coverage, old.basis, old.headline, old.tone], ["full", "reviewed_composition", composed.headline, composed.tone]);
// A bridge names its theorem and its target; one not checked, or read at another version, says so.
assert.match(text(bridged), /Bridge Cover\.three_even .*Target Cover\.Spec\.three_even/);
const stale = coverageView({ ...base, basis: "checked_bridge", bridge: bridge("stale", ["the target is not the version the auditor read"]) });
assert.equal(stale.headline, "Every clause, through a checked bridge; the reading is out of date");
assert.match(text(stale), /Out of date the target is not the version the auditor read\./);
const unchecked = coverageView({ ...base, basis: "checked_bridge", bridge: bridge("unchecked", ["its type is not exactly the target"]) });
assert.equal(unchecked.headline, "Every clause, through a bridge Lean does not check");
assert.doesNotMatch(text(unchecked), /Lean checks its proof/);
const forged = coverageView({ ...base, basis: "checked_bridge", bridge: { ...bridge("verified") } });
assert.equal(forged.headline, "Every clause, through a bridge Lean does not check");

// A workspace finding's own bridge reads as the engine's check of it (`bridge_check`), never as
// recorded; one the engine reads as the auditor's composition says what it was recorded as.
{
  const { findingCoverageView, recordedBasisText } = await import("../src/lib/coverage.js");
  const named = { theorem: "Cover.three_even", target: "Cover.Spec.three_even" };
  const finding = { coverage: "full", basis: "checked_bridge", bridge: named, note: "n" };
  assert.equal(findingCoverageView(finding).headline, "Every clause, through a bridge Lean does not check");
  assert.equal(findingCoverageView({ ...finding, bridge_check: { state: "checked", reasons: [] } }).headline,
               "Every clause, through a checked bridge");
  assert.match(text(findingCoverageView({ ...finding, bridge_check: { state: "checked", reasons: [] } })),
               /Bridge Cover\.three_even/);
  const read = { coverage: "full", basis: "reviewed_composition", recorded_basis: "checked_bridge",
                 basis_reason: ["Lean finds no such theorem", "Lean finds no such target"] };
  assert.equal(findingCoverageView({ ...read, bridge: named }).headline, "Every clause, by an argument combining Lean results");
  assert.equal(recordedBasisText({ ...read, bridge: named }),
               "Recorded as a checked bridge (Cover.three_even for Cover.Spec.three_even); no bridge Lean checks now: Lean finds no such theorem; Lean finds no such target.");
  assert.equal(recordedBasisText({ ...read, basis_reason: ["no bridge is recorded"] }),
               "Recorded as a checked bridge; no bridge Lean checks now: no bridge is recorded.");
  assert.equal(recordedBasisText(finding), null);
  assert.equal(findingCoverageView(null), null);
}

// An unresolved reading: its question, never a difference.
const open = coverageView({ ...base, coverage: "unresolved", question: "Natural numbers or integers?", would_decide: "The conventions." });
assert.equal(open.headline, "Unresolved");
assert.match(text(open), /Open question Natural numbers or integers\? \| Would decide it The conventions\./);
assert.notEqual(open.tone, "warning");

// Existing readings keep their words; a basis left out stays unspecified.
assert.equal(coverageView({ ...base, coverage: "partial", note: "n" }).headline, "Part of the claim");
// A basis is named with any coverage.
assert.equal(coverageView({ ...base, coverage: "changed", basis: "direct" }).headline, "Stated differently, in one Lean statement");
assert.equal(coverageView({ ...base }).basis, null);
assert.equal(coverageView({ ...base }).lines.length, 0);
// Unknown values: no label, no basis.
for (const odd of [{ coverage: "verified" }, { coverage: "toString" }]) {
  const v = coverageView({ ...base, ...odd, basis: "direct", note: "n" });
  assert.deepEqual([v.coverage, v.basis, v.headline, v.tone], [null, null, null, "note"], JSON.stringify(odd));
}
assert.equal(coverageView({ ...base, basis: "checked" }).basis, null);
assert.equal(coverageView(null), null);

// A composition (the engine's `composition.view`): the auditor's argument unless Lean checks its
// bridge now, never worded or drawn as a direct result, with the next step beside it.
{
  const { compositionView } = await import("../src/lib/coverage.js");
  const comp = { coverage: "full", basis: "reviewed_composition", gaps: { requirements: 2, uncovered: [], open: [] },
                 next_step: "State the combination as one Lean result." };
  const reviewed = compositionView(comp);
  assert.equal(reviewed.headline, "Every clause, by an argument combining Lean results");
  assert.equal(reviewed.nextStep, "State the combination as one Lean result.");
  assert.notEqual(reviewed.headline, direct.headline);
  assert.notEqual(reviewed.tone, direct.tone);
  const checked = compositionView({ ...comp, basis: "checked_bridge", next_step: null, bridge_check: { state: "checked", reasons: [] } });
  assert.deepEqual([checked.headline, checked.basis, checked.nextStep], ["Every clause, through a checked bridge", "checked_bridge", null]);
  // A basis that says bridge without a check Lean answers now reads as the auditor's composition.
  for (const bridge_check of [undefined, { state: "stale", reasons: ["the target changed"] }, { state: "odd" }]) {
    const v = compositionView({ ...comp, basis: "checked_bridge", bridge_check });
    assert.equal(v.basis, "reviewed_composition");
    assert.equal(v.headline, "Every clause, by an argument combining Lean results");
  }
  const open = compositionView({ coverage: "partial", basis: "reviewed_composition", gaps: { uncovered: ["r1"], open: ["o1"] } });
  assert.equal(open.headline, "Part of the claim, by an argument combining Lean results");
  assert.deepEqual([open.open, open.uncovered], [["o1"], ["r1"]]);
  assert.match(compositionView({ steps: [] }).headline, /no coverage recorded/);
}

// Every surface of the reader words each coverage and basis value as the engine's vocabulary does
// (data/semantic.json): a passport's reading, a composition, the review page's choices and its
// summary of the reviewer's coverage, and the Overview.
{
  const vocabulary = JSON.parse(readFileSync(new URL("../../engine/python/prooflens/data/semantic.json", import.meta.url), "utf8"));
  const { COVERAGE, BASIS, compositionView, inText, readingWords } = await import("../src/lib/coverage.js");
  const { COVERAGE_CHOICES, BASIS_CHOICES, coverageWords } = await import("../src/lib/review.js");
  const { words } = await import("../src/lib/semantic.js");
  const cov = (k) => vocabulary.coverage[k].label, how = (k) => vocabulary.basis[k].label;
  assert.deepEqual(COVERAGE, ["full", "partial", "changed", "related", "unresolved"]);
  assert.deepEqual(COVERAGE_CHOICES, COVERAGE.map((value) => ({ value, label: cov(value) })));
  assert.deepEqual(BASIS_CHOICES, BASIS.map((value) => ({ value, label: how(value) })));
  for (const c of COVERAGE) {
    assert.equal(coverageView({ ...base, coverage: c }).headline, cov(c));
    assert.equal(words("coverage", c).label, cov(c));
    for (const b of BASIS) {
      const both = `${cov(c)}, ${inText(how(b))}`;
      assert.equal(readingWords(c, b), both);
      assert.equal(coverageWords({ coverage: c, basis: b }), both);
      assert.equal(words("basis", b).label, how(b));
      const v = coverageView({ ...base, coverage: c, basis: b, bridge: b === "checked_bridge" ? bridge("checked") : null });
      assert.equal(v.headline, both, `${c} ${b}`);
    }
    assert.equal(compositionView({ coverage: c, basis: "reviewed_composition" }).headline,
                 `${cov(c)}, ${inText(how("reviewed_composition"))}`);
    for (const state of ["stale", "unchecked"]) {
      assert.equal(coverageView({ ...base, coverage: c, basis: "checked_bridge", bridge: bridge(state) }).headline,
                   `${cov(c)}, ${inText(vocabulary.bridge[state].label)}`);
    }
  }
  assert.equal(inText("In one Lean statement"), "in one Lean statement");
}
