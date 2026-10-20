<script>
  import { loadWork } from "../lib/data.js";
  import { coverageView, compositionView } from "../lib/coverage.js";
  import Composition from "./Composition.svelte";

  // The workspace records the audit publishes for this claim (`published_work.py`): each
  // auditor's requirements, the passages accepted as governing them, the alignments with Lean
  // and the submitted findings with their evidence and compositions. They are shown as recorded, attributed and
  // read-only; the claim's status comes from the evidence, never from them.
  let { claim } = $props();

  let work = $state(null);
  let error = $state(null);
  $effect(() => {
    let current = true;
    work = null; error = null;
    loadWork(claim).then((w) => { if (current) work = w; }).catch((e) => { if (current) error = String(e.message || e); });
    return () => { current = false; };
  });

  const ROLE = { statement: "the statement", "quantifier domain": "domain of a quantifier",
    "constant dependence": "allowed dependence of a constant", "standing assumption": "standing assumption",
    definition: "definition used", "earlier choice": "choice made earlier", "cited result": "result cited",
    context: "context", "later use": "later use", "proposed correction": "proposed correction" };
  const ORIGIN = { printed: "printed for this claim", inferred: "attached by inference", correction: "proposed correction" };
  const MODE = { informed: "informed investigation", independent: "independent review" };
  const STALE = "changed since it was recorded";

  function who(r) {
    if (r.kind === "model") return "the AI model " + (r.model || r.id);
    return (r.name || r.id || "an unnamed auditor") + (r.identity === "self-declared" ? " (self-declared)" : "");
  }
  function where(f) {
    if (f.passage) return f.passage.claim === claim.id ? "this claim's passage" : `the passage of ${f.passage.claim}`;
    const r = f.region || {};
    if (!r.file) return "a passage of the paper (its text is not published)";
    return `${r.file}:${r.start_line}${r.end_line && r.end_line !== r.start_line ? "–" + r.end_line : ""}`;
  }
  function targetText(t) {
    const part = t.conclusion ? "the conclusion" : "var" in t ? "variable" : "binder" in t ? "hypothesis or type" : "at" in t ? "sub-term" : null;
    return t.decl + (part ? ` (${part}${t.target ? ": " + t.target : ""})` : "");
  }
  function refText(r) {
    if (r?.app) return `${r.app.callee} applied in ${r.app.caller}`;
    if (r?.fact) return `${r.fact.name || r.fact.head || "a fact"}${r.fact.type ? " : " + r.fact.type : ""}, inside the proof of ${r.fact.decl} (${r.fact.basis})`;
    if (r?.decl) return r.decl;
    if (r?.source) return r.source.file ? r.source.file + (r.source.line ? ":" + r.source.line : "") : "a Lean source location";
    return r?.paper?.quote ? `“${r.paper.quote}”` : "a passage of the paper";
  }
  const day = (t) => (typeof t === "string" ? t.slice(0, 10) : "");
  const stale = (x) => x?.currency?.state === "stale";
  const governing = (rd, lid) => rd.fragments.filter((f) => f.requirement === lid && f.role !== "later use");
  const uses = (rd, lid) => rd.fragments.filter((f) => f.requirement === lid && f.role === "later use");
  const aligned = (rd, lid) => rd.alignments.filter((a) => (a.requirements || []).includes(lid));
  const cited = (rd, f) => (f.evidence || []).map((id) => rd.evidence.find((e) => e.id === id)).filter(Boolean);
  const view = (rd, f) => {
    // A finding that rests on a composition reads as that composition, shown below it.
    const c = f.composition && (rd.compositions || []).find((x) => x.id === f.composition);
    if (c) return { headline: compositionView({ coverage: f.coverage, basis: f.basis, bridge_check: c.bridge_check }).headline, lines: [] };
    return coverageView({ ...f, refs: cited(rd, f).map((e) => e.ref?.decl).filter(Boolean) });
  };
</script>

