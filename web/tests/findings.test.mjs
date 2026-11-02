// Findings at the clauses they explain (src/lib/findings.js): which row of the comparison each
// finding is drawn at, through the alignments of its own reading only; what stays on the whole
// claim; and the words each is shown with. On the toy audit's claims as the engine wrote them and
// on synthetic statements. Runs in Node: `node tests/findings.test.mjs`.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { correspondenceFields, reviewFields, findingSets, placeFindings, findingView, targetRole, rowWords } from "../src/lib/findings.js";
import { comparisonInputs } from "../src/lib/comparison.js";
import { readingWords } from "../src/lib/coverage.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const claim = (prefix) => {
  const d = path.join(here, "fixtures", "toy", "data", "claims");
  return JSON.parse(fs.readFileSync(path.join(d, fs.readdirSync(d).find((f) => f.startsWith(prefix))), "utf8"));
};
const cur = { state: "current", changes: [] };
const who = (r) => r?.name || r?.id;
const keysOf = (placed) => Object.fromEntries([...placed.at].map(([k, es]) => [k, es.map((e) => e.finding.id)]));
// A published reading in the form `published_work.py` writes it.
const reading = (workspace, name, records) => ({ workspace, mode: "informed",
  reviewer: { id: "human:" + name.replace(/ /g, "-"), kind: "human", name, identity: "self-declared" },
  requirements: [], fragments: [], alignments: [], findings: [], evidence: [], compositions: [], counterexamples: [], ...records });
const req = (local_id, form, text) => ({ id: "q-" + local_id, kind: "requirement", local_id, form, text, depth: 0, currency: cur });
const align = (id, requirement, lean, relation = "corresponds", currency = cur) =>
  ({ id, kind: "alignment", requirements: [requirement], relation, lean, created_by: "human:SYNTHETIC", currency });
const finding = (id, requirement, extra = {}) => ({ id, kind: "finding", ...(requirement ? { requirement } : {}), state: "submitted",
  submitted_at: "2026-10-20T00:00:00Z", created_by: "human:SYNTHETIC", evidence: [], in_force: true, currency: cur, ...extra });

// -- an author's review: its `Correspondence:` field, same line or several, to the next field ----
assert.deepEqual(correspondenceFields("Manuscript: the bound. Correspondence: both clauses. Verdict: faithful."), ["both clauses."]);
assert.deepEqual(correspondenceFields("Manuscript: the bound. Propositions: both. Correspondence: item by item. Verdict: faithful."), ["item by item."]);
const evenAdd = claim("T_thm_even-add");
const reviewText = evenAdd.clauses[0].spec_review.current[0].text;
const [field] = correspondenceFields(reviewText);
assert.match(field, /^both quantifiers, both hypotheses and the conclusion appear as printed\. The\nwitness `thm_even_add_hypotheses`/);
assert.ok(field.endsWith("which are nonzero."), "the note as written, over its lines");
assert.ok(!/Verdict|faithful/.test(field), "the following verdict is not part of it");
assert.deepEqual(correspondenceFields("Correspondence: the first part.\n\nIt goes on here.\n\n## Theorem 2\n\nCorrespondence: next."), ["the first part.\n\nIt goes on here.", "next."],
  "a field ends at the next section");
assert.deepEqual(correspondenceFields("**Correspondence:** in bold. **Verdict:** faithful."), ["in bold."]);
assert.deepEqual(correspondenceFields("The type is `C : Nat`. No field here."), []);
assert.deepEqual(correspondenceFields(null), []);
// Each review's field at the whole proposition it read, with its reviewer and provenance.
const fields = reviewFields(evenAdd.clauses);
assert.deepEqual([...fields.keys()], ["Toy.PaperSpec.thm_even_add::top"]);
assert.deepEqual({ ...fields.get("Toy.PaperSpec.thm_even_add::top")[0], text: null },
  { spec: "Toy.PaperSpec.thm_even_add", text: null, by: "a.referee", kind: "human", provenance: "self-declared", current: true });
