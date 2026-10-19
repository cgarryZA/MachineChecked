<script>
  import LeanText from "./LeanText.svelte";
  let { st, name = null, onref = null } = $props();
  let copied = $state(false), error = $state(null);
  const text = $derived(typeof st?.exact === "string" ? st.exact : st?.exact?.text || st?.exact?.segments?.map((s) => s.t).join(""));
  async function copy() {
    try { await navigator.clipboard.writeText(text); copied = true; error = null; }
    catch { error = "Select the statement to copy it."; }
  }
</script>
<div class="exact">
  {#if name}<p class="name"><code>{name}</code></p>{/if}
  {#if text}
    <pre><LeanText pp={typeof st.exact === "string" ? { text } : st.exact} {onref} refs={[...(st.closure || []), ...(st.direct || [])]} /></pre>
    <button class="copy" onclick={copy}>{copied ? "Copied" : "Copy Lean"}</button>
    {#if error}<p role="status">{error}</p>{/if}
  {:else}<p class="muted">Rebuild this audit to include the exact Lean statement.</p>{/if}
</div>
<style>
  .exact { min-width: 0; }
  .name { margin: 0 0 12px; color: var(--muted); overflow-wrap: anywhere; }
  pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 15px/1.65 var(--mono); }
  .copy { margin-top: 12px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--accent); padding: 4px 10px; cursor: pointer; font-size: 14px; }
  .exact :global(.lean button), .exact :global(.lean a) { min-height: 0; }
</style>
