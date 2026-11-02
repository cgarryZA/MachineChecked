// The review page's issue drafts: the same, verdict for verdict, as the command line's
// (tests/fixtures/review/issue-drafts.json, which tests/contracts/test_review_cli.py checks
// against `review_cli.issue_draft`); and its orders, with the exposure an informed order records.
// Runs in Node: `node tests/review.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { issueDraft, buildReport, orderedUnits, recordExposure, exposureOf, holdsBack, ORDER_SEEN,
         ORDER_EXPOSURE, reportCorrespondence, draftCoverage } from "../src/lib/review.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const DRAFTS = JSON.parse(fs.readFileSync(path.resolve(here, "../../tests/fixtures/review/issue-drafts.json"), "utf8"));
// The coverage a report records beside its verdict, or refuses: the same, case for case, as the
// command line's (tests/fixtures/review/report-coverage.json, which
// tests/contracts/test_review_cli.py checks against `review_cli.correspondence`).
const COVER = JSON.parse(fs.readFileSync(path.resolve(here, "../../tests/fixtures/review/report-coverage.json"), "utf8"));
for (const c of COVER.cases) {
  const { correspondence, problems } = reportCorrespondence(COVER.units[c.unit], c.verdict, c.given);
  assert.equal(problems.length > 0, !!c.refused, `${c.name}: ${problems.join("; ")}`);
  if (!c.refused) assert.deepEqual(correspondence, c.correspondence, c.name);
}
// The page records only the fields of the coverage and basis chosen.
assert.deepEqual(draftCoverage({ coverage: "full", basis: "direct", argument: "left from before", would_decide: "x",
                                 bridge: { theorem: "A", target: "B" } }),
                 { coverage: "full", basis: "direct", argument: null, bridge: null, would_decide: null });
assert.deepEqual(draftCoverage({ basis: "direct" }), { coverage: null, basis: null, argument: null, bridge: null, would_decide: null });

// A report carries the coverage recorded with its verdict; an open question's draft says what
// would decide it, and is never a defect.
const unresolved = buildReport({
  index: { release: "v1", papers: [] }, unit: { ...DRAFTS.unit, kind: "statement" },
  reviewer: { kind: "person", name: "A" },
  draft: { reading: "r".repeat(20), locked_at: "2026-01-01T00:00:00Z", comparison: "c",
           decided_at: "2026-01-01T00:01:00Z", group: "cannot", verdict: "cannot determine",
           detail: "Is n allowed to be 0?", author_shown_at: "2026-01-01T00:02:00Z",
           correspondence: { coverage: "unresolved", would_decide: "The paper's Section 1." } },
});
assert.deepEqual(unresolved.correspondence, { coverage: "unresolved", would_decide: "The paper's Section 1." });
assert.equal(unresolved.issue_draft.kind, "unresolved question");
assert.match(unresolved.issue_draft.body, /\*\*Would decide it\.\*\* The paper's Section 1\./);

for (const c of DRAFTS.cases) {
  assert.deepEqual(issueDraft(DRAFTS.unit, c.verdict, c.detail), c.draft, `issue draft for ${c.verdict}`);
}

// "Cannot determine" leaves an open question in the saved report, never a defect.
const report = buildReport({
  index: { release: "v1", papers: [] }, unit: { ...DRAFTS.unit, kind: "statement" },
  reviewer: { kind: "person", name: "A" },
  draft: { reading: "r".repeat(20), locked_at: "2026-01-01T00:00:00Z", comparison: "c",
           decided_at: "2026-01-01T00:01:00Z", group: "cannot", verdict: "cannot determine",
           detail: "Is n allowed to be 0?", author_shown_at: "2026-01-01T00:02:00Z" },
});
assert.equal(report.issue_draft.kind, "unresolved question");
assert.ok(!JSON.stringify(report.issue_draft).includes("defect"));
assert.match(report.issue_draft.body, /Is n allowed to be 0\?/);
// A report with no coverage recorded says so: null, not a guess from its verdict.
assert.equal(report.correspondence, null);

// The review page's orders (#128). An order the engine arranged puts its open units first, with
// its reasons; the units it does not list (reviewed ones) follow in the queue's order.
const U = (id, claims, extra = {}) => ({ id, kind: "spec", claims: claims.map((c) => ({ id: c })),
  reason: "Short statement", state: "pending", ...extra });
const units = [U("spec:a", ["P:a"]), U("spec:b", ["P:b"]), U("spec:r", ["P:r"], { state: "reviewed" })];
assert.equal(orderedUnits(units, null), units, "without a list, the queue's own order");
const inPaper = orderedUnits(units, [{ id: "spec:b", reason: "In the paper's order; short statement" },
                                     { id: "spec:a", reason: "In the paper's order; short statement" }]);
assert.deepEqual(inPaper.map((u) => u.id), ["spec:b", "spec:a", "spec:r"]);
assert.equal(inPaper[0].reason, "In the paper's order; short statement");
assert.equal(units[1].reason, "Short statement", "the queue's units are left as they are");
assert.deepEqual(orderedUnits(units, [{ id: "spec:gone", reason: "x" }]).map((u) => u.id),
                 ["spec:a", "spec:b", "spec:r"], "a unit the queue does not hold is left out");

// Choosing the informed order records the exposure once for a set of claims, as the command line
// does; a reading of a unit with one of those claims is then not blind, and one with none is.
const work = { exposure: [] };
assert.equal(recordExposure(work, [], "t0"), false, "nothing drawn, nothing seen");
assert.equal(recordExposure(work, ["P:b", "P:a"], "t1"), true);
assert.deepEqual(work.exposure, [{ what: ["prior interpretations"], claims: ["P:a", "P:b"], how: ORDER_EXPOSURE, at: "t1" }]);
assert.equal(recordExposure(work, ["P:a"], "t2"), false, "already recorded");
assert.equal(recordExposure(work, ["P:a", "P:c"], "t3"), true, "a new claim is recorded");
assert.equal(work.exposure.length, 2);
assert.deepEqual(exposureOf(work, units[0]), [{ unit: ORDER_SEEN, what: "author's review" }]);
assert.deepEqual(exposureOf(work, U("spec:z", ["P:z"])), []);
assert.deepEqual(exposureOf({}, units[0]), []);

// The informed order's reason for a unit whose reading was locked without the workspaces' records
// is held back until its verdict. A reading locked after them, a recorded verdict, another order,
// or a reason from the build's own records is shown.
const recorded = U("spec:a", ["P:a"], { priority: { base: "Short statement", signals: [
  { kind: "open question", text: "an open question is recorded", claims: ["P:a"] }] } });
const built = U("spec:b", ["P:b"], { priority: { base: "Short statement", signals: [
  { kind: "changed", text: "changed since the last release: the passage of Theorem 1", claims: ["P:b"] }] } });
const blind = { stage: "compare", revealed_by: [] };
assert.equal(holdsBack("informed", recorded, blind), true);
assert.equal(holdsBack("informed", recorded, { ...blind, revealed_by: exposureOf(work, recorded) }), false);
assert.equal(holdsBack("informed", recorded, { stage: "read" }), false);
assert.equal(holdsBack("informed", recorded, { stage: "author", revealed_by: [] }), false);
assert.equal(holdsBack("priority", recorded, blind), false);
assert.equal(holdsBack("informed", built, blind), false);
