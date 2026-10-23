// The review page's issue drafts: the same, verdict for verdict, as the command line's
// (tests/fixtures/review/issue-drafts.json, which tests/contracts/test_review_cli.py checks
// against `review_cli.issue_draft`). Runs in Node: `node tests/review.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { issueDraft, buildReport, reportCorrespondence, draftCoverage } from "../src/lib/review.js";

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
