<script>
  import Statement from "./Statement.svelte";
  import StatusChip from "./StatusChip.svelte";
  import LinkPicker from "./LinkPicker.svelte";
  import StepContext from "./StepContext.svelte";
  import { evidenceView } from "../lib/presentation.js";
  import { href, withQuery } from "../lib/route.svelte.js";
  import { STEP_VERDICTS } from "../lib/review.js";
  import { readingWords } from "../lib/coverage.js";

  // A proof step (an equation or passage of a printed proof) as a target of its own. `part`
  // chooses what is drawn: its own review beside the printed step ("finding"), the Lean that
  // establishes it and the formal route used instead ("lean"), or, on the enclosing result,
  // the list of its steps ("list"). Nothing here is the parent's: a step that no review covers
  // reads "not reviewed", whatever its parent's status.
  let { claim, index, part, onref = null, editable = false, busy = false, onlink = null, onroute = null } = $props();

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
</script>

{#if part === "finding" && st}
  <div class="finding" data-review={rv.state}>
    <p class="small kind">{UNIT[st.unit] || "Proof step"}{#if st.parent}{" of "}<a href={href(index.release, "read", claim.paper, st.parent.id)}>{st.parent.number || st.parent.id}</a>{/if}</p>
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
    {#if claim.context_tex}
      <StepContext text={claim.context_tex} cut={claim.context_cut} />
    {/if}
    {#if reviewHref}<p class="small"><a href={reviewHref}>Review this step</a></p>{/if}
  </div>
{:else if part === "lean" && st}
  <h3 class="sub">Lean that establishes this step</h3>
  {#if st.correspondence?.coverage || st.correspondence?.note}
    {@const cor = st.correspondence}
    <p class="small cov" data-coverage={cor.coverage || "note"}>{#if corWords}<strong>{corWords}</strong>{#if cor.basis === "reviewed_composition"}{" (Lean has not checked the combination)"}{/if}{#if cor.note}{". "}{/if}{/if}{cor.note}{#if cor.by}<span class="faint">{" — " + cor.by}</span>{/if}</p>
  {/if}
  {#each st.links as l (l.name)}
    <div class="block">
      <p class="decl"><code>{l.name}</code> <StatusChip record={l} small /></p>
      {#if l.statement}<Statement st={l.statement} {onref} compact />{/if}
      {#if editable}<button class="btn ghost" disabled={busy} onclick={() => onlink(st.links.filter((x) => x.name !== l.name).map((x) => x.name))}>Unlink</button>{/if}
    </div>
  {:else}
    <p class="muted small">No Lean declaration is linked as establishing this step.</p>
  {/each}
  {#if editable}<LinkPicker {index} disabled={busy} onpick={(name) => onlink([...st.links.map((x) => x.name), name])} />{/if}
  {#if st.route || editable}
    <h3 class="sub">Different formal route used instead</h3>
    {#if st.route?.note}<p class="small">{st.route.note}{#if st.route.by}<span class="faint">{" — " + st.route.by}</span>{/if}</p>{/if}
    {#each st.route?.links || [] as l (l.name)}
      <div class="block route">
        <p class="decl"><code>{l.name}</code> <StatusChip record={l} small /></p>
        {#if l.statement}<Statement st={l.statement} {onref} compact />{/if}
        {#if editable}<button class="btn ghost" disabled={busy} onclick={() => onroute(st.route.links.filter((x) => x.name !== l.name).map((x) => x.name))}>Remove</button>{/if}
      </div>
    {:else}
      <p class="muted small">No formal route is recorded for this step.</p>
    {/each}
    {#if st.route?.links?.length}<p class="faint small">This Lean reaches {st.parent?.number || "the enclosing result"} by another argument; it does not state this step.</p>{/if}
    {#if editable}<LinkPicker {index} disabled={busy} onpick={(name) => onroute([...(st.route?.links || []).map((x) => x.name), name])} />{/if}
  {/if}
{:else if part === "list" && claim.steps?.length}
  <section class="steps" aria-label="Proof steps">
    <h3 class="sub">Steps of its proof ({claim.steps.length})</h3>
    <ul>
      {#each claim.steps as s (s.id)}
        <li data-review={s.review}>
          <a href={href(index.release, "read", claim.paper, s.id)}>{s.number || s.id}</a>
          <span class="small">{evidenceView("step", { state: s.review }).word}</span>
          <span class="faint small">{s.linked.length ? "Lean: " + s.linked.join(", ") : s.route.length ? "formal route: " + s.route.join(", ") : "no Lean linked"}</span>
        </li>
      {/each}
    </ul>
  </section>
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
  .block { margin-bottom: 14px; }
  .block.route { border-left: 3px dashed var(--border); padding-left: 10px; }
  .decl { margin: 0 0 6px; overflow-wrap: anywhere; }
  .cov { border-left: 3px solid var(--border); padding-left: 10px; }
  .cov[data-coverage="full"] { border-left-color: var(--st-proved); }
  .steps ul { list-style: none; padding: 0; margin: 0; }
  .steps li { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; padding: 4px 0; border-bottom: 1px solid var(--border); }
  .btn { border: 1px solid var(--accent); background: transparent; color: var(--accent); border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 13px; margin-top: 8px; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .small { font-size: 13px; }
</style>
