<script>
  import { untrack } from "svelte";
  import { listWorkspaces, exportWorkspace, importWorkspace } from "../lib/workspace.js";
  import { ensureWorkspace, workspaceFile, readWorkspaceFile, importPlan, applyImport, importedWords, saveFile,
           sameReviewer, chosenWorkspace, chooseWorkspace } from "../lib/workfile.js";

  // The review work as a workspace file (`prooflens/workspace@1`): exported to hand on, and
  // imported to continue. On a static copy of the site the page writes and reads the file itself
  // (`workfile.js`) and the work stays in this browser. Under `machinechecked view` the engine
  // exports and imports it (`machinechecked workspace export` and `import`), and the page offers
  // the reviewer's workspaces to work in, an imported one among them.
  //
  // `work` is the page's work (a static copy's, saved by `persist`); `reviewer` the reviewer's id;
  // `current` the workspace the engine says the page works in; `onswitch(id)` makes the page work
  // in another (none: the reviewer's first). `compact` offers the import only, before a reviewer
  // is named.
  let { index, units, served, work = $bindable(), persist, reviewer = null, current = null,
        onswitch = () => {}, compact = false } = $props();

  const project = untrack(() => index.project?.name) || "project";
  let input = $state(null);
  let note = $state(null);
  let asking = $state(null);
  let mine = $state([]);

  // The reviewer's workspaces in the working directory (`machinechecked workspace list`).
  async function listMine() {
    try {
      mine = (await listWorkspaces()).workspaces.filter((w) => sameReviewer(w.reviewer, reviewer));
    } catch { mine = []; return; }
    // A workspace chosen in this browser that the working directory no longer has: the first.
    const chosen = chosenWorkspace(project);
    if (chosen && !mine.some((w) => w.id === chosen)) choose(null);
  }
  // Read again whenever the page works in another workspace, or saves its first.
  $effect(() => { current?.id; if (served && reviewer) untrack(listMine); });
  const options = $derived(current && !mine.some((w) => w.id === current.id) ? [...mine, current] : mine);
  function choose(id) {
    if (id && id === current?.id && id === chosenWorkspace(project)) return;
    chooseWorkspace(project, id);
    onswitch(id);
  }

  const refuse = (why) => { note = { ok: false, text: `The file was not imported: ${why}.` }; };

  async function doExport() {
    note = null;
    try {
      let ws;
      if (served) ws = await exportWorkspace(current.id);
      else {
        if (ensureWorkspace(work, index)) persist();
        ws = workspaceFile($state.snapshot(work), units);
      }
      saveFile(`machinechecked-workspace-${ws.id}.json`, ws);
    } catch (e) {
      note = { ok: false, text: `The workspace was not exported: ${e.message}.` };
    }
  }

  async function pick(e) {
    const file = e.currentTarget.files?.[0];
    e.currentTarget.value = "";
    if (!file) return;
    note = null; asking = null;
    const text = await file.text();
    if (served) return importServed(text);
    let ws;
    try { ws = readWorkspaceFile(text); } catch (err) { return refuse(err.message); }
    const plan = importPlan($state.snapshot(work), ws);
    if (plan.error) return refuse(plan.error);
    if (plan.typed.length) { asking = { id: ws.id, typed: plan.typed, go: (replace) => apply(ws, file.name, replace) }; return; }
    apply(ws, file.name, false);
  }
  function apply(ws, from, replace) {
    asking = null;
    const merge = applyImport(work, ws, from, replace);
    persist();
    note = { ok: true, text: `Imported workspace ${ws.id}: ${importedWords(ws)}.`, items: notApplied(merge?.not_applied) };
  }
  // The drafts an import did not apply, and why (`merge_drafts`).
  const notApplied = (list) => (list || []).map((n) => `The file's draft of ${n.unit} was not applied: ${n.why}.`);

  // The engine checks and keeps the file; a workspace of this reviewer's is then the one the page
  // works in. What the build cannot resolve, and records and drafts kept here in another version,
  // are listed. Drafts that differ only in what was typed are asked about first, as on a static
  // copy: the engine says what the import would do before it is made.
  async function importServed(text) {
    let data;
    try { data = JSON.parse(text); } catch { return refuse("not a JSON file"); }
    let plan;
    try { plan = await importWorkspace(data, reviewer, { dry_run: true }); } catch (e) { return refuse(e.message); }
    const typed = plan.drafts.not_applied.filter((n) => n.kind === "typed");
    if (typed.length) { asking = { id: plan.workspace, typed, go: (replace) => importNow(data, replace) }; return; }
    await importNow(data, false);
  }
  async function importNow(data, replace) {
    asking = null;
    let res;
    try { res = await importWorkspace(data, reviewer, { replace_drafts: replace }); } catch (e) { return refuse(e.message); }
    const own = sameReviewer(data?.reviewer?.id, reviewer);
    note = { ok: true, text: `Imported workspace ${res.workspace}` + (own ? "; the review page works in it."
      : ` of ${data?.reviewer?.id || "no named reviewer"}; the review page works in your own workspaces.`),
      items: [...(res.problems || []).map((p) => `${p.record}: ${p.problem}`),
              ...(res.conflicts || []).filter((c) => !String(c.id).startsWith("draft "))
                .map((c) => `${c.id}: kept as this working directory had it; the file's version is kept under conflicts`),
              ...notApplied(res.drafts?.not_applied)] };
    await listMine();
    if (own) choose(res.workspace);
  }
