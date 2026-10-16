// The formalisation a paper page shows. A paper may have several Lean projects; they are separate
// evidence, never combined, so the page shows one at a time. The choice is shared by every view
// (contents, margin bands, the claim panel) and kept in the page's address, `?project=owner/repo`,
// so a copied link keeps it.

const REPO = /^[\w.-]+\/[\w.-]+$/;

function fromAddress() {
  const r = new URLSearchParams(location.search).get("project");
  return r && REPO.test(r) ? r : null;
}

export const project = $state({ repo: fromAddress() });

// Choose a project: every claim view follows, and the address records it (without reloading,
// so the paper and its scroll position stay where they are).
export function chooseProject(repo) {
  if (!REPO.test(repo || "")) return;
  project.repo = repo;
  const u = new URL(location.href);
  u.searchParams.set("project", repo);
  history.replaceState(history.state, "", u);
}

// The repositories a paper page lists; the default choice is the first, unless the address names
// another of them.
export function settleProject(repos) {
  if (!repos.length) project.repo = null;
  else if (!repos.includes(project.repo)) project.repo = repos[0];
}
