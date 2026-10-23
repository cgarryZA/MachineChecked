<script>
  import { listWorkspaces, openWorkspace, showWorkspace, updateWorkspace, suggestContext, newId,
    rememberedWorkspace, rememberWorkspace, humanId } from "../lib/workspace.js";
  import { href } from "../lib/route.svelte.js";
  import { compositionView, findingCoverageView, recordedBasisText } from "../lib/coverage.js";
  import Composition from "./Composition.svelte";

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

  const here = $derived(view?.claims?.[claim.id] || { evidence: [], findings: [], questions: [], compositions: [] });
  const reading = $derived(here.reading || { requirements: [], witnesses: [], alignments: [], questions: [] });

  // The breakdown of the claim into requirements (`requirements.py`): the words below describe
  // a fragment's role and origin, and a witness's scope, as the engine records them.
  const FORMS = ["statement", "object", "assumption", "conclusion", "condition", "for every",
    "there is", "and", "or", "not", "implies", "constant dependence", "definition", "other"];
  const ROLE = { statement: "the statement", "quantifier domain": "domain of a quantifier",
    "constant dependence": "allowed dependence of a constant", "standing assumption": "standing assumption",
    definition: "definition used", "earlier choice": "choice made earlier", "cited result": "result cited",
    context: "context", "later use": "later use", "proposed correction": "proposed correction" };
  const ORIGIN = { printed: "printed for this claim", inferred: "attached by inference", correction: "proposed correction" };
  const SCOPE = { produced: "the claim produces it", assumed: "assumed by the claim",
    denied: "the claim says there is none", alternative: "inside one alternative" };
  let rqId = $state("");
  let rqForm = $state("condition");
  let rqParent = $state("");
  let rqText = $state("");
  let rqBinds = $state("");
  let rqPassage = $state(true);
  let removing = $state(null);
  let why = $state("");
  const binding = $derived(["for every", "there is", "constant dependence"].includes(rqForm));
  const alignments = $derived(Object.fromEntries((reading.alignments || []).map((a) => [a.id, a])));

  // Estimates (`estimates.py`): each requirement's printed and corrected readings with their
  // counterexamples and certificates, the differences recorded on it, and computed hints.
  const OUTCOME = { open: "not yet decided", difference: "a difference", resolved: "resolved", "no difference": "no difference" };
  const est = $derived(reading.estimates || { estimates: [], differences: [], resolved: [], hints: [], inherited: [] });
  const estimatesFor = (lid) => (est.estimates || []).filter((e) => e.requirement === lid);
  const differencesFor = (lid) => [...(est.differences || []), ...(est.resolved || [])].filter((d) => d.requirement === lid);
  const changed = (x) => x?.currency?.state === "stale";
  function findingHead(f, cv) {
    if (cv?.headline) return cv.headline;
    if (f.verdict) return "The printed step: " + f.verdict;
    if (f.difference) return `A ${f.difference.feature} difference: ${OUTCOME[f.difference.outcome]}`;
    return "No coverage given";
  }

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

  async function addRequirement() {
    const binds = binding ? rqBinds.split(",").map((b) => b.trim()).filter(Boolean) : [];
    const ops = [{ op: "put", record: { id: newId("r"), kind: "requirement", claim: claim.id,
      local_id: rqId.trim(), form: rqForm, text: rqText, ...(rqParent ? { parent: rqParent } : {}),
      ...(binds.length ? { binds } : {}) } }];
    if (rqPassage) ops.push({ op: "put", record: { id: newId("p"), kind: "fragment", claim: claim.id,
      requirement: rqId.trim(), role: "statement", passage: { claim: claim.id } } });
    if (await run(ops)) { rqId = ""; rqText = ""; rqBinds = ""; rqParent = ""; }
  }

  // A put replaces a fragment's content: its location is sent as it is, so it keeps the text
  // it was attached with.
  function fragmentRecord(f, change) {
    const keep = ["id", "kind", "claim", "requirement", "role", "origin", "scope", "note", "suggestion", "state", "why_removed"];
    const rec = Object.fromEntries(keep.filter((k) => f[k] !== undefined).map((k) => [k, f[k]]));
    if (f.region) rec.region = Object.fromEntries(["paper", "file", "start_line", "end_line", "start_column", "end_column"]
      .filter((k) => f.region[k] !== undefined).map((k) => [k, f.region[k]]));
    if (f.passage) rec.passage = { claim: f.passage.claim };
    return { op: "put", base_rev: f.rev, record: { ...rec, ...change } };
  }
  const accept = (f) => run([fragmentRecord(f, { state: "accepted" })]);
  async function remove(f) {
    if (await run([fragmentRecord(f, { state: "removed", why_removed: why })])) { removing = null; why = ""; }
  }
  async function suggestFor(r) {
    busy = true; error = null;
    try {
      await suggestContext(wsId, claim.id, r.local_id);
      await refresh();
    } catch (e) { error = String(e.message || e); }
    busy = false;
  }
  function where(f) {
    if (f.passage) return f.passage.claim === claim.id ? "this claim's passage" : `the passage of ${f.passage.claim}`;
    const r = f.region || {};
    return `${r.file}:${r.start_line}${r.end_line && r.end_line !== r.start_line ? "–" + r.end_line : ""}`;
  }
  function targetText(t) {
    const part = t.conclusion ? "the conclusion" : "var" in t ? "variable" : "binder" in t ? "hypothesis or type" : "at" in t ? "sub-term" : null;
    return t.decl + (part ? ` (${part}${t.target ? ": " + t.target : ""})` : "");
  }

  // A finding that rests on a composition reads as that composition: its argument is shown
  // with the composition, under Compositions. Its own bridge reads as the engine checked it.
  function findingView(f) {
    if (!f.composition) return findingCoverageView(f);
    const c = (here.compositions || []).find((x) => x.id === f.composition);
    return { headline: compositionView({ coverage: f.coverage, basis: f.basis, bridge_check: c?.bridge_check }).headline, lines: [] };
  }

  function refText(r) {
    if (r.certificate) return `${r.certificate.theorem}, certificate for ${r.certificate.target}`;
    if (r.fact) return `${r.fact.name || r.fact.head || "a fact"} : ${r.fact.type}, inside the proof of ${r.fact.decl}`;
    if (r.app) return `${r.app.callee} applied in ${r.app.caller}`;
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
        {@const cv = findingView(f)}
        <div class="item" data-kind="finding" data-state={f.state} class:old={!f.in_force}>
          <p class="small"><strong>{findingHead(f, cv)}</strong>
            <span class="faint">· {f.in_force ? (f.state === "submitted" ? "submitted" : "draft") : "superseded"} · {f.created_by}{f.requirement ? ` · on ${f.requirement}` : ""}</span>
            {#if f.currency?.state === "stale"}<span class="stale"> · evidence changed since</span>{/if}</p>
          {#each cv?.lines || [] as line}<p class="small" data-line={line.label}><span class="faint">{line.label}:</span> {line.names?.join(", ") || ""}{line.names?.length && line.text ? ". " : ""}<span class="text">{line.text || ""}</span>{#if line.note} <span class="faint">{line.note}</span>{/if}</p>{/each}
          {#if f.composition}<p class="small faint">Rests on composition {f.composition}{f.recorded_basis ? `; recorded as ${f.recorded_basis === "checked_bridge" ? "a checked bridge" : f.recorded_basis}, its bridge is not checked now` : ""}.</p>
          {:else if recordedBasisText(f)}<p class="small faint" data-line="recorded">{recordedBasisText(f)}</p>{/if}
          {#if f.note}<p class="small text">{f.note}</p>{/if}
          {#if f.supersedes}<p class="faint small">Supersedes {f.supersedes}: {f.reason}</p>{/if}
          {#if f.state === "draft"}<button class="act" disabled={busy} onclick={() => submit(f)}>Submit</button>{/if}
        </div>
      {/each}
      {#if here.compositions?.length}
        <div class="compositions" aria-label="Compositions">
          <h3>Compositions</h3>
          <p class="faint small">Arguments that combine several results, recorded with <code>machinechecked workspace update</code>.</p>
          {#each here.compositions as c (c.id)}<Composition {c} evidence={here.evidence} />{/each}
        </div>
      {/if}
      {#if reading.requirements.length || reading.alignments.length}
        <div class="reading" aria-label="Requirements">
          <h3>Requirements</h3>
          <p class="faint small">Your reading of what the claim demands, each with the passages of the paper it comes from. Lean has not checked these associations.</p>
          {#each reading.requirements as r (r.id)}
            <div class="req" data-req={r.local_id} style:margin-left="{r.depth * 16}px">
              <p class="small"><code>{r.local_id}</code> <span class="form">{r.form}{r.binds?.length ? " " + r.binds.join(", ") : ""}{r.domain ? ` (${r.domain})` : ""}</span>: <span class="text">{r.text}</span>
                {#if r.independent_of?.length}<span class="faint"> · independent of {r.independent_of.join(", ")}</span>{/if}
                {#if r.depends_on?.length}<span class="faint"> · may depend on {r.depends_on.join(", ")}</span>{/if}
                {#if r.origin === "correction"}<span class="faint"> · added by a correction of {r.corrects}; the printed requirement stays</span>{/if}
                {#if r.currency?.state === "stale"}<span class="stale"> · its source or Lean changed since</span>{/if}</p>
              {#each r.fragments.governing as f (f.id)}
                <div class="frag" data-role={f.role}>
                  {#if f.region?.text}<pre class="src">{f.region.text}</pre>{/if}
                  <p class="faint small">{ROLE[f.role]} · {where(f)} · {ORIGIN[f.origin]}{f.scope ? ` · applies to ${f.scope}` : ""} · by {f.created_by}{f.suggestion ? " (suggested by MachineChecked)" : ""}
                    {#if f.currency?.state === "stale"}<span class="stale"> · the passage changed since</span>{/if}
                    · <button class="link" disabled={busy} onclick={() => { removing = f.id; why = ""; }}>Remove</button></p>
                  {#if removing === f.id}<p class="small"><input class="why" bind:value={why} placeholder="Why it does not govern this requirement" aria-label="Why remove it" />
                    <button class="act" disabled={busy || !why.trim()} onclick={() => remove(f)}>Remove passage</button></p>{/if}
                </div>
              {/each}
              {#each r.fragments.later_uses as f (f.id)}
                <div class="frag use" data-role="later use">
                  {#if f.region?.text}<pre class="src">{f.region.text}</pre>{/if}
                  <p class="faint small">Used later at {where(f)}: a use of the result; this reading is unchanged · by {f.created_by}</p>
                </div>
              {/each}
              {#each r.fragments.proposed as f (f.id)}
                <div class="frag proposed" data-role={f.role}>
                  {#if f.region?.text}<pre class="src">{f.region.text}</pre>{/if}
                  <p class="small"><span class="faint">Suggested: {ROLE[f.role]} · {where(f)}{f.suggestion ? ` (${f.suggestion.rule})` : ""}</span>
                    <button class="act" disabled={busy} onclick={() => accept(f)}>Accept</button>
                    <button class="act" disabled={busy} onclick={() => { removing = f.id; why = ""; }}>Remove</button></p>
                  {#if removing === f.id}<p class="small"><input class="why" bind:value={why} placeholder="Why it does not govern this requirement" aria-label="Why remove it" />
                    <button class="act" disabled={busy || !why.trim()} onclick={() => remove(f)}>Remove passage</button></p>{/if}
                </div>
              {/each}
              {#if r.fragments.removed.length}
                <details class="removed"><summary class="faint small">Removed passages ({r.fragments.removed.length})</summary>
                  {#each r.fragments.removed as f (f.id)}<p class="faint small">{where(f)} ({ROLE[f.role]}), removed by {f.state_by}: {f.why_removed}</p>{/each}
                </details>
              {/if}
              {#each r.alignments as aid}
                {@const a = alignments[aid]}
                {#if a}<p class="small lean" data-alignment={a.id}><span class="faint">Lean:</span> {a.lean.map(targetText).join("; ")} <span class="faint">· {a.relation} · recorded by {a.created_by}</span>{#if a.currency?.state === "stale"}<span class="stale"> · the Lean changed since</span>{/if}</p>{/if}
              {/each}
              {#each r.questions as q}<p class="small question">Question: {q}</p>{/each}
              {#each estimatesFor(r.local_id) as e (e.requirement)}
                {#each e.readings as rd (rd.corrections.join(","))}
                  <div class="estimate" data-reading={rd.printed ? "printed" : rd.corrections.join(",")}>
                    <p class="small"><span class="faint">{rd.printed ? "Read as printed" : `Read with the correction ${rd.corrections.join(", ")}`}:</span> <span class="text">{rd.obligation.text}</span></p>
                    {#each rd.obligation.order.filter((o) => o.quantifier === "there is") as o (o.var)}
                      <p class="faint small">{o.var} may depend on {o.may_depend_on.length ? o.may_depend_on.join(", ") : "nothing chosen before it"}{o.independent_of.length ? `; independent of ${o.independent_of.join(", ")}` : ""}</p>
                    {/each}
                    {#each rd.counterexamples as c (c.id)}
                      <div class="cx" data-cx={c.id} data-standing={c.analysis.standing}>
                        <p class="small"><strong>Counterexample</strong> <span class="faint">· {c.analysis.standing_text} · {c.created_by}</span>{#if changed(c)}<span class="stale"> · the reading or its evidence changed since</span>{/if}</p>
                        <p class="small text">{c.analysis.shows}</p>
                        {#each c.analysis.problems as q}<p class="small question">{q}</p>{/each}
                        {#each c.analysis.open_obligations as o}<p class="small question">Not yet shown: {o}</p>{/each}
                        {#if c.analysis.samples_note}<p class="faint small">{c.analysis.samples} sample(s). {c.analysis.samples_note}</p>{/if}
                        {#each c.certificates as k (k.evidence)}<p class="small cert">{k.scope}{#if changed(k)}<span class="stale"> · changed since</span>{/if}</p>{/each}
                      </div>
                    {/each}
                    {#each rd.findings.filter((f) => f.verdict) as f (f.id)}<p class="small verdict">The printed step: <strong>{f.verdict}</strong> <span class="faint">· {f.state}</span>{#if changed(f)}<span class="stale"> · its evidence changed since</span>{/if}</p>{/each}
                    {#each rd.certificates as k (k.evidence)}<p class="small cert">{k.scope}{#if changed(k)}<span class="stale"> · changed since</span>{/if}</p>{/each}
                    {#each rd.specialisations as t}<p class="faint small">To try: {t.try} (from {t.rule})</p>{/each}
                  </div>
                {/each}
              {/each}
              {#each differencesFor(r.local_id) as d (d.finding)}
                <p class="small diff" data-feature={d.feature} data-outcome={d.outcome}><span class="faint">{d.feature[0].toUpperCase() + d.feature.slice(1)}, {OUTCOME[d.outcome]}:</span> paper <code>{d.paper}</code>{#if d.lean}; Lean <code>{d.lean}</code>{/if}{#if d.transport}<span class="faint">{` · transport inspected: ${d.transport}`}</span>{/if}{#if d.resolution}<span class="faint">{` · resolved by ${d.resolution.by}: ${d.resolution.text}`}</span>{/if}{#if d.why}<span class="faint">{` · ${d.why}`}</span>{/if}</p>
              {/each}
              <p class="small"><button class="link" disabled={busy} onclick={() => suggestFor(r)}>Suggest nearby context</button></p>
            </div>
          {/each}
          {#each reading.witnesses as w}
            <p class="small witness"><span class="faint">Witness {w.binds.join(", ") || w.requirement}:</span> {SCOPE[w.scope]}{w.after.length ? `; chosen after ${w.after.join(", ")}` : ""}{w.before.length ? `; chosen before ${w.before.join(", ")}` : ""}{w.independent_of.length ? `; independent of ${w.independent_of.join(", ")}` : ""}</p>
          {/each}
          {#each est.inherited || [] as h}
            <p class="small inherited" data-binder={h.binder}>{h.decl} assumes <code>{h.lean}</code>: inherited from {h.from} ({h.requirement})</p>
          {/each}
          {#each est.hints || [] as h}
            <p class="small hint" data-binder={h.binder}>{h.text} <span class="faint">(computed hint: inspect it)</span></p>
          {/each}
          {#each reading.alignments.filter((a) => !a.requirements.length) as a (a.id)}
            <p class="small lean" data-alignment={a.id}><span class="faint">Lean only ({a.relation}):</span> {a.lean.map(targetText).join("; ")} <span class="faint">· recorded by {a.created_by}</span>{#if a.note} <span class="text">{a.note}</span>{/if}</p>
          {/each}
        </div>
      {/if}

      {#if here.evidence.length}
        <p class="small faint">Evidence: {#each here.evidence as e, i (e.id)}{i ? ", " : ""}<code>{refText(e.ref)}</code> ({e.role}{e.ref?.fact ? ", " + e.ref.fact.basis : ""}{e.currency?.state === "stale" ? ", changed since" : ""}){/each}</p>
      {/if}

      <details class="add">
        <summary>Record a finding</summary>
        <p class="small"><label>Coverage <select bind:value={choice} aria-label="Coverage">{#each Object.entries(CHOICES) as [k, c]}<option value={k}>{c.label}</option>{/each}</select></label>
          {#if claim.links?.length}<label><input type="checkbox" bind:checked={cite} /> cite the linked declarations</label>{/if}</p>
        {#if picked.coverage === "unresolved"}<textarea bind:value={openQ} rows="2" placeholder="The open question" aria-label="Open question"></textarea>
          <textarea bind:value={decide} rows="2" placeholder="What would decide it" aria-label="What would decide it"></textarea>{/if}
        {#if picked.basis === "reviewed_composition"}<textarea bind:value={argument} rows="3" placeholder="How the linked results combine to give each clause" aria-label="Argument"></textarea>
          <p class="faint small">Lean has not checked this combination. Next step: state the combination as one Lean result.</p>{/if}
        <textarea bind:value={note} rows="3" placeholder="What establishes each clause, or what differs" aria-label="Note"></textarea>
        <button class="act" disabled={busy || (picked.coverage === "unresolved" && !openQ.trim())} onclick={addFinding}>Save draft</button>
      </details>
      <details class="add">
        <summary>Add a requirement</summary>
        <p class="small"><input class="who" bind:value={rqId} placeholder="r1" aria-label="Local id" />
          <label>Form <select bind:value={rqForm}>{#each FORMS as f}<option value={f}>{f}</option>{/each}</select></label>
          <label>Inside <select bind:value={rqParent}><option value="">(top level)</option>{#each reading.requirements as r}<option value={r.local_id}>{r.local_id}</option>{/each}</select></label></p>
        {#if binding}<p class="small"><input class="who" bind:value={rqBinds} placeholder="ε, C" aria-label="Variables" /> <span class="faint">the variables it introduces</span></p>{/if}
        <textarea bind:value={rqText} rows="2" placeholder="What the claim demands, in your words" aria-label="Requirement"></textarea>
        <p class="small"><label><input type="checkbox" bind:checked={rqPassage} /> its source is this claim's passage</label></p>
        <button class="act" disabled={busy || !rqId.trim() || !rqText.trim()} onclick={addRequirement}>Save requirement</button>
        <p class="faint small">Other passages (the sentence that sets a quantifier's domain, a standing assumption) are attached with “Suggest nearby context” or <code>machinechecked workspace update</code>.</p>
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
  .reading h3, .compositions h3 { font-size: 14px; margin: 12px 0 2px; }
  .req { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 6px 0; }
  .req p { margin: 2px 0; }
  .form { font-style: italic; }
  .frag { margin: 4px 0 4px 8px; }
  .frag.use { opacity: 0.8; }
  .frag.proposed { border-left: 2px dashed var(--border); padding-left: 6px; }
  .src { margin: 2px 0; padding: 4px 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
  .why { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 22em; max-width: 100%; }
  .question { color: var(--tier-warning); }
  .estimate { margin: 4px 0 4px 8px; padding-left: 6px; border-left: 2px solid var(--border); }
  .cx { margin: 4px 0; }
  .hint { color: var(--tier-warning); }
</style>
