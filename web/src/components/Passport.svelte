<script>
  import { claimLink, claimReference, issueUrl, reportsUrl, sourceUrl, sourceLabel, sourceTitle } from "../lib/issue.js";
  import TexInline from "./TexInline.svelte";
  import { loadClaim, loadSearch, saveLink, saveSymbol, inProject } from "../lib/data.js";
  import { project } from "../lib/project.svelte.js";
  import { href } from "../lib/route.svelte.js";
  import StatusChip from "./StatusChip.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import Statement from "./Statement.svelte";
  import Ladder from "./Ladder.svelte";
  import Findings from "./Findings.svelte";
  import Decl from "./Decl.svelte";
  import Tex from "./Tex.svelte";
  import LinkPicker from "./LinkPicker.svelte";
  import { tick } from "svelte";

  // One claim as Paper and Lean: a heading, the status the engine computed, the printed
  // statement and the Lean statement. Everything else (reviews, evidence, provenance) is in the
  // audit details, which open in the inspector like a declaration does.
  let { index, claimId, full = false, editable = false } = $props();

  let loaded = $state(null);
  // On a page with several projects, the claim as the chosen one sees it.
  const claim = $derived(loaded && index.projects ? inProject(loaded, project.repo) : loaded);
  let error = $state(null);
  // The inspector: the declarations opened from this claim, in order. While it is not empty the
  // last one replaces the claim view, which stays mounted (hidden) so its open sections and
  // scroll position come back on Back.
  let stack = $state([]);
  let scrolls = [];
  let article = $state();
  let showAll = $state(false);
  let menu = $state(false);
  const DETAILS = "@details";
  let busy = $state(null);
  let saveError = $state(null);
  const RANK = { stale: 0, pending: 1, "author-reviewed": 2, reviewed: 3 };

  $effect(() => {
    claimId;
    loaded = null; error = null; stack = []; scrolls = []; showAll = false; saveError = null; menu = false;
    loadClaim(index, claimId).then((c) => (loaded = c)).catch((e) => (error = String(e)));
  });

  const paper = $derived(claim && index.papers.find((p) => p.id === claim.paper));
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
  let search = null;
  async function paperOf(name) {
    search ??= await loadSearch(index).catch(() => ({ claims: [], decls: [] }));
    const ids = search.decls?.find((d) => d.name === name)?.claims || [];
    const linked = (search.claims || []).filter((c) => ids.includes(c.id) && (c.lean || []).includes(name)).map((c) => c.id);
    const meta = index.claims.find((c) => linked.includes(c.id) && c.kind === "definition" && c.anchor);
    const rec = meta && (await loadClaim(index, meta.id).catch(() => null));
    return rec?.anchor?.begin ? rec : null;
  }

  async function showDecl(name) {
    menu = false;
    if (stack[stack.length - 1] === name) return;
    scrolls[stack.length] = scroller().scrollTop;
    stack = [...stack, name];
    await tick();
    const sc = scroller(), top = article.getBoundingClientRect().top - (sc === document.scrollingElement ? 0 : sc.getBoundingClientRect().top);
    if (top < 0) sc.scrollTop += top;
  }

  // Back to level `n` (0 is the claim), restoring that level's scroll position.
  async function backTo(n) {
    menu = false;
    stack = stack.slice(0, n);
    await tick();
    scroller().scrollTop = scrolls[n] ?? 0;
  }

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

  // A sentence under a clause only when it adds to the status chip: a check that fails, a
  // statement or proof that is missing, or, with several clauses, what each one establishes.
  function note(cl) {
    if (claim.clauses.length > 1) return verdict(cl, false);
    const ch = cl.checks || {};
    const p = ch.accept || ch.refute;
    if (["unchecked", "unspecified"].includes(cl.state)) return verdict(cl);
    if (cl.state !== "stated" && (!p || !p.ok)) return verdict(cl);
    return null;
  }

  // One line on what the Lean side of a clause establishes, in words.
  // `review` adds how its meaning was reviewed, which the audit details say and the main view
  // leaves to them.
  function verdict(cl, review = true) {
    const ch = cl.checks || {};
    const p = ch.accept || ch.refute;
    if (cl.state === "unchecked") return "The Lean project was not checked in this build.";
    if (cl.state === "unspecified") return "No Lean statement has been written for it yet.";
    if (cl.state === "stated") return "Stated in Lean as definitions.";
    if (!p) return "A Lean statement exists; it has no proof yet.";
    if (!p.ok) return "The Lean proof fails a check: " + p.errors.join(", ") + ".";
    const replay = ch.replay?.state === "pass" ? ", replayed independently" : "";
    const rev = { reviewed: "its meaning reviewed independently", "author-reviewed": "its meaning reviewed only by its author", pending: "its meaning not yet reviewed" }[cl.review] || "";
    return (cl.state === "refuted" ? "Lean proves the printed statement false" : "Proved in Lean") + replay + (rev && review ? "; " + rev : "") + ".";
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

  // The sentence under a link restates the status the engine computed for it, and nothing more.
  function linkVerdict(l) {
    const s = l.status || "";
    if (s.includes("no audit")) return "Declared by the project; Lean has not been run on it here, and no audit of this formalisation is published, so whether it is proved, and whether it says what the paper says, is not shown.";
    if (s.includes("not checked")) return "Lean has not been run on it here: the project is not built, so whether it is proved is not known.";
    if (s.includes("not found")) return "Not found in the built modules.";
    if (s.includes("definition")) return `A Lean ${l.kind || "definition"}.`;
    if (s.includes("incomplete")) return "Its Lean proof is incomplete (it uses sorry).";
    if (s.includes("further axioms")) return "Its proof uses axioms beyond the standard three: " + (l.axioms || []).join(", ") + ".";
    if (s === "linked: Lean proof checked") return "Proved in Lean. Whether it says what the paper says has not been reviewed.";
    return s;
  }

  // A check or piece of evidence the claim lacks, said as what it is: an independent replay is
  // a further check, not a condition of acceptance.
  function describe(b) {
    if (/^no independent kernel replay/.test(b)) return "Independent replay: not recorded (" + b.replace(/^no independent kernel replay:?\s*/, "") + ")";
    return b;
  }
</script>

{#snippet crop(c)}
  {@const pp = index.papers.find((p) => p.id === c.paper)}
  {#if (pp?.pdf || pp?.pdf_url) && c.anchor?.begin}
    <PdfCrop url={pp.pdf_url || "data/" + pp.pdf} anchor={c.anchor} />
  {/if}
{/snippet}

{#if error}
  <p>{error}</p>
{:else if !claim}
  <p class="muted">Loading…</p>
{:else}
  <article class="passport" class:full bind:this={article}>
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
          <Decl name={top} key={claim.decls?.[top] ?? null} inspector onref={showDecl} />
        {/if}
      {/key}
    {/if}
    <div class="view" hidden={stack.length > 0}>
    <header>
      <h1>{claim.number || claim.id}{#if claim.heading}<span class="title">&nbsp;— <TexInline text={claim.heading} /></span>{/if}</h1>
      {#if !claim.heading && claim.title}<p class="desc"><TexInline text={claim.title} /></p>{/if}
      <div class="bar">
        <button class="chipbtn" onclick={() => showDecl(DETAILS)} title="Audit details: what this status rests on"><StatusChip status={claim.status} cls={claim.class} /></button>
        <span class="grow"></span>
        {#if issueUrl(index, claim)}
          <a class="act" href={issueUrl(index, claim)} target="_blank" rel="noopener" title={"Opens a draft issue in " + index.issues + " with this claim's details filled in"}>Report issue ↗</a>
        {/if}
        <span class="menuwrap">
          <button class="act more" aria-haspopup="menu" aria-expanded={menu} aria-label="More" onclick={() => (menu = !menu)}>⋯</button>
          {#if menu}
            <div class="menu" role="menu">
              {#if !full}<a role="menuitem" href={href(index.release, "claim", claim.id)}>Open as a page</a>{/if}
              {#if full && meta?.anchor}<a role="menuitem" href={href(index.release, "read", claim.paper, claim.id)}>Show in the paper</a>{/if}
              <button role="menuitem" onclick={() => { copyLink(); menu = false; }}>{claimLink(index, claim) ? "Copy link" : "Copy reference"}</button>
              {#if reportsUrl(index, claim)}<a role="menuitem" href={reportsUrl(index, claim)} target="_blank" rel="noopener">View existing reports ↗</a>{/if}
              {#if index.review_queue && claim.scope !== "out-of-scope" && !String(claim.status).startsWith("out of scope")}
                <a role="menuitem" href={href(index.release, "review")}>Review it</a>
              {/if}
              <button role="menuitem" onclick={() => showDecl(DETAILS)}>Audit details</button>
            </div>
          {/if}
        </span>
      </div>
      {#if copied}<p class="faint small copied">{copied}</p>{/if}
    </header>

    <section class="paper">
      <h2>Paper</h2>
      {#if (paper?.pdf || paper?.pdf_url) && claim.anchor?.begin}
        <PdfCrop url={paper.pdf_url || "data/" + paper.pdf} anchor={claim.anchor} />
      {:else if claim.statement_tex}
        <Tex text={claim.statement_tex} />
      {:else}
        <p class="muted small">The printed statement is not part of this site.</p>
      {/if}
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
            <p class="small">Link <code>{pickSym}</code> to {#if pickVar.term}the selected sub-expression{:else}{pickType ? "the type of" : "the variable"} <code>{b?.name}</code>{/if} of <code>{pickVar.spec}</code>, as
              <input class="who" bind:value={author} placeholder="your name" /></p>
            <button class="act" disabled={!authorId} onclick={() => saveLinkOfSymbol(pickVar.term
              ? { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, term: pickVar.term.where + "#" + pickVar.term.k, by: authorId }
              : { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, [pickType ? "type_of" : "var"]: b?.name, by: authorId })}>Save link{authorId ? " as " + authorId : ""}</button>
          {/if}
          {#each (claim.symbols || []) as l}
            <p class="small"><code>{l.symbol.tex}</code> → {l.lean.term != null ? "sub-expression " + l.lean.in + "#" + l.lean.term : l.lean.var != null ? "variable " + l.lean.var : "type of binder " + l.lean.binder} of <code>{l.lean.decl}</code>, by {l.by}{l.stale ? " (stale)" : ""}
              <button class="act" onclick={() => saveLinkOfSymbol({ action: "remove", claim: claim.id, tex: l.symbol.tex })}>Remove</button></p>
          {/each}
          {#if linkErr}<p class="bad small">{linkErr}</p>{/if}
        </details>
      {/if}
      {#if links.length && claim.statement_tex}
        <Tex text={claim.statement_tex} symbols={links.map((l) => ({ tex: l.symbol.tex, id: l.id }))} active={litSymbols} {onsym} />
        {@const shown = links.find((l) => l.id === symActive)}
        <p class="faint small linkby">{#if shown}Linked by {shown.by}: their reading of the symbol, not a check.{:else}Underlined symbols are linked to the Lean below, each by a named person; point at one to see what it is linked to.{/if}</p>
      {/if}
    </section>

    <section class="lean">
      <h2>Lean</h2>
      {#if simple}
        {#each claim.links as l (l.name)}
          <div class="block">
            <p class="decl"><code>{l.name}</code>
              {#if sourceUrl(index, l.path, l.range?.line)}<a class="src-link small" href={sourceUrl(index, l.path, l.range?.line)} target="_blank" rel="noopener" title={sourceTitle(index)}>{sourceLabel(index)}</a>{/if}</p>
            {#if l.statement}<Statement st={l.statement} onref={showDecl} compact />{:else}<p class="verdict">{linkVerdict(l)}</p>{/if}
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
                <p class="faint small">A suggestion, not a link. Run <code>machinechecked view</code> to confirm it.</p>
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
            {#if note(cl)}<p class="verdict">{note(cl)}</p>{/if}
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
                onpinned={(v) => { if (linking) pickVar = v == null ? (pickVar?.spec === cl.spec && pickVar.var != null ? null : pickVar) : { spec: cl.spec, var: v }; }}
                onterm={(t) => { if (linking) pickVar = t == null ? (pickVar?.spec === cl.spec && pickVar.term ? null : pickVar) : { spec: cl.spec, term: t }; }}
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
    </div>
  </article>
{/if}

{#snippet details()}
  <section class="details">
    <h2>Audit details</h2>
    <p class="faint small"><code>{claim.id}</code>{#if index.papers.length > 1} · paper {claim.paper}{/if}</p>
    {#if claim.number_note}<p class="summary">{claim.number} <span class="faint">({claim.number_note})</span></p>{/if}
    {#if claim.scope_note}<p class="muted small">{claim.scope_note}</p>{/if}
    {#if simple}
      {#each claim.links as l (l.name)}
        <h3><code>{l.name}</code></h3>
        <p class="small">{linkVerdict(l)}</p>
        <p class="faint small">{l.source === "paper" ? "Linked by a \\lean{…} tag in the paper's source" : l.source === "formalization.yaml" ? "Declared in the project's formalization.yaml" + (index.formalization?.review_status ? ` (the project describes its review as “${index.formalization.review_status}”)` : "") : "Linked in the reader (machinechecked.links.json)"}{#if l.repository} · {l.repository}{/if}{#if l.module} · {l.module}{l.range ? ":" + l.range.line : ""}{/if}</p>
      {/each}
    {:else}
      {#if claim.blockers?.length}
        <h3>Checks and evidence</h3>
        <ul class="small">{#each claim.blockers as b}<li><TexInline text={describe(b)} /></li>{/each}</ul>
      {/if}
      {#each claim.clauses as cl, k (k)}
        <h3>{#if claim.clauses.length > 1}<TexInline text={cl.label || cl.name} />{:else}Evidence{/if}</h3>
        <p class="small">{verdict(cl)}</p>
        <Ladder rungs={cl.ladder} />
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
          <p class="small muted">Definitions its meaning depends on: {Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(", ")}</p>
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
          <Decl name={n} key={claim.decls[n]} onref={showDecl} />
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
      Release <code>{index.release}</code> · evidence <code title={index.evidence}>{index.evidence.slice(0, 12)}</code>
      {#if index.lean}· Lean {index.lean.lean}{/if}
      {#if index.project?.commit}· project <code>{index.project.commit.slice(0, 12)}</code>{/if}
    </p>
  </section>
{/snippet}

<style>
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
  .chipbtn { border: 0; background: none; padding: 0; cursor: pointer; }
  .menuwrap { position: relative; }
  .more { font-size: 15px; line-height: 1; padding: 3px 9px; }
  .menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 10; min-width: 200px; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 6px 20px rgb(0 0 0 / 0.14); padding: 4px; }
  .menu > a, .menu > button { text-align: left; font: inherit; font-size: 14px; padding: 7px 10px; border: 0; background: none; color: var(--text); border-radius: 6px; cursor: pointer; text-decoration: none; }
  .menu > a:hover, .menu > button:hover { background: var(--surface-2); }
  .copied { margin: 4px 0 0; }
  .linkby { margin: 4px 0 0; }
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
  .verdict.top { margin: 0 0 8px; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: white; border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 13px; margin-top: 8px; }
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
