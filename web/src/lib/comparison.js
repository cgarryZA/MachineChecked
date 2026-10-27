// The content one Paper | Lean comparison may show, and how it is laid out in rows.
//
// The controller that shows a comparison (the reader, the claim page, the review page) builds an
// explicit view of what it allows (`comparisonInputs`), and the renderer (Comparison.svelte) draws
// that view only. The review protocol's stages keep their boundaries in this data, not in what is
// hidden on the page:
//
//   read     the paper's passages and their source context only;
//   compare  the paper's passages with the unit's complete Lean as Lean extracted it: statements
//            with their scope tree, carried properties and expansions, definitions with their
//            equations and source. No association a person made (symbol links, workspace
//            alignments, correspondence notes, reviews, findings, a proof step's route, the paper
//            definition a declaration is linked to, the claims a declaration is linked to) and no
//            review of a declaration is in it;
//   after    once the verdict is recorded: the records as the reader shows them;
//   reading  the reader and the claim page: the claim as the engine wrote it.

import { spineOf, conclusionOf } from "./tree.js";

export const MODES = ["reading", "read", "compare", "after"];
export const independent = (mode) => mode === "read" || mode === "compare";

const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o?.[k] !== undefined).map((k) => [k, o[k]]));

// The paper's side of a claim record: the printed passage, where it is, and its context in the
// paper (a proof step's surrounding proof). Nothing a person wrote about it.
const PAPER = ["id", "number", "heading", "title", "paper", "kind", "anchor", "excerpt", "statement_tex",
  "source_matches", "context_tex", "context_cut", "release"];
export function paperSide(c) {
  if (!c) return null;
  const out = pick(c, PAPER);
  if (c.step) out.step = { unit: c.step.unit, ...(c.step.parent ? { parent: pick(c.step.parent, ["id", "number"]) } : {}) };
  return out;
}

// The Lean side of a claim record as Lean gives it: the clauses' statements and definitions, a
// zero-configuration claim's linked declarations, a proof step's linked declarations, and the
// keys of the declarations their statements use (to load them). `only` keeps the declarations a
// review unit is about.
const CLAUSE = ["name", "label", "spec", "statement", "defs", "witness"];
const LINK = ["name", "kind", "statement", "definition", "path", "range", "module", "repository"];
export function formalSide(c, only = null) {
  if (!c) return null;
  const keep = (n) => !only || only.includes(n);
  const out = { id: c.id, mode: c.mode, decls: { ...(c.decls || {}) } };
  if (c.clauses) {
    out.clauses = c.clauses.filter((cl) => keep(cl.spec) || (cl.defs || []).some(keep))
      .map((cl) => ({ ...pick(cl, CLAUSE), ...(cl.witness_record?.type ? { witness_record: { type: cl.witness_record.type } } : {}) }));
  }
  if (c.links) out.links = c.links.filter((l) => keep(l.name)).map((l) => pick(l, LINK));
  if (c.step) {
    out.step = { links: (c.step.links || []).filter((l) => keep(l.name)).map((l) => pick(l, LINK)) };
    // The declarations a proof step's route names, without what was written about them.
    if (c.step.route?.links?.length) out.step.route = { links: c.step.route.links.map((l) => pick(l, LINK)) };
  }
  return out;
}

// A claim record restricted to the declarations a review unit is about, with its other fields.
function restricted(c, only) {
  if (!c || !only) return c;
  const keep = (n) => only.includes(n);
  return { ...c,
    ...(c.clauses ? { clauses: c.clauses.filter((cl) => keep(cl.spec) || (cl.defs || []).some(keep)) } : {}),
    ...(c.links ? { links: c.links.filter((l) => keep(l.name)) } : {}),
    ...(c.step ? { step: { ...c.step, links: (c.step.links || []).filter((l) => keep(l.name)) } } : {}) };
}

// A declaration record of the shared store as a stage allows it: without its review in an
// independent stage.
export function declSide(rec, mode) {
  if (!rec || !independent(mode)) return rec;
  const { review, ...rest } = rec;
  return rest;
}

// Reverse references as a stage allows them: in an independent stage, without the claims a
// declaration is linked to (an author's association).
export function usersSide(entry, mode) {
  if (!entry || !independent(mode)) return entry;
  const strip = (u) => { const { claims, caller_claims, ...rest } = u; return rest; };
  const out = { ...entry };
  for (const k of ["users", "further", "applications"]) if (Array.isArray(entry[k])) out[k] = entry[k].map(strip);
  return out;
}

