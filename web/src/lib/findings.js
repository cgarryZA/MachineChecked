// Findings at the paper and Lean clauses they explain, for the shared comparison
// (Comparison.svelte). A finding is a record of an auditor's workspace (`workspace.py`): a
// published reading of the audit (`published_work.py`) or the reading of the investigation open
// in this page. It sits at a row of the Lean only through an explicit association its own
// reading records: the finding names a requirement, and an alignment of that reading names a
// variable, binder, sub-term or the conclusion of a declaration the comparison shows. A finding
// that names no requirement, a requirement aligned with nothing, or a target whose statement has
// changed since it was recorded stays at the level of the whole claim; it is never moved to
// another row, nor to an expression with similar text.
//
// The words for coverage and basis are the engine's (`coverage.js`). Nothing here is a status,
// and an independent stage of the review protocol is given none of it (`findingSets`).

import { alignmentSource, rowOfTarget, statementRows } from "./comparison.js";
import { spineOf, conclusionOf } from "./tree.js";
import { compositionView, findingCoverageView, recordedBasisText } from "./coverage.js";

// -- correspondence fields of a review --------------------------------------------------------

// A field of a review's text: a label of one to three words, capitalised, then a colon, at the
// start of a line or after the end of a sentence ("Verdict: faithful."), in bold or not.
const FIELD = /(^|\n|[.!?;][ \t]+)[ \t]*(?:\*\*|__)?([A-Z][A-Za-z-]*(?: [A-Za-z-]+){0,2}):(?:\*\*|__)?(?=[ \t\n]|$)/g;
// What ends a field besides the next one: a section of the review file (a heading, a rule, a
// marker).
const SECTION = /\n[ \t]*(#{1,6}[ \t]|-{3,}[ \t]*(\n|$)|\*{3,}[ \t]*(\n|$)|<!--)/;

// The `Correspondence:` fields of a review's text, each as written: from the label to the next
// field, on the same line or a later one, or to the end of its section. Empty when it has none.
export function correspondenceFields(text) {
  if (typeof text !== "string" || !text) return [];
  const fields = [...text.matchAll(FIELD)].map((m) => ({
    label: m[2], start: m.index + m[1].length, body: m.index + m[0].length }));
  const out = [];
  fields.forEach((f, i) => {
    if (f.label !== "Correspondence") return;
    let end = i + 1 < fields.length ? fields[i + 1].start : text.length;
    const cut = text.slice(f.body, end).search(SECTION);
    if (cut >= 0) end = f.body + cut;
    const body = text.slice(f.body, end).trim();
    if (body) out.push(body);
  });
  return out;
}

// The correspondence fields of the reviews of each clause's proposition, by the row they belong
// to: a review of a proposition reads the whole of it (`<spec>::top`). Each keeps its reviewer,
// provenance and whether the review is of the current proposition; a review of an earlier one
// keeps its association and says so.
export function reviewFields(clauses) {
  const at = new Map();
  for (const cl of clauses || []) {
    const sr = cl?.spec_review;
    if (!cl?.spec || !sr) continue;
    const list = [];
    for (const [state, rs] of [["current", sr.current], ["stale", sr.stale]]) {
      for (const r of rs || []) {
        for (const text of correspondenceFields(r?.text)) {
          list.push({ spec: cl.spec, text, by: r.by || null, kind: r.kind || null,
                      provenance: r.provenance || null, current: state === "current" });
        }
      }
    }
    if (list.length) at.set(cl.spec + "::top", list);
  }
  return at;
}

// -- the findings of each reading -----------------------------------------------------------

// The readings whose findings a comparison may show: each published reading of the audit, and
// the investigation open in this page (`own`: its view of the claim, `workspace.view.claims[id]`,
// with its workspace id and reviewer). None in an independent stage of the review protocol.
// `who` words a published reading's reviewer, as the comparison names alignments' authors.
export function findingSets(published, own, { blind = false, who = (r) => r?.name || r?.id } = {}) {
  if (blind) return [];
  const out = [];
  for (const rd of published || []) {
    const s = setOf(rd, { who: who(rd.reviewer || {}), from: "published", mode: rd.mode || null,
                          id: "published:" + (rd.workspace || "") });
    if (s) out.push(s);
  }
  if (own) {
    const rd = { ...(own.reading || {}), findings: own.findings, evidence: own.evidence,
                 compositions: own.compositions, counterexamples: own.counterexamples,
                 workspace: own.workspace };
    const s = setOf(rd, { who: "your investigation (" + (own.reviewer || "") + ")", from: "workspace",
                          mode: "informed", id: "workspace:" + (own.workspace || "") });
    if (s) out.push(s);
  }
  return out;
}

function setOf(rd, meta) {
  const findings = (rd?.findings || []).filter((f) => f && f.in_force !== false);
  if (!findings.length) return null;
  const aligned = alignmentSource(rd, meta)?.alignments || [];
  const raw = new Map((rd.alignments || []).map((a) => [a.id, a]));
  // The passages that govern each requirement: a published reading lists its accepted passages,
  // an open investigation groups them under their requirement.
  const governing = new Map();
  const govern = (lid, f) => { if (!governing.has(lid)) governing.set(lid, []); governing.get(lid).push(f); };
  for (const f of rd.fragments || []) {
    if (f.role !== "later use" && (f.state ?? "accepted") === "accepted") govern(f.requirement, f);
  }
  for (const r of rd.requirements || []) for (const f of r.fragments?.governing || []) govern(r.local_id, f);
  return { ...meta, findings, governing,
           requirements: new Map((rd.requirements || []).map((r) => [r.local_id, r])),
           alignments: aligned.map((a) => ({ ...a, changes: raw.get(a.id)?.currency?.changes || [] })),
           evidence: rd.evidence || [], compositions: rd.compositions || [],
           counterexamples: rd.counterexamples || [] };
}

// A change of an alignment's currency that concerns the paper's side.
const paperChange = (c) => "fragment" in c || "region" in c || "passage" in c;

// Where a target of an alignment is now, in the statements a comparison shows: `here` with its
// row, `elsewhere` (a declaration the comparison does not show), `changed` (its declaration's
// statement changed since it was recorded: the identity it names may now be another expression)
// or `missing` (the statement has no such part now).
function placeTarget(a, t, statements) {
  if (!Object.hasOwn(statements, t.decl)) return { state: "elsewhere" };
  if (a.changes.some((c) => !paperChange(c) && c.decl === t.decl && !c.used_by)) return { state: "changed" };
  const st = statements[t.decl];
  const sub = t.conclusion || t.at != null || t.binder != null || t.var != null;
  if (!st || !sub) return { state: "here", row: "top" };
  const row = rowOfTarget(st, t) ?? innerRow(st, t);
  return row ? { state: "here", row } : { state: "missing" };
}

// The row of a variable bound inside the statement (after the binders that open it): the
// conclusion's, or that of the hypothesis whose own tree binds it.
function innerRow(st, t) {
  if (t.var == null || !/^\d+$/.test(String(t.var))) return null;
  const i = Number(t.var);
  const binds = (n) => !!n && typeof n === "object" && ((n.var === i && (n.op === "exists" || n.op === "forall"))
    || (n.args || []).some(binds));
  if (binds(conclusionOf(st))) return st.conclusion ? "c" : null;
  const rows = statementRows(st);
  const k = spineOf(st).findIndex((b) => binds(b.logic));
  return k < 0 ? null : rows.find((r) => r.head === k || r.members.includes(k))?.key ?? null;
}

// The rows of a comparison, in the order it draws them: for each declaration shown, the
// declaration as a whole, then its statement's rows.
function rowOrder(statements) {
  const out = [];
  for (const [name, st] of Object.entries(statements)) {
    out.push(name + "::top");
    if (st) for (const r of statementRows(st)) out.push(name + "::" + r.key);
  }
  return out;
}

// Each finding of `sets` where the comparison draws it: `at`, the row key (`<decl>::<row>`, or
// `<decl>::top` for a whole declaration) to its entries, in the order the readings are given;
// `claim`, the findings of the whole claim. An entry is `{set, finding, targets, first}`: every
// target the finding's alignments name, each with where it is now (`placeTarget`) and its
// alignment, and whether this is the first row the finding is drawn at, where its explanation is
// printed; later rows name it.
export function placeFindings(sets, statements) {
  const order = new Map(rowOrder(statements).map((k, i) => [k, i]));
  const at = new Map(), claim = [];
  for (const set of sets || []) {
    for (const f of set.findings) {
      const mine = f.requirement ? set.alignments.filter((a) => a.requirements.some((r) => r.local_id === f.requirement)) : [];
      const targets = mine.flatMap((a) => a.lean.map((t) => ({ t, alignment: a, ...placeTarget(a, t, statements) })));
      const rows = [...new Set(targets.filter((x) => x.state === "here").map((x) => x.t.decl + "::" + x.row))]
        .sort((a, b) => (order.get(a) ?? 1e9) - (order.get(b) ?? 1e9));
      const entry = (first) => ({ set, finding: f, targets, first, rows });
      if (!rows.length) { claim.push(entry(true)); continue; }
      rows.forEach((key, i) => {
        if (!at.has(key)) at.set(key, []);
        at.get(key).push(entry(i === 0));
      });
    }
  }
  return { at, claim };
}

// -- one finding in words ---------------------------------------------------------------------

const OUTCOME = { open: "not yet decided", difference: "a difference", resolved: "resolved", "no difference": "no difference" };
const MODE = { informed: "informed investigation", independent: "independent review" };
const RELATION = { corresponds: "corresponds", "additional assumption": "an additional assumption of the Lean",
                   changed: "changed", "alternative representation": "an alternative representation" };
const ROLE = { statement: "the statement", "quantifier domain": "domain of a quantifier",
               "constant dependence": "allowed dependence of a constant", "standing assumption": "standing assumption",
               definition: "definition used", "earlier choice": "choice made earlier", "cited result": "result cited",
               context: "context", "later use": "later use", "proposed correction": "proposed correction" };

const day = (t) => (typeof t === "string" ? t.slice(0, 10) : "");

// What a binder of a statement is, in words: an object the statement is given, one it produces,
// or an assumption.
function binderWords(b) {
  if (!b) return null;
  if (b.role === "exists") return "an object the statement produces";
  if (b.role === "hypothesis" || (b.role === "instance" && b.supplies === "proposition")) return "an assumption";
  if (b.role === "instance") return "an instance the statement is given";
  return "an object the statement is given";
}

// What an object bound inside the statement is, from where the probe places it.
function innerWords(n) {
  if (n.scope === "assumed") return "an object inside an assumption";
  if (n.scope === "denied") return "an object inside a negation";
  if (n.scope === "alternative") return "an object inside one alternative";
  return n.op === "exists" ? "an object the statement produces" : "any value, in the part it belongs to";
}

// The role in its statement of what a target names: the conclusion, an object the statement is
// given or produces (or that object's type), an assumption, or a sub-term of one of them. Null for
// a whole declaration or a definition.
export function targetRole(st, t) {
  if (!st || !t) return null;
  if (t.conclusion) return "the conclusion";
  const binders = spineOf(st);
  const index = (v) => (/^\d+$/.test(String(v)) ? Number(v) : binders.findIndex((b) => b.name === v));
  if (t.var != null || t.binder != null) {
    const i = index(t.var ?? t.binder);
    let words = binderWords(binders[i]);
    if (!words && i >= binders.length) {
      const walk = (n) => (!n || typeof n !== "object" ? null
        : n.var === i && (n.op === "exists" || n.op === "forall") ? n : (n.args || []).map(walk).find(Boolean) || walk(n.logic));
      const n = walk(conclusionOf(st)) || binders.map((b) => walk(b.logic)).find(Boolean);
      words = n ? innerWords(n) : null;
    }
    if (!words) return null;
    return t.binder != null && binders[i]?.role !== "hypothesis" ? "the type of " + words : words;
  }
  if (t.at != null) {
    const id = String(t.at);
    const inside = (p) => p != null && (id === p || id.startsWith(p + "/") || id.startsWith(p + "=") || id.startsWith(p + "#"));
    if (inside(st.conclusion?.id)) return "part of the conclusion";
    const b = binders.find((x) => inside(x.type?.id));
    return b ? "part of " + binderWords(b) : null;
  }
  return null;
}

// A row of a comparison in words (`<decl>::<row>`): its first object or assumption, the
// conclusion, or the declaration as a whole.
export function rowWords(statements, key) {
  const cut = key.lastIndexOf("::");
  const decl = key.slice(0, cut), row = key.slice(cut + 2);
  const short = decl.split(".").pop();
  if (row === "top") return `${short} as a whole`;
  if (row === "c") return `the conclusion of ${short}`;
  const st = statements?.[decl];
  const r = st ? statementRows(st).find((x) => x.key === row) : null;
  const b = r ? spineOf(st)[r.head ?? r.members[0]] : null;
  return b ? `the row of ${b.name || "an assumption"} in ${short}` : `a row of ${short}`;
}

// Where a passage of the paper is, in words.
function whereOf(f, claimId) {
  if (f.missing) return "a passage no longer kept";
  if (f.passage) return f.passage.claim === claimId ? "this claim's passage" : `the passage of ${f.passage.claim}`;
  const r = f.region || {};
  if (!r.file) return "a passage of the paper";
  return `${r.file}:${r.start_line}${r.end_line && r.end_line !== r.start_line ? "–" + r.end_line : ""}`;
}

// A piece of evidence in words, as the published reading names it.
export function refText(r) {
  if (r?.app) return `${r.app.callee} applied in ${r.app.caller || "a proof"}${r.app.result ? ", giving " + r.app.result : ""}`;
  if (r?.certificate) {
    const c = r.certificate;
    return `${c.theorem}: Lean ${c.result === "checked" ? "checks" : "does not check"} that its type is ${c.certifies === "refutes" ? "the negation of" : "exactly"} ${c.target}; it certifies that proposition only`;
  }
  if (r?.fact) return `${r.fact.name || r.fact.head || "a fact"}${r.fact.type ? " : " + r.fact.type : ""}, inside the proof of ${r.fact.decl}${r.fact.basis ? " (" + r.fact.basis + ")" : ""}`;
  if (r?.decl) return r.decl;
  if (r?.source) return r.source.file ? r.source.file + (r.source.line ? ":" + r.source.line : "") : "a Lean source location";
  return r?.paper?.quote ? `“${r.paper.quote}”` : "a passage of the paper";
}

// One entry of `placeFindings` as the comparison words it: the headline (its coverage and basis
// in the engine's words, else what it records), the lines that explain the basis, the difference
// or the printed step's verdict, the paper side (the requirement and its passages) and the Lean
// side (each target with its role and relation, and where it is now), its author, reading and
// state, and the evidence, composition and counterexamples it rests on.
export function findingView(entry, statements, claimId) {
  const { set, finding: f, targets } = entry;
  const cited = (f.evidence || []).map((id) => set.evidence.find((e) => e.id === id)).filter(Boolean);
  const comp = f.composition ? set.compositions.find((c) => c.id === f.composition) || null : null;
  const cv = comp
    ? { headline: compositionView({ coverage: f.coverage, basis: f.basis, bridge_check: comp.bridge_check }).headline, lines: [], tone: "reading" }
    : findingCoverageView({ ...f, refs: cited.map((e) => e.ref?.decl).filter(Boolean) });
  const d = f.difference || null;
  const diffWords = d ? `${/^[aeiou]/i.test(d.feature || "") ? "An" : "A"} ${d.feature} difference: ${OUTCOME[d.outcome] || d.outcome}` : null;
  const stepWords = f.verdict ? "The printed step: " + f.verdict : null;
  // A finding that records only a note is headed by the note itself.
  const head = cv?.headline || stepWords || diffWords || f.note || "A finding recorded without a note";
  const req = f.requirement ? set.requirements.get(f.requirement) || { local_id: f.requirement, missing: true } : null;
  // The passages of its requirement that its alignments name, else those that govern it.
  const named = [...new Set(targets.map((x) => x.alignment))].flatMap((a) => a.passages)
    .filter((p) => p.missing || p.requirement === f.requirement);
  const passages = [];
  for (const p of named.length ? named : set.governing.get(f.requirement) || []) {
    if (passages.some((q) => q.id === p.id)) continue;
    passages.push({ id: p.id, where: whereOf(p, claimId), text: p.region?.text || null,
                    role: ROLE[p.role] || p.role || null, scope: p.scope || null,
                    whole: !!p.passage && p.passage.claim === claimId, missing: !!p.missing });
  }
  const lean = targets.map(({ t, alignment, state }) => ({
    decl: t.decl, text: t.target || null, state,
    role: state === "here" || state === "missing" ? targetRole(statements[t.decl], t) : null,
    relation: RELATION[alignment.relation] || alignment.relation, alignment: alignment.id,
    stale: alignment.stale }));
  const stale = f.currency?.state === "stale";
  const why = [...new Set((f.currency?.changes || []).map((c) => c.reason).filter(Boolean))];
  return {
    id: f.id, head, tone: cv?.tone || (d?.outcome === "difference" ? "warning" : f.verdict ? "reading" : "note"),
    lines: cv?.lines || [], recorded: comp ? null : recordedBasisText(f),
    composition: comp, difference: d ? { ...d, words: diffWords === head ? null : diffWords } : null,
    verdict: stepWords && stepWords !== head ? stepWords : null, note: f.note && f.note !== head ? f.note : null, clause: f.clause || null,
    question: f.coverage === "unresolved" ? f.question || null : null,
    requirement: req, passages, lean,
    by: f.created_by || null, who: set.who, from: set.from, mode: MODE[set.mode] || set.mode || null,
    state: f.state === "draft" ? "draft" : "submitted", at: day(f.submitted_at),
    stale, unchecked: f.currency?.state === "unchecked", why,
    supersedes: f.supersedes || null, reason: f.reason || null,
    evidence: cited.map((e) => ({ id: e.id, text: refText(e.ref), role: e.role, stale: e.currency?.state === "stale" })),
    counterexamples: (f.counterexamples || []).map((c) => set.counterexamples.find((x) => x.id === (c.id || c))).filter(Boolean),
  };
}
