<script>
  import { readingWords } from "../lib/coverage.js";
  import { refText } from "../lib/findings.js";
  import { COMPOSITION_RELATIONS, COMPOSITION_HOW, OBLIGATION_KINDS, newStep, newIdentification, newObligation,
    withoutStep, compositionOp, stepEvidence, linkEvidence } from "../lib/workspace.js";

  // Writing a composition of the open investigation (`composition.py`), under
  // `machinechecked view`: its steps (what each establishes, the evidence it rests on, the earlier
  // steps it follows from, the requirements it establishes, its substitutions and inference),
  // the identifications between the steps' objects (citing connections between objects where
  // they rest on them), its obligations, its coverage and a Lean bridge. `draft` is the form
  // (`workspace.newComposition` or `compositionDraft`); `save(ops)` sends the engine's `put` and
  // resolves true once it is saved; `error` is the engine's refusal, shown as it words it.
  // Only the investigation's own evidence and requirements are offered.
  let { draft = $bindable(), claim, here, busy = false, error = null, save, oncancel } = $props();

  const COVERAGE = ["full", "partial", "changed", "related", "unresolved"];
  const steps = $derived(draft.steps);
  const forSteps = $derived(stepEvidence(here?.evidence));
  const forLinks = $derived(linkEvidence(here?.evidence));
  const requirements = $derived(here?.reading?.requirements || []);
  const ev = $derived(Object.fromEntries((here?.evidence || []).map((e) => [e.id, e])));
  const label = (id) => (ev[id] ? refText(ev[id].ref) : id);

  const toggle = (list, x, on) => (on ? [...list.filter((y) => y !== x), x] : list.filter((y) => y !== x));
  const earlier = (i) => steps.slice(0, i);

  async function submit() {
    if (await save([compositionOp(draft, claim.id)])) oncancel?.();
  }
</script>

