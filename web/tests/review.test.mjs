// The review page's issue drafts: the same, verdict for verdict, as the command line's
// (tests/fixtures/review/issue-drafts.json, which tests/contracts/test_review_cli.py checks
// against `review_cli.issue_draft`). Runs in Node: `node tests/review.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { issueDraft, buildReport } from "../src/lib/review.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const DRAFTS = JSON.parse(fs.readFileSync(path.resolve(here, "../../tests/fixtures/review/issue-drafts.json"), "utf8"));

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
