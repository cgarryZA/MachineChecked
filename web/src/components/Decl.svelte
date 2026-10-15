<script>
  import LeanText from "./LeanText.svelte";

  // One Lean declaration of the definition closure, expandable one level at a time.
  let { d, open = false, onref } = $props();
  let expanded = $state(false);
  $effect(() => { if (open) expanded = true; });
</script>

<details class="decl" id={"decl-" + d.name} bind:open={expanded}>
  <summary>
    <code>{d.name}</code>
    <span class="faint">{d.kind}{d.module ? " · " + d.module : ""}{d.range ? ":" + d.range.line : ""}</span>
  </summary>
  {#if expanded}
  {#if d.doc}<p class="doc">{d.doc}</p>{/if}
  {#if d.signature}
    <p class="lbl">type</p>
    <LeanText pp={d.signature} {onref} refs={d.uses} />
  {/if}
  {#if d.value}
    <p class="lbl">value</p>
    <LeanText pp={d.value} {onref} refs={d.uses} />
  {/if}
  {#if d.fingerprint}<p class="fp faint" title={d.legacy_hash ? "legacy " + d.legacy_hash : ""}>{d.fingerprint.slice(0, 24)}…</p>{/if}
  {/if}
</details>

<style>
  .decl { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; margin: 6px 0; background: var(--surface); }
  summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .doc { margin: 8px 0; color: var(--muted); }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .fp { font-family: var(--mono); font-size: 11px; margin: 8px 0 2px; }
</style>
