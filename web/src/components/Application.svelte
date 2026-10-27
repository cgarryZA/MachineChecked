<script>
  // One application of a declaration (`callee`) in a caller, as Lean described it under
  // `machinechecked view` (the document `machinechecked compare --query uses` prints): the
  // argument supplied for each binder, where each premise's proof comes from, the conclusion
  // obtained and the objects each premise and the conclusion are about; and, asked for, every
  // local of its context. Drawn in the list of a declaration's uses and as an inspection beside
  // the comparison; `inspect` opens it as one.
  import { getContext } from "svelte";
  import { askUses, canEdit, siteIndex } from "../lib/data.js";
  import { applications } from "../lib/inspect.svelte.js";
  import LeanText from "./LeanText.svelte";

  let { a: given, callee, module = null, onref = null, index = siteIndex, inspect = null } = $props();
  const stage = getContext("comparison")?.users || ((e) => e);
  const local = $derived(canEdit(index));
  // The application with its context, once asked for.
  let full = $state(null);
  const a = $derived(full?.id === given.id ? full : given);

  const DISCHARGE = {
    assumed: "assumed by the caller",
    proved: "proved in the caller",
    local: "from a hypothesis introduced in the proof",
    helper: "a parameter of a constant Lean generated",
    unknown: "not determined from the term",
  };
  const LOCAL = {
    "caller parameter": "a parameter of the caller",
    "caller hypothesis": "a hypothesis of the caller",
    "caller instance": "an instance the caller assumes",
    "helper parameter": "a parameter of a constant Lean generated",
    "local fact": "established earlier in the proof",
    "local definition": "defined in the proof",
    "local hypothesis": "a hypothesis introduced in the proof",
    "local variable": "a variable introduced in the proof",
  };
  // The objects each premise (by its index) and the conclusion (`result`) are about.
  function about(a) {
    const out = {};
    for (const o of a.objects || []) for (const p of o.properties) (out[p.basis === "premise" ? p.index : "result"] ||= []).push(o.binder);
    return out;
  }
  const ab = $derived(about(a));
  // The application asked for again in its caller alone, which lists its whole context.
  let reading = $state(null);
  async function inContext() {
    const id = given.id;
    reading = "asking";
    try {
      const got = stage(await askUses(callee, module, id)).applications?.[0];
      if (!got) throw new Error(`Lean no longer describes ${id}.`);
      applications.set(callee + "|" + id, got);
      full = got;
      reading = null;
    } catch (e) { reading = e.message; }
  }
</script>

<div class="app" data-app={a.id}>
  <p class="ahead">In {#if onref}<button class="r" onclick={() => onref(a.caller)}>{a.caller}</button>{:else}<code>{a.caller}</code>{/if}
    {#if a.via}<span class="faint small">(in {a.via})</span>{/if}
    {#if a.caller_claims?.length}<span class="small linked">linked to {a.caller_claims.join(", ")}</span>{/if}
    <span class="faint small" title={a.location?.note}>at {a.location?.path}{a.location?.range ? `, lines ${a.location.range.line}–${a.location.range.end_line}` : ""}</span>
    {#if inspect}<button class="r inspect" onclick={inspect}>Inspect</button>{/if}</p>
  {#if !a.available}
    <p class="small warn">Not described: {(a.errors || []).join("; ")}</p>
  {:else}
    {#if a.context}
      <p class="lbl">context</p>
      <ul class="params ctx">{#each a.context as c}<li><code>{c.name}</code> <span class="ty"><LeanText pp={c.type} /></span> <span class="faint small">{LOCAL[c.kind] || "in the context"}</span></li>{/each}</ul>
    {:else if local}
      <button class="btn ghost" onclick={inContext} disabled={reading === "asking"}>{reading === "asking" ? "Asking Lean…" : "Show its context"}</button>
      {#if reading && reading !== "asking"}<p class="small warn">{reading}</p>{/if}
    {/if}
    <ul class="params">
      {#each a.params as p}
        <li class={"role-" + p.role}>
          <div class="sig"><code>{p.binder}</code> <span class="faint small">{p.role}{p.binder_info !== "explicit" ? ", " + p.binder_info : ""}</span> <span class="ty"><LeanText pp={p.type} /></span>{#if ab[p.index]} <span class="faint small about">about {ab[p.index].join(", ")}</span>{/if}</div>
          <div class="src">
            {#if p.role === "premise"}
              <span class={"d d-" + p.discharge}>{DISCHARGE[p.discharge]}</span><span class="small faint">: {p.supplied}</span>
            {:else}
              {#if p.argument}<span class="small faint">:=&nbsp;</span><LeanText pp={p.argument} />{/if}
              <span class="small faint">({p.supplied})</span>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
    {#each a.unsupplied || [] as o}<p class="small faint">Left open: <code>{o.binder}</code> ({o.role}).</p>{/each}
    <p class="lbl">gives</p>
    <LeanText pp={a.result} {onref} />{#if ab.result} <span class="faint small about">about {ab.result.join(", ")}</span>{/if}
  {/if}
</div>

<style>
  .app { border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; margin: 8px 0; }
  .ahead { margin: 0 0 6px; display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
  .r { border: 0; padding: 0; background: none; font: inherit; font-family: var(--mono); font-size: 13px; color: var(--accent); cursor: pointer; text-align: left; overflow-wrap: anywhere; }
  .params { list-style: none; margin: 0; padding: 0; font-size: 13px; }
  .params li { border-top: 1px solid var(--border); padding: 4px 0; overflow-wrap: anywhere; }
  .src { padding-left: 14px; }
  .d { font-size: 12px; }
  .d-assumed { color: var(--st-open); }
  .d-proved { color: var(--st-proved); }
  .linked { color: var(--accent); }
  .warn { color: var(--st-open); }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .small { font-size: 12px; }
</style>
