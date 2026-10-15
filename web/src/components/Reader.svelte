<script>
  import { href, go } from "../lib/route.svelte.js";
  import PdfView from "./PdfView.svelte";
  import Passport from "./Passport.svelte";

  let { index, paperId, claimId } = $props();

  const paper = $derived(index.papers.find((p) => p.id === paperId));
  const claims = $derived(index.claims.filter((c) => c.paper === paperId));
  const unanchored = $derived(claims.filter((c) => !c.anchor && !c.status.startsWith("out of scope")));

  function select(id) {
    go(href(index.release, "read", paperId, id));
  }
  function close() {
    go(href(index.release, "read", paperId));
  }
</script>

{#if !paper}
  <main class="msg"><p>No paper <code>{paperId}</code> in this release.</p></main>
{:else}
  <div class="reader" class:open={!!claimId}>
    <section class="paperpane" aria-label="Paper">
      {#if paper.pdf}
        <PdfView url={"data/" + paper.pdf} {claims} selected={claimId} onselect={select} />
      {:else}
        <div class="msg">
          <p>The PDF of this paper is not part of this site.</p>
          <ul>
            {#each claims as c (c.id)}
              <li><button class="link" onclick={() => select(c.id)}>{c.number || c.id}</button> — {c.status}</li>
            {/each}
          </ul>
        </div>
      {/if}
      {#if unanchored.length}
        <details class="unanchored">
          <summary>{unanchored.length} claim{unanchored.length === 1 ? " is" : "s are"} not located in the PDF</summary>
          <ul>
            {#each unanchored as c (c.id)}
              <li><button class="link" onclick={() => select(c.id)}>{c.number || c.id}</button></li>
            {/each}
          </ul>
        </details>
      {/if}
    </section>
    {#if claimId}
      <aside class="side" aria-label="Formal evidence">
        <div class="sidebar-head">
          <a href={href(index.release, "claim", claimId)}>Open as a page</a>
          <button class="x" onclick={close} aria-label="Close">×</button>
        </div>
        <Passport {index} {claimId} />
      </aside>
    {/if}
  </div>
{/if}

<style>
  .reader { display: grid; grid-template-columns: minmax(0, 1fr); height: calc(100vh - 49px); }
  .reader.open { grid-template-columns: minmax(0, 1.05fr) minmax(380px, 0.95fr); }
  .paperpane { overflow: auto; background: var(--surface-2); position: relative; }
  .side { overflow: auto; border-left: 1px solid var(--border); background: var(--bg); padding: 0 20px 60px; }
  .sidebar-head {
    position: sticky; top: 0; z-index: 2; display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; background: var(--bg); border-bottom: 1px solid var(--border); margin-bottom: 14px;
  }
  .x { border: 0; background: none; font-size: 22px; line-height: 1; cursor: pointer; color: var(--muted); padding: 0 4px; }
  .msg { padding: 24px; }
  .unanchored { margin: 12px 16px 24px; color: var(--muted); }
  .link { border: 0; background: none; color: var(--accent); cursor: pointer; padding: 0; }
  @media (max-width: 900px) {
    .reader.open { grid-template-columns: minmax(0, 1fr); }
    .side {
      position: fixed; left: 0; right: 0; bottom: 0; height: 70vh; z-index: 30;
      border-left: 0; border-top: 1px solid var(--border); border-radius: 14px 14px 0 0;
      box-shadow: 0 -8px 24px rgb(0 0 0 / 0.18); padding: 0 16px 40px;
    }
  }
</style>
