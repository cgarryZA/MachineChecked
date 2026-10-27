// The semantic summary the engine computed (`index.semantic`, prooflens/semantic-summary@1,
// engine/python/prooflens/semantic.py) and each claim's facts (`semantic` on its index row). The
// Overview shows these values and filters by them; it computes no coverage, basis or review of
// its own, and never adds the counts of different units.
import vocabulary from "../../../engine/python/prooflens/data/semantic.json" with { type: "json" };
import { inText } from "./coverage.js";

export const UNITS = ["statements", "notation", "proof_steps"];
export const DIMENSIONS = ["coverage", "basis", "review", "findings"];
const RELATIONS = ["full", "partial", "changed", "related", "unresolved"];
const own = (table, key) => (table && Object.hasOwn(table, key) ? table[key] : null);

// The summary, or null when the index has none (older data, a paper page).
export function summaryOf(index) {
  const s = index?.semantic;
  return s && s.schema === "prooflens/semantic-summary@1" && s.papers && typeof s.papers === "object" &&
    Array.isArray(s.sets) ? s : null;
}

// The keys of a dimension, in the vocabulary's order (the review of statements, then of proof
// steps).
export function keys(dimension) {
  if (dimension === "review") return [...new Set([...Object.keys(vocabulary.review), ...Object.keys(vocabulary.step_review)])];
  return Object.keys(vocabulary[dimension] || {});
}

// The words for a key of a dimension: `{label, explanation}`. For a review, `unit` chooses the
// words of a proof step's review.
export function words(dimension, key, unit) {
  if (dimension === "review") {
    const step = own(vocabulary.step_review, key), statement = own(vocabulary.review, key);
    const row = unit === "proof_steps" ? step || statement : statement || step;
    if (row) return { label: row.label, explanation: row.explanation || "" };
  }
  return own(vocabulary[dimension], key) || { label: "Not recognised", explanation: "Rebuild the audit with the current MachineChecked version." };
}

export function unitWord(unit, n) {
  const w = own(vocabulary.units, unit);
  return w ? (n === 1 ? w.one : w.many) : "claims";
}

// A set of readings in words: the audit's own, a reviewer's, a workspace's.
export function setLabel(set) {
  if (!set) return "";
  const who = set.reviewer?.name || set.reviewer?.id || "";
  if (set.kind === "audit") return vocabulary.sets.audit.label;
  if (set.kind === "review") return `${vocabulary.sets.review.label} ${who}`.trim();
  if (set.kind === "workspace") return `${vocabulary.sets.workspace.label} ${who}`.trim() + (set.mode ? ` (${set.mode})` : "");
  return set.id;
}

export function setExplanation(set) {
  return own(vocabulary.sets, set?.kind)?.explanation || "";
}

// The unit a claim is counted in.
export function unitOf(row) {
  if (UNITS.includes(row?.semantic?.unit)) return row.semantic.unit;
  return row?.unit && row.unit !== "statement" ? "proof_steps" : "statements";
}

export function readingOf(row, setId) {
  return (row?.semantic?.readings || []).find((r) => r && r.set === setId) || null;
}

// A claim's key in each dimension, for the set `setId`: as the engine counted it.
export function keysOf(row, setId) {
  const r = readingOf(row, setId);
  const coverage = r ? r.count : "not_assessed";
  return {
    coverage,
    basis: r && RELATIONS.includes(r.count) ? r.basis || "unspecified" : null,
    review: row?.semantic?.review || null,
    findings: Array.isArray(row?.semantic?.findings) ? row.semantic.findings : [],
  };
}

// How many claims of each unit the engine counted under `key` of `dimension` (for the set
// `setId`), over the summary's papers. A paper's claims are its own, so the papers' counts of
// one unit add up to a count of distinct claims; different units are kept apart.
export function unitCounts(summary, dimension, setId, key) {
  const out = {};
  for (const p of Object.values(summary?.papers || {})) {
    for (const u of UNITS) {
      const table = dimension === "review" || dimension === "findings" ? p?.[dimension]?.[u] : p?.[dimension]?.[setId]?.[u];
      const n = own(table, key);
      if (Number.isInteger(n) && n > 0) out[u] = (out[u] || 0) + n;
    }
  }
  return out;
}

// The count shown beside a filter: the chosen unit's, or each unit's with its name.
export function countText(counts, unit) {
  if (unit !== "all") return String(counts[unit] || 0);
  return UNITS.filter((u) => counts[u]).map((u) => `${counts[u]} ${unitWord(u, counts[u])}`).join(", ");
}

// One unit of a paper's inventory in words ("5 statements, 4 linked to 3 declarations"), or ""
// when the paper has none of that unit. Only counts the summary gives are said.
export function unitInventoryText(paper, u) {
  const inv = paper?.inventory, row = inv?.[u];
  if (!Number.isInteger(row?.records) || row.records <= 0) return "";
  const n = (v) => Number.isInteger(v) && v > 0;
  const decls = n(row.declarations) ? ` to ${row.declarations} declaration${row.declarations === 1 ? "" : "s"}` : "";
  const kinds = u === "proof_steps" ? [[inv.proof_equations, "equation"], [inv.proof_passages, "passage"]]
    .filter(([k]) => n(k)).map(([k, w]) => `${k} ${w}${k === 1 ? "" : "s"}`).join(", ") : "";
  const linked = Number.isInteger(row.linked) ? `, ${row.linked} linked${decls}` : "";
  return `${row.records} ${unitWord(u, row.records)}${kinds ? ` (${kinds})` : ""}${linked}`;
}

// A paper's inventory in words: each unit, how many are linked, and to how many declarations.
export function inventoryText(paper) {
  const inv = paper?.inventory;
  if (!inv) return "";
  return UNITS.filter((u) => inv[u]?.records).map((u) => {
    const row = inv[u];
    const decls = row.declarations ? ` to ${row.declarations} declaration${row.declarations === 1 ? "" : "s"}` : "";
    const kinds = u === "proof_steps" ? ` (${[[inv.proof_equations, "equation"], [inv.proof_passages, "passage"]]
      .filter(([n]) => n).map(([n, w]) => `${n} ${w}${n === 1 ? "" : "s"}`).join(", ")})` : "";
    return `${row.records} ${unitWord(u, row.records)}${kinds}, ${row.linked} linked${decls}`;
  }).join(" · ");
}

// The correspondence of a claim's reading in a row: its coverage, what an out-of-date reading
// recorded, and the clauses a clause-only reading covers.
export function coverageText(reading) {
  if (!reading) return words("coverage", "not_assessed").label;
  const head = words("coverage", reading.count).label;
  if (reading.count === "stale" && RELATIONS.includes(reading.coverage)) return `${head} (recorded: ${inText(words("coverage", reading.coverage).label)})`;
  if (reading.count === "clauses_only" && Number.isInteger(reading.clauses)) return `${head} (${reading.clauses})`;
  return head;
}

export function basisText(reading) {
  if (!reading || !RELATIONS.includes(reading.count)) return "";
  const head = words("basis", reading.basis || "unspecified").label;
  return reading.recorded_basis && reading.recorded_basis !== reading.basis
    ? `${head} (recorded as ${inText(words("basis", reading.recorded_basis).label)})` : head;
}

// The question an unresolved reading records, when it is short enough for a row.
export const SHORT = 160;
export function shortQuestion(reading) {
  const q = typeof reading?.question === "string" ? reading.question.trim() : "";
  return q && q.length <= SHORT ? q : null;
}
