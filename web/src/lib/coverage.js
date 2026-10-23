// The words for an auditor's correspondence reading (`correspondence` of a claim, from the
// links file): its coverage, how far the claim and the linked declarations agree, and its basis,
// how that agreement is supported. Neither is a status, and the words never say more than the
// reading records: a value this table does not know is shown as no value.

const COVERAGE = {
  full: "Every clause",
  partial: "States part of the claim",
  changed: "States it differently",
  related: "A related result, not this claim",
  unresolved: "Unresolved",
};
const BASIS = ["direct", "reviewed_composition", "checked_bridge"];
const BRIDGE = ["checked", "stale", "unchecked"];
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
  const coverage = legacy ? "full" : Object.hasOwn(COVERAGE, cor.coverage) ? cor.coverage : null;
  const basis = legacy ? "reviewed_composition" : coverage && BASIS.includes(cor.basis) ? cor.basis : null;
  const bridge = basis === "checked_bridge" && cor.bridge && typeof cor.bridge === "object" ? cor.bridge : null;
  const state = bridge && BRIDGE.includes(bridge.state) ? bridge.state : "unchecked";
  const refs = names(cor.refs);
  const lines = [];
  let headline = coverage ? COVERAGE[coverage] : null;
  let tone = coverage ? "warning" : "note";
  if (coverage === "full") {
    tone = "full";
    if (basis === "direct") headline = "States every clause";
    else if (basis === "reviewed_composition") { headline = "Every clause, by the auditor's composition"; tone = "reading"; }
    else if (basis === "checked_bridge") {
      headline = state === "checked" ? "Every clause, through a checked bridge"
        : state === "stale" ? "Every clause, through a checked bridge; the auditor's reading is out of date"
        : "Every clause, through a bridge Lean does not check";
      if (state !== "checked") tone = "warning";
    }
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
  const coverage = Object.hasOwn(COVERAGE, c.coverage) ? c.coverage : null;
  const check = c.bridge_check && typeof c.bridge_check === "object" ? c.bridge_check : null;
  const bridgeState = check && BRIDGE.includes(check.state) ? check.state : check ? "unchecked" : null;
  const basis = c.basis === "checked_bridge" && bridgeState === "checked" ? "checked_bridge" : "reviewed_composition";
  const how = basis === "checked_bridge" ? "through a checked bridge" : "by the auditor's composition";
  const headline = coverage === "full" ? `Every clause, ${how}`
    : coverage ? `${COVERAGE[coverage]}, ${how}` : `A composition, ${how}; no coverage recorded`;
  const gaps = c.gaps && typeof c.gaps === "object" ? c.gaps : {};
  return {
    headline, basis, bridgeState,
    tone: coverage === "unresolved" ? "open" : basis === "checked_bridge" && coverage === "full" ? "bridge" : "reading",
    nextStep: basis === "reviewed_composition" ? text(c.next_step) || NEXT_STEP : null,
    open: names(gaps.open), uncovered: names(gaps.uncovered),
  };
}
