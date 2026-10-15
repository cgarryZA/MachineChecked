<script>
  // Findings by tier. A violation contradicts acceptance and is always shown. Review obligations
  // are open work and are listed. Warnings are heuristics that can be wrong: they are grouped by
  // the operation that raised them and folded away, low-signal ones last.
  let { findings } = $props();

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
</script>

{#if !findings.length}
  <p class="muted">None.</p>
{/if}

{#if violations.length}
  <div class="tier violation">
    <h3>Violations <span class="faint">· mechanical facts that contradict acceptance</span></h3>
    <ul>{#each violations as f (f.id)}<li>{f.message}</li>{/each}</ul>
  </div>
{/if}

{#if obligations.length}
  <div class="tier obligation">
    <h3>Review obligations <span class="faint">· judgements only a reviewer can make</span></h3>
    <ul>{#each obligations as f (f.id)}<li>{f.message}</li>{/each}</ul>
  </div>
{/if}

{#if warnings.length}
  <details class="tier warning">
    <summary>
      <strong>Warnings</strong>
      <span class="faint">· heuristics that may be wrong ·
        {groups.map((g) => `${g.trigger} ×${g.items.length}`).join(", ")}</span>
    </summary>
    {#each groups as g (g.trigger)}
      <div class="group" class:low={g.low}>
        <p class="gh"><code>{g.trigger}</code> — {reason(g.items[0])}
          {#if g.low}<span class="pill">low signal</span>{/if}</p>
        <ul>
          {#each g.items as f (f.id)}
            <li class:dismissed={f.dismissed}>
              in clause {f.subject.split("#")[1] ?? ""}
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
</style>
