<script>
  import { setContext, tick } from "svelte";
  import PaperStatement from "./PaperStatement.svelte";
  import StepContext from "./StepContext.svelte";
  import TexInline from "./TexInline.svelte";
  import Statement from "./Statement.svelte";
  import Definition from "./Definition.svelte";
  import ExactLean from "./ExactLean.svelte";
  import Inspection from "./Inspection.svelte";
  import { loadDecl, loadWork } from "../lib/data.js";
  import { withQuery } from "../lib/route.svelte.js";
  import { sourceUrl, sourceLabel, sourceTitle } from "../lib/issue.js";
  import { clauseNote } from "../lib/presentation.js";
  import { declSide, usersSide, independent, statementRows, alignmentSource, alignedRows, targetText } from "../lib/comparison.js";
  import { trail, anchor, openInspection, backTo, opener, pins, pinsIn, pinOf, togglePin, tokenOf, itemOf,
           workspace, DETAILS } from "../lib/inspect.svelte.js";
  import { carriedOf } from "../lib/carried.js";

  // One claim's comparison, Paper | Lean, shared by the reader, the claim page and the review
  // page. It draws the content its controller allows (`inputs`, from `comparison.comparisonInputs`)
  // and nothing else: the paper's passages, and the Lean as rows (each object with its conditions,
  // each other condition, the conclusion; a definition per row), each row's readable mathematics
  // with its exact Lean beside it when there is room, and each statement's complete exact Lean
  // after its rows. On a narrow screen the paper comes first, then the Lean, row by row.
  //
  // Rows are paired with the paper when an alignment a person recorded is allowed and chosen:
  // each row then has the passages aligned with it beside it, with their author. Otherwise the
  // paper's passage is beside the whole Lean.
  //
  // A declaration, a carried property, a fact or application, or saved evidence opens beside the
  // row it was opened from, and the claim stays on the page; the trail is in the page's address,
  // so Back and Forward close and reopen it, and a pin keeps an inspection open. `extra` draws the
  // inspections its controller owns (the audit details); `paperTools`, `linkTools(link, at, role)`
  // (role: a claim's "link", a step's "step" or "route" declaration), `clauseTools(clause, k)`
  // and `leanFoot` hold its controls (making links, reading a proof's facts, suggestions).
  let { index, inputs, scope = null, headings = false, selection = $bindable(null), mark = null,
        onpinned = null, paperTools = null, linkTools = null, clauseTools = null, leanFoot = null,
        extra = null, stickyTop = 0 } = $props();

  const mode = $derived(inputs.mode);
  const blind = $derived(independent(mode));
  const passages = $derived(inputs.passages || []);
  const main = $derived(passages[0] || null);
  const formal = $derived(inputs.formal);
  const decls = $derived(formal?.decls || {});
  const clauses = $derived(formal?.clauses || []);
  const simple = $derived(formal?.mode === "simple" || (!!formal?.links && !formal?.clauses?.length));
  const step = $derived(main?.step && formal?.step ? formal.step : null);
  const defsOnly = $derived(inputs.definitions || []);
  const paperOf = (c) => c?.audit?.paper || index.papers.find((p) => p.id === c?.paper);
  let witnessOpen = $state({});

  // A declaration's link opens it above the comparison in another tab.
  setContext("declarationHref", (name) => withQuery(location.hash, { inspect: [name], at: null }));
  // Declarations and reverse references reach an inspection as the stage allows them.
  setContext("comparison", {
    get mode() { return mode; },
    decl: (key) => loadDecl(key).then((r) => declSide(r, mode)),
    users: (entry) => usersSide(entry, mode),
  });

  // The statements shown, by declaration (a definition maps to null): what alignments and
  // property inspections are resolved against.
  const statements = $derived.by(() => {
    const out = {};
    if (step) for (const l of [...(step.links || []), ...(step.route?.links || [])]) out[l.name] = l.statement || null;
    else if (simple) for (const l of formal?.links || []) out[l.name] = l.statement || null;
    else for (const cl of clauses) {
      if (cl.statement) out[cl.spec] = cl.statement;
      for (const d of cl.defs || []) out[d] = null;
    }
    for (const d of defsOnly) out[d.name] = null;
    return out;
  });

  // The sub-term selected, by its identity in one declaration's statement ({spec, id}): shared by
  // the readable rows, each row's exact Lean and the complete exact statement.
  const selFor = (spec) => (spec != null && selection && selection.spec === spec ? selection.id : null);
  function select(spec, id) {
    if (spec == null) return;
    if (id == null) { if (selection?.spec === spec) selection = null; }
    else if (selection?.spec !== spec || selection.id !== id) selection = { spec, id };
  }

  // Symbol links (docs/SYMBOL_LINKS.md), where allowed: a symbol of the printed statement linked,
  // by a named person, to a variable or a binder's type of the Lean statement. Only links that
  // are not stale are drawn. Hovering either side highlights the other; a click holds a symbol.
  const links = $derived((inputs.annotations?.symbols || []).filter((l) => !l.stale).map((l, i) => ({ ...l, id: i })));
  let symHover = $state(null), symPinned = $state(null), leanActive = $state(null);
  const symActive = $derived(symHover ?? symPinned);
  function onsym(id, how) {
    if (how === "pin") symPinned = symPinned === id ? null : id;
    else symHover = id;
  }
  const litSymbols = $derived(symActive != null ? [symActive]
    : leanActive ? links.filter((l) => l.lean.decl === leanActive.spec && l.lean.var === leanActive.var).map((l) => l.id) : []);
  function extFor(spec) {
    const l = links.find((x) => x.id === symActive);
    if (!l || l.lean.decl !== spec) return null;
    if (l.lean.at != null) return { at: l.lean.at };
    return l.lean.var != null ? { var: l.lean.var } : { type: l.lean.binder };
  }
  const shownLink = $derived(links.find((l) => l.id === symActive));

  // The view a pin belongs to changes with the claim, the project or the build: then selections
  // and held symbols go too.
  const viewKey = $derived(JSON.stringify(scope) + "\u0000" + (main?.id || ""));
  let lastView = null;
  $effect(() => {
    if (viewKey !== lastView) {
      if (lastView !== null) { selection = null; symHover = null; symPinned = null; leanActive = null; rowsFrom = null; }
      lastView = viewKey;
    }
  });

  // What a correcting clause changes, read off the two Lean statements as they are shown: the
  // hypotheses one has and the other lacks, and whether the conclusion is the same text. It
  // describes the statements; it is not a judgement of either.
  function changes(cl) {
    if (!cl.corrects || !cl.statement) return null;
    const orig = clauses.find((c) => c.name === cl.corrects);
    if (!orig?.statement) return null;
    const text = (pp) => (typeof pp === "string" ? pp : pp?.text ?? (pp?.segments || []).map((s) => s.t).join(""));
    const hyps = (st) => (st.binders || []).filter((b) => b.role === "hypothesis").map((b) => text(b.type));
    const vars = (st) => (st.binders || []).filter((b) => b.role !== "hypothesis").map((b) => b.role + " " + b.name + " : " + text(b.type));
    const a = hyps(orig.statement), b = hyps(cl.statement);
    const added = b.filter((h) => !a.includes(h)), dropped = a.filter((h) => !b.includes(h));
    const va = vars(orig.statement), vb = vars(cl.statement);
    return {
      label: orig.label || orig.name, added, dropped,
      varsSame: va.length === vb.length && va.every((v, i) => v === vb[i]),
      conclusionSame: text(orig.statement.conclusion) === text(cl.statement.conclusion),
    };
  }

  // Alignments a person recorded, where allowed: each published reading of the audit, and the
  // reading of the investigation open in this page. One is chosen to pair the rows.
  let published = $state([]);
  $effect(() => {
    const w = inputs.annotations?.work ? { work: inputs.annotations.work, id: main?.id } : null;
    let current = true;
    published = [];
    if (!w) return;
    loadWork(w).then((d) => { if (current) published = d?.readings || []; }).catch(() => {});
    return () => { current = false; };
  });
  const whoOf = (r) => r?.kind === "model" ? "the AI model " + (r.model || r.id) : (r?.name || r?.id || "an unnamed auditor");
  const sources = $derived.by(() => {
    if (blind) return [];
    const out = [];
    for (const rd of published) {
      const s = alignmentSource(rd, { who: whoOf(rd.reviewer || {}), from: "published" });
      if (s) out.push(s);
    }
    const own = workspace.view?.claims?.[main?.id]?.reading;
    const mine = own && alignmentSource({ ...own, workspace: workspace.id }, { who: "your investigation (" + workspace.view.reviewer + ")", from: "workspace" });
    if (mine) out.push(mine);
    return out;
  });
  let rowsFrom = $state(null);
  const source = $derived(rowsFrom === "none" ? null : sources.find((s) => s.id === rowsFrom) || sources[0] || null);
  const paired = $derived(!!source);
  const aligned = $derived(alignedRows(source, statements));
  const seenAt = $derived.by(() => {
    // The first row an alignment is drawn at: its passages are printed there, and named after.
    const m = new Map();
    for (const [key, list] of aligned.at) for (const e of list) if (!m.has(e.alignment)) m.set(e.alignment, key);
    return m;
  });
  const where = (f) => f.missing ? "a passage no longer kept"
    : f.passage ? (f.passage.claim === main?.id ? "this claim's passage" : `the passage of ${f.passage.claim}`)
    : f.region?.file ? `${f.region.file}:${f.region.start_line}${f.region.end_line && f.region.end_line !== f.region.start_line ? "–" + f.region.end_line : ""}`
    : "a passage of the paper";

  // Inspections. The trail is in the address; an anchor this comparison does not draw is the top.
  const stack = $derived(trail());
  const anchors = $derived.by(() => {
    const out = new Set(["top"]);
    for (const [name, st] of Object.entries(statements)) {
      out.add(name + "::top");
      if (st) { out.add("exact:" + name); for (const r of statementRows(st)) out.add(name + "::" + r.key); }
    }
    return out;
  });
  const at = $derived(stack.length ? (anchors.has(anchor()) ? anchor() : "top") : null);
  const top = $derived(stack.at(-1) || null);
  const pinsHere = $derived(scope ? pinsIn(scope).filter((p) => resolves(p)) : []);
  const open = (token, row) => openInspection(token, row);
  const nestedRef = (name) => openInspection(name, at || "top", { nested: true });

  // What a pin shows must still be what it was pinned on: the same declaration record, the same
  // property of the same object in the same statement.
  function identOf(token) {
    const it = itemOf(token);
    if (it.kind === "decl") return "decl|" + it.name + "|" + (decls[it.name] ?? "");
    if (it.kind === "property") {
      const st = statements[it.spec];
      const p = st && carriedOf(st).find((c) => c.prop.type?.id === it.id);
      const exact = typeof st?.exact === "object" ? st.exact.text : st?.exact;
      return p ? "property|" + it.spec + "|" + it.id + "|" + (p.prop.type?.text || "") + "|" + (exact || "") : null;
    }
    return token;
  }
  function resolves(p) { return identOf(p.token) === p.ident; }
  function pin(token, row) {
    if (!scope) return;
    togglePin({ token, at: row, scope, ident: identOf(token), label: labelOf(token) });
  }
  const isPinned = (token) => !!scope && !!pinOf(scope, token) && pinsHere.some((p) => p.token === token);

  function labelOf(token) {
    const it = itemOf(token);
    if (it.kind === "details") return "Audit details";
    if (it.kind === "decl") return (it.name || "").split(".").pop();
    if (it.kind === "property") {
      const p = statements[it.spec] && carriedOf(statements[it.spec]).find((c) => c.prop.type?.id === it.id);
      return p ? p.prop.term : "a property";
    }
    if (it.kind === "fact") return "a fact of " + it.decl.split(".").pop();
    if (it.kind === "application") return "an application of " + it.callee.split(".").pop();
    return "saved evidence";
  }

  // Opening and closing an inspection keeps the reader's place: the scroll position and the
  // element they opened it from come back when they return.
  let root = $state();
  const panels = {};
  function scroller() {
    for (let e = root?.parentElement; e; e = e.parentElement) {
      const o = getComputedStyle(e).overflowY;
      if ((o === "auto" || o === "scroll") && e.scrollHeight > e.clientHeight) return e;
    }
    return document.scrollingElement;
  }
  let previous = [];
  const scrolls = [];
  $effect.pre(() => {
    const next = [...stack];
    if (!root) { previous = next; return; }
    const before = previous;
    if (next.length > before.length || (next.length && next.join("\u0000") !== before.join("\u0000") && next.length === before.length)) scrolls[before.length] = scroller().scrollTop;
    previous = next;
    if (next.join("\u0000") === before.join("\u0000")) return;
    tick().then(() => {
      if (!root) return;
      if (next.length >= before.length && next.length) {
        const p = root.querySelector(".current-wrap .inspection");
        p?.querySelector(".back")?.focus({ preventScroll: true });
        p?.scrollIntoView({ block: "nearest" });
      } else if (next.length < before.length) {
        const s = scroller();
        if (scrolls[next.length] != null) s.scrollTop = scrolls[next.length];
        if (next.length) root.querySelector(".current-wrap .inspection .back")?.focus({ preventScroll: true });
        else {
          const o = opener(0);
          if (o?.isConnected) o.focus({ preventScroll: true });
        }
      }
    });
  });

  // The paper's passage stays beside the Lean while the Lean scrolls, when it is short enough to.
  let paperHeight = $state(0), viewHeight = $state(window.innerHeight);
  const sticky = $derived(!paired && paperHeight > 0 && paperHeight < viewHeight * 0.66);
