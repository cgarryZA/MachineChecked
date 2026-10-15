<script>
  import { loadDecl } from "../lib/data.js";
  import LeanText from "./LeanText.svelte";

  // One Lean declaration of a closure, loaded from the shared store when it is opened.
  // `hideReview` keeps the author's review (and the review state) out of sight, as the review
  // queue does until the reviewer has recorded a verdict.
  let { name, key, open = false, onref, hideReview = false } = $props();
  let expanded = $state(false);
  let d = $state(null);
  $effect(() => { if (open) expanded = true; });
  let error = $state(null);
  $effect(() => {
    if (expanded && !d && !error) {
      if (!key) error = "not part of this claim's closure in this release";
      else loadDecl(key).then((x) => (d = x)).catch((e) => (error = `record ${key} missing: ${e.message}`));
    }
  });
</script>

<details class="decl" id={"decl-" + name} bind:open={expanded}>
  <summary>
    <code>{name}</code>
    {#if d}
      <span class="faint">{d.kind}{d.module ? " · " + d.module : ""}{d.range ? ":" + d.range.line : ""}</span>
      {#if d.review && !hideReview}<span class={"rv rv-" + d.review.state}>{d.review.state}</span>{/if}
    {/if}
  </summary>
  {#if expanded}
    {#if error}
      <p class="err">{error}</p>
    {:else if !d}
      <p class="faint">Loading…</p>
    {:else}
      {#if d.doc}
        {#if hideReview}<p class="lbl">docstring (the author's words, not the definition)</p>{/if}
        <p class="doc">{d.doc}</p>
      {/if}
      {#if d.signature}
        <p class="lbl">type</p>
        <LeanText pp={d.signature} {onref} refs={d.uses} />
      {/if}
      {#if d.value}
        <p class="lbl">value</p>
        <LeanText pp={d.value} {onref} refs={d.uses} />
      {/if}
      {#if hideReview}
      {:else if d.review?.current?.length}
        {#each d.review.current as r}
          <p class="lbl">review · {r.by}{r.kind === "ai" ? " (AI)" : r.kind === "human" ? " (human)" : ""} · {r.provenance}</p>
          {#if r.text}<pre class="rtext">{r.text}</pre>{/if}
        {/each}
      {:else if d.review}
        <p class="lbl">no current review{d.review.stale?.length ? " (the last one is stale)" : ""}</p>
      {/if}
      {#if d.fingerprint}<p class="fp faint" title={d.legacy_hash ? "legacy " + d.legacy_hash : ""}>{d.fingerprint.slice(0, 24)}…</p>{/if}
    {/if}
  {/if}
</details>

<style>
  .decl { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; margin: 6px 0; background: var(--surface); }
  summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .doc { margin: 8px 0; color: var(--muted); }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .fp { font-family: var(--mono); font-size: 11px; margin: 8px 0 2px; }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 2px 0 0; }
  .rv { font-size: 12px; }
  .err { color: var(--st-malformed); font-size: 13px; }
  .rv-reviewed { color: var(--st-accepted); }
  .rv-author-reviewed { color: var(--st-proved); }
  .rv-pending, .rv-stale { color: var(--st-open); }
</style>
