// The words for a correspondence reading (src/lib/coverage.js): coverage and basis are shown
// separately, a composition never reads as a Lean statement, an unresolved reading keeps its
// question, and a value the reader does not know is shown as no value. Runs in Node.
import assert from "node:assert/strict";
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
assert.equal(direct.headline, "States every clause");
assert.equal(composed.headline, "Every clause, by the auditor's composition");
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
assert.match(stale.headline, /out of date/);
assert.match(text(stale), /Out of date the target is not the version the auditor read\./);
const unchecked = coverageView({ ...base, basis: "checked_bridge", bridge: bridge("unchecked", ["its type is not exactly the target"]) });
assert.equal(unchecked.headline, "Every clause, through a bridge Lean does not check");
assert.doesNotMatch(text(unchecked), /Lean checks its proof/);
const forged = coverageView({ ...base, basis: "checked_bridge", bridge: { ...bridge("verified") } });
assert.equal(forged.headline, "Every clause, through a bridge Lean does not check");

// An unresolved reading: its question, never a difference.
const open = coverageView({ ...base, coverage: "unresolved", question: "Natural numbers or integers?", would_decide: "The conventions." });
assert.equal(open.headline, "Unresolved");
assert.match(text(open), /Open question Natural numbers or integers\? \| Would decide it The conventions\./);
assert.notEqual(open.tone, "warning");

// Existing readings keep their words; a basis left out stays unspecified.
assert.equal(coverageView({ ...base, coverage: "partial", note: "n" }).headline, "States part of the claim");
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
  assert.equal(reviewed.headline, "Every clause, by the auditor's composition");
  assert.equal(reviewed.nextStep, "State the combination as one Lean result.");
  assert.notEqual(reviewed.headline, direct.headline);
  assert.notEqual(reviewed.tone, direct.tone);
  const checked = compositionView({ ...comp, basis: "checked_bridge", next_step: null, bridge_check: { state: "checked", reasons: [] } });
  assert.deepEqual([checked.headline, checked.basis, checked.nextStep], ["Every clause, through a checked bridge", "checked_bridge", null]);
  // A basis that says bridge without a check Lean answers now reads as the auditor's composition.
  for (const bridge_check of [undefined, { state: "stale", reasons: ["the target changed"] }, { state: "odd" }]) {
    const v = compositionView({ ...comp, basis: "checked_bridge", bridge_check });
    assert.equal(v.basis, "reviewed_composition");
    assert.equal(v.headline, "Every clause, by the auditor's composition");
  }
  const open = compositionView({ coverage: "partial", basis: "reviewed_composition", gaps: { uncovered: ["r1"], open: ["o1"] } });
  assert.equal(open.headline, "States part of the claim, by the auditor's composition");
  assert.deepEqual([open.open, open.uncovered], [["o1"], ["r1"]]);
  assert.match(compositionView({ steps: [] }).headline, /no coverage recorded/);
}