{#if work?.readings?.length}
  <section class="published-work" aria-label="Auditors' readings">
    <h2>Auditors' readings</h2>
    <p class="faint small">What each auditor recorded for this claim and published with the audit. Lean has not checked these associations; the status comes from the evidence.</p>
    {#each work.readings as rd (rd.workspace)}
      <div class="reading" data-workspace={rd.workspace}>
        <p class="small by">Reading by <strong>{who(rd.reviewer || {})}</strong> <span class="faint">· {MODE[rd.mode] || rd.mode}</span></p>
        {#each rd.findings as f (f.id)}
          {@const cv = view(rd, f)}
          <div class="item" data-kind="finding" class:old={!f.in_force}>
            <p class="small"><strong>{cv?.headline || "No coverage given"}</strong>
              <span class="faint">· {f.in_force ? "submitted" : "superseded"} {day(f.submitted_at)} by {f.created_by}{f.requirement ? ` · on ${f.requirement}` : ""}</span>
              {#if stale(f)}<span class="stale"> · its evidence {STALE}</span>{/if}</p>
            {#each cv?.lines || [] as line}<p class="small" data-line={line.label}><span class="faint">{line.label}:</span> {line.names?.join(", ") || ""}{line.names?.length && line.text ? ". " : ""}<span class="text">{line.text || ""}</span>{#if line.note} <span class="faint">{line.note}</span>{/if}</p>{/each}
            {#if f.note}<p class="small text">{f.note}</p>{/if}
            {#each (rd.compositions || []).filter((c) => c.id === f.composition) as c (c.id)}<Composition {c} evidence={rd.evidence} />{/each}
            {#if f.supersedes}<p class="faint small">Supersedes {f.supersedes}{f.reason ? `: ${f.reason}` : ""}</p>{/if}
            {#if cited(rd, f).length}<p class="faint small">Evidence: {#each cited(rd, f) as e, i (e.id)}{i ? ", " : ""}<code>{refText(e.ref)}</code> ({e.role}{stale(e) ? ", " + STALE : ""}){/each}</p>{/if}
          </div>
        {/each}
        {#if rd.requirements.length}
          <h3>Requirements</h3>
          {#each rd.requirements as r (r.id)}
            <div class="req" data-req={r.local_id} style:margin-left="{(r.depth || 0) * 16}px">
              <p class="small"><code>{r.local_id}</code> <span class="form">{r.form}{r.binds?.length ? " " + r.binds.join(", ") : ""}</span>: <span class="text">{r.text}</span>
                {#if r.independent_of?.length}<span class="faint"> · independent of {r.independent_of.join(", ")}</span>{/if}
                {#if r.origin === "correction"}<span class="faint"> · added by a correction of {r.corrects}; the printed requirement stays</span>{/if}
                {#if stale(r)}<span class="stale"> · its source or Lean {STALE}</span>{/if}</p>
              {#each governing(rd, r.local_id) as f (f.id)}
                <div class="frag" data-role={f.role}>
                  {#if f.region?.text}<pre class="src">{f.region.text}</pre>{/if}
                  <p class="faint small">{ROLE[f.role] || f.role} · {where(f)} · {ORIGIN[f.origin] || f.origin}{f.scope ? ` · applies to ${f.scope}` : ""} · accepted by {f.state_by || f.created_by}{f.suggestion ? " (suggested by MachineChecked)" : ""}{#if stale(f)}<span class="stale"> · the passage {STALE}</span>{/if}</p>
                </div>
              {/each}
              {#each uses(rd, r.local_id) as f (f.id)}
                <div class="frag use" data-role="later use">
                  {#if f.region?.text}<pre class="src">{f.region.text}</pre>{/if}
                  <p class="faint small">Used later at {where(f)}: a use of the result; this reading is unchanged · by {f.created_by}</p>
                </div>
              {/each}
              {#each aligned(rd, r.local_id) as a (a.id)}
                <p class="small lean" data-alignment={a.id}><span class="faint">Lean:</span> {a.lean.map(targetText).join("; ")} <span class="faint">· {a.relation} · recorded by {a.created_by}</span>{#if a.note} <span class="text">{a.note}</span>{/if}{#if stale(a)}<span class="stale"> · the Lean {STALE}</span>{/if}</p>
              {/each}
            </div>
          {/each}
        {/if}
        {#each rd.alignments.filter((a) => !(a.requirements || []).length) as a (a.id)}
          <p class="small lean" data-alignment={a.id}><span class="faint">Lean only ({a.relation}):</span> {a.lean.map(targetText).join("; ")} <span class="faint">· recorded by {a.created_by}</span>{#if a.note} <span class="text">{a.note}</span>{/if}{#if stale(a)}<span class="stale"> · the Lean {STALE}</span>{/if}</p>
        {/each}
      </div>
    {/each}
  </section>
{:else if error}
  <p class="faint small">The auditors' readings of this claim could not be loaded: {error}</p>
{/if}

<style>
  .published-work { margin-top: 24px; padding-top: 12px; border-top: 1px solid var(--border); }
  .published-work h2 { font-size: 15px; margin: 0 0 6px; }
  .published-work h3 { font-size: 14px; margin: 10px 0 2px; }
  .reading { margin: 10px 0; }
  .by { margin: 4px 0; }
  .item { border-left: 3px solid var(--accent); padding: 2px 0 2px 10px; margin: 8px 0; }
  .item.old { border-left-color: var(--border); opacity: 0.7; }
  .item p, .req p { margin: 2px 0; }
  .req { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 6px 0; }
  .text { white-space: pre-wrap; }
  .form { font-style: italic; }
  .stale { color: var(--tier-warning); }
  .frag { margin: 4px 0 4px 8px; }
  .frag.use { opacity: 0.8; }
  .src { margin: 2px 0; padding: 4px 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
