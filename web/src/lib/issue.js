import { statusView } from "./presentation.js";
// Reporting a problem with a claim: a pre-filled GitHub issue in the audit's own repository, and
// a link to the claim pinned to its release.
//
// The issue carries identifiers only (the claim, the Lean declarations, the commits, the release,
// the link): never the statement's text, so nothing unpublished leaves through a report. Nothing
// is sent from here; GitHub opens with the draft, and the reporter writes what is wrong and
// submits it. A report changes no status.

import { href } from "./route.svelte.js";

// The public address of the claim at this release, if the site has one: the configured
// `site_url`, else the page's own address when it is served from a public host.
export function claimLink(index, claim) {
  if (claim.audit?.link) return new URL(claim.audit.link, location.href).href;
  let base = index.site_url || null;
  if (!base && /^https?:$/.test(location.protocol) &&
      !/^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname)) {
    base = location.origin + location.pathname + location.search;
  }
  if (!base) return null;
  const u = new URL(base.replace(/#.*$/, ""));
  if (!u.pathname.endsWith("/")) u.pathname += "/";
  return u.href + href(index.release, "read", claim.paper, claim.id);
}

// A reference to the claim that does not depend on where the site is served.
export function claimReference(index, claim) {
  return `${claim.id} (${claim.number || "unnumbered"}), release ${index.release}`;
}

function leanNames(claim) {
  const names = [];
  for (const cl of claim.clauses || []) for (const k of ["spec", "accept", "refute"]) if (cl[k]) names.push(cl[k]);
  for (const l of claim.links || []) names.push(l.name);
  return [...new Set(names)];
}

export function issueUrl(index, claim) {
  if (claim.audit?.claim) claim = { ...claim, id: claim.audit.claim, paper: claim.audit.paper?.id || claim.paper };
  if (!index.issues || !/^[\w.-]+\/[\w.-]+$/.test(index.issues)) return null;
  const paper = (index.papers || []).find((p) => p.id === claim.paper) || {};
  const link = claimLink(index, claim);
  const lean = leanNames(claim);
  const lines = [
    `**Claim:** ${claim.number || "(unnumbered)"} — \`${claim.id}\``,
    `**Paper:** ${paper.title || claim.paper}${paper.revision ? ` (revision \`${String(paper.revision).slice(0, 12)}\`)` : ""}`,
    `**Lean:** ${lean.length ? lean.map((n) => "`" + n + "`").join(", ") : "(no declaration linked)"}`,
    `**Project commit:** ${index.project?.commit ? "`" + index.project.commit.slice(0, 12) + "`" : "(unknown)"}`,
    `**Status shown:** ${statusView(claim).label} (release \`${index.release}\`)`,
    `**Claim in the reader:** ${link || "(not published: " + claimReference(index, claim) + ")"}`,
    "",
    "### What looks wrong",
    "",
    "<!-- Which hypothesis, quantifier, definition or conclusion differs between the paper and the Lean, and where. -->",
    "",
    "---",
    "_Drafted from the MachineChecked reader._",
  ];
  const title = `[${claim.number || claim.id}] Possible paper/Lean mismatch`;
  const q = new URLSearchParams({ title, body: lines.join("\n") });
  return `https://github.com/${index.issues}/issues/new?${q.toString()}`;
}

// The reports already opened about the claim: a GitHub search of the audit's issue repository
// for the claim's identifier, which every report body carries.
export function reportsUrl(index, claim) {
  if (claim.audit?.claim) claim = { ...claim, id: claim.audit.claim, paper: claim.audit.paper?.id || claim.paper };
  if (!index.issues || !/^[\w.-]+\/[\w.-]+$/.test(index.issues)) return null;
  const q = new URLSearchParams({ q: `is:issue in:body "${claim.id}"` });
  return `https://github.com/${index.issues}/issues?${q.toString()}`;
}

// The declaration's source on GitHub, at the commit the evidence is for, when the project's
// repository is known and the file is the project's own.
export function sourceUrl(index, path, line) {
  const repo = index.project?.repository;
  const commit = index.project?.commit;
  if (!repo || !/^[\w.-]+\/[\w.-]+$/.test(repo) || !/^[0-9a-f]{7,40}$/.test(commit || "")) return null;
  if (!path || !/^[\w.'/-]+\.lean$/.test(path) || path.split("/").includes("..")) return null;
  const n = Number.isInteger(line) && line > 0 ? `#L${line}` : "";
  return `https://github.com/${repo}/blob/${commit}/${path.split("/").map(encodeURIComponent).join("/")}${n}`;
}

// A module's source, when the module is the project's own: its file under the project's path in
// the repository.
export function moduleSourceUrl(index, module, line) {
  const pr = index.project || {};
  if (!module || !/^[\w.']+$/.test(module) || !(pr.source_roots || []).includes(module.split(".")[0])) return null;
  const prefix = pr.source_prefix || "";
  if (!/^([\w.'-]+\/)*$/.test(prefix)) return null;
  return sourceUrl(index, prefix + module.replaceAll(".", "/") + ".lean", line);
}

// The source link's words: a private repository is not named, and the link says it will open
// only for people with access.
export function sourceLabel(index) {
  return index.project?.repository_private ? "Lean source (private repository) ↗" : "Lean source ↗";
}
export function sourceTitle(index) {
  return index.project?.repository_private
    ? "The repository is private: this opens only for people with access to it."
    : `The declaration in ${index.project?.repository} at the audited commit`;
}
