<script>
  import { canEdit } from "../lib/data.js";
  import { listWorkspaces, mainResults, saveMainResults, rememberedWorkspace } from "../lib/workspace.js";
  import { entriesOf, suggestedOf, savedText, withAdded, without, sameSelection } from "../lib/mainresults.js";

  // The main results each declaration's use is traced from (`compare --query impact`). Under
  // `machinechecked view`: those a workspace of the working directory saves, or the suggestion
  // when it saves none, as the engine gives them, edited with the engine's `main-results`
  // operation; a refusal is shown in the engine's words. In a published audit: those each of its
  // workspaces saves (`index.main_results`), read-only. A static copy only shows them.
  let { index } = $props();

  const published = $derived(index.main_results || []);
  const whoOf = (r) => (r?.kind === "model" ? "the AI model " + (r.model || r.id) : r?.name || r?.id || "an unnamed auditor");
  let local = $state(false);
  let spaces = $state([]);
  let wsId = $state(null);
  let doc = $state(null);
  let error = $state(null);
  let busy = $state(false);
  let name = $state("");
  const saved = $derived(doc?.basis === "saved" ? doc : null);

  async function load(keepError = false) {
    if (!keepError) error = null;
    try {
      spaces = (await listWorkspaces()).workspaces;
      local = true;
      if (!spaces.some((w) => w.id === wsId)) wsId = spaces.find((w) => w.id === rememberedWorkspace())?.id || spaces[0]?.id || null;
      doc = wsId ? await mainResults(wsId) : null;
    } catch (e) {
      if (e.status === 404 && !local) return;   // a server without workspaces
      error = String(e.message || e);
    }
  }
  $effect(() => { if (canEdit(index)) load(); });

  // An edit replaces the whole selection, so it is saved only over the selection shown.
  async function save(main) {
    busy = true; error = null;
    try {
      const now = await mainResults(wsId);
      if (!sameSelection(now?.basis === "saved" ? now : null, saved)) {
        doc = now;
        error = "The main results of this workspace changed elsewhere (in a terminal, or another window) since they were shown here. Nothing was saved; they are shown now.";
        return;
      }
      await saveMainResults(wsId, main);
      name = "";
      await load();
    } catch (e) {
      error = String(e.message || e);
      await load(true);
    } finally { busy = false; }
  }
</script>

{#snippet entry(e)}<strong>{e.label}</strong>{#if e.detail}<span class="faint">{" · " + e.detail}</span>{/if}{#if e.problem}<span class="warn" data-problem>{" · " + e.problem}</span>{/if}{/snippet}

{#if local || published.length}
  <section class="mains" aria-labelledby="main-results">
    <h2 id="main-results">Main results</h2>
    <p class="small faint">The results whose Lean each declaration's use is traced from (<code>compare --query impact</code>). A claim stands for its linked Lean. Choosing them changes no status.</p>
    {#if local}
      {#if !spaces.length}
        <p class="small" data-no-workspace>No workspace here yet. Start an investigation on a claim's page, or run <code>machinechecked workspace open</code>, to save main results.</p>
      {:else}
        <div class="local" data-workspace={wsId}>
          {#if spaces.length > 1}
            <p class="small"><label>Workspace <select aria-label="Workspace" value={wsId} disabled={busy} onchange={(e) => { wsId = e.currentTarget.value; load(); }}>
              {#each spaces as w (w.id)}<option value={w.id}>{w.id} · {w.reviewer} · {w.mode}</option>{/each}</select></label></p>
          {:else}
            <p class="small faint">Workspace {wsId} · {spaces[0].reviewer} · {spaces[0].mode}</p>
          {/if}
          {#if saved}
            <p class="small" data-saved>{savedText(saved)}{#if saved.note}<span class="warn">{" " + saved.note[0].toUpperCase() + saved.note.slice(1) + "."}</span>{/if}</p>
            <ul class="entries">
              {#each entriesOf(saved, index.claims) as e, i (e.key)}
                <li data-main={e.key}>{@render entry(e)} <button class="link" disabled={busy} aria-label={"Remove " + e.label} onclick={() => save(without(saved, i))}>Remove</button></li>
              {/each}
            </ul>
            <p class="small"><button class="act" disabled={busy} onclick={() => save([])}>Clear</button></p>
          {:else if doc}
            <p class="small" data-suggested>This workspace saves none; impact traces from the suggestion, {doc.rule}.</p>
            <ul class="entries">{#each suggestedOf(doc, index.claims) as e (e.key)}<li data-main={e.key}>{@render entry(e)}</li>{/each}</ul>
            {#if doc.main_results?.length}<p class="small"><button class="act" disabled={busy} onclick={() => save(doc.main_results.map((m) => m.name))}>Save the suggestion</button></p>{/if}
          {/if}
          <p class="small add"><input bind:value={name} aria-label="Main result to add" placeholder="a claim (Theorem 2), or a declaration (NAME or MODULE:NAME)"
              onkeydown={(e) => { if (e.key === "Enter" && name.trim() && !busy) save(withAdded(saved, name.trim())); }} />
            <button class="act" disabled={busy || !name.trim()} onclick={() => save(withAdded(saved, name.trim()))}>Add</button></p>
        </div>
      {/if}
      {#if error}<p class="bad small" role="alert">{error}</p>{/if}
    {/if}
    {#each published as s (s.workspace)}
      <div class="published" data-published={s.workspace}>
        <p class="small"><strong>Saved in workspace {s.workspace}</strong> by {whoOf(s.reviewer)}{s.mode ? ` (${s.mode})` : ""}. {savedText(s)}</p>
        <ul class="entries">{#each entriesOf(s, index.claims) as e (e.key)}<li data-main={e.key}>{@render entry(e)}</li>{/each}</ul>
        {#if s.left_out?.count}<p class="small faint" data-left-out>{s.left_out.count} more not named: {s.left_out.why}.</p>{/if}
      </div>
    {/each}
  </section>
{/if}

<style>
  .mains { margin: 20px 0; padding: 12px 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); }
  .mains h2 { font-family: var(--serif); font-size: 18px; margin: 0 0 6px; }
  .mains p { margin: 4px 0; }
  .entries { margin: 6px 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; font-size: 14px; }
  .entries li { overflow-wrap: anywhere; }
  .published { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
  .add { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
  input, select { font: inherit; font-size: 14px; padding: 4px 8px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); min-width: 0; max-width: 100%; }
  input { width: min(420px, 100%); }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: var(--radius); border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .act:disabled { opacity: 0.5; cursor: default; }
  .link { font: inherit; font-size: 13px; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; }
  .warn { color: var(--tier-warning); }
  .bad { color: var(--st-refuted); }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
</style>
