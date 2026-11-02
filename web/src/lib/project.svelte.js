// The formalisation a paper page shows. A paper may have several Lean projects; their evidence is
// never combined into one status. By default a page with several audits of its version shows them
// together: each claim with the evidence of the first audit (`index.audit_order`, the most-starred
// repository first) that maps it, labelled with that audit. Choosing one project shows only its
// evidence. The choice is shared by every view (contents, margin bands, the claim panel) and kept
// in the page's address, `?project=owner/repo` (absent for the audits together), so a copied
// link keeps it.

import { route, withQuery } from "./route.svelte.js";

const REPO = /^[\w.-]+\/[\w.-]+$/;

function fromAddress() {
  const r = new URLSearchParams(location.search).get("project");
  return r && REPO.test(r) ? r : null;
}

// `repo` is the project whose evidence is shown first (the default audit, when `combined`);
// `order` the page's audits in the order they are drawn on.
export const project = $state({ repo: fromAddress(), combined: false, order: [],
  edition: new URLSearchParams(location.search).get("edition") || "original" });

export function chooseEdition(edition) {
  project.edition = edition;
  const u = new URL(location.href);
  if (edition === "original") u.searchParams.delete("edition");
  else u.searchParams.set("edition", edition);
  history.replaceState(history.state, "", u);
}

// Choose a project: every claim view follows, and the address records it (without reloading,
// so the paper and its scroll position stay where they are). An empty choice shows the page's
// audits together.
export function chooseProject(repo) {
  const together = !repo && project.order.length > 1;
  if (!together && !REPO.test(repo || "")) return;
  project.combined = together;
  project.repo = together ? project.order[0] : repo;
  const u = new URL(location.href);
  if (together) u.searchParams.delete("project");
  else u.searchParams.set("project", repo);
  u.hash = withQuery(u.hash, { inspect: null, at: null });
  route.inspection = [];
  route.at = null;
  history.replaceState(history.state, "", u);
}

// The repositories a paper page lists, and its loaded audits in order. The address may name one
// of the repositories; otherwise a page with several audits shows them together, and one with a
// single audit (or none) shows the first of its audits (or of its repositories).
export function settleProject(repos, order = []) {
  project.order = order.filter((r) => repos.includes(r));
  const named = fromAddress();
  if (!repos.length) { project.repo = null; project.combined = false; }
  else if (named && repos.includes(named)) { project.repo = named; project.combined = false; }
  else { project.repo = project.order[0] || repos[0]; project.combined = project.order.length > 1; }
}
