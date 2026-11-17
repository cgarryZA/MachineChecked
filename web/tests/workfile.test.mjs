// The review page's workspace files (`prooflens/workspace@1`), as a static copy of the site writes
// and reads them (web/src/lib/workfile.js): what it refuses, with the reason; how an import merges
// the drafts, as the engine's `machinechecked workspace import` merges them
// (tests/fixtures/review/import-drafts.json, which tests/contracts/test_import_drafts.py checks
// against `workspace.merge_drafts`), and what it asks first; and what the work records as seen,
// read as the engine's `Session.revealed_by` reads it. The round trip through `machinechecked workspace import` and
// `machinechecked view` is in reader.test.mjs. Runs in Node: `node tests/workfile.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readWorkspaceFile, workspaceFile, ensureWorkspace, importPlan, applyImport, importedWords, sameReviewer,
         workspaceReviewer, mergeDrafts, WORKSPACE_SCHEMA } from "../src/lib/workfile.js";
import { exposureOf, recordExposure, revealedIn, READER_SEEN, ORDER_SEEN } from "../src/lib/review.js";

// The drafts an import merges, case for case as the engine merges them.
const FIX = JSON.parse(fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)),
                                                    "../../tests/fixtures/review/import-drafts.json"), "utf8"));
const named = (v) => (typeof v === "string" ? structuredClone(FIX.named[v])
  : { ...structuredClone(FIX.named[v.$]), ...Object.fromEntries(Object.entries(v).filter(([k]) => k !== "$")) });
const draftsOf = (m) => Object.fromEntries(Object.entries(m).map(([u, v]) => [u, named(v)]));
for (const c of FIX.cases) {
  const out = mergeDrafts(draftsOf(c.here), draftsOf(c.theirs), c.reports, c.replace);
  assert.deepEqual(out.drafts, draftsOf(c.drafts), c.name);
  assert.deepEqual(out.applied, c.applied, c.name);
  assert.deepEqual(out.not_applied, c.not_applied, c.name);
  assert.deepEqual(out.kept, c.kept.map((k) => ({ unit: k.unit, current: named(k.current), proposed: named(k.proposed) })), c.name);
}

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
  assert.deepEqual(importPlan(other, read), { merge: null, typed: [] });
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

// An import of the same workspace merges the drafts as the engine does, asks first about those
// that differ only in what was typed, and keeps the browser's exposure, reports, conflicts and
// provenance with the file's; the records the page does not use are the file's.
{
  const base = { reviewer, drafts: { "spec:A": draft("compare", { locked_at: "t0", comparison: "Typed here." }), "spec:B": { stage: "read", reading: "" } },
                 reports: [report("spec:C")], exposure: [{ what: ["prior interpretations"], claims: ["T:thm:a"], how: "x", at: "t1" }] };
  ensureWorkspace(base, index);
  const file = (over) => readWorkspaceFile(JSON.stringify({ ...workspaceFile(base, units), ...over }));
  const typed = file({ review: { drafts: { "spec:A": draft("compare", { locked_at: "t0", comparison: "Typed there." }) }, reports: [report("spec:D")] },
                       exposure: [{ what: ["Lean"], claims: ["T:thm:b"], how: "y", at: "t2" }],
                       records: { "f-1": { id: "f-1", kind: "finding", claim: "T:thm:a", note: "Synthetic finding." } } });
  const plan = importPlan(base, typed);
  assert.deepEqual(plan.typed, [{ unit: "spec:A", kind: "typed", why: "differs from the draft here only in what was typed at step 2; kept as here" }]);
  // Kept as here: the file's version is kept under the workspace's conflicts.
  const work = structuredClone(base);
  const merged = applyImport(work, typed, "typed.json", false);
  assert.deepEqual(merged.not_applied, plan.typed);
  assert.deepEqual(work.drafts, base.drafts, "an empty draft here is kept too");
  assert.deepEqual(work.reports.map((r) => r.unit.id), ["spec:C", "spec:D"], "the browser's reports, then the file's");
  assert.deepEqual(work.exposure.map((e) => e.at), ["t1", "t2"], "what was seen stays recorded");
  assert.deepEqual(Object.keys(work.workspace.records), ["f-1"], "records the page does not use are kept");
  assert.deepEqual(work.workspace.conflicts.map((c) => [c.id, c.current.comparison, c.proposed.comparison, c.how]),
                   [["draft spec:A", "Typed here.", "Typed there.", "import"]]);
  assert.deepEqual(work.workspace.provenance.map((p) => [p.event, p.from]), [["imported", "typed.json"]]);
  // Taken from the file: the one here is kept under conflicts.
  const taken = structuredClone(base);
  applyImport(taken, typed, "typed.json", true);
  assert.equal(taken.drafts["spec:A"].comparison, "Typed there.");
  assert.deepEqual(taken.workspace.conflicts.map((c) => [c.current.comparison, c.proposed.comparison, c.how]),
                   [["Typed there.", "Typed here.", "import, replaced"]]);
  // An unlocked reading from the file never replaces the locked one, whatever is chosen.
  const older = file({ review: { drafts: { "spec:A": draft("read") }, reports: [] } });
  assert.deepEqual(importPlan(base, older).merge.not_applied.map((n) => n.why), ["older than the draft here (step 1 in the file, step 2 here)"]);
  const kept = structuredClone(base);
  applyImport(kept, older, "older.json", true);
  assert.deepEqual(kept.drafts["spec:A"], base.drafts["spec:A"]);
  // Another workspace, or another reviewer's: refused while the browser holds work, taken when it holds none.
  const another = file({ id: "ws-another" });
  assert.match(importPlan(work, another).error, new RegExp(`the file is workspace ws-another, and this browser holds the review work of workspace ${work.workspace.id}; a static copy keeps one workspace`));
  assert.match(importPlan({ reviewer, drafts: { "spec:A": draft("compare") }, reports: [], exposure: [] }, another).error,
               /holds the review work of a workspace it has not exported/);
  const theirs = file({ id: "ws-theirs", reviewer: { id: "human:Someone-else", kind: "human", name: "Someone else" } });
  assert.match(importPlan(work, theirs).error, /the workspace of human:Someone-else, and this browser holds the review work of human:Synthetic-reviewer/);
  const fresh = { reviewer, drafts: { "spec:B": { stage: "read", reading: "" } }, reports: [], exposure: [] };
  assert.deepEqual(importPlan(fresh, theirs), { merge: null, typed: [] });
  applyImport(fresh, theirs, "theirs.json");
  assert.equal(fresh.reviewer.id, "human:Someone-else");
  assert.equal(fresh.reviewer.name, "Someone else");
  assert.deepEqual(fresh.drafts, theirs.review.drafts, "a browser without work takes the file's drafts");
}
assert.ok(sameReviewer("human:Ada Lovelace", "human:Ada_Lovelace"), "as the engine's reviewer_slug");
assert.ok(!sameReviewer("human:Ada", "human:Bob") && !sameReviewer(null, "human:Ada"));

