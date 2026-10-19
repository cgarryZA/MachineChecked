<script>
  import LeanText from "./LeanText.svelte";
  import { loadDecl } from "../lib/data.js";

  // What a Lean definition says, from its declaration record (`d`, or loaded by `key`).
  // `view = "readable"`: its parameters and the body under them, or the equations Lean derives
  // from it, each under its own variables. `view = "exact"`: the authored source, the exact
  // statement of each equation theorem, and the elaborated value. The two views share sub-term
  // identities (`selId`, reported by `onselect`): a body's sub-terms are those of the value, and
  // an equation's are those of its theorem. `onname` makes the name a link (to inspect it).
  let { d = null, name = null, key = null, view = "readable", onref = null, onname = null,
        selId = null, onselect = null, heading = true } = $props();

  let loaded = $state(null), error = $state(null);
  $effect(() => {
    if (d || !key) return;
    loadDecl(key).then((x) => (loaded = x)).catch((e) => (error = `record ${key} missing: ${e.message}`));
  });
  const rec = $derived(d || loaded);
  const label = $derived(rec?.name || name);
  const refs = $derived(rec?.uses || []);
  const equations = $derived(rec?.equations || []);
  const byEquations = $derived(rec?.defined_by === "equations");
  const BIND = { explicit: ["(", ")"], implicit: ["{", "}"], "strict-implicit": ["⦃", "⦄"], instance: ["[", "]"] };
  const term = (pp) => (pp?.terms || []);
  const sel = (pp) => (k) => onselect?.(k == null ? null : term(pp)[k]?.id ?? null);
  const src = $derived(rec?.lean_source);
</script>

{#snippet lean(pp)}<LeanText {pp} {onref} {refs} {selId} onterm={onselect ? sel(pp) : null} />{/snippet}

{#snippet params(ps)}
  {#each ps as p}{@const br = BIND[p.binder] || BIND.explicit}{" "}<span class="param">{br[0]}{#if p.binder !== "instance"}<span class="pn">{p.name}</span>{" : "}{/if}{@render lean(p.type)}{br[1]}</span>{/each}
{/snippet}

<div class={"defn " + view} data-decl={label}>
  {#if view === "readable"}
    <p class="head">{#if onname}<button class="ref" onclick={() => onname(label)}>{label}</button>{:else}<code>{label}</code>{/if}{#if rec && !byEquations && rec.params}{@render params(rec.params)}{#if rec.result}{" "}<span class="colon">:</span>{" "}<LeanText pp={rec.result} {onref} {refs} />{/if}{/if}</p>
  {:else if heading}
    <p class="head"><code>{label}</code></p>
  {/if}
  {#if error}
    <p class="err">{error}</p>
  {:else if !rec}
    <p class="faint small">Loading…</p>
  {:else if view === "readable"}
    {#if rec.definition_error}
      <p class="small bad">The definition's equations could not be read from Lean: {rec.definition_error}</p>
    {/if}
    {#if byEquations}
      <p class="lbl">defined by {equations.length === 1 ? "the equation" : "the equations"}</p>
      <ul class="eqs">
        {#each equations as e (e.name)}
          <li class="eq" data-eq={e.name}>
            {#if e.params.length}<span class="for">for{@render params(e.params)}:</span>{/if}
            <span class="body">{@render lean(e.equation)}</span>
          </li>
        {/each}
      </ul>
      {#if rec.equations_omitted}<p class="small">{rec.equations_omitted} further equation{rec.equations_omitted === 1 ? " is" : "s are"} not included in this audit; the Lean source has them all.</p>{/if}
    {:else if rec.body}
      <div class="line"><span class="role">:=</span><span class="body">{@render lean(rec.body)}</span></div>
    {:else if rec.value}
      <p class="small faint">Lean gives no equations for this definition; its value is in the exact Lean.</p>
    {:else if rec.signature}
      <div class="line"><span class="role">:</span><span class="body">{@render lean(rec.signature)}</span></div>
    {/if}
  {:else}
    {#if src}
      <p class="lbl">Lean source · <span class="nocase">{src.file}:{src.line}{src.end_line > src.line ? "–" + src.end_line : ""}</span></p>
      <pre class="src">{src.text}</pre>
    {:else}
      <p class="small faint">The authored Lean source of this definition is not part of this audit.</p>
    {/if}
    {#if byEquations || (equations.length && !rec.body)}
      <p class="lbl">equation theorems Lean derives</p>
      {#each equations as e (e.name)}
        <div class="thm" data-eq={e.name}><code class="tn">{e.name}</code><pre>{@render lean(e.statement)}</pre></div>
      {/each}
      {#if rec.equations_omitted}<p class="small">{rec.equations_omitted} further equation theorem{rec.equations_omitted === 1 ? " is" : "s are"} not included in this audit.</p>{/if}
    {/if}
    {#if rec.signature}
      <p class="lbl">type</p>
      <pre><LeanText pp={rec.signature} {onref} {refs} /></pre>
    {/if}
    {#if rec.value}
      {#if byEquations}
        <details class="compiled">
          <summary>Compiled value</summary>
          <pre><LeanText pp={rec.value} {onref} {refs} /></pre>
        </details>
      {:else}
        <p class="lbl">elaborated value</p>
        <pre>{@render lean(rec.value)}</pre>
      {/if}
    {/if}
  {/if}
</div>

<style>
  .defn { margin: 0 0 16px; min-width: 0; }
  .head { margin: 0 0 6px; overflow-wrap: anywhere; }
  .readable :global(.lean) { font-family: var(--serif); font-size: 18px; line-height: 1.6; }
  .param { white-space: normal; }
  .colon { color: var(--faint); }
  .pn { font-family: var(--mono); font-weight: 600; }
  .line { display: flex; gap: 8px; align-items: baseline; }
  .role { font-size: 14px; color: var(--muted); }
  .body { min-width: 0; }
  .eqs { list-style: none; margin: 0; padding: 0; }
  .eq { margin: 4px 0; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .for { font-size: 14px; color: var(--muted); }
  .for :global(.lean) { font-size: 16px; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 10px 0 2px; }
  .nocase { text-transform: none; letter-spacing: 0; }
  pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.6 var(--mono); }
  .src { padding: 6px 8px; background: var(--surface-2, transparent); border-radius: 6px; }
  .thm { margin: 4px 0 8px; }
  .tn { font-size: 12px; color: var(--muted); }
  .compiled { margin-top: 10px; }
  .compiled > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .ref { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-family: var(--mono); font-size: 0.95em; text-align: left; overflow-wrap: anywhere; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  .bad, .err { color: var(--st-malformed); font-size: 13px; }
  .defn :global(.lean button), .defn :global(.lean a) { min-height: 0; }
</style>
