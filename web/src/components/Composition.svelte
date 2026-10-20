<script>
  import { compositionView } from "../lib/coverage.js";

  // An auditor's composition (`composition.py`): the steps of the argument, the result each one
  // rests on, the substitutions and identifications between steps, the obligations and any Lean
  // bridge. It is the auditor's argument unless Lean checks its bridge now, and it changes no
  // status. `evidence` holds the evidence records its steps cite.
  let { c, evidence = [] } = $props();

  const OBLIGATION = { "compatible witnesses": "compatible witness choices", "local to global": "a local-to-global step",
    "equality transport": "an equality transport", "constant dependence": "a constant's allowed dependence",
    genericity: "a genericity condition", "side condition": "a side condition", other: "an obligation" };
  const v = $derived(compositionView(c));
  const byId = $derived(Object.fromEntries((evidence || []).map((e) => [e.id, e])));

  function refText(id) {
    const r = byId[id]?.ref;
    if (!r) return id;
    if (r.app) return `${r.app.callee} applied in ${r.app.caller}${r.app.result ? ", giving " + r.app.result : ""}`;
    if (r.fact) return `${r.fact.name || r.fact.head || "a fact"}${r.fact.type ? " : " + r.fact.type : ""}, inside the proof of ${r.fact.decl}`;
    return r.decl || id;
  }
  const side = (e) => (e.object ? `${e.object} of ${e.step}` : `an object of ${e.step}`);
</script>

{#if v}
  <div class="composition" data-composition={c.id} data-basis={v.basis} data-tone={v.tone}>
    <p class="small"><strong>{v.headline}</strong>
      <span class="faint">· composition {c.id}{c.created_by ? ` · ${c.created_by}` : ""}</span>
      {#if c.currency?.state === "stale"}<span class="stale"> · a result it uses changed since</span>{/if}</p>
    {#if c.statement}<p class="small text">{c.statement}</p>{/if}
    <ol class="steps">
      {#each c.steps || [] as s (s.id)}
        <li class="small" data-step={s.id}><code>{s.id}</code>
          {#if s.establishes}<span class="text">{s.establishes}</span>{/if}
          <span class="faint">· from {[...(s.uses || []).map(refText), ...(s.after || []).map((a) => "step " + a)].join("; ")}{s.requirements?.length ? ` · establishes ${s.requirements.join(", ")}` : ""}</span>
          {#if s.substitutions?.length}<span class="faint"> · with</span> <code>{s.substitutions.map((x) => `${x.variable} := ${x.value}`).join(", ")}</code>{/if}
          {#if s.inference}<br /><span class="faint">The auditor's inference:</span> <span class="text">{s.inference}</span>{/if}
        </li>
      {/each}
    </ol>
    {#each c.identifications || [] as x}
      <p class="small" data-identification><span class="faint">Same object:</span> {side(x.left)} and {side(x.right)} <span class="faint">({x.relation}; {x.how}{x.evidence?.length ? ": " + x.evidence.map(refText).join("; ") : ""})</span></p>
    {/each}
    {#each c.obligations || [] as o (o.id)}
      <p class="small" data-obligation={o.id} data-state={o.state}><span class={o.state === "open" ? "open" : "faint"}>{o.state === "open" ? "Open" : "Discharged"}: {OBLIGATION[o.kind] || o.kind}</span>
        {#if o.text}<span class="text">{o.text}</span>{/if}
        {#if o.by}<span class="faint"> · by {[...(o.by.steps || []).map((s) => "step " + s), ...(o.by.evidence || []).map(refText)].join("; ")}</span>{/if}</p>
    {/each}
    {#if v.uncovered.length}<p class="small open">No step establishes {v.uncovered.join(", ")}.</p>{/if}
    {#if c.bridge}
      <p class="small" data-line="Bridge"><span class="faint">Bridge:</span> <code>{c.bridge.theorem}</code> for the target <code>{c.bridge.target}</code>.
        {#if v.bridgeState === "checked"}Lean checks its proof and that its type is exactly the target.
        {:else}<span class="stale">{v.bridgeState === "stale" ? "Out of date" : "Not checked now"}{c.bridge_check?.reasons?.length ? ": " + c.bridge_check.reasons.join("; ") : ""}.</span>{/if}</p>
    {/if}
    {#if v.nextStep}<p class="small" data-line="Next step"><span class="faint">Lean has not checked this combination. Next step:</span> {v.nextStep}</p>{/if}
  </div>
{/if}

<style>
  .composition { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 8px 0; }
  .composition p { margin: 2px 0; }
  .steps { margin: 4px 0; padding-left: 20px; }
  .steps li { margin: 2px 0; }
  .text { white-space: pre-wrap; }
  .stale { color: var(--tier-warning); }
  .open { color: var(--tier-warning); }
  code { overflow-wrap: anywhere; }
</style>
