// The main results a workspace saves, in the reader's words (src/lib/mainresults.js): who saved
// them, when and against what, each entry with what it stands for and its problem, as the engine
// gives them under `machinechecked view` (`impact.workspace_selection`) and in a published audit
// (`published_work.main_results`), and the selection an edit sends back. Runs in Node:
// `node tests/mainresults.test.mjs`.
import assert from "node:assert/strict";
import { entriesOf, suggestedOf, savedText, pinsText, withAdded, without, sameSelection, editable } from "../src/lib/mainresults.js";

const claims = [{ id: "S:thm:main", number: "Theorem 1" }, { id: "S:lem:none", number: "Lemma 7" }];
// As `GET /api/main-results` answers for a workspace that saves three.
const saved = { basis: "saved", workspace: "ws-1", reviewer: "human:A-Auditor", by: "human:A-Auditor", at: "2026-11-03T00:00:00Z",
  pins: { release: "v-synthetic", commit: "c".repeat(40) },
  selected: [{ claim: "S:thm:main" }, { decl: "Syn.step", module: "Syn.Main", build: "built" }, { claim: "S:lem:none" }, { decl: "Syn.retired", module: "Syn.Main", build: "built" }],
  problems: [{ decl: "Syn.retired", module: "Syn.Main", problem: "Syn.retired is not declared in Syn.Main in this build" }],
  unlinked_claims: ["S:lem:none"],
  main_results: [{ name: "Syn.main", claims: ["S:thm:main"], selected: ["S:thm:main"] }, { name: "Syn.step", claims: [], selected: ["named"] },
                 { name: "Syn.retired", claims: [], selected: ["named"] }] };
assert.equal(savedText(saved), "Saved by human:A-Auditor on 2026-11-03T00:00:00Z, against release v-synthetic, project commit ccccccc.");
assert.equal(pinsText({}), "");
assert.deepEqual(entriesOf(saved, claims).map((e) => [e.label, e.detail, e.problem]), [
  ["Theorem 1 (S:thm:main)", "its linked Lean: Syn.main", null],
  ["Syn.step", "in Syn.Main", null],
  ["Lemma 7 (S:lem:none)", "no Lean is linked to it", null],
  ["Syn.retired", "in Syn.Main", "Syn.retired is not declared in Syn.Main in this build"]]);
// A published selection names no traced declaration: a claim stands for its linked Lean.
const pub = { workspace: "ws-1", mode: "informed", reviewer: { id: "human:A-Auditor", name: "A Auditor" }, by: "human:A-Auditor", at: "2026-11-03T00:00:00Z",
  pins: { release: "v-synthetic" }, selected: [{ claim: "S:thm:main" }, { claim: "S:thm:gone" }],
  problems: [{ claim: "S:thm:gone", problem: "no claim S:thm:gone in release v-synthetic" }] };
assert.deepEqual(entriesOf(pub, claims).map((e) => [e.label, e.detail, e.problem]), [
  ["Theorem 1 (S:thm:main)", "stands for its linked Lean", null], ["S:thm:gone", null, "no claim S:thm:gone in release v-synthetic"]]);
assert.equal(savedText(pub), "Saved by human:A-Auditor on 2026-11-03T00:00:00Z, against release v-synthetic.");
// The suggestion, with the claims each declaration is linked to.
assert.deepEqual(suggestedOf({ basis: "suggested", main_results: [{ name: "Syn.main", claims: ["S:thm:main"] }, { name: "Syn.other", claims: [] }] }, claims)
  .map((e) => [e.label, e.detail]), [["Syn.main", "linked to Theorem 1 (S:thm:main)"], ["Syn.other", null]]);
// An edit sends the whole selection back as the engine takes it: added, without one, or none.
assert.deepEqual(withAdded(saved, "Lemma 3"), [{ claim: "S:thm:main" }, { decl: "Syn.step", module: "Syn.Main" }, { claim: "S:lem:none" },
                                               { decl: "Syn.retired", module: "Syn.Main" }, "Lemma 3"]);
assert.deepEqual(withAdded(null, "Lemma 3"), ["Lemma 3"]);
assert.deepEqual(without(saved, 0), [{ decl: "Syn.step", module: "Syn.Main" }, { claim: "S:lem:none" }, { decl: "Syn.retired", module: "Syn.Main" }]);
assert.deepEqual(editable({ decl: "Syn.x", build: "built" }), { decl: "Syn.x" });
assert.ok(sameSelection(saved, { ...saved, at: "later", problems: [] }));
assert.ok(!sameSelection(saved, { selected: saved.selected.slice(1) }));
assert.ok(sameSelection(null, { basis: "suggested" }), "nothing saved on either side");
console.log("mainresults.test.mjs: ok");
