<script>
  import { tick, untrack } from "svelte";
  import { statusView } from "../lib/presentation.js";
  import { openPdf, documentPage, pdfUrl } from "../lib/pdf.js";
  let { url, claims = [], selected = null, onselect } = $props();
  let doc = $state(null), error = $state(null), width = $state(800), host = $state(), pages = $state([]), attempt = $state(0);
  let toolbar = $state();
  let zoom = $state(1), pageNo = $state(1), query = $state(""), matches = $state([]), match = $state(0), searching = $state(false), searched = $state(false);
  let searchError = $state(null), searchGeneration = 0;
  const original = $derived(pdfUrl(url));
  const pageWidth = $derived(Math.max(120, width * zoom));
  $effect(() => {
    attempt; const source = url; let current = true;
    doc = null; pages = []; error = null; matches = []; searched = false; searchGeneration++;
    openPdf(source).then(async (d) => {
      const ps = [];
      for (let i = 1; i <= d.numPages; i++) {
        const vp = (await d.getPage(i)).getViewport({ scale: 1 });
        if (!current) return;
        ps.push({ no: i, w: vp.width, h: vp.height });
      }
      pages = ps; doc = d;
    }).catch((e) => { if (current) error = String(e.message || e); });
    return () => { current = false; searchGeneration++; };
  });
  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver(() => { if (host.clientWidth) width = Math.max(120, Math.min(host.clientWidth - 32, 980)); });
    ro.observe(host); return () => ro.disconnect();
  });
  function bands(pageNo) {
    return claims.flatMap((c) => {
      const a = c.anchor;
      if (!a || pageNo < a.page || pageNo > (a.page_end ?? a.page)) return [];
      return [{ c, top: pageNo === a.page ? Math.max(0, a.y0 - 2) : 36,
        bottom: pageNo === (a.page_end ?? a.page) && a.y1 != null ? Math.max(a.y1 + 5, pageNo === a.page ? a.y0 + 16 : 52) : null }];
    });
  }
  function jump(no) {
    stopKeeping();
    toPage(no);
  }
  function toPage(no) {
    pageNo = Math.max(1, Math.min(doc?.numPages || 1, Number(no) || 1));
    const target = host?.querySelector(`[data-page="${pageNo}"]`), pane = host?.parentElement;
    if (target && pane) pane.scrollTop += target.getBoundingClientRect().top - pane.getBoundingClientRect().top - (toolbar?.offsetHeight || 0) - 16;
  }
  // A zoom change resizes every page; the page the reader was on stays in view (a selected
  // claim is kept in view by the effect above instead).
  let shownZoom = 1;
  $effect(() => {
    const z = zoom;
    if (z === shownZoom) return;
    shownZoom = z;
    const at = untrack(() => pageNo);
    if (!kept) tick().then(() => toPage(at));
  });
  // While the reader types in the page box, the page tracker leaves it alone.
  let typing = false;
  let kept = null, shown = null;
  function reveal() { if (kept) host?.querySelector(`[data-claim="${CSS.escape(kept)}"]`)?.scrollIntoView({ block: "center", behavior: "instant" }); }
  $effect(() => {
    pageWidth;
    if (!selected || !doc || !host) return;
    if (shown !== selected) { shown = selected; kept = selected; }
    tick().then(reveal);
  });
  function stopKeeping() { kept = null; }
  function pageObserver(node) {
    const io = new IntersectionObserver(() => {
      const line = (toolbar?.getBoundingClientRect().bottom || host?.parentElement.getBoundingClientRect().top || 0) + 8;
      const current = [...host.querySelectorAll("[data-page]")].find((p) => p.getBoundingClientRect().bottom > line);
      if (current && !typing) pageNo = Number(current.dataset.page);
    }, { root: host?.parentElement, rootMargin: "-10% 0px -70% 0px" });
    io.observe(node); return { destroy() { io.disconnect(); } };
  }
  async function find() {
    const mine = ++searchGeneration, needle = query.trim().toLocaleLowerCase();
    matches = []; match = 0; searchError = null; searched = false;
    if (!needle || !doc) { searching = false; return; }
    searching = true;
    try {
      const found = [];
      for (let no = 1; no <= doc.numPages; no++) {
        const content = await (await doc.getPage(no)).getTextContent();
        if (mine !== searchGeneration) return;
        const text = content.items.map((x) => x.str || "").join(" ").replace(/\s+/g, " ").toLocaleLowerCase();
        if (text.includes(needle.replace(/\s+/g, " "))) found.push(no);
      }
      matches = found; searched = true;
      if (found.length) jump(found[0]);
    } catch { if (mine === searchGeneration) searchError = "Paper search unavailable. Try again."; }
    finally { if (mine === searchGeneration) searching = false; }
  }
  function next(delta) { match = (match + delta + matches.length) % matches.length; jump(matches[match]); }
