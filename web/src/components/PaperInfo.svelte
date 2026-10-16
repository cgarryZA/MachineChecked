<script>
  // What is known about a paper's formalisations, beside the paper: the Lean repositories that
  // formalise it (one at a time, chosen at the top when there are several), who says so, the
  // project's own description of its review, and the audits published of it. Nothing here is a
  // judgement of the formalisation: without an audit, it says nothing about what Lean establishes.
  import { project } from "../lib/project.svelte.js";
  let { paper } = $props();

  const https = (u) => typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u);
  const repoOk = (r) => typeof r === "string" && /^[\w.-]+\/[\w.-]+$/.test(r);
  const shaOk = (c) => typeof c === "string" && /^[0-9a-f]{40}$/.test(c);
  const fs = $derived((paper.formalisations || []).filter((f) => repoOk(f.repository) && shaOk(f.commit)));
  // The project chosen for the whole page (at the top of the page when there are several).
  const f = $derived(fs.find((x) => x.repository === project.repo) || fs[0]);
  const audits = $derived((f?.audits || []).filter((a) => https(a.url)));
  const links = $derived(paper.links || {});
  const pdf = $derived([links.pdf, https(links.arxiv) ? links.arxiv.replace("/abs/", "/pdf/") : null].find(https));
  const arxivId = $derived(String(paper.id || "").startsWith("arxiv:") ? paper.id.slice(6) : null);

  function provenance(f) {
    const s = f.stated_by || {};
    return s.source === "formalization.yaml" ? "Linked by the repository's formalization.yaml" : "Listed by the site's maintainer";
  }
  function reportUrl(f) {
    const title = `Listing: ${f.repository} for ${paper.id}`;
    const body = `**Paper:** ${paper.title} (\`${paper.id}\`)\n**Repository:** ${f.repository} at \`${f.commit.slice(0, 12)}\`\n\n### What is wrong with this listing\n\n`;
    return "https://github.com/cgarryZA/machinechecked.org/issues/new?" + new URLSearchParams({ title, body });
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
      <p class="faint small">One of {fs.length} formalisations, chosen at the top of the page. Separate projects are separate evidence; their results are never combined.</p>
    {/if}
    <div class="card">
      <p class="repo"><a href={`https://github.com/${f.repository}/tree/${f.commit}`} target="_blank" rel="noopener"><code>{f.repository}</code></a></p>
      <p class="small muted">
        {provenance(f)}{#if f.stated_by?.source === "formalization.yaml"}&nbsp;· <a href={`https://github.com/${f.repository}/blob/${f.commit}/formalization.yaml`} target="_blank" rel="noopener">view it</a>{/if}&nbsp;· at <code>{f.commit.slice(0, 12)}</code>
      </p>
      {#if f.review_status}<p class="small muted">The project describes its own review as “{f.review_status}”.</p>{/if}
      {#if audits.length}
        {#each audits as a}
          <p><a class="btn" href={"/read/?audit=" + encodeURIComponent(a.url)}>Open the audit</a> <span class="small">by {a.author}</span></p>
        {/each}
        <p class="faint small">An audit records what its author linked, checked and reviewed; MachineChecked does not endorse it.</p>
      {:else}
        <p class="small">No claim-level audit is published yet.</p>
      {/if}
      <p class="small"><a href={reportUrl(f)} target="_blank" rel="noopener">Report this listing</a></p>
    </div>
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
  .card { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px; background: var(--surface); }
  .card p { margin: 4px 0; }
  .repo { font-size: 15px; overflow-wrap: anywhere; }
  .btn { display: inline-block; padding: 4px 12px; border-radius: 6px; background: var(--accent); color: var(--surface); text-decoration: none; }
  .related { margin-top: 18px; }
  .related summary { cursor: pointer; color: var(--muted); }
  .related ul { padding-left: 18px; }
  .related li { margin: 6px 0; }
  .small { font-size: 13px; }
  .muted { color: var(--muted); } .faint { color: var(--faint); }
</style>
