// A connection between two objects of Lean results (a workspace's evidence reference
// `connection`, `connections.py`), in the words the engine uses for it (`connections.text`):
// its ends, its relation with its scope, the conditions under which it holds and what supports
// it. A published audit leaves out the Lean text of the ends and the scope when it does not
// publish the Lean; the words then name the ends by declaration and variable number.
//
// The comparison shows each connection beside the rows of the objects it joins, recorded and
// computed ones marked apart, and on request the chain of connections from one object to
// another. Nothing here is a status.

import { rowOfTarget, rowOfId, innerRow } from "./comparison.js";

function refWords(r) {
  if (r?.decl) return r.decl;
  if (r?.app) return `${r.app.callee} applied in ${r.app.caller}`;
  const f = r?.fact || {};
  return `${f.name || f.head || "a fact"} inside the proof of ${f.decl}`;
}

export function endText(e) {
  e = e || {};
  if (e.decl) {
    if (e.var != null) return `${e.name || "variable " + e.var} of ${e.decl}`;
    if (e.at) return e.target ? `\`${e.target}\` in ${e.decl}` : `the sub-term ${e.at} of ${e.decl}`;
    return e.decl;
  }
  if (e.app) return `${e.param} of ${e.app.callee} applied in ${e.app.caller}`;
  return `${e.local} in the proof of ${e.fact?.decl}`;
}

export function relationText(c) {
  const a = endText(c.from), b = endText(c.to);
  switch (c.relation) {
    case "definitional": return `${a} and ${b} are definitionally equal`;
    case "projection": return `${b} is the field ${c.field || "taken"} of ${a}`;
    case "equal": return `${a} and ${b} are equal`;
    case "equal on a domain": return `${a} and ${b} are equal on ${c.domain || "a domain"}`;
    case "eventually equal": return `${a} and ${b} are eventually equal along ${c.along || "a filter"}`;
    case "equal as classes": return `${a} and ${b} are equal as classes, modulo ${c.modulo || "an equivalence"}`;
    case "restriction": return `${b} is the restriction of ${a} to ${c.domain || "a domain"}`;
    case "coercion": return `${b} is ${a} coerced`;
    case "transformation": return `${b} is a transformation of ${a} preserving ${c.preserves || "a property"}`;
    case "shared witness": return `${a} and ${b} are one witness`;
    default: return `${a} and ${b}: ${c.relation}`;
  }
}

export function connectionText(c) {
  let out = relationText(c || {});
  if (c?.conditions?.length) out += `, when ${c.conditions.join("; ")}`;
  if (c?.unfolds?.length) out += ", unfolding " + c.unfolds.map((u) => u.decl).join(", ");
  if (c?.support?.length) out += ", by " + c.support.map(refWords).join("; ");
  return out;
}

// -- beside the comparison's rows ------------------------------------------------------------

const ENDS = ["from", "to"];

// One end as one object: two ends are the same object only when they name the same part of the
// same result (a statement's variable by its binder's identity, else its number; a sub-term by
// its identity; an application's parameter; a fact's local). Names never decide it, and a
// declaration as a whole is not one of its variables (`connections.same_binder`).
export function endKey(e) {
  e = e || {};
  if (e.decl) {
    if (e.var != null) return `decl|${e.decl}|var|${e.id ?? "#" + e.var}`;
    if (e.at != null) return `decl|${e.decl}|at|${e.at}`;
    return `decl|${e.decl}`;
  }
  if (e.app) return `app|${e.app.callee}|${e.app.id ?? ""}|${e.param}`;
  const f = e.fact || {};
  return `fact|${f.decl}|${f.at ?? ""}|${e.local}`;
}

// The declaration an end belongs to: its own, its application's callee, or the declaration
// whose proof holds its fact (`connections.end_decl`).
export const endDecl = (e) => e?.decl || e?.app?.callee || e?.fact?.decl || null;

// The connections a comparison may show for a claim, each once, with where it comes from: those
// recorded in each published reading of the audit (`published`, as `published_work.py` writes
// them) and in the investigation open in this page (`own`: its view of the claim, with its
// workspace id and reviewer), as evidence records whose reference is a connection and that are
// not rejected; then those the build computed from Lean's terms (`computed`, each a connection
// as `connections.ref` writes it). `who` words a published reading's reviewer. An independent
// stage of the review protocol is given none (`comparison.comparisonInputs`).
export function connectionEntries({ published = [], own = null, computed = [], who = (r) => r?.name || r?.id } = {}) {
  const out = [];
  const recorded = (records, meta) => {
    for (const e of records || []) {
      const c = e?.ref?.connection;
      if (!c || e.role === "rejected") continue;
      out.push({ key: meta.set + "|" + e.id, id: e.id, origin: "recorded", connection: c, role: e.role || "candidate",
                 by: meta.who, set: meta.set, state: e.currency?.state || "unchecked", currency: e.currency || null });
    }
  };
  for (const rd of published || []) {
    recorded(rd?.evidence, { who: who(rd?.reviewer || {}), set: "published:" + (rd?.workspace || "") });
  }
  if (own) recorded(own.evidence, { who: "your investigation (" + (own.reviewer || "") + ")", set: "workspace:" + (own.workspace || "") });
  (computed || []).forEach((c, i) => {
    if (!c?.relation || !c.from || !c.to) return;
    out.push({ key: "computed|" + i, id: null, origin: "computed", connection: c, role: null, by: null,
               set: "computed", state: c.currency?.state || null, currency: c.currency || null });
  });
  return out;
}

