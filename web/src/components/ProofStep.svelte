<script>
  import LinkPicker from "./LinkPicker.svelte";
  import { evidenceView } from "../lib/presentation.js";
  import { href, withQuery } from "../lib/route.svelte.js";
  import { STEP_VERDICTS } from "../lib/review.js";
  import { readingWords } from "../lib/coverage.js";

  // A proof step (an equation or passage of a printed proof) as a target of its own. `part`
  // chooses what is drawn: its own review beside the printed step ("finding"), what was recorded
  // about the Lean that establishes it and the formal route used instead ("route"; the comparison
  // draws the linked Lean itself), or, on the enclosing result, the list of its steps ("list")
  // and, in the local reader, the selection of a passage of its proof ("select"). Nothing here is
  // the parent's: a step that no review covers reads "not reviewed", whatever its parent's status.
  let { claim, index, part, editable = false, busy = false, error = null, onlink = null, onroute = null, onpassage = null } = $props();

  const st = $derived(claim.step);
  const rv = $derived(st?.review || { state: "unreviewed", reports: [] });
  const UNIT = { "proof-equation": "Equation in a proof", "proof-passage": "Passage of a proof" };
  // The step's reading in the engine's words; a bridge reads as checked only while Lean checks it
  // (a full assessment checks none for a step).
  const corWords = $derived(st?.correspondence ? readingWords(st.correspondence.coverage, st.correspondence.basis,
    st.correspondence.bridge?.state || "unchecked") : null);
  const LABEL = Object.fromEntries(Object.values(STEP_VERDICTS).flat().map((v) => [v.value, v.label]));
  function who(r) {
    const x = r.reviewer || {};
    return (x.kind === "model" ? "the AI model " + (x.model || x.id) : (x.name || x.id))
      + (x.identity === "self-declared" ? " (self-declared)" : "")
      + (x.author ? ", an author of the statements" : "");
  }
  // When a review was made: its date, or where its marker is recorded.
  function when(r) {
    return r.submitted_at ? ", " + r.submitted_at.slice(0, 10) : r.file ? " (" + r.file + (r.line ? ":" + r.line : "") + ")" : "";
  }
  const reviewHref = $derived(index.review_queue ? withQuery(href(index.release, "review"), { claim: claim.id }) : null);
  // On a paper page a step and its parent are named by the audit's ids; the page lists each
  // under its own id (the row whose audit entry it is).
  const pageId = (id) => (!index.projects ? id
    : index.claims.find((c) => c.by_project?.[claim.evidence_from]?.audit?.claim === id)?.id || id);

  // A selected passage's pinned lines, as `FILE:A-B` (one line: `FILE:A`).
  const span = (p) => p.file + ":" + p.start_line + (p.end_line > p.start_line ? "\u2013" + p.end_line : "");
  const spec = (file, a, b) => `${file}:${a}-${b}`;

  // Selecting a passage of the statement's proof: the local server gives the proofs' lines
  // (`GET api/proof`), the first click marks a line and the second the other end of the
  // passage; the engine checks the selection when it is saved (`link --passage`).
  let proofs = $state(null), proofError = $state(null), sel = $state(null);
  async function loadProofs() {
    if (proofs || proofError) return;
    try {
      const r = await fetch("api/proof?claim=" + encodeURIComponent(claim.id));
      const out = await r.json();
      if (!r.ok) throw new Error(out.error || r.statusText);
      proofs = out.proofs;
    } catch (e) { proofError = String(e.message || e); }
  }
  const stepAt = (p, n) => p.steps.find((t) => t.start_line <= n && n <= t.end_line);
  function pick(p, n) {
    if (!sel || sel.file !== p.file || sel.proof !== p.start_line || sel.done) sel = { file: p.file, proof: p.start_line, from: n, a: n, b: n, done: false };
    else sel = { ...sel, a: Math.min(sel.from, n), b: Math.max(sel.from, n), done: true };
  }
  const chosen = (p, n) => sel && sel.file === p.file && sel.proof === p.start_line && sel.a <= n && n <= sel.b;