const stale = reviewFields([{ spec: "S.p", spec_review: { current: [], stale: [{ by: "x", text: "Correspondence: an earlier reading." }] } }]);
assert.equal(stale.get("S.p::top")[0].current, false, "a review of an earlier proposition keeps its association, and says so");
assert.equal(reviewFields(claim("T_thm_triangle").clauses).size, 0, "no field, no note");

// -- the added `0 < n` of the corrected predecessor clause is local ----------------------------
const pred = claim("T_prop_pred");
const [printed, corrected] = pred.clauses;
const predStatements = { [printed.spec]: printed.statement, [corrected.spec]: corrected.statement };
const predReading = reading("ws-pred", "A Auditor", {
  requirements: [req("all", "for every", "every natural number n"), req("pos", "assumption", "n is positive")],
  alignments: [align("al-pos", "pos", [{ decl: corrected.spec, binder: 1, target: "h1 : 0 < n" }], "additional assumption"),
               align("al-all", "all", [{ decl: printed.spec, var: 0, target: "n" }, { decl: corrected.spec, var: 0, target: "n" }])],
  findings: [finding("f-pos", "pos", { difference: { feature: "additional assumption", paper: "every natural number n", lean: "0 < n",
                                                     outcome: "difference", transport: "the printed clause, refuted at n = 0" },
                                       note: "The correction adds 0 < n; the printed clause has no such condition." }),
             finding("f-whole", null, { coverage: "changed", basis: "direct", note: "The corrected clause states the claim for positive n." })] });
const predPlaced = placeFindings(findingSets([predReading], null, { who }), predStatements);
assert.deepEqual(keysOf(predPlaced), { [corrected.spec + "::b:0"]: ["f-pos"] }, "at the row of n and its condition, in the corrected clause only");
assert.deepEqual(predPlaced.claim.map((e) => e.finding.id), ["f-whole"], "a finding on no requirement is the whole claim's");
const pos = findingView(predPlaced.at.get(corrected.spec + "::b:0")[0], predStatements, pred.id);
assert.equal(pos.lean[0].role, "an assumption");
assert.equal(pos.lean[0].relation, "an additional assumption of the Lean");
assert.equal(pos.head, "An additional assumption difference: a difference");
assert.equal(pos.requirement.text, "n is positive");
assert.equal(pos.who, "A Auditor");
assert.equal(findingView(predPlaced.claim[0], predStatements, pred.id).head, readingWords("changed", "direct"));
assert.equal(rowWords(predStatements, corrected.spec + "::b:0"), "the row of n in prop_pred_pos");

// -- the natural output constant of the uniform bound, in its output role ----------------------
const bound = claim("T_thm_bound");
const bst = bound.clauses[0].statement, bspec = bound.clauses[0].spec;
assert.equal(targetRole(bst, { var: 0 }), "an object the statement produces", "C is produced, not assumed");
assert.equal(targetRole(bst, { binder: 0 }), "the type of an object the statement produces");
assert.equal(targetRole(bst, { var: "n" }), "an object the statement is given");
assert.equal(targetRole(bst, { conclusion: true }), "the conclusion");
assert.equal(targetRole(bst, { at: bst.conclusion.id }), "part of the conclusion");
const cReading = reading("ws-c", "A Auditor", {
  requirements: [req("c", "there is", "a constant C, independent of n")],
  alignments: [align("al-c", "c", [{ decl: bspec, binder: 0, target: "C : Nat" }])],
  findings: [finding("f-c", "c", { note: "C : Nat is the type of the constant the statement produces: an output, not a hypothesis." })] });
const cPlaced = placeFindings(findingSets([cReading], null, { who }), { [bspec]: bst });
assert.deepEqual(keysOf(cPlaced), { [bspec + "::b:0"]: ["f-c"] });
const cv = findingView(cPlaced.at.get(bspec + "::b:0")[0], { [bspec]: bst }, bound.id);
assert.equal(cv.lean[0].role, "the type of an object the statement produces");
assert.equal(cv.head, "C : Nat is the type of the constant the statement produces: an output, not a hypothesis.", "a note alone heads its finding");
assert.equal(cv.note, null, "and is not repeated");

