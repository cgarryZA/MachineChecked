<script>
  import LeanText from "./LeanText.svelte";
  import { carriedOf } from "../lib/carried.js";
  // `selId` and `onselect`: the sub-term selected, by its identity in the proposition, shared
  // with the readable statement of the same proposition.
  let { st, name = null, onref = null, selId = null, onselect = null } = $props();
  const terms = $derived(typeof st?.exact === "object" ? st.exact?.terms || [] : []);
  let copied = $state(false), error = $state(null);
  // The propositions carried by the types of the statement's objects, each as the Lean term that
  // proves it for that object (`s.start : s.path 0 = d`), with its field's projection: they are
  // part of the statement's meaning without being written in it.
  const carried = $derived(carriedOf(st).filter((c) => c.prop.kind === "proposition"));
  const refs = $derived([...(st?.closure || []), ...(st?.direct || [])]);
  const text = $derived(typeof st?.exact === "string" ? st.exact : st?.exact?.text || st?.exact?.segments?.map((s) => s.t).join(""));
  async function copy() {
    try { await navigator.clipboard.writeText(text); copied = true; error = null; }
    catch { error = "Select the statement to copy it."; }
  }
</script>
<div class="exact">
  {#if name}<p class="name"><code>{name}</code></p>{/if}
  {#if text}
    <pre><LeanText pp={typeof st.exact === "string" ? { text } : st.exact} {onref} refs={[...(st.closure || []), ...(st.direct || [])]} {selId} onterm={onselect ? (k) => onselect(k == null ? null : terms[k]?.id ?? null) : null} /></pre>
    <button class="copy" onclick={copy}>{copied ? "Copied" : "Copy Lean"}</button>
    {#if error}<p role="status">{error}</p>{/if}
    {#if carried.length}
      <details class="carried" open={carried.length <= 8}>
        <summary>Carried by the types of its objects ({carried.length})</summary>
        {#each carried as c}
          <div class="field" data-field={c.prop.field} data-owner={c.owner.id}><pre><code>{c.prop.term}</code> : <LeanText pp={c.prop.type} {onref} {refs} {selId} onterm={onselect ? (k) => onselect(k == null ? null : c.prop.type?.terms?.[k]?.id ?? null) : null} /></pre>
            <p class="origin">{c.prop.projection || c.prop.field}{#if c.prop.module} · {c.prop.module}{#if c.prop.range?.line}:{c.prop.range.line}{/if}{/if}</p></div>
        {/each}
      </details>
    {/if}
  {:else}<p class="muted">Rebuild this audit to include the exact Lean statement.</p>{/if}
</div>
<style>
  .exact { min-width: 0; }
  .name { margin: 0 0 12px; color: var(--muted); overflow-wrap: anywhere; }
  pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 15px/1.65 var(--mono); }
  .copy { margin-top: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--accent); padding: 4px 10px; cursor: pointer; font-size: 14px; }
  .carried { margin-top: 14px; }
  .carried > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .field { margin: 6px 0; }
  .field pre { font-size: 14px; }
  .origin { margin: 0; font-size: 12px; color: var(--faint); font-family: var(--mono); overflow-wrap: anywhere; }
  .exact :global(.lean button), .exact :global(.lean a) { min-height: 0; }
</style>
