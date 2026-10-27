<script>
  import LeanText from "./LeanText.svelte";
  import Expansion from "./Expansion.svelte";
  import { expansionFor, expansionsOf } from "../lib/expand.js";
  import { loadExpansion } from "../lib/data.js";

  // A definition expanded at one application of it (`x`, one of a printed expression's
  // `expansions`): the arguments it is applied to, by the definition's parameters, then its body
  // at those arguments, or each of its equations that applies to them, as Lean computed and
  // checked them. `occ` is the application as the statement prints it. A sub-term of the
  // expansion that applies another of the project's definitions expands in turn, below.
  // A statement refers to an expansion by key (`{at, id, name, key}`); it is fetched here, when
  // it is opened.
  let { x: given, occ = null, onref = null, refs = null, onclose = null } = $props();
  const byKey = (g) => g?.key && !g.defined_by && !g.error;
  let loaded = $state(null), failed = $state(null);
  $effect(() => {
    const g = given;
    loaded = null;
    failed = null;
    if (!byKey(g)) return;
    loadExpansion(g.key).then((r) => { if (given === g) loaded = r; })
      .catch((e) => { if (given === g) failed = String(e?.message || e); });
  });
  const x = $derived(byKey(given) ? loaded : given);

  const BIND = { explicit: ["(", ")"], implicit: ["{", "}"], "strict-implicit": ["⦃", "⦄"], instance: ["[", "]"] };
  const WRITTEN = { implicit: "implicit", "strict-implicit": "implicit", instance: "instance" };
  // A sub-term selected inside this expansion, and the expansion it opens.
  let sel = $state(null), alone = $state(null);
  const inner = $derived(alone ? { x: alone, text: null } : sel ? expansionFor(sel.pp, sel.k) : null);
  const pick = (pp) => (k) => { alone = null; sel = k == null ? null : { pp, k }; };
  function open(pp, o) {
    if (o.k >= 0) pick(pp)(sel?.pp === pp && sel.k === o.k ? null : o.k);
    else { sel = null; alone = alone === o.x ? null : o.x; }
  }
  // Equations that do not apply are named in full up to this many, the rest on request.
  const FEW = 12;
  const conds = (e) => e.params.filter((p) => p.proposition);
  const vars = (e) => e.params.filter((p) => !p.proposition);
</script>

