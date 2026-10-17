<script>
  import { openPdf, renderPage } from "../lib/pdf.js";

  // The claim as typeset: the band of the page between its anchors.
  let { url, anchor } = $props();
  let canvas = $state();
  let box = $state();
  let failed = $state(false);
  // Enlarged, the band is drawn at twice the panel's width and scrolls inside its own box.
  let big = $state(false);

  $effect(() => {
    if (!canvas || !box) return;
    const top = anchor.head || anchor.begin;
    const page = top[0];
    const y0 = anchor.head ? top[2] - 12 : top[2];
    const sameEnd = anchor.end && anchor.end[0] === page;
    const width = big ? Math.min(box.clientWidth * 2, 1520) : Math.min(box.clientWidth, 760);
    const y1 = sameEnd ? Math.max(anchor.end[2] + 5, y0 + 18) + (anchor.kind === "approximate" ? 40 : 0) : y0 + 220;
    openPdf(url)
      .then((doc) => renderPage(doc, page, canvas, width, [y0, y1]))
      .catch((e) => { console.error("crop", e); failed = true; });
  });
</script>

<div class="crop" bind:this={box}>
  {#if failed}
    <p class="muted">The page could not be rendered.</p>
  {:else}
    <div class="band" class:big><canvas bind:this={canvas} aria-label="The claim as printed"></canvas></div>
    <button class="zoom" onclick={() => (big = !big)} aria-pressed={big}>{big ? "Smaller" : "Enlarge"}</button>
  {/if}
  {#if anchor.kind === "approximate"}
    {#if anchor.file}
      <p class="faint small">Located approximately (SyncTeX, from {anchor.file}:{anchor.line}); the claim may extend beyond this band.</p>
    {:else}
      <p class="faint small">Found by its bold heading in the PDF; where the statement ends is estimated, and it may extend beyond this band.</p>
    {/if}
  {:else if anchor.kind === "manual"}
    <p class="faint small">Placed by hand{anchor.by ? " by " + anchor.by : ""}{anchor.note ? ": " + anchor.note : ""}.</p>
  {/if}
  {#if anchor.end && anchor.end[0] !== anchor.begin[0]}
    <p class="faint small">Continues on page {anchor.end[0]}.</p>
  {/if}
</div>

<style>
  .crop { background: white; border: 1px solid var(--border); border-radius: 8px; padding: 6px 0; overflow: hidden; }
  .crop { position: relative; }
  canvas { display: block; max-width: 100%; }
  .band.big { overflow-x: auto; }
  .band.big canvas { max-width: none; }
  .zoom { position: absolute; right: 6px; top: 6px; font-size: 12px; padding: 1px 8px; border-radius: 6px; border: 1px solid #d0d0d0; background: rgb(255 255 255 / 0.9); color: #333; cursor: pointer; }
  .small { font-size: 12px; padding: 0 10px; color: #6b6b6b; }
</style>
