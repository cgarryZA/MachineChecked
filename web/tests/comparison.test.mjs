// The comparison's inputs and rows (src/lib/comparison.js): what each stage of the review
// protocol may show, as data, and where a statement's rows and an alignment's targets are. On the
// toy audit's and the structure fixture's claims as the engine wrote them.
// Runs in Node: `node tests/comparison.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { comparisonInputs, declSide, usersSide, statementRows, rowOfTarget, rowOfId, exactPart,
         alignmentSource, alignedRows, pinScope, sameScope, paperSide, formalSide } from "../src/lib/comparison.js";
import { propertyStanding } from "../src/lib/carried.js";
import { spineOf } from "../src/lib/tree.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const claim = (dir, prefix) => {
  const d = path.join(here, "fixtures", dir, "data", "claims");
  return JSON.parse(fs.readFileSync(path.join(d, fs.readdirSync(d).find((f) => f.startsWith(prefix))), "utf8"));
};
const decl = (key) => JSON.parse(fs.readFileSync(path.join(here, "fixtures", "toy", "data", "decls", key + ".json"), "utf8"));

// The even-addition claim with everything a person can record about it: symbol links (in the
// fixture), a correspondence note, a review, the engine's findings, published workspace records.
const evenAdd = { ...claim("toy", "T_thm_even-add"),
  correspondence: { coverage: "full", note: "SYNTHETIC-NOTE: the author's reading", by: "SYNTHETIC-AUTHOR" },
  reviews: [{ verdict: { value: "faithful", detail: "SYNTHETIC-REVIEW" }, reviewer: { id: "human:SYNTHETIC-REVIEWER" } }],
  findings: [{ id: "totalised:SYNTHETIC", subject: "T:thm:even-add#0", dismissed: { by: "SYNTHETIC-AUTHOR", rationale: "SYNTHETIC-RATIONALE" } }],
  work: "work/even-add.json" };
assert.ok(evenAdd.symbols.length, "the fixture has symbol links");

// Independent Read: the paper only.
const read = comparisonInputs("read", [evenAdd]);
assert.equal(read.formal, null);
assert.deepEqual(read.definitions, []);
assert.equal(read.annotations, null);
assert.ok(read.passages[0].excerpt && read.passages[0].statement_tex, "the printed passage, complete");

// Independent Compare: the paper and the complete Lean as Lean gives it, and nothing a person
// recorded about it, in the data passed (not hidden on the page).
const compare = comparisonInputs("compare", [evenAdd], { only: ["Toy.PaperSpec.thm_even_add"] });
const text = JSON.stringify(compare);
for (const absent of ["SYNTHETIC-NOTE", "SYNTHETIC-AUTHOR", "SYNTHETIC-REVIEW", "SYNTHETIC-REVIEWER", "A-Referee",
                      "work/even-add.json", "totalised", "spec_review", "def_reviews", "a.referee", "status_code", "blockers"]) {
  assert.ok(!text.includes(absent), `${absent} is not in Compare's inputs`);
}
assert.equal(compare.annotations, null);
for (const k of ["symbols", "correspondence", "reviews", "findings", "work", "status", "clauses", "decls"]) {
  assert.ok(!(k in compare.passages[0]), `the paper side has no ${k}`);
}
const cl = compare.formal.clauses[0];
assert.deepEqual(Object.keys(cl).sort(), ["defs", "name", "spec", "statement", "witness", "witness_record"]);
assert.deepEqual(cl.statement, evenAdd.clauses[0].statement, "the statement is complete, as Lean gave it");
assert.deepEqual(compare.formal.decls, evenAdd.decls, "its declarations can be loaded");
// The reader's own view keeps the records, attributed, for the reader and the later stage.
const reading = comparisonInputs("reading", [evenAdd]);
assert.equal(reading.formal, evenAdd);
assert.deepEqual(reading.annotations.symbols, evenAdd.symbols);
assert.equal(reading.annotations.work, "work/even-add.json");
const after = comparisonInputs("after", [evenAdd], { only: ["No.Such"] });
assert.deepEqual(after.formal.clauses, [], "the later stage shows the unit's declarations only");
assert.equal(after.formal.correspondence.note, "SYNTHETIC-NOTE: the author's reading");
assert.throws(() => comparisonInputs("anything", [evenAdd]));

