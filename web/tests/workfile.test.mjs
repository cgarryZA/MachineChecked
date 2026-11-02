// The review page's workspace files (`prooflens/workspace@1`), as a static copy of the site writes
// and reads them (web/src/lib/workfile.js): what it refuses, with the reason; what an import keeps
// and what it asks before replacing; and the exposure a workspace records, read as the engine's
// `Session.revealed_by` reads it. The round trip through `machinechecked workspace import` and
// `machinechecked view` is in reader.test.mjs. Runs in Node: `node tests/workfile.test.mjs`.
import assert from "node:assert/strict";
import { readWorkspaceFile, workspaceFile, ensureWorkspace, importPlan, applyImport, importedWords, sameReviewer,
         workspaceReviewer, WORKSPACE_SCHEMA } from "../src/lib/workfile.js";
import { exposureOf, recordExposure, READER_SEEN, ORDER_SEEN } from "../src/lib/review.js";

const refused = (text, why) => assert.throws(() => readWorkspaceFile(typeof text === "string" ? text : JSON.stringify(text)),
                                             (e) => e.message === why, why);
const index = { release: "r1", project: { name: "toy-paper", commit: "abc" }, papers: [{ id: "T", title: "A toy paper", revision: null }] };
const units = [{ id: "spec:A", claims: [{ id: "T:thm:a" }] }, { id: "spec:B", claims: [{ id: "T:thm:b" }, { id: "T:thm:c" }] }];
const reviewer = { kind: "human", name: "Synthetic reviewer", id: "human:Synthetic-reviewer" };
const draft = (stage, extra = {}) => ({ stage, reading: "A synthetic reading of the claim, long enough.", ...extra });
const report = (unit) => ({ schema: "prooflens/review-report@1", unit: { id: unit }, pins: { release: "r1", fingerprint: "fp-" + unit } });

// What the page refuses, with the reason the engine gives where it gives one.
refused("{", "not a JSON file");
refused([], "not a workspace or review work file");
refused({ schema: "prooflens/workspace@2", id: "ws-new" }, "not a workspace this version can read (schema 'prooflens/workspace@2')");
refused({ schema: "prooflens/review-reports@1", reports: [] }, "not a workspace this version can read (schema 'prooflens/review-reports@1')");
refused({ hello: 1 }, "not a workspace or review work file");
refused({ schema: WORKSPACE_SCHEMA, id: "ws-a", mode: "blind" }, "mode 'blind' is not one of: independent, informed");
assert.throws(() => readWorkspaceFile(JSON.stringify({ schema: WORKSPACE_SCHEMA, id: "ws-a", mode: "informed" })),
              /informed investigation, which a static copy of the site cannot continue/);
refused({ schema: WORKSPACE_SCHEMA, mode: "independent" }, "not a workspace: it has no id");
refused({ schema: WORKSPACE_SCHEMA, id: "ws-a", mode: "independent", review: { drafts: { "spec:A": { reading: "x" } }, reports: [] } },
        "not a workspace: the draft of spec:A is at no step");
refused({ schema: WORKSPACE_SCHEMA, id: "ws-a", mode: "independent", review: { drafts: {}, reports: [{ unit: "spec:A" }] } },
        "not a workspace: a report has no unit or pins");
refused({ schema: WORKSPACE_SCHEMA, id: "ws-a", mode: "independent", exposure: [{ claims: null }] },
        "not a workspace: its exposure is not a list of what was seen");
// The older review work file is read as the engine upgrades it: an independent workspace.
{
  const ws = readWorkspaceFile(JSON.stringify({ reviewer: workspaceReviewer(reviewer), drafts: { "spec:A": draft("compare") }, reports: [] }));
  assert.equal(ws.schema, WORKSPACE_SCHEMA);
  assert.equal(ws.mode, "independent");
  assert.deepEqual(ws.review.drafts, { "spec:A": draft("compare") });
  assert.equal(ws.provenance[0].event, "upgraded from a review work file");
}

// The page's work written as a workspace: the parts `workspace.new` opens, the page's review work,
// its exposure, and the time it was exported; the same workspace each time.
{
  const work = { reviewer, drafts: { "spec:A": draft("compare", { checklist: { constants: "unsure" } }) },
                 reports: [report("spec:B")], exposure: [], skipped: ["spec:B"], exported: 1 };
  assert.equal(ensureWorkspace(work, index), true);
  assert.equal(ensureWorkspace(work, index), false, "opened once");
  const f = workspaceFile(work, units);
  assert.deepEqual(Object.keys(f).sort(), ["conflicts", "created_at", "exported_at", "exposure", "id", "mode", "provenance", "records",
                                           "resume", "review", "reviewer", "revision", "schema", "selection", "sources"]);
  assert.match(f.id, /^ws-[0-9a-f]{12}$/);
  assert.equal(f.mode, "independent");
  assert.deepEqual(f.reviewer, { id: "human:Synthetic-reviewer", kind: "human", name: "Synthetic reviewer", model: null,
                                 same_family_as_author: "no", identity: "self-declared" });
  assert.deepEqual(f.sources, { release: "r1", project: { name: "toy-paper", commit: "abc" }, papers: [{ id: "T", title: "A toy paper" }] });
  assert.deepEqual(f.review, { drafts: work.drafts, reports: work.reports });
  assert.equal(workspaceFile(work, units).id, f.id);
  // A file the page wrote reads back as it was written, and imported into another browser gives
  // the same work, which it writes again as the same workspace.
  const other = { drafts: {}, reports: [], exposure: [] };
  const read = readWorkspaceFile(JSON.stringify(f));
  assert.deepEqual(importPlan(other, read), { losing: [] });
  applyImport(other, read, "work.json");
  assert.deepEqual([other.drafts, other.reports, other.reviewer.id], [work.drafts, work.reports, reviewer.id]);
  const again = workspaceFile(other, units);
  assert.deepEqual({ ...again, exported_at: null, provenance: null }, { ...f, exported_at: null, provenance: null });
  assert.deepEqual(again.provenance.map((p) => [p.event, p.by, p.from]), [["imported", reviewer.id, "work.json"]]);
  assert.equal(importedWords(read), "1 draft, 1 report, 0 records");
}
// A draft in which an earlier version of the page recorded the Lean seen on the claim's page
// before its reading is written as the exposure the engine reads, for the unit's claims.
{
  const work = { reviewer, drafts: { "spec:B": { stage: "read", reading: "", reader_exposure: true } }, reports: [], exposure: [] };
  ensureWorkspace(work, index);
  assert.deepEqual(workspaceFile(work, units).exposure, [{ what: ["Lean"], claims: ["T:thm:b", "T:thm:c"], how: READER_SEEN }]);
}

