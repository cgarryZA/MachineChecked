<script>
  import { loadIndex } from "./lib/data.js";
  import { route, href } from "./lib/route.svelte.js";
  import Coverage from "./components/Coverage.svelte";
  import Reader from "./components/Reader.svelte";
  import Passport from "./components/Passport.svelte";
  import Changes from "./components/Changes.svelte";
  import Search from "./components/Search.svelte";

  let index = $state(null);
  let error = $state(null);
  loadIndex().then((i) => (index = i)).catch((e) => (error = String(e)));

  const firstPaper = $derived(index?.papers[0]?.id);
  const releaseMismatch = $derived(index && route.release && route.release !== index.release);
</script>

{#if error}
  <main class="state"><h1>ProofLens</h1><p>The manifest could not be loaded: {error}</p></main>
{:else if !index}
  <main class="state"><p class="muted">Loading…</p></main>
{:else}
  <header class="top">
    <a class="brand" href={href(index.release, "coverage")}>
      <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden="true"
        ><circle cx="13" cy="13" r="9" fill="none" stroke="currentColor" stroke-width="3" /><path
          d="M20 20l8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg
      >
      <span>ProofLens</span>
      <span class="proj">{index.project?.name}</span>
    </a>
    <nav>
      {#if firstPaper}
        <a class:on={route.view === "read"} href={href(index.release, "read", route.paper || firstPaper)}>Read</a>
      {/if}
      <a class:on={route.view === "coverage"} href={href(index.release, "coverage")}>Coverage</a>
      <a class:on={route.view === "claim"} href={route.claim ? href(index.release, "claim", route.claim) : href(index.release, "coverage")}>Audit</a>
      <a class:on={route.view === "changes"} href={href(index.release, "changes")}>Changes</a>
    </nav>
    <Search {index} />
    <span class="release" title={"evidence " + index.evidence}>release <code>{index.release}</code></span>
  </header>

  {#if releaseMismatch}
    <div class="banner" role="alert">
      This link names release <code>{route.release}</code>; this site shows release
      <code>{index.release}</code>. What it says about the claim may differ.
    </div>
  {/if}

  {#if route.view === "read"}
    <Reader {index} paperId={route.paper || firstPaper} claimId={route.claim} />
  {:else if route.view === "claim" && route.claim}
    <main class="page"><Passport {index} claimId={route.claim} full /></main>
  {:else if route.view === "changes"}
    <Changes {index} />
  {:else}
    <Coverage {index} />
  {/if}
{/if}

<style>
  .state { max-width: 640px; margin: 15vh auto; padding: 0 16px; }
  .top {
    position: sticky; top: 0; z-index: 20;
    display: flex; align-items: center; gap: 20px; flex-wrap: wrap;
    padding: 10px 20px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: 8px; color: var(--accent); font-weight: 650; }
  .brand:hover { text-decoration: none; }
  .proj { color: var(--muted); font-weight: 450; }
  nav { display: flex; gap: 4px; }
  nav a { padding: 4px 10px; border-radius: 6px; color: var(--muted); }
  nav a:hover { background: var(--surface-2); text-decoration: none; }
  nav a.on { background: var(--accent-soft); color: var(--text); }
  .release { margin-left: auto; color: var(--faint); font-size: 13px; }
  .banner { padding: 10px 20px; background: var(--surface-2); border-bottom: 1px solid var(--border); }
  .page { max-width: 980px; margin: 0 auto; padding: 24px 16px 80px; }
  @media (max-width: 640px) {
    .top { gap: 10px; padding: 8px 16px; }
    .release { display: none; }
  }
</style>