// -- a synthetic derivative estimate: the output and inverse clauses match, one input order differs
const id = (s) => "/1/1/1/1" + s;
const seg = (t, v) => (v == null ? { t } : { t, var: v });
const derivative = {
  binders: [
    { name: "f", role: "forall", binder: "explicit", id: "/", type: { id: "/0", text: "Nat → Nat", segments: [seg("Nat → Nat")] } },
    { name: "g", role: "forall", binder: "explicit", id: "/1", type: { id: "/1/0", text: "Nat → Nat", segments: [seg("Nat → Nat")] } },
    { name: "m", role: "forall", binder: "explicit", id: "/1/1", type: { id: "/1/1/0", text: "Nat", segments: [seg("Nat")] } },
    { name: "C", role: "forall", binder: "explicit", id: "/1/1/1", type: { id: "/1/1/1/0", text: "Nat", segments: [seg("Nat")] } },
    { name: "hin", role: "hypothesis", binder: "explicit", id: id(""), type: { id: id("/0"), text: "Est.DerivBound f (m + 5) C",
      segments: [seg("Est.DerivBound "), seg("f", 0), seg(" ("), seg("m", 2), seg(" + 5) "), seg("C", 3)] } },
    { name: "hinv", role: "hypothesis", binder: "explicit", id: id("/1"), type: { id: id("/1/0"), text: "Est.IsInverse g f",
      segments: [seg("Est.IsInverse "), seg("g", 1), seg(" "), seg("f", 0)] } }],
  conclusion: { id: id("/1/1"), text: "Est.OutBound f m C ∧ Est.OutBound g m C",
    segments: [seg("Est.OutBound "), seg("f", 0), seg(" "), seg("m", 2), seg(" "), seg("C", 3), seg(" ∧ "), seg("Est.OutBound "), seg("g", 1), seg(" "), seg("m", 2), seg(" "), seg("C", 3)],
    terms: [{ id: id("/1/1/0/1"), from: 0, to: 6 }, { id: id("/1/1/1"), from: 7, to: 13 }] } };
const est = { "Est.bound": derivative };
const no = (paper) => ({ feature: "derivative order", paper, lean: paper, outcome: "no difference", why: "the same order" });
const estReading = reading("ws-est", "A Auditor", {
  requirements: [req("in", "assumption", "the first m + 4 derivatives of f are bounded by C"), req("inv", "assumption", "g is the inverse of f"),
                 req("out", "conclusion", "f is bounded at order m"), req("out-inv", "conclusion", "g is bounded at order m")],
  alignments: [align("al-in", "in", [{ decl: "Est.bound", binder: 4, target: "hin : Est.DerivBound f (m + 5) C" }], "changed"),
               align("al-inv", "inv", [{ decl: "Est.bound", binder: 5 }]),
               align("al-out", "out", [{ decl: "Est.bound", at: id("/1/1/0/1"), target: "Est.OutBound f m C" }]),
               align("al-out-inv", "out-inv", [{ decl: "Est.bound", at: id("/1/1/1"), target: "Est.OutBound g m C" }])],
  findings: [finding("f-in", "in", { difference: { feature: "derivative order", paper: "m + 4", lean: "m + 5", outcome: "difference" },
                                     note: "Input bound uses derivatives through m+5; the paper uses m+4." }),
             finding("f-inv", "inv", { coverage: "full", basis: "direct", note: "The inverse is the paper's." }),
             finding("f-out", "out", { difference: no("m") }),
             finding("f-out-inv", "out-inv", { difference: no("m") })] });
