<script>
  // Where a declaration is used. The build's reverse references list its users and how each one
  // refers to it (statement, proof, definition body). Served by `machinechecked view`, the reader
  // can ask Lean for each application: the argument supplied for each binder, where each
  // premise's proof comes from, the conclusion obtained and the objects each premise and the
  // conclusion are about; and, for one application, every local of its context. Those documents
  // are the ones `machinechecked compare --query uses` prints (with `--in`, for one).
  import { askUses, canEdit, loadUsers, siteIndex } from "../lib/data.js";
  import LeanText from "./LeanText.svelte";

  let { name, module = null, onref = null, index = siteIndex } = $props();
  let open = $state(false);
  let entry = $state(undefined);
  let doc = $state(null);
  let asking = $state(false);
  let askError = $state(null);
  const local = $derived(canEdit(index));
  $effect(() => {
    if (open && entry === undefined) loadUsers(index, name, module).then((e) => (entry = e)).catch(() => (entry = null));
  });
  async function ask() {
    asking = true;
    askError = null;
    try { doc = await askUses(name, module); } catch (e) { askError = e.message; }
    asking = false;
  }
  const DISCHARGE = {
    assumed: "assumed by the caller",
    proved: "proved in the caller",
    local: "from a hypothesis introduced in the proof",
    helper: "a parameter of a constant Lean generated",
    unknown: "not determined from the term",
  };
  const refsText = (u) => (u.refs || []).join(", ");
  // The objects each premise (by its index) and the conclusion (`result`) are about.
  function about(a) {
    const out = {};
    for (const o of a.objects || []) for (const p of o.properties) (out[p.basis === "premise" ? p.index : "result"] ||= []).push(o.binder);
    return out;
  }
  // One application asked for again in its caller alone, which lists its whole context.
  let reading = $state({});
  async function inContext(a) {
    reading = { ...reading, [a.id]: "asking" };
    try {
      const got = (await askUses(name, module, a.id)).applications?.[0];
      if (!got) throw new Error(`Lean no longer describes ${a.id}.`);
      doc = { ...doc, applications: doc.applications.map((x) => (x.id === a.id ? got : x)) };
      reading = { ...reading, [a.id]: null };
    } catch (e) { reading = { ...reading, [a.id]: e.message }; }
  }
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
</script>

{#snippet user(u)}
  {#if onref}<button class="r" onclick={() => onref(u.name)}>{u.name}</button>{:else}<code>{u.name}</code>{/if}
  <span class="faint small">{refsText(u)}{u.module ? " · " + u.module : ""}{u.via?.length ? " · through " + u.via.join(", ") : ""}</span>
  {#if u.claims?.length}<span class="small linked">linked to {u.claims.join(", ")}</span>{/if}
{/snippet}

<details class="uses" bind:open>
  <summary>Used by</summary>
  {#if open}
    {#if doc?.ok}
      <p class="small">{doc.answer === "used" ? `${doc.users.length} declaration(s) use it` : doc.answer}.
        {#if !doc.complete}<span class="warn">Searched {doc.scope.modules} built module(s); {doc.scope.unbuilt.length} not built, {Object.keys(doc.scope.failed).length} not loaded.</span>{/if}</p>
      <ul class="list">{#each doc.users as u}<li>{@render user(u)}</li>{/each}</ul>
      {#if doc.further?.length}
        <p class="lbl">further, through these ({doc.further.length})</p>
        <ul class="list">{#each doc.further.slice(0, 12) as f}<li>{@render user(f)} <span class="faint small">through {f.through}</span></li>{/each}</ul>
      {/if}
      {#if doc.imports_without_use?.length}<p class="small faint">Imported without use by {doc.imports_without_use.join(", ")}.</p>{/if}
      {#each doc.applications as a (a.id)}
        {@const ab = about(a)}
        <div class="app">
          <p class="ahead">In {#if onref}<button class="r" onclick={() => onref(a.caller)}>{a.caller}</button>{:else}<code>{a.caller}</code>{/if}
            {#if a.via}<span class="faint small">(in {a.via})</span>{/if}
            {#if a.caller_claims?.length}<span class="small linked">linked to {a.caller_claims.join(", ")}</span>{/if}
            <span class="faint small" title={a.location.note}>at {a.location.path}{a.location.range ? `, lines ${a.location.range.line}–${a.location.range.end_line}` : ""}</span></p>
          {#if !a.available}
            <p class="small warn">Not described: {(a.errors || []).join("; ")}</p>
          {:else}
            {#if a.context}
              <p class="lbl">context</p>
              <ul class="params ctx">{#each a.context as c}<li><code>{c.name}</code> <span class="ty"><LeanText pp={c.type} /></span> <span class="faint small">{LOCAL[c.kind] || "in the context"}</span></li>{/each}</ul>
            {:else if local}
              <button class="btn ghost" onclick={() => inContext(a)} disabled={reading[a.id] === "asking"}>{reading[a.id] === "asking" ? "Asking Lean…" : "Show its context"}</button>
              {#if reading[a.id] && reading[a.id] !== "asking"}<p class="small warn">{reading[a.id]}</p>{/if}
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
            {#each a.unsupplied as o}<p class="small faint">Left open: <code>{o.binder}</code> ({o.role}).</p>{/each}
            <p class="lbl">gives</p>
            <LeanText pp={a.result} />{#if ab.result} <span class="faint small about">about {ab.result.join(", ")}</span>{/if}
          {/if}
        </div>
      {/each}
      {#if doc.applications_note}<p class="small faint">{doc.applications_note}</p>{/if}
      <p class="small faint">{doc.note}</p>
    {:else}
      {#if entry === undefined}
        <p class="faint small">Loading…</p>
      {:else if entry === null}
        <p class="faint small">This build holds no reverse references.</p>
      {:else if entry.ambiguous}
        <p class="faint small">Several modules declare this name: {entry.ambiguous.join(", ")}.</p>
      {:else if !entry.users.length}
        <p class="small">No declaration of the project's built modules refers to it.</p>
      {:else}
        <ul class="list">{#each entry.users as u}<li>{@render user(u)}</li>{/each}</ul>
      {/if}
      {#if local}
        <button class="btn ghost" onclick={ask} disabled={asking}>{asking ? "Asking Lean…" : "Show each application"}</button>
        {#if askError}<p class="small warn">{askError}</p>{/if}
      {:else}
        <p class="small faint">Each application's arguments and the source of each premise: <code>machinechecked compare --query uses {name}</code></p>
      {/if}
    {/if}
  {/if}
</details>

<style>
  .uses { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 6px; }
  .uses > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .list { margin: 4px 0; padding-left: 18px; }
  .list li { margin: 2px 0; overflow-wrap: anywhere; }
  .r { border: 0; padding: 0; background: none; font: inherit; font-family: var(--mono); font-size: 13px; color: var(--accent); cursor: pointer; text-align: left; overflow-wrap: anywhere; }
  .app { border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px; margin: 8px 0; }
  .ahead { margin: 0 0 6px; display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }
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
