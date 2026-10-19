<script>
  import { claimLink, claimReference, issueUrl, reportsUrl, sourceUrl, sourceLabel, sourceTitle } from "../lib/issue.js";
  import TexInline from "./TexInline.svelte";
  import { loadClaim, loadSearch, saveLink, saveSymbol, inProject, projectClaims } from "../lib/data.js";
  import { project } from "../lib/project.svelte.js";
  import { href, route, go, withQuery, inspectionHref } from "../lib/route.svelte.js";
  import { statusView, inScope, clauseNote, evidenceView } from "../lib/presentation.js";
  import ExactLean from "./ExactLean.svelte";
  import EvidenceSummary from "./EvidenceSummary.svelte";
  import PaperStatement from "./PaperStatement.svelte";
  import StatusChip from "./StatusChip.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import Statement from "./Statement.svelte";
  import Ladder from "./Ladder.svelte";
  import Findings from "./Findings.svelte";
  import Decl from "./Decl.svelte";
  import Tex from "./Tex.svelte";
  import LinkPicker from "./LinkPicker.svelte";
  import { tick, setContext } from "svelte";

  // One claim as Paper and Lean: a heading, the status the engine computed, the printed
  // statement and the Lean statement. Everything else (reviews, evidence, provenance) is in the
  // audit details, which open in the inspector like a declaration does.
  let { index, claimId, full = false, editable = false, comparison = false } = $props();

  let loaded = $state(null);
  // On a page with several projects, the claim as the chosen one sees it.
  const claim = $derived(loaded && index.projects ? inProject(loaded, project.repo) : loaded);
  let error = $state(null);
  // The inspector: the declarations opened from this claim, in order. While it is not empty the
  // last one replaces the claim view, which stays mounted (hidden) so its open sections and
  // scroll position come back on Back.
  const stack = $derived(route.inspection || []);
  setContext("declarationHref", (name) => inspectionHref([...stack, name]));
  let scrolls = [], returnFocus = [];
  let article = $state();
  let showAll = $state(false);
  let menu = $state(false), menuWrap = $state(), menuButton = $state();
  let attempt = $state(0);
  const DETAILS = "@details";
  // The words for a mapper's coverage reading (links file `coverage`).
  const COVERAGE = { full: "States every clause", partial: "States part of the claim",
    changed: "States it differently", related: "A related result, not this claim" };
  let busy = $state(null);
  let saveError = $state(null);
  const RANK = { stale: 0, pending: 1, "author-reviewed": 2, reviewed: 3 };

  $effect(() => {
    claimId; project.repo; attempt;
    let current = true;
    loaded = null; error = null; scrolls = []; showAll = false; saveError = null; menu = false;
    loadClaim(index, claimId).then((c) => { if (current) loaded = c; }).catch((e) => { if (current) error = String(e); });
    return () => { current = false; };
  });

  const paper = $derived(claim?.audit?.paper || (claim && index.papers.find((p) => p.id === claim.paper)));
  const evidenceIndex = $derived(claim?.audit?.context ? { ...index, ...claim.audit.context, papers: [paper] } : index);
  const meta = $derived(index.claims.find((c) => c.id === claimId));
  const simple = $derived(claim?.mode === "simple");

  // The element that scrolls the panel: the side panel in the reader, the page on a claim page.
  function scroller() {
    for (let e = article?.parentElement; e; e = e.parentElement) {
      const o = getComputedStyle(e).overflowY;
      if ((o === "auto" || o === "scroll") && e.scrollHeight > e.clientHeight) return e;
    }
    return document.scrollingElement;
  }

  // Symbol links (docs/SYMBOL_LINKS.md): a symbol of the printed statement linked, by a named
  // person, to a variable or a binder's type of the Lean statement. Only links that are not stale
  // are drawn. Hovering either side highlights the other; a click holds a symbol.
  const links = $derived((claim?.symbols || []).filter((l) => !l.stale).map((l, i) => ({ ...l, id: i })));
  let symHover = $state(null);
  let symPinned = $state(null);
  let leanActive = $state(null);
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
    if (l.lean.term != null) return { term: { where: l.lean.in, k: l.lean.term } };
    return l.lean.var != null ? { var: l.lean.var } : { type: l.lean.binder };
  }

  // Making a symbol link in the local reader (full assessment, editable): choose a symbol of the
  // claim's mathematics, then click its variable in the Lean statement, and save it under a name.
  const GREEK = "alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega";
  function candidates(tex) {
    const math = (tex || "").match(/\$\$[\s\S]*?\$\$|\$[\s\S]*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g) || [];
    const re = new RegExp(`\\\\(?:mathbb|mathcal|mathfrak|mathscr|mathrm|boldsymbol)\\s*\\{?[A-Za-z]\\}?(?:\\^\\{?[A-Za-z0-9]+\\}?)?|\\\\(?:${GREEK})(?![A-Za-z])|(?<![\\\\A-Za-z])[A-Za-z](?![A-Za-z])`, "g");
    return [...new Set(math.flatMap((m) => m.match(re) || []))];
  }
  // The sub-term selected in a statement, by its identity in the proposition: shared between
  // the readable statement and its exact Lean ({spec, id}).
  let selAt = $state(null);
  const selFor = (spec) => (spec != null && selAt && selAt.spec === spec ? selAt.id : null);
  function select(spec, id) {
    if (spec == null) return;
    if (id == null) { if (selAt?.spec === spec) selAt = null; }
    else if (selAt?.spec !== spec || selAt.id !== id) selAt = { spec, id };
    if (linking) pickVar = id == null ? (pickVar?.spec === spec && pickVar.at ? null : pickVar) : { spec, at: id };
  }
  let linking = $state(false);
  let pickSym = $state(null);
  let pickVar = $state(null);
  let pickType = $state(false);
  let linkErr = $state(null);
  let author = $state((() => { try { return localStorage.getItem("machinechecked-symbol-author") || ""; } catch { return ""; } })());
  const authorId = $derived(/^(human|llm):\S+$/.test(author.trim()) ? author.trim() : (author.trim() ? "human:" + author.trim().replace(/\s+/g, "-") : ""));
  async function saveLinkOfSymbol(req) {
    linkErr = null;
    try {
      try { localStorage.setItem("machinechecked-symbol-author", author.trim()); } catch {}
      await saveSymbol(req);
      location.reload();
    } catch (e) { linkErr = String(e.message || e); }
  }

  // The definition claim of the paper that a declaration states, if one links it: its excerpt is
  // shown above the Lean definition.
  async function paperOf(name) {
    const search = await loadSearch(index).catch(() => ({ claims: [], decls: [] }));
    const ids = search.decls?.find((d) => d.name === name)?.claims || [];
    const linked = (search.claims || []).filter((c) => ids.includes(c.id) && (c.lean || []).includes(name)).map((c) => c.id);
    const meta = projectClaims(index).find((c) => linked.includes(c.id) && c.kind === "definition");
    const raw = meta && (await loadClaim(index, meta.id).catch(() => null));
    const rec = raw && inProject(raw, project.repo);
    return rec?.anchor?.begin ? rec : null;
  }

  function showDecl(name) {
    if (article?.contains(document.activeElement)) returnFocus[stack.length] = document.activeElement;
    menu = false;
    if (stack.at(-1) !== name) go(inspectionHref([...stack, name]));
  }
  function backTo(n) { menu = false; go(inspectionHref(stack.slice(0, n))); }
  let previousStack = [];
  $effect.pre(() => {
    const next = [...stack];
    if (!article) return;
    const previous = previousStack;
    scrolls[previous.length] = scroller().scrollTop;
    previousStack = next;
    tick().then(() => {
      if (!article) return;
      scroller().scrollTop = next.length < previous.length ? scrolls[next.length] || 0 : 0;
      if (next.length) article.querySelector(".crumbs .back")?.focus({ preventScroll: true });
      else if (previous.length > next.length) (returnFocus[0]?.isConnected ? returnFocus[0] : menuButton)?.focus({ preventScroll: true });
    });
  });
  $effect(() => {
    if (!menu) return;
    const dismiss = (e) => {
      if (e.type === "keydown") {
        if (e.key !== "Escape") return;
        e.preventDefault(); menu = false; menuButton?.focus();
      } else if (!menuWrap?.contains(e.target)) menu = false;
    };
    document.addEventListener("keydown", dismiss);
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    return () => {
      document.removeEventListener("keydown", dismiss);
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
    };
  });

  async function act(req, label) {
    busy = label; saveError = null;
    try {
      await saveLink({ key: claim.key, ...req });
      location.reload();
    } catch (e) {
      saveError = String(e.message || e);
      busy = null;
    }
  }

  // What a correcting clause changes, read off the two Lean statements as they are shown: the
  // hypotheses one has and the other lacks, and whether the conclusion is the same text. It
  // describes the statements; it is not a judgement of either.
  function changes(cl) {
    if (!cl.corrects || !cl.statement) return null;
    const orig = claim.clauses.find((c) => c.name === cl.corrects);
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

  let copied = $state(null);
  async function copyLink() {
    const text = claimLink(index, claim) || claimReference(index, claim);
    try {
      await navigator.clipboard.writeText(text);
      copied = claimLink(index, claim) ? "Link copied" : "Reference copied";
    } catch {
      window.prompt("Copy this:", text);
    }
    setTimeout(() => (copied = null), 2000);
  }

</script>

{#snippet crop(c)}
  {@const pp = c.audit?.paper || index.papers.find((p) => p.id === c.paper)}
  {#if (pp?.pdf || pp?.pdf_url) && c.anchor?.begin}
    <PdfCrop url={pp.pdf_url || "data/" + pp.pdf} anchor={c.anchor} />
  {/if}
{/snippet}

{#if error}
  <p role="alert">{error} <button class="act" onclick={() => attempt++}>Try again</button></p>
{:else if !claim}
  <p class="muted">Loading…</p>
{:else}
  <article class="passport" class:full class:comparison={comparison || full} bind:this={article}>
    {#if stack.length}
      {@const top = stack[stack.length - 1]}
      <nav class="crumbs" aria-label="Opened from this claim">
        <button class="back" onclick={() => backTo(stack.length - 1)}>← Back</button>
        <span class="trail">
          <button class="crumb" onclick={() => backTo(0)}>{claim.number || claim.id}</button>
          {#each stack.slice(0, -1) as n, i}› <button class="crumb" title={n} onclick={() => backTo(i + 1)}>{n === DETAILS ? "Audit details" : n.split(".").pop()}</button>{/each}
          › <span class="here" title={top}>{top === DETAILS ? "Audit details" : top.split(".").pop()}</span>
        </span>
      </nav>
      {#key top}
        {#if top === DETAILS}
          {@render details()}
        {:else}
          {#await paperOf(top) then def}
            {#if def}
              <section class="paper"><h2>Paper · {def.number}</h2>{@render crop(def)}</section>
              <h2>Lean</h2>
            {/if}
          {/await}
          <Decl name={top} key={claim.decls?.[top] ?? null} index={evidenceIndex} inspector onref={showDecl} />
        {/if}
      {/key}
    {/if}
    <div class="view" hidden={stack.length > 0}>
    <header>
      <h1>{claim.number || claim.id}{#if claim.heading}<span class="title">&nbsp;— <TexInline text={claim.heading} /></span>{/if}</h1>
      {#if !claim.heading && claim.title}<p class="desc"><TexInline text={claim.title} /></p>{/if}
      <div class="bar">
        <button class="chipbtn" onclick={() => showDecl(DETAILS)} title="Audit details: what this status rests on"><EvidenceSummary record={claim} /></button>
        <span class="grow"></span>
        <span class="menuwrap" bind:this={menuWrap}>
          <button class="act more" bind:this={menuButton} aria-expanded={menu} aria-controls="claim-actions" aria-label="More" onclick={() => (menu = !menu)}>⋯</button>
          {#if menu}
            <div class="menu" id="claim-actions" role="group" aria-label="Claim actions">
        {#if issueUrl(evidenceIndex, claim)}
          <a class="act" href={issueUrl(evidenceIndex, claim)} target="_blank" rel="noopener" title={"Opens a draft issue in " + evidenceIndex.issues + " with this claim's details filled in"}>Report issue ↗</a>
        {/if}

              {#if !full}<a href={href(index.release, "claim", claim.id)}>Open as a page</a>{/if}
              {#if full && meta?.anchor}<a href={href(index.release, "read", claim.paper, claim.id)}>Show in the paper</a>{/if}
              <button onclick={() => { copyLink(); menu = false; }}>{claimLink(index, claim) ? "Copy link" : "Copy reference"}</button>
              {#if reportsUrl(evidenceIndex, claim)}<a href={reportsUrl(evidenceIndex, claim)} target="_blank" rel="noopener">View existing reports ↗</a>{/if}
              {#if index.review_queue && inScope(claim)}
                <a href={withQuery(href(index.release, "review"), { claim: claim.id, seen: "lean" })}>Review it</a>
              {/if}
              <button onclick={() => showDecl(DETAILS)}>Audit details</button>
            </div>
          {/if}
        </span>
      </div>
      {#if copied}<p class="faint small copied">{copied}</p>{/if}
      {#if claim.correspondence}
        {@const cor = claim.correspondence}
        <div class="coverage" data-coverage={cor.coverage || "note"}>
          <p class="small">{#if cor.coverage}<strong>{COVERAGE[cor.coverage]}</strong>{#if cor.confidence}{" "}<span class="faint">({cor.confidence} confidence)</span>{/if}{#if cor.note}{". "}{/if}{/if}{cor.note}</p>
          <p class="faint small">{cor.source === "formalization.yaml" ? "The project's note in formalization.yaml" : "The auditor's reading" + (cor.by ? ", by " + cor.by : "")}: how far the linked Lean states this claim. It is not a review and does not change the status.</p>
        </div>
      {/if}
    </header>

    <div class="comparison-grid">
    <section class="paper">
      <h2>Paper{claim.audit?.paper ? " · audited revision" : ""}</h2>
      {#if claim.audit?.paper}<p class="small faint">Revision <code>{claim.audit.paper.revision.slice(0, 12)}</code> · <a href={claim.audit.link}>Open audit</a></p>{/if}
      <PaperStatement {claim} {paper} symbols={links.map((l) => ({ tex: l.symbol.tex, id: l.id }))} active={litSymbols} {onsym} />
      {#if editable && !simple && claim.statement_tex && claim.clauses.some((c) => c.statement)}
        <details class="mklink" bind:open={linking}>
          <summary>Link a symbol to the Lean</summary>
          <p class="small">1. Choose a symbol of the statement:</p>
          <div class="chips">
            {#each candidates(claim.statement_tex) as t}
              <button class="chip" class:on={pickSym === t} data-tex={t} title={t} onclick={() => (pickSym = pickSym === t ? null : t)}><Tex text={"$" + t + "$"} /></button>
            {/each}
          </div>
          <p class="small">2. Click its variable in the Lean statement below, or click inside an expression to select it (again to widen it).
            <label class="small"><input type="checkbox" bind:checked={pickType} /> the symbol is that variable's type</label></p>
          {#if pickSym && pickVar}
            {@const b = pickVar.var != null ? claim.clauses.find((c) => c.spec === pickVar.spec)?.statement?.binders?.[pickVar.var] : null}
            <p class="small">Link <code>{pickSym}</code> to {#if pickVar.at}the selected sub-expression{:else}{pickType ? "the type of" : "the variable"} <code>{b?.name}</code>{/if} of <code>{pickVar.spec}</code>, as
              <input class="who" bind:value={author} placeholder="your name" /></p>
            <button class="act" disabled={!authorId} onclick={() => saveLinkOfSymbol(pickVar.at
              ? { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, at: pickVar.at, by: authorId }
              : { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, [pickType ? "type_of" : "var"]: b?.name, by: authorId })}>Save link{authorId ? " as " + authorId : ""}</button>
          {/if}
          {#each (claim.symbols || []) as l}
            <p class="small"><code>{l.symbol.tex}</code> → {l.lean.at != null ? "sub-expression " + l.lean.at : l.lean.term != null ? "sub-expression " + l.lean.in + "#" + l.lean.term : l.lean.var != null ? "variable " + l.lean.var : "type of binder " + l.lean.binder} of <code>{l.lean.decl}</code>, by {l.by}{l.stale ? " (stale)" : ""}
              <button class="act" onclick={() => saveLinkOfSymbol({ action: "remove", claim: claim.id, tex: l.symbol.tex })}>Remove</button></p>
          {/each}
          {#if linkErr}<p class="bad small">{linkErr}</p>{/if}
        </details>
      {/if}
      {#if links.length && claim.statement_tex}
        {@const shown = links.find((l) => l.id === symActive)}
        <p class="faint small linkby">{#if shown}Symbol correspondence by {shown.by}.{:else}Select an underlined symbol to see its Lean correspondence and author.{/if}</p>
      {/if}
    </section>

    <section class="lean">
      <h2>Readable Lean</h2>
      {#if simple}
        {#if claim.audit}
          <p class="small recorded">As recorded in the published audit{claim.audit.author ? " by " + claim.audit.author : ""}.
            {#if claim.audit.link}<a href={claim.audit.link} target="_blank" rel="noopener">Open this claim in the audit ↗</a>{/if}</p>
        {/if}
        {#each claim.links as l (l.name)}
          <div class="block">
            <p class="decl"><code>{l.name}</code>
              {#if sourceUrl(evidenceIndex, l.path, l.range?.line)}<a class="src-link small" href={sourceUrl(evidenceIndex, l.path, l.range?.line)} target="_blank" rel="noopener" title={sourceTitle(evidenceIndex)}>{sourceLabel(evidenceIndex)}</a>{/if}</p>
            {#if l.statement}<Statement st={l.statement} onref={showDecl} compact selId={selFor(l.name)} onselect={(id) => select(l.name, id)} />{/if}
            {#if claim.links.length > 1}<StatusChip record={l} small />{/if}
            {#if editable}
              <button class="btn ghost" disabled={!!busy} onclick={() => act({ lean: claim.links.filter((x) => x.name !== l.name).map((x) => x.name) }, "unlink")}>Unlink</button>
            {/if}
          </div>
        {:else}
          <p class="muted">Not linked to a Lean declaration.</p>
        {/each}

        {#if claim.suggestions?.some((s) => !claim.links.some((l) => l.name === s.name))}
          <h3>Suggested</h3>
          {#each claim.suggestions.filter((s) => !claim.links.some((l) => l.name === s.name)) as s (s.name)}
            <div class="block suggestion">
              <p class="decl"><code>{s.name}</code> <span class="faint">— {s.why}</span></p>
              {#if s.statement}<Statement st={s.statement} onref={showDecl} compact />{/if}
              {#if editable}
                <div class="row">
                  <button class="btn" disabled={!!busy || !s.kind} onclick={() => act({ lean: [...claim.links.map((x) => x.name), s.name] }, "link")}>Link</button>
                  <button class="btn ghost" disabled={!!busy} onclick={() => act({ reject: [s.name] }, "reject")}>Not this</button>
                </div>
              {:else}
                <p class="faint small">Confirm this suggestion with <code>machinechecked view</code>.</p>
              {/if}
            </div>
          {/each}
        {/if}
        {#if editable}
          <LinkPicker {index} disabled={!!busy} onpick={(name) => act({ lean: [...claim.links.map((x) => x.name), name] }, "link")} />
        {/if}
        {#if busy}<p class="faint small">Saving the link and rebuilding…</p>{/if}
        {#if saveError}<p class="bad small">{saveError}</p>{/if}
      {:else}
        {#each claim.clauses as cl, k (k)}
          <div class="block" class:refuted={cl.state === "refuted"}>
            {#if claim.clauses.length > 1}<p class="cname"><TexInline text={cl.label || cl.name} />{#if cl.corrects}<span class="faint">&nbsp;— corrects “<TexInline text={cl.corrects_label || cl.corrects} />”</span>{/if}</p>{/if}
            {#if clauseNote(cl, claim.clauses.length)}<p class="verdict">{clauseNote(cl, claim.clauses.length)}</p>{/if}
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
            {#if cl.statement}
              <Statement st={cl.statement} spec={cl.spec} onref={showDecl} compact ext={extFor(cl.spec)}
                selId={selFor(cl.spec)} onselect={(id) => select(cl.spec, id)}
                onpinned={(v) => { if (linking) pickVar = v == null ? (pickVar?.spec === cl.spec && pickVar.var != null ? null : pickVar) : { spec: cl.spec, var: v }; }}
                onactive={(v) => (leanActive = v == null ? (leanActive?.spec === cl.spec ? null : leanActive) : { spec: cl.spec, var: v })} />
            {:else if cl.defs?.length}
              <p class="defs">{#each cl.defs as d, i}{#if i}, {/if}<button class="ref" onclick={() => showDecl(d)}>{d}</button>{/each}</p>
            {/if}
          </div>
        {:else}
          <p class="muted">No Lean statement has been written for this claim.</p>
        {/each}
      {/if}
    </section>
    <section class="exact-pane">
      <h2>Exact Lean</h2>
      {#if simple}
        {#each claim.links || [] as l}<ExactLean st={l.statement} name={l.name} onref={showDecl} selId={selFor(l.name)} onselect={(id) => select(l.name, id)} />{:else}<p class="muted">Choose a Lean declaration to compare.</p>{/each}
      {:else}
        {#each claim.clauses || [] as cl}
          {#if cl.statement}<ExactLean st={cl.statement} name={cl.spec} onref={showDecl} selId={selFor(cl.spec)} onselect={(id) => select(cl.spec, id)} />
          {:else if cl.defs?.length}{#each cl.defs as name}<Decl {name} key={claim.decls?.[name]} index={evidenceIndex} inspector onref={showDecl} />{/each}{/if}
        {/each}
      {/if}
    </section>
    </div>
    </div>
  </article>
{/if}

{#snippet details()}
  <section class="details">
    <h2>Audit details</h2>
    <StatusChip record={claim} />
    {#if claim.audit?.author}<p class="small">Audit by {claim.audit.author}</p>{/if}
    {#if claim.audit?.detail}<p class="small">{claim.audit.detail}</p>{/if}
    <p class="faint small"><code>{claim.id}</code>{#if index.papers.length > 1} · paper {claim.paper}{/if}</p>
    {#if claim.number_note}<p class="summary">{claim.number} <span class="faint">({claim.number_note})</span></p>{/if}
    {#if claim.scope_note}<p class="muted small">{claim.scope_note}</p>{/if}
    {#if simple}
      <Ladder evidence={{ source: claim.source_evidence }} />
      {#each claim.links as l (l.name)}
        <h3><code>{l.name}</code></h3>
        <p class="small">{statusView(l).explanation}</p>
        {#if l.status_detail}<p class="small">{l.status_detail}</p>{/if}
        <p class="faint small">{l.source === "paper" ? "Linked by a \\lean{…} tag in the paper's source" : l.source === "formalization.yaml" ? "Declared in the project's formalization.yaml" + (index.formalization?.review_status ? ` (the project describes its review as “${index.formalization.review_status}”)` : "") : "Linked in the reader (machinechecked.links.json)"}{#if l.repository} · {l.repository}{/if}{#if l.module} · {l.module}{l.range ? ":" + l.range.line : ""}{/if}</p>
      {/each}
    {:else}
      {#if claim.blockers?.length}
        <h3>Checks and evidence</h3>
        <ul class="small">{#each claim.blockers as b}<li><TexInline text={b} /></li>{/each}</ul>
      {/if}
      {#each claim.clauses as cl, k (k)}
        <h3>{#if claim.clauses.length > 1}<TexInline text={cl.label || cl.name} />{:else}Evidence{/if}</h3>
        <Ladder evidence={cl.evidence} />
        {#if cl.proofs && Object.keys(cl.proofs).length}
          <dl class="proof">
            {#each Object.entries(cl.proofs) as [kind, p]}
              {#if p}
                <dt>{kind === "refute" ? "Refutation" : "Proof"}</dt>
                <dd><code>{p.name}</code> <span class="faint">— axioms: {p.axioms.length ? p.axioms.join(", ") : "none"}</span></dd>
              {/if}
            {/each}
          </dl>
        {/if}
        {#if cl.witness_record}
          <p class="small">Witness <code>{cl.witness}</code>:</p>
          <Statement st={{ binders: [], conclusion: cl.witness_record.type }} onref={showDecl} compact />
        {/if}
        {#if cl.regimes?.length}
          <ul class="small">
            {#each cl.regimes as r}<li>{r.discharged ? "covered" : "not shown"}: {r.name}{#if r.description} — {r.description}{/if}</li>{/each}
          </ul>
        {/if}
        {#if cl.spec_review}
          {#each cl.spec_review.current as r}
            <div class="review">
              <p class="small"><strong>{r.by}</strong> <span class="pill">{r.kind === "ai" ? "AI" : r.kind === "human" ? "human" : "kind not recorded"}</span> <span class="pill">{r.provenance}</span></p>
              {#if r.text}<pre class="rtext">{r.text}</pre>{/if}
            </div>
          {:else}
            <p class="muted small">The proposition has no current review.</p>
          {/each}
        {/if}
        {#if cl.def_reviews && Object.keys(cl.def_reviews).length}
          {@const entries = Object.entries(cl.def_reviews).sort((a, b) => RANK[a[1].state] - RANK[b[1].state] || a[0].localeCompare(b[0]))}
          {@const counts = entries.reduce((m, [, r]) => ((m[r.state] = (m[r.state] || 0) + 1), m), {})}
          <p class="small muted">Definitions its meaning depends on: {Object.entries(counts).map(([k, v]) => `${v} ${evidenceView("review", { state: k }).word}`).join(", ")}</p>
        {/if}
      {/each}
    {/if}
    {#if claim.statement_tex && paper?.pdf && claim.anchor?.begin}
      <h3>Source text</h3>
      <Tex text={claim.statement_tex} />
      {#if claim.anchor?.file}<p class="faint small"><code>{claim.anchor.file}:{claim.anchor.line}</code>
        {#if claim.anchor.kind === "approximate"} · located approximately{/if}
        {#if claim.source_matches === false}<span class="bad"> · differs from the frozen inventory</span>{/if}</p>{/if}
    {/if}
    {#if Object.keys(claim.decls || {}).length}
      {@const ds = Object.keys(claim.decls || {})}
      <h3>Definitions ({ds.length})</h3>
      {#each ds as n (n)}
        {#if ds.length <= 40 || showAll}
          <Decl name={n} key={claim.decls[n]} index={evidenceIndex} onref={showDecl} />
        {/if}
      {/each}
      {#if ds.length > 40 && !showAll}
        <button class="btn ghost" onclick={() => (showAll = true)}>Show all {ds.length}</button>
      {/if}
    {/if}
    {#if claim.findings?.length}
      <h3>Findings</h3>
      <Findings findings={claim.findings} />
    {/if}
    <p class="faint small foot">
      Release <code>{evidenceIndex.release}</code> · evidence <code title={evidenceIndex.evidence}>{evidenceIndex.evidence.slice(0, 12)}</code>
      {#if evidenceIndex.lean}· Lean {evidenceIndex.lean.lean}{/if}
      {#if evidenceIndex.project?.commit}· project <code>{evidenceIndex.project.commit.slice(0, 12)}</code>{/if}
    </p>
  </section>
{/snippet}

<style>
  .comparison-grid { display: grid; gap: 24px; min-width: 0; }
  .comparison-grid > section { min-width: 0; }
  .comparison .comparison-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: start; }
  .comparison .comparison-grid > section { padding: 0 18px; border-left: 1px solid var(--border); }
  .comparison .comparison-grid > section:first-child { padding-left: 0; border: 0; }
  @media (max-width: 1250px) and (min-width: 851px) {
    .comparison .comparison-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .comparison .paper { grid-row: span 2; }
  }
  @media (max-width: 850px) {
    .comparison .comparison-grid { grid-template-columns: minmax(0, 1fr); }
    .comparison .comparison-grid > section { padding: 0; border: 0; }
  }
  .passport, .view { display: flex; flex-direction: column; gap: 18px; }
  .view[hidden] { display: none; }
  .crumbs { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; font-size: 13px; color: var(--muted); }
  .back { font: inherit; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .crumb { border: 0; background: none; padding: 0; font: inherit; color: var(--accent); cursor: pointer; }
  .trail { overflow-wrap: anywhere; }
  .here { color: var(--text); }
  header h1 { font-family: var(--serif); font-size: 24px; font-weight: 600; margin: 2px 0 10px; }
  .full header h1 { font-size: 30px; }
  .title { font-weight: 450; }
  .coverage { border-left: 3px solid var(--border); padding: 4px 0 4px 10px; margin-top: 8px; }
  .coverage p { margin: 2px 0; }
  .coverage[data-coverage="partial"], .coverage[data-coverage="changed"], .coverage[data-coverage="related"] { border-left-color: var(--tier-warning); }
  .coverage[data-coverage="full"] { border-left-color: var(--st-proved); }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; text-decoration: none; }
  .act:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .summary { margin: 4px 0 8px; font-size: 13px; color: var(--muted); }
  .desc { margin: 2px 0 10px; font-size: 15px; color: var(--muted); line-height: 1.5; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 8px; }
  h3 { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .block { margin-bottom: 14px; }
  .block.refuted { border-left: 3px solid var(--st-refuted); padding-left: 10px; }
  .block.suggestion { border: 1px dashed var(--border); border-radius: 8px; padding: 8px 10px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .grow { flex: 1; }
  .chipbtn { border: 0; background: none; padding: 4px 0; cursor: pointer; }
  .menuwrap { position: relative; }
  .more { font-size: 15px; line-height: 1; padding: 3px 9px; }
  .menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 10; min-width: 200px; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 6px 20px rgb(0 0 0 / 0.14); padding: 4px; }
  .menu > a, .menu > button { text-align: left; font: inherit; font-size: 14px; padding: 7px 10px; border: 0; background: none; color: var(--text); border-radius: 6px; cursor: pointer; text-decoration: none; }
  .menu > a:hover, .menu > button:hover { background: var(--surface-2); }
  .copied { margin: 4px 0 0; }
  .linkby { margin: 4px 0 0; }
  .recorded { margin: 0 0 8px; }
  .mklink { margin-top: 8px; border: 1px dashed var(--border); border-radius: 8px; padding: 6px 10px; }
  .mklink > summary { cursor: pointer; font-size: 13px; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { border: 1px solid var(--border); background: var(--surface); border-radius: 6px; padding: 0 6px; cursor: pointer; }
  .chip.on { border-color: var(--accent); background: var(--accent-soft); }
  .chip :global(.tex) { border: 0; padding: 0; margin: 0; background: none; font-size: 15px; }
  .who { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 12em; }
  .defs { margin: 0; }
  .details h2 { margin-bottom: 4px; }
  .cname { font-weight: 600; margin: 0 0 8px; }
  .changes { border-left: 3px solid var(--st-open, #b7791f); background: var(--surface-2, transparent); padding: 6px 10px; margin: 0 0 10px; border-radius: 0 6px 6px 0; }
  .changes p { margin: 0 0 4px; }
  .changes ul { margin: 0; padding-left: 18px; }
  .changes code { font-size: 12px; }
  .src-link { margin-left: 8px; white-space: nowrap; }
  .decl { margin: 0 0 6px; overflow-wrap: anywhere; }
  .verdict { margin: 10px 0 0; font-size: 14px; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: var(--on-accent); border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 13px; margin-top: 8px; }
  .row .btn { margin-top: 0; }
  .btn.ghost { background: transparent; color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .small { font-size: 13px; }
  .bad { color: var(--st-malformed); }
  .proof { margin: 10px 0 0; }
  .proof dt { font-size: 12px; color: var(--muted); }
  .proof dd { margin: 0 0 6px; }
  .review { border-left: 3px solid var(--border); padding-left: 10px; margin: 8px 0; }
  .pill { font-size: 11px; padding: 0 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: 4px; }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 6px 0 0; }
  .ref { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-family: var(--mono); font-size: 0.92em; max-width: 100%; text-align: left; overflow-wrap: anywhere; }
  .foot { margin-top: 16px; }
  @media (max-width: 700px) {
    .passport, .view { gap: 12px; }
    header h1 { font-size: 20px; margin: 0 0 6px; }
    .desc { font-size: 14px; margin: 0 0 6px; }
    .act { font-size: 12px; padding: 2px 8px; }
    .passport h2 { margin-bottom: 4px; }
  }
</style>
