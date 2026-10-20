// Loading of the presentation manifest. The site only reads: every status and finding comes
// from the manifest as written by the engine.

import { Retrieval } from "./retrieval.js";
import { statusView } from "./presentation.js";
export { notProved } from "./presentation.js";

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
    const pending = Promise.resolve().then(() => fetch(resolve(path), AUDIT ? { credentials: "omit", referrerPolicy: "no-referrer" } : {}).then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`);
        return r.json();
      }));
    cache.set(path, pending);
    pending.catch(() => { if (cache.get(path) === pending) cache.delete(path); });
  }
  return cache.get(path);
}

// The audit's descriptor (`audit.json`), when an audit is read from elsewhere; null otherwise.
export let auditInfo = null;

// The index this page shows, once loaded, for components that need its project details.
export let siteIndex = null;

export async function loadIndex() {
  siteIndex = await loadIndexData();
  if (siteIndex.schema !== "prooflens/manifest@1") throw new Error("Old reader data: rebuild the audit with the current MachineChecked version.");
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

// Whether the page is served by `machinechecked view`, which can save links into the repository:
// that local server (on a loopback address only) marks the data index it serves `editable`. A
// static copy of the site, an audit or a bundle never is, and asks no server anything.
export function canEdit(index) {
  if (window.__PROOFLENS__ || AUDIT) return false;
  const loopback = /^(127\.0\.0\.1|localhost|\[::1\])$/.test(location.hostname);
  return loopback && index?.editable === true;
}

export async function saveLink(req) {
  const r = await fetch("api/link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
  const out = await r.json();
  if (!r.ok) throw new Error(out.error || r.statusText);
  return out;
}

// A symbol link made in the local reader (full assessment): recorded with the checks of
// `machinechecked symbol add`, under the name given.
export async function saveSymbol(req) {
  const r = await fetch("api/symbol", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
  const out = await r.json();
  if (!r.ok) throw new Error(out.error || r.statusText);
  return out;
}

// The workspace records an audit publishes for a claim (`prooflens/published-work@1`): the
// passport names their file in `work`; a paper page carries them in the claim's record already.
export async function loadWork(claim) {
  const w = claim?.work;
  if (!w) return null;
  if (typeof w === "object") return w;
  if (!inside(w)) throw new Error(`${w}: outside the audit's directory`);
  const data = await getJson("data/" + w);
  return data?.schema === "prooflens/published-work@1" && data.claim === claim.id ? data : null;
}

export function loadLeanIndex(index) {
  return getJson(index.lean_index || "data/lean-index.json");
}

// The content index of every project declaration (lib/retrieval.js), or null when the build has
// none (a full assessment's site).
const retrievals = new Map();
export function loadRetrieval(index) {
  if (!index.retrieval) return Promise.resolve(null);
  if (!retrievals.has(index.retrieval)) {
    const p = getJson(index.retrieval).then((d) => new Retrieval(d));
    retrievals.set(index.retrieval, p);
    p.catch(() => retrievals.delete(index.retrieval));
  }
  return retrievals.get(index.retrieval);
}

export async function loadSearch(index) {
  const data = await getJson(index.search || "data/search.json");
  return data.by_project?.[project.repo] || data;
}

// A claim as the chosen project sees it, on a page with several projects (a paper page): only
// that project's links, with the status the engine gave it for that project. Another project's
// links never show here, and are never combined with these.
export function inProject(c, repo) {
  if (!c.by_project) return c;
  const st = c.by_project[repo] || { status_code: "link.none" };
  const links = c.links && c.links.filter((l) => l.repository === repo);
  const { record, audit, ...facts } = st;
  return { ...c, ...(links ? { links } : {}), ...facts, ...(record || {}),
    id: c.id, paper: c.paper, mode: record ? (record.mode || "full") : c.mode, audit: audit || null,
    status_code: st.status_code, status: statusView(st).label, class: statusView(st).class };

}

// The claims of the index for the chosen project (reactive on the choice).
export function projectClaims(index) {
  if (!index.projects) return index.claims;
  return index.claims.filter((c) => !c.projects || c.projects.includes(project.repo)).map((c) => {
    const row = inProject(c, project.repo);
    if (project.edition !== "original") {
      return { ...row, anchor: row.audit?.edition === project.edition ? row.audit.audit_anchor : null };
    }
    return row;
  });
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

// The review queue the engine wrote (`data/review-queue.json`), if this site has one.
export function loadQueue(index) {
  return getJson(index.review_queue);
}
