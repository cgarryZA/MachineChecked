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
  loadIndex().then((i) => { index = i; editable = canEdit(i); }).catch((e) => (error = String(e)));

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
  <div class="app-shell" class:reading={route.view === "read"}>
  <div class="shell-top">
  <header class="top">
    <a class="brand" href={index.mode === "paper" ? "/" : href(index.release, "read", firstPaper)} aria-label={index.mode === "paper" ? "MachineChecked home" : "Back to the paper"}>
      <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden="true"
        ><circle cx="13" cy="13" r="9" fill="none" stroke="currentColor" stroke-width="3" /><path
          d="M20 20l8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg
      >
      <span>MachineChecked</span>
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
      {@const repos = index.projects || []}
      {#if repos.length > 1}
        <label class="project" title="Choose the project whose evidence to show">
          <span>Formalisation</span>
          <select value={project.repo} onchange={(e) => chooseProject(e.currentTarget.value)} aria-label="Formalisation shown">
            {#each repos as r}<option value={r}>{r}</option>{/each}
          </select>
        </label>
      {/if}
      <a class="aux" href="/papers/">Papers</a>
    {:else}
    {#if index.review_queue}
      <a class="aux" class:on={route.view === "review"} href={href(index.release, "review")}>Review</a>
    {/if}
    <a class="aux" class:on={route.view === "coverage"} href={href(index.release, "coverage")}>Overview</a>
    {/if}
    <Search {index} />
  </header>

  {#if AUDIT && auditInfo}
    <div class="banner attribution">
      <span>Audit by {auditInfo.author || "the project"}</span>
      <a href={href(index.release, "changes")}>Details</a>
    </div>
  {/if}
  {#if releaseMismatch}
    <div class="banner" role="alert">
      Showing release <code>{index.release}</code>. The link requests <code>{route.release}</code>.
    </div>
  {/if}
  {#if index.notes?.length}
    <div class="banner">{#each index.notes as n}<div>{n}</div>{/each}</div>
  {/if}

  </div>
  <div class="workspace">
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
  </div>
  </div>
{/if}

<style>
  .app-shell { min-height: 100dvh; display: grid; grid-template-rows: auto minmax(0, 1fr); }
  .app-shell.reading { height: 100dvh; }
  .shell-top { min-width: 0; z-index: 20; }
  .workspace { min-width: 0; min-height: 0; }
  .reading .workspace { overflow: hidden; }
  .state { max-width: 640px; margin: 15vh auto; padding: 0 16px; }
  .top {
    position: sticky; top: 0; z-index: 20;
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
    padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: 6px; color: var(--accent); font-family: var(--serif); font-weight: 600; }
  .ptitle { font-family: var(--serif); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40vw; }
  .papers { display: flex; gap: 4px; }
  .papers a, .aux { padding: 4px 10px; border-radius: 6px; color: var(--muted); white-space: nowrap; }
  .papers a:hover, .aux:hover { background: var(--surface-2); text-decoration: none; }
  .papers a.on, .aux.on { background: var(--accent-soft); color: var(--text); }
  .aux { font-size: 14px; }
  :global(.top .aux:first-of-type) { margin-left: auto; }
  .banner { padding: 8px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); font-size: 14px; }
  .attribution { display: flex; gap: 12px; align-items: baseline; font-size: 13px; }
  .page { max-width: 1560px; margin: 0 auto; padding: 24px 16px 80px; }
  @media (max-width: 640px) {
    .top { gap: 8px; padding: 8px 12px; flex-wrap: wrap; }
    .ptitle { max-width: 100%; flex: 1 1 180px; font-size: 14px; }
    .brand span { display: none; }
  }
  .project { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); margin-left: auto; }
  .project select { font: inherit; max-width: min(42vw, 320px); padding: 3px 6px; border-radius: 6px; border: 1px solid var(--accent); background: var(--surface); color: var(--text); }
</style>