const estPlaced = placeFindings(findingSets([estReading], null, { who }), est);
assert.deepEqual(keysOf(estPlaced), { "Est.bound::b:4": ["f-in"], "Est.bound::b:5": ["f-inv"], "Est.bound::c": ["f-out", "f-out-inv"] },
  "each at its own clause, together on one comparison");
assert.deepEqual(estPlaced.claim, []);
const estViews = [...estPlaced.at.values()].flat().map((e) => findingView(e, est, "E:thm:est"));
assert.deepEqual(estViews.map((v) => v.difference?.outcome ?? null), ["difference", null, "no difference", "no difference"],
  "only the input order differs");
assert.deepEqual(estViews.map((v) => v.lean[0].role), ["an assumption", "an assumption", "part of the conclusion", "part of the conclusion"]);
assert.equal(estViews[0].note, "Input bound uses derivatives through m+5; the paper uses m+4.");

// -- one coverage, three bases, three readings that stay distinct ------------------------------
const basisReading = reading("ws-basis", "A Auditor", {
  requirements: [req("out", "conclusion", "f is bounded at order m")],
  alignments: [align("al-out", "out", [{ decl: "Est.bound", conclusion: true }])],
  evidence: [{ id: "e1", kind: "evidence", role: "supports", ref: { decl: "Est.bound" }, currency: cur }],
  compositions: [{ id: "c-bridge", kind: "composition", coverage: "full", basis: "checked_bridge", steps: [], evidence: ["e1"],
                   bridge_check: { state: "checked", reasons: [] }, gaps: { uncovered: [], open: [] }, currency: cur },
                 { id: "c-arg", kind: "composition", coverage: "full", basis: "reviewed_composition", steps: [], evidence: ["e1"],
                   gaps: { uncovered: [], open: [] }, currency: cur }],
  findings: [finding("f-direct", "out", { coverage: "full", basis: "direct", evidence: ["e1"] }),
             finding("f-arg", "out", { coverage: "full", basis: "reviewed_composition", composition: "c-arg", evidence: ["e1"] }),
             finding("f-bridge", "out", { coverage: "full", basis: "checked_bridge", composition: "c-bridge" }),
             finding("f-own-bridge", "out", { coverage: "full", basis: "reviewed_composition", recorded_basis: "checked_bridge",
                                              bridge: { theorem: "Est.no_bridge", target: "Est.Spec" }, basis_reason: ["Lean finds no such theorem"],
                                              bridge_check: { state: "unchecked", reasons: ["Lean finds no such theorem"] } })] });
const heads = placeFindings(findingSets([basisReading], null, { who }), est).at.get("Est.bound::c").map((e) => findingView(e, est, "E:x"));
assert.deepEqual(heads.map((v) => v.head), [readingWords("full", "direct"), readingWords("full", "reviewed_composition"),
                                             readingWords("full", "checked_bridge"), readingWords("full", "reviewed_composition")]);
assert.equal(new Set(heads.slice(0, 3).map((v) => v.head)).size, 3, "the same coverage, three bases");
assert.match(heads[3].recorded, /^Recorded as a checked bridge \(Est\.no_bridge for Est\.Spec\); no bridge Lean checks now: Lean finds no such theorem\.$/,
  "a composition whose declarations Lean proves does not become a checked bridge");
assert.deepEqual(heads[0].lines.map((l) => l.label), ["Stated by"]);

// -- a covered uniqueness statement and a separately assessed intermediate estimate -------------
const unique = { binders: [{ name: "x", role: "exists", binder: "explicit", id: "/1", type: { id: "/1/0", text: "Nat", segments: [seg("Nat")] } }],
  conclusion: { id: "/1/1", text: "U.P x ∧ ∀ (y : Nat), U.P y → y = x", segments: [seg("U.P "), seg("x", 0), seg(" ∧ ∀ (y : Nat), U.P y → y = "), seg("x", 0)] } };