// The row of a statement an end's object is at: the row where the statement binds its variable,
// or the row whose expression holds its sub-term. Null for a declaration as a whole, an
// application's argument, a fact's local, or an identity the statement does not have.
export function endRow(e, st) {
  if (!st || !e?.decl) return null;
  if (e.var != null) return rowOfTarget(st, { var: e.var }) ?? innerRow(st, { var: e.var });
  if (e.at != null) return rowOfId(st, String(e.at));
  return null;
}

// Where the connections are in the comparison, given the statements it shows (each name to its
// statement, or null for a definition): at the row of each end's object, or at its declaration
// as a whole (`<decl>::top`), drawn once at each such row with the ends there (`sides`). A
// connection that changed since it was recorded is never placed at a row, since the object it
// names may now be another expression: it is listed with the whole claim (`claim`), with what
// changed. One with no end in the Lean the comparison shows is listed apart (`elsewhere`).
export function placeConnections(entries, statements) {
  const at = new Map(), claim = [], elsewhere = [];
  for (const entry of entries || []) {
    const sides = ENDS.filter((s) => Object.hasOwn(statements, endDecl(entry.connection[s])));
    if (!sides.length) { elsewhere.push(entry); continue; }
    if (entry.state === "stale") { claim.push(entry); continue; }
    const rows = new Map();
    for (const s of sides) {
      const e = entry.connection[s], d = endDecl(e);
      const key = d + "::" + (endRow(e, statements[d]) || "top");
      if (!rows.has(key)) rows.set(key, []);
      rows.get(key).push(s);
    }
    for (const [key, ss] of rows) {
      if (!at.has(key)) at.set(key, []);
      at.get(key).push({ entry, sides: ss });
    }
  }
  return { at, claim, elsewhere };
}

// The graph of the connections: each object (`endKey`) with the connections at it.
function graph(entries) {
  const adj = new Map(), ends = new Map();
  const add = (k, step) => { if (!adj.has(k)) adj.set(k, []); adj.get(k).push(step); };
  for (const entry of entries) {
    const a = entry.connection.from, b = entry.connection.to;
    const ka = endKey(a), kb = endKey(b);
    if (!ends.has(ka)) ends.set(ka, a);
    if (!ends.has(kb)) ends.set(kb, b);
    if (ka === kb) continue;
    add(ka, { entry, from: a, to: b, next: kb });
    add(kb, { entry, from: b, to: a, next: ka });
  }
  return { adj, ends };
}

function shortest(entries, fromKey, toKey) {
  const { adj } = graph(entries);
  const back = new Map([[fromKey, null]]);
  const queue = [fromKey];
  while (queue.length) {
    const k = queue.shift();
    if (k === toKey) break;
    for (const step of adj.get(k) || []) {
      if (back.has(step.next)) continue;
      back.set(step.next, step);
      queue.push(step.next);
    }
  }
  if (fromKey === toKey || !back.has(toKey)) return null;
  const steps = [];
  for (let k = toKey; back.get(k); k = endKey(back.get(k).from)) steps.unshift(back.get(k));
  return steps;
}

// The objects the connections join to the object `fromKey`, nearest first: `{key, end}`.
export function linkedObjects(entries, fromKey) {
  const { adj, ends } = graph(entries || []);
  const seen = new Set([fromKey]), out = [], queue = [fromKey];
  while (queue.length) {
    for (const step of adj.get(queue.shift()) || []) {
      if (seen.has(step.next)) continue;
      seen.add(step.next);
      queue.push(step.next);
      out.push({ key: step.next, end: ends.get(step.next) });
    }
  }
  return out;
}

// The chain of connections from the object `fromKey` to the object `toKey`, on request: the
// fewest connections that join them, each step with its connection and the ends it is read from
// and to (`{entry, from, to}`). Connections that have not changed since they were recorded are
// tried first; a chain through one that changed is given only when there is no other, and its
// step says so (`entry.state`). Null when no chain of these connections joins them.
export function chainBetween(entries, fromKey, toKey) {
  const all = entries || [];
  const steps = shortest(all.filter((e) => e.state !== "stale"), fromKey, toKey) || shortest(all, fromKey, toKey);
  if (!steps) return null;
  return { steps: steps.map(({ entry, from, to }) => ({ entry, from, to })),
           sources: [...new Set(steps.map((s) => s.entry.set))] };
}
