<script>
  import Tex from "./Tex.svelte";

  // A proof step's context in the proof, as the build holds it. A context kept only in part
  // (`context_cut`, written by the engine's `steps.cut_text`) is drawn as partial: its summary
  // says so, a note says where it was cut and how much is shown, and the text ends with a mark
  // at the cut. The words follow `compare.context_cut_reason`, so the reader says no more than
  // `compare` does.
  let { text, cut = null, open = false } = $props();

  const note = $derived(!cut ? null : cut.line
    ? `Cut at ${cut.file}:${cut.line}. This shows the first ${cut.kept} of its ${cut.chars} characters; `
      + `the context runs on to line ${cut.end_line}. Read the rest in the paper.`
    : `This shows only its first ${cut.kept} characters; the build does not record where it was cut. `
      + "Read the rest in the paper.");
</script>

<details class="context" data-cut={cut ? "cut" : "whole"} {open}>
  <summary class="small">Its context in the proof{cut ? " (cut)" : ""}</summary>
  {#if cut}<p class="cut small" role="note">{note}</p>{/if}
  <Tex {text} />
  {#if cut}<p class="cut-end small" aria-hidden="true">[cut here]</p>{/if}
</details>

<style>
  .context { margin-top: 6px; }
  .context summary { cursor: pointer; }
  .cut { margin: 6px 0 0; border-left: 3px solid var(--tier-warning); padding-left: 10px; }
  .cut-end { margin: 4px 0 0; color: var(--tier-warning); font-style: italic; }
  .small { font-size: 13px; }
</style>
