<script>
  import { openPdf, renderBand } from "../lib/pdf.js";

  // The claim as typeset: the band of the page between its anchors.
  let { url, anchor } = $props();
  let canvas = $state();
  let box = $state();
  let failed = $state(null);
  let attempt = $state(0);
  // The band is trimmed to its text and drawn to the panel's width; enlarged, at twice that,
  // scrolling inside its own box.
  let big = $state(false);

  $effect(() => {
    attempt;
    if (!canvas || !box) return;
    const top = anchor.head || anchor.begin;
    const page = top[0];
    const y0 = anchor.head ? top[2] - 12 : top[2];
    const sameEnd = anchor.end && anchor.end[0] === page;
    const width = (big ? 2 : 1) * Math.min(box.clientWidth - 2, 760);
    const y1 = sameEnd ? Math.max(anchor.end[2] + 5, y0 + 18) + (anchor.kind === "approximate" ? 40 : 0) : y0 + 220;
    openPdf(url)
      .then((doc) => renderBand(doc, page, canvas, width, [y0, y1], big ? 3.2 : 1.6))
      .catch((e) => { console.error("crop", e); failed = String(e); });
  });
</script>

<div class="crop" bind:this={box}>
  {#if failed}
    <div class="fail">
      <p>Paper preview unavailable. <button class="retry" onclick={() => { failed = null; attempt++; }}>Try again</button></p>
      <details><summary>Details</summary><p class="small">{failed}</p></details>
    </div>
  {:else}
    <div class="band" class:big><canvas bind:this={canvas} aria-label="The claim as printed"></canvas></div>
    <p class="tools"><button class="zoom" onclick={() => (big = !big)} aria-pressed={big}>{big ? "Smaller" : "Enlarge"}</button></p>
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
  .fail { padding: 4px 12px; color: #333; font-size: 14px; }
  .fail p { margin: 0 0 4px; }
  .fail details { color: #6b6b6b; font-size: 12px; }
  .fail summary { cursor: pointer; }
  .retry { font: inherit; font-size: 12px; border: 1px solid #d0d0d0; background: white; border-radius: 6px; padding: 0 8px; cursor: pointer; margin-left: 4px; }
  .band.big canvas { max-width: none; }
  .tools { margin: 2px 8px 0; text-align: right; }
  .zoom { margin: 0; font-size: 12px; padding: 1px 8px; border-radius: 6px; border: 1px solid #d0d0d0; background: rgb(255 255 255 / 0.9); color: #333; cursor: pointer; }
  .small { font-size: 12px; padding: 0 10px; color: #6b6b6b; }
</style>