// The inputs of a comparison. `claims` are the claim records shown (the first is the claim; any
// other states the same unit elsewhere), `only` the declarations of a review unit, `decls` a
// unit's definitions that have no claim of their own ([{name, key}]).
export function comparisonInputs(mode, claims, { only = null, decls = [] } = {}) {
  if (!MODES.includes(mode)) throw new Error(`not a comparison mode: ${mode}`);
  const shown = (claims || []).filter(Boolean);
  const blind = independent(mode);
  return {
    mode,
    passages: shown.map((c) => (blind ? paperSide(c) : c)),
    formal: mode === "read" || !shown[0] ? null : blind ? formalSide(shown[0], only) : restricted(shown[0], only),
    definitions: mode === "read" ? [] : decls.map((d) => ({ name: d.name, key: d.key })),
    // What a person recorded about the claim: symbol links and the published workspace records.
    annotations: blind || !shown[0] ? null : { symbols: shown[0].symbols || [], work: shown[0].work || null },
  };
}

// The rows of a statement: each object that opens it with the conditions on it alone (`members`),
// each other condition, then the conclusion. A condition that directly follows an object of a
// "for all", or that object's other conditions, and mentions that object only, is that object's;
// nothing moves, and nothing is grouped with a "there is". Row keys: `b:<i>` (binder i opens the
// row) and `c` (the conclusion).
const varsOf = (pp) => new Set((pp?.segments || []).filter((x) => x.var != null).map((x) => x.var));
export function statementRows(st) {
  const binders = spineOf(st);
  const out = [];
  binders.forEach((b, i) => {
    if (b.role === "forall" || b.role === "exists") { out.push({ key: "b:" + i, head: i, members: [] }); return; }
    const last = out.at(-1), vs = varsOf(b.type);
    if (last?.head != null && binders[last.head].role === "forall" && vs.size === 1 && vs.has(last.head)) last.members.push(i);
    else out.push({ key: "b:" + i, head: null, members: [i] });
  });
  if (st?.conclusion) out.push({ key: "c", head: null, members: [], conclusion: true });
  return out;
}

// The row of a statement that holds binder `i`.
export function rowOfBinder(rows, i) {
  return rows.find((r) => r.head === i || r.members.includes(i))?.key ?? null;
}

// The exact Lean of one sub-term of the exact statement, by its identity: the segments it spans,
// with the sub-terms inside it. Null when the exact statement gives that identity no sub-term.
export function exactPart(st, id) {
  const ex = typeof st?.exact === "object" ? st.exact : null;
  const t = ex?.terms?.find((x) => x.id === id);
  if (!t) return null;
  const segments = ex.segments.slice(t.from, t.to);
  const terms = ex.terms.filter((x) => x.from >= t.from && x.to <= t.to)
    .map((x) => ({ ...x, from: x.from - t.from, to: x.to - t.from }));
  return { id, segments, terms, text: segments.map((s) => s.t).join("") };
}

// The row of a statement whose expression holds identity `id`: the binder whose type (or whose
// object's carried property) it is in, or the conclusion. Null for an identity it does not have.
export function rowOfId(st, id) {
  const rows = statementRows(st);
  const cands = [];
  spineOf(st).forEach((b, i) => {
    const row = rowOfBinder(rows, i);
    if (b.type?.id) cands.push([b.type.id, row]);
    if (b.id != null) cands.push([b.id + "#", row]);
  });
  if (st?.conclusion?.id) cands.push([st.conclusion.id, "c"]);
  const walk = (n) => {
    if (!n || typeof n !== "object") return;
    if (n.leaf?.id) cands.push([n.leaf.id, "c"]);
    if (n.type?.id) cands.push([n.type.id, "c"]);
    if (n.id != null && (n.op === "exists" || n.op === "forall")) cands.push([n.id + "#", "c"]);
    (n.args || []).forEach(walk);
  };
  walk(conclusionOf(st));
  let best = null, len = -1;
  for (const [p, row] of cands) {
    const hit = p.endsWith("#") ? id.startsWith(p)
      : id === p || id.startsWith(p + "/") || id.startsWith(p + "=") || id.startsWith(p + "#");
    if (hit && p.length > len) { best = row; len = p.length; }
  }
  return best;
}

