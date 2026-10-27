<script>
  // What is known about a paper's formalisations, beside the paper: the Lean repositories that
  // formalise it (one at a time, chosen at the top when there are several, or every audited one
  // when the audits are shown together), who says so, the project's description of its review,
  // and its published audits, each with the version of the paper it pins and its commit.
  import { project } from "../lib/project.svelte.js";
  import { auditOf } from "../lib/data.js";
  import { pageVersions, versionHref, versionLabel } from "../lib/versions.js";
  let { paper, index = null } = $props();

  const https = (u) => typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u);
  const repoOk = (r) => typeof r === "string" && /^[\w.-]+\/[\w.-]+$/.test(r);
  // The site gives each listing's report link (a new issue on its own repository).
  const reportOk = (u) => typeof u === "string" && u.startsWith("https://github.com/cgarryZA/machinechecked.org/issues/new?");
  const shaOk = (c) => typeof c === "string" && /^[0-9a-f]{40}$/.test(c);
  const fs = $derived((paper.formalisations || []).filter((f) => repoOk(f.repository) && shaOk(f.commit)));
  // The projects shown: the one chosen for the whole page (at the top of the page when there are
  // several), or, with the audits shown together, every audited one in the order they are used.
  const shown = $derived(project.combined
    ? project.order.map((r) => fs.find((x) => x.repository === r)).filter(Boolean)
    : [fs.find((x) => x.repository === project.repo) || fs[0]].filter(Boolean));
  const links = $derived(paper.links || {});
  const pdf = $derived([links.pdf, https(links.arxiv) ? links.arxiv.replace("/abs/", "/pdf/") : null].find(https));
  const arxivId = $derived(String(paper.id || "").startsWith("arxiv:") ? paper.id.slice(6) : null);
  const versions = $derived(pageVersions(index));
  const same = (a, b) => String(a || "").replace(/\/+$/, "") === String(b || "").replace(/\/+$/, "");

  function provenance(f) {
    const s = f.stated_by || {};
    return s.source === "formalization.yaml" ? "Linked by the repository's formalization.yaml" : "Listed by the site's maintainer";
  }

  // An audit the site could not load: machinechecked.org gives each registered audit its `state`
  // (and `detail`, why it did not load). It is shown with its reason, never as this page's audit.
  const failedState = (a) => a.state === "unavailable" || a.state === "incompatible";
  const why = (s) => `Audit ${s.state}${typeof s.detail === "string" && s.detail ? ": " + s.detail : ""}`;

  // A listing's audits, each placed by the version it pins: this page's (`here`), another version
  // with its own page (`href`), or neither (an audit this page could not place). An audit the site
  // says did not load is `failed`; one without a state is placed as the others. The version's
  // label is MachineChecked's, from the page's versions or from the audit this page loaded, never
  // one the listing supplies.
  function placed(f) {
    const loaded = auditOf(index, f.repository);
    return (f.audits || []).filter((a) => https(a.url)).map((a) => {
      if (failedState(a)) return { ...a, failed: true, label: null, commit: null, here: false, href: null };
      const onPage = !!loaded && same(loaded.url, a.url);
      const v = versions.find((x) => (x.audits || []).some((y) => same(y.url, a.url) && (!y.repository || y.repository === f.repository)));
      if (v) {
        const entry = v.audits.find((y) => same(y.url, a.url));
        const here = v.id === index?.version;
        return { ...a, label: versionLabel(v), here, href: here ? null : versionHref(v, project.combined ? null : f.repository),
          commit: shaOk(entry.commit) ? entry.commit : here && onPage ? loaded.commit : null };
      }
      if (onPage) return { ...a, label: loaded.paper_version ? versionLabel(loaded.paper_version) : null, commit: shaOk(loaded.commit) ? loaded.commit : null, here: true };
      return { ...a, label: null, commit: null, here: !versions.length && !loaded };
    });
  }
</script>

