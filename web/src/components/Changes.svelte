<script>
  // What this release was built from, and what changed since the release before it: each
  // claim's passage, its Lean statements and definitions, both builds' statuses, and every
  // review the later build no longer counts, with the change it depends on and the question a
  // new reading answers (`changes.py`). Every state shown is the one the engine recorded.
  import { auditInfo, AUDIT, loadChanges } from "../lib/data.js";
  import { href } from "../lib/route.svelte.js";
  import StatusChip from "./StatusChip.svelte";
  let { index } = $props();

  let changes = $state(null);
  let error = $state(null);
  let everything = $state(false);
  $effect(() => {
    loadChanges(index).then((d) => (changes = d)).catch((e) => (error = String(e)));
  });

  const PAPER = {
    changed: "Passage changed", "context-changed": "Context changed", removed: "Removed",
    ambiguous: "Ambiguous match", new: "New", unknown: "Not comparable", moved: "Moved",
    unchanged: "Unchanged",
  };
  const LEAN = {
    statement: "statement changed", proof: "only the proof changed", removed: "not in the later build",
    new: "new in the later build", renamed: "another declaration in the later build",
  };
  const OUTCOME = {
    reopened: "Due for review", dropped: "No longer applies", replaced: "New reading",
    "newly-current": "Current in the later build only", kept: "Still current", open: "Not current in either build",
  };

  function quiet(c) {
    return c.paper_change.class === "unchanged" && !c.lean_changed && !c.due &&
      c.evidence.every((e) => e.outcome === "kept" || e.outcome === "open");
  }
  const shown = $derived(changes ? changes.claims.filter((c) => everything || !quiet(c)) : []);
  const known = $derived(new Set(index.claims.map((c) => c.id)));

  function leanRows(c) {
    const out = [];
    for (const r of c.lean) {
      for (const e of [r.proposition, ...r.definitions, ...r.proofs]) {
        if (e && e.change !== "unchanged" && e.change !== "absent") out.push({ clause: r.clause, ...e });
      }
    }
    return out;
  }
  function where(ctx) {
    return ctx.macro || (ctx.to || ctx.from || {}).location || "";
  }
  function dependency(d) {
    if (d.dependency === "lean") return d.now ? `${d.name} changed` : `${d.name}: ${d.detail || "not in the later build"}`;
    if (d.dependency === "paper") {
      const ctx = (d.context || []).map(where).filter(Boolean).join(", ");
      return d.change === "context-changed"
        ? `the context of the passage of ${d.claim} changed${ctx ? ` (${ctx})` : ""}`
        : `the passage of ${d.claim} changed`;
    }
    return d.detail || "";
  }
  // The texts that show a passage change: for a change of context, the further passages that
  // changed; otherwise the claim's own passage (`changes.shown_texts`).
  function texts(p) {
    if (p.class === "unchanged" || p.class === "moved") return [];
    const places = new Set((p.context || []).flatMap((c) => [c.from?.location, c.to?.location]).filter(Boolean));
    const out = [];
    for (const [side, word] of [["from", "Earlier"], ["to", "Later"]]) {
      const here = p[side];
      if (!here || typeof here !== "object") continue;
      if (p.class === "context-changed") {
        for (const q of (here.part_text || []).slice(1)) {
          if (places.has(q.location) && q.text) out.push({ label: `${word} context (${q.location})`, text: q.text });
        }
      } else if (here.text?.text) out.push({ label: `${word} text`, text: here.text.text });
    }
    return out;
  }
  function revision(v, pid) {
    const r = v.papers?.[pid]?.revision;
    return r ? r.slice(0, 12) : "not recorded";
  }
</script>