// Where an alignment's Lean target is in a statement: the row of the variable or binder it names,
// the conclusion, or the row whose expression holds its sub-term; null for the whole declaration
// or an identity the statement does not have.
export function rowOfTarget(st, t) {
  if (!st || !t) return null;
  const rows = statementRows(st);
  if (t.conclusion) return st.conclusion ? "c" : null;
  if (t.at != null) return rowOfId(st, String(t.at));
  if (t.binder != null) return rowOfBinder(rows, Number(t.binder));
  if (t.var != null) {
    const binders = spineOf(st);
    const i = /^\d+$/.test(String(t.var)) ? Number(t.var) : binders.findIndex((b) => b.name === t.var);
    return i >= 0 && i < binders.length ? rowOfBinder(rows, i) : null;
  }
  return null;
}

// An alignment source in one form: a published reading (`published_work.py`) or the reading of
// the open workspace (the view `requirements.py` gives). Each alignment keeps its requirements,
// the passages it names (or its requirements' governing passages), its relation and its author.
export function alignmentSource(rd, { who, from }) {
  if (!rd) return null;
  const reqs = new Map((rd.requirements || []).map((r) => [r.local_id, r]));
  const frags = new Map();
  const governing = new Map();
  const govern = (lid, f) => { if (!governing.has(lid)) governing.set(lid, []); governing.get(lid).push(f); };
  for (const f of rd.fragments || []) {
    frags.set(f.id, f);
    if (f.role !== "later use" && (f.state ?? "accepted") === "accepted") govern(f.requirement, f);
  }
  for (const r of rd.requirements || []) {
    for (const f of r.fragments?.governing || []) { frags.set(f.id, f); govern(r.local_id, f); }
  }
  const alignments = (rd.alignments || []).filter((a) => (a.lean || []).length).map((a) => ({
    id: a.id, relation: a.relation, note: a.note || null, by: a.created_by || null,
    stale: a.currency?.state === "stale", lean: a.lean,
    requirements: (a.requirements || []).map((lid) => reqs.get(lid) || { local_id: lid, missing: true }),
    passages: a.fragments?.length
      ? a.fragments.map((id) => frags.get(id) || { id, missing: true })
      : (a.requirements || []).flatMap((lid) => governing.get(lid) || []),
  }));
  return alignments.length ? { id: from + ":" + (rd.workspace || rd.id || ""), who, from, alignments } : null;
}

// The rows of a comparison an alignment source fills: for each declaration shown (`statements`,
// its name to its statement, or null for a definition), the row of each target
// (`<decl>::<row>`, or `<decl>::top` for the whole declaration) with the alignments that name it,
// in their order. An alignment with several targets is at each of their rows; targets in a
// declaration the comparison does not show are kept apart (`elsewhere`), never moved to a row.
export function alignedRows(source, statements) {
  const at = new Map(), elsewhere = [];
  if (!source) return { at, elsewhere };
  for (const a of source.alignments) {
    for (const t of a.lean) {
      if (!Object.hasOwn(statements, t.decl)) { if (!elsewhere.includes(a)) elsewhere.push(a); continue; }
      const st = statements[t.decl];
      const row = (st && rowOfTarget(st, t)) || "top";
      const key = t.decl + "::" + row;
      if (!at.has(key)) at.set(key, []);
      const list = at.get(key);
      const seen = list.find((x) => x.alignment === a);
      if (seen) seen.targets.push(t);
      else list.push({ alignment: a, targets: [t] });
    }
  }
  return { at, elsewhere };
}

// A target of an alignment in words.
export function targetText(t) {
  const part = t.conclusion ? "the conclusion" : "var" in t ? "variable" : "binder" in t ? "hypothesis or type" : "at" in t ? "sub-term" : null;
  return t.decl + (part ? ` (${part}${t.target ? ": " + t.target : ""})` : "");
}

// The view a pin belongs to: the claim, the project and the build. A pin also holds the identity
// of what it shows (`lib/inspect.svelte.js`), so it is shown only where the same object is: never
// for another witness, project or revision.
export function pinScope(index, claimId, repo) {
  return { claim: claimId ?? null, repo: repo ?? null, release: index?.release ?? null, evidence: index?.evidence ?? null };
}

export const sameScope = (a, b) => !!a && !!b && a.claim === b.claim && a.repo === b.repo
  && a.release === b.release && a.evidence === b.evidence;
