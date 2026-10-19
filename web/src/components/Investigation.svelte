<script>
  import { listWorkspaces, openWorkspace, showWorkspace, updateWorkspace, newId,
    rememberedWorkspace, rememberWorkspace, humanId } from "../lib/workspace.js";
  import { href } from "../lib/route.svelte.js";
  import { coverageView } from "../lib/coverage.js";

  // The auditor's saved investigation of this claim, under `machinechecked view`: its open
  // questions, findings and evidence, saved by the engine in the project's working directory, and
  // continued with `machinechecked workspace` in a terminal. A claim page shows the Lean, so a
  // workspace opened here is an informed investigation; an independent review uses the review page.
  let { index, claim } = $props();

  // The readings a finding can record: the links file's coverage and, for full coverage, how it
  // is supported (a checked bridge is recorded with `machinechecked workspace update`).
  const CHOICES = {
    direct: { label: "Every clause, in one Lean statement", coverage: "full", basis: "direct" },
    composition: { label: "Every clause, by my composition", coverage: "full", basis: "reviewed_composition" },
    full: { label: "Every clause", coverage: "full" },
    partial: { label: "Part of the claim", coverage: "partial" },
    changed: { label: "Stated differently", coverage: "changed" },
    related: { label: "A related result", coverage: "related" },
    unresolved: { label: "Unresolved", coverage: "unresolved" },
  };

  let available = $state(true);
  let mine = $state([]);
  let wsId = $state(rememberedWorkspace());
  let view = $state(null);
  let error = $state(null);
  let busy = $state(false);
  let name = $state("");
  let question = $state("");
  let choice = $state("direct");
  let note = $state("");
  let openQ = $state("");
  let decide = $state("");
  let argument = $state("");
  const picked = $derived(CHOICES[choice]);
  let cite = $state(true);

  const here = $derived(view?.claims?.[claim.id] || { evidence: [], findings: [], questions: [] });

  async function refresh(keepError = false) {
    if (!keepError) error = null;
    try {
      mine = (await listWorkspaces()).workspaces.filter((w) => w.mode === "informed");
      if (wsId && !mine.some((w) => w.id === wsId)) { wsId = null; rememberWorkspace(null); }
      view = wsId ? await showWorkspace(wsId) : null;
    } catch (e) {
      if (e.status === 404) available = false;   // a server without workspaces
      else error = String(e.message || e);
    }
  }

  $effect(() => { claim.id; refresh(); });
  // A fact cited from a proof's facts is saved by that panel; show it here too.
  $effect(() => {
    const again = () => refresh();
    globalThis.addEventListener?.("machinechecked-workspace-changed", again);
    return () => globalThis.removeEventListener?.("machinechecked-workspace-changed", again);
  });

  async function start(id) {
    busy = true; error = null;
    try {
      const v = await openWorkspace(id ? undefined : humanId(name), "informed", id);
      wsId = v.id; rememberWorkspace(v.id);
      await refresh();
    } catch (e) { error = String(e.message || e); }
    busy = false;
  }

  async function run(ops) {
    busy = true; error = null;
    try {
      await updateWorkspace(wsId, ops);
      await refresh();
      return true;
    } catch (e) {
      error = e.conflicts
        ? "This record was changed elsewhere (in a terminal, or another window) since it was shown here. Both versions are kept in the workspace; the current one is shown now."
        : String(e.message || e);
      await refresh(true);
      return false;
    } finally { busy = false; }
  }

  async function addFinding() {
    const ops = [], ev = [];
    if (cite) {
      for (const l of claim.links || []) {
        const known = here.evidence.find((e) => e.ref?.decl === l.name);
        if (known) { ev.push(known.id); continue; }
        const id = newId("e");
        ops.push({ op: "put", record: { id, kind: "evidence", claim: claim.id, ref: { decl: l.name }, role: "supports" } });
        ev.push(id);
      }
    }
    const { coverage, basis } = picked;
    ops.push({ op: "put", record: { id: newId("f"), kind: "finding", claim: claim.id, coverage,
      note, evidence: ev, ...(basis ? { basis } : {}),
      ...(basis === "reviewed_composition" && argument.trim() ? { argument } : {}),
      ...(coverage === "unresolved" ? { question: openQ, ...(decide.trim() ? { would_decide: decide } : {}) } : {}) } });
    if (await run(ops)) { note = ""; openQ = ""; decide = ""; argument = ""; }
  }

  async function addQuestion() {
    const id = newId("q");
    if (await run([{ op: "put", record: { id, kind: "question", claim: claim.id, text: question } },
      { op: "resume", state: { claim: claim.id, question: id } }])) question = "";
  }

  // A put replaces the record's content, so the question's other fields go with it.
  const close = (q, state) => run([{ op: "put", base_rev: q.rev, record: {
    id: q.id, kind: "question", claim: q.claim, text: q.text, state,
    ...(q.clause ? { clause: q.clause } : {}), ...(q.note ? { note: q.note } : {}),
    ...(q.answer ? { answer: q.answer } : {}), ...(q.evidence ? { evidence: q.evidence } : {}) } }]);
  const submit = (f) => run([{ op: "submit", id: f.id, base_rev: f.rev }]);
  const resumeHere = () => run([{ op: "resume", state: { claim: claim.id } }]);

  function refText(r) {
    if (r.fact) return `${r.fact.name || r.fact.head || "a fact"} : ${r.fact.type}, inside the proof of ${r.fact.decl}`;
    return r.decl || (r.source ? r.source.file + (r.source.line ? ":" + r.source.line : "") : "a passage of the paper");
  }
</script>