{#snippet picks(list, chosen, onpick, attr)}
  {#each list as e (e.id)}<label class="pick"><input type="checkbox" {...{ [attr]: e.id }} checked={chosen.includes(e.id)} onchange={(x) => onpick(e.id, x.currentTarget.checked)} /> <code>{refText(e.ref)}</code></label>{/each}
{/snippet}

<div class="compose" data-composing={draft.id || "new"}>
  <p class="small faint">{draft.id ? `Editing composition ${draft.id}.` : "A new composition."} Each step rests on evidence of this investigation or on earlier steps; the engine checks the argument's structure when it is saved. Lean has not checked the argument; a bridge is checked when it is saved.</p>
  <textarea bind:value={draft.statement} rows="2" placeholder="The combined statement, in words (optional)" aria-label="Combined statement"></textarea>

  <h4>Steps</h4>
  {#each draft.steps as s, i (s.id)}
    <fieldset class="step" data-step-edit={s.id}>
      <legend>Step <code>{s.id}</code></legend>
      <textarea bind:value={s.establishes} rows="2" placeholder="What this step establishes" aria-label={"What " + s.id + " establishes"}></textarea>
      <p class="small"><span class="faint">Rests on:</span>
        {#if forSteps.length}{@render picks(forSteps, s.uses, (id, on) => (s.uses = toggle(s.uses, id, on)), "data-use")}
        {:else}<span class="faint">no evidence to cite yet: save the results it rests on as evidence first.</span>{/if}</p>
      {#if i > 0}
        <p class="small"><span class="faint">Follows from:</span>
          {#each earlier(i) as t (t.id)}<label class="pick"><input type="checkbox" data-after={t.id} checked={s.after.includes(t.id)} onchange={(x) => (s.after = toggle(s.after, t.id, x.currentTarget.checked))} /> {t.id}</label>{/each}</p>
      {/if}
      {#if requirements.length}
        <p class="small"><span class="faint">Establishes the requirements:</span>
          {#each requirements as r (r.id)}<label class="pick"><input type="checkbox" data-req={r.local_id} checked={s.requirements.includes(r.local_id)} onchange={(x) => (s.requirements = toggle(s.requirements, r.local_id, x.currentTarget.checked))} /> {r.local_id}</label>{/each}</p>
      {/if}
      {#each s.substitutions as x, k (k)}
        <p class="small row" data-substitution={k}><input class="short" bind:value={x.variable} placeholder="variable" aria-label="Variable" />
          <span class="faint">:=</span> <input class="short" bind:value={x.value} placeholder="value" aria-label="Value" />
          <label>in <select bind:value={x.in} aria-label="In the evidence"><option value="">(the step)</option>{#each s.uses as u (u)}<option value={u}>{label(u)}</option>{/each}</select></label>
          <button class="link" onclick={() => (s.substitutions = s.substitutions.filter((_, j) => j !== k))}>Remove</button></p>
      {/each}
      <p class="small"><button class="link" onclick={() => (s.substitutions = [...s.substitutions, { variable: "", value: "", in: "" }])}>Add a substitution</button></p>
      <textarea bind:value={s.inference} rows="2" placeholder="Your own inference in this step, if any" aria-label={"Inference of " + s.id}></textarea>
      {#if steps.length > 1}<p class="small"><button class="link" onclick={() => (draft = withoutStep(draft, s.id))}>Remove step {s.id}</button></p>{/if}
    </fieldset>
  {/each}
  <p class="small"><button class="act" onclick={() => (draft.steps = [...draft.steps, newStep(draft.steps)])}>Add a step</button></p>

  <h4>Identifications</h4>
  {#each draft.identifications as x, k (k)}
    <fieldset class="ident" data-ident-edit={k}>
      <p class="small row">
        <select bind:value={x.left.step} aria-label="Left step">{#each steps as t (t.id)}<option value={t.id}>{t.id}</option>{/each}</select>
        <input class="short" bind:value={x.left.object} placeholder="object" aria-label="Left object" />
        <span class="faint">and</span>
        <select bind:value={x.right.step} aria-label="Right step">{#each steps as t (t.id)}<option value={t.id}>{t.id}</option>{/each}</select>
        <input class="short" bind:value={x.right.object} placeholder="object" aria-label="Right object" /></p>
      <p class="small row"><label>are <select bind:value={x.relation} aria-label="Relation">{#each COMPOSITION_RELATIONS as r}<option value={r}>{r}</option>{/each}</select></label>
        <label>known by <select bind:value={x.how} aria-label="How it is known">{#each COMPOSITION_HOW as h}<option value={h}>{h}</option>{/each}</select></label></p>
      {#if x.how === "evidence"}
        <p class="small"><span class="faint">Evidence, connections between objects included:</span>
          {@render picks(forLinks, x.evidence, (id, on) => (x.evidence = toggle(x.evidence, id, on)), "data-ident-evidence")}</p>
      {/if}
      <p class="small"><button class="link" onclick={() => (draft.identifications = draft.identifications.filter((_, j) => j !== k))}>Remove</button></p>
    </fieldset>
  {/each}
  <p class="small"><button class="act" onclick={() => (draft.identifications = [...draft.identifications, newIdentification(draft.steps)])}>Add an identification</button></p>

  <h4>Obligations</h4>
  {#each draft.obligations as o, k (o.id)}
    <fieldset class="obligation" data-obligation-edit={o.id}>
      <legend><code>{o.id}</code>{#if o.connection}<span class="faint">{" · left by the connection " + label(o.connection)}</span>{/if}</legend>
      <p class="small row"><select bind:value={o.kind} aria-label="Kind">{#each OBLIGATION_KINDS as kd}<option value={kd}>{kd}</option>{/each}</select>
        <select bind:value={o.state} aria-label="State"><option value="open">open</option><option value="discharged">discharged</option></select></p>
      <textarea bind:value={o.text} rows="2" placeholder="What the argument still needs" aria-label={"What " + o.id + " needs"}></textarea>
      <p class="small"><span class="faint">Discharged by steps:</span>
        {#each steps as t (t.id)}<label class="pick"><input type="checkbox" data-by-step={t.id} checked={o.steps.includes(t.id)} onchange={(x) => (o.steps = toggle(o.steps, t.id, x.currentTarget.checked))} /> {t.id}</label>{/each}</p>
      <p class="small"><span class="faint">Or by evidence:</span>
        {@render picks(forLinks, o.evidence, (id, on) => (o.evidence = toggle(o.evidence, id, on)), "data-by-evidence")}</p>
      <p class="small"><button class="link" onclick={() => (draft.obligations = draft.obligations.filter((_, j) => j !== k))}>Remove</button></p>
    </fieldset>
  {/each}
  <p class="small"><button class="act" onclick={() => (draft.obligations = [...draft.obligations, newObligation(draft.obligations)])}>Add an obligation</button></p>

  <h4>Coverage and bridge</h4>
  <p class="small"><label>Coverage <select bind:value={draft.coverage} aria-label="Composition coverage"><option value="">not given</option>{#each COVERAGE as c}<option value={c}>{readingWords(c)}</option>{/each}</select></label></p>
  <p class="small row"><input bind:value={draft.bridge.theorem} placeholder="theorem" aria-label="Bridge theorem" />
    <span class="faint">proves exactly</span> <input bind:value={draft.bridge.target} placeholder="target proposition" aria-label="Bridge target" /></p>
  <p class="small faint">A bridge is a theorem whose type is exactly a target proposition the project defines; Lean checks it when the composition is saved, and refuses one it does not check.</p>
  <p class="small"><button class="act" disabled={busy} onclick={submit}>Save composition</button> <button class="link" disabled={busy} onclick={() => oncancel?.()}>Cancel</button></p>
  {#if error}<p class="bad small" role="alert">{error}</p>{/if}
</div>

<style>
  .compose { margin: 6px 0; display: flex; flex-direction: column; gap: 4px; }
  .compose h4 { font-size: 13px; margin: 8px 0 2px; }
  fieldset { border: 1px solid var(--border); border-radius: 6px; padding: 4px 8px; margin: 4px 0; min-width: 0; }
  legend { font-size: 13px; }
  p { margin: 2px 0; }
  .row { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center; }
  .pick { display: inline-flex; gap: 4px; align-items: center; margin-right: 10px; overflow-wrap: anywhere; max-width: 100%; vertical-align: middle; }
  .pick input { flex: none; margin: 0; }
  textarea { display: block; width: 100%; box-sizing: border-box; font: inherit; font-size: 13px; margin: 4px 0; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
  input:not([type="checkbox"]), select { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); min-width: 0; max-width: 100%; }
  .short { width: 9em; }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .act:disabled { opacity: 0.5; cursor: default; }
  .link { font: inherit; font-size: 13px; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  .bad { color: var(--st-refuted); }
  code { font-size: 12px; overflow-wrap: anywhere; }
</style>
