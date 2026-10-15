<script>
  import { loadClaim } from "../lib/data.js";
  import { href } from "../lib/route.svelte.js";
  import StatusChip from "./StatusChip.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import Statement from "./Statement.svelte";
  import Ladder from "./Ladder.svelte";
  import Findings from "./Findings.svelte";
  import Decl from "./Decl.svelte";
  import Tex from "./Tex.svelte";

  // Everything established about one claim, from the manifest.
  let { index, claimId, full = false } = $props();

  let claim = $state(null);
  let error = $state(null);
  let openDecl = $state(null);
  let showAll = $state(false);
  const RANK = { stale: 0, pending: 1, "author-reviewed": 2, reviewed: 3 };

  $effect(() => {
    claim = null;
    error = null;
    openDecl = null;
    showAll = false;
    loadClaim(index, claimId).then((c) => (claim = c)).catch((e) => (error = String(e)));
  });

  const paper = $derived(claim && index.papers.find((p) => p.id === claim.paper));
  const meta = $derived(index.claims.find((c) => c.id === claimId));

  function showDecl(name) {
    openDecl = name;
    queueMicrotask(() => document.getElementById("decl-" + name)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }
</script>

{#if error}
  <p>{error}</p>
{:else if !claim}
  <p class="muted">Loading…</p>
{:else}
  <article class="passport" class:full>
    <header>
      <p class="eyebrow">
        Paper {claim.paper} · <code>{claim.id}</code>
        {#if full && meta?.anchor}· <a href={href(index.release, "read", claim.paper, claim.id)}>show in the paper</a>{/if}
      </p>
      <h1>{claim.number || claim.id}{#if claim.title}<span class="title">&nbsp;— {claim.title}</span>{/if}</h1>
      <StatusChip status={claim.status} cls={claim.class} />
      {#if claim.blockers?.length}
        <details class="why" open={full}>
          <summary>Why is this claim not accepted? <span class="faint">({claim.blockers.length})</span></summary>
          <ul>{#each claim.blockers as b}<li>{b}</li>{/each}</ul>
        </details>
      {/if}
      {#if claim.scope_note}<p class="muted note">{claim.scope_note}</p>{/if}
      {#if claim.scope_reviewed === false}
        <p class="faint note">The scope of this claim was set by the automatic first pass and has not been checked by reading.</p>
      {/if}
    </header>

    <section>
      <h2>As printed</h2>
      {#if paper?.pdf && claim.anchor?.begin}
        <PdfCrop url={"data/" + paper.pdf} anchor={claim.anchor} />
      {/if}
      {#if claim.statement_tex}
        <details class="src" open={!(paper?.pdf && claim.anchor?.begin)}>
          <summary>Source text</summary>
          <Tex text={claim.statement_tex} />
          {#if claim.anchor?.file}
            <p class="faint small"><code>{claim.anchor.file}:{claim.anchor.line}</code>
              {#if claim.source_matches === false}<span class="bad"> · differs from the frozen inventory</span>{/if}
            </p>
          {/if}
        </details>
      {:else if !(paper?.pdf && claim.anchor?.begin)}
        <p class="muted">The printed statement is not part of this site.</p>
      {/if}
    </section>

    {#each claim.clauses as cl, k (k)}
      <section class="clause">
        <div class="chead">
          <h2>{claim.clauses.length > 1 ? cl.name : "Formal statement"}</h2>
          <span class={"state s-" + cl.state}>{cl.state}</span>
        </div>
        {#if cl.corrects}
          <p class="muted small">Corrects <code>{cl.corrects}</code>, refuted as printed.</p>
        {/if}

        <Ladder rungs={cl.ladder} />

        {#if cl.statement}
          <Statement st={cl.statement} spec={cl.spec} onref={showDecl} />
        {:else if cl.spec}
          <p class="muted">The proposition <code>{cl.spec}</code> is not shown in this site.</p>
        {:else if cl.defs?.length}
          <p>Lean definitions:
            {#each cl.defs as d, i}{#if i}, {/if}<button class="ref" onclick={() => showDecl(d)}>{d}</button>{/each}
          </p>
        {:else}
          <p class="muted">No proposition has been written for this claim yet.</p>
        {/if}

        {#if cl.proofs && Object.keys(cl.proofs).length}
          <dl class="proof">
            {#each Object.entries(cl.proofs) as [kind, p]}
              {#if p}
                <dt>{kind === "refute" ? "Refutation" : "Proof"}</dt>
                <dd>
                  <code>{p.name}</code>
                  <span class="faint">— type {kind === "refute" ? "¬ " : ""}exactly the proposition{p.errors.length ? "? no: " + p.errors.join(", ") : ""}</span>
                  <br /><span class="small muted">axioms: {p.axioms.length ? p.axioms.join(", ") : "none"}</span>
                </dd>
              {/if}
            {/each}
          </dl>
        {/if}

        {#if cl.witness_record}
          <div class="witness">
            <h3>Witness that the hypotheses can be met</h3>
            <p><code>{cl.witness}</code></p>
            <Statement st={{ binders: [], conclusion: cl.witness_record.type }} onref={showDecl} compact />
          </div>
        {/if}

        {#if cl.regimes?.length}
          <div class="regimes">
            <h3>Regimes the paper intends to cover</h3>
            <ul>
              {#each cl.regimes as r}
                <li>
                  <span class={r.discharged ? "ok" : "bad"}>{r.discharged ? "covered" : "not shown"}</span>
                  <strong>{r.name}</strong>{#if r.description} — <span class="muted">{r.description}</span>{/if}
                  {#if r.witness}<br /><span class="small">by <code>{r.witness}</code></span>{/if}
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        {#if cl.spec_review}
          <div class="reviews">
            <h3>Review of the proposition</h3>
            {#each cl.spec_review.current as r}
              <div class="review">
                <p class="small">
                  <strong>{r.by}</strong>
                  <span class="pill">{r.kind === "ai" ? "AI" : r.kind === "human" ? "human" : "kind not recorded"}</span>
                  <span class="pill">{r.provenance}</span>
                  {#if r.file}<span class="faint">{r.file}:{r.line}</span>{/if}
                </p>
                {#if r.text}<pre class="rtext">{r.text}</pre>{/if}
              </div>
            {:else}
              <p class="muted">No current review{cl.spec_review.stale.length ? " (an earlier review is stale: the proposition changed after it)" : ""}.</p>
            {/each}
          </div>
        {/if}
        {#if cl.def_reviews && Object.keys(cl.def_reviews).length}
          {@const entries = Object.entries(cl.def_reviews).sort((a, b) => RANK[a[1].state] - RANK[b[1].state] || a[0].localeCompare(b[0]))}
          {@const counts = entries.reduce((m, [, r]) => ((m[r.state] = (m[r.state] || 0) + 1), m), {})}
          <div class="reviews">
            <h3>Definitions the meaning depends on</h3>
            <p class="small muted">
              {entries.length} project declaration{entries.length === 1 ? "" : "s"}:
              {Object.entries(counts).sort((a, b) => RANK[a[0]] - RANK[b[0]]).map(([k, v]) => `${v} ${k}`).join(", ")}
            </p>
            <details open={entries.length <= 12}>
              <summary class="small">List</summary>
              <ul class="defs">
                {#each entries as [n, r] (n)}
                  <li>
                    <button class="ref" onclick={() => showDecl(n)}>{n}</button>
                    <span class={"rv rv-" + r.state}>{r.state}</span>
                    {#each r.current as x}<span class="faint small"> by {x.by}{x.kind === "ai" ? " (AI)" : ""}</span>{/each}
                  </li>
                {/each}
              </ul>
            </details>
          </div>
        {/if}
      </section>
    {/each}

    {#if Object.keys(claim.decls || {}).length}
      {@const ds = Object.entries(claim.decls)}
      <section>
        <h2>Definitions ({ds.length})</h2>
        {#each ds as [n, d] (n)}
          {#if ds.length <= 40 || openDecl === n || showAll}
            <Decl {d} open={openDecl === n} onref={showDecl} />
          {/if}
        {/each}
        {#if ds.length > 40 && !showAll}
          <button class="more" onclick={() => (showAll = true)}>Show all {ds.length} declarations</button>
        {/if}
      </section>
    {/if}

    <section>
      <h2>Findings</h2>
      <Findings findings={claim.findings} />
    </section>

    <footer class="faint small">
      Release <code>{index.release}</code> · evidence <code title={index.evidence}>{index.evidence.slice(0, 12)}</code>
      {#if index.lean}· Lean {index.lean.lean}{/if}
      {#if index.project?.commit}· project <code>{index.project.commit.slice(0, 12)}</code>{index.project.dirty ? " (uncommitted changes)" : ""}{/if}
    </footer>
  </article>
{/if}

<style>
  .passport { display: flex; flex-direction: column; gap: 22px; }
  header h1 { font-family: var(--serif); font-size: 24px; font-weight: 600; margin: 2px 0 10px; }
  .full header h1 { font-size: 30px; }
  .title { font-weight: 450; }
  .eyebrow { margin: 0; color: var(--muted); font-size: 13px; }
  .note { margin: 8px 0 0; font-size: 14px; }
  .why { margin-top: 12px; padding: 8px 12px; border: 1px solid var(--border); border-left: 4px solid var(--st-open); border-radius: 8px; background: var(--surface); }
  .why summary { cursor: pointer; font-weight: 600; }
  .why ul { margin: 6px 0 2px; padding-left: 18px; }
  .why li { margin: 2px 0; }
  section h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin-bottom: 10px; }
  h3 { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .clause { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .chead { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
  .chead h2 { margin: 0 0 10px; }
  .state { font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted); }
  .s-proved, .s-stated { color: var(--st-proved); }
  .s-refuted { color: var(--st-refuted); }
  .s-open { color: var(--st-open); }
  .s-malformed { color: var(--st-malformed); }
  .src summary { cursor: pointer; color: var(--muted); font-size: 13px; margin-top: 8px; }
  .small { font-size: 13px; }
  .bad { color: var(--st-malformed); }
  .ok { color: var(--st-accepted); }
  .proof { margin: 14px 0 0; }
  .proof dt { font-size: 12px; color: var(--muted); }
  .proof dd { margin: 0 0 6px; }
  .regimes ul, .defs { list-style: none; padding: 0; margin: 0; }
  .regimes li, .defs li { padding: 3px 0; }
  .regimes .ok, .regimes .bad { font-size: 12px; margin-right: 6px; }
  .review { border-left: 3px solid var(--border); padding-left: 10px; margin: 8px 0; }
  .pill { font-size: 11px; padding: 0 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: 4px; }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 6px 0 0; }
  .rv { font-size: 12px; margin-left: 6px; }
  .rv-reviewed { color: var(--st-accepted); }
  .rv-author-reviewed { color: var(--st-proved); }
  .rv-pending, .rv-stale { color: var(--st-open); }
  .ref { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-family: var(--mono); font-size: 0.92em; }
  .more { margin-top: 6px; border: 1px solid var(--border); background: var(--surface); border-radius: 6px; padding: 4px 10px; cursor: pointer; }
  footer { border-top: 1px solid var(--border); padding-top: 12px; }
</style>