{#if available}
  <section class="investigation" aria-label="Investigation">
    <h2>Investigation</h2>
    {#if !view}
      <p class="small">Save evidence, findings and open questions for this claim, and continue them here or with <code>machinechecked workspace</code>. The Lean is on this page, so this is an informed investigation; an independent review starts from the review page.</p>
      {#each mine as w (w.id)}
        <p class="small"><button class="act" disabled={busy} onclick={() => start(w.id)}>Continue {w.id}</button> <span class="faint">{w.reviewer} · {w.findings} finding(s), {w.open_questions} open question(s)</span></p>
      {/each}
      <p class="small"><input class="who" bind:value={name} placeholder="your name" aria-label="Your name" />
        <button class="act" disabled={busy || !humanId(name)} onclick={() => start(null)}>Start an investigation</button></p>
    {:else}
      <p class="faint small">{view.reviewer} · informed investigation · workspace {view.id}
        {#if view.resume?.claim && view.resume.claim !== claim.id} · <a href={href(index.release, "claim", view.resume.claim)}>Resume at {view.resume.claim}</a>{/if}
        {#if view.resume?.claim !== claim.id} · <button class="link" disabled={busy} onclick={resumeHere}>Resume here next time</button>{/if}</p>

      {#each here.questions as q (q.id)}
        <div class="item" data-kind="question" data-state={q.state}>
          <p class="small"><strong>{q.state === "open" ? "Open question" : q.state === "answered" ? "Answered" : "Withdrawn"}:</strong> <span class="text">{q.text}</span></p>
          {#if q.state === "open"}<p class="small"><button class="link" disabled={busy} onclick={() => close(q, "answered")}>Mark answered</button> · <button class="link" disabled={busy} onclick={() => close(q, "withdrawn")}>Withdraw</button></p>{/if}
        </div>
      {/each}
      {#each here.findings as f (f.id)}
        {@const cv = coverageView(f)}
        <div class="item" data-kind="finding" data-state={f.state} class:old={!f.in_force}>
          <p class="small"><strong>{cv?.headline || "No coverage given"}</strong>
            <span class="faint">· {f.in_force ? (f.state === "submitted" ? "submitted" : "draft") : "superseded"} · {f.created_by}</span>
            {#if f.currency?.state === "stale"}<span class="stale"> · evidence changed since</span>{/if}</p>
          {#each cv?.lines || [] as line}<p class="small" data-line={line.label}><span class="faint">{line.label}:</span> {line.names?.join(", ") || ""}{line.names?.length && line.text ? ". " : ""}<span class="text">{line.text || ""}</span>{#if line.note} <span class="faint">{line.note}</span>{/if}</p>{/each}
          {#if f.note}<p class="small text">{f.note}</p>{/if}
          {#if f.supersedes}<p class="faint small">Supersedes {f.supersedes}: {f.reason}</p>{/if}
          {#if f.state === "draft"}<button class="act" disabled={busy} onclick={() => submit(f)}>Submit</button>{/if}
        </div>
      {/each}
      {#if here.evidence.length}
        <p class="small faint">Evidence: {#each here.evidence as e, i (e.id)}{i ? ", " : ""}<code>{refText(e.ref)}</code> ({e.role}{e.ref?.fact ? ", " + e.ref.fact.basis : ""}{e.currency?.state === "stale" ? ", changed since" : ""}){/each}</p>
      {/if}

      <details class="add">
        <summary>Record a finding</summary>
        <p class="small"><label>Coverage <select bind:value={choice}>{#each Object.entries(CHOICES) as [k, c]}<option value={k}>{c.label}</option>{/each}</select></label>
          {#if claim.links?.length}<label><input type="checkbox" bind:checked={cite} /> cite the linked declarations</label>{/if}</p>
        {#if picked.coverage === "unresolved"}<textarea bind:value={openQ} rows="2" placeholder="The open question" aria-label="Open question"></textarea>
          <textarea bind:value={decide} rows="2" placeholder="What would decide it" aria-label="What would decide it"></textarea>{/if}
        {#if picked.basis === "reviewed_composition"}<textarea bind:value={argument} rows="3" placeholder="How the linked results combine to give each clause" aria-label="Argument"></textarea>
          <p class="faint small">Lean has not checked this combination. Next step: state the combination as one Lean result.</p>{/if}
        <textarea bind:value={note} rows="3" placeholder="What establishes each clause, or what differs" aria-label="Note"></textarea>
        <button class="act" disabled={busy || (picked.coverage === "unresolved" && !openQ.trim())} onclick={addFinding}>Save draft</button>
      </details>
      <details class="add">
        <summary>Ask a question</summary>
        <textarea bind:value={question} rows="2" placeholder="The next question about this claim" aria-label="Question"></textarea>
        <button class="act" disabled={busy || !question.trim()} onclick={addQuestion}>Save question</button>
      </details>
    {/if}
    {#if error}<p class="bad small" role="alert">{error}</p>{/if}
  </section>
{/if}

<style>
  .investigation { margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--border); }
  .investigation h2 { font-size: 15px; margin: 0 0 6px; }
  .item { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 8px 0; }
  .item[data-kind="finding"][data-state="submitted"] { border-left-color: var(--accent); }
  .item.old { opacity: 0.7; }
  .item p { margin: 2px 0; }
  .text { white-space: pre-wrap; }
  .stale { color: var(--tier-warning); }
  .add { margin: 8px 0; }
  .add summary { cursor: pointer; font-size: 13px; }
  textarea { display: block; width: 100%; box-sizing: border-box; font: inherit; font-size: 13px; margin: 6px 0; padding: 4px 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); }
  select { font: inherit; font-size: 13px; }
  label { margin-right: 12px; }
  .who { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 12em; }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .act:hover { border-color: var(--accent); color: var(--accent); }
  .act:disabled { opacity: 0.5; cursor: default; }
  .link { font: inherit; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; }
  .bad { color: var(--st-refuted); }
</style>
