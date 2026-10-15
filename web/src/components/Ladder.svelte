<script>
  // The evidence ladder of a clause: each rung reports its own state, and none implies another.
  let { rungs } = $props();
  const MARK = { pass: "✓", fail: "✗", open: "…", author: "◐", none: "–", "n/a": "–", "pdf-only": "◌", "not-run": "○", unverified: "?" };
  const WORD = { pass: "passed", fail: "failed", open: "open", author: "author only", none: "none", "n/a": "not applicable", "pdf-only": "PDF only", "not-run": "not run", unverified: "unverified" };
</script>

<ol class="ladder">
  {#each rungs as r}
    <li class={"r " + r.state.replace("/", "")} title={r.detail}>
      <span class="m" aria-hidden="true">{MARK[r.state] || "?"}</span>
      <span class="n">{r.rung}</span>
      <span class="w">{WORD[r.state] || r.state}</span>
    </li>
  {/each}
</ol>

<style>
  .ladder { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 6px; }
  .r { display: flex; align-items: center; gap: 6px; padding: 3px 10px 3px 6px; border-radius: 6px; border: 1px solid var(--border); font-size: 12px; background: var(--surface); }
  .m { width: 18px; height: 18px; border-radius: 50%; display: inline-grid; place-items: center; font-size: 11px; color: white; background: var(--faint); }
  .n { font-weight: 600; }
  .w { color: var(--muted); }
  .pass .m { background: var(--st-accepted); }
  .fail .m { background: var(--st-malformed); }
  .open .m { background: var(--st-open); }
  .author .m { background: var(--st-proved); }
  .pdf-only .m { background: var(--st-open); }
  .not-run .m { background: transparent; color: var(--faint); border: 1.5px solid var(--faint); }
  .unverified .m { background: var(--st-open); }
</style>