// A proof step: its linked Lean and the declarations of its route, without the route's note, the
// step's review or its correspondence.
const step = { ...claim("toy", "T_eq_bound-range"), };
step.step = { ...step.step, correspondence: { coverage: "full", note: "SYNTHETIC-STEP-NOTE" },
  route: { ...(step.step.route || {}), note: "SYNTHETIC-ROUTE-NOTE", by: "SYNTHETIC-AUTHOR", links: step.step.route?.links || [{ name: "Toy.Acceptance.thm_bound" }] } };
const stepCompare = comparisonInputs("compare", [step]);
assert.ok(!JSON.stringify(stepCompare).includes("SYNTHETIC"), "nothing written about the step");
assert.deepEqual(stepCompare.formal.step.route.links.map((l) => l.name), step.step.route.links.map((l) => l.name));
assert.deepEqual(stepCompare.passages[0].step, { unit: step.step.unit, parent: { id: step.step.parent.id, number: step.step.parent.number } });
assert.ok(stepCompare.passages[0].context_tex, "the step's context in the proof is paper content");

// A definition of its own (a review unit): its record without its review in an independent stage.
const isEven = decl(evenAdd.decls["Toy.IsEven"]);
assert.ok(isEven.review?.current?.length);
assert.equal(declSide(isEven, "compare").review, undefined);
assert.equal(declSide(isEven, "read").review, undefined);
assert.equal(declSide(isEven, "reading"), isEven);
assert.deepEqual(comparisonInputs("compare", [], { decls: [{ name: "Toy.IsEven", key: "k", review: "x" }] }).definitions, [{ name: "Toy.IsEven", key: "k" }]);
// Reverse references without the claims a declaration is linked to.
const users = { users: [{ name: "A.b", claims: ["T:x"] }], applications: [{ id: "1", caller: "A.b", caller_claims: ["T:x"] }] };
assert.ok(!JSON.stringify(usersSide(users, "compare")).includes("T:x"));
assert.equal(usersSide(users, "reading"), users);
assert.equal(paperSide(null), null);
assert.equal(formalSide(null), null);

// Rows: each object with the conditions on it alone, each other condition, the conclusion.
// Objects the readable statement introduces together share a row (#70): `∀ a b : ℕ`.
const st = evenAdd.clauses[0].statement;
assert.deepEqual(statementRows(st).map((r) => r.key), ["b:0", "b:2", "b:3", "c"]);
assert.deepEqual(statementRows(st)[0].heads, [0, 1], "a and b share one row");
const { readable: _, ...unread } = st;
assert.deepEqual(statementRows(unread).map((r) => r.key), ["b:0", "b:1", "b:2", "b:3", "c"], "without a readable statement, a row each");
const supplied = claim("structure", "P_thm_supplied").links[0].statement;
assert.deepEqual(statementRows(supplied).map((r) => [r.key, r.members]), [["b:0", []], ["b:1", [2]], ["c", []]],
  "the assumption on s alone is s's");
const layout = claim("structure", "P_thm_layout").links[0].statement;
assert.equal(statementRows(layout).length, 8, "seven rows of the prefix, then the conclusion");

// An alignment's target is drawn at the row that holds it: a variable, a binder, a sub-term, a
// property of an object, the conclusion; the whole declaration has no row of its own.
assert.equal(rowOfTarget(st, { decl: "x", var: 0 }), "b:0");
assert.equal(rowOfTarget(st, { decl: "x", var: "b" }), "b:0", "b is in the row it shares with a");
assert.equal(rowOfTarget(st, { decl: "x", binder: 3 }), "b:3");
assert.equal(rowOfTarget(st, { decl: "x", conclusion: true }), "c");
assert.equal(rowOfTarget(st, { decl: "x", at: "/1/1/1/1/1" }), "c", "a + b is in the conclusion");
assert.equal(rowOfTarget(st, { decl: "x", at: "/1/1/0" }), "b:2", "the first hypothesis");
assert.equal(rowOfTarget(st, { decl: "x" }), null);
assert.equal(rowOfTarget(st, { decl: "x", at: "/no/such" }), null);
assert.equal(rowOfId(supplied, "/1#start:/0/1"), "b:1", "a property of s is s's row");
const produced = claim("structure", "P_thm_produced").links[0].statement;
const sId = produced.tree.args[0].args[0].id;
assert.equal(rowOfId(produced, sId + "#start:/"), rowOfTarget(produced, { decl: "x", var: "s" }), "the produced s's property is s's row");

