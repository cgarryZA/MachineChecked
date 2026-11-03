// What a recorded difference affects at one use: a finding's `impact` (`impact.py`), in the
// engine's words. It names the difference finding as it was read, the use (an evidence record
// citing one application), the outcome at that use and the reviewer's explanation; the
// requirement at the use is the finding's own requirement. An impact is one reviewer's reading
// of one application: it says nothing of another application and changes no status.

export const IMPACT_OUTCOMES = ["sufficient for this use", "not sufficient", "a separate scope question", "unresolved"];

export function impactHead(imp) {
  return `At a use: ${imp?.outcome}`;
}

// The difference an impact concerns, as it pinned it (`impact.difference_words`).
export function differenceText(pin) {
  pin = pin || {};
  const where = [pin.claim, pin.requirement].filter(Boolean).join(" ");
  const sides = [pin.paper ? `paper ${pin.paper}` : "", pin.lean ? `Lean ${pin.lean}` : ""].filter(Boolean).join("; ");
  return `the ${pin.feature || "recorded"} difference ${pin.finding}` + (where ? ` on ${where}` : "") + (sides ? ` (${sides})` : "");
}

// The application an impact is recorded at, from the evidence it cites.
export function useText(id, evidence) {
  const a = (evidence || []).find((e) => e.id === id)?.ref?.app;
  return a ? `${a.callee} applied in ${a.caller}${a.id ? " (" + a.id + ")" : ""}` : id;
}

export function impactView(f, evidence) {
  const imp = f?.impact;
  if (!imp) return null;
  return { head: impactHead(imp), outcome: imp.outcome, difference: differenceText(imp.difference),
           use: useText(imp.use, evidence), why: imp.why || null,
           tone: imp.outcome === "sufficient for this use" ? "note" : "warning" };
}

// The impacts a workspace view (`workspace.view`) records at the application `id` of `callee`:
// each finding with its claim, outcome and explanation.
export function impactsAt(view, callee, id) {
  const out = [];
  for (const [claim, c] of Object.entries(view?.claims || {})) {
    for (const f of c.findings || []) {
      const app = (c.evidence || []).find((e) => e.id === f.impact?.use)?.ref?.app;
      if (app && app.callee === callee && app.id === id) out.push({ claim, finding: f, ...impactView(f, c.evidence) });
    }
  }
  return out;
}
