<script>
  import { openPdf, renderBand, pdfUrl } from "../lib/pdf.js";
  let { url, anchor } = $props();
  let box = $state(), width = $state(400), doc = $state(null), bands = $state([]), failed = $state(null), attempt = $state(0), big = $state(false);
  $effect(() => {
    attempt; const source = url, a = anchor; let current = true;
    failed = null; doc = null; bands = [];
    openPdf(source).then(async (d) => {
      const start = a.head || a.begin, end = a.end || a.begin;
      const parts = [];
      for (let no = start[0]; no <= Math.min(end[0], d.numPages); no++) {
        const height = (await d.getPage(no)).getViewport({ scale: 1 }).height;
        if (!current) return;
        const y0 = no === start[0] ? Math.max(0, start[2] - (a.head ? 12 : 0)) : 0;
        const y1 = no === end[0] ? Math.min(height, Math.max(end[2] + 5 + (a.kind === "approximate" ? 40 : 0), y0 + 18)) : height;
        parts.push({ no, range: [y0, y1] });
      }
      if (current) { bands = parts; doc = d; }
    }).catch((e) => { if (current) failed = String(e.message || e); });
    return () => { current = false; };
  });
  $effect(() => {
    if (!box) return;
    const observer = new ResizeObserver(() => { if (box.clientWidth) width = Math.max(100, Math.min(box.clientWidth - 2, 760)); });
    observer.observe(box); return () => observer.disconnect();
  });
  function draw(node, args) {
    let controller;
    function update(a) {
      controller?.abort(); controller = new AbortController();
      const signal = controller.signal;
      renderBand(a.doc, a.part.no, node, a.width, a.part.range, a.big ? 3.2 : 1.6, signal)
        .catch((e) => { if (!signal.aborted && e.name !== "RenderingCancelledException") failed = String(e.message || e); });
    }
    update(args); return { update, destroy() { controller?.abort(); } };
  }
</script>
<div class="crop" bind:this={box}>
  {#if failed}<div class="fail"><p>Paper preview unavailable. <button onclick={() => attempt++}>Try again</button></p><details><summary>Details</summary>{failed}</details></div>
  {:else if doc}
    {#each bands as part (part.no)}
      {#if bands.length > 1}<p class="page-label">Page {part.no}</p>{/if}
      <div class="band" class:big><canvas use:draw={{ doc, part, width: width * (big ? 2 : 1), big }} aria-label={"The claim as printed, page " + part.no}></canvas></div>
    {/each}
    <p class="tools"><a href={pdfUrl(url) + "#page=" + anchor.begin[0]} target="_blank" rel="noopener">Open excerpt in PDF ↗</a><button onclick={() => big = !big} aria-pressed={big}>{big ? "Fit excerpt" : "Enlarge"}</button></p>
  {:else}<p class="page-label">Loading excerpt…</p>{/if}
  {#if anchor.kind === "approximate"}<p class="small">Estimated PDF location · {anchor.file ? `SyncTeX · ${anchor.file}:${anchor.line}` : "detected heading"}</p>
  {:else if anchor.kind === "manual"}<p class="small">Placed by hand{anchor.by ? " by " + anchor.by : ""}{anchor.note ? ": " + anchor.note : ""}.</p>{/if}
</div>
<style>
  .crop { background: white; color: #333; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 0; overflow: hidden; }
  canvas { display: block; max-width: 100%; }
  .band { overflow-x: auto; }
  .band.big canvas { max-width: none; }
  .tools { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin: 6px 10px; font-size: 13px; }
  button { font: inherit; border: 1px solid #ccc; border-radius: var(--radius); padding: 4px 10px; background: white; color: #333; cursor: pointer; }
  a { color: #2f6f73; }
  .page-label, .small { font-size: 13px; color: #626262; padding: 0 10px; }
  .page-label { margin: 6px 0; }
  .fail { padding: 8px 12px; }
  .fail details { font-size: 13px; }
</style>