</script>
<div class="pdf-toolbar" bind:this={toolbar} aria-label="Paper controls">
  <label>Page <input type="number" min="1" max={doc?.numPages || 1} bind:value={pageNo} onfocus={() => (typing = true)} onblur={() => (typing = false)} onchange={(e) => jump(e.currentTarget.value)} aria-label="Page number" /></label><span class="muted">of {doc?.numPages || "…"}</span>
  <label class="zoom">Zoom <select bind:value={zoom} aria-label="PDF zoom"><option value={1}>Fit width</option><option value={1.25}>125%</option><option value={1.5}>150%</option><option value={2}>200%</option></select></label>
  <a href={original} target="_blank" rel="noopener">Open original PDF ↗</a>
  <form onsubmit={(e) => { e.preventDefault(); find(); }}>
    <input type="search" bind:value={query} aria-label="Find in paper" placeholder="Find in paper" oninput={() => { searchGeneration++; searching = false; searched = false; matches = []; }} />
    <button disabled={!doc || searching}>Find</button>
    {#if matches.length}<button type="button" aria-label="Previous matching page" onclick={() => next(-1)}>↑</button><button type="button" aria-label="Next matching page" onclick={() => next(1)}>↓</button>{/if}
    <span class="find-status" role="status">{searchError || (searching ? "Searching…" : matches.length ? `${match + 1} of ${matches.length} matching pages` : searched ? "No matches" : "")}</span>
  </form>
</div>
<div class="pdf" bind:this={host} onwheel={stopKeeping} ontouchmove={stopKeeping} onkeydown={stopKeeping} role="region" aria-label="Paper pages" tabindex="0">
  {#if error}<div class="err"><p>Paper preview unavailable. <button onclick={() => attempt++}>Try again</button></p><details><summary>Details</summary>{error}</details></div>
  {:else if !doc}<p class="muted wait">Opening the paper…</p>
  {:else}
    {#each pages as p (p.no)}
      {@const scale = pageWidth / p.w}
      <div class="page" class:found={matches[match] === p.no} data-page={p.no} style:width={pageWidth + "px"} style:height={p.h * scale + "px"}
        use:documentPage={{ doc, no: p.no, width: pageWidth, original, onpage: jump, onerror: (e) => error = e }} use:pageObserver={p.no}>
        <canvas aria-label={"Page " + p.no}></canvas><div class="textLayer"></div><div class="pdf-links"></div>
        {#each bands(p.no) as b (b.c.id)}
          <button class={"band st-" + statusView(b.c).class} class:approximate={b.c.anchor.kind === "approximate"} class:sel={b.c.id === selected}
            data-claim={b.c.id} style:top={b.top * scale + "px"} style:height={Math.max(24, ((b.bottom ?? p.h - 36) - b.top) * scale) + "px"}
            onclick={() => onselect(b.c.id)} aria-label={`${b.c.number || b.c.id}: ${statusView(b.c).label}`} title={`${b.c.number || b.c.id}: ${statusView(b.c).label}`}>
            <span class="tag">{b.c.number || b.c.id}{b.c.anchor.kind === "approximate" ? " · approximate location" : ""}</span>
          </button>
        {/each}
      </div>
    {/each}
  {/if}
</div>
<style>
  .pdf-toolbar { position: sticky; top: 0; z-index: 6; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; padding: 8px 12px; background: var(--surface); border-bottom: 1px solid var(--border); font-size: 14px; }
  label { display: flex; align-items: center; gap: 4px; }
  input, select, button { font: inherit; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); padding: 4px 8px; }
  input[type="number"] { width: 4em; }
  form { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; width: 100%; }
  input[type="search"] { min-width: 100px; width: 150px; flex: 1; }
  button { cursor: pointer; }
  .find-status { font-size: 13px; }
  .pdf { padding: 16px; display: flex; flex-direction: column; align-items: flex-start; gap: 16px; min-height: 100%; min-width: 0; }
  .page { position: relative; flex: none; margin: 0 auto; background: white; color: black; box-shadow: 0 1px 4px #0003; scroll-margin-top: 130px; }
  .page.found { outline: 3px solid var(--accent); }
  canvas { display: block; }
  .pdf :global(.textLayer) { z-index: 1; }
  .pdf-links { position: absolute; inset: 0; pointer-events: none; z-index: 2; }
  .pdf-links :global(a) { position: absolute; pointer-events: auto; }
  .pdf-links :global(a:hover) { background: #2f6f7326; }
  .band { position: absolute; left: 0; width: 28px; border: 0; padding: 0; background: transparent; cursor: pointer; z-index: 3; min-height: 24px; }
  .band::before { content: ""; position: absolute; left: 10px; top: 0; bottom: 0; width: 4px; border-radius: 2px; background: var(--st); }
  .band.approximate::before { background: repeating-linear-gradient(to bottom, var(--st) 0 4px, transparent 4px 7px); }
  .band.sel, .band:hover { background: color-mix(in srgb, var(--st) 20%, transparent); }
  .tag { position: absolute; top: 0; left: 28px; white-space: nowrap; font: 12px/1.5 var(--sans); padding: 2px 8px; background: #fff; color: #1d1d1b; border: 1px solid var(--st); border-radius: 4px; opacity: 0; pointer-events: none; }
  .band:hover .tag, .band:focus-visible .tag { opacity: 1; }
  .err, .wait { padding: 24px; }
  .err details { font-size: 13px; }
  @media (max-width: 700px) { input, select { font-size: 16px; } }
</style>
