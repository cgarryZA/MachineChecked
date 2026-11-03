// A connection between two objects in words (src/lib/connections.js): the same words the engine
// gives it (`connections.text`), from a workspace's record and from a published one that leaves
// out the Lean text. Runs in Node: `node tests/connections.test.mjs`.
import assert from "node:assert/strict";
import { connectionText } from "../src/lib/connections.js";
import { refText } from "../src/lib/findings.js";

const onDomain = { relation: "equal on a domain", from: { decl: "Syn.u" }, to: { decl: "Syn.v" },
  domain: "the interval [0, T]", conditions: ["T > 0"], support: [{ decl: "Syn.u_eq_v_on" }] };
assert.equal(connectionText(onDomain), "Syn.u and Syn.v are equal on the interval [0, T], when T > 0, by Syn.u_eq_v_on");
assert.equal(refText({ connection: onDomain }), connectionText(onDomain));

const witness = { relation: "shared witness", from: { decl: "Syn.exists_pq", var: 0, id: "/", name: "x" },
  to: { decl: "Syn.exists_pq", var: 0, id: "/", name: "x" } };
assert.equal(connectionText(witness), "x of Syn.exists_pq and x of Syn.exists_pq are one witness");
assert.equal(connectionText({ relation: "projection", from: { decl: "Syn.prepare" }, to: { decl: "Syn.correct", var: 0, name: "W" }, field: "Syn.Profile.W" }),
  "W of Syn.correct is the field Syn.Profile.W of Syn.prepare");

// Published without the Lean: the ends by declaration and number, the scope left out.
assert.equal(connectionText({ relation: "equal as classes", from: { decl: "Syn.f", var: 1 }, to: { app: { callee: "Syn.g", caller: "Syn.main" }, param: "h" },
  support: [{ fact: { decl: "Syn.main", name: "hfg" } }] }),
  "variable 1 of Syn.f and h of Syn.g applied in Syn.main are equal as classes, modulo an equivalence, by hfg inside the proof of Syn.main");
console.log("connections.test.mjs: ok");
