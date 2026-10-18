<script>
  import { evidenceView } from "../lib/presentation.js";
  let { evidence } = $props();
</script>

<ol class="ladder">
  {#each Object.entries(evidence || {}) as [dimension, fact]}
    {@const view = evidenceView(dimension, fact)}
    <li class={"r " + view.state} title={view.detail} data-dimension={dimension} data-state={view.state}>
      <span class="n">{view.label}</span>
      <span class="w">{view.word}</span>
    </li>
  {/each}
</ol>

<style>
  .ladder { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  .r { display: flex; align-items: center; gap: 6px; padding: 3px 10px 3px 6px; border-radius: 6px; border: 1px solid var(--border); font-size: 12px; background: var(--surface); }
  .n { font-weight: 600; }
  .w { color: var(--muted); }
</style>
