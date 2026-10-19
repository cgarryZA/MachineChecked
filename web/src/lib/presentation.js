// Status codes and evidence facts are the contract. Display text never selects behaviour.
import vocabulary from "../../../engine/python/prooflens/data/statuses.json" with { type: "json" };

const own = (table, key) => Object.hasOwn(table, key) ? table[key] : null;
export const CLASS_ORDER = ["accepted", "proved", "refuted", "open", "caution", "unspecified", "declared", "malformed", "out-of-scope"];

export function statusView(record) {
  return own(vocabulary.statuses, record?.status_code) || vocabulary.statuses.unknown;
}

export function inScope(record) {
  return statusView(record).class !== "out-of-scope";
}

export function notProved(record) {
  return record.scope !== undefined && inScope(record) && statusView(record).class !== "accepted";
}

export function statusSummary(claims) {
  const counts = new Map();
  for (const claim of claims) {
    const code = own(vocabulary.statuses, claim.status_code) ? claim.status_code : "unknown";
    counts.set(code, (counts.get(code) || 0) + 1);
  }
  return [...counts].map(([status_code, count]) => ({ status_code, count }))
    .sort((a, b) => CLASS_ORDER.indexOf(statusView(a).class) - CLASS_ORDER.indexOf(statusView(b).class));
}

export function evidenceView(dimension, fact) {
  const dim = own(vocabulary.dimensions, dimension);
  const state = own(dim?.states || {}, fact?.state);
  const unknown = { label: "unknown", explanation: "This evidence state is not recognised. Rebuild the audit with the current MachineChecked version." };
  const row = state || unknown;
  const extras = [];
  if (dimension === "source") {
    extras.push(own(vocabulary.pdf_integrity, fact?.pdf_integrity));
    extras.push(own(vocabulary.placement, fact?.placement));
  }
  const word = [row.label, ...extras.filter(Boolean)].join(" · ");
  const detail = [row.explanation, fact?.detail, ...(fact?.errors || [])].filter(Boolean).join(" ");
  return { label: dim?.label || "Unknown evidence", word, detail, state: state ? fact.state : "unknown" };
}

// A clause note is useful when clauses differ, a check failed, or the statement is absent.
export function clauseNote(clause, count) {
  const failed = [clause.checks?.accept, clause.checks?.refute].find((p) => p && !p.ok);
  if (failed) return "The Lean proof fails a check: " + (failed.errors || []).join(", ") + ".";
  if (count > 1 || ["unchecked", "unspecified", "open"].includes(clause.evidence?.formal?.state)) {
    return evidenceView("formal", clause.evidence?.formal).detail;
  }
  return null;
}

// Preserve each recorded state when a claim has clauses with different evidence.
export function evidenceFacts(record) {
  const rows = record?.clauses?.map((c) => c.evidence) || record?.evidence_summary || [];
  return ["formal", "review"].flatMap((dimension) => {
    const facts = [...new Map(rows.filter((r) => r?.[dimension]).map((r) => [r[dimension].state, evidenceView(dimension, r[dimension])])).values()];
    return facts.length ? [{ dimension, label: dimension === "formal" ? "Proof" : "Review", word: facts.map((f) => f.word).join(" · "), detail: facts.map((f) => f.detail).join(" ") }] : [];
  });
}
