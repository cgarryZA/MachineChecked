// Hash routes. Every route may carry the release it was made for, `#/r/<release>/...`, so a
// link names one snapshot of the evidence and never silently resolves to a later one.
//
//   #/                       the first paper
//   #/read/<paper>[/<claim>] the paper with the passport of a claim beside it
//   #/overview               every claim by status
//   #/claim/<claim>          the passport alone
//   #/changes                what changed between releases
//   #/review                 the review queue

function parse(hash) {
  const [path, query = ""] = hash.split("?");
  const params = new URLSearchParams(query);
  const state = { inspection: params.getAll("inspect"), compare: params.get("compare") === "1", target: params.get("claim"), readerSeen: params.get("seen") === "lean" };
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

window.addEventListener("hashchange", () => Object.assign(route, { paper: null, claim: null }, parse(location.hash)));

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
