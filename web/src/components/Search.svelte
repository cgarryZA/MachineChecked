<script>
  import { loadSearch } from "../lib/data.js";
  import { project } from "../lib/project.svelte.js";
  import { href, go, withQuery } from "../lib/route.svelte.js";
  import TexInline from "./TexInline.svelte";
  let { index } = $props();
  const id = $props.id();
  let q = $state(""), data = $state(null), error = $state(null), open = $state(false), sel = $state(0);
  let attempt = $state(0), requested = $state(false), host;
  $effect(() => {
    const repo = project.repo;
    attempt; index;
    if (!requested) return;
    let current = true;
    data = null; error = null;
    loadSearch(index).then((d) => { if (current && repo === project.repo) data = d; })
      .catch((e) => { if (current) error = String(e.message || e); });
    return () => { current = false; };
  });
  const results = $derived.by(() => {
    const words = q.toLowerCase().trim().split(/\s+/).filter(Boolean);
    if (!data || !words.length) return [];
    const hit = (t) => words.every((w) => t.toLowerCase().includes(w));
    const out = [];
    for (const c of data.claims || []) {
      const head = `${c.number || ""} ${c.heading || ""} ${c.title || ""} ${c.id}`;
      if (hit(head)) out.push({ kind: "claim", c, rank: 0 });
      else if (hit((c.lean || []).join(" "))) out.push({ kind: "claim", c, rank: 1 });
      else if (hit(c.statement || "")) out.push({ kind: "claim", c, rank: 2 });
    }
    for (const d of data.decls || []) if (hit(d.name) && d.claims?.length) out.push({ kind: "decl", d, rank: 3 });
    return out.sort((a, b) => a.rank - b.rank).slice(0, 30);
  });
  function target(r) {
    if (r.kind === "claim") return href(index.release, "read", r.c.paper, r.c.id);
    const c = index.claims.find((c) => c.id === r.d.claims[0]);
    return withQuery(href(index.release, "read", c?.paper || index.papers[0]?.id, r.d.claims[0]), { inspect: r.d.name });
  }
  function choose(r) { go(target(r)); open = false; q = ""; }
  function key(e) {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) && results.length) {
      e.preventDefault(); open = true;
      sel = e.key === "Home" ? 0 : e.key === "End" ? results.length - 1
        : (sel + (e.key === "ArrowDown" ? 1 : -1) + results.length) % results.length;
      requestAnimationFrame(() => document.getElementById(`${id}-${sel}`)?.scrollIntoView({ block: "nearest" }));
    } else if (e.key === "Enter" && open && results[sel]) { e.preventDefault(); choose(results[sel]); }
    else if (e.key === "Escape") { e.preventDefault(); open = false; }
  }
</script>

<div class="search" bind:this={host} onfocusout={(e) => { if (!host.contains(e.relatedTarget)) open = false; }}>
  <input type="search" role="combobox" aria-autocomplete="list" aria-expanded={open && !!q}
    aria-controls={id} aria-activedescendant={open && results[sel] ? `${id}-${sel}` : undefined}
    placeholder="Search claims or Lean names" bind:value={q} aria-label="Search claims and definitions"
    onfocus={() => { requested = true; open = true; }} oninput={() => { open = true; sel = 0; }} onkeydown={key} />
  {#if open && q}
    <div class="results">
      {#if error}
        <p role="status">Search unavailable. <button onclick={() => attempt++}>Try again</button></p>
      {:else if !data}<p role="status">Searching…</p>
      {:else if !results.length}<p role="status">No matching claims or definitions.</p>{/if}
      <ul id={id} role="listbox" aria-label="Search results">
        {#each results as r, i}
          <li role="presentation">
            <a id={`${id}-${i}`} role="option" aria-selected={i === sel} class:sel={i === sel} href={target(r)}
              onfocus={() => sel = i} onclick={(e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); choose(r); } }}>
              {#if r.kind === "claim"}<strong>{r.c.number || r.c.id}</strong><span><TexInline text={r.c.heading || r.c.title || ""} /></span>
              {:else}<code>{r.d.name}</code><span class="muted">Definition · {r.d.claims.length} claim{r.d.claims.length === 1 ? "" : "s"}</span>{/if}
            </a>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</div>

<style>
  .search { position: relative; flex: 1 1 220px; max-width: 420px; min-width: 160px; }
  input { width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg); color: var(--text); font: inherit; }
  .results { position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 50; max-height: 65dvh; overflow: auto; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: 0 6px 20px #0002; }
  ul { list-style: none; margin: 0; padding: 4px; }
  a { display: flex; flex-direction: column; gap: 2px; padding: 10px; color: var(--text); overflow-wrap: anywhere; text-decoration: none; border-radius: 4px; }
  a.sel, a:hover { background: var(--accent-soft); }
  a span { font-size: 13px; }
  p { padding: 10px; margin: 0; }
  button { color: var(--accent); background: none; border: 0; cursor: pointer; }
  @media (max-width: 700px) { .search { max-width: none; flex-basis: 100%; } input { font-size: 16px; } }
</style>