const thm = { "U.unique": unique }, stepLean = { "U.unique": unique };
const thmReading = reading("ws-u", "A Auditor", {
  requirements: [req("uniq", "conclusion", "any other solution is x")],
  alignments: [align("al-uniq", "uniq", [{ decl: "U.unique", conclusion: true }])],
  findings: [finding("f-cover", null, { coverage: "full", basis: "direct", note: "Existence and uniqueness, as printed." }),
             finding("f-uniq", "uniq", { coverage: "full", basis: "direct" })] });
const stepReading = reading("ws-u", "A Auditor", {
  requirements: [req("est", "conclusion", "the intermediate estimate (2)")],
  alignments: [], findings: [finding("f-est", "est", { verdict: "holds, with a gap in the argument", note: "The estimate needs n ≥ 1." })] });
const onTheorem = placeFindings(findingSets([thmReading], null, { who }), thm);
const onStep = placeFindings(findingSets([stepReading], null, { who }), stepLean);
assert.deepEqual(onTheorem.claim.map((e) => e.finding.id), ["f-cover"]);
assert.deepEqual(keysOf(onTheorem), { "U.unique::c": ["f-uniq"] });
assert.ok(!JSON.stringify([...onTheorem.at.values(), onTheorem.claim].flat().map((e) => e.finding.id)).includes("f-est"),
  "the step's finding is not the theorem's");
assert.deepEqual(onStep.claim.map((e) => e.finding.id), ["f-est"], "it stays with the proof step, which aligns it with no Lean");
assert.equal(findingView(onStep.claim[0], stepLean, "U:eq:2").head, "The printed step: holds, with a gap in the argument");
assert.equal(findingView(onTheorem.claim[0], thm, "U:thm").head, readingWords("full", "direct"));

// -- several readers at one clause, each attributed; one finding at several rows, written once --
const second = reading("ws-pred-2", "B Auditor", {
  requirements: [req("pos2", "assumption", "the predecessor of a positive n")],
  alignments: [align("al-pos2", "pos2", [{ decl: corrected.spec, binder: 1 }, { decl: corrected.spec, conclusion: true }], "additional assumption")],
  findings: [finding("f-pos2", "pos2", { coverage: "changed", basis: "direct" })] });
const both = placeFindings(findingSets([predReading, second], null, { who }), predStatements);
const atPos = both.at.get(corrected.spec + "::b:0");
assert.deepEqual(atPos.map((e) => [e.finding.id, e.set.who, e.first]), [["f-pos", "A Auditor", true], ["f-pos2", "B Auditor", true]]);
assert.deepEqual(both.at.get(corrected.spec + "::c").map((e) => [e.finding.id, e.first]), [["f-pos2", false]],
  "a later row names the finding instead of repeating it");
assert.deepEqual(both.at.get(corrected.spec + "::c")[0].rows, [corrected.spec + "::b:0", corrected.spec + "::c"]);

// -- stale associations: never rebound to another expression ----------------------------------
const staleOf = (changes) => ({ state: "stale", changes });
const staleReading = reading("ws-stale", "A Auditor", {
  requirements: [req("a", "assumption", "x"), req("b", "assumption", "y"), req("c", "assumption", "z"), req("d", "assumption", "w")],
  alignments: [align("al-a", "a", [{ decl: corrected.spec, binder: 1 }], "corresponds", staleOf([{ decl: corrected.spec, was: "1", now: "2" }])),
               align("al-b", "b", [{ decl: corrected.spec, binder: 1 }], "corresponds", staleOf([{ fragment: "p-gone", was: "accepted", now: "missing" }])),
               align("al-c", "c", [{ decl: corrected.spec, binder: 1 }], "corresponds", staleOf([{ decl: "Toy.helper", used_by: corrected.spec, was: "1", now: "2" }])),
               align("al-d", "d", [{ decl: corrected.spec, at: "/no/such/term" }])],
  findings: [finding("f-a", "a", { currency: staleOf([{ decl: corrected.spec, reason: "Toy.PaperSpec.prop_pred_pos changed" }]) }),
             finding("f-b", "b"), finding("f-c", "c"), finding("f-d", "d"),
             finding("f-old", "a", { in_force: false })] });
