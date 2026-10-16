// Loading of the presentation manifest. The site only reads: every status and finding comes
// from the manifest as written by the engine.

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

// A paper page of machinechecked.org gives its paper in the page (`window.__MACHINECHECKED_PAPER__`,
// a registry entry: the paper, its links, the Lean repositories that formalise it and their
// audits). The reader then shows the paper with what is known about its formalisations, and no
// claims: claims come only from an audit.
export const PAPER = typeof window !== "undefined" && window.__MACHINECHECKED_PAPER__ &&
  typeof window.__MACHINECHECKED_PAPER__ === "object" && !Array.isArray(window.__MACHINECHECKED_PAPER__)
  ? window.__MACHINECHECKED_PAPER__ : null;

const https = (u) => typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u);

function paperIndex(p) {
  const links = p.links || {};
  const arxivPdf = https(links.arxiv) ? links.arxiv.replace("/abs/", "/pdf/") : null;
  const pdf = [links.pdf, arxivPdf].find(https) || null;
  // The claims the site found in the paper's PDF (approximate places), with the links each
  // repository's formalization.yaml declares; no audit, so no claim says what Lean establishes.
  const claims = (Array.isArray(p.claims) ? p.claims : []).filter((c) => c && typeof c.id === "string").map((c) => ({
    id: c.id, paper: "P", number: String(c.number || ""), title: c.title ? String(c.title) : null,
    heading: c.title ? String(c.title) : null, kind: String(c.kind || ""), scope: "formal",
    status: String(c.status || "not linked"), class: Array.isArray(c.links) && c.links.length ? "declared" : "unspecified", counts: {},
    anchor: c.anchor && Number.isFinite(c.anchor.page) ? { kind: "approximate", page: c.anchor.page, y0: Number(c.anchor.y0) || 0,
      y1: Number.isFinite(c.anchor.y1) ? c.anchor.y1 : null, page_end: Number.isFinite(c.anchor.page_end) ? c.anchor.page_end : null } : null,
    links: (Array.isArray(c.links) ? c.links : []).map((l) => ({
      name: String(l.name || ""), status: String(l.status || ""), class: "unspecified",
      source: "formalization.yaml", repository: String(l.repository || ""), why: null, statement: null })),
  }));
  const summary = {};
  for (const c of claims) summary[c.status] = (summary[c.status] || 0) + 1;
  return {
    mode: "paper", schema: "machinechecked/paper@1", release: "paper", evidence: "",
    project: {}, papers: [{ id: "P", title: String(p.title || ""), pdf: null, pdf_url: pdf,
      page_size: Array.isArray(p.page_size) ? p.page_size : null }],
    claims, summary: { P: summary }, classes: {}, findings: { total: {}, general: [] }, gates: {},
    notes: [], paper: p,
  };
}

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
  return siteIndex;
}

async function loadIndexData() {
  if (PAPER && !AUDIT) return paperIndex(PAPER);
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
  if (window.__PROOFLENS__ || AUDIT || PAPER) return false;
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

export function loadClaim(index, id) {
  const c = index.claims.find((x) => x.id === id);
  if (!c) return Promise.reject(new Error(`no claim ${id} in release ${index.release}`));
  if (index.mode === "paper") {
    // A paper page's claim is all there is to show: its number, place and declared links.
    const a = c.anchor;
    const anchor = a && {
      kind: "approximate", begin: [a.page, 0, a.y0],
      end: a.y1 != null ? [a.page, 0, a.y1] : a.page_end ? [a.page_end, 0, 0] : null,
    };
    return Promise.resolve({ ...c, anchor, mode: "simple", key: c.id, suggestions: [], clauses: [],
      blockers: [], findings: [], decls: {}, statement_tex: null, source_matches: null });
  }
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
