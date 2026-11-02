<script>
  // Where a declaration is used. The build's reverse references list its users and how each one
  // refers to it (statement, proof, definition body). Served by `machinechecked view`, the reader
  // can ask Lean for each application: the argument supplied for each binder, where each
  // premise's proof comes from, the conclusion obtained and the objects each premise and the
  // conclusion are about; and, for one application, every local of its context. Those documents
  // are the ones `machinechecked compare --query uses` prints (with `--in`, for one).
  // Inside a comparison its data come as the stage allows them (`comparison.usersSide`): an
  // independent stage's do not name the claims a declaration is linked to. An application opens
  // as an inspection beside the comparison row, after the trail it was found in.
  import { getContext } from "svelte";
  import { askUses, canEdit, loadUsers, siteIndex } from "../lib/data.js";
  import { applications, openInspection, tokenOf } from "../lib/inspect.svelte.js";
  import Application from "./Application.svelte";
  import { userName } from "../lib/names.js";

  let { name, module = null, onref = null, index = siteIndex } = $props();
  const stage = getContext("comparison")?.users || ((e) => e);
  let open = $state(false);
  let entry = $state(undefined);
  let doc = $state(null);
  let asking = $state(false);
  let askError = $state(null);
  const local = $derived(canEdit(index));
  $effect(() => {
    if (open && entry === undefined) loadUsers(index, name, module).then((e) => (entry = stage(e))).catch(() => (entry = null));
  });
  async function ask() {
    asking = true;
    askError = null;
    try {
      doc = stage(await askUses(name, module));
      for (const a of doc.applications || []) applications.set(name + "|" + a.id, a);
    } catch (e) { askError = e.message; }
    asking = false;
  }
  const refsText = (u) => (u.refs || []).join(", ");
</script>

{#snippet user(u)}
  {#if onref}<button class="r" onclick={() => onref(u.name)}>{userName(u.name)}</button>{:else}<code>{userName(u.name)}</code>{/if}
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
        <Application {a} callee={name} {module} {onref} {index}
          inspect={() => openInspection(tokenOf({ kind: "application", callee: name, id: a.id }), "top", { nested: true })} />
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
  .linked { color: var(--accent); }
  .warn { color: var(--st-open); }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .small { font-size: 12px; }
</style>
