<script>
  import PaperExcerpt from "./PaperExcerpt.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import { evidenceView } from "../lib/presentation.js";

  // The paper's statement, as printed: typeset from its pinned LaTeX source when the whole
  // passage can be typeset faithfully (`claim.excerpt`), else the PDF excerpt, else its raw
  // source. Used wherever the paper's statement is shown (the claim view, the review queue).
  let { claim, paper, symbols = [], active = [], onsym = null, evidence = true } = $props();
  // Whether this excerpt was typeset whole (null until it is tried), kept with the excerpt it is
  // about so that another claim's result never applies.
  let tried = $state(null);
  const key = $derived(claim.id + " " + (claim.excerpt?.fingerprint || ""));
  const typeset = $derived(tried && tried.key === key ? tried.ok : null);
  const pdf = $derived((paper?.pdf_url || paper?.pdf) && claim.anchor?.begin ? (paper.pdf_url || "data/" + paper.pdf) : null);
  // A passage whose source differs from the frozen inventory is not shown as the reviewed text.
  const native = $derived(!!claim.excerpt?.ready && claim.source_matches !== false);
  const raw = $derived(claim.excerpt?.text ?? claim.statement_tex);
</script>
{#if native}
  <div class="native" hidden={typeset !== true}><PaperExcerpt excerpt={claim.excerpt} {symbols} {active} {onsym} onstatus={(ok) => (tried = { key, ok })} /></div>
{/if}
{#if native && typeset === true}
  {#if pdf}<details class="original"><summary>As printed in the PDF</summary><PdfCrop url={pdf} anchor={claim.anchor} /></details>{/if}
  <details class="original rawsrc"><summary>LaTeX source</summary><pre>{raw}</pre></details>
{:else if !native || typeset === false}
  {#if pdf}<PdfCrop url={pdf} anchor={claim.anchor} />
  {:else if raw}<p class="muted">Manuscript source</p><pre>{raw}</pre>
  {:else}<p class="muted">Open the paper to read this statement.</p>{/if}
{/if}
{#if evidence && claim.source_evidence && ["pass", "fail", "open"].includes(claim.source_evidence.state)}
  <p class="source" title={evidenceView("source", claim.source_evidence).detail}>Source: {evidenceView("source", claim.source_evidence).word}</p>
{/if}
<style>
  .original { margin-top: 8px; font-size: 14px; }
  summary { cursor: pointer; color: var(--accent); padding: 4px 0; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.6 var(--mono); }
  .source { color: var(--muted); font-size: 13px; margin: 8px 0; }
</style>