</script>

{#if part === "finding" && st}
  <div class="finding" data-review={rv.state}>
    <p class="small kind">{UNIT[st.unit] || "Proof step"}{#if st.parent}{" of "}<a href={href(index.release, "read", claim.paper, pageId(st.parent.id))}>{st.parent.number || st.parent.id}</a>{/if}{#if st.passage}{", selected at "}<code>{span(st.passage)}</code>{/if}</p>
    {#if st.passage && !st.passage.matches}
      <p class="small changed" data-passage="changed">Its lines no longer hold the text it was selected at, so no review of it counts until it is selected again{#if st.passage.moved_to}{"; that text is now at "}<code>{span({ file: st.passage.file, ...st.passage.moved_to })}</code>{/if}.
        {#if editable && st.passage.moved_to}<button class="btn ghost" disabled={busy} onclick={() => onpassage(spec(st.passage.file, st.passage.moved_to.start_line, st.passage.moved_to.end_line))}>Select it there</button>{/if}</p>
    {/if}
    <p class="word"><strong>{evidenceView("step", rv).word}</strong>{#if rv.finding?.verdict?.detail || rv.finding?.text}<span class="pre">{" — " + (rv.finding.verdict.detail || rv.finding.text)}</span>{/if}</p>
    {#if rv.finding}
      <p class="faint small">Review of the printed step by {who(rv.finding)}{when(rv.finding)}. The status of {st.parent?.number || "the enclosing result"} is assessed separately.</p>
    {:else}
      <p class="faint small">{evidenceView("step", rv).detail}{rv.state === "unreviewed" ? " Its scope decision records formal coverage only." : ""}</p>
    {/if}
    {#each rv.reports || [] as r}
      <details class="report">
        <summary class="small">{LABEL[r.verdict.value] || r.verdict.value}, by {who(r)}{when(r)}{r.current ? "" : " · made on other source text"}</summary>
        {#if r.comparison}<p class="small pre">{r.comparison}</p>{/if}
        {#if r.text && r !== rv.finding}<p class="small pre">{r.text}</p>{/if}
        {#if r.reading}<details><summary class="faint small">The reading, locked {r.locked_at}</summary><p class="small pre">{r.reading}</p></details>{/if}
      </details>
    {/each}
    {#if reviewHref}<p class="small"><a href={reviewHref}>Review this step</a></p>{/if}
    {#if editable && st.passage}<p class="small"><button class="btn ghost" disabled={busy} onclick={() => onpassage("none")}>Remove this passage</button></p>{/if}
  </div>
{:else if part === "route" && st}
  {#if st.correspondence?.coverage || st.correspondence?.note}
    {@const cor = st.correspondence}
    <p class="small cov" data-coverage={cor.coverage || "note"}>{#if corWords}<strong>{corWords}</strong>{#if cor.basis === "reviewed_composition"}{" (Lean has not checked the combination)"}{/if}{#if cor.note}{". "}{/if}{/if}{cor.note}{#if cor.by}<span class="faint">{" — " + cor.by}</span>{/if}</p>
  {/if}
  {#if editable}
    <LinkPicker {index} disabled={busy} onpick={(name) => onlink([...st.links.map((x) => x.name), name])} />
    {#if !st.route?.links?.length}
      <h3 class="sub">Different formal route used instead</h3>
      <p class="muted small">No formal route is recorded for this step.</p>
    {/if}
    <LinkPicker {index} disabled={busy} onpick={(name) => onroute([...(st.route?.links || []).map((x) => x.name), name])} />
  {/if}
{:else if part === "list" && claim.steps?.length}
  <section class="steps" aria-label="Proof steps">
    <h3 class="sub">Steps of its proof ({claim.steps.length})</h3>
    <ul>
      {#each claim.steps as s (s.id)}
        <li data-review={s.review}>
          <a href={href(index.release, "read", claim.paper, pageId(s.id))}>{s.number || s.id}</a>
          <span class="small">{evidenceView("step", { state: s.review }).word}</span>
          <span class="faint small">{s.linked.length ? "Lean: " + s.linked.join(", ") : s.route.length ? "formal route: " + s.route.join(", ") : "no Lean linked"}</span>
          {#if s.passage && !s.passage.matches}<span class="small changed">its lines changed since it was selected</span>{/if}
        </li>
      {/each}
    </ul>
  </section>
{:else if part === "select" && editable}
  <details class="select" ontoggle={(e) => e.currentTarget.open && loadProofs()}>
    <summary class="small">Select a passage of its proof</summary>
    {#if proofError}<p class="bad small">{proofError}</p>
    {:else if !proofs}<p class="faint small" role="status">Loading its proof…</p>
    {:else if !proofs.length}<p class="faint small">The paper's source has no proof of this statement.</p>
    {:else}
      <p class="faint small">Click the passage's first line, then its last. A line of a step already listed belongs to that step.</p>
      {#each proofs as p (p.file + p.start_line)}
        <ol class="src" aria-label={"The proof at " + p.file + ":" + p.start_line}>
          {#each p.lines as text, i}
            {@const n = p.start_line + i}
            {@const taken = stepAt(p, n)}
            <li>
              <button class="ln" class:on={chosen(p, n)} data-line={n} disabled={busy || i === 0 || i === p.lines.length - 1 || !!taken}
                title={taken ? "In " + (taken.number || taken.id) : null} onclick={() => pick(p, n)}><span class="no">{n}</span><code>{text}</code>{#if taken}<span class="faint small">{taken.number || taken.id}</span>{/if}</button>
            </li>
          {/each}
        </ol>
      {/each}
      {#if sel}
        <p class="small pick">Lines {sel.a}{sel.b > sel.a ? "\u2013" + sel.b : ""} of <code>{sel.file}</code>.
          <button class="btn" disabled={busy} onclick={() => onpassage(spec(sel.file, sel.a, sel.b))}>Select as a proof passage</button></p>
      {/if}
    {/if}
    {#if error}<p class="bad small">{error}</p>{/if}
  </details>
{/if}

<style>
  .finding { border-left: 3px solid var(--border); padding: 4px 0 4px 10px; margin-top: 12px; }
  .finding[data-review="false"], .finding[data-review="undetermined"], .finding[data-review="stale"] { border-left-color: var(--tier-warning); }
  .finding[data-review="holds"], .finding[data-review="gap"] { border-left-color: var(--st-proved); }
  .finding p { margin: 2px 0; }
  .kind { color: var(--muted); }
  .word { font-size: 14px; }
  .pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  .report { margin-top: 6px; }
  .report summary { cursor: pointer; }
  .sub { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .cov { border-left: 3px solid var(--border); padding-left: 10px; }
  .cov[data-coverage="full"] { border-left-color: var(--st-proved); }
  .steps ul { list-style: none; padding: 0; margin: 0; }
  .steps li { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; padding: 4px 0; border-bottom: 1px solid var(--border); }
  .changed { color: var(--tier-warning); }
  .select { margin-top: 10px; }
  .select summary { cursor: pointer; color: var(--muted); }
  .src { list-style: none; margin: 6px 0; padding: 0; border: 1px solid var(--border); border-radius: 8px; max-height: 360px; overflow: auto; background: var(--surface); }
  .ln { display: flex; gap: 8px; align-items: baseline; width: 100%; text-align: left; border: 0; background: none; color: var(--text); padding: 1px 8px; cursor: pointer; font: inherit; }
  .ln:disabled { cursor: default; color: var(--muted); }
  .ln.on { background: var(--accent-soft); }
  .ln code { font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; flex: 1; min-width: 0; }
  .no { font: 12px/1.5 var(--mono); color: var(--muted); min-width: 3ch; text-align: right; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent); border-radius: 6px; padding: 3px 10px; cursor: pointer; font-size: 13px; }
  .btn.ghost { background: transparent; color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .bad { color: var(--st-malformed); }
  .small { font-size: 13px; }
</style>
