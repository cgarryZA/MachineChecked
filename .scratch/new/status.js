// Result explanations use machine-readable facts. Display labels are never control flow.
const excluded = new Set(["expository", "literature", "empirical", "proof-step", "part-of", "duplicate", "out-of-scope"]);
export const inScope = (claim) => !excluded.has(claim.scope) && claim.class !== "out-of-scope";
export const notAccepted = (claim) => claim.scope !== undefined && inScope(claim) && claim.class !== "accepted";

export function clauseVerdict(cl, review = true) {
  const checks = cl.checks || {};
  const proof = checks.accept || checks.refute;
  if (cl.state === "unchecked") return "The Lean project was not checked in this build.";
  if (cl.state === "unspecified") return "No Lean statement has been written for it yet.";
  if (cl.state === "stated") return "Stated in Lean as definitions.";
  if (!["open", "proved", "refuted"].includes(cl.state)) return "No recognised formal result is available.";
  if (!proof || cl.state === "open" && proof.ok) return "A Lean statement exists; it has no proof yet.";
  if (!proof.ok) return "The Lean proof fails a check: " + (proof.errors || []).join(", ") + ".";
  const replay = checks.replay?.state === "pass" ? ", replayed independently" : "";
  const reviews = { reviewed: "its correspondence reviewed independently", "author-reviewed": "its correspondence reviewed only by its author", pending: "its correspondence not yet reviewed" };
  const note = review && Object.hasOwn(reviews, cl.review) ? "; " + reviews[cl.review] : "";
  return (cl.state === "refuted" ? "Lean proves the negation of the formal statement" : "Proved in Lean") + replay + note + ".";
}

export function clauseNote(cl, count) {
  if (count > 1) return clauseVerdict(cl, false);
  const proof = cl.checks?.accept || cl.checks?.refute;
  if (["unchecked", "unspecified"].includes(cl.state) || cl.state !== "stated" && (!proof || !proof.ok)) return clauseVerdict(cl);
  return null;
}

const LINK_NOTES = {
  "link.no-audit": "The project declares this link. No published audit records what Lean establishes here.",
  "link.not-in-audit": "The published audit does not include this claim. Its proof status is not shown here.",
  "link.unbuilt": "The project is not built, so this declaration has not been checked.",
  "link.module-unbuilt": "The declaration's module is not built, so it has not been checked.",
  "link.module-failed": "The declaration's module could not be loaded, so it has not been checked.",
  "link.ambiguous": "More than one module declares this name. Select the intended module before checking it.",
  "link.failed": "Lean could not inspect this declaration. No proof result is available.",
  "link.missing": "Not found in the built modules.",
  "link.definition": "A Lean definition, not a theorem proof.",
  "link.incomplete": "Its Lean proof is incomplete (it uses sorry).",
  "link.checked": "Proved in Lean. Correspondence with the paper has not been reviewed here.",
  "link.suggested": "A suggested link, not a confirmed correspondence.",
  "link.none": "No Lean declaration is linked to this claim.",
  "published-audit": "This result is recorded by the linked audit, not checked by this page.",
};

export function linkVerdict(link) {
  if (link.status_code === "link.axioms") return "Its proof uses additional axioms: " + (link.axioms || []).join(", ") + ".";
  return Object.hasOwn(LINK_NOTES, link.status_code) ? LINK_NOTES[link.status_code]
    : "No recognised machine-readable result is available. Rebuild the audit to inspect it.";
}
