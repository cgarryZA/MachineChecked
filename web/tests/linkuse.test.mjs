// How the main results use one link, in the reader's words (src/lib/linkuse.js): the engine's
// answers for the synthetic project tests/fixtures/mainuse (web/tests/fixtures/mainuse, written by
// make_mainuse.py), traced from the suggestion and from a saved selection, and the basis of each.
// Runs in Node: `node tests/linkuse.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { basisText, linkUses } from "../src/lib/linkuse.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (f) => JSON.parse(fs.readFileSync(path.join(here, "fixtures", "mainuse", f), "utf8"));
const built = read("data/main-use.json"), live = read("api-main-use.json");

// The variant the main proof uses, beside the paper-faithful statement it does not.
const variant = linkUses(built, "P:lem:bound", "MainUse.bound_variant");
assert.equal(variant.basis, "suggested: the declarations linked to the paper's theorems");
assert.deepEqual(variant.entries.map((e) => [e.main, e.use, e.answer, e.via]),
  [["MainUse.main_result", "proof", "used by its proof, directly", []]]);
assert.deepEqual(linkUses(built, "P:lem:bound", "MainUse.bound_faithful").entries.map((e) => e.answer),
  ["formalized separately: not used by this main result"]);
assert.deepEqual(linkUses(built, "P:lem:ten", "MainUse.le_ten").entries.map((e) => [e.answer, e.via]),
  [["used by its proof, through 1 other declaration", ["MainUse.bound_variant"]]]);
assert.equal(linkUses(built, "P:lem:ten", "No.Such"), null, "a link the answer does not hold");
assert.equal(linkUses(null, "P:lem:ten", "MainUse.le_ten"), null);

// Saved in a workspace: whose, and when.
const saved = linkUses(live, "P:thm:main", "MainUse.main_result");
assert.match(saved.basis, /^saved in workspace ws-\w+ by human:A-Auditor on \S+$/);
assert.deepEqual(saved.entries.map((e) => [e.main, e.use]),
  [["MainUse.bound_faithful", "none"], ["MainUse.bound_variant", "none"]]);
assert.equal(basisText({ basis: "saved", workspace: "ws-1", by: "human:B", note: "saved against project commit aaaaaaa; this build is of commit bbbbbbb" }),
  "saved in workspace ws-1 by human:B; saved against project commit aaaaaaa; this build is of commit bbbbbbb");
// A full assessment, or several saved selections: not available, with the engine's reason.
assert.deepEqual(linkUses({ available: false, reason: "not available in a full assessment" }, "P:x", "N"),
  { unavailable: "not available in a full assessment" });
console.log("linkuse.test.mjs: ok");
