<script>
  import { loadQueue, loadClaim } from "../lib/data.js";
  import { href } from "../lib/route.svelte.js";
  import { VERDICTS, GROUPS, CHECKLIST, MARKS, loadWork, saveWork, now, reviewerId, needsDetail, buildReport,
           exportFile } from "../lib/review.js";
  import PdfCrop from "./PdfCrop.svelte";
  import Tex from "./Tex.svelte";
  import Statement from "./Statement.svelte";
  import Decl from "./Decl.svelte";
  import TexInline from "./TexInline.svelte";

  // The review queue: one unit at a time, in three steps. Read the paper and write your own
  // reading; then see the Lean, compare and record a verdict; then read the author's review.
  let { index } = $props();

  let queue = $state(null);
  let error = $state(null);
  loadQueue(index).then((q) => (queue = q)).catch((e) => (error = String(e)));

  const project = index.project?.name || "project";
  let work = $state(loadWork(project));
  let stored = $state(true);
  function persist() { stored = saveWork(project, $state.snapshot(work)); }

  // Who is reviewing: asked once, kept in this browser.
  let who = $state({ kind: "human", name: "", model: "", sameFamily: "no" });
  function setReviewer() {
    if (who.kind === "human" ? !who.name.trim() : !who.model.trim()) return;
    work.reviewer = { ...who, sameFamily: who.kind === "human" ? "no" : who.sameFamily };
    persist();
  }

  // What to review: a paper, then a section of statements or a group of definitions.
  let paper = $state(work.selection?.paper || "all");
  let group = $state(work.selection?.group || "all");
  function select() { work.selection = { paper, group }; persist(); }

  const fpOf = (u) => u.fingerprint || JSON.stringify(u.fingerprints || {});
  const reportFor = (u) => work.reports.find((r) => r.unit.id === u.id &&
    (r.pins.fingerprint || JSON.stringify(r.pins.fingerprints || {})) === fpOf(u));
  const groupOf = (u) => (u.kind === "def" ? "def:" + u.section : "sec:" + (u.paper || "") + ":" + u.section);
  const groupLabel = (g) => g.startsWith("def:") ? "Definitions · " + g.slice(4)
    : "Statements · " + (index.papers.length > 1 ? "Paper " + g.split(":")[1] + " " : "") + "§" + g.split(":")[2];

  const inPaper = $derived(queue ? queue.units.filter((u) => paper === "all" || (u.papers || []).includes(paper)) : []);
  const groups = $derived([...new Set(inPaper.map(groupOf))].sort());
  const selected = $derived(inPaper.filter((u) => group === "all" || groupOf(u) === group));
  const open = $derived(selected.filter((u) => u.state !== "reviewed" && !reportFor(u)));
  const fresh = $derived(open.filter((u) => !work.skipped.includes(u.id)));
  const skippedHere = $derived(open.filter((u) => work.skipped.includes(u.id)));
  const current = $derived(fresh[0] || skippedHere[0] || null);
  const submittedHere = $derived(selected.filter((u) => reportFor(u)).length);
  const doneBefore = $derived(selected.filter((u) => u.state === "reviewed").length);
  const unexported = $derived(work.reports.length - (work.exported || 0));

  // The card's draft, kept as it is typed.
  $effect(() => {
    if (current && !work.drafts[current.id]) work.drafts[current.id] = { stage: "read", reading: "" };
  });
  const draft = $derived(current ? work.drafts[current.id] || null : null);

  // What the card shows, loaded when it changes.
  let claims = $state([]);
  $effect(() => {
    const u = current;
    claims = [];
    if (!u) return;
    Promise.all(u.claims.slice(0, 6).map((c) => loadClaim(index, c.id).catch(() => null)))
      .then((cs) => { if (current === u) claims = cs.filter(Boolean); });
  });
  const clause = $derived(current?.kind === "spec"
    ? claims.flatMap((c) => c.clauses || []).find((cl) => cl.spec === current.name) : null);
  const host = $derived(claims[0]);
  const paperOf = (c) => index.papers.find((p) => p.id === c.paper);

  function lockReading() {
    if ((draft.reading || "").trim().length < 20) return;
    draft.locked_at = now(); draft.stage = "compare"; persist();
  }
  function choose(g) { draft.group = g; draft.verdict = VERDICTS[g].length === 1 ? VERDICTS[g][0].value : null; persist(); }
  const detailWanted = $derived(draft?.verdict ? needsDetail(draft.verdict) : null);
  const canDecide = $derived(!!draft?.verdict && (!detailWanted || (draft.detail || "").trim().length > 0)
                             && (draft.comparison || "").trim().length > 0);
  function decide() {
    if (!canDecide) return;
    draft.decided_at = now(); draft.stage = "author"; draft.author_shown_at = now(); persist();
  }
  function submit() {
    const r = buildReport({ index, unit: current, draft: $state.snapshot(draft), reviewer: work.reviewer });
    work.reports.push(r);
    work.skipped = work.skipped.filter((id) => id !== current.id);
    delete work.drafts[current.id];
    lastIssue = r.issue_draft;
    persist();
  }
  function skip() {
    if (!work.skipped.includes(current.id)) work.skipped.push(current.id);
    else work.skipped = [...work.skipped.filter((id) => id !== current.id), current.id];
    persist();
  }
  function undo() {
    const r = work.reports.pop();
    if (!r) return;
    work.drafts[r.unit.id] = {
      stage: "author", reading: r.reading.text, locked_at: r.reading.locked_at,
      comparison: r.comparison.text, witness: r.comparison.witness, decided_at: r.comparison.decided_at,
      group: r.verdict.group, verdict: r.verdict.value, detail: r.verdict.detail,
      author_shown_at: r.author_review.shown_at, disagreements: r.author_review.disagreements };
    work.exported = Math.min(work.exported || 0, work.reports.length);
    lastIssue = null;
    persist();
  }
  function doExport() { exportFile(index, $state.snapshot(work)); work.exported = work.reports.length; persist(); }
  let lastIssue = $state(null);