<main class="ch">
  <h1>Audit details</h1>
  <dl>
    {#if auditInfo}<dt>Author</dt><dd>{auditInfo.author}</dd><dt>Publication</dt><dd><a href={AUDIT.href}>{AUDIT.href}</a></dd>{/if}
    <dt>Release</dt><dd><code>{index.release}</code></dd>
    <dt>Evidence</dt><dd><code>{index.evidence}</code></dd>
    <dt>Built</dt><dd>{index.created}</dd>
    {#if index.lean}<dt>Lean</dt><dd>{index.lean.lean} <span class="faint">({index.lean.githash?.slice(0, 12)})</span></dd>{/if}
    {#if index.project}
      <dt>Project</dt>
      <dd>{index.project.name} {#if index.project.commit}<code>{index.project.commit.slice(0, 12)}</code>{/if}{index.project.dirty ? " with uncommitted changes" : ""}</dd>
      {#if index.project.toolchain}<dt>Toolchain</dt><dd><code>{index.project.toolchain}</code></dd>{/if}
      {#each Object.entries(index.project.dependencies || {}) as [n, r]}
        <dt>{n}</dt><dd><code>{r}</code></dd>
      {/each}
    {/if}
    {#each index.papers as p}
      {#if p.published}<dt>Published paper</dt><dd>{p.published}</dd>{/if}
      {#if p.published_note}<dt>Revision note</dt><dd>{p.published_note}</dd>{/if}
      <dt>Paper {p.id}</dt>
      <dd>{p.mode === "latex" ? "LaTeX" : "PDF only"}{#if p.revision} at <code>{p.revision.slice(0, 12)}</code>{/if}{#if p.root}, root <code>{p.root}</code>{/if}{#if p.pdf_sha256}, PDF <code title={p.pdf_sha256}>{p.pdf_sha256.slice(0, 12)}</code>{/if}</dd>
    {/each}
    <dt>Tool</dt><dd>{index.tool?.name} {index.tool?.version} <span class="faint">({index.tool?.fingerprint})</span></dd>
  </dl>

  {#if error}
    <p class="faint">The changes since the earlier release could not be loaded: {error}</p>
  {:else if changes}
    <section class="changes" data-changes>
      <h2>Changes since release <code>{changes.from.release}</code></h2>
      <ul class="ids">
        {#each Object.keys(changes.paper_changed) as pid}
          <li>Paper {pid}: revision {revision(changes.from, pid)} → {revision(changes.to, pid)}{changes.paper_changed[pid] ? "" : " (unchanged)"}</li>
        {/each}
        <li>Lean project: {(changes.from.project.commit || "not recorded").slice(0, 12)} → {(changes.to.project.commit || "not recorded").slice(0, 12)}{changes.lean_changed ? "" : " (Lean inputs unchanged)"}</li>
      </ul>
      <p class="counts">
        {#each Object.entries(changes.counts.evidence) as [k, n]}<span class={"out o-" + k}>{n} {OUTCOME[k].toLowerCase()}</span>{/each}
        {#each Object.entries(changes.counts.claims) as [k, n]}<span>{n} {PAPER[k].toLowerCase()}</span>{/each}
      </p>
      <p class="note">{changes.note}</p>
      <label class="all"><input type="checkbox" bind:checked={everything} /> Show unchanged claims</label>

      {#each shown as c (c.claim)}
        <article class="claim" data-claim={c.claim}>
          <h3>
            {#if known.has(c.claim)}<a href={href(index.release, "claim", c.claim)}>{c.number || c.claim}</a>{:else}{c.number || c.claim}{/if}
            <span class={"pc p-" + c.paper_change.class}>{PAPER[c.paper_change.class]}</span>
          </h3>
          <p class="why">{c.paper_change.reason}</p>
          {#if c.paper_change.pin}<p class="warn">{c.paper_change.pin}</p>{/if}
          <div class="status">
            <span class="faint">Earlier build</span>{#if c.status.from}<StatusChip record={c.status.from} small />{:else}<span>not in this build</span>{/if}
            <span class="faint">Later build</span>{#if c.status.to}<StatusChip record={c.status.to} small />{:else}<span>not in this build</span>{/if}
          </div>
          {#each c.paper_change.context || [] as ctx}
            <p class="ctx">Context: {ctx.what} {where(ctx)} {ctx.change}</p>
          {/each}
          {#each texts(c.paper_change) as t}
            <div class="text"><span class="faint">{t.label}</span><pre>{t.text}</pre></div>
          {/each}
          {#each leanRows(c) as e}
            <div class="lean">
              <p><code>{e.name}</code> <span class="faint">({e.clause})</span>: {LEAN[e.change]}</p>
              {#if e.change === "statement" || e.change === "renamed"}
                {#if e.from?.text}<div class="text"><span class="faint">Was</span><pre>{e.from.text}</pre></div>{/if}
                {#if e.to?.text}<div class="text"><span class="faint">Now</span><pre>{e.to.text}</pre></div>{/if}
              {/if}
            </div>
          {/each}
          {#each c.evidence.filter((e) => everything || e.outcome !== "open") as e}
            <div class={"ev o-" + e.outcome} data-outcome={e.outcome}>
              <p><strong>{OUTCOME[e.outcome]}</strong>: review of <code>{e.name}</code>{#if (e.from.marker || e.to.marker)?.by}{" by " + (e.from.marker || e.to.marker).by}{/if}</p>
              {#each e.because || [] as d}<p class="because">Because {dependency(d)}.</p>{/each}
              {#if e.question}<p class="question">{e.question}</p>{/if}
              {#if e.caveat}<p class="warn">{e.caveat}</p>{/if}
              {#each e.kept_through || [] as t}<p class="faint">Stands through a change of {t}, which it does not read.</p>{/each}
            </div>
          {/each}
        </article>
      {/each}
      {#if !shown.length}<p class="faint">No claim changed and no review was reopened.</p>{/if}
    </section>
  {:else if index.changes_unavailable}
    <p class="note" data-changes-unavailable>{index.changes_unavailable}</p>
  {/if}
</main>

<style>
  .ch { max-width: 860px; margin: 0 auto; padding: 28px 16px 80px; }
  h1 { font-family: var(--serif); font-size: 30px; font-weight: 600; }
  h2 { font-family: var(--serif); font-size: 22px; font-weight: 600; margin-top: 36px; }
  h3 { font-size: 16px; margin: 0 0 4px; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 18px; }
  dt { color: var(--muted); }
  dd { margin: 0; word-break: break-all; }
  .ids { padding-left: 18px; color: var(--muted); }
  .counts { display: flex; flex-wrap: wrap; gap: 6px 14px; }
  .note, .why { color: var(--muted); font-size: 14px; }
  .claim { border-top: 1px solid var(--border); padding: 14px 0; }
  .pc { font-size: 12px; font-weight: 500; padding: 0 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface-2); }
  .status { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; font-size: 13px; margin: 6px 0; }
  .text pre { white-space: pre-wrap; word-break: break-word; font-family: var(--mono); font-size: 13px; background: var(--surface-2); padding: 6px 8px; margin: 2px 0 8px; border-radius: 4px; }
  .lean p, .ev p, .ctx { margin: 4px 0; font-size: 14px; }
  .ev { border-left: 3px solid var(--border); padding-left: 10px; margin: 8px 0; }
  .ev.o-reopened, .ev.o-dropped { border-left-color: var(--st-pending, #b7791f); }
  .question { font-style: italic; }
  .warn { font-size: 13px; color: var(--muted); border-left: 3px solid var(--border); padding-left: 8px; }
  .all { font-size: 14px; color: var(--muted); display: flex; gap: 6px; align-items: center; }
  code { word-break: break-all; }
</style>
