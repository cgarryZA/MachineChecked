<script>
  import { evidenceView } from "../lib/presentation.js";
  import { loadDecl, siteIndex } from "../lib/data.js";
  import { moduleSourceUrl, sourceLabel, sourceTitle } from "../lib/issue.js";
  import LeanText from "./LeanText.svelte";
  import Definition from "./Definition.svelte";

  // One Lean declaration of a closure, loaded from the shared store when it is opened.
  // `hideReview` keeps the author's review (and the review state) out of sight, as the review
  // queue does until the reviewer has recorded a verdict.
  // The claim inspector opens the declaration and its complete value.
  let { name, key, open = false, onref, hideReview = false, inspector = false, index = siteIndex } = $props();
  let expanded = $state(false);
  let d = $state(null);
  $effect(() => { if (open || inspector) expanded = true; });
  let error = $state(null);
  // The sub-term selected in the definition, shared between its readable and exact views.
  let selId = $state(null);
  $effect(() => {
    if (expanded && !d && !error) {
      if (!key) error = "not part of this claim's closure in this release";
      else loadDecl(key).then((x) => (d = x)).catch((e) => (error = `record ${key} missing: ${e.message}`));
    }
  });
</script>

{#snippet head()}
  <code>{name}</code>
  {#if d && inspector}
    <span class="faint">{d.kind}</span>
  {:else if d}
    <span class="faint">{d.kind}{d.module ? " · " + d.module : ""}{d.range ? ":" + d.range.line : ""}</span>
    {#if d.review && !hideReview}<span class={"rv rv-" + d.review.state} title={evidenceView("review", d.review).detail}>{evidenceView("review", d.review).word}</span>{/if}
  {/if}
{/snippet}

{#snippet body()}
    {#if error}
      <p class="err">{error}</p>
    {:else if !d}
      <p class="faint">Loading…</p>
    {:else if inspector && d.defined_by !== undefined}
      <Definition {d} {onref} {selId} onselect={(id) => (selId = id)} />
      <Definition {d} view="exact" heading={false} {onref} {selId} onselect={(id) => (selId = id)} />
      <details class="extra">
        <summary>Details</summary>
        {@render extra()}
      </details>
    {:else if inspector}
      {#if d.signature}<LeanText pp={d.signature} {onref} refs={d.uses} />{/if}
      {#if d.value}
        <p class="lbl">value</p>
        <LeanText pp={d.value} {onref} refs={d.uses} />
      {/if}
      <details class="extra">
        <summary>Details</summary>
        {@render extra()}
      </details>
    {:else}
      {#if index && moduleSourceUrl(index, d.module, d.range?.line)}
        <p class="small"><a href={moduleSourceUrl(index, d.module, d.range?.line)} target="_blank" rel="noopener" title={sourceTitle(index)}>{sourceLabel(index)}</a></p>
      {/if}
      {#if d.doc}
        {#if hideReview}<p class="lbl">author’s docstring</p>{/if}
        <p class="doc">{d.doc}</p>
      {/if}
      {#if d.defined_by !== undefined}
        <p class="lbl">what it says</p>
        <Definition {d} {onref} {selId} onselect={(id) => (selId = id)} />
        {#if d.lean_source}
          <p class="lbl">Lean source</p>
          <pre class="src">{d.lean_source.text}</pre>
        {/if}
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
{/snippet}

{#snippet extra()}
  <p class="small faint">{d.module}{d.range ? ":" + d.range.line : ""}
    {#if index && moduleSourceUrl(index, d.module, d.range?.line)} · <a href={moduleSourceUrl(index, d.module, d.range?.line)} target="_blank" rel="noopener" title={sourceTitle(index)}>{sourceLabel(index)}</a>{/if}</p>
  {#if d.doc}<p class="lbl">docstring</p><p class="doc">{d.doc}</p>{/if}
  {#if d.review}<p class="lbl">review: <span class={"rv rv-" + d.review.state} title={evidenceView("review", d.review).detail}>{evidenceView("review", d.review).word}</span></p>{/if}
  {#each d.review?.current || [] as r}
    <p class="lbl">{r.by}{r.kind === "ai" ? " (AI)" : r.kind === "human" ? " (human)" : ""} · {r.provenance}</p>
    {#if r.text}<pre class="rtext">{r.text}</pre>{/if}
  {/each}
  {#if d.fingerprint}<p class="fp faint" title={d.legacy_hash ? "legacy " + d.legacy_hash : ""}>{d.fingerprint.slice(0, 24)}…</p>{/if}
{/snippet}

{#if inspector}
  <div class="decl inspector" id={"decl-" + name}>
    <p class="ihead">{@render head()}</p>
    {@render body()}
  </div>
{:else}
  <details class="decl" id={"decl-" + name} bind:open={expanded}>
    <summary>{@render head()}</summary>
    {#if expanded}{@render body()}{/if}
  </details>
{/if}

<style>
  .decl { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; margin: 6px 0; background: var(--surface); }
  summary { cursor: pointer; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .inspector { padding: 10px 14px; }
  .ihead { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin: 0; overflow-wrap: anywhere; }
  .extra { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 6px; }
  .extra > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .show { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-size: 13px; }
  .doc { margin: 8px 0; color: var(--muted); }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .fp { font-family: var(--mono); font-size: 11px; margin: 8px 0 2px; }
  .src { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.55 var(--mono); }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 2px 0 0; }
  .rv { font-size: 12px; }
  .err { color: var(--st-malformed); font-size: 13px; }
  .rv-reviewed { color: var(--st-accepted); }
  .rv-author-reviewed { color: var(--st-proved); }
  .rv-pending, .rv-stale { color: var(--st-open); }
</style>
