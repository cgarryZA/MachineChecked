// The reader's content search (src/lib/retrieval.js) against the engine's: for each case of
// tests/fixtures/retrieval/cases.json, written by the engine, the same terms, the same results
// in the same order, the same scores and the same reasons, for searches by text and from a
// declaration, and the same parts of each statement. Runs in Node.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Retrieval, claimQuery, leanShape, normalParts } from "../src/lib/retrieval.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const data = JSON.parse(fs.readFileSync(path.resolve(here, "../../tests/fixtures/retrieval/cases.json"), "utf8"));
const ret = new Retrieval(data.index);
const KINDS = { theorem: (k) => k === "theorem", definition: (k) => k !== "theorem" };
const project = (r) => ({ name: r.name, kind: r.kind, score: r.score, content: r.content, reasons: r.reasons });

assert.ok(data.cases.length >= 15, "the fixture has its cases");
for (const c of data.cases) {
  assert.deepEqual(ret.tok.terms(c.query), c.terms, `terms of ${JSON.stringify(c.query)}`);
  const order = c.paper ? ret.tok.paperQuantifiers(c.query) : null;
  assert.equal(order, c.paper_order, `quantifier order of ${JSON.stringify(c.query)}`);
  const got = ret.search(c.query, { kinds: KINDS[c.kinds] || null, limit: c.limit, after: c.after || null, paperOrder: order });
  assert.deepEqual({ ...got, results: got.results.map(project) }, c.expect, `search for ${JSON.stringify(c.query)}`);
  for (const r of got.results) assert.equal(r.statement, data.index.docs.find((d) => d.name === r.name).type, "the complete statement");
}
// Searches from a declaration, and the parts of each statement, as the engine reads them.
assert.ok(data.like.length >= 5 && data.shapes.length >= 8, "the fixture has its searches from a declaration and its statements");
for (const c of data.like) {
  const got = ret.searchLike(c.name, { limit: c.limit });
  assert.deepEqual({ ...got, results: got.results.map(project) }, c.expect, `search like ${c.name}`);
}
for (const c of data.shapes) {
  const sh = leanShape(c.type);
  assert.deepEqual(sh, c.shape, `the parts of ${JSON.stringify(c.type)}`);
  assert.deepEqual([normalParts(sh, true), normalParts(sh, false)], c.parts, `the normalised parts of ${JSON.stringify(c.type)}`);
}
// A claim's own query: its title and printed passage, over declarations of its sort.
const q = claimQuery(ret, { title: "", statement_tex: data.cases[0].query, scope: "formal" });
assert.equal(q.text, data.cases[0].query);
assert.equal(q.paperOrder, data.cases[0].paper_order);
assert.equal(q.kinds("theorem"), true);
assert.equal(q.kinds("def"), false);
console.log(`retrieval: ${data.cases.length} searches, ${data.like.length} searches from a declaration and ${data.shapes.length} statements' parts agree with the engine`);
