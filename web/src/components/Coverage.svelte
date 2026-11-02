<script>
  import TexInline from "./TexInline.svelte";
  import { projectClaims } from "../lib/data.js";
  import { statusView, statusSummary, evidenceView } from "../lib/presentation.js";
  import { href, route, withQuery, OVERVIEW_FILTERS } from "../lib/route.svelte.js";
  import { summaryOf, keys, words, setLabel, setExplanation, unitOf, readingOf, keysOf,
           unitCounts, countText, inventoryText, coverageText, basisText, shortQuestion } from "../lib/semantic.js";
  import EvidenceSummary from "./EvidenceSummary.svelte";
  let { index } = $props();
  // The engine's semantic summary (`index.semantic`): the counts and each claim's keys are its
  // own, shown as computed. Without one (older data, a paper page), claims are listed by status.
  const summary = $derived(summaryOf(index));
  const sets = $derived(summary?.sets || []);
  const UNIT_VALUES = ["all", "statements", "notation", "proof_steps"];
  // The filters are kept in the address (`?set=&unit=&coverage=…`), so a link names a subset.
  function read(q) {
    const out = {};
    for (const k of OVERVIEW_FILTERS) out[k] = typeof q?.[k] === "string" && q[k] ? q[k] : null;
    out.unit = UNIT_VALUES.includes(out.unit) ? out.unit : out.unit === "steps" ? "proof_steps" : "all";
    return out;
  }
  let f = $state(read(route.filters));
  $effect(() => { f = read(route.filters); });
  function choose(values) {
    f = { ...f, ...values };
    const params = Object.fromEntries(OVERVIEW_FILTERS.map((k) => [k, f[k] && f[k] !== "all" ? f[k] : null]));
    const base = location.hash && location.hash.includes("/overview") ? location.hash : href(index.release, "coverage");
    history.replaceState(history.state, "", withQuery(base, params));
  }
  function reset() { query = ""; choose(Object.fromEntries(OVERVIEW_FILTERS.map((k) => [k, k === "unit" ? "all" : null]))); }
  let query = $state("");
  const setId = $derived(sets.some((s) => s.id === f.set) ? f.set : summary?.selected || "audit");
  const set = $derived(sets.find((s) => s.id === setId) || null);
  const all = $derived(projectClaims(index));
  const unitCount = $derived(Object.fromEntries(["statements", "notation", "proof_steps"].map((u) => [u, all.filter((c) => unitOf(c) === u).length])));
  const claims = $derived(all.filter((c) => f.unit === "all" || unitOf(c) === f.unit));
  const counts = $derived(statusSummary(claims));
  const searched = (c) => `${c.number} ${c.heading || ""} ${c.title || ""} ${c.id}`.toLowerCase();
  const shown = $derived(claims.filter((c) => {
    const k = keysOf(c, setId);
    return (!f.status || c.status_code === f.status) && (!summary || ((!f.coverage || k.coverage === f.coverage) &&
      (!f.basis || k.basis === f.basis) && (!f.review || k.review === f.review) && (!f.finding || k.findings.includes(f.finding)))) &&
      query.toLowerCase().trim().split(/\s+/).every((w) => searched(c).includes(w));
  }));
  // The semantic filters: each key the engine counted for the chosen unit (and set), with its count.
  const GROUPS = [["coverage", "coverage", "Correspondence"], ["basis", "basis", "Evidence basis"],
                  ["review", "review", "Review"], ["findings", "finding", "Recorded findings"]];
  const groups = $derived(summary ? GROUPS.map(([dimension, param, label]) => ({ dimension, param, label,
    rows: keys(dimension).map((key) => ({ key, counts: unitCounts(summary, dimension, setId, key) }))
      .filter((r) => f.unit === "all" ? Object.keys(r.counts).length : r.counts[f.unit]) }))
    .filter((g) => g.rows.length) : []);
  const filtered = $derived(f.status || (summary && (f.coverage || f.basis || f.review || f.finding)) || query.trim());