</script>

<main class="review">
  {#if error}
    <p class="bad">The review queue could not be loaded: {error}</p>
  {:else if !queue}
    <p class="muted">Loading…</p>
  {:else if !work.reviewer}
    <section class="card setup">
      <h1>Review</h1>
      <p>One unit at a time: read the paper and write down what it says, then compare the Lean
        with your reading and record a verdict, then read the author's review. Your drafts and
        reports are kept only in this browser until you export them (clearing its data, or another
        browser, starts with none); a maintainer examines them before anything is recorded as
        reviewed.</p>
      <fieldset>
        <legend>Who is reviewing?</legend>
        <label><input type="radio" bind:group={who.kind} value="human" /> A person</label>
        <label><input type="radio" bind:group={who.kind} value="model" /> An AI model</label>
      </fieldset>
      {#if who.kind === "human"}
        <label class="field">Your name <input bind:value={who.name} placeholder="e.g. Ada Lovelace" /></label>
      {:else}
        <label class="field">Model and version <input bind:value={who.model} placeholder="e.g. some-model-2" /></label>
        <label class="field">Same model family as the author of the statements{queue.authors.length ? ` (${queue.authors.join(", ")})` : ""}?
          <select bind:value={who.sameFamily}><option value="yes">yes</option><option value="no">no</option><option value="unknown">don't know</option></select>
        </label>
      {/if}
      <p class="faint small">This is recorded as you state it (self-declared); nothing here verifies it.</p>
      <button class="btn" onclick={setReviewer}>Start</button>
    </section>
  {:else}
    <div class="bar">
      <label>Paper
        <select bind:value={paper} onchange={() => { group = "all"; select(); }}>
          <option value="all">All</option>
          {#each index.papers as p}<option value={p.id}>{index.papers.length > 1 ? "Paper " + p.id : p.title}</option>{/each}
        </select>
      </label>
      <label>Part
        <select bind:value={group} onchange={select}>
          <option value="all">All</option>
          {#each groups as g}<option value={g}>{groupLabel(g)}</option>{/each}
        </select>
      </label>
      <span class="progress">
        {submittedHere} submitted · {skippedHere.length} skipped · {fresh.length} to review{doneBefore ? ` · ${doneBefore} already independently reviewed` : ""}
      </span>
      <span class="who faint" title="self-declared">{reviewerId(work.reviewer)}</span>
      <button class="btn ghost" disabled={!work.reports.length} onclick={undo}>Undo last</button>
      <button class="btn" disabled={!work.reports.length} onclick={doExport}>Export reports{unexported > 0 ? ` (${unexported} new)` : ""}</button>
    </div>
    {#if unexported > 0 || !stored}
      <p class="warn">{!stored ? "This browser is not keeping your work: export after every report." : `${unexported} report(s) are only in this browser until you export them.`}</p>
    {/if}
    {#if queue.needs_statement.length && (paper === "all" || queue.needs_statement.some((c) => c.paper === paper))}
      <p class="faint small">{queue.needs_statement.filter((c) => paper === "all" || c.paper === paper).length} claim(s) need a formal statement before they can be reviewed; they are not in the queue.</p>
    {/if}

    {#if lastIssue}
      <section class="card issue">
        <p class="lbl">Issue draft ({lastIssue.kind}) — for the maintainer; nothing is filed</p>
        <p><strong>{lastIssue.title}</strong></p>
        <pre>{lastIssue.body}</pre>
        <button class="btn ghost" onclick={() => navigator.clipboard?.writeText(lastIssue.title + "\n\n" + lastIssue.body)}>Copy</button>
        <button class="btn ghost" onclick={() => (lastIssue = null)}>Dismiss</button>
      </section>
    {/if}

    {#if !current}
      <section class="card"><p>Nothing left to review in this selection.</p></section>
    {:else if !draft}
      <p class="muted">Loading…</p>
    {:else}
      <article class="card unit">
        <ol class="steps">
          <li class:on={draft.stage === "read"}>1. Read</li>
          <li class:on={draft.stage === "compare"}>2. Compare</li>
          <li class:on={draft.stage === "author"}>3. Author's review</li>
        </ol>
        <p class="why faint">{current.kind === "def" ? "Definition" : current.kind === "link" ? "Linked claim" : "Statement"} · {current.reason}{work.skipped.includes(current.id) ? " · skipped before" : ""}</p>

        {#if current.kind === "def"}
          <h2>A definition used by {current.claims.length} claim(s)</h2>
          <p class="small">Used by:
            {#each current.claims.slice(0, 12) as c, i}{i ? ", " : ""}<a href={href(index.release, "read", c.id.split(":")[0], c.id)} target="_blank" rel="noopener">{c.id}</a>{/each}{current.claims.length > 12 ? ", …" : ""}
          </p>
        {:else}
          {#snippet printed(c)}
            <h2>{c.number}{#if c.heading}<span class="ht">&nbsp;— <TexInline text={c.heading} /></span>{/if}</h2>
            {#if !c.heading && c.title}<p class="desc"><TexInline text={c.title} /></p>{/if}
            {#if paperOf(c)?.pdf && c.anchor?.begin}
              <PdfCrop url={"data/" + paperOf(c).pdf} anchor={c.anchor} />
            {:else if c.statement_tex}
              <Tex text={c.statement_tex} />
            {/if}
            <p class="small"><a href={href(index.release, "read", c.paper, c.id)} target="_blank" rel="noopener" title="Opens the reader, where the Lean side is not hidden">Open in the paper ↗</a></p>
          {/snippet}
          {#if claims[0]}{@render printed(claims[0])}{/if}
          {#if claims.length > 1}
            <details class="also"><summary>Also stated in {claims.length - 1} other place(s)</summary>
              {#each claims.slice(1) as c (c.id)}{@render printed(c)}{/each}
            </details>
          {/if}
        {/if}

        <h3>Your reading{draft.stage !== "read" ? " (locked " + draft.locked_at + ")" : ""}</h3>
        {#if draft.stage === "read"}
          <p class="faint small">{current.kind === "def"
            ? "What is this object in the paper? Its setting, what it is built from, and anything left ambiguous."
            : "The setting; every hypothesis, with its quantifiers and where it holds; the notion of solution; the conclusion, with its quantifier order and what constants depend on; every ambiguity and its readings."}</p>
          <textarea rows="8" bind:value={draft.reading} oninput={persist}></textarea>
          <div class="row">
            <button class="btn" disabled={(draft.reading || "").trim().length < 20} onclick={lockReading}>Lock my reading and show the Lean</button>
            <button class="btn ghost" onclick={skip}>Skip</button>
          </div>
        {:else}
          <pre class="locked">{draft.reading}</pre>

          <h3>In Lean <code class="small">{current.name}</code></h3>
          {#if current.kind === "def"}
            <Decl name={current.name} key={current.key} open hideReview />
          {:else if current.kind === "spec" && clause?.statement}
            <Statement st={clause.statement} spec={current.name} />
            {#if clause.statement.closure?.length}
              <details class="closure"><summary>Definitions it uses ({clause.statement.closure.length})</summary>
                {#each clause.statement.closure as n}<Decl name={n} key={host?.decls?.[n]} hideReview />{/each}
              </details>
            {/if}
            {#if current.witness}<p class="small">Witness: <code>{current.witness}</code></p>{/if}
          {:else if current.kind === "link"}
            {#each host?.links || [] as l}
              <p class="small"><code>{l.name}</code></p>
              {#if l.statement}<Statement st={l.statement} />{/if}
            {/each}
          {:else}
            <p class="faint">Loading…</p>
          {/if}

          {#if draft.stage === "compare"}
            <h3>Comparison</h3>
            <ul class="checklist" aria-label="What to compare">
              {#each CHECKLIST[current.kind === "def" ? "def" : "statement"] as it (it.key)}
                <li>
                  <span class="ck-label">{it.label}<span class="faint small">&nbsp;— {it.hint}</span></span>
                  <span class="ck-marks">
                    {#each MARKS as m}
                      <button class="mark" class:on={draft.checklist?.[it.key] === m.value} class:differs={m.value === "differs"}
                        onclick={() => { draft.checklist = { ...(draft.checklist || {}), [it.key]: draft.checklist?.[it.key] === m.value ? undefined : m.value }; persist(); }}>{m.label}</button>
                    {/each}
                  </span>
                </li>
              {/each}
            </ul>
            <p class="faint small">A guide: mark each item if it helps, and write what you found below.</p>
            <textarea rows="6" bind:value={draft.comparison} oninput={persist} placeholder="Item by item against your reading: each hypothesis, each quantifier and its order, the conclusion, representation choices, constants."></textarea>
            {#if current.kind === "spec" && current.witness}
              <textarea rows="3" bind:value={draft.witness} oninput={persist} placeholder="The witness: does it meet the hypotheses at an instance the paper intends, and is that instance non-trivial?"></textarea>
            {/if}
            <div class="groups">
              {#each GROUPS as g}<button class="choice" class:on={draft.group === g.key} onclick={() => choose(g.key)}>{g.label}</button>{/each}
            </div>
            {#if draft.group}
              <div class="verdicts">
                {#each VERDICTS[draft.group].filter((v) => !v.refuteOnly || current.refute) as v}
                  <label><input type="radio" bind:group={draft.verdict} value={v.value} onchange={persist} /> {v.label}</label>
                {/each}
              </div>
              {#if detailWanted}
                <textarea rows="3" bind:value={draft.detail} oninput={persist} placeholder={detailWanted}></textarea>
              {/if}
            {/if}
            <div class="row">
              <button class="btn" disabled={!canDecide} onclick={decide}>Record verdict and show the author's review</button>
              <button class="btn ghost" onclick={skip}>Skip</button>
            </div>
          {:else}
            <p class="small"><strong>Your verdict:</strong> {draft.verdict}{draft.detail ? " — " + draft.detail : ""} <span class="faint">(recorded {draft.decided_at})</span></p>
            <h3>The author's review</h3>
            {#each current.author_review as r}
              <p class="lbl">{r.by}{r.file ? " · " + r.file + (r.line ? ":" + r.line : "") : ""}</p>
              <pre class="author">{r.text || "(no text)"}</pre>
            {:else}
              <p class="faint">No review by the author is recorded for this unit.</p>
            {/each}
            <textarea rows="3" bind:value={draft.disagreements} oninput={persist} placeholder="Where you disagree with the author's review, or where it claims more than the Lean shows (or “none”). Your verdict stays as recorded."></textarea>
            <div class="row">
              <button class="btn" onclick={submit}>Submit report</button>
              <button class="btn ghost" onclick={skip}>Skip</button>
            </div>
          {/if}
        {/if}
      </article>
    {/if}
  {/if}
</main>

<style>
  .review { max-width: 920px; margin: 0 auto; padding: 16px 16px 80px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px 20px; margin: 12px 0; }
  .setup h1 { margin-top: 0; }
  fieldset { border: 0; padding: 0; margin: 12px 0; display: flex; gap: 16px; }
  .field { display: flex; flex-direction: column; gap: 4px; margin: 8px 0; font-size: 14px; }
  input:not([type]), input[type="text"], select, textarea { font: inherit; font-size: 14px; color: var(--text); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; }
  textarea { width: 100%; box-sizing: border-box; margin: 6px 0; font-family: var(--sans); }
  .bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 14px; }
  .bar label { display: flex; gap: 6px; align-items: center; }
  .progress { color: var(--muted); }
  .who { margin-left: auto; font-family: var(--mono); font-size: 12px; }
  .warn { background: var(--surface-2); border-left: 3px solid var(--st-open); padding: 6px 10px; font-size: 13px; }
  .steps { list-style: none; display: flex; gap: 6px; padding: 0; margin: 0 0 6px; font-size: 13px; }
  .steps li { padding: 2px 10px; border-radius: 999px; background: var(--surface-2); color: var(--muted); }
  .steps li.on { background: var(--accent-soft); color: var(--text); }
  .why { font-size: 13px; margin: 4px 0 8px; }
  h2 { font-size: 15px; font-weight: 600; margin: 14px 0 6px; }
  .ht { font-weight: 400; color: var(--muted); }
  .desc { margin: -2px 0 8px; font-size: 14px; color: var(--muted); }
  h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin: 18px 0 6px; }
  .locked, .author, .issue pre { white-space: pre-wrap; font: 14px/1.5 var(--sans); background: var(--surface-2); padding: 8px 10px; border-radius: 6px; margin: 0; }
  .row { display: flex; gap: 8px; margin-top: 8px; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: white; border-radius: 6px; padding: 5px 12px; cursor: pointer; font-size: 14px; }
  .btn.ghost { background: none; color: var(--accent); }
  .btn:disabled { opacity: 0.45; cursor: default; }
  .groups { display: flex; gap: 8px; margin: 12px 0 6px; flex-wrap: wrap; }
  .choice { flex: 1; min-width: 160px; padding: 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-2); cursor: pointer; font-size: 14px; color: var(--text); }
  .choice.on { border-color: var(--accent); background: var(--accent-soft); }
  .verdicts { display: flex; flex-direction: column; gap: 4px; font-size: 14px; margin: 6px 0; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 8px 0 2px; }
  .small { font-size: 13px; }
  .also summary { cursor: pointer; font-size: 13px; color: var(--accent); margin: 10px 0; }
  .closure summary { cursor: pointer; font-size: 13px; color: var(--accent); margin: 8px 0; }
  .bad { color: var(--st-malformed); }
  @media (max-width: 640px) { .who { margin-left: 0; } }
  .checklist { list-style: none; padding: 0; margin: 6px 0; }
  .checklist li { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; padding: 4px 0; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
  .ck-marks { display: flex; gap: 4px; flex: none; }
  .mark { font: inherit; font-size: 12px; padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); cursor: pointer; }
  .mark.on { border-color: var(--accent); color: var(--accent); background: var(--accent-soft, transparent); }
  .mark.differs.on { border-color: var(--st-open, #b7791f); color: var(--st-open, #b7791f); }
</style>
