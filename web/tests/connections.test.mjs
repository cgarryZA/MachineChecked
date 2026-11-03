// A connection between two objects in words (src/lib/connections.js): the same words the engine
// gives it (`connections.text`), from a workspace's record and from a published one that leaves
// out the Lean text; where the comparison places each beside its rows, and the chain from one
// object to another. Runs in Node: `node tests/connections.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { connectionText, connectionEntries, placeConnections, endKey, endRow, linkedObjects, chainBetween } from "../src/lib/connections.js";
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

// -- beside the comparison's rows -----------------------------------------------------------
const here = path.dirname(fileURLToPath(import.meta.url));
const claim = (prefix) => {
  const d = path.join(here, "fixtures", "toy", "data", "claims");
  return JSON.parse(fs.readFileSync(path.join(d, fs.readdirSync(d).find((f) => f.startsWith(prefix))), "utf8"));
};
const BOUND = "Toy.PaperSpec.thm_bound", ADD = "Toy.PaperSpec.thm_even_add";
const statements = { [BOUND]: claim("T_thm_bound").clauses[0].statement, [ADD]: claim("T_thm_even-add").clauses[0].statement, "Toy.triangle": null };

// An object is identified by its binder (or sub-term), never by its name; a declaration as a
// whole is not one of its variables.
assert.equal(endKey({ decl: BOUND, var: 0, id: "/", name: "C" }), endKey({ decl: BOUND, var: 0, id: "/", name: "K" }));
assert.notEqual(endKey({ decl: BOUND, var: 0, id: "/" }), endKey({ decl: BOUND }));
assert.notEqual(endKey({ decl: BOUND, var: 0, id: "/" }), endKey({ decl: BOUND, var: 1, id: "/1" }));
assert.notEqual(endKey({ app: { callee: "Toy.f", id: "app:Toy.g:0" }, param: "x" }), endKey({ app: { callee: "Toy.f", id: "app:Toy.g:1" }, param: "x" }));

// Each end at the row where its statement binds the object, or holds the sub-term; a variable
// introduced together with another shares its row.
assert.equal(endRow({ decl: BOUND, var: 0 }, statements[BOUND]), "b:0");
assert.equal(endRow({ decl: BOUND, var: 1 }, statements[BOUND]), "b:1");
assert.equal(endRow({ decl: BOUND, at: statements[BOUND].conclusion.id }, statements[BOUND]), "c");
assert.equal(endRow({ decl: ADD, var: 1 }, statements[ADD]), "b:0", "a and b share a row");
assert.equal(endRow({ decl: BOUND }, statements[BOUND]), null, "a declaration as a whole");

const rec = (id, connection, extra = {}) => ({ id, kind: "evidence", role: "supports", ref: { connection }, currency: { state: "current", changes: [] }, ...extra });
const cC = { relation: "equal", from: { decl: BOUND, var: 0, id: "/", name: "C" }, to: { decl: "Toy.Other.k", var: 0, name: "k" }, support: [{ decl: "Toy.Other.k_eq" }] };
const cT = { relation: "definitional", from: { decl: BOUND, at: statements[BOUND].conclusion.id, target: "Toy.triangle n ≤ C * (n * n)" }, to: { decl: "Toy.triangle" }, unfolds: [{ decl: "Toy.triangle" }] };
const cApp = { relation: "projection", field: "1", from: { app: { callee: "Toy.Other.k", caller: BOUND, id: "app:Toy.Other.k:0" }, param: "h" }, to: { decl: "Toy.Other.k", var: 0, name: "k" } };
const cStale = { relation: "shared witness", from: { decl: BOUND, var: 0, id: "/", name: "C" }, to: { decl: ADD, var: 0, id: "/", name: "a" } };
const cAway = { relation: "coercion", from: { decl: "Toy.Far.x" }, to: { decl: "Toy.Far.y" } };
const published = [{ workspace: "ws-1", reviewer: { id: "human:A-Auditor", name: "A Auditor" }, evidence: [
  rec("e-c", cC), rec("e-t", cT), rec("e-no", cAway, { role: "rejected" }), rec("e-old", cStale, { currency: { state: "stale", changes: [{ decl: BOUND, var: 0, reason: "Toy.PaperSpec.thm_bound: variable 0 is now K : Nat, not C : Nat" }] } }),
  rec("e-far", cAway, { currency: { state: "unchecked", changes: [], reason: "the module is not built" } }), { id: "e-decl", kind: "evidence", role: "supports", ref: { decl: BOUND } }] }];
