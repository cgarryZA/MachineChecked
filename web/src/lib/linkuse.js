// How the main results use one link of a claim (`impact.link_uses`), in the engine's words: for
// each main result, whether its proof uses the link (directly or through other declarations),
// its statement only, neither (formalized separately), or whether that is not traced, with the
// basis of the main results traced from. A use is a fact about the Lean terms of the build; it
// changes no status.

// Where the main results come from, in words.
export function basisText(sel) {
  if (!sel) return "";
  if (sel.basis === "suggested") return `suggested: ${sel.rule}`;
  if (sel.basis === "saved") {
    const by = [sel.workspace ? `in workspace ${sel.workspace}` : "", sel.by ? `by ${sel.by}` : "", sel.at ? `on ${sel.at}` : ""].filter(Boolean).join(" ");
    return `saved ${by}`.trim() + (sel.note ? `; ${sel.note}` : "");
  }
  return sel.basis || "";
}

// One link's answers, each with the declarations its shortest path goes through (`via`). Null
// when the answer is not available or does not hold this link (a link made since it was traced).
export function linkUses(doc, claimId, name) {
  if (!doc) return null;
  if (doc.available === false) return { unavailable: doc.reason || "not available" };
  const list = doc.claims?.[claimId]?.[name];
  if (!list) return null;
  return { basis: basisText(doc.selection), complete: doc.complete !== false,
           entries: list.map((e) => ({ ...e, via: (e.path || []).slice(1, -1) })) };
}
