// Writing a composition in the reader (src/lib/workspace.js): the form's draft, and the `put` the
// engine checks, for a new composition and for the next revision of a saved one, whose fields it
// sends back as they are. Runs in Node: `node tests/compose.test.mjs`.
import assert from "node:assert/strict";
import { newComposition, newStep, newObligation, compositionDraft, compositionOp, withoutStep, stepEvidence, linkEvidence } from "../src/lib/workspace.js";

// A composition as `workspace.view` gives it (engine-added obligation and computed fields too).
const saved = { id: "c-1", kind: "composition", claim: "T:thm:bound", rev: 3, coverage: "partial", statement: "T_n ≤ n² for every n",
  steps: [{ id: "s1", establishes: "2 T_n = n(n+1)", uses: ["e-tri"], substitutions: [{ variable: "n", value: "n", in: "e-tri" }] },
          { id: "s2", establishes: "T_n ≤ n²", requirements: ["c"], uses: ["e-bound"], after: ["s1"], inference: "2 T_n = n² + n ≤ 2 n²" }],
  identifications: [{ left: { step: "s1", object: "n" }, right: { step: "s2", object: "n" }, relation: "same object", how: "evidence", evidence: ["e-conn"] }],
  obligations: [{ id: "o1", kind: "local to global", text: "extend it", state: "open", connection: "e-conn" },
                { id: "o2", kind: "constant dependence", text: "C = 1 before n", state: "discharged", by: { steps: ["s2"] } }],
  bridge: { theorem: "Toy.Acceptance.thm_bound", target: "Toy.PaperSpec.thm_bound", target_fingerprint: "x", checked_at: "t" },
  evidence: ["e-tri", "e-bound", "e-conn"], currency: { state: "current", changes: [] }, basis: "reviewed_composition", gaps: {}, complete: false };
const op = compositionOp(compositionDraft(saved), "T:thm:bound");
assert.equal(op.op, "put");
assert.equal(op.id, "c-1");
assert.equal(op.base_rev, 3, "the next revision of the one shown");
const fields = ["id", "kind", "claim", "statement", "steps", "identifications", "obligations", "coverage"];
assert.deepEqual(Object.fromEntries(fields.map((k) => [k, op.record[k]])), Object.fromEntries(fields.map((k) => [k, saved[k]])),
  "a saved composition is sent back as it is");
assert.deepEqual(op.record.bridge, { theorem: "Toy.Acceptance.thm_bound", target: "Toy.PaperSpec.thm_bound" }, "the bridge by its names; the engine keeps its pins");
assert.ok(!("basis" in op.record) && !("evidence" in op.record), "nothing computed is written");

// A new one: a fresh id, the empty optional fields left out.
const draft = newComposition();
draft.steps[0].establishes = "x";
draft.steps[0].uses = ["e-1"];
draft.steps.push(newStep(draft.steps));
assert.equal(draft.steps[1].id, "s2");
draft.steps[1].after = ["s1"];
draft.obligations.push(newObligation(draft.obligations));
const fresh = compositionOp(draft, "P:thm:x");
assert.match(fresh.record.id, /^c-\w+$/);
assert.ok(!("base_rev" in fresh));
assert.deepEqual(fresh.record.steps, [{ id: "s1", establishes: "x", uses: ["e-1"] }, { id: "s2", establishes: "", after: ["s1"] }]);
assert.deepEqual(fresh.record.obligations, [{ id: "o1", kind: "compatible witnesses", text: "", state: "open" }]);
assert.ok(!("statement" in fresh.record) && !("bridge" in fresh.record) && !("coverage" in fresh.record) && !("identifications" in fresh.record));
// Removing a step drops the choices that name it; an identification that names it stays.
const d = compositionDraft(saved);
const less = withoutStep(d, "s1");
assert.deepEqual(less.steps.map((s) => [s.id, s.after]), [["s2", []]]);
assert.equal(less.identifications.length, 1);
// What can be cited: a step rests on Lean results; an identification also on connections.
const ev = [{ id: "e-1", ref: { decl: "A" } }, { id: "e-2", ref: { connection: {} } }, { id: "e-3", ref: { decl: "B" }, role: "rejected" },
            { id: "e-4", ref: { paper: { quote: "q" } } }, { id: "e-5", ref: { app: { callee: "C" } } }];
assert.deepEqual(stepEvidence(ev).map((e) => e.id), ["e-1", "e-5"]);
assert.deepEqual(linkEvidence(ev).map((e) => e.id), ["e-1", "e-2", "e-5"]);
console.log("compose.test.mjs: ok");
