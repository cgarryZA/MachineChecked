// Hash routes. Every route may carry the release it was made for, `#/r/<release>/...`, so a
// link names one snapshot of the evidence and never silently resolves to a later one.
//
//   #/                       coverage
//   #/read/<paper>[/<claim>] the paper with the passport of a claim beside it
//   #/claim/<claim>          the passport alone
//   #/changes                what changed between releases

function parse(hash) {
  let parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  let release = null;
  if (parts[0] === "r" && parts.length > 1) {
    release = parts[1];
    parts = parts.slice(2);
  }
  const [view, ...rest] = parts;
  if (view === "read") return { release, view: "read", paper: rest[0], claim: rest.slice(1).join("/") || null };
  if (view === "claim") return { release, view: "claim", claim: rest.join("/") };
  if (view === "changes") return { release, view: "changes" };
  return { release, view: "coverage" };
}

export const route = $state(parse(location.hash));

window.addEventListener("hashchange", () => Object.assign(route, { paper: null, claim: null }, parse(location.hash)));

export function href(release, view, ...args) {
  const tail = args.filter((a) => a != null && a !== "").map(encodeURIComponent).join("/");
  const base = view === "coverage" ? "" : view + (tail ? "/" + tail : "");
  return `#/r/${encodeURIComponent(release)}/${base}`;
}

export function go(url) {
  if (location.hash !== url) location.hash = url;
}