// An import replaces the browser's drafts with the file's, and asks first when the browser holds a
// draft the file does not hold as it is; it keeps the browser's exposure, and its reports when the
// file is the same workspace.
{
  const base = { reviewer, drafts: { "spec:A": draft("compare"), "spec:B": { stage: "read", reading: "" } }, reports: [report("spec:C")],
                 exposure: [{ what: ["prior interpretations"], claims: ["T:thm:a"], how: "x", at: "t1" }] };
  ensureWorkspace(base, index);
  const file = (over) => readWorkspaceFile(JSON.stringify({ ...workspaceFile(base, units), ...over }));
  const later = file({ review: { drafts: { "spec:A": draft("author", { verdict: "faithful" }) }, reports: [report("spec:D")] },
                       exposure: [{ what: ["Lean"], claims: ["T:thm:b"], how: "y", at: "t2" }],
                       records: { "f-1": { id: "f-1", kind: "finding", claim: "T:thm:a", note: "Synthetic finding." } } });
  assert.deepEqual(importPlan(base, later), { losing: ["your draft of spec:A"] }, "an empty draft is not work");
  const work = structuredClone(base);
  applyImport(work, later, "later.json");
  assert.deepEqual(work.drafts, later.review.drafts);
  assert.deepEqual(work.reports.map((r) => r.unit.id), ["spec:D", "spec:C"], "same workspace: the browser's reports are kept");
  assert.deepEqual(work.exposure.map((e) => e.at), ["t2", "t1"], "what was seen stays recorded");
  assert.deepEqual(Object.keys(work.workspace.records), ["f-1"], "records the page does not use are kept");
  // Another workspace of the same reviewer: its reports replace the browser's, after asking.
  const another = file({ id: "ws-another", review: { drafts: {}, reports: [] } });
  assert.deepEqual(importPlan(work, another), { losing: ["your draft of spec:A", "2 reports", "1 record of workspace " + work.workspace.id] });
  // Another reviewer's workspace: refused while the browser holds work, taken when it holds none.
  const theirs = file({ id: "ws-theirs", reviewer: { id: "human:Someone-else", kind: "human", name: "Someone else" } });
  assert.match(importPlan(work, theirs).error, /the workspace of human:Someone-else, and this browser holds the review work of human:Synthetic-reviewer/);
  const fresh = { reviewer, drafts: { "spec:B": { stage: "read", reading: "" } }, reports: [], exposure: [] };
  assert.deepEqual(importPlan(fresh, theirs), { losing: [] });
  applyImport(fresh, theirs, "theirs.json");
  assert.equal(fresh.reviewer.id, "human:Someone-else");
  assert.equal(fresh.reviewer.name, "Someone else");
}
assert.ok(sameReviewer("human:Ada Lovelace", "human:Ada_Lovelace"), "as the engine's reviewer_slug");
assert.ok(!sameReviewer("human:Ada", "human:Bob") && !sameReviewer(null, "human:Ada"));

// Exposure the engine recorded is read as the engine reads it, named by the workspace it is in.
{
  const work = { workspace: { id: "ws-1" }, exposure: [
    { what: ["Lean"], claims: ["T:thm:a"], how: READER_SEEN, at: "t" },
    { what: ["Lean", "prior interpretations"], claims: null, how: "informed investigation", at: "t" },
    { what: ["external material"], claims: ["T:thm:a"], how: "a talk", at: "t" }] };
  assert.deepEqual(exposureOf(work, units[0]), [
    { unit: `workspace ws-1 (${READER_SEEN})`, what: "Lean" },
    { unit: "workspace ws-1 (informed investigation)", what: "Lean" },
    { unit: "workspace ws-1 (informed investigation)", what: "author's review" }]);
  // On a page that has not written a workspace, its own records are named by the review page.
  const page = { exposure: [] };
  assert.equal(recordExposure(page, ["T:thm:a"], "t", ["Lean"], READER_SEEN), true);
  assert.equal(recordExposure(page, ["T:thm:a"], "t2", ["Lean"], READER_SEEN), false, "already recorded");
  assert.equal(recordExposure(page, ["T:thm:a"], "t3"), true, "prior interpretations are another thing seen");
  assert.deepEqual(exposureOf(page, units[0]), [{ unit: `review page (${READER_SEEN})`, what: "Lean" },
                                                { unit: ORDER_SEEN, what: "author's review" }]);
  assert.deepEqual(exposureOf(page, units[1]), []);
}