</script>

{#if served && options.length > 1}
  <label class="ws">Workspace
    <select aria-label="Workspace" value={current?.id} onchange={(e) => choose(e.currentTarget.value)}>
      {#each options as w (w.id)}<option value={w.id}>{w.id} ({w.mode})</option>{/each}
    </select>
  </label>
{/if}
{#if compact}<p class="small">Work saved in a workspace file continues here once imported.</p>{/if}
{#if !compact}<button class="btn ghost" disabled={served && !current} onclick={doExport}>Export workspace</button>{/if}
<button class="btn ghost" onclick={() => input.click()}>Import workspace</button>
<input type="file" accept=".json,application/json" hidden bind:this={input} onchange={pick} />
{#if asking}
  <section class="card wsnote" aria-labelledby="import-title">
    <p id="import-title"><strong>Import workspace {asking.id}</strong></p>
    <p class="small">The file's draft of {asking.typed.map((n) => n.unit).join(", ")} differs from the one here only in
      what was typed. Take the file's, or keep the one here; the other is kept in the workspace's conflicts. A step
      already taken stays as it is either way.</p>
    <div class="row">
      <button class="btn" onclick={() => asking.go(true)}>Take the file's drafts</button>
      <button class="btn ghost" onclick={() => asking.go(false)}>Keep the drafts here</button>
      <button class="btn ghost" onclick={() => (asking = null)}>Cancel</button>
    </div>
  </section>
{/if}
{#if note}
  <div class="wsnote {note.ok ? 'done' : 'warn'}" role={note.ok ? "status" : "alert"}>
    {note.text}
    {#if note.items?.length}<ul>{#each note.items as it}<li>{it}</li>{/each}</ul>{/if}
  </div>
{/if}

<style>
  .ws { display: flex; gap: 6px; align-items: center; min-width: 0; max-width: 100%; }
  .ws select { min-width: 0; max-width: 100%; font: inherit; font-size: 14px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 4px 6px; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent); border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 14px; }
  .btn.ghost { background: none; color: var(--accent); }
  .btn:disabled { opacity: 0.45; cursor: default; }
  .wsnote { flex-basis: 100%; font-size: 13px; margin: 4px 0; overflow-wrap: anywhere; }
  .wsnote ul { margin: 4px 0 0; padding-left: 18px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 16px; }
  .card p { margin: 4px 0; }
  .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .warn { background: var(--surface-2); border-left: 3px solid var(--st-open); padding: 6px 10px; }
  .done { background: var(--surface-2); border-left: 3px solid var(--accent); padding: 6px 10px; }
  .small { font-size: 13px; }
</style>
