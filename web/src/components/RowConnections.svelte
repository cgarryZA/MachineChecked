<script>
  import { connectionText, endText, endKey, linkedObjects, chainBetween } from "../lib/connections.js";

  // The connections between objects at one row of the comparison (`connections.placeConnections`):
  // each with its relation, scope, conditions and support in the engine's words, and where it
  // comes from, recorded by an auditor or computed from the Lean's terms, marked apart. On
  // request, the chain of connections from an object at this row to another object (`all`: every
  // connection the comparison shows). `claim` lists those placed at no row: changed since they
  // were recorded, or between objects of Lean the comparison does not show. Nothing here is a
  // status.
  let { items = [], all = [], at = null, claim = false } = $props();

  const ROLE = { candidate: "a candidate", context: "context" };
  const origin = (e) => (e.origin === "computed" ? "Computed from the Lean's terms" : "Recorded by " + e.by + (ROLE[e.role] ? ", " + ROLE[e.role] : ""));
  const reasons = (e) => [...new Set((e.currency?.changes || []).map((c) => c.reason).filter(Boolean))];
  const unknown = (e) => e.currency?.reason || "";

  // The objects a chain can start from: the ends at this row, each once.
  const starts = $derived.by(() => {
    const out = new Map();
    for (const it of items) {
      for (const s of claim ? ["from", "to"] : it.sides) {
        const e = it.entry.connection[s];
        if (!out.has(endKey(e))) out.set(endKey(e), { key: endKey(e), end: e });
      }
    }
    return [...out.values()].filter((s) => linkedObjects(all, s.key).length);
  });
  let open = $state(false);
  let fromPick = $state(null), toPick = $state(null);
  const from = $derived(starts.some((s) => s.key === fromPick) ? fromPick : starts[0]?.key ?? null);
  const targets = $derived(from ? linkedObjects(all, from) : []);
  const to = $derived(targets.some((t) => t.key === toPick) ? toPick : targets[0]?.key ?? null);
  const chain = $derived(open && from && to ? chainBetween(all, from, to) : null);
</script>

{#snippet state(e)}{#if e.state === "stale"}<span class="warn">{" · changed since it was recorded"}</span>{:else if e.state === "unchecked"}<span data-currency="unchecked">{" · not known to be current"}</span>{/if}{/snippet}

{#if items.length}
  <div class="row-connections" class:claim data-connections-at={at}>
    <p class="lbl">{claim ? "Connections not placed at a row" : "Connections"}</p>
    {#each items as { entry } (entry.key)}
      <div class="conn" data-connection={entry.key} data-origin={entry.origin} data-state={entry.state} class:stale={entry.state === "stale"}>
        <p class="small"><span class="tag">{entry.origin === "computed" ? "Computed" : "Recorded"}</span> {connectionText(entry.connection)}.</p>
        <p class="small faint by">{origin(entry)}{@render state(entry)}</p>
        {#if entry.state === "stale" && reasons(entry).length}<p class="small faint">Changed: {reasons(entry).join("; ")}.</p>{/if}
        {#if entry.state === "unchecked" && unknown(entry)}<p class="small faint">Not known to be current: {unknown(entry)}.</p>{/if}
        {#if claim}<p class="small faint">{entry.state === "stale" ? "Not placed at a row: the object it names may now be another expression." : "Its objects are in Lean this comparison does not show."}</p>{/if}
      </div>
    {/each}
    {#if starts.length}
      <details class="chain" bind:open>
        <summary class="small">Chain to another object</summary>
        {#if open}
          <p class="small pick">
            {#if starts.length > 1}<label><span class="w">From</span><select aria-label="Chain from" value={from} onchange={(e) => (fromPick = e.currentTarget.value)}>{#each starts as s (s.key)}<option value={s.key}>{endText(s.end)}</option>{/each}</select></label>
            {:else}<span>From {endText(starts[0].end)}</span>{/if}
            <label><span class="w">to</span><select aria-label="Chain to" value={to} onchange={(e) => (toPick = e.currentTarget.value)}>{#each targets as t (t.key)}<option value={t.key}>{endText(t.end)}</option>{/each}</select></label>
          </p>
          {#if chain}
            <ol class="steps" data-chain={chain.steps.length}>
              {#each chain.steps as s, i (i)}
                <li class="small" data-chain-step={i} data-origin={s.entry.origin} data-state={s.entry.state}>{connectionText(s.entry.connection)}. <span class="faint">{origin(s.entry)}{@render state(s.entry)}</span></li>
              {/each}
            </ol>
            {#if chain.sources.length > 1}<p class="small faint">Its steps come from more than one record; each step is as its source gives it.</p>{/if}
          {/if}
        {/if}
      </details>
    {/if}
  </div>
{/if}

<style>
  .row-connections { margin: 6px 0 4px; display: flex; flex-direction: column; gap: 4px; }
  .row-connections.claim { margin: 0; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 0; }
  .conn { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; }
  .conn[data-origin="computed"] { border-left-style: double; }
  .conn.stale { border-left-style: dashed; }
  .conn p, .chain p { margin: 2px 0; overflow-wrap: anywhere; }
  .tag { font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); font-weight: 600; margin-right: 4px; }
  .chain > summary { cursor: pointer; color: var(--accent); }
  .pick { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; }
  .pick label { display: flex; gap: 6px; align-items: baseline; min-width: 0; max-width: 100%; }
  .pick select { font: inherit; font-size: 13px; min-width: 0; max-width: 100%; }
  .pick .w { flex: none; }
  .steps { margin: 4px 0; padding-left: 22px; }
  .steps li { margin: 2px 0; overflow-wrap: anywhere; }
  .warn { color: var(--tier-warning); }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
</style>
