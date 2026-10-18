<script>
  import { statusView } from "../lib/presentation.js";
  import TexInline from "./TexInline.svelte";
  import { loadSearch } from "../lib/data.js";
  import { href, go } from "../lib/route.svelte.js";

  // Search over claims (numbers, titles, ids, printed statements, Lean names) and declarations.
  let { index } = $props();
  let q = $state("");
  let data = $state(null);
  let open = $state(false);
  let sel = $state(0);

  function load() {
    if (!data) loadSearch(index).then((d) => (data = d)).catch(() => (data = { claims: [], decls: [] }));
  }

  const results = $derived.by(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!data || !words.length) return [];
    const hit = (t) => { const s = t.toLowerCase(); return words.every((w) => s.includes(w)); };
    const out = [];
    for (const c of data.claims) {
      const head = `${c.number} ${c.title} ${c.id}`;
      const lean = c.lean.join(" ");
      if (hit(head)) out.push({ kind: "claim", c, rank: 0 });
      else if (hit(lean)) out.push({ kind: "claim", c, rank: 1, why: c.lean.find((n) => words.some((w) => n.toLowerCase().includes(w))) });
      else if (hit(c.statement)) out.push({ kind: "claim", c, rank: 2, why: "matches the statement" });
    }
    for (const d of data.decls) if (hit(d.name)) out.push({ kind: "decl", d, rank: 3 });
    return out.sort((a, b) => a.rank - b.rank).slice(0, 30);
  });

  const c_heading = (r) => (r.kind === "claim" ? r.c.heading || r.c.title : null);

  function choose(r) {
    open = false;
    q = "";
    if (r.kind === "claim") go(href(index.release, "read", r.c.paper, r.c.id));
    else go(href(index.release, "claim", r.d.claims[0]));
  }
  function key(e) {
    if (e.key === "ArrowDown") { sel = Math.min(sel + 1, results.length - 1); e.preventDefault(); }
    else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); e.preventDefault(); }
    else if (e.key === "Enter" && results[sel]) choose(results[sel]);
    else if (e.key === "Escape") open = false;
  }
</script>

<div class="search">
  <input type="search" placeholder="Search claims, statements, Lean names" bind:value={q}
    onfocus={() => { load(); open = true; }} oninput={() => { open = true; sel = 0; }}
    onkeydown={key} onblur={() => setTimeout(() => (open = false), 150)} aria-label="Search" />
  {#if open && q && results.length}
    <ul class="results" role="listbox">
      {#each results as r, i}
        <li role="option" aria-selected={i === sel}>
          <button class:sel={i === sel} onmousedown={() => choose(r)}>
            {#if r.kind === "claim"}
              <span class="t">{r.c.number || r.c.id}</span>
              <span class="p">Paper {r.c.paper}</span>
              <span class="s">{statusView(r.c).label}</span>
              {#if c_heading(r)}<span class="w"><TexInline text={c_heading(r)} /></span>{/if}
              {#if r.why}<span class="w">{r.why}</span>{/if}
            {:else}
              <span class="t mono">{r.d.name}</span>
              <span class="p">declaration · in {r.d.claims.length} claim{r.d.claims.length === 1 ? "" : "s"}</span>
            {/if}
          </button>
        </li>
      {/each}
    </ul>
  {:else if open && q && data}
    <ul class="results"><li class="none">No match.</li></ul>
  {/if}
</div>

<style>
  .search { position: relative; flex: 1; max-width: 420px; min-width: 160px; }
  input { width: 100%; padding: 6px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font: inherit; font-size: 14px; }
  .results { position: absolute; top: 38px; left: 0; right: 0; z-index: 50; list-style: none; margin: 0; padding: 4px; max-height: 70vh; overflow: auto;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px; box-shadow: 0 8px 24px rgb(0 0 0 / 0.15); }
  button { display: flex; flex-wrap: wrap; gap: 2px 10px; align-items: baseline; width: 100%; text-align: left; border: 0; background: none; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
  button.sel, button:hover { background: var(--accent-soft); }
  .t { font-weight: 600; }
  .p, .s { font-size: 12px; color: var(--muted); }
  .w { flex-basis: 100%; font-size: 12px; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .none { padding: 8px; color: var(--muted); }
  .mono { font-family: var(--mono); font-size: 13px; }
</style>
