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
  if (!index.issues || !/^[\w.-]+\/[\w.-]+$/.test(index.issues)) return null;
  const paper = (index.papers || []).find((p) => p.id === claim.paper) || {};
  const link = claimLink(index, claim);
  const lean = leanNames(claim);
  const lines = [
    `**Claim:** ${claim.number || "(unnumbered)"} — \`${claim.id}\``,
    `**Paper:** ${paper.title || claim.paper}${paper.revision ? ` (revision \`${String(paper.revision).slice(0, 12)}\`)` : ""}`,
    `**Lean:** ${lean.length ? lean.map((n) => "`" + n + "`").join(", ") : "(no declaration linked)"}`,
    `**Project commit:** ${index.project?.commit ? "`" + index.project.commit.slice(0, 12) + "`" : "(unknown)"}`,
    `**Status shown:** ${claim.status} (release \`${index.release}\`)`,
    `**Claim in the reader:** ${link || "(not published: " + claimReference(index, claim) + ")"}`,
    "",
    "### What looks wrong",
    "",
    "<!-- Which hypothesis, quantifier, definition or conclusion differs between the paper and the Lean, and where. -->",
    "",
    "---",
    "_Opened from the MachineChecked reader. A report changes no status in the audit._",
  ];
  const title = `[${claim.number || claim.id}] Possible paper/Lean mismatch`;
  const q = new URLSearchParams({ title, body: lines.join("\n") });
  return `https://github.com/${index.issues}/issues/new?${q.toString()}`;
}
