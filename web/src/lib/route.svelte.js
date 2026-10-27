// Hash routes. Every route may carry the release it was made for, `#/r/<release>/...`, so a
// link names one snapshot of the evidence and never silently resolves to a later one.
//
//   #/                       the first paper
//   #/read/<paper>[/<claim>] the paper with the passport of a claim beside it
//   #/overview               every claim, with its correspondence, basis, review and status;
//                            `?set=&unit=&coverage=&basis=&review=&finding=&status=` choose the
//                            readings shown and filter the claims
//   #/claim/<claim>          the passport alone
//   #/changes                what changed between releases
//   #/review                 the review queue
//
// A claim's inspections are in the query of its route: `?inspect=<token>…&at=<row>`
// (lib/inspect.svelte.js).

export const OVERVIEW_FILTERS = ["set", "unit", "coverage", "basis", "review", "finding", "status"];

function parse(hash) {
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  const state = { inspection: params.getAll("inspect"), at: params.get("at"), compare: params.get("compare") === "1", target: params.get("claim"), readerSeen: params.get("seen") === "lean",
    filters: Object.fromEntries(OVERVIEW_FILTERS.map((k) => [k, params.get(k)])) };
  let parts = path.replace(/^#\/?/, "").split("/").map((s) => { try { return decodeURIComponent(s); } catch { return s; } });
  let release = null;
  if (parts[0] === "r" && parts.length > 1) {
    release = parts[1];
    parts = parts.slice(2);
  }
  const [view, ...rest] = parts;
  if (view === "read") return { ...state, release, view: "read", paper: rest[0], claim: rest.slice(1).join("/") || null };
  if (view === "claim") return { ...state, release, view: "claim", claim: rest.join("/") };
  if (view === "changes") return { ...state, release, view: "changes" };
  if (view === "review") return { ...state, release, view: "review" };
  if (view === "overview" || view === "coverage") return { ...state, release, view: "coverage" };
  return { ...state, release, view: "read", paper: null, claim: null };
}

export const route = $state(parse(location.hash));

// Only what changed is written, so that a view of the same claim (whose inspections the query
// holds) is not drawn again from the start.
window.addEventListener("hashchange", () => {
  const next = { paper: null, claim: null, ...parse(location.hash) };
  for (const [k, v] of Object.entries(next)) if (JSON.stringify(route[k]) !== JSON.stringify(v)) route[k] = v;
});

export function href(release, view, ...args) {
  const tail = args.filter((a) => a != null && a !== "").map(encodeURIComponent).join("/");
  const name = view === "coverage" ? "overview" : view;
  const base = name + (tail ? "/" + tail : "");
  return `#/r/${encodeURIComponent(release)}/${base}`;
}

export function go(url) {
  if (location.hash !== url) location.hash = url;
}

export function withQuery(url, values) {
  const [path, query = ""] = url.split("?");
  const params = new URLSearchParams(query);
  for (const [key, value] of Object.entries(values)) {
    params.delete(key);
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item != null && item !== false) params.append(key, String(item));
    }
  }
  return path + (params.size ? "?" + params : "");
}

export const inspectionHref = (names) => withQuery(location.hash, { inspect: names });
