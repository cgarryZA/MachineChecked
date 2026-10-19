// The versions of a paper a paper page offers (`index.versions`, written by the engine's
// `write_paper_site`). Each version has its own page, with its own PDF, claim numbering and
// audits; choosing one opens that page. A version is labelled from its kind and identifier, the
// same way the engine labels it: a published version as "arXiv v1", an unpublished manuscript as
// "Latest manuscript (commit abc1234)", never with a version number it has not been given.

const COMMIT = /^[0-9a-f]{7,40}$/;
const ARXIV = /^arxiv:(.+?)(v\d+)?$/;

export function versionLabel(v) {
  if (v?.kind === "manuscript" && COMMIT.test(v.revision || "")) return `Latest manuscript (commit ${v.revision.slice(0, 7)})`;
  if (v?.kind === "published" && typeof v.id === "string") {
    const m = ARXIV.exec(v.id);
    if (m) return m[2] ? `arXiv ${m[2]}` : `arXiv ${m[1]}`;
    return `Published (${v.id})`;
  }
  return null;
}

// The address of a version's page, on this site only. The chosen formalisation goes with it;
// the claim does not, since claim numbers can differ between versions.
export function versionHref(v, repo) {
  if (typeof v?.href !== "string" || /^[a-z][\w+.-]*:|^\/\//i.test(v.href)) return null;
  let u;
  try {
    u = new URL(v.href, location.href);
  } catch {
    return null;
  }
  if (u.origin !== location.origin) return null;
  u.hash = "";
  if (repo) u.searchParams.set("project", repo);
  return u.href;
}

// The versions the page can offer: those with a label and an address on this site.
export function pageVersions(index) {
  return (Array.isArray(index?.versions) ? index.versions : []).filter((v) => versionLabel(v) && versionHref(v));
}
