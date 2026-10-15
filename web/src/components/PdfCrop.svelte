<script>
  import { openPdf, renderPage } from "../lib/pdf.js";

  // The claim as typeset: the band of the page between its anchors.
  let { url, anchor } = $props();
  let canvas = $state();
  let box = $state();
  let failed = $state(false);

  $effect(() => {
    if (!canvas || !box) return;
    const top = anchor.head || anchor.begin;
    const page = top[0];
    const y0 = anchor.head ? top[2] - 12 : top[2];
    const sameEnd = anchor.end && anchor.end[0] === page;
    const y1 = sameEnd ? Math.max(anchor.end[2] + 5, y0 + 18) : y0 + 220;
    openPdf(url)
      .then((doc) => renderPage(doc, page, canvas, Math.min(box.clientWidth, 760), [y0, y1]))
      .catch((e) => { console.error("crop", e); failed = true; });
  });
</script>

<div class="crop" bind:this={box}>
  {#if failed}
    <p class="muted">The page could not be rendered.</p>
  {:else}
    <canvas bind:this={canvas} aria-label="The claim as printed"></canvas>
  {/if}
  {#if anchor.end && anchor.end[0] !== anchor.begin[0]}
    <p class="faint small">Continues on page {anchor.end[0]}.</p>
  {/if}
</div>

<style>
  .crop { background: white; border: 1px solid var(--border); border-radius: 8px; padding: 6px 0; overflow: hidden; }
  canvas { display: block; max-width: 100%; }
  .small { font-size: 12px; padding: 0 10px; color: #6b6b6b; }
</style>
