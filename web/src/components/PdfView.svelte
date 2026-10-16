<script>
  import { openPdf, renderPage } from "../lib/pdf.js";

  // The paper's PDF, page by page, with a band over every claim located by the anchors.
  let { url, claims, selected = null, onselect } = $props();

  let doc = $state(null);
  let error = $state(null);
  let width = $state(800);
  let host;
  let pages = $state([]); // [{ no, w, h }] in PDF points

  $effect(() => {
    error = null;
    openPdf(url)
      .then(async (d) => {
        const ps = [];
        for (let i = 1; i <= d.numPages; i++) {
          const vp = (await d.getPage(i)).getViewport({ scale: 1 });
          ps.push({ no: i, w: vp.width, h: vp.height });
        }
        pages = ps;
        doc = d;
      })
      .catch((e) => (error = String(e)));
  });

  $effect(() => {
    if (!host) return;
    const ro = new ResizeObserver(() => (width = Math.min(host.clientWidth - 32, 980)));
    ro.observe(host);
    return () => ro.disconnect();
  });

  function bands(pageNo) {
    const out = [];
    for (const c of claims) {
      const a = c.anchor;
      if (!a) continue;
      const end = a.page_end ?? a.page;
      if (pageNo < a.page || pageNo > end) continue;
      out.push({ c, top: pageNo === a.page ? a.y0 - 2 : 36, bottom: pageNo === end && a.y1 != null ? Math.max(a.y1 + 5, a.y0 + 16) : null });
    }
    return out;
  }

  // Keep the selected claim in view. Selecting one opens the side panel, and a page loads at a
  // provisional width, so the pages' size (which follows the width) can change after the scroll
  // started; the claim is scrolled to again whenever it does, until the reader scrolls
  // themselves.
  let shown = null; // the claim last brought into view
  let kept = null; // the claim kept in view until the reader scrolls
  function bringIntoView() {
    const el = host?.querySelector(`[data-claim="${CSS.escape(kept)}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "instant" });
  }
  $effect(() => {
    void width; // re-run when the pages' size changes
    if (!selected || !doc || !host) return;
    if (selected !== shown) { shown = selected; kept = selected; }
    if (kept === selected) requestAnimationFrame(bringIntoView);
  });
  $effect(() => {
    const pane = host?.parentElement;
    if (!pane) return;
    const release = () => (kept = null);
    const onPointer = (e) => { if (e.target === pane) kept = null; }; // the scrollbar
    pane.addEventListener("wheel", release, { passive: true });
    pane.addEventListener("touchmove", release, { passive: true });
    pane.addEventListener("keydown", release);
    pane.addEventListener("pointerdown", onPointer);
    return () => {
      pane.removeEventListener("wheel", release);
      pane.removeEventListener("touchmove", release);
      pane.removeEventListener("keydown", release);
      pane.removeEventListener("pointerdown", onPointer);
    };
  });

  function canvasAction(node, args) {
    let current = null;
    const draw = (a) => {
      const key = a.no + ":" + a.width;
      if (key === current || !a.doc) return;
      current = key;
      renderPage(a.doc, a.no, node, a.width).catch((e) => console.error("render", e));
    };
    // Render pages only when they come near the viewport.
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && draw(args), { rootMargin: "800px" });
    io.observe(node);
    return {
      update(a) { args = a; current = null; draw(a); },
      destroy() { io.disconnect(); },
    };
  }
</script>

<div class="pdf" bind:this={host}>
  {#if error}
    <p class="err">The PDF could not be opened: {error}</p>
  {:else if !doc}
    <p class="muted wait">Opening the paper…</p>
  {:else}
    {#each pages as p (p.no)}
      {@const s = width / p.w}
      <div class="page" style:width={width + "px"} style:height={p.h * s + "px"}>
        <canvas use:canvasAction={{ doc, no: p.no, width }} aria-label={"Page " + p.no}></canvas>
        {#each bands(p.no) as b (b.c.id + ":" + p.no)}
          <button
            class={"band st-" + b.c.class + (b.c.anchor?.kind && b.c.anchor.kind !== "exact" ? " " + b.c.anchor.kind : "")}
            class:sel={b.c.id === selected}
            data-claim={b.c.id}
            style:top={b.top * s + "px"}
            style:height={((b.bottom ?? p.h - 36) - b.top) * s + "px"}
            onclick={() => onselect(b.c.id)}
            title={`${b.c.number}: ${b.c.status}`}
          >
            <span class="tag">{b.c.status}{b.c.anchor?.kind === "approximate" ? " · approximate location" : b.c.anchor?.kind === "manual" ? " · placed by hand" : ""}</span>
          </button>
        {/each}
      </div>
    {/each}
  {/if}
</div>

<style>
  .pdf { padding: 16px; display: flex; flex-direction: column; align-items: center; gap: 16px; min-height: 100%; }
  .page { position: relative; background: white; box-shadow: 0 1px 4px rgb(0 0 0 / 0.18); }
  canvas { display: block; }
  /* A claim is a thin marker in the margin; the paper itself stays clean. Hovering shows where
     the claim is, selecting it outlines it. */
  .band {
    position: absolute; left: 0; right: 0; border: 0; padding: 0; cursor: pointer;
    background: transparent;
  }
  .band::before {
    content: ""; position: absolute; left: 18px; top: 0; bottom: 0; width: 4px; border-radius: 2px;
    background: var(--st);
  }
  .band.approximate::before { background: repeating-linear-gradient(to bottom, var(--st) 0 4px, transparent 4px 7px); }
  .band:hover { background: color-mix(in srgb, var(--st) 7%, transparent); }
  .band.sel { background: color-mix(in srgb, var(--st) 10%, transparent); outline: 1.5px solid color-mix(in srgb, var(--st) 70%, transparent); outline-offset: -1px; }
  .band.approximate.sel { outline-style: dashed; }
  /* The status sits just above the claim, so it never covers the statement's own first line. */
  .tag {
    position: absolute; right: 6px; top: -3px; transform: translateY(-100%); z-index: 3;
    font: 11px/1.4 var(--sans); max-width: calc(100% - 40px); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; box-shadow: 0 1px 3px rgb(0 0 0 / 0.12);
    padding: 1px 8px; border-radius: 999px; color: #1d1d1b;
    background: color-mix(in srgb, var(--st) 22%, white); border: 1px solid var(--st);
    opacity: 0; transition: opacity 0.12s; pointer-events: none;
  }
  .band:hover .tag, .band.sel .tag { opacity: 1; }
  .err, .wait { padding: 24px; }
</style>