</script>

<svelte:window bind:innerHeight={viewHeight} />

<!-- The inspections beside one row: those pinned there, then the open trail's, if it is there. -->
{#snippet slot(key)}
  {#each pinsHere.filter((p) => p.at === key && !(p.token === top && at === key)) as p (p.token)}
    <Inspection {index} token={p.token} {mode} claimId={main?.id} {decls} {statements} {labelOf} {extra}
      pinned onpin={() => pin(p.token, key)} onclose={() => pin(p.token, key)} onref={(n) => open(n, key)} />
  {/each}
  {#if top && at === key}
    <div class="current-wrap">
      <Inspection {index} token={top} {mode} claimId={main?.id} {decls} {statements} {labelOf} {extra}
        crumbs={{ root: main?.number || main?.id || "The claim", trail: stack, depth: stack.length - 1 }}
        pinned={isPinned(top)} pinnable={!!scope} onpin={() => pin(top, key)} onclose={() => backTo(0)}
        onback={(n) => backTo(n)} onref={nestedRef} />
    </div>
  {/if}
{/snippet}

{#snippet afterRow(key, spec)}{@render slot(spec + "::" + key)}{/snippet}

<!-- A paired row's paper cell: the passages aligned with it, each with its requirement, its
     relation and its author. An alignment drawn at an earlier row is named, not repeated. -->
{#snippet alignedCell(key)}
  {#each aligned.at.get(key) || [] as e (e.alignment.id)}
    {@const a = e.alignment}
    <div class="aligned" data-alignment={a.id} class:stale={a.stale}>
      {#if seenAt.get(a) === key}
        {#each a.passages as f (f.id)}
          {#if f.region?.text}<pre class="frag">{f.region.text}</pre>{:else}<p class="small faint">{where(f)}</p>{/if}
        {/each}
        {#each a.requirements as r (r.local_id)}<p class="small req"><code>{r.local_id}</code>{#if r.form}{" "}<span class="form">{r.form}</span>{/if}{#if r.text}: <span class="text">{r.text}</span>{/if}{#if r.missing}<span class="faint"> (no longer kept)</span>{/if}</p>{/each}
        {#if !a.requirements.length}<p class="small faint">Lean only: no passage of the paper.</p>{/if}
      {:else}
        <p class="small faint">The passages aligned above ({a.requirements.map((r) => r.local_id).join(", ") || "Lean only"}), also here.</p>
      {/if}
      <p class="small faint">{a.relation}{e.targets.length > 1 || e.targets.some((t) => t.target) ? " · " + e.targets.map(targetText).join("; ") : ""} · recorded by {a.by}{#if a.stale}<span class="warn"> · {a.stale ? "out of date since it was recorded" : ""}</span>{/if}</p>
      {#if a.note}<p class="small text">{a.note}</p>{/if}
    </div>
  {:else}
    <p class="small faint none">Not aligned with the paper in this reading.</p>
  {/each}
{/snippet}

{#snippet paperCell(key, spec)}{@render alignedCell(spec + "::" + key)}{/snippet}

<!-- A whole declaration's alignments, before its rows. -->
{#snippet wholeRow(name)}
  {#if paired && aligned.at.has(name + "::top")}
    <div class="crow whole" data-row={name + "::top"}>
      <div class="pcell">{@render alignedCell(name + "::top")}</div>
      <div class="lcell"><p class="small"><code>{name}</code> <span class="faint">as a whole</span></p></div>
    </div>
  {/if}
{/snippet}

<!-- A statement: its rows, then its complete exact Lean. -->
{#snippet statementOf(spec, st, k)}
  {@render wholeRow(spec)}
  <Statement {st} {spec} compact exact paper={paired ? paperCell : null} after={afterRow}
    onref={(n, row) => open(n, spec + "::" + row)}
    onproperty={(p, o, how, row) => open(tokenOf({ kind: "property", spec, id: p.type?.id }), spec + "::" + row)}
    ext={extFor(spec)} mark={mark?.(spec, k) ?? null}
    selId={selFor(spec)} onselect={(id) => select(spec, id)}
    onpinned={(v, name) => onpinned?.(spec, v, name)}
    onactive={(v) => (leanActive = v == null ? (leanActive?.spec === spec ? null : leanActive) : { spec, var: v })} />
  <div class={paired ? "crow exactrow" : "exactrow"}>
    {#if paired}<div class="pcell"></div>{/if}
    <div class="exact-pane lcell" data-exact={spec}>
      <p class="lbl">Exact Lean</p>
      <ExactLean {st} name={spec} onref={(n) => open(n, "exact:" + spec)} selId={selFor(spec)} onselect={(id) => select(spec, id)} />
      {#if st.closure?.length}
        <details class="closure">
          <summary>Definitions it uses ({st.closure.length})</summary>
          <ul>{#each st.closure as n (n)}<li><button class="ref" onclick={() => open(n, "exact:" + spec)}><code>{n}</code></button></li>{/each}</ul>
        </details>
      {/if}
      {@render slot("exact:" + spec)}
    </div>
  </div>
{/snippet}

<!-- A definition: one row, what it says beside its exact Lean. -->
{#snippet definitionOf(name, key, d = null)}
  <div class={paired ? "crow defrow" : "defrow"} data-row={name + "::top"}>
    {#if paired}<div class="pcell">{@render alignedCell(name + "::top")}</div>{/if}
    <div class="lcell">
      <div class="drow">
        <div class="readable" data-slot="readable"><Definition {d} {name} {key} onref={(n) => open(n, name + "::top")} onname={(n) => open(n, name + "::top")} selId={selFor(name) ?? extFor(name)?.at ?? null} onselect={(id) => select(name, id)} /></div>
        <div class="exact-pane"><Definition {d} {name} {key} view="exact" onref={(n) => open(n, name + "::top")} selId={selFor(name)} onselect={(id) => select(name, id)} /></div>
      </div>
      {@render slot(name + "::top")}
    </div>
  </div>
{/snippet}

{#snippet blocks()}
  {#if step}
    <h3 class="sub">Lean that establishes this step</h3>
    {#each step.links as l (l.name)}
      <div class="block" data-decl={l.name}>
        <p class="decl"><code>{l.name}</code></p>
        {#if l.statement}{@render statementOf(l.name, l.statement, 0)}{/if}
        {@render linkTools?.(l, l.name + "::top", "step")}
      </div>
    {:else}
      <p class="muted small">No Lean declaration is linked as establishing this step.</p>
    {/each}
    {#if step.route?.links?.length}
      <h3 class="sub">Different formal route used instead</h3>
      {#if step.route.note}<p class="small">{step.route.note}{#if step.route.by}<span class="faint">{" — " + step.route.by}</span>{/if}</p>{/if}
      {#each step.route.links as l (l.name)}
        <div class="block route" data-decl={l.name}>
          <p class="decl"><code>{l.name}</code></p>
          {#if l.statement}{@render statementOf(l.name, l.statement, 0)}{/if}
          {@render linkTools?.(l, l.name + "::top", "route")}
        </div>
      {/each}
      <p class="faint small">This Lean reaches {main?.step?.parent?.number || "the enclosing result"} by another argument; it does not state this step.</p>
    {/if}
  {:else if simple}
    {#each formal?.links || [] as l (l.name)}
      <div class="block" data-decl={l.name}>
        <p class="decl"><code>{l.name}</code>
          {#if sourceUrl(index, l.path, l.range?.line)}<a class="src-link small" href={sourceUrl(index, l.path, l.range?.line)} target="_blank" rel="noopener" title={sourceTitle(index)}>{sourceLabel(index)}</a>{/if}</p>
        {#if l.definition}{@render definitionOf(l.name, null, l.definition)}
        {:else if l.statement}{@render statementOf(l.name, l.statement, 0)}{/if}
        {@render linkTools?.(l, l.name + "::top", "link")}
      </div>
    {:else}
      {#if !defsOnly.length}<p class="muted">Not linked to a Lean declaration.</p>{/if}
    {/each}
  {:else}
    {#each clauses as cl, k (k)}
      <div class="block" class:refuted={cl.state === "refuted"} data-spec={cl.spec}>
        {#if clauses.length > 1}<p class="cname"><TexInline text={cl.label || cl.name} />{#if cl.corrects}<span class="faint">&nbsp;— corrects “<TexInline text={cl.corrects_label || cl.corrects} />”</span>{/if}</p>{/if}
        {#if clauseNote(cl, clauses.length)}<p class="verdict">{clauseNote(cl, clauses.length)}</p>{/if}
        {#if changes(cl)}
          {@const d = changes(cl)}
          <div class="changes">
            <p class="small"><strong>Compared with “<TexInline text={d.label} />”</strong></p>
            <ul class="small">
              {#each d.added as h}<li class="add">adds the hypothesis <code>{h}</code></li>{/each}
              {#each d.dropped as h}<li class="drop">drops the hypothesis <code>{h}</code></li>{/each}
              {#if !d.varsSame}<li>its variables or their types differ</li>{/if}
              <li>{d.conclusionSame ? "the same conclusion" : "a different conclusion"}</li>
            </ul>
          </div>
        {/if}
        {@render clauseTools?.(cl, k)}
        {#if cl.statement}
          {@render statementOf(cl.spec, cl.statement, k)}
        {:else if cl.defs?.length}
          {#each cl.defs as d (d)}{@render definitionOf(d, decls[d] ?? null)}{/each}
        {/if}
        {#if cl.witness}
          {#if cl.witness_record?.type}
            <details class="witness" bind:open={witnessOpen[cl.spec]}>
              <summary class="small">Witness <code>{cl.witness}</code></summary>
              {#if witnessOpen[cl.spec]}
                <p class="small faint">The instance it exhibits has this type:</p>
                <Statement st={{ binders: [], conclusion: cl.witness_record.type }} onref={(n) => open(n, cl.spec + "::top")} compact />
              {/if}
            </details>
          {:else}<p class="small witness">Witness <code>{cl.witness}</code></p>{/if}
        {/if}
      </div>
    {:else}
      {#if !defsOnly.length && formal}<p class="muted">No Lean statement has been written for this claim.</p>{/if}
    {/each}
  {/if}
  {#each defsOnly as d (d.name)}
    <div class="block" data-decl={d.name}><p class="decl"><code>{d.name}</code></p>{@render definitionOf(d.name, d.key)}</div>
  {/each}
  {#if paired && aligned.elsewhere.length}
    <div class="elsewhere">
      <p class="small faint">Aligned with Lean this comparison does not show:</p>
      {#each aligned.elsewhere as a (a.id)}<p class="small" data-alignment={a.id}>{a.requirements.map((r) => r.local_id).join(", ") || "Lean only"} · {a.lean.map(targetText).join("; ")} <span class="faint">· {a.relation} · recorded by {a.by}</span></p>{/each}
    </div>
  {/if}
  {@render leanFoot?.()}
{/snippet}

{#snippet passagesOf()}
  <h2>Paper{main?.audit?.paper ? " · audited revision" : ""}</h2>
  {#if main?.audit?.paper}<p class="small faint">Revision <code>{main.audit.paper.revision.slice(0, 12)}</code> · <a href={main.audit.link}>Open audit</a></p>{/if}
  {#each passages as c, i (c.id)}
    {#if i === 1}<p class="small faint also">Also stated in {passages.length - 1} other place{passages.length > 2 ? "s" : ""}:</p>{/if}
    <div class="passage" data-claim={c.id}>
      {#if headings || i}
        <h3 class="pnum">{c.number || c.id}{#if c.heading}<span class="ht">&nbsp;— <TexInline text={c.heading} /></span>{/if}</h3>
        {#if !c.heading && c.title}<p class="desc"><TexInline text={c.title} /></p>{/if}
      {/if}
      <PaperStatement claim={c} paper={paperOf(c)} evidence={!blind && i === 0}
        symbols={i === 0 ? links.map((l) => ({ tex: l.symbol.tex, id: l.id, occurrence: l.symbol.occurrence })) : []}
        active={i === 0 ? litSymbols : []} onsym={i === 0 ? onsym : null} />
      {#if c.step && c.context_tex}<StepContext text={c.context_tex} cut={c.context_cut} open={blind} />{/if}
    </div>
  {/each}
  {#if links.length && main?.statement_tex}
    <p class="faint small linkby">{#if shownLink}Symbol correspondence by {shownLink.by}{shownLink.symbol.object ? ` for ${shownLink.symbol.object}` : ""}.{:else}Select an underlined symbol to see its Lean correspondence and author.{/if}</p>
  {/if}
  {@render paperTools?.()}
{/snippet}

<div class="cmp" class:paired bind:this={root} data-mode={mode}>
  {@render slot("top")}
  {#if sources.length}
    <p class="rows small">
      <label>Rows <select aria-label="Rows" value={source ? source.id : "none"} onchange={(e) => (rowsFrom = e.currentTarget.value)}>
        {#each sources as s (s.id)}<option value={s.id}>Aligned with the paper by {s.who}</option>{/each}
        <option value="none">The Lean's own rows, beside the whole passage</option>
      </select></label>
      {#if source}<span class="faint">Each passage is beside the Lean it was aligned with, as recorded{source.from === "published" ? " and published with the audit" : ""}; Lean has not checked these associations.</span>{/if}
    </p>
  {/if}
  {#if !paired}
    <div class="grid" class:single={!passages.length || (!formal && !defsOnly.length)}>
      {#if passages.length}
        <section class="paper" class:sticky style:top={sticky ? stickyTop + "px" : null} bind:offsetHeight={paperHeight}>
          {@render passagesOf()}
        </section>
      {/if}
      {#if formal || defsOnly.length}
        <section class="lean">
          <h2>Lean</h2>
          {@render blocks()}
        </section>
      {/if}
    </div>
  {:else}
    <section class="paper whole">
      {@render passagesOf()}
    </section>
    <section class="lean paired">
      <h2>Lean, row by row</h2>
      <div class="crow heads" aria-hidden="true"><div class="pcell">Paper</div><div class="lcell">Lean</div></div>
      {@render blocks()}
    </section>
  {/if}
</div>

<style>
  .cmp { container-type: inline-size; display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; min-width: 0; }
  .grid > section { min-width: 0; }
  @container (min-width: 760px) {
    .grid:not(.single) { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 0 28px; align-items: start; }
    .grid:not(.single) > .lean { padding-left: 24px; border-left: 1px solid var(--border); }
    .paper.sticky { position: sticky; z-index: 1; background: var(--bg); }
  }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 8px; }
  .sub { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .pnum { font-size: 15px; font-weight: 600; margin: 10px 0 4px; }
  .ht { font-weight: 400; color: var(--muted); }
  .desc { margin: -2px 0 6px; font-size: 14px; color: var(--muted); }
  .also { margin: 14px 0 0; }
  .passage + .passage { margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border); }
  .block { margin-bottom: 18px; }
  .block.refuted { border-left: 3px solid var(--st-refuted); padding-left: 10px; }
  .block.route { border-left: 3px dashed var(--border); padding-left: 10px; }
  .cname { font-weight: 600; margin: 0 0 8px; }
  .verdict { margin: 10px 0 0; font-size: 14px; }
  .changes { border-left: 3px solid var(--st-open, #b7791f); background: var(--surface-2, transparent); padding: 6px 10px; margin: 0 0 10px; border-radius: 0 6px 6px 0; }
  .changes p { margin: 0 0 4px; }
  .changes ul { margin: 0; padding-left: 18px; }
  .changes code { font-size: 12px; }
  .decl { margin: 0 0 6px; overflow-wrap: anywhere; }
  .src-link { margin-left: 8px; white-space: nowrap; }
  .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); margin: 12px 0 4px; }
  .exactrow { margin-top: 4px; }
  .exact-pane { min-width: 0; }
  .closure { margin-top: 8px; }
  .closure > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
  .closure ul { margin: 4px 0; padding-left: 18px; font-size: 13px; }
  .ref { font: inherit; padding: 0; border: 0; background: none; color: var(--accent); cursor: pointer; text-align: left; overflow-wrap: anywhere; }
  .witness { margin: 8px 0 0; }
  details.witness > summary { cursor: pointer; color: var(--muted); }
  .defrow { margin: 0 0 12px; }
  .drow { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; }
  @container (min-width: 1000px) {
    .grid .drow, .paired .drow { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; align-items: start; }
    .drow > .exact-pane { padding-left: 12px; border-left: 1px dashed var(--border); }
  }
  .linkby { margin: 4px 0 0; }
  .rows { margin: 0; display: flex; gap: 8px 12px; flex-wrap: wrap; align-items: baseline; }
  .rows select { font: inherit; font-size: 13px; max-width: 100%; }
  .rows label { display: flex; gap: 6px; align-items: baseline; min-width: 0; max-width: 100%; }
  /* Paired rows: the aligned passages beside each row of the Lean; the paper first when narrow. */
  .crow { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; padding: 8px 0; border-top: 1px solid var(--border); }
  .crow > div { min-width: 0; }
  .heads { display: none; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); }
  @container (min-width: 760px) {
    .crow { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 20px; }
    .heads { display: grid; }
  }
  .frag { margin: 2px 0; padding: 4px 6px; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
  .aligned { margin: 0 0 8px; }
  .aligned p { margin: 2px 0; }
  .aligned.stale { opacity: 0.85; }
  .form { font-style: italic; }
  .text { white-space: pre-wrap; }
  .warn { color: var(--tier-warning); }
  .none { margin: 0; }
  .elsewhere { margin-top: 10px; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  .muted { color: var(--muted); }
</style>