const own = { workspace: "ws-2", reviewer: "human:B-Auditor", evidence: [rec("e-app", cApp, { role: "candidate" })] };
const entries = connectionEntries({ published, own, computed: [cT], who: (r) => r.name });
assert.deepEqual(entries.map((e) => [e.id, e.origin, e.by, e.state]), [
  ["e-c", "recorded", "A Auditor", "current"], ["e-t", "recorded", "A Auditor", "current"], ["e-old", "recorded", "A Auditor", "stale"],
  ["e-far", "recorded", "A Auditor", "unchecked"], ["e-app", "recorded", "your investigation (human:B-Auditor)", "current"],
  [null, "computed", null, null]], "a rejected connection is not shown, a declaration reference is not a connection, computed ones are marked");
assert.equal(new Set(entries.map((e) => e.key)).size, entries.length, "each once");

const placed = placeConnections(entries, statements);
const at = (key) => (placed.at.get(key) || []).map((x) => [x.entry.id ?? x.entry.origin, x.sides.join("+")]);
assert.deepEqual(at(BOUND + "::b:0"), [["e-c", "from"]]);
assert.deepEqual(at(BOUND + "::c"), [["e-t", "from"], ["computed", "from"]]);
assert.deepEqual(at("Toy.triangle::top"), [["e-t", "to"], ["computed", "to"]], "a definition's whole row");
assert.deepEqual(at(BOUND + "::b:1"), []);
assert.deepEqual(placed.claim.map((e) => e.id), ["e-old"], "a connection that changed is never placed at a row");
assert.deepEqual(placed.elsewhere.map((e) => e.id), ["e-far", "e-app"], "nor one whose objects are not shown");
assert.ok(![...placed.at.values()].flat().some((x) => x.entry.id === "e-old"));

// The chain from one object to another: the fewest connections, a changed one only when there
// is no other, and none between objects nothing joins.
const C = endKey(cC.from), k = endKey(cC.to), h = endKey(cApp.from), a = endKey(cStale.to);
assert.deepEqual(linkedObjects(entries, C).map((o) => o.key), [k, a, h]);
const ch = chainBetween(entries, C, h);
assert.deepEqual(ch.steps.map((s) => [s.entry.id, endKey(s.from), endKey(s.to)]), [["e-c", C, k], ["e-app", k, h]]);
assert.deepEqual(ch.sources, ["published:ws-1", "workspace:ws-2"]);
const direct = rec("e-short", { relation: "equal", from: cC.from, to: cApp.from, support: [{ decl: "Toy.Other.k_eq" }] }, { currency: { state: "stale", changes: [] } });
const withStale = connectionEntries({ published: [{ ...published[0], evidence: [...published[0].evidence, direct] }], own });
assert.deepEqual(chainBetween(withStale, C, h).steps.map((s) => s.entry.id), ["e-c", "e-app"], "current connections first");
assert.deepEqual(chainBetween(withStale.filter((e) => e.id !== "e-c"), C, h).steps.map((s) => [s.entry.id, s.entry.state]), [["e-short", "stale"]]);
assert.deepEqual(chainBetween(entries, a, C).steps.map((s) => s.entry.id), ["e-old"], "a changed connection is the only chain, and says so");
assert.equal(chainBetween(entries, C, endKey(cAway.from)), null);
assert.equal(chainBetween(entries, C, C), null);
console.log("connections.test.mjs: ok");
