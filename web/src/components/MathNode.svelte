<script>
  import MathNode from "./MathNode.svelte";
  import { getContext } from "svelte";
  import { layout } from "../lib/math.js";
  import { gloss } from "../lib/gloss.js";

  // One node of a printed expression's mathematics (`math`, from the probe), laid out as notation
  // (`lib/math.js`). A node that is a sub-term the exact statement shows is chosen by clicking
  // it: the smallest such node around the click, then the next larger on each click, and a click
  // past the largest (`root`) releases it; the exact Lean highlights the same sub-term, and the
  // one selected there is highlighted here. `ctx`: `key(id)` (the identity the exact statement
  // shows the sub-term under, or null), `sel` (the selected identity), `mark` (the positions of
  // a warning's occurrences), `onselect(key, id)`, `onref` and `refs` (the project's
  // declarations, which open), `ongloss` (a name's plain-English note), `active` (a variable's
  // number, highlighted) and `onvar(v, how)` (a variable hovered or held).
  let { m, min = 0, ctx, root = false } = $props();
  const refHref = getContext("declarationHref");

  const lay = $derived(layout(m));
  const key = $derived(m?.id != null ? ctx.key(m.id) : null);
  const selected = $derived(ctx.sel != null && m?.id != null && (key === ctx.sel || m.id === ctx.sel));
  // A warning's occurrence: an application at one of `ctx.mark`'s positions, or whose head is
  // (how an operator's notation was tagged before #457).
  const marked = $derived(m?.id != null && (ctx.mark || []).some((a) => a === m.id
    || (a.startsWith(m.id + "/") && /^(\/0)+$/.test(a.slice(m.id.length)))));
  const paren = $derived(lay.prec < min);
  // A click is handled from the innermost node out (`e.mc` carries how far it got): the
  // innermost node that can be chosen is chosen unless a node around it is selected; a selected
  // node passes the choice to the next node around it that can be chosen; past the largest, the
  // selection is released.
  function choose(e) {
    if (!ctx.onselect) return;
    const mc = (e.mc ||= { done: false, pass: false });
    if (mc.done) return;
    if (key != null && !selected && (mc.pass || !e.currentTarget.parentElement?.closest(".m.in"))) {
      mc.done = true;
      ctx.onselect(key, m.id);
      return;
    }
    if (selected) mc.pass = true;
    if (root) { mc.done = true; if (mc.pass) ctx.onselect(null); }
  }
  const project = (r) => !!ctx.onref && (ctx.refs || []).includes(r);
  function follow(e, name) { e.stopPropagation(); if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); ctx.onref(name); } }
  const pin = (e, v) => { e.stopPropagation(); ctx.onvar?.(v, "pin"); };
  const REP = "A representative of the class: a function equal to it almost everywhere";
</script>

{#snippet pieces(ps)}{#each ps as p}{#if typeof p === "string"}<span class="o">{p}</span>{:else if p.n}<MathNode m={p.n} min={p.p} {ctx} />{:else if p.word}<span class="w">{p.word}</span>{:else if p.v != null}<span class="var" class:hl={ctx.active === p.v} data-var={p.v} role="button" tabindex="0" onmouseenter={() => ctx.onvar?.(p.v, "hover")} onmouseleave={() => ctx.onvar?.(null, "hover")} onfocus={() => ctx.onvar?.(p.v, "hover")} onblur={() => ctx.onvar?.(null, "hover")} onclick={(e) => pin(e, p.v)} onkeydown={(e) => { e.stopPropagation(); if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pin(e, p.v); } }}>{p.t}</span>{:else if p.b != null}<span class="bv" data-binder={p.b}>{p.t}</span>{:else if p.ref}{#if project(p.ref)}{#if refHref}<a class="r" title={p.ref} href={refHref(p.ref)} onclick={(e) => follow(e, p.ref)} onkeydown={(e) => e.stopPropagation()}>{p.t}</a>{:else}<button class="r" title={p.ref} onclick={(e) => { e.stopPropagation(); ctx.onref(p.ref); }} onkeydown={(e) => e.stopPropagation()}>{p.t}</button>{/if}{:else if gloss(p.ref) && ctx.ongloss}<button class="g" title={p.ref} onclick={(e) => { e.stopPropagation(); ctx.ongloss(p.ref); }} onkeydown={(e) => e.stopPropagation()}>{p.t}</button>{:else}<span class="c" title={gloss(p.ref) ? p.ref + ": " + gloss(p.ref) : p.ref}>{p.t}</span>{/if}{:else if p.lean != null}<code class="xl" title="Exact Lean: not read as mathematics">{p.lean}</code>{:else if p.sup}<sup>{@render pieces(p.sup)}</sup>{:else if p.sub}<sub>{@render pieces(p.sub)}</sub>{:else if p.italic}<i>{p.t}</i>{/if}{/each}{/snippet}

{#snippet body()}{#if paren}({/if}{@render pieces(lay.pieces)}{#if paren}){/if}{/snippet}
{#if m && (key != null || root)}<span class="m" class:pick={key != null} class:in={selected} class:mk={marked} data-at={key} data-k={m.k} title={m.k === "rep" ? REP : null}
  role="button" tabindex="-1" onclick={choose} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), choose(e))}>{@render body()}</span>
{:else if m}<span class="m" class:in={selected} class:mk={marked} data-k={m.k} title={m.k === "rep" ? REP : null}>{@render body()}</span>{/if}

<style>
  .m { border-radius: 2px; }
  .m.pick { cursor: pointer; }
  .m.pick:hover { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  .m.in { background: color-mix(in srgb, var(--st-open) 22%, transparent); }
  .m.mk { background: color-mix(in srgb, var(--tier-warning) 20%, transparent); border-bottom: 2px solid var(--tier-warning); }
  .w { font-family: var(--sans, inherit); font-size: 0.82em; color: var(--muted); font-style: normal; }
  .var { font-style: italic; border-radius: 3px; cursor: pointer; }
  .var.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
  .bv { font-style: italic; }
  .r, .g { border: 0; padding: 0; background: none; font: inherit; min-height: 0; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
  .r { color: var(--accent); }
  .g { color: inherit; }
  .xl { font-family: var(--mono); font-size: 0.82em; color: var(--muted); }
  sup, sub { font-size: 0.7em; }
</style>
