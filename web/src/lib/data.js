// Loading of the presentation manifest. The site only reads: every status and finding comes
// from the manifest as written by the engine.

import { project, settleProject } from "./project.svelte.js";

const cache = new Map();

// An audit published elsewhere is read with `?audit=<address of its directory>`: the data comes
// from there, as data only. The address must be https (or a local server, for testing).
function auditBase() {
  const a = new URLSearchParams(location.search).get("audit");
  if (!a) return null;
  let u;
  try {
    u = new URL(a, location.href);
  } catch {
    return { error: `not an address: ${a}` };
  }
  const local = u.protocol === "http:" && /^(localhost|127\.0\.0\.1)$/.test(u.hostname);
  if (u.protocol !== "https:" && !local) return { error: `an audit must be at an https address: ${a}` };
  u.search = "";
  u.hash = "";
  // The audit's directory: given as `…/audit/`, `…/audit` or `…/audit/index.html`.
  if (/\.(json|html?)$/i.test(u.pathname)) u.pathname = u.pathname.replace(/[^/]*$/, "");
  else if (!u.pathname.endsWith("/")) u.pathname += "/";
  return { href: u.href };
}

export const AUDIT = auditBase();

// The address of one of the site's files: under the audit's directory when one is being read.
export function resolve(path) {
  if (!AUDIT?.href) return path;
  if (!inside(path)) throw new Error(`${path}: outside the audit's directory`);
  return new URL(path, AUDIT.href).href;
}

// A data path an audit names must stay inside its directory.
function inside(path) {
  return typeof path === "string" && path && !/^[a-z][\w+.-]*:|^\/|(^|\/)\.\.(\/|$)/i.test(path);
}

// A one-file bundle (`prooflens bundle`) carries its data in `window.__PROOFLENS__`, keyed by the
// same paths the site fetches, so it works opened straight from disk.
async function getJson(path) {
  const bundled = window.__PROOFLENS__;
  if (bundled) {
    if (!(path in bundled)) throw new Error(`${path}: not in this bundle`);
    return bundled[path];
  }
  if (!cache.has(path)) {
    cache.set(
      path,
      Promise.resolve().then(() => fetch(resolve(path), AUDIT ? { credentials: "omit", referrerPolicy: "no-referrer" } : {}).then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`);
        return r.json();
      })),
    );
  }
  return cache.get(path);
}

// The audit's descriptor (`audit.json`), when an audit is read from elsewhere; null otherwise.
export let auditInfo = null;

// The index this page shows, once loaded, for components that need its project details.
export let siteIndex = null;

export async function loadIndex() {
  siteIndex = await loadIndexData();
  // A paper page lists the Lean projects that formalise the paper; one is shown at a time.
  if (Array.isArray(siteIndex.projects)) settleProject(siteIndex.projects.filter((r) => typeof r === "string"));
  return siteIndex;
}

async function loadIndexData() {
  if (!AUDIT) return getJson("data/index.json");
  if (AUDIT.error) throw new Error(AUDIT.error);
  const d = await getJson("audit.json");
  if (!d || typeof d !== "object" || !String(d.schema || "").startsWith("machinechecked/audit@")) {
    throw new Error("audit.json is not a MachineChecked audit descriptor");
  }
  if (!inside(d.data)) throw new Error("audit.json names its data outside its directory");
  auditInfo = d;
  return getJson(d.data);
}

// Whether the page is served by `prooflens view`, which can save links into the repository.
export async function canEdit() {
  if (window.__PROOFLENS__ || AUDIT) return false;
  try {
    const r = await fetch("api/status");
    return r.ok && (await r.json()).editable === true;
  } catch {
    return false;
  }
}

export async function saveLink(req) {
  const r = await fetch("api/link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
  const out = await r.json();
  if (!r.ok) throw new Error(out.error || r.statusText);
  return out;
}

export function loadLeanIndex(index) {
  return getJson(index.lean_index || "data/lean-index.json");
}

export function loadSearch(index) {
  return getJson(index.search || "data/search.json");
}

// A claim as the chosen project sees it, on a page with several projects (a paper page): only
// that project's links, with the status the engine gave it for that project. Another project's
// links never show here, and are never combined with these.
export function inProject(c, repo) {
  if (!c.by_project) return c;
  const st = c.by_project[repo] || { status: "not linked", class: "unspecified" };
  const links = c.links && c.links.filter((l) => l.repository === repo);
  return { ...c, ...(links ? { links } : {}), status: st.status, class: st.class };
}

// The claims of the index for the chosen project (reactive on the choice).
export function projectClaims(index) {
  return index.projects ? index.claims.map((c) => inProject(c, project.repo)) : index.claims;
}

// A claim's full record, as the engine wrote it (on a page with several projects, show it through
// `inProject`).
export function loadClaim(index, id) {
  const c = index.claims.find((x) => x.id === id);
  if (!c) return Promise.reject(new Error(`no claim ${id} in release ${index.release}`));
  return getJson(`data/claims/${c.file}`);
}

// A declaration record of the shared store, by the key a claim gives for it. Records never change
// under their key, so one download serves every claim that uses the declaration.
export function loadDecl(key) {
  return getJson(`data/decls/${key}.json`);
}

export const CLASS_LABEL = {
  accepted: "accepted",
  proved: "proved",
  refuted: "refuted as printed",
  open: "open",
  malformed: "malformed",
  unspecified: "unspecified",
  declared: "linked, not checked",
  "out-of-scope": "out of scope",
};

// The order classes are listed in, from established to not.
export const CLASS_ORDER = [
  "accepted",
  "proved",
  "refuted",
  "open",
  "unspecified",
  "malformed",
  "out-of-scope",
];

// A claim is "not proved" when its paper claim is not established at the strongest level:
// anything but accepted, among claims in scope.
export function notProved(c) {
  return c.scope !== undefined && !String(c.status).startsWith("out of scope") && c.class !== "accepted";
}

// The review queue the engine wrote (`data/review-queue.json`), if this site has one.
export function loadQueue(index) {
  return getJson(index.review_queue);
}
