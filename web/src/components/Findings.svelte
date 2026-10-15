<script>
  // Findings by tier. A violation contradicts acceptance; a warning asks for investigation and
  // may be wrong; an obligation is a judgement only a reviewer can make.
  let { findings } = $props();
  const TIERS = [
    ["violation", "Violations", "mechanical facts that contradict acceptance"],
    ["warning", "Warnings", "patterns that may change the meaning; they can be wrong"],
    ["obligation", "Review obligations", "judgements only a reviewer can make"],
  ];
</script>

{#if !findings.length}
  <p class="muted">None.</p>
{:else}
  {#each TIERS as [t, title, gloss]}
    {@const fs = findings.filter((f) => f.tier === t)}
    {#if fs.length}
      <div class={"tier " + t}>
        <h3>{title} <span class="faint">· {gloss}</span></h3>
        <ul>
          {#each fs as f (f.id)}
            <li class:dismissed={f.dismissed}>
              {f.message}
              {#if f.dismissed}
                <span class="dz">dismissed by {f.dismissed.by}: “{f.dismissed.rationale}”</span>
              {:else if f.dismissal_stale}
                <span class="dz">an earlier dismissal no longer applies: the statement changed</span>
              {/if}
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  {/each}
{/if}

<style>
  h3 { font-size: 14px; margin: 10px 0 4px; }
  .faint { font-weight: 400; font-size: 12px; }
  ul { margin: 0; padding-left: 18px; }
  li { margin: 3px 0; }
  .violation li::marker { color: var(--tier-violation); }
  .warning li::marker { color: var(--tier-warning); }
  .obligation li::marker { color: var(--tier-obligation); }
  .violation h3 { color: var(--tier-violation); }
  .warning h3 { color: var(--tier-warning); }
  .obligation h3 { color: var(--tier-obligation); }
  .dismissed { color: var(--faint); }
  .dz { display: block; font-size: 12px; color: var(--muted); }
</style>
