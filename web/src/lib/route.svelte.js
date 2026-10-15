// Hash routes. Every route may carry the release it was made for, `#/r/<release>/...`, so a
// link names one snapshot of the evidence and never silently resolves to a later one.
//
//   #/                       the first paper
//   #/read/<paper>[/<claim>] the paper with the passport of a claim beside it
//   #/overview               every claim by status
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
  if (view === "overview" || view === "coverage") return { release, view: "coverage" };
  return { release, view: "read", paper: null, claim: null };
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
