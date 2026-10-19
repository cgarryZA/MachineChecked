<script>
  import Tex from "./Tex.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import { evidenceView } from "../lib/presentation.js";
  let { claim, paper, symbols = [], active = [], onsym = null } = $props();
  let supported = $state(true);
  const hasPdf = $derived((paper?.pdf_url || paper?.pdf) && claim.anchor?.begin);
  const source = $derived(claim.statement_tex && claim.source_matches !== false && claim.anchor?.kind !== "approximate");
  $effect(() => { claim.id; claim.statement_tex; supported = true; });
</script>
{#if source}
  <div hidden={!supported}><Tex text={claim.statement_tex} {symbols} {active} {onsym} macros={paper?.macros || {}} onstatus={(ok) => supported = ok} /></div>
{/if}
{#if hasPdf}
  {#if source && supported}
    <details class="original"><summary>Original excerpt</summary><PdfCrop url={paper.pdf_url || "data/" + paper.pdf} anchor={claim.anchor} /></details>
  {:else}<PdfCrop url={paper.pdf_url || "data/" + paper.pdf} anchor={claim.anchor} />{/if}
{:else if !source || !supported}
  {#if claim.statement_tex}<p class="muted">Manuscript source</p><pre>{claim.statement_tex}</pre>
  {:else}<p class="muted">Open the paper to read this statement.</p>{/if}
{/if}
{#if claim.source_evidence && ["pass", "fail", "open"].includes(claim.source_evidence.state)}
  <p class="source" title={evidenceView("source", claim.source_evidence).detail}>Source: {evidenceView("source", claim.source_evidence).word}</p>
{/if}
<style>
  .original { margin-top: 12px; font-size: 14px; }
  summary { cursor: pointer; color: var(--accent); padding: 4px 0; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.6 var(--mono); }
  .source { color: var(--muted); font-size: 13px; margin: 8px 0; }
</style>
