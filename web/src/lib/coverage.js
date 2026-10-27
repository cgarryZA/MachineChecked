// The words for an auditor's correspondence reading (`correspondence` of a claim, from the
// links file): its coverage, how far the claim and the linked declarations agree, and its basis,
// how that agreement is supported. Neither is a status, and the words never say more than the
// reading records: a value the vocabulary does not know is shown as no value. Every value's words
// are the engine's (`data/semantic.json`, as `semantic.reading_words` uses them), the same in the
// terminal, the Overview and every page that shows a reading.
import vocabulary from "../../../engine/python/prooflens/data/semantic.json" with { type: "json" };

export const COVERAGE = ["full", "partial", "changed", "related", "unresolved"];
export const BASIS = ["direct", "reviewed_composition", "checked_bridge"];
const BRIDGE = ["checked", "stale", "unchecked"];

function label(dimension, key) {
  const table = vocabulary[dimension] || {};
  return typeof key === "string" && Object.hasOwn(table, key) ? table[key].label : null;
}

// Words as they read inside a sentence: the first letter in lower case.
export function inText(words) {
  return words ? words.charAt(0).toLowerCase() + words.slice(1) : words;
}

// The words for a basis. A checked bridge whose state (`bridge`) is `stale` or `unchecked` reads as
// that state; with no state given, it reads as recorded.
export function basisWords(basis, bridge) {
  if (basis === "checked_bridge" && (bridge === "stale" || bridge === "unchecked")) return label("bridge", bridge);
  return BASIS.includes(basis) ? label("basis", basis) : null;
}

// The words for a coverage (null for a value the vocabulary does not name).
export function coverageLabel(coverage) {
  return COVERAGE.includes(coverage) ? label("coverage", coverage) : null;
}

// A reading's coverage and basis in words: "Part of the claim, in one Lean statement".
export function readingWords(coverage, basis, bridge) {
  const head = coverageLabel(coverage), how = basisWords(basis, bridge);
  return head && how ? `${head}, ${inText(how)}` : head;
}

// Beside every composition: what would make it a Lean result (the engine's `next_step`).
const NEXT_STEP = "State the combination as one Lean result.";

function names(list) {
  return Array.isArray(list) ? list.filter((n) => typeof n === "string" && n) : [];
}

function text(v) {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

// `{coverage, basis, headline, tone, lines}`: the known coverage and basis (or null), the
// headline, a tone for its mark (`full`, `reading`, `warning`, `open` or `note`) and the
// explanation lines, each `{label, text, names}`. A composition never has the tone or the words of
// a direct result.
export function coverageView(cor) {
  if (!cor) return null;
  // `composed` is the earlier single value for full coverage by the auditor's composition.
  const legacy = cor.coverage === "composed";
  const coverage = legacy ? "full" : COVERAGE.includes(cor.coverage) ? cor.coverage : null;
  const basis = legacy ? "reviewed_composition" : coverage && BASIS.includes(cor.basis) ? cor.basis : null;
  const bridge = basis === "checked_bridge" && cor.bridge && typeof cor.bridge === "object" ? cor.bridge : null;
  const state = bridge && BRIDGE.includes(bridge.state) ? bridge.state : "unchecked";
  const refs = names(cor.refs);
  const lines = [];
  // A bridge reads as checked only while Lean checks it.
  const headline = coverage ? readingWords(coverage, basis, state) : null;
  let tone = coverage ? "warning" : "note";
  if (coverage === "full") {
    tone = "full";
    if (basis === "reviewed_composition") tone = "reading";
    else if (basis === "checked_bridge" && state !== "checked") tone = "warning";
  }
  if (coverage === "unresolved") tone = "open";
  if (basis === "direct" && refs.length) lines.push({ label: "Stated by", names: refs });
  if (basis === "reviewed_composition") {
    if (refs.length) lines.push({ label: "Combines", names: refs });
    lines.push({ label: "The auditor's argument",
                 text: text(cor.argument) || "Not written in the reading.",
                 note: "Lean has not checked this combination." });
    lines.push({ label: "Next step", text: text(cor.next_step) || NEXT_STEP });
  }
  if (basis === "checked_bridge") {
    const thm = text(bridge?.theorem), target = text(bridge?.target);
    const checked = state === "checked" || state === "stale";
    if (thm) lines.push({ label: "Bridge", names: [thm],
                          text: checked ? "Lean checks its proof and that its type is exactly the target." : null });
    if (target) lines.push({ label: "Target", names: [target],
                             text: checked ? "The auditor read it against the paper." : null });
    const reasons = names(bridge?.reasons);
    if (reasons.length) lines.push({ label: state === "stale" ? "Out of date" : "Not checked", text: reasons.join("; ") + "." });
  }
  if (coverage === "unresolved") {
    lines.push({ label: "Open question", text: text(cor.question) || "Not stated in the reading." });
    if (text(cor.would_decide)) lines.push({ label: "Would decide it", text: text(cor.would_decide) });
  }
  return { coverage, basis, headline, tone, lines };
}

// A finding that rests on no composition (a workspace's or a published one), as `coverageView`
// reads it, with its own bridge as the engine checked it (`bridge_check`): a bridge without the
// engine's check reads as one Lean does not check.
export function findingCoverageView(f) {
  if (!f) return null;
  const check = f.bridge_check && typeof f.bridge_check === "object" ? f.bridge_check : null;
  const bridge = f.bridge && typeof f.bridge === "object" ? f.bridge : null;
  return coverageView(check ? { ...f, bridge: { ...(bridge || {}), ...check } } : f);
}

// The sentence beside a finding recorded as a checked bridge that the engine reads as the
// auditor's composition (`recorded_basis`), with the engine's reasons; null otherwise.
export function recordedBasisText(f) {
  if (f?.recorded_basis !== "checked_bridge") return null;
  const b = f.bridge && typeof f.bridge === "object" ? f.bridge : {};
  const named = text(b.theorem) && text(b.target) ? ` (${text(b.theorem)} for ${text(b.target)})` : "";
  const why = names(f.basis_reason);
  return `Recorded as a checked bridge${named}; no bridge Lean checks now${why.length ? ": " + why.join("; ") : ""}.`;
}

// An auditor's composition (`composition.view` of the engine): `{headline, tone, basis,
// bridgeState, nextStep, open, uncovered}`. The basis is a checked bridge only when the engine
// says Lean checks it now; otherwise it is the auditor's composition, with the next step beside
// it. A composition never has the words or the tone of a direct result.
export function compositionView(c) {
  if (!c) return null;
  const coverage = COVERAGE.includes(c.coverage) ? c.coverage : null;
  const check = c.bridge_check && typeof c.bridge_check === "object" ? c.bridge_check : null;
  const bridgeState = check && BRIDGE.includes(check.state) ? check.state : check ? "unchecked" : null;
  const basis = c.basis === "checked_bridge" && bridgeState === "checked" ? "checked_bridge" : "reviewed_composition";
  const headline = coverage ? readingWords(coverage, basis) : `${basisWords(basis)}; no coverage recorded`;
  const gaps = c.gaps && typeof c.gaps === "object" ? c.gaps : {};
  return {
    headline, basis, bridgeState,
    tone: coverage === "unresolved" ? "open" : basis === "checked_bridge" && coverage === "full" ? "bridge" : "reading",
    nextStep: basis === "reviewed_composition" ? text(c.next_step) || NEXT_STEP : null,
    open: names(gaps.open), uncovered: names(gaps.uncovered),
  };
}
