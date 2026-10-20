<script>
  import { loadLeanIndex, loadRetrieval } from "../lib/data.js";
  import { claimQuery } from "../lib/retrieval.js";

  // Search the project's declarations by their complete statements and pick one to link. The
  // search is the engine's (lib/retrieval.js): the same ranking and reasons as the suggestions
  // and `machinechecked compare --query search`. A result is a candidate, not a link.
  let { index, onpick, disabled = false, claim = null } = $props();
  let q = $state("");
  let fromClaim = $state(false);
  let ret = $state(null), decls = $state(null), loading = $state(false);

  function load() {
    if (ret || decls || loading) return;
    loading = true;
    loadRetrieval(index).then((r) => {
      if (r) ret = r;
      else return loadLeanIndex(index).then((d) => (decls = d));
    }).catch(() => (decls = [])).finally(() => (loading = false));
  }
  const linked = $derived((claim?.links || []).map((l) => l.name));
  const found = $derived.by(() => {
    if (ret) {
      if (fromClaim && claim) {
        const cq = claimQuery(ret, claim);
        return { scope: `${cq.sort} matching this claim's printed statement`, ...ret.search(cq.text, { kinds: cq.kinds, paperOrder: cq.paperOrder, limit: 12, exclude: linked }) };
      }
      if (!q.trim()) return null;
      return { scope: "declarations matching the search", ...ret.search(q, { limit: 12 }) };
    }
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!decls || !words.length) return null;
    const results = decls.filter((d) => words.every((w) => (d.name + " " + d.doc).toLowerCase().includes(w))).slice(0, 12)
      .map((d) => ({ name: d.name, kind: d.kind, reasons: [], statement: d.type, complete: d.type_complete !== false }));
    return { scope: "names and docstrings containing every word", results, page: { total: results.length } };
  });
</script>

<div class="picker">
  <div class="bar">
    <input type="search" placeholder="Search the Lean by statement, symbols or name…" bind:value={q}
      oninput={() => (fromClaim = false)} onfocus={load} {disabled} aria-label="Search the project's declarations" />
    {#if claim}
      <button class="btn ghost" {disabled} onclick={() => { load(); fromClaim = true; q = ""; }}>Search with this claim</button>
    {/if}
  </div>
  {#if found}
    <p class="faint small" role="status">
      {found.page.total} {found.scope}{#if ret}, among {ret.size} declarations of the project, linked or not{/if}.
    </p>
    {#if found.results.length}
      <ul>
        {#each found.results as d (d.name)}
          <li>
            <div class="info">
              <code>{d.name}</code> <span class="faint">{d.kind}</span>
              {#each d.reasons as r}<div class="why small">{r.text}</div>{/each}
              <details>
                <summary class="ty">{d.statement}</summary>
                <pre>{d.statement}</pre>
                {#if !d.complete}<p class="faint small">Only the beginning of this statement is in this build.</p>{/if}
              </details>
            </div>
            <button class="btn" {disabled} onclick={() => onpick(d.name)}>Link</button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="faint small">No declaration matches.</p>
    {/if}
  {:else if loading}
    <p class="faint small" role="status">Loading the project's declarations…</p>
  {/if}
</div>

<style>
  .picker { margin-top: 12px; }
  .bar { display: flex; gap: 8px; flex-wrap: wrap; }
  input { flex: 1 1 220px; min-width: 0; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: 14px; }
  ul { list-style: none; margin: 6px 0 0; padding: 0; border: 1px solid var(--border); border-radius: 8px; max-height: 420px; overflow: auto; background: var(--surface); }
  li { display: flex; gap: 10px; align-items: flex-start; justify-content: space-between; padding: 6px 10px; border-bottom: 1px solid var(--border); }
  li:last-child { border-bottom: 0; }
  .info { min-width: 0; flex: 1; }
  .why { color: var(--muted); }
  summary.ty { font-family: var(--mono); font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
  pre { font-family: var(--mono); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 4px 0; }
  .btn { flex: none; border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent); border-radius: 6px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
  .btn.ghost { background: none; color: var(--accent); }
  .small { font-size: 13px; }
</style>
