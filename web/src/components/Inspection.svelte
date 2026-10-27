<script>
  import Decl from "./Decl.svelte";
  import Application from "./Application.svelte";
  import LeanText from "./LeanText.svelte";
  import PaperStatement from "./PaperStatement.svelte";
  import { loadClaim, loadSearch, shownClaim, projectClaims, canEdit, askUses } from "../lib/data.js";
  import { proofFacts } from "../lib/workspace.js";
  import { itemOf, facts, applications, workspace } from "../lib/inspect.svelte.js";
  import { propertyStanding } from "../lib/carried.js";
  import { independent, usersSide } from "../lib/comparison.js";

  // One inspection beside a comparison row: a declaration, a property carried by an object's
  // type, a fact inside a proof, an application of a declaration, or a saved piece of evidence.
  // The trail's panel (`crumbs`) leads back through what was opened; a pinned panel stays where it
  // is while another reference is opened. `extra` draws a kind the comparison's controller owns
  // (the audit's details). The panel names what it shows and where it comes from; it changes
  // nothing.
  let { index, token, mode = "reading", claimId = null, decls = {}, statements = {}, crumbs = null,
        pinnable = true, pinned = false, onpin = null, onclose = null, onback = null, onref = null,
        labelOf = (t) => t, extra = null } = $props();

  const item = $derived(itemOf(token));
  const local = $derived(canEdit(index));
  const blind = $derived(independent(mode));
  let panel = $state();

  // The definition claim of the paper that a declaration states, if one links it (another claim
  // than this one): its passage is shown above the Lean definition. An association a person made,
  // so not in an independent stage.
  async function paperOf(name) {
    if (blind) return null;
    const search = await loadSearch(index).catch(() => ({ claims: [], decls: [] }));
    const ids = search.decls?.find((d) => d.name === name)?.claims || [];
    const linked = (search.claims || []).filter((c) => ids.includes(c.id) && (c.lean || []).includes(name)).map((c) => c.id);
    const meta = projectClaims(index).find((c) => linked.includes(c.id) && c.kind === "definition" && c.id !== claimId);
    const raw = meta && (await loadClaim(index, meta.id).catch(() => null));
    const rec = raw && shownClaim(raw);
    return rec && (rec.anchor?.begin || rec.excerpt?.ready) ? rec : null;
  }

  // A property, from the statement that carries it.
  const standing = $derived(item.kind === "property" ? propertyStanding(statements[item.spec], item.id) : null);
  const short = (n) => (n || "").split(".").pop();
  const STANDS = {
    given: (o) => `A field of the given object ${o}: part of what the statement is given, carried by its type.`,
    produced: (o) => `A field of the object ${o} the statement produces: producing ${o} establishes it.`,
    states: (o) => `An input condition: what the assumption ${o} states, field by field.`,
    inside: (o) => `A field of ${o}, an object inside an assumption: it holds there, not as a fact the statement is given.`,
    local: (o) => `A field of ${o} within the clause that contains it: the statement neither gives nor produces ${o}.`,
  };

  // A fact inside a proof, as Lean last gave it in this page, or read again under `view`.
  let fact = $state(null), factError = $state(null);
  $effect(() => {
    fact = null; factError = null;
    if (item.kind !== "fact") return;
    const key = item.decl + "|" + item.id, it = item, asked = token;
    if (facts.has(key)) { fact = facts.get(key); return; }
    if (!local) return;
    proofFacts(it.decl).then((doc) => {
      for (const f of doc.results || []) facts.set(it.decl + "|" + f.id, f);
      if (token !== asked) return;
      fact = facts.get(key) || null;
      if (!fact) factError = "This proof no longer has that fact.";
    }).catch((e) => { if (token === asked) factError = String(e.message || e); });
  });
  const hyps = (f) => (f.assumptions || []).filter((a) => a.role === "hypothesis");

  // An application of a declaration, likewise.
  let app = $state(null), appError = $state(null);
  $effect(() => {
    app = null; appError = null;
    if (item.kind !== "application") return;
    const key = item.callee + "|" + item.id, it = item, asked = token;
    if (applications.has(key)) { app = applications.get(key); return; }
    if (!local) return;
    askUses(it.callee).then((got) => {
      const doc = usersSide(got, mode);
      for (const a of doc.applications || []) applications.set(it.callee + "|" + a.id, a);
      if (token !== asked) return;
      app = applications.get(key) || null;
      if (!app) appError = "Lean no longer finds that application.";
    }).catch((e) => { if (token === asked) appError = String(e.message || e); });
  });

  // A saved piece of evidence of the open investigation.
  const evidence = $derived(item.kind === "evidence" && workspace.id === item.ws
    ? (workspace.view?.claims?.[claimId]?.evidence || []).find((e) => e.id === item.id) || null : null);

  function key(e) {
    if (e.key === "Escape" && (crumbs || onclose)) {
      e.preventDefault();
      e.stopPropagation();
      if (crumbs) onback?.(crumbs.depth);
      else onclose?.();
    }
  }
  export function focus() {
    panel?.querySelector(".back, .x")?.focus({ preventScroll: true });
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section class="inspection" class:pinned data-inspect={token} data-kind={item.kind} aria-label={"Inspecting " + labelOf(token)} bind:this={panel} onkeydown={key}>
  <nav class="crumbs" aria-label={crumbs ? "Opened from this claim" : "Pinned"}>
    {#if crumbs}
      <button class="back" onclick={() => onback?.(crumbs.depth)}>← Back</button>
      <span class="trail">
        <button class="crumb" onclick={() => onback?.(0)}>{crumbs.root}</button>
        {#each crumbs.trail.slice(0, crumbs.depth) as t, i}› <button class="crumb" title={t} onclick={() => onback?.(i + 1)}>{labelOf(t)}</button>{/each}
        › <span class="here" title={token}>{labelOf(token)}</span>
      </span>
    {:else}
      <span class="trail"><span class="here" title={token}>{labelOf(token)}</span></span>
    {/if}
    <span class="tools">
      {#if pinnable && onpin}<button class="pin" aria-pressed={pinned} title={pinned ? "Unpin: close it with the trail" : "Pin: keep it open while you open another reference"} onclick={onpin}>{pinned ? "Pinned" : "Pin"}</button>{/if}
      {#if onclose}<button class="x" aria-label="Close" onclick={onclose}>×</button>{/if}
    </span>
  </nav>
  {#key token}
    {#if item.kind === "details"}
      {@render extra?.(item)}
    {:else if item.kind === "decl"}
      {#await paperOf(item.name) then def}
        {#if def}
          <section class="paper-def"><h2>Paper · {def.number}</h2><PaperStatement claim={def} paper={def.audit?.paper || index.papers.find((p) => p.id === def.paper)} evidence={false} /></section>
          <h2>Lean</h2>
        {/if}
      {/await}
      <Decl name={item.name} key={decls?.[item.name] ?? null} {index} inspector onref={onref} />
    {:else if item.kind === "property"}
      {#if standing}
        {@const p = standing.prop}
        {@const o = standing.owner.name || "this object"}
        <div class="prop" data-standing={standing.how}>
          <p class="lead"><LeanText pp={p.type} {onref} refs={statements[item.spec]?.closure || []} /></p>
          <pre class="exact"><code>{p.term}</code> : <LeanText pp={p.type} /></pre>
          <p class="small stands">{STANDS[standing.how](o)}</p>
          <p class="small faint">Field <code>{p.field}</code> of <code>{p.structure}</code>{#if p.inherited}, inherited from <code>{p.declared_in}</code>{#if p.via?.length} through <code>{p.via.join(", ")}</code>{/if}{/if}; its projection <code>{p.projection || p.field}</code>{#if p.module}, in {p.module}{p.range?.line ? ":" + p.range.line : ""}{/if}.</p>
          {#if p.structure && onref}<p class="small"><button class="link" onclick={() => onref(p.structure)}>Open {short(p.structure)}</button>{#if p.inherited && p.declared_in && p.declared_in !== p.structure}{" · "}<button class="link" onclick={() => onref(p.declared_in)}>Open {short(p.declared_in)}</button>{/if}</p>{/if}
        </div>
      {:else}
        <p class="small bad">This statement has no such property in this build. A property is shown for the object it was chosen on only.</p>
      {/if}
    {:else if item.kind === "fact"}
      {#if fact}
        <div class="fact" data-fact={fact.id}>
          <p class="small"><span class="what">{fact.what}</span> {#if fact.kind === "application" ? fact.head : fact.name}<code>{fact.kind === "application" ? fact.head : fact.name}</code>{/if}
            <span class="faint">· inside the proof of <code>{item.decl}</code>{#if fact.source?.line} · {fact.source.file}:{fact.source.line}{/if}</span></p>
          <p class="lead"><LeanText pp={fact.type} {onref} /></p>
          {#if hyps(fact).length}<p class="small"><span class="faint">assuming</span> {#each hyps(fact) as a, i}{i ? "; " : ""}<code>{a.name} : {a.type}</code>{/each}</p>{/if}
          {#each fact.cases || [] as c}<p class="small faint">{c}</p>{/each}
          <p class="small stands">{fact.basis}: established inside this proof under its context, not a theorem of its own.</p>
        </div>
      {:else if factError}<p class="small bad">{factError}</p>
      {:else if local}<p class="small faint">Reading the proof of <code>{item.decl}</code>…</p>
      {:else}<p class="small faint">Facts inside a proof are read from Lean under <code>machinechecked view</code>: <code>machinechecked compare --query proof-facts {item.decl}</code>.</p>{/if}
    {:else if item.kind === "application"}
      {#if app}
        <p class="small">An application of <code>{item.callee}</code>, as Lean described it.</p>
        <Application a={app} callee={item.callee} {onref} {index} />
      {:else if appError}<p class="small bad">{appError}</p>
      {:else if local}<p class="small faint">Asking Lean for the application…</p>
      {:else}<p class="small faint">Applications are read from Lean under <code>machinechecked view</code>: <code>machinechecked compare --query uses {item.callee}</code>.</p>{/if}
    {:else if item.kind === "evidence"}
      {#if evidence}
        {@const r = evidence.ref || {}}
        <p class="small faint">Saved in the investigation {item.ws} as {evidence.role}{evidence.currency?.state === "stale" ? "; it changed since" : ""}.</p>
        {#if r.decl}
          <Decl name={r.decl} key={decls?.[r.decl] ?? null} {index} inspector onref={onref} />
        {:else if r.fact}
          <p class="small"><code>{r.fact.name || r.fact.head || "a fact"}</code> : <code>{r.fact.type}</code>, inside the proof of <code>{r.fact.decl}</code> ({r.fact.basis}).</p>
          {#if onref}<p class="small"><button class="link" onclick={() => onref(r.fact.decl)}>Open {short(r.fact.decl)}</button></p>{/if}
        {:else if r.app}
          <p class="small"><code>{r.app.callee}</code> applied in <code>{r.app.caller}</code>.</p>
          {#if onref}<p class="small"><button class="link" onclick={() => onref(r.app.callee)}>Open {short(r.app.callee)}</button> · <button class="link" onclick={() => onref(r.app.caller)}>Open {short(r.app.caller)}</button></p>{/if}
        {:else if r.certificate}
          <p class="small"><code>{r.certificate.theorem}</code>, a certificate for <code>{r.certificate.target}</code>.</p>
        {:else if r.source}
          <p class="small">{r.source.file}{r.source.line ? ":" + r.source.line : ""}</p>
        {:else}
          <p class="small">A passage of the paper.</p>
        {/if}
      {:else}
        <p class="small faint">This evidence is saved in the investigation {item.ws}; open it below to see it here.</p>
      {/if}
    {/if}
  {/key}
</section>

<style>
  .inspection { margin: 10px 0; padding: 8px 12px 10px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 8px; background: var(--surface); min-width: 0; }
  .inspection.pinned { border-style: dashed; }
  .crumbs { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 13px; color: var(--muted); margin-bottom: 6px; }
  .back, .pin { font: inherit; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .pin[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft); }
  .crumb { border: 0; background: none; padding: 0; font: inherit; color: var(--accent); cursor: pointer; }
  .trail { overflow-wrap: anywhere; flex: 1; min-width: 0; }
  .here { color: var(--text); }
  .tools { display: flex; gap: 6px; align-items: baseline; margin-left: auto; }
  .x { border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 18px; line-height: 1; padding: 0 4px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 4px 0 6px; }
  .lead { margin: 4px 0; }
  .lead :global(.lean) { font-family: var(--serif); font-size: 17px; line-height: 1.6; }
  .exact { margin: 4px 0; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.6 var(--mono); }
  .stands { margin: 6px 0; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  .bad { color: var(--st-malformed); }
  .link { font: inherit; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; }
  .what { margin-right: 6px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); }
  .inspection :global(.lean button), .inspection :global(.lean a) { min-height: 0; }
  /* The panel is the declaration's frame. */
  .inspection > :global(.decl.inspector) { border: 0; padding: 0; margin: 0; background: none; }
</style>
