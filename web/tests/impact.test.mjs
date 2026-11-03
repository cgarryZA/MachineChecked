// A finding's impact at a use in words (src/lib/impact.js): the engine's words for its outcome
// and for the difference it concerns, and the impacts a workspace records at one application
// only. Runs in Node: `node tests/impact.test.mjs`.
import assert from "node:assert/strict";
import { differenceText, impactHead, impactsAt, impactView } from "../src/lib/impact.js";
import { findingView } from "../src/lib/findings.js";

const pin = { finding: "f-diff", claim: "P:lem:inverse", requirement: "r1", feature: "derivative order", paper: "m + 4", lean: "n + 5", outcome: "difference" };
assert.equal(differenceText(pin), "the derivative order difference f-diff on P:lem:inverse r1 (paper m + 4; Lean n + 5)");
// Published without the source text or the Lean: no expressions.
assert.equal(differenceText({ finding: "f-diff", claim: "P:lem:inverse", requirement: "r1", feature: "derivative order" }),
  "the derivative order difference f-diff on P:lem:inverse r1");
assert.equal(impactHead({ outcome: "not sufficient" }), "At a use: not sufficient");

const use = (id, caller, n) => ({ id, ref: { app: { callee: "Syn.inverse_estimate", caller, id: `app:${caller}:${n}` } } });
const view = { claims: {
  "P:thm:construct": { evidence: [use("e-use", "Syn.construct", 0)], findings: [
    { id: "f-imp", impact: { difference: pin, use: "e-use", outcome: "sufficient for this use", why: "finite" } }] },
  "P:thm:sharp": { evidence: [use("e-sharp", "Syn.sharp", 0)], findings: [
    { id: "f-sharp", impact: { difference: pin, use: "e-sharp", outcome: "not sufficient", why: "four" } }] },
} };
const v = impactView(view.claims["P:thm:construct"].findings[0], view.claims["P:thm:construct"].evidence);
assert.equal(v.use, "Syn.inverse_estimate applied in Syn.construct (app:Syn.construct:0)");
assert.deepEqual(impactsAt(view, "Syn.inverse_estimate", "app:Syn.construct:0").map((x) => [x.finding.id, x.outcome]), [["f-imp", "sufficient for this use"]]);
assert.deepEqual(impactsAt(view, "Syn.inverse_estimate", "app:Syn.third:0"), []);
assert.deepEqual(impactsAt(view, "Syn.other", "app:Syn.construct:0"), []);
// A comparison row shows the impact as its heading, with the use and the difference it concerns.
const set = { id: "ws:w", who: "A. Auditor", from: "published", mode: "informed", evidence: view.claims["P:thm:construct"].evidence,
  compositions: [], counterexamples: [], requirements: new Map([["r2", { local_id: "r2", form: "condition", text: "some finite number" }]]),
  governing: new Map() };
const shown = findingView({ set, targets: [], finding: { ...view.claims["P:thm:construct"].findings[0], requirement: "r2", state: "submitted",
  evidence: ["e-use"], currency: { state: "current", changes: [] } } }, {}, "P:thm:construct");
assert.equal(shown.head, "At a use: sufficient for this use");
assert.equal(shown.impact.use, "Syn.inverse_estimate applied in Syn.construct (app:Syn.construct:0)");
assert.equal(shown.impact.why, "finite");
assert.equal(shown.requirement.text, "some finite number");
console.log("impact.test.mjs: ok");
