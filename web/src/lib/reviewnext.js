// The Overview's "Review next": the first open units of the review queue the build wrote
// (`data/review-queue.json`, `review_queue.prioritise`), in its own priority order, each with the
// reason the engine gave it. Nothing is ranked here, and only that order is read: the informed
// order, which draws on prior interpretations, is never asked for, so the list shows nothing a
// later blind reading must not see. An entry names its unit by the printed numbers of its claims,
// never by its Lean, as the review page names a unit before its reading is locked.

export const SHOWN = 5;
const KIND = { def: "Definition", link: "Linked claim", step: "Proof step" };
const NAMED = 3;

// The words the review page gives a unit's kind.
export function kindWord(u) {
  return KIND[u?.kind] || "Statement";
}

function list(items) {
  const xs = [...new Set(items)];
  if (xs.length > NAMED) return `${xs.slice(0, NAMED).join(", ")} and ${xs.length - NAMED} more`;
  return xs.length < 2 ? xs[0] || "" : `${xs.slice(0, -1).join(", ")} and ${xs[xs.length - 1]}`;
}

// `{entries, open}`: up to `n` open units of `queue` in its order, each `{id, kind, label,
// reason}`, and how many units are open. `claims` (the index's) gives each claim's number.
export function reviewNext(queue, claims, n = SHOWN) {
  const open = (Array.isArray(queue?.units) ? queue.units : []).filter((u) => u && typeof u.id === "string" && u.state !== "reviewed");
  const number = new Map((claims || []).map((c) => [c.id, c.number || c.id]));
  const entries = open.slice(0, n).map((u) => {
    const names = (Array.isArray(u.claims) ? u.claims : []).map((c) => number.get(c.id) || c.number || c.id).filter(Boolean);
    const label = u.kind === "def" ? (names.length ? `A definition used by ${list(names)}` : "A definition") : list(names) || "A unit";
    return { id: u.id, kind: kindWord(u), label, reason: typeof u.reason === "string" ? u.reason : "" };
  });
  return { entries, open: open.length };
}
