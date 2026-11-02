<script>
  import { renderExcerpt } from "../lib/excerpt.js";
  import { markMath, bindSymbols, highlightSymbols } from "../lib/symbolmarks.js";

  // A passage of the paper typeset from its pinned LaTeX source (lib/excerpt.js). `onstatus`
  // is told whether the whole passage was typeset; nothing is shown otherwise. Linked symbols
  // (`symbols`, [{tex, id, occurrence}]) are marked in its mathematics: every occurrence, or
  // those a link numbers, counted through the passage. The body of a theorem in amsthm's
  // `plain` style is italic, as printed.
  let { excerpt, symbols = [], active = [], onsym = null, onstatus = null } = $props();
  let el;

  $effect(() => {
    if (!el) return;
    const seen = new Map();
    const r = renderExcerpt(excerpt, document, (src) => markMath(src, symbols, seen));
    el.replaceChildren(...(r.ok ? [r.node] : []));
    onstatus?.(r.ok);
    if (r.ok) bindSymbols(el, symbols, onsym);
  });

  $effect(() => {
    if (!el) return;
    highlightSymbols(el, active);
  });
</script>

<div class="tex excerpt" class:italic={excerpt?.body_style === "italic"} bind:this={el}></div>

<style>
  .tex { font-family: var(--serif); font-size: 16px; line-height: 1.6; padding: 10px 14px; background: var(--surface); border-radius: var(--radius); margin-top: 6px; overflow-wrap: anywhere; }
  .tex :global(p) { margin: 0 0 0.6em; }
  .tex :global(p:last-child) { margin-bottom: 0; }
  .tex :global(em em), .tex :global(i em), .italic :global(em) { font-style: normal; }
  .italic { font-style: italic; }
  .italic :global(em em) { font-style: italic; }
  .tex :global(.sc) { font-variant: small-caps; }
  .tex :global(.tt) { font-family: var(--mono); }
  .tex :global(.sf) { font-family: var(--sans, sans-serif); }
  .tex :global(.rm) { font-style: normal; font-weight: normal; }
  .tex :global(.display) { overflow-x: auto; overflow-y: hidden; margin: 0.5em 0; }
  .tex :global(ul), .tex :global(ol) { margin: 0.3em 0 0.6em; padding-left: 1.6em; }
  .tex :global(ol.labelled), .tex :global(ul.labelled) { list-style: none; }
  .tex :global(.lbl) { display: inline-block; min-width: 2em; margin-left: -2em; }
  .tex :global([data-sym]) { cursor: pointer; border-bottom: 1px dotted var(--accent); }
  .tex :global([data-sym].hl) { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 3px; }
</style>
