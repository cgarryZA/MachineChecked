// Loading of the presentation manifest. The site only reads: every status and finding comes
// from the manifest as written by the engine.

const cache = new Map();

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
      fetch(path).then((r) => {
        if (!r.ok) throw new Error(`${path}: ${r.status}`);
        return r.json();
      }),
    );
  }
  return cache.get(path);
}

export function loadIndex() {
  return getJson("data/index.json");
}

// Whether the page is served by `prooflens view`, which can save links into the repository.
export async function canEdit() {
  if (window.__PROOFLENS__) return false;
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
