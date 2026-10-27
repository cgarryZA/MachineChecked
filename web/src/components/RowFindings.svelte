<script>
  import Composition from "./Composition.svelte";
  import { findingView, rowWords } from "../lib/findings.js";

  // The findings at one row of the comparison (`findings.placeFindings`), and the correspondence
  // fields of the reviews of a whole proposition (`findings.reviewFields`), whose reviewer and full
  // text are in the audit details. A finding's
  // explanation is printed at the first row it concerns, with its source and basis once; a later
  // row names it. Each is attributed to its reading; a finding of the whole claim (`claim`) says
  // which requirement or clause it is on, when it names one. Nothing here is a status.
  //
  // `paired` is the reading the comparison's rows are paired with: its passages are already
  // beside the row, so a finding of that reading names them instead of printing them again.
  let { entries = [], notes = [], statements = {}, claimId = null, paired = null, claim = false, at = null } = $props();

  const views = $derived(entries.map((e) => ({ e, v: findingView(e, statements, claimId) })));
  const shown = (p, e) => p.text && !p.whole && !(paired && paired === e.set.id && !claim);
  const roleOf = (l) => (l.role ? l.role : l.state === "here" ? "the declaration as a whole" : null);
  const whereNow = { elsewhere: "not in this comparison", changed: "its statement changed since this was recorded",
                     missing: "the statement no longer has this part" };
</script>