const stalePlaced = placeFindings(findingSets([staleReading], null, { who }), predStatements);
assert.deepEqual(stalePlaced.claim.map((e) => [e.finding.id, e.targets[0].state]), [["f-a", "changed"], ["f-d", "missing"]],
  "its statement changed, or it has no such part: kept on the whole claim, with its recorded target");
assert.deepEqual(keysOf(stalePlaced), { [corrected.spec + "::b:0"]: ["f-b", "f-c"] }, "a changed passage or definition keeps the row");
const fa = findingView(stalePlaced.claim[0], predStatements, pred.id);
assert.equal(fa.stale, true);
assert.deepEqual(fa.why, ["Toy.PaperSpec.prop_pred_pos changed"]);
assert.equal(fa.lean[0].role, null, "no role is read off a statement that changed");
assert.equal(findingView(stalePlaced.at.get(corrected.spec + "::b:0")[0], predStatements, pred.id).lean[0].stale, true);
assert.ok(!JSON.stringify(stalePlaced).includes("f-old"), "a superseded finding is not drawn at a row");
// Another project or claim gives other statements: an alignment into Lean the comparison does not
// show stays on the whole claim.
const elsewhere = placeFindings(findingSets([predReading], null, { who }), { [printed.spec]: printed.statement });
assert.deepEqual(elsewhere.claim.map((e) => [e.finding.id, e.targets.map((t) => t.state)]), [["f-pos", ["elsewhere"]], ["f-whole", []]]);

// -- the open investigation: its own findings, drafts included, at its own alignments ----------
const own = { workspace: "ws-own", reviewer: "human:Me",
  findings: [finding("f-mine", "even", { state: "draft", coverage: "partial" })], evidence: [], compositions: [],
  reading: { requirements: [{ id: "r1", local_id: "even", form: "definition", text: "n is even when n = 2k",
                              fragments: { governing: [{ id: "p1", requirement: "even", role: "statement", region: { file: "toy.tex", start_line: 12, text: "SYNTHETIC-PASSAGE" } }] } }],
             alignments: [{ id: "a1", requirements: ["even"], relation: "corresponds", lean: [{ decl: "Toy.IsEven" }], created_by: "human:Me", currency: cur }] } };
const mine = findingSets([], own, { who });
assert.deepEqual(mine.map((s) => [s.id, s.who, s.mode]), [["workspace:ws-own", "your investigation (human:Me)", "informed"]]);
const minePlaced = placeFindings(mine, { "Toy.IsEven": null });
assert.deepEqual(keysOf(minePlaced), { "Toy.IsEven::top": ["f-mine"] });
const mv = findingView(minePlaced.at.get("Toy.IsEven::top")[0], { "Toy.IsEven": null }, "T:def:even");
assert.equal(mv.state, "draft");
assert.deepEqual(mv.passages.map((p) => [p.where, p.text]), [["toy.tex:12", "SYNTHETIC-PASSAGE"]]);

// -- Independent Compare: no prior authored finding, alignment or review note in its data -------
const recorded = { ...evenAdd, work: "work/SYNTHETIC.json" };
const compare = comparisonInputs("compare", [recorded], { only: [evenAdd.clauses[0].spec] });
assert.equal(reviewFields(compare.formal.clauses).size, 0, "the author's review is not in Compare's data");
assert.ok(!JSON.stringify(compare).includes("Correspondence:"));
assert.deepEqual(findingSets([predReading], own, { blind: true, who }), [], "nor a published or an open reading's findings");
assert.equal(compare.annotations, null);
// The reader, the claim page and the later stage receive them.
assert.equal(reviewFields(comparisonInputs("reading", [recorded]).formal.clauses).size, 1);
assert.equal(reviewFields(comparisonInputs("after", [recorded]).formal.clauses).size, 1);
assert.equal(findingSets([predReading], own, { who }).length, 2);

console.log("ok   findings at their clauses");