// A row's exact Lean is the exact statement's own sub-term.
assert.equal(exactPart(st, "/1/1/1/1").text, "Toy.IsEven (a + b)");
assert.deepEqual(exactPart(st, "/1/1/1/1").terms.map((t) => t.id), ["/1/1/1/1", "/1/1/1/1/1"]);
assert.equal(exactPart(st, "/missing"), null);

// How a carried property stands, as the statement view words it: given, produced, inside an
// assumption, or local to the clause that contains it.
assert.equal(propertyStanding(supplied, "/1#start:/").how, "given");
assert.equal(propertyStanding(produced, sId + "#start:/").how, "produced");
const assumed = claim("structure", "P_thm_assumed").links[0].statement;
const inside = JSON.stringify(spineOf(assumed)[0].logic).match(/"id":"([^"]*#start:\/)"/)[1];
assert.equal(propertyStanding(assumed, inside).how, "inside", "the assumed solution's property stays in the assumption");
const own = spineOf(assumed).find((b) => b.role === "exists").properties.find((p) => p.field === "start").type.id;
assert.equal(propertyStanding(assumed, own).how, "produced", "the result's own solution is produced");
assert.equal(propertyStanding(supplied, "/no#such:/"), null);

// Paired rows from an alignment source, published or the open workspace's: a target in a
// definition is that definition's row; one in a declaration not shown is kept apart.
const reading1 = {
  workspace: "ws-1", requirements: [{ local_id: "even", form: "definition", text: "n is even when n = 2k" }],
  fragments: [{ id: "p1", requirement: "even", role: "statement", state: "accepted", region: { text: "A printed sentence." } },
              { id: "p2", requirement: "even", role: "later use", state: "accepted", region: { text: "A later use." } }],
  alignments: [{ id: "a1", requirements: ["even"], relation: "corresponds", lean: [{ decl: "Toy.IsEven" }], created_by: "llm:m" },
               { id: "a2", requirements: ["even"], fragments: ["p1", "gone"], relation: "corresponds",
                 lean: [{ decl: "Toy.PaperSpec.thm_even_add", var: 0 }, { decl: "Toy.PaperSpec.thm_even_add", conclusion: true }], created_by: "llm:m" },
               { id: "a3", requirements: [], relation: "additional assumption", lean: [{ decl: "Other.decl" }], created_by: "llm:m" },
               { id: "a4", requirements: ["even"], relation: "corresponds", lean: [], created_by: "llm:m" }] };
const src = alignmentSource(reading1, { who: "the model", from: "published" });
assert.deepEqual(src.alignments.map((a) => a.id), ["a1", "a2", "a3"], "an alignment without a target has no row");
assert.deepEqual(src.alignments[0].passages.map((f) => f.id), ["p1"], "its requirement's governing passages, not a later use");
assert.deepEqual(src.alignments[1].passages.map((f) => f.id ?? null), ["p1", "gone"]);
assert.equal(src.alignments[1].passages[1].missing, true, "a named passage no longer kept says so");
const rows = alignedRows(src, { "Toy.IsEven": null, "Toy.PaperSpec.thm_even_add": st });
assert.deepEqual([...rows.at.keys()], ["Toy.IsEven::top", "Toy.PaperSpec.thm_even_add::b:0", "Toy.PaperSpec.thm_even_add::c"]);
assert.equal(rows.at.get("Toy.PaperSpec.thm_even_add::b:0")[0].alignment.id, "a2", "one alignment, several rows");
assert.deepEqual(rows.elsewhere.map((a) => a.id), ["a3"]);
assert.equal(alignmentSource({ alignments: [] }, { who: "x", from: "y" }), null);

// A pin belongs to one claim, project and build: another project or revision has its own pins.
const a = pinScope({ release: "r1", evidence: "e1" }, "T:x", "o/a");
assert.ok(sameScope(a, pinScope({ release: "r1", evidence: "e1" }, "T:x", "o/a")));
assert.ok(!sameScope(a, pinScope({ release: "r1", evidence: "e1" }, "T:x", "o/b")), "another project");
assert.ok(!sameScope(a, pinScope({ release: "r2", evidence: "e1" }, "T:x", "o/a")), "another release");
assert.ok(!sameScope(a, pinScope({ release: "r1", evidence: "e2" }, "T:x", "o/a")), "another build");
assert.ok(!sameScope(a, pinScope({ release: "r1", evidence: "e1" }, "T:y", "o/a")), "another claim");

console.log("ok   comparison inputs and rows");
