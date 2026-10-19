<script>
  import TexInline from "./TexInline.svelte";
  import { projectClaims } from "../lib/data.js";
  import { statusView, statusSummary } from "../lib/presentation.js";
  import { href } from "../lib/route.svelte.js";
  import EvidenceSummary from "./EvidenceSummary.svelte";
  let { index } = $props();
  let query = $state(""), filter = $state("all");
  const claims = $derived(projectClaims(index));
  const counts = $derived(statusSummary(claims));
  const shown = $derived(claims.filter((c) => (filter === "all" || c.status_code === filter) &&
    query.toLowerCase().trim().split(/\s+/).every((w) => `${c.number} ${c.heading || ""} ${c.title || ""} ${c.id}`.toLowerCase().includes(w))));
</script>
<main class="coverage">
  <h1>Overview</h1>
  <p class="muted">Claims, proof results and correspondence reviews.</p>
  <label class="search">Find a claim <input type="search" bind:value={query} placeholder="Number or mathematical title" /></label>
  <div class="filters" aria-label="Filter claims by status">
    <button class:on={filter === "all"} aria-pressed={filter === "all"} onclick={() => filter = "all"}>All ({claims.length})</button>
    {#each counts as row}<button class:on={filter === row.status_code} aria-pressed={filter === row.status_code} onclick={() => filter = row.status_code}>{statusView(row).label} ({row.count})</button>{/each}
  </div>
  <p class="count" role="status">{shown.length} claim{shown.length === 1 ? "" : "s"}</p>
  {#each index.papers as paper}
    {@const rows = shown.filter((c) => c.paper === paper.id)}
    {#if rows.length}
      <section class="paper">
        <div class="phead"><h2><TexInline text={paper.title} /></h2><a href={href(index.release, "read", paper.id)}>Read paper →</a></div>
        <ul class="claims">
          {#each rows as c (c.id)}
            <li data-status={c.status_code}><a class="claim" href={href(index.release, "read", c.paper, c.id)}><strong>{c.number || c.id}</strong>{#if c.heading || c.title}<span><TexInline text={c.heading || c.title} /></span>{/if}</a><EvidenceSummary record={c} /></li>
          {/each}
        </ul>
      </section>
    {/if}
  {/each}
  {#if !shown.length}<p>No claims match this selection. <button class="reset" onclick={() => { filter = "all"; query = ""; }}>Show all claims</button></p>{/if}
  {#if index.gates && Object.keys(index.gates).length}
    <details class="checks"><summary>Paper checks</summary>
      {#each index.papers as p}
        {#if index.gates[p.id]}
          {@const g = index.gates[p.id]}
          <h3>{p.title}</h3>
          <details><summary>Consistency check: {g.consistency.pass ? "passed" : "failed"}</summary><ul>{#each g.consistency.failures || [] as f}<li>{f}</li>{/each}</ul></details>
          <details><summary>Release gate: {g.release.pass ? "passed" : "not passed"}</summary><ul>{#each g.release.reasons || [] as reason}<li>{reason}</li>{/each}</ul></details>
        {/if}
      {/each}
    </details>
  {/if}
</main>
<style>
  .coverage { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
  h1, h2 { font-family: var(--serif); }
  h1 { font-size: 30px; }
  h2 { font-size: 22px; }
  h3 { margin: 18px 0 8px; }
  .search { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
  input { font: inherit; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); width: min(420px, 100%); }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
  button { font: inherit; font-size: 14px; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; background: var(--surface); color: var(--text); cursor: pointer; }
  button.on { background: var(--accent-soft); border-color: var(--accent); }
  .count { color: var(--muted); font-size: 14px; }
  .paper { margin-top: 28px; }
  .phead { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: baseline; }
  .claims { list-style: none; padding: 0; margin: 16px 0; }
  .claims li { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .7fr); gap: 12px 28px; padding: 14px 0; border-bottom: 1px solid var(--border); align-items: baseline; }
  .claim { display: flex; gap: 6px; flex-direction: column; overflow-wrap: anywhere; }
  .claim span { color: var(--text); font-family: var(--serif); font-size: 17px; }
  .checks { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); }
  summary { cursor: pointer; padding: 6px 0; }
  @media (max-width: 700px) { .claims li { grid-template-columns: minmax(0, 1fr); } input { font-size: 16px; } }
</style>