</script>
<main class="coverage">
  <h1>Overview</h1>
  <p class="muted">{summary ? "Each claim's correspondence with the Lean, how it is supported, its review and its proof results." : "Claims, proof results and correspondence reviews."}</p>
  <label class="search">Find a claim <input type="search" bind:value={query} placeholder="Number or mathematical title" /></label>
  {#if unitCount.proof_steps || unitCount.notation}
    <div class="filters" aria-label="Filter by kind of unit">
      <button class:on={f.unit === "all"} aria-pressed={f.unit === "all"} onclick={() => choose({ unit: "all", status: null })}>{unitCount.notation ? "All claims" : "Statements and proof steps"} ({all.length})</button>
      <button class:on={f.unit === "statements"} aria-pressed={f.unit === "statements"} onclick={() => choose({ unit: "statements", status: null })}>Statements ({unitCount.statements})</button>
      {#if unitCount.notation}<button class:on={f.unit === "notation"} aria-pressed={f.unit === "notation"} onclick={() => choose({ unit: "notation", status: null })}>Notation ({unitCount.notation})</button>{/if}
      {#if unitCount.proof_steps}<button class:on={f.unit === "proof_steps"} aria-pressed={f.unit === "proof_steps"} onclick={() => choose({ unit: "proof_steps", status: null })}>Proof steps ({unitCount.proof_steps})</button>{/if}
    </div>
  {/if}
  {#if summary}
    <section class="semantic" aria-label="Semantic summary" data-digest={summary.digest}>
      {#if sets.length > 1}
        <label class="readings">Readings shown
          <select value={setId} onchange={(e) => choose({ set: e.currentTarget.value === summary.selected ? null : e.currentTarget.value })}>
            {#each sets as s}<option value={s.id}>{setLabel(s)}</option>{/each}
          </select>
        </label>
      {/if}
      <p class="small faint set-note">{setLabel(set)}{set?.kind === "audit" && set.by?.length ? `, by ${set.by.join(", ")}` : ""}. {setExplanation(set)} Each count is of one kind of unit; a claim is counted once in each dimension.</p>
      {#each groups as g}
        <div class="filters" role="group" aria-label={"Filter claims by " + g.label.toLowerCase()} data-dimension={g.dimension}>
          <span class="glabel">{g.label}</span>
          <button class:on={!f[g.param]} aria-pressed={!f[g.param]} onclick={() => choose({ [g.param]: null })}>Any</button>
          {#each g.rows as r}
            {@const w = words(g.dimension, r.key, f.unit)}
            <button class:on={f[g.param] === r.key} aria-pressed={f[g.param] === r.key} data-key={r.key} title={w.explanation}
              onclick={() => choose({ [g.param]: r.key })}>{w.label} ({countText(r.counts, f.unit)})</button>
          {/each}
        </div>
      {/each}
    </section>
  {/if}
  <div class="filters" aria-label="Filter claims by status">
    {#if summary}<span class="glabel">Proof status</span>{/if}
    <button class:on={!f.status} aria-pressed={!f.status} onclick={() => choose({ status: null })}>All ({claims.length})</button>
    {#each counts as row}<button class:on={f.status === row.status_code} aria-pressed={f.status === row.status_code} onclick={() => choose({ status: row.status_code })}>{statusView(row).label} ({row.count})</button>{/each}
  </div>
  <p class="count" role="status">{shown.length} claim{shown.length === 1 ? "" : "s"}{#if filtered}{" "}<button class="reset inline" onclick={reset}>Clear the filters</button>{/if}{#if index.review_queue}{" "}<a class="next" href={href(index.release, "review")}>Review next →</a>{/if}</p>
  {#each index.papers as paper}
    {@const rows = shown.filter((c) => c.paper === paper.id)}
    {#if rows.length}
      <section class="paper">
        <div class="phead"><h2><TexInline text={paper.title} /></h2><a href={href(index.release, "read", paper.id)}>Read paper →</a></div>
        {#if summary?.papers?.[paper.id]}<p class="small faint inventory">{inventoryText(summary.papers[paper.id])}</p>{/if}
        {#if summary}
          <div class="thead" aria-hidden="true"><span>Claim</span><span>Correspondence</span><span>Evidence basis</span><span>Difference or open question</span><span>Review</span></div>
        {/if}
        <ul class="claims" class:sem={!!summary}>
          {#each rows as c (c.id)}
            {@const reading = summary ? readingOf(c, setId) : null}
            {@const k = summary ? keysOf(c, setId) : null}
            <li data-status={c.status_code} data-coverage={k?.coverage} data-basis={k?.basis} data-review={k?.review}>
              <div class="who">
                <a class="claim" href={href(index.release, "read", c.paper, c.id)}><strong>{c.number || c.id}</strong>{#if c.heading || c.title}<span><TexInline text={c.heading || c.title} /></span>{/if}</a>
                <span class="facts"><EvidenceSummary record={c} />{#if unitOf(c) === "proof_steps"}<span class="small step">Review of the printed step: {evidenceView("step", { state: c.step_review || "unreviewed" }).word}</span>{/if}</span>
              </div>
              {#if summary}
                <dl class="cells">
                  <div><dt>Correspondence</dt><dd class="cov">{coverageText(reading)}{#if reading?.by}<span class="faint small by">{" · "}{reading.by}</span>{/if}</dd></div>
                  <div><dt>Evidence basis</dt><dd>{basisText(reading) || "—"}</dd></div>
                  <div><dt>Difference or open question</dt><dd class="question">{#if shortQuestion(reading)}{shortQuestion(reading)}{:else if reading?.question}An open question: see the claim.{:else if k.findings.length}{k.findings.map((x) => words("findings", x).label).join("; ")}{:else}—{/if}</dd></div>
                  <div><dt>Review</dt><dd>{k.review ? words("review", k.review, unitOf(c)).label : "—"}</dd></div>
                </dl>
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {/if}
  {/each}
  {#if !shown.length}<p>No claims match this selection. <button class="reset" onclick={reset}>Show all claims</button></p>{/if}
  {#if index.gates && Object.keys(index.gates).length}
    <details class="checks"><summary>Paper checks</summary>
      {#each index.papers as p}
        {#if index.gates[p.id]}
          {@const g = index.gates[p.id]}
          <h3>{p.title}</h3>
          <details><summary>Consistency check: {g.consistency.pass ? "passed" : "failed"}</summary><ul>{#each g.consistency.failures || [] as f}<li>{f}</li>{/each}</ul></details>
          <details><summary>Release gate: {g.release.pass ? "passed" : "not passed"}</summary><ul>{#each g.release.reasons || [] as reason}<li>{reason}</li>{/each}</ul></details>
        {/if}
      {/each}
    </details>
  {/if}
</main>
<style>
  .coverage { max-width: 1100px; margin: 0 auto; padding: 28px 20px 64px; }
  h1, h2 { font-family: var(--serif); }
  h1 { font-size: 30px; }
  h2 { font-size: 22px; }
  h3 { margin: 18px 0 8px; }
  .search, .readings { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
  .readings { margin-top: 16px; }
  input, select { font: inherit; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); width: min(420px, 100%); background: var(--surface); color: var(--text); }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; align-items: center; }
  .glabel { font-size: 13px; color: var(--muted); min-width: 9em; }
  .semantic { margin-top: 8px; }
  .set-note { margin: 12px 0 0; }
  button { font: inherit; font-size: 14px; border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; background: var(--surface); color: var(--text); cursor: pointer; }
  button.on { background: var(--accent-soft); border-color: var(--accent); }
  .reset.inline { border: 0; background: none; color: var(--accent); padding: 0 4px; }
  .next { margin-left: 8px; }
  .count { color: var(--muted); font-size: 14px; }
  .paper { margin-top: 28px; }
  .phead { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: baseline; }
  .inventory { margin: 4px 0 0; }
  .claims { list-style: none; padding: 0; margin: 16px 0; }
  .claims li { display: grid; grid-template-columns: minmax(0, 1fr) minmax(260px, .7fr); gap: 12px 28px; padding: 14px 0; border-bottom: 1px solid var(--border); align-items: baseline; }
  .claims:not(.sem) li .who { display: contents; }
  .claims.sem li { grid-template-columns: minmax(0, 1.4fr) minmax(0, 4fr); gap: 12px; }
  .thead { display: grid; grid-template-columns: minmax(0, 1.4fr) repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 12px; font-size: 13px; color: var(--muted); border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .who { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .cells { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0; font-size: 14px; }
  .cells dt { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .cells dd { margin: 0; overflow-wrap: anywhere; }
  .claim { display: flex; gap: 6px; flex-direction: column; overflow-wrap: anywhere; }
  .claim span { color: var(--text); font-family: var(--serif); font-size: 17px; }
  .facts { display: flex; flex-direction: column; gap: 4px; }
  .step { color: var(--muted); font-size: 13px; }
  .checks { margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--border); }
  summary { cursor: pointer; padding: 6px 0; }
  @media (max-width: 800px) {
    .claims li, .claims.sem li { grid-template-columns: minmax(0, 1fr); }
    .thead { display: none; }
    .cells { grid-template-columns: minmax(0, 1fr); gap: 4px; }
    .cells div { display: flex; gap: 8px; flex-wrap: wrap; }
    .cells dt { position: static; width: auto; height: auto; clip: auto; color: var(--muted); }
    .cells dt::after { content: ":"; }
    input, select { font-size: 16px; }
    .glabel { min-width: 100%; }
  }
</style>
