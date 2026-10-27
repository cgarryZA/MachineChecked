<script>
  // What this release was built from, and what changed since the release before it: each
  // claim's passage, its Lean statements and definitions, both builds' statuses, and every
  // review the later build no longer counts, with the change it depends on and the question a
  // new reading answers (`changes.py`). Every state shown is the one the engine recorded.
  import { auditInfo, AUDIT, loadChanges } from "../lib/data.js";
  import { href } from "../lib/route.svelte.js";
  import { listWorkspaces, revisionOf, rememberedWorkspace } from "../lib/workspace.js";
  import { findingCoverageView, recordedBasisText } from "../lib/coverage.js";
  import StatusChip from "./StatusChip.svelte";
  let { index, editable = false } = $props();

  let changes = $state(null);
  let error = $state(null);
  let everything = $state(false);
  $effect(() => {
    loadChanges(index).then((d) => (changes = d)).catch((e) => (error = String(e)));
  });

  // Under `machinechecked view`: the findings of a saved investigation that a revision of the
  // paper reopens, through each version map the workspace keeps to this release
  // (`reopen.py`). A static copy of the site has no workspace.
  let spaces = $state([]);
  let wsId = $state(null);
  let reopened = $state(null);
  let revisionError = $state(null);
  $effect(() => {
    if (!editable) return;
    listWorkspaces().then((d) => {
      spaces = (d.workspaces || []).filter((w) => w.version_maps);
      const mine = rememberedWorkspace();
      wsId = (spaces.find((w) => w.id === mine) || spaces[0])?.id || null;
    }).catch(() => (spaces = []));
  });
  $effect(() => {
    const id = wsId;
    reopened = null;
    revisionError = null;
    if (id) revisionOf(id).then((d) => (reopened = d)).catch((e) => (revisionError = String(e.message || e)));
  });

  const STATE = { reopened: "Due for review", unchecked: "Not known to be current", current: "Still current" };
  const RANK = { reopened: 0, unchecked: 1, current: 2 };
  // The findings of one map by the claim they are about, those with something to review first.
  function groups(m) {
    const by = new Map();
    for (const f of m.findings || []) {
      if (!by.has(f.claim)) by.set(f.claim, { claim: f.claim, earlier: f.earlier, later: f.later, cls: f.class, findings: [] });
      by.get(f.claim).findings.push(f);
    }
    const rank = (g) => Math.min(...g.findings.map((f) => RANK[f.state] ?? 2));
    return [...by.values()].sort((a, b) => rank(a) - rank(b) || a.claim.localeCompare(b.claim));
  }
  function headline(f) {
    const cv = findingCoverageView(f);
    if (cv?.headline) return cv.headline;
    if (f.verdict) return "The printed step: " + f.verdict;
    if (f.difference?.feature) return `A ${f.difference.feature} difference`;
    return "No coverage given";
  }
  // Each diff a change carries: of the passage itself, of a context it is read with, and of a
  // claim it relies on.
  function diffs(ch) {
    if (!ch) return [];
    const out = [];
    if (ch.diff?.length) out.push(ch.diff);
    for (const x of ch.context || []) {
      if (x.diff?.length) out.push(x.diff);
      if (x.claim_change?.diff?.length) out.push(x.claim_change.diff);
    }
    return out;
  }
  const lineClass = (ln) => (ln.startsWith("+++") || ln.startsWith("---") || ln.startsWith("@@")) ? "dh"
    : ln.startsWith("+") ? "add" : ln.startsWith("-") ? "del" : "";
  function places(o) {
    const a = o.earlier?.location, b = o.later?.location;
    if (a && b && a !== b) return `${a} → ${b}${o.later?.proposed ? " (from the line diff)" : ""}`;
    return a || b || "";
  }
  function heading(g) {
    const a = g.earlier?.number || g.claim, b = g.later?.number || g.later?.claim;
    return b && b !== a ? `${a} → ${b}` : a;
  }

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
  {/if}

  {#if revisionError}
    <p class="faint">The findings across the paper revision could not be loaded: {revisionError}</p>
  {:else if reopened && (reopened.maps.length || reopened.other.length)}
    <section class="revision" data-revision>
      <h2>Findings across the paper revision</h2>
      {#if spaces.length > 1}
        <label class="all">Workspace
          <select bind:value={wsId} aria-label="Workspace">
            {#each spaces as w}<option value={w.id}>{w.id} ({w.reviewer})</option>{/each}
          </select>
        </label>
      {/if}
      {#each reopened.maps as m}
        <div class="map" data-map={m.paper}>
          <p class="where">Workspace <code>{m.workspace}</code>, paper {m.paper}: release <code>{m.from?.release || m.from?.revision}</code> → <code>{m.to?.release || m.to?.revision}</code>{#if m.map?.kept_by}; version map kept by {m.map.kept_by}{/if}</p>
          <p class="counts">{#each Object.entries(m.counts) as [k, n]}<span class={"st s-" + k}>{n} {STATE[k].toLowerCase()}</span>{/each}</p>
          {#if !m.build_checked}<p class="warn">The Lean these findings cite is not checked against this build.</p>{/if}
          <p class="note">{m.note}</p>
          {#each groups(m) as g (g.claim)}
            <article class="claim" data-claim={g.claim}>
              <h3>
                {#if g.later && known.has(g.later.claim)}<a href={href(index.release, "claim", g.later.claim)}>{heading(g)}</a>{:else}{heading(g)}{/if}
                {#if g.cls}<span class={"pc p-" + g.cls}>{PAPER[g.cls]}</span>{/if}
              </h3>
              {#each g.findings as f (f.id)}
                <div class={"fd s-" + f.state} data-finding={f.id} data-state={f.state}>
                  <p><strong>{STATE[f.state]}</strong>: finding <code>{f.id}</code>{#if f.finding.requirement}{" on " + f.finding.requirement}{/if}{#if f.finding.created_by}{" by " + f.finding.created_by}{/if}: {headline(f.finding)}</p>
                  {#if f.finding.note}<p class="earlier">{f.finding.note}</p>{/if}
                  {#if recordedBasisText(f.finding)}<p class="faint">{recordedBasisText(f.finding)}</p>{/if}
                  {#each f.paper as o}
                    {#if o.state === "current"}
                      <p class="kept">Still current: {o.text}{o.note ? `: ${o.note}` : ""}.</p>
                    {:else}
                      <div class="dep" data-dep={o.state}>
                        <p>{o.state === "unchecked" ? "Not known" : o.change?.class === "removed" ? "Removed" : "Changed"}: {o.text}{places(o) ? ` (${places(o)})` : ""}: {o.state === "unchecked" ? o.why : o.change?.reason}.</p>
                        {#each diffs(o.change) as d}<pre class="diff">{#each d as ln}<span class={lineClass(ln)}>{ln}</span>{"\n"}{/each}</pre>{/each}
                        {#if o.question}<p class="question">{o.question}</p>{/if}
                      </div>
                    {/if}
                  {/each}
                  {#each f.build?.changes || [] as ch}
                    <div class="dep" data-dep="build">
                      <p>Changed in this build: {ch.words}.</p>
                      {#if ch.statement?.from}<div class="text"><span class="faint">Was</span><pre>{ch.statement.from}</pre></div>{/if}
                      {#if ch.statement?.to}<div class="text"><span class="faint">Now</span><pre>{ch.statement.to}</pre></div>{/if}
                      {#if ch.question}<p class="question">{ch.question}</p>{/if}
                    </div>
                  {/each}
                  {#each f.build?.unknown || [] as u}<p class="faint">Not known in this build: {u.why}.</p>{/each}
                </div>
              {/each}
            </article>
          {/each}
          {#if !m.findings.length}<p class="faint">No finding of this workspace rests on this paper.</p>{/if}
          {#each [...(m.evidence || []), ...(m.passages || [])].filter((r) => r.state !== "current") as r (r.id)}
            <p class="rec" data-record={r.id}>{STATE[r.state]}: {r.requirement ? `passage ${r.id} (${r.role} of ${r.requirement})` : `evidence ${r.id} quoting ${r.earlier?.claim || r.claim}`}{places(r) ? ` at ${places(r)}` : ""}: {r.state === "unchecked" ? r.why : r.change?.reason}.</p>
          {/each}
        </div>
      {/each}
      {#each reopened.other as o}
        <p class="faint">The workspace also keeps a version map of paper {o.paper} to release {o.to?.release}; this site is of release {reopened.release}.</p>
      {/each}
    </section>
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
  .where { color: var(--muted); }
  .map + .map { margin-top: 24px; }
  .fd { border-left: 3px solid var(--border); padding-left: 10px; margin: 8px 0; }
  .fd.s-reopened { border-left-color: var(--tier-warning, #b7791f); }
  .fd p, .rec { margin: 4px 0; font-size: 14px; }
  .earlier { font-family: var(--serif); }
  .kept { color: var(--muted); font-size: 13px; }
  .dep { margin: 6px 0 6px 4px; }
  .diff { white-space: pre-wrap; word-break: break-word; font-family: var(--mono); font-size: 13px; background: var(--surface-2); padding: 6px 8px; margin: 2px 0 8px; border-radius: 4px; }
  .diff .add { color: var(--st-accepted); }
  .diff .del { color: var(--st-refuted); }
  .diff .dh { color: var(--faint); }
  .st { font-size: 14px; }
</style>
