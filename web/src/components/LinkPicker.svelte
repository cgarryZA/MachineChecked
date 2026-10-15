<script>
  import { loadLeanIndex } from "../lib/data.js";

  // Search the project's declarations and pick one to link.
  let { index, onpick, disabled = false } = $props();
  let q = $state("");
  let decls = $state(null);

  function load() {
    if (!decls) loadLeanIndex(index).then((d) => (decls = d)).catch(() => (decls = []));
  }
  const results = $derived.by(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!decls || !words.length) return [];
    return decls.filter((d) => words.every((w) => (d.name + " " + d.doc).toLowerCase().includes(w))).slice(0, 12);
  });
</script>

<div class="picker">
  <input type="search" placeholder="Link a different Lean declaration…" bind:value={q} onfocus={load} {disabled} />
  {#if results.length}
    <ul>
      {#each results as d (d.name)}
        <li>
          <div class="info"><code>{d.name}</code> <span class="faint">{d.kind}</span>
            <div class="ty">{d.type}</div></div>
          <button class="btn" {disabled} onclick={() => onpick(d.name)}>Link</button>
        </li>
      {/each}
    </ul>
  {:else if q && decls}
    <p class="faint small">No declaration matches.</p>
  {/if}
</div>

<style>
  .picker { margin-top: 12px; }
  input { width: 100%; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: 14px; }
  ul { list-style: none; margin: 6px 0 0; padding: 0; border: 1px solid var(--border); border-radius: 8px; max-height: 320px; overflow: auto; background: var(--surface); }
  li { display: flex; gap: 10px; align-items: center; justify-content: space-between; padding: 6px 10px; border-bottom: 1px solid var(--border); }
  li:last-child { border-bottom: 0; }
  .info { min-width: 0; }
  .ty { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .btn { flex: none; border: 1px solid var(--accent); background: var(--accent); color: white; border-radius: 6px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
  .small { font-size: 13px; }
</style>
