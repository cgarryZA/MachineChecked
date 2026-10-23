<script>
  // Findings by tier. A violation contradicts acceptance and is always shown. Review obligations
  // are open work, listed as review tasks. Warnings are heuristics, shown as heuristic findings:
  // they are grouped by the operation that raised them and folded away, low-signal ones last. A warning about a
  // totalised operation lists the applications it read (`occurrences`), each with its type and
  // what the type gives; `onshow` marks them in the statement.
  let { findings, onshow = null } = $props();

  const live = $derived(findings.filter((f) => !f.dismissed));
  const violations = $derived(live.filter((f) => f.tier === "violation"));
  const obligations = $derived(live.filter((f) => f.tier === "obligation"));
  const warnings = $derived(findings.filter((f) => f.tier === "warning"));
  const groups = $derived.by(() => {
    const m = new Map();
    for (const f of warnings) {
      const k = f.trigger || f.code;
      if (!m.has(k)) m.set(k, { trigger: k, low: f.signal === "low", items: [] });
      m.get(k).items.push(f);
    }
    return [...m.values()].sort((a, b) => a.low - b.low || b.items.length - a.items.length);
  });
  const reason = (f) => f.message.replace(/\s*\([^()]*occurs in [^()]*\)$/, "");
  // One reason for the group when its warnings agree; otherwise each says its own.
  const shared = (g) => g.items.every((f) => reason(f) === reason(g.items[0]));
  const STRUCTURE = {
    "complete-lattice": "a complete lattice", "conditionally-complete-lattice": "a conditionally complete lattice",
    group: "a group", "group-with-zero": "a group with zero", "one-element": "a type with one element",
    unknown: "no structure Lean finds",
  };
  const outcome = (o) => o.state === "applies" ? o.rule : o.state === "none" ? "no exceptional case in this type" : "unresolved";
  const shown = (f) => (f.occurrences || []).filter((o) => o.state !== "none" && o.at?.length);
</script>

{#if !findings.length}
  <p class="muted">None.</p>
{/if}

{#if violations.length}
  <div class="tier violation">
    <h3>Violations <span class="faint">· failed mechanical checks</span></h3>
    <ul>{#each violations as f (f.id)}<li>{f.message}</li>{/each}</ul>
  </div>
{/if}

{#if obligations.length}
  <div class="tier obligation">
    <h3>Review tasks</h3>
    <ul>{#each obligations as f (f.id)}<li>{f.message}</li>{/each}</ul>
  </div>
{/if}

{#if warnings.length}
  <details class="tier warning">
    <summary>
      <strong>Heuristic findings</strong>
      <span class="faint">·
        {groups.map((g) => `${g.trigger} ×${g.items.length}`).join(", ")}</span>
    </summary>
    {#each groups as g (g.trigger)}
      <div class="group" class:low={g.low}>
        <p class="gh"><code>{g.trigger}</code>{#if shared(g)} — {reason(g.items[0])}{/if}
          {#if g.low}<span class="pill">low signal</span>{/if}</p>
        <ul>
          {#each g.items as f (f.id)}
            <li class:dismissed={f.dismissed} data-finding={f.id}>
              in clause {f.subject.split("#")[1] ?? ""}{#if !shared(g)} — {reason(f)}{/if}
              {#if f.occurrences?.length}
                <ul class="occ">
                  {#each f.occurrences as o, i (i)}
                    <li data-state={o.state}><span class="ty">in <code>{o.type || "a type not read"}</code>{#if STRUCTURE[o.structure]}, {STRUCTURE[o.structure]}{/if}</span>: {outcome(o)}</li>
                  {/each}
                  {#if f.occurrences_complete === false}<li data-state="unresolved">the statement is too large to read every application</li>{/if}
                </ul>
                {#if onshow && shown(f).length}<button class="show" onclick={() => onshow(f)}>Show in the statement</button>{/if}
              {/if}
              {#if f.dismissed}<span class="dz">dismissed by {f.dismissed.by}: “{f.dismissed.rationale}”</span>
              {:else if f.dismissal_stale}<span class="dz">an earlier dismissal no longer applies: the statement changed</span>{/if}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </details>
{/if}

<style>
  h3 { font-size: 14px; margin: 10px 0 4px; }
  .faint { font-weight: 400; font-size: 12px; }
  ul { margin: 0; padding-left: 18px; }
  li { margin: 3px 0; }
  .violation h3, .violation li::marker { color: var(--tier-violation); }
  .obligation h3, .obligation li::marker { color: var(--tier-obligation); }
  .warning { margin-top: 10px; }
  .warning summary { cursor: pointer; color: var(--tier-warning); }
  .group { margin: 8px 0 4px 6px; }
  .group.low { opacity: 0.75; }
  .gh { margin: 0; font-size: 13px; }
  .pill { font-size: 11px; padding: 0 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: 4px; }
  .dismissed { color: var(--faint); }
  .dz { display: block; font-size: 12px; color: var(--muted); }
  .occ { list-style: none; padding-left: 8px; font-size: 12px; color: var(--muted); }
  .occ li { margin: 1px 0; overflow-wrap: anywhere; }
  .occ .ty code { color: var(--text, inherit); }
  .show { border: 0; padding: 0; background: none; font: inherit; font-size: 12px; color: var(--accent); cursor: pointer; text-decoration: underline; min-height: 0; }
</style>