<div class="info">
  <p class="who">{(paper.authors || []).join(", ")}{paper.year ? " · " + paper.year : ""}</p>
  <p class="src small">
    {#if arxivId}<a href={"https://arxiv.org/abs/" + arxivId} target="_blank" rel="noopener">arXiv:{arxivId}</a> · {/if}
    {#if pdf}<a href={pdf} target="_blank" rel="noopener">Original PDF ↗</a>{/if}
  </p>

  <h2>Lean</h2>
  {#if !fs.length}
    <p class="muted">No Lean formalisation of this paper is listed.</p>
  {:else}
    {#if fs.length > 1}
      <p class="faint small">Choose from {fs.length} formalisations at the top of the page.</p>
    {/if}
    {#each shown as f, i (f.repository)}
    {@const audits = placed(f)}
    {@const here = audits.filter((a) => a.here)}
    {@const elsewhere = audits.filter((a) => !a.here && a.href)}
    {@const unplaced = audits.filter((a) => !a.here && !a.href && !a.failed)}
    {@const failed = audits.filter((a) => a.failed)}
    <div class="card" data-repository={f.repository}>
      {#if project.combined}<p class="small faint rank">{i === 0 ? "Default audit" : `Audit ${i + 1}`}{Number.isInteger(index?.stars?.[f.repository]) ? ` · ${index.stars[f.repository]} GitHub ${index.stars[f.repository] === 1 ? "star" : "stars"}` : ""}</p>{/if}
      <p class="repo"><a href={`https://github.com/${f.repository}/tree/${f.commit}`} target="_blank" rel="noopener"><code>{f.repository}</code></a></p>
      <p class="small muted">
        {provenance(f)}{#if f.stated_by?.source === "formalization.yaml"}&nbsp;· <a href={`https://github.com/${f.repository}/blob/${f.commit}/formalization.yaml`} target="_blank" rel="noopener">view it</a>{/if}&nbsp;· at <code>{f.commit.slice(0, 12)}</code>
      </p>
      {#if f.review_status}<p class="small muted">Project review: {f.review_status}</p>{/if}
      {#if failedState(f.audit_state || {}) && !failed.some((a) => why(a) === why(f.audit_state))}
        <p class="small">Audit {f.audit_state.state}: {f.audit_state.detail}</p>
      {/if}
      {#each here as a}
        <p class="audit here"><a class="btn" href={"/read/?audit=" + encodeURIComponent(a.url)}>Open the audit{a.label ? " of " + a.label : ""}</a>
          <span class="small">by {a.author}{#if a.commit}{" · commit "}<code>{a.commit.slice(0, 12)}</code>{/if}</span></p>
      {/each}
      {#each unplaced as a}
        <p class="audit small"><a href={"/read/?audit=" + encodeURIComponent(a.url)}>Open the audit</a> by {a.author}</p>
      {/each}
      {#each failed as a}
        <p class="audit failed small" data-state={a.state}>{why(a)}<br>
          <a href={"/read/?audit=" + encodeURIComponent(a.url)}>Open the audit</a> by {a.author}</p>
      {/each}
      {#if elsewhere.length}
        <p class="small muted">{here.length ? "Audits of other versions:" : "Audits of other versions of the paper:"}</p>
        <ul class="elsewhere">
          {#each elsewhere as a}<li class="small"><a href={a.href}>{a.label}</a>{" · by " + a.author}{#if a.commit}{" · commit "}<code>{a.commit.slice(0, 12)}</code>{/if}</li>{/each}
        </ul>
      {/if}
      {#if !audits.length}
        <p class="small">No claim-level audit is published yet.</p>
      {:else if !here.length && !unplaced.length && !failed.length}
        <p class="small">No audit of this version of the paper is published yet.</p>
      {/if}
      {#if reportOk(f.report_url)}<p class="small"><a href={f.report_url} target="_blank" rel="noopener">Report this listing</a></p>{/if}
    </div>
    {/each}
  {/if}

  {#if paper.related?.length}
    <details class="related">
      <summary>Related research ({paper.related.length})</summary>
      <ul>
        {#each paper.related.filter((r) => https(r.url)) as r}
          <li><a href={r.url} target="_blank" rel="noopener">{r.title}</a>{#if r.authors?.length}<span class="muted"> — {r.authors.join(", ")}</span>{/if}{#if r.note}<div class="faint small">{r.note}</div>{/if}</li>
        {/each}
      </ul>
    </details>
  {/if}
</div>

<style>
  .info { font-size: 14px; }
  .who { margin: 0 0 2px; font-size: 15px; }
  .src { margin: 0 0 14px; }
  h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--faint); margin: 16px 0 8px; }
  .card + .card { margin-top: 10px; }
  .rank { margin: 0 0 2px; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px; }
  .elsewhere { margin: 2px 0 4px; padding-left: 18px; }
  .elsewhere li { margin: 2px 0; overflow-wrap: anywhere; }
  .card { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--surface); }
  .card p { margin: 4px 0; }
  .repo { font-size: 15px; overflow-wrap: anywhere; }
  .failed { overflow-wrap: anywhere; }
  .btn { display: inline-block; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: var(--surface); text-decoration: none; }
  .related { margin-top: 18px; }
  .related summary { cursor: pointer; color: var(--muted); }
  .related ul { padding-left: 18px; }
  .related li { margin: 6px 0; }
  .small { font-size: 13px; }
  .muted { color: var(--muted); } .faint { color: var(--faint); }
</style>
