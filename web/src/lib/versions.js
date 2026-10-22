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

// A claim's counterparts in the other versions of its paper (`counterparts` on the claim's index
// row, from a claim map the site supplies), as the claim view shows them: each with the other
// version's label and a link to each counterpart claim on that version's page. A version the page
// does not offer is left out. A counterpart says how the claim relates; it never changes a status.
const CHANGE = { same: "same statement", renumbered: "renumbered", changed: "statement changed" };

export function counterpartViews(index, row, repo) {
  const versions = pageVersions(index);
  const out = [];
  for (const cp of Array.isArray(row?.counterparts) ? row.counterparts : []) {
    const v = versions.find((x) => x.id === cp.version);
    const page = v && v.id !== index.version ? versionHref(v, repo) : null;
    if (!page) continue;
    const label = versionLabel(v);
    const claims = (Array.isArray(cp.claims) ? cp.claims : [])
      .filter((c) => typeof c?.id === "string" && typeof c?.number === "string")
      .map((c) => ({ number: c.number, href: page + "#/r/paper/read/P/" + encodeURIComponent(c.id) }));
    let before = "", after = "";
    if (cp.change === "removed" && cp.later && !claims.length) before = "Removed in " + label;
    else if (cp.change === "new" && !cp.later && !claims.length) before = "New in this version: not in " + label;
    else if (cp.change === "split" && cp.later && claims.length >= 2) { before = "Split into "; after = " in " + label; }
    else if (cp.change === "split" && !cp.later && claims.length === 1) { before = "Part of "; after = " in " + label + ", which was split"; }
    else if (CHANGE[cp.change] && claims.length === 1) after = " in " + label + ", " + CHANGE[cp.change];
    else continue;
    out.push({ change: cp.change, version: v.id, before, claims, after });
  }
  return out;
}
