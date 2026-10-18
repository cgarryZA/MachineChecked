// Every engine code has a label; misleading display fields cannot confer assurance.
import assert from "node:assert/strict";
import vocabulary from "../../engine/python/prooflens/data/statuses.json" with { type: "json" };
import { statusView, evidenceView, inScope, notProved, statusSummary, clauseNote } from "../src/lib/presentation.js";
for (const [status_code, row] of Object.entries(vocabulary.statuses)) {
  assert.ok(row.label && row.explanation && row.class);
  assert.deepEqual(statusView({ status_code, status: "formal: accepted", class: "accepted" }), row);
}
for (const [dimension, dim] of Object.entries(vocabulary.dimensions)) {
  for (const state of Object.keys(dim.states)) {
    const shown = evidenceView(dimension, { state });
    assert.equal(shown.state, state);
    assert.ok(shown.label && shown.word && shown.detail);
  }
  assert.equal(evidenceView(dimension, { state: "future" }).state, "unknown");
}
for (const status_code of [undefined, "future", "toString", "__proto__"]) {
  assert.equal(statusView({ status_code, status: "formal: accepted", class: "accepted" }).class, "unspecified");
}
assert.equal(evidenceView("toString", { state: "pass" }).state, "unknown");
assert.equal(inScope({ status_code: "scope.expository", status: "formal: accepted" }), false);
assert.equal(inScope({ status_code: "formal.open", status: "out of scope: expository" }), true);
assert.equal(notProved({ scope: "formal", status_code: "formal.review-pending", class: "accepted" }), true);
assert.equal(notProved({ scope: "formal", status_code: "formal.accepted", class: "open" }), false);
assert.deepEqual(statusSummary([{ status_code: "formal.accepted", status: "x" }, { status_code: "formal.accepted", status: "y" }]),
  [{ status_code: "formal.accepted", count: 2 }]);
assert.equal(clauseNote({ evidence: { formal: { state: "proved" } } }, 1), null);
assert.match(clauseNote({ evidence: { formal: { state: "refuted" } } }, 2), /formal proposition/);
assert.doesNotMatch(clauseNote({ evidence: { formal: { state: "refuted" } } }, 2), /printed statement false/);
assert.match(evidenceView("source", { state: "pdf-only", placement: "approximate", pdf_integrity: "matched" }).word,
  /PDF only · PDF hash matched · approximate location/);
console.log("all structured presentation contracts passed");

const { evidenceFacts } = await import("../src/lib/presentation.js");
assert.deepEqual(evidenceFacts({ clauses: [
  { evidence: { formal: { state: "proved" }, review: { state: "author-reviewed" } } },
  { evidence: { formal: { state: "refuted" }, review: { state: "pending" } } },
] }).map((f) => f.word), ["proved · refuted", "author review · pending"]);