// Exposure the engine recorded is read as the engine reads it, each named by how it was seen.
{
  const work = { workspace: { id: "ws-1" }, exposure: [
    { what: ["Lean"], claims: ["T:thm:a"], how: READER_SEEN, at: "2026-01-01T00:00:00Z" },
    { what: ["Lean", "prior interpretations"], claims: null, how: "informed investigation", at: "2026-01-03T00:00:00Z" },
    { what: ["external material"], claims: ["T:thm:a"], how: "a talk", at: "2026-01-01T00:00:00Z" }] };
  assert.deepEqual(exposureOf(work, units[0]), [
    { unit: `review page (${READER_SEEN})`, what: "Lean" },
    { unit: "review page (informed investigation)", what: "Lean" },
    { unit: "review page (informed investigation)", what: "author's review" }]);
  // What was recorded by a time: what a reading locked then had seen.
  assert.deepEqual(exposureOf(work, units[0], "2026-01-02T00:00:00Z"), [{ unit: `review page (${READER_SEEN})`, what: "Lean" }]);
  const page = { exposure: [] };
  assert.equal(recordExposure(page, ["T:thm:a"], "t", ["Lean"], READER_SEEN), true);
  assert.equal(recordExposure(page, ["T:thm:a"], "t2", ["Lean"], READER_SEEN), false, "already recorded");
  assert.equal(recordExposure(page, ["T:thm:a"], "t3"), true, "prior interpretations are another thing seen");
  assert.deepEqual(exposureOf(page, units[0]), [{ unit: `review page (${READER_SEEN})`, what: "Lean" },
                                                { unit: ORDER_SEEN, what: "author's review" }]);
  assert.deepEqual(exposureOf(page, units[1]), []);
}

// What a reading had seen by the time it was locked, as the engine's submit lists it: the units the
// work reached whose material shows its Lean, by then, with the exposure recorded by then.
{
  const shows = [{ id: "spec:A", claims: [{ id: "T:thm:a" }], reveals: { lean: ["spec:B"], author: [] } },
                 { id: "spec:B", claims: [{ id: "T:thm:b" }] }];
  const work = { drafts: { "spec:A": { stage: "compare", locked_at: "2026-01-02T00:00:00Z" } }, reports: [],
                 exposure: [{ what: ["Lean"], claims: ["T:thm:b"], how: READER_SEEN, at: "2026-01-01T00:00:00Z" }] };
  assert.deepEqual(revealedIn(work, shows, shows[1]), [{ unit: `review page (${READER_SEEN})`, what: "Lean" }, { unit: "spec:A", what: "Lean" }]);
  assert.deepEqual(revealedIn(work, shows, shows[1], "2026-01-01T12:00:00Z"), [{ unit: `review page (${READER_SEEN})`, what: "Lean" }],
                   "spec:A's Lean was shown after that");
  assert.deepEqual(revealedIn(work, shows, shows[1], "2025-12-31T00:00:00Z"), []);
}

// A structure's unit: a projection's Lean seen as a unit of its own is the structure's Lean seen.
{
  const pair = { id: "def:Toy.Pair", claims: [{ id: "T:thm:a" }], members: [{ name: "Toy.Pair.x", role: "projection" }] };
  const work = { drafts: { "def:Toy.Pair.x": { stage: "compare", locked_at: "2026-01-02T00:00:00Z" } }, reports: [], exposure: [] };
  assert.deepEqual(revealedIn(work, [pair], pair), [{ unit: "def:Toy.Pair.x", what: "Lean" }]);
}
