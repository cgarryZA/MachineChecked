<script>
  import { loadIndex, canEdit, auditInfo, AUDIT } from "./lib/data.js";
  import { project, chooseProject } from "./lib/project.svelte.js";
  import { route, href } from "./lib/route.svelte.js";
  import Coverage from "./components/Coverage.svelte";
  import Reader from "./components/Reader.svelte";
  import Passport from "./components/Passport.svelte";
  import Changes from "./components/Changes.svelte";
  import Search from "./components/Search.svelte";
  import TexInline from "./components/TexInline.svelte";
  import Review from "./components/Review.svelte";

  let index = $state(null);
  let error = $state(null);
  let editable = $state(false);
  loadIndex().then((i) => (index = i)).catch((e) => (error = String(e)));
  canEdit().then((e) => (editable = e));

  const firstPaper = $derived(index?.papers[0]?.id);
  const paperId = $derived(route.paper || firstPaper);
  const paper = $derived(index?.papers.find((p) => p.id === paperId));
  const releaseMismatch = $derived(index && route.release && route.release !== index.release);
</script>

{#if error}
  <main class="state"><h1>MachineChecked</h1><p>The site's data could not be loaded: {error}</p></main>
{:else if !index}
  <main class="state"><p class="muted">Loading…</p></main>
{:else}
  <header class="top">
    <a class="brand" href={index.mode === "paper" ? "/" : href(index.release, "read", firstPaper)} title="MachineChecked">
      <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden="true"
        ><circle cx="13" cy="13" r="9" fill="none" stroke="currentColor" stroke-width="3" /><path
          d="M20 20l8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg
      >
    </a>
    {#if index.papers.length > 1}
      <nav class="papers">
        {#each index.papers as p}
          <a class:on={route.view === "read" && p.id === paperId} href={href(index.release, "read", p.id)} title={p.title}>Paper {p.id}</a>
        {/each}
      </nav>
    {:else if paper}
      <span class="ptitle" title={paper.title}><TexInline text={paper.title} /></span>
    {/if}
    {#if index.mode === "paper"}
      {@const repos = (index.paper.formalisations || []).map((f) => f.repository)}
      {#if repos.length > 1}
        <label class="project" title="Separate projects are separate evidence; the page shows one at a time">
          <span>Formalisation</span>
          <select value={project.repo} onchange={(e) => chooseProject(e.currentTarget.value)} aria-label="Formalisation shown">
            {#each repos as r}<option value={r}>{r}</option>{/each}
          </select>
        </label>
      {/if}
      <a class="aux" href="/papers/">Papers</a>
    {:else}
    <Search {index} />
    {#if index.review_queue}
      <a class="aux" class:on={route.view === "review"} href={href(index.release, "review")}>Review</a>
    {/if}
    <a class="aux" class:on={route.view === "coverage"} href={href(index.release, "coverage")}>Overview</a>
    {/if}
  </header>

  {#if AUDIT && auditInfo}
    <div class="banner">
      An audit published by {auditInfo.author || "its author"} at
      <code>{new URL(AUDIT.href).host}</code>. It records what its author linked, checked and
      reviewed; MachineChecked displays it and does not endorse it.
    </div>
  {/if}
  {#if releaseMismatch}
    <div class="banner" role="alert">
      This link names release <code>{route.release}</code>; this page shows release
      <code>{index.release}</code>. What it says about the claim may differ.
    </div>
  {/if}
  {#if index.notes?.length}
    <div class="banner">{#each index.notes as n}<div>{n}</div>{/each}</div>
  {/if}

  {#if route.view === "claim" && route.claim}
    <main class="page"><Passport {index} claimId={route.claim} full {editable} /></main>
  {:else if route.view === "coverage"}
    <Coverage {index} />
  {:else if route.view === "changes"}
    <Changes {index} />
  {:else if route.view === "review" && index.review_queue}
    <Review {index} />
  {:else}
    <Reader {index} paperId={paperId} claimId={route.claim} {editable} />
  {/if}
{/if}

<style>
  .state { max-width: 640px; margin: 15vh auto; padding: 0 16px; }
  .top {
    position: sticky; top: 0; z-index: 20;
    display: flex; align-items: center; gap: 16px;
    padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; color: var(--accent); }
  .ptitle { font-family: var(--serif); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40vw; }
  .papers { display: flex; gap: 4px; }
  .papers a, .aux { padding: 4px 10px; border-radius: 6px; color: var(--muted); white-space: nowrap; }
  .papers a:hover, .aux:hover { background: var(--surface-2); text-decoration: none; }
  .papers a.on, .aux.on { background: var(--accent-soft); color: var(--text); }
  .aux { font-size: 14px; }
  :global(.top .aux:first-of-type) { margin-left: auto; }
  .banner { padding: 8px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); font-size: 14px; }
  .page { max-width: 900px; margin: 0 auto; padding: 24px 16px 80px; }
  @media (max-width: 640px) {
    .top { gap: 8px; padding: 8px 12px; flex-wrap: wrap; }
    .ptitle { display: none; }
  }
  .project { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); margin-left: auto; }
  .project select { font: inherit; max-width: 34vw; padding: 3px 6px; border-radius: 6px; border: 1px solid var(--accent); background: var(--surface); color: var(--text); }
</style>