{#if views.length || notes.length}
  <div class="row-findings" class:claim data-findings-at={at}>
    {#if claim}<p class="lbl">Findings on the whole claim</p>{/if}
    {#each notes as n, i (i)}
      <div class="finding legacy" data-review-field={n.spec} class:stale={!n.current}>
        <p class="small"><strong>Correspondence</strong> <span class="faint">· from a review of <code>{n.spec}</code>{n.kind === "ai" ? ", by an AI reviewer" : n.kind === "human" ? ", by a human reviewer" : ""}</span>{#if !n.current}<span class="warn">{" · a review of an earlier version of this proposition"}</span>{/if}</p>
        <p class="small text">{n.text}</p>
      </div>
    {/each}
    {#each views as { e, v } (e.set.id + "|" + v.id)}
      {#if e.first}
        <div class="finding" data-finding={v.id} data-set={e.set.id} data-tone={v.tone} data-state={v.state} class:stale={v.stale}>
          <p class="small head"><strong>{v.head}</strong>{#if v.state === "draft"}<span class="faint">{" · draft"}</span>{/if}</p>
          {#if v.difference?.words}<p class="small">{v.difference.words}.</p>{/if}
          {#if v.difference}
            {@const d = v.difference}
            <p class="small diff" data-feature={d.feature} data-outcome={d.outcome}>{#if d.paper}paper <code>{d.paper}</code>{/if}{#if d.lean}{d.paper ? "; " : ""}Lean <code>{d.lean}</code>{/if}{#if d.why}<span class="faint">{" · " + d.why}</span>{/if}{#if d.transport}<span class="faint">{" · transport inspected: " + d.transport}</span>{/if}{#if d.resolution}<span class="faint">{" · resolved by " + d.resolution.by + (d.resolution.text ? ": " + d.resolution.text : "")}</span>{/if}</p>
          {/if}
          {#if v.verdict}<p class="small">{v.verdict}.</p>{/if}
          {#if v.note}<p class="small text">{v.note}</p>{/if}
          {#if v.question}<p class="small"><span class="faint">Open question:</span> <span class="text">{v.question}</span></p>{/if}
          {#if v.requirement}
            <p class="small subject" data-requirement={v.requirement.local_id}><span class="faint">Paper:</span> <code>{v.requirement.local_id}</code>{#if v.requirement.form}{" "}<span class="form">{v.requirement.form}{v.requirement.binds?.length ? " " + v.requirement.binds.join(", ") : ""}{v.requirement.domain ? ` (${v.requirement.domain})` : ""}</span>{/if}{#if v.requirement.text}: <span class="text">{v.requirement.text}</span>{/if}{#if v.requirement.independent_of?.length}<span class="faint">{" · independent of " + v.requirement.independent_of.join(", ")}</span>{/if}{#if v.requirement.missing}<span class="faint">{" (no longer kept)"}</span>{/if}{#if v.passages.length}<span class="faint">{" · " + v.passages.map((p) => p.where + (p.role && p.role !== "the statement" ? ` (${p.role}${p.scope ? ", applies to " + p.scope : ""})` : "")).join("; ")}</span>{/if}</p>
            {#each v.passages.filter((p) => shown(p, e)) as p (p.id)}<pre class="frag">{p.text}</pre>{/each}
          {:else if v.clause}
            <p class="small subject"><span class="faint">On:</span> <span class="text">{v.clause}</span></p>
          {/if}
          {#each v.lean as l, i (i)}
            <p class="small target" data-target-state={l.state}><span class="faint">Lean:</span> {#if l.text}<code>{l.text}</code>{" in "}{/if}<code>{l.decl}</code>{#if roleOf(l)}<span class="role">{", " + roleOf(l)}</span>{/if}<span class="faint">{" · " + l.relation}</span>{#if whereNow[l.state]}<span class="warn">{" · " + whereNow[l.state]}</span>{:else if l.stale}<span class="warn">{" · the association changed since it was recorded"}</span>{/if}</p>
          {/each}
          {#each v.lines as line}<p class="small" data-line={line.label}><span class="faint">{line.label}:</span> {line.names?.join(", ") || ""}{line.names?.length && line.text ? ". " : ""}<span class="text">{line.text || ""}</span>{#if line.note} <span class="faint">{line.note}</span>{/if}</p>{/each}
          {#if v.recorded}<p class="small faint" data-line="recorded">{v.recorded}</p>{/if}
          <p class="small faint by">{v.from === "workspace" ? "Recorded in " + e.set.who : "By " + e.set.who + (v.mode ? ", " + v.mode : "")}{#if v.stale}<span class="warn">{" · what it rests on changed since it was recorded"}</span>{:else if v.unchecked}<span data-currency="unchecked">{" · not known to be current"}</span>{/if}</p>
          {#if v.at || v.evidence.length || v.composition || v.counterexamples.length || v.supersedes || v.why.length}
            <details class="more">
              <summary class="small faint">Details</summary>
              <p class="small faint">Finding <code>{v.id}</code>{v.by ? " by " + v.by : ""}{v.at ? ", submitted " + v.at : ""}{e.set.id ? " · " + e.set.id.replace(/^[a-z]+:/, "workspace ") : ""}</p>
              {#if v.why.length}<p class="small faint">Changed: {v.why.join("; ")}.</p>{/if}
              {#if v.supersedes}<p class="small faint">Supersedes {v.supersedes}{v.reason ? ": " + v.reason : ""}</p>{/if}
              {#each v.evidence as ev (ev.id)}<p class="small faint">Evidence: <code>{ev.text}</code> ({ev.role}{ev.stale ? ", changed since it was recorded" : ""})</p>{/each}
              {#if v.composition}<Composition c={v.composition} evidence={e.set.evidence} />{/if}
              {#each v.counterexamples as c (c.id)}<p class="small faint">Counterexample <code>{c.id}</code>{c.analysis?.standing_text ? ": " + c.analysis.standing_text : ""}</p>{/each}
            </details>
          {/if}
        </div>
      {:else}
        <p class="small faint also" data-finding-ref={v.id} data-set={e.set.id}>Also concerns this row: “{v.head}”, by {e.set.who}, explained at {rowWords(statements, e.rows[0])}.</p>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .row-findings { margin: 6px 0 4px; display: flex; flex-direction: column; gap: 6px; }
  .row-findings.claim { margin: 0; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 0; }
  .finding { border-left: 3px solid var(--accent); padding: 2px 0 2px 10px; }
  .finding[data-tone="warning"] { border-left-color: var(--tier-warning); }
  .finding[data-tone="full"] { border-left-color: var(--st-proved); }
  .finding.legacy { border-left-color: var(--border); }
  .finding.stale { border-left-style: dashed; }
  .finding p { margin: 2px 0; overflow-wrap: anywhere; }
  .also { margin: 0; }
  .text { white-space: pre-wrap; }
  .form { font-style: italic; }
  .warn { color: var(--tier-warning); }
  .frag { margin: 2px 0; padding: 4px 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
  .more > summary { cursor: pointer; }
  .more p { margin: 2px 0; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  code { font-size: 12px; }
</style>