{#snippet lean(pp)}<LeanText {pp} {onref} {refs} term={sel?.pp === pp ? sel.k : null} onterm={pick(pp)} />{@const os = expansionsOf(pp)}{#if os.length}{" "}<span class="xs">expand{#each os as o}{" "}<button class="xb" aria-label={"Expand " + o.text + " at its arguments"} onclick={() => open(pp, o)}>{o.label}</button>{/each}</span>{/if}{/snippet}

{#snippet params(ps)}
  {#each ps as p}{@const br = BIND[p.binder] || BIND.explicit}{" "}<span class="param">{br[0]}{#if p.binder !== "instance"}<span class="pn">{p.name}</span>{" : "}{/if}<LeanText pp={p.type} {onref} {refs} />{br[1]}</span>{/each}
{/snippet}

<div class="xp" data-expansion={given.id}>
  <p class="head">
    <code class="nm">{given.name}</code><span class="lbl">at its arguments</span>
    {#if onclose}<button class="x" aria-label="Close the expansion" onclick={onclose}>×</button>{/if}
  </p>
  {#if occ}<p class="occ"><code>{occ}</code></p>{/if}
  {#if !x}
    {#if failed}<p class="small bad">This expansion could not be loaded ({failed}). The statement above is exact.</p>
    {:else}<p class="small faint">Loading the expansion…</p>{/if}
  {:else}
  {#if x.args?.length}
    <ul class="args" aria-label="Arguments">
      {#each x.args as a, i}
        <li><span class="pn">{a.name || (a.binder === "instance" ? "instance" : "argument " + (i + 1))}</span><span class="colon">{" := "}</span><LeanText pp={a.value} {onref} {refs} />{#if WRITTEN[a.binder] && (a.name || a.binder !== "instance")}<span class="faint small">{" (" + WRITTEN[a.binder] + ")"}</span>{/if}</li>
      {/each}
    </ul>
  {/if}
  {#if x.error}
    <p class="small bad">Lean could not expand this application: {x.error}. The statement above is exact.</p>
  {:else if x.defined_by === "equations"}
    {#if x.equations.length}
      <p class="lbl">{x.equations.length === 1 ? "the equation that applies" : "the equations that apply"}</p>
      <ul class="eqs">
        {#each x.equations as e (e.name)}
          <li class="eq" data-eq={e.name}>
            {#if vars(e).length}<span class="for">for{@render params(vars(e))}:</span>{/if}
            {#if conds(e).length}<span class="for">provided{@render params(conds(e))}:</span>{/if}
            <span class="body">{@render lean(e.equation)}</span>
            <code class="tn">{e.name}</code>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="small">No equation of <code>{x.name}</code> applies to these arguments as written: each equation fixes a form of its arguments that they do not have.</p>
    {/if}
    {#if x.equations_not_applying?.length && x.equations.length}
      {@const na = x.equations_not_applying}
      {#if na.length <= FEW}
        <p class="small faint">Not applying here: {na.join(", ")}.</p>
      {:else}
        <details class="small faint na"><summary>Not applying here: {na.slice(0, FEW).join(", ")} and {na.length - FEW} more</summary>{na.slice(FEW).join(", ")}.</details>
      {/if}
    {/if}
    {#if x.equations_omitted}<p class="small">{x.equations_omitted} further equation{x.equations_omitted === 1 ? " was" : "s were"} not compared with these arguments; the definition lists them all.</p>{/if}
  {:else}
    <div class="line">
      {#if x.params?.length}<span class="for">still to supply{@render params(x.params)}:</span>{/if}
      <span class="body">{@render lean(x.body)}</span>
    </div>
  {/if}
  {#if !x.error}<p class="small faint">Substituted and type-checked by Lean.</p>{/if}
  {/if}
  {#if inner}
    <Expansion x={inner.x} occ={inner.text} {onref} {refs} onclose={() => { sel = null; alone = null; }} />
  {/if}
</div>

<style>
  .xp { margin-top: 6px; padding: 6px 10px; border-left: 2px solid color-mix(in srgb, var(--accent) 45%, var(--border)); }
  .xp :global(.lean) { font-family: var(--serif); font-size: 17px; line-height: 1.6; }
  .head { margin: 0; display: flex; gap: 6px; align-items: baseline; }
  .head .x { margin-left: auto; border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 16px; line-height: 1; }
  .occ { margin: 2px 0; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 6px 0 2px; }
  .head .lbl { margin: 0; }
  .nm { font-size: 13px; }
  .args { list-style: none; margin: 2px 0; padding: 0; }
  .args li { margin: 1px 0; }
  .pn { font-family: var(--mono); font-weight: 600; }
  .colon { color: var(--faint); }
  .param { white-space: normal; }
  .line, .eq { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .eqs { list-style: none; margin: 0; padding: 0; }
  .eq { margin: 4px 0; }
  .for { font-size: 14px; color: var(--muted); }
  .for :global(.lean) { font-size: 15px; }
  .body { min-width: 0; }
  .tn { font-size: 12px; color: var(--muted); }
  .small { font-size: 13px; margin: 4px 0; }
  .na > summary { cursor: pointer; }
  .faint { color: var(--faint); }
  .bad { color: var(--st-malformed); }
  .xs { font-size: 12px; color: var(--faint); white-space: normal; }
  .xb { border: 1px solid var(--border); border-radius: 10px; background: none; color: var(--accent); cursor: pointer; font: 12px var(--mono); padding: 0 6px; min-height: 0; }
  .xp :global(.lean button), .xp :global(.lean a) { min-height: 0; }
</style>
