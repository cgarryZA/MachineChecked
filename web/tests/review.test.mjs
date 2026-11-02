// The review page's issue drafts: the same, verdict for verdict, as the command line's
// (tests/fixtures/review/issue-drafts.json, which tests/contracts/test_review_cli.py checks
// against `review_cli.issue_draft`); its Undo, which gives back the draft the engine's does; and
// its orders, with the exposure an informed order records.
// Runs in Node: `node tests/review.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { issueDraft, buildReport, orderedUnits, recordExposure, exposureOf, holdsBack, ORDER_SEEN,
         ORDER_EXPOSURE, reportCorrespondence, draftCoverage, draftFromReport, undoReport,
         questionsOf } from "../src/lib/review.js";

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

// Undo on a static copy gives back the draft the engine's Undo gives back, report for report
// (tests/fixtures/review/undo.json, which tests/contracts/test_review_shared.py checks against
// `review_cli.Session.undo`). Saved again, even on a later build, the report records what it
// recorded before: its checklist, and the Lean its verdict was recorded against. A draft of the
// unit in progress is kept, and Undo refused.
const UNDO = JSON.parse(fs.readFileSync(path.resolve(here, "../../tests/fixtures/review/undo.json"), "utf8"));
const again = (r, draft) => buildReport({
  index: { release: r.pins.release, papers: [{ id: "T" }] }, draft,
  unit: { ...r.unit, claims: r.unit.claims.map((id) => ({ id })), fingerprint: "a later build's", fingerprints: null },
  reviewer: { kind: "human", name: "Synthetic Reviewer", sameFamily: "no" } });
for (const c of UNDO.cases) {
  assert.deepEqual(draftFromReport(c.report), c.draft, c.name);
  const work = { drafts: {}, reports: [structuredClone(c.report)] };
  assert.equal(undoReport(work), null, c.name);
  assert.deepEqual(work, { drafts: { [c.report.unit.id]: c.draft }, reports: [] }, c.name);
  const r = again(c.report, work.drafts[c.report.unit.id]);
  assert.deepEqual(r.comparison.checklist, c.draft.checklist, c.name);
  for (const k of ["fingerprint", "fingerprints", "legacy_hash"]) assert.deepEqual(r.pins[k], c.report.pins[k], `${c.name}: pins.${k}`);
  work.reports.push(structuredClone(c.report));
  assert.equal(undoReport(work), `${c.report.unit.id} has a draft in progress; finish or keep it first`);
  assert.equal(work.reports.length, 1, "nothing is taken back");
  assert.deepEqual(work.drafts, { [c.report.unit.id]: c.draft }, "the draft in progress is kept");
}
{
  const full = UNDO.cases[0].report;
  const r = again(full, draftFromReport(full));
  assert.deepEqual(r, { ...full, submitted_at: r.submitted_at }, "a report saved again is the report taken back");
}
assert.equal(undoReport({ drafts: {}, reports: [] }), "there is no report to take back");

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

// Every signal the workspaces give is held back the same way: a finding a change reopened, a
// record out of date, a saved main result.
for (const kind of ["reopened finding", "out of date", "main result"]) {
  const u = U("spec:w", ["P:w"], { priority: { base: "Short statement", signals: [{ kind, text: "x", claims: ["P:w"] }] } });
  assert.equal(holdsBack("informed", u, blind), true, kind);
}

// The questions a new reading answers, as the engine words them, each once; none for a unit
// whose signals ask none.
const asked = U("spec:q", ["P:q"], { priority: { base: "Short statement", signals: [
  { kind: "reopened finding", text: "a recorded finding is due for review: the passage of Theorem 1 changed", claims: ["P:q"],
    questions: ["Does finding f-1 still hold now that the passage of Theorem 1 changed?"] },
  { kind: "reopened", text: "reopened since the last release: its Lean statement changed", claims: ["P:q"],
    questions: ["Does it still state Theorem 1?", "Does finding f-1 still hold now that the passage of Theorem 1 changed?", " ", 7] }] } });
assert.deepEqual(questionsOf(asked), ["Does finding f-1 still hold now that the passage of Theorem 1 changed?", "Does it still state Theorem 1?"]);
assert.deepEqual(questionsOf(recorded), []);
assert.deepEqual(questionsOf(null), []);

// The Overview's Review next (#478): the queue's open units in the queue's own order, with the
// engine's reasons, named by their claims' numbers and never by their Lean; a definition by the
// claims that use it.
{
  const { reviewNext, kindWord } = await import("../src/lib/reviewnext.js");
  const claims = [{ id: "P:a", number: "Theorem 1" }, { id: "P:b", number: "Lemma 2" }, { id: "P:c", number: "(3)" }];
  const queue = { units: [
    { id: "spec:X.a", kind: "spec", name: "X.a", state: "pending", reason: "Reopened since the last release: the passage of Theorem 1 changed; short statement", claims: [{ id: "P:a" }] },
    { id: "def:X.d", kind: "def", name: "X.d", state: "pending", reason: "Short definition; used by 2 claim(s)", claims: [{ id: "P:a" }, { id: "P:b" }] },
    { id: "spec:X.b", kind: "spec", name: "X.b", state: "reviewed", reason: "Short statement", claims: [{ id: "P:b" }] },
    { id: "step:P:c", kind: "step", name: "(3)", state: "pending", reason: "Proof step of Theorem 1", claims: [{ id: "P:c" }] },
    { id: "link:x", kind: "link", name: "X.x", state: "pending", reason: "Short statement", claims: [{ id: "P:x", number: "Theorem 9" }] }] };
  const got = reviewNext(queue, claims, 3);
  assert.equal(got.open, 4);
  assert.deepEqual(got.entries, [
    { id: "spec:X.a", kind: "Statement", label: "Theorem 1", reason: queue.units[0].reason },
    { id: "def:X.d", kind: "Definition", label: "A definition used by Theorem 1 and Lemma 2", reason: queue.units[1].reason },
    { id: "step:P:c", kind: "Proof step", label: "(3)", reason: "Proof step of Theorem 1" }]);
  assert.ok(!got.entries.some((e) => `${e.label} ${e.reason}`.includes("X.")), "no Lean name in what is shown");
  assert.equal(reviewNext(queue, claims).entries[3].label, "Theorem 9");
  assert.equal(kindWord({ kind: "link" }), "Linked claim");
  assert.deepEqual(reviewNext({ units: [{ ...queue.units[2] }] }, claims), { entries: [], open: 0 });
  assert.deepEqual(reviewNext(null, claims), { entries: [], open: 0 });
}
