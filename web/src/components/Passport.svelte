<script>
  import { claimLink, claimReference, issueUrl, reportsUrl } from "../lib/issue.js";
  import TexInline from "./TexInline.svelte";
  import { loadClaim, saveLink, saveSymbol, shownClaim, auditOf } from "../lib/data.js";
  import { project } from "../lib/project.svelte.js";
  import { counterpartViews } from "../lib/versions.js";
  import { href, withQuery } from "../lib/route.svelte.js";
  import { statusView, inScope, evidenceView } from "../lib/presentation.js";
  import { coverageView, recordedBasisText } from "../lib/coverage.js";
  import { comparisonInputs, pinScope } from "../lib/comparison.js";
  import { openInspection, DETAILS } from "../lib/inspect.svelte.js";
  import EvidenceSummary from "./EvidenceSummary.svelte";
  import StatusChip from "./StatusChip.svelte";
  import Statement from "./Statement.svelte";
  import Comparison from "./Comparison.svelte";
  import Ladder from "./Ladder.svelte";
  import Findings from "./Findings.svelte";
  import Decl from "./Decl.svelte";
  import Tex from "./Tex.svelte";
  import LinkPicker from "./LinkPicker.svelte";
  import ProofStep from "./ProofStep.svelte";
  import Investigation from "./Investigation.svelte";
  import ProofFacts from "./ProofFacts.svelte";
  import PublishedWork from "./PublishedWork.svelte";
  import { VERDICTS } from "../lib/review.js";
  import { occurrenceCount } from "../lib/symbolmarks.js";
  import { tick } from "svelte";

  // One claim as Paper and Lean: a heading, the status the engine computed, and the comparison
  // of the printed statement with its Lean (Comparison.svelte), which the review page shares.
  // Everything else (reviews, evidence, provenance) is in the audit details, which open above the
  // comparison like an inspection, the comparison staying where it is.
  let { index, claimId, full = false, editable = false, comparison = false } = $props();

  let loaded = $state(null);
  // On a page with several projects, the claim as the chosen project (or the audit that maps it,
  // with the audits shown together) sees it.
  const claim = $derived(loaded && index.projects ? shownClaim(loaded) : loaded);
  // The audit whose evidence the claim shows, on a paper page, for its attribution.
  const source = $derived(claim?.evidence_from ? auditOf(index, claim.evidence_from) : null);
  let error = $state(null);
  let article = $state();
  let showAll = $state(false);
  let menu = $state(false), menuWrap = $state(), menuButton = $state();
  let attempt = $state(0);
  const VERDICT_LABEL = Object.fromEntries(Object.values(VERDICTS).flat().map((v) => [v.value, v.label]));
  function reviewer(r) {
    const who = r.reviewer.kind === "model" ? "the AI model " + (r.reviewer.model || r.reviewer.id)
      : (r.reviewer.name || r.reviewer.id);
    return who + (r.reviewer.identity === "self-declared" ? " (self-declared)" : "");
  }
  let busy = $state(null);
  let saveError = $state(null);
  const RANK = { stale: 0, pending: 1, "author-reviewed": 2, reviewed: 3 };

  // The claim, project and release shown: a selection names an expression of this claim's
  // statements in this build, so it is cleared when any of them changes.
  let shownKey = null;
  $effect(() => {
    claimId; project.repo; project.combined; attempt;
    let current = true;
    loaded = null; error = null; showAll = false; saveError = null; menu = false;
    const key = [claimId, project.repo, project.combined, index.release].join("\u0000");
    if (key !== shownKey) {
      shownKey = key;
      selAt = null; pickVar = null; pickSym = null; marking = null;
    }
    loadClaim(index, claimId).then((c) => { if (current) loaded = c; }).catch((e) => { if (current) error = String(e); });
    return () => { current = false; };
  });

  const paper = $derived(claim?.audit?.paper || (claim && index.papers.find((p) => p.id === claim.paper)));
  const evidenceIndex = $derived(claim?.audit?.context ? { ...index, ...claim.audit.context, papers: [paper] } : index);
  const meta = $derived(index.claims.find((c) => c.id === claimId));
  // The claim in the other versions of the paper, from the site's claim map.
  const counterparts = $derived(counterpartViews(index, meta, project.combined ? null : project.repo));
  const simple = $derived(claim?.mode === "simple");
  // A paper page that cannot show the PDF an audit read joins its statements to the audit's
  // entries by printed number, and records it on the claim's audit record (`matched`).
  const matched = $derived(claim?.audit?.matched?.by === "number" ? claim.audit.matched : null);
  // The comparison draws the claim as the reader shows it; pins belong to this claim, this
  // project and this build.
  const inputs = $derived(claim ? comparisonInputs("reading", [claim]) : null);
  const scope = $derived(claim ? pinScope(index, claim.id, claim.evidence_from || project.repo) : null);

  // Symbol links (docs/SYMBOL_LINKS.md) are drawn by the comparison; why one is not drawn comes
  // from the reasons the build records (`stale_because`).
  const STALE = {
    statement: "the Lean statement changed since it was made",
    source: "the paper's text changed since it was made",
    excerpt: "the typeset passage changed since it was made",
    missing: "the Lean statement no longer has the object it names",
    target: "the Lean object at its place is a different one now",
    unpinned: "it was made without the text of its Lean object",
    positional: "it names its Lean object by place and number in an earlier display",
    ids: "it was made with an earlier scheme of identities",
  };
  const staleWhy = (l) => (l.stale_because || []).map((c) => STALE[c] || c).join("; ") || "what it relates changed";

  // Making a symbol link in the local reader (full assessment, editable): choose a symbol of the
  // claim's mathematics, then click its variable in the Lean statement, and save it under a name.
  const GREEK = "alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|tau|upsilon|phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega";
  function candidates(tex) {
    const math = (tex || "").match(/\$\$[\s\S]*?\$\$|\$[\s\S]*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g) || [];
    const re = new RegExp(`\\\\(?:mathbb|mathcal|mathfrak|mathscr|mathrm|boldsymbol)\\s*\\{?[A-Za-z]\\}?(?:\\^\\{?[A-Za-z0-9]+\\}?)?|\\\\(?:${GREEK})(?![A-Za-z])|(?<![\\\\A-Za-z])[A-Za-z](?![A-Za-z])`, "g");
    return [...new Set(math.flatMap((m) => m.match(re) || []))];
  }
  // The sub-term selected in the comparison, by its identity in one statement ({spec, id}).
  let selAt = $state(null);
  // The applications a warning is about, marked in its clause's statement ({subject, at, what}),
  // and whether the view still has to scroll to them.
  let marking = $state(null);
  let markScroll = $state(false);
  const markFor = (k) => (marking && marking.subject === `${claim.id}#${k}` ? marking.at : null);
  function showOccurrences(f) {
    const occ = (f.occurrences || []).filter((o) => o.state !== "none" && o.at?.length);
    marking = { subject: f.subject, at: occ.flatMap((o) => o.at),
                what: [...new Set(occ.map((o) => o.type).filter(Boolean))].join(", ") };
    markScroll = true;
  }
  $effect(() => {
    if (!markScroll || !article) return;
    markScroll = false;
    tick().then(() => article?.querySelector(".lean .mk")?.scrollIntoView({ block: "center" }));
  });
  let linking = $state(false);
  let pickSym = $state(null);
  let pickVar = $state(null);
  let pickType = $state(false);
  // The selection in the Lean is the link's Lean side while a link is being made.
  $effect(() => {
    const s = selAt;
    if (!linking) return;
    if (s) pickVar = { spec: s.spec, at: s.id };
    else if (pickVar?.at) pickVar = null;
  });
  function pinnedVar(spec, v, name) {
    if (!linking) return;
    pickVar = v == null ? (pickVar?.spec === spec && pickVar.var != null ? null : pickVar) : { spec, var: v, name };
  }
  // A symbol printed several times may stand for several objects of the paper: a link may take
  // only some occurrences (numbered from 1 in reading order), which are then one object, named.
  let pickOcc = $state([]);
  let pickObj = $state("");
  const occCount = $derived(pickSym && claim?.excerpt?.ready ? occurrenceCount(claim.excerpt, pickSym) : 0);
  $effect(() => { pickSym; pickOcc = []; });
  const symbolText = (s) => s.tex + (s.object ? ` (${s.object})` : "") +
    (Array.isArray(s.occurrence) ? ` at occurrence ${s.occurrence.join(", ")} of ${s.of}` : "");
  const paperSide = () => ({ ...(pickOcc.length ? { occurrences: [...pickOcc].sort((a, b) => a - b) } : {}),
    ...(pickObj.trim() ? { object: pickObj.trim() } : {}) });
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

  // A declaration named in the header or in the audit details opens above the comparison; from
  // inside the details it continues their trail.
  function showDecl(name, nested = false) {
    menu = false;
    openInspection(name, "top", { nested });
  }
  const inDetails = (name) => showDecl(name, true);
  function details() { menu = false; openInspection(DETAILS, "top"); }
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

<!-- The Lean's references to the paper's numbers that disagree with the paper read here. The list
     is not keyed by id, which audits written by older engines repeat for a repeated reference. -->
{#snippet paperNumbers()}
  {#if claim.references?.some((o) => o.status !== "exact" || o.stale_lead)}
    <h3>Paper numbers in the Lean</h3>
    <ul class="reasons small">
      {#each claim.references.filter((o) => o.status !== "exact" || o.stale_lead) as o}<li>{o.message}</li>{/each}
    </ul>
  {/if}
{/snippet}

<!-- Under the paper's passage: the review of a proof step, and making a symbol link. -->
{#snippet paperTools()}
  {#if claim.step}<ProofStep {claim} {index} part="finding" />{/if}
  {#if editable && !simple && claim.statement_tex && claim.clauses.some((c) => c.statement || c.defs?.length)}
    <details class="mklink" bind:open={linking}>
      <summary>Link a symbol to the Lean</summary>
      <p class="small">1. Choose a symbol of the statement:</p>
      <div class="chips">
        {#each candidates(claim.statement_tex) as t}
          <button class="chip" class:on={pickSym === t} data-tex={t} title={t} onclick={() => (pickSym = pickSym === t ? null : t)}><Tex text={"$" + t + "$"} /></button>
        {/each}
      </div>
      <p class="small">2. Click its variable in the Lean statement, or click inside an expression to select it (again to widen it).
        <label class="small"><input type="checkbox" bind:checked={pickType} /> the symbol is that variable's type</label></p>
      {#if pickSym && occCount > 1}
        <p class="small occ">It occurs {occCount} times; link only occurrences
          {#each Array.from({ length: occCount }, (_, i) => i + 1) as k}<label><input type="checkbox" data-occ={k} checked={pickOcc.includes(k)} onchange={(e) => (pickOcc = e.currentTarget.checked ? [...pickOcc, k] : pickOcc.filter((x) => x !== k))} /> {k}</label>{/each}
          <span class="faint">(none ticked: every occurrence)</span></p>
        <p class="small"><input class="obj" bind:value={pickObj} placeholder="which object of the paper" aria-label="The object of the paper" />
          <span class="faint">{pickOcc.length ? "the occurrences chosen are this one object; others printed the same are linked apart" : "optional"}</span></p>
      {/if}
      {#if pickSym && pickVar}
        <!-- A variable is sent by its number: two variables can have the same name. -->
        <p class="small">Link <code>{pickSym}</code> to {#if pickVar.at}the selected sub-expression{:else}{pickType ? "the type of" : "the variable"} <code>{pickVar.name}</code>{/if} of <code>{pickVar.spec}</code>, as
          <input class="who" bind:value={author} placeholder="your name" /></p>
        <button class="act" disabled={!authorId || (pickOcc.length && !pickObj.trim())} onclick={() => saveLinkOfSymbol(pickVar.at
          ? { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, at: pickVar.at, by: authorId, ...paperSide() }
          : { action: "add", claim: claim.id, tex: pickSym, decl: pickVar.spec, [pickType ? "type_of" : "var"]: String(pickVar.var), by: authorId, ...paperSide() })}>Save link{authorId ? " as " + authorId : ""}</button>
      {/if}
      {#each (claim.symbols || []) as l}
        <p class="small" data-link={l.symbol.tex} data-object={l.symbol.object}><code>{symbolText(l.symbol)}</code> → {l.lean.at != null ? "sub-expression " + l.lean.at : l.lean.term != null ? "sub-expression " + l.lean.in + "#" + l.lean.term : l.lean.var != null ? "variable " + l.lean.var : "type of binder " + l.lean.binder} of <code>{l.lean.decl}</code>, by {l.by}{l.stale ? " (stale)" : ""}
          <button class="act" onclick={() => saveLinkOfSymbol({ action: "remove", claim: claim.id, tex: l.symbol.tex, ...(l.symbol.object ? { object: l.symbol.object } : {}) })}>Remove</button>
          {#if l.stale}<span class="stale-why">Not shown: {staleWhy(l)}. Link it again{l.stale_because?.includes("statement") || l.stale_because?.includes("ids") ? " after checking the Lean statement" : ""}, or remove it.</span>{/if}</p>
      {/each}
      {#if linkErr}<p class="bad small">{linkErr}</p>{/if}
    </details>
  {/if}
{/snippet}

<!-- Under each linked declaration: its status when the claim links several, and in the local
     reader the facts of its proof and unlinking it. -->
{#snippet linkTools(l, at, role)}
  {#if role === "step"}
    <StatusChip record={l} small />
    {#if editable && simple}<button class="btn ghost" disabled={!!busy} onclick={() => act({ lean: claim.step.links.filter((x) => x.name !== l.name).map((x) => x.name) }, "link")}>Unlink</button>{/if}
  {:else if role === "route"}
    <StatusChip record={l} small />
    {#if editable && simple}<button class="btn ghost" disabled={!!busy} onclick={() => act({ route: claim.step.route.links.filter((x) => x.name !== l.name).map((x) => x.name) }, "route")}>Remove</button>{/if}
  {:else}
    {#if claim.links?.length > 1}<StatusChip record={l} small />{/if}
    {#if editable}
      {#if l.kind === "theorem" || l.kind === "def"}<ProofFacts name={l.name} {claim} onref={(n) => openInspection(n, at)} {at} />{/if}
      <button class="btn ghost" disabled={!!busy} onclick={() => act({ lean: claim.links.filter((x) => x.name !== l.name).map((x) => x.name) }, "unlink")}>Unlink</button>
    {/if}
  {/if}
{/snippet}

<!-- A warning's marks in a clause. -->
{#snippet clauseTools(cl, k)}
  {#if cl.statement && markFor(k)}<p class="small marknote">Marked: the operation this finding is about{marking.what ? ", in " + marking.what : ""}. <button class="act" onclick={() => (marking = null)}>Clear</button></p>{/if}
{/snippet}

<!-- After the Lean: a step's recorded route, suggestions, the paper numbers and linking. -->
{#snippet leanFoot()}
  {#if claim.step}
    <ProofStep {claim} {index} part="route" editable={editable && simple} busy={!!busy}
      onlink={(names) => act({ lean: names }, "link")} onroute={(names) => act({ route: names }, "route")} />
  {:else if simple}
    {#if claim.audit}
      <p class="small recorded">As recorded in the published audit{claim.audit.author ? " by " + claim.audit.author : ""}.
        {#if claim.audit.link}<a href={claim.audit.link} target="_blank" rel="noopener">Open this claim in the audit ↗</a>{/if}</p>
    {/if}
    {#if claim.suggestions?.some((s) => !claim.links.some((l) => l.name === s.name))}
      <h3>Suggested</h3>
      {#each claim.suggestions.filter((s) => !claim.links.some((l) => l.name === s.name)) as s (s.name)}
        <div class="block suggestion">
          <p class="decl"><code>{s.name}</code></p>
          {#if s.reasons?.length}
            <ul class="reasons faint small">{#each s.reasons as r}<li>{r.text}</li>{/each}</ul>
          {:else if s.why}<p class="faint small">{s.why}</p>{/if}
          {#if s.statement}<Statement st={s.statement} onref={(n) => showDecl(n)} compact />{/if}
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
    {@render paperNumbers()}
    {#if editable}
      <LinkPicker {index} {claim} disabled={!!busy} onpick={(name) => act({ lean: [...claim.links.map((x) => x.name), name] }, "link")} />
    {/if}
  {:else}
    {@render paperNumbers()}
  {/if}
  {#if busy}<p class="faint small">Saving the link and rebuilding…</p>{/if}
  {#if saveError}<p class="bad small">{saveError}</p>{/if}
{/snippet}

{#snippet auditDetails()}
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
        <p class="faint small">{l.source === "paper" ? "Linked by a \\lean{…} tag in the paper's source" : l.source === "formalization.yaml" ? "Declared in the project's formalization.yaml" + (index.formalization?.review_status ? ` · project review: “${index.formalization.review_status}”` : "") : "Linked in the reader (machinechecked.links.json)"}{#if l.repository} · {l.repository}{/if}{#if l.module} · {l.module}{l.range ? ":" + l.range.line : ""}{/if}</p>
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
        {#if cl.witness_defs?.length}
          <p class="small">Declarations only its witness uses, without a current review: the instance the witness exhibits is fixed by them.</p>
          <ul class="small witness-defs">
            {#each cl.witness_defs as w (w.name)}<li><button class="ref" onclick={() => inDetails(w.name)}><code>{w.name}</code></button> <span class="faint">— {w.state === "stale" ? "review out of date" : "no review"}</span></li>{/each}
          </ul>
        {/if}
        {#if cl.witness_candidates?.length}
          <p class="small">Declarations only witnesses use that build on this definition: candidates for its mapping.</p>
          <ul class="small witness-candidates">
            {#each cl.witness_candidates as w (w.name)}<li><button class="ref" onclick={() => inDetails(w.name)}><code>{w.name}</code></button> <span class="faint">— uses {w.uses.join(", ")}; used by {w.witnesses.join(", ")}</span></li>{/each}
          </ul>
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
          {#if claim.scope === "definition"}
            {#each entries.filter(([, r]) => r.rests_on?.passages?.length) as [n, r]}
              <p class="faint small rests-on"><code>{n}</code>: the review by {r.rests_on.by} at <code>{r.rests_on.file}:{r.rests_on.line}</code>, which read {r.rests_on.passages.join(", ")}</p>
            {/each}
          {/if}
        {/if}
      {/each}
    {/if}
    {#if (claim.excerpt?.text || claim.statement_tex) && paper?.pdf && claim.anchor?.begin}
      <h3>Source text</h3>
      <pre class="srctext">{claim.excerpt?.text ?? claim.statement_tex}</pre>
      {#if claim.excerpt && !claim.excerpt.ready}<p class="faint small excerpt-why">Shown from the PDF: {claim.excerpt.reasons[0]}.</p>
      {:else if claim.excerpt}<p class="faint small">Typeset from <code>{claim.excerpt.file}</code>, lines {claim.excerpt.start_line}–{claim.excerpt.end_line}{claim.excerpt.revision ? " at revision " + claim.excerpt.revision.slice(0, 12) : ""}.</p>{/if}
      {#if claim.anchor?.file}<p class="faint small"><code>{claim.anchor.file}:{claim.anchor.line}</code>
        {#if claim.anchor.kind === "approximate"} · located approximately{/if}
        {#if claim.source_matches === false}<span class="bad"> · differs from the frozen inventory</span>{/if}</p>{/if}
    {/if}
    {#if claim.source_parts?.length > 1}
      <h3>Pinned passages ({claim.source_parts.length})</h3>
      <p class="faint small">The claim's source pin covers these passages, in this order; a change to any of them reopens its reviews.{#if claim.source_matches === false}<span class="bad"> One of them differs from the frozen inventory.</span>{/if}</p>
      {#each claim.source_parts as part, i}
        <p class="faint small part-head"><code>{part.file}</code>, lines {part.start_line}–{part.end_line}{#if i === 0} · the claim's passage{:else if part.macro} · the definition of <code>{part.macro}</code>{/if}</p>
        <pre class="srctext">{part.text}</pre>
      {/each}
    {/if}
    {#if Object.keys(claim.decls || {}).length}
      {@const ds = Object.keys(claim.decls || {})}
      <h3>Definitions ({ds.length})</h3>
      {#each ds as n (n)}
        {#if ds.length <= 40 || showAll}
          <Decl name={n} key={claim.decls[n]} index={evidenceIndex} onref={inDetails} />
        {/if}
      {/each}
      {#if ds.length > 40 && !showAll}
        <button class="btn ghost" onclick={() => (showAll = true)}>Show all {ds.length}</button>
      {/if}
    {/if}
    {#if claim.findings?.length}
      <h3>Findings</h3>
      <Findings findings={claim.findings} onshow={claim.clauses?.length ? showOccurrences : null} />
    {/if}
    <p class="faint small foot">
      Release <code>{evidenceIndex.release}</code> · evidence <code title={evidenceIndex.evidence}>{evidenceIndex.evidence.slice(0, 12)}</code>
      {#if evidenceIndex.lean}· Lean {evidenceIndex.lean.lean}{/if}
      {#if evidenceIndex.project?.commit}· project <code>{evidenceIndex.project.commit.slice(0, 12)}</code>{/if}
    </p>
  </section>
{/snippet}

{#snippet extra(item)}{#if item.kind === "details"}{@render auditDetails()}{/if}{/snippet}

{#if error}
  <p role="alert">{error} <button class="act" onclick={() => attempt++}>Try again</button></p>
{:else if !claim}
  <p class="muted">Loading…</p>
{:else}
  <article class="passport" class:full class:comparison={comparison || full} bind:this={article}>
    <div class="view">
    <header>
      <h1>{claim.number || claim.id}{#if claim.heading}<span class="title">&nbsp;— <TexInline text={claim.heading} /></span>{/if}</h1>
      {#if !claim.heading && claim.title}<p class="desc"><TexInline text={claim.title} /></p>{/if}
      <div class="bar">
        <button class="chipbtn" onclick={details} title="Audit details: what this status rests on"><EvidenceSummary record={claim} /></button>
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
              {#if index.review_queue && (inScope(claim) || claim.step)}
                <a href={withQuery(href(index.release, "review"), { claim: claim.id, seen: "lean" })}>Review it</a>
              {/if}
              <button onclick={details}>Audit details</button>
            </div>
          {/if}
        </span>
      </div>
      {#if copied}<p class="faint small copied">{copied}</p>{/if}
      {#if claim.missing}
        <p class="small evidence-from missing" data-source="missing">Not in this audit: the audit of <code>{claim.evidence_from}</code> does not map this claim.</p>
      {:else if project.combined && claim.unmapped}
        <p class="small evidence-from" data-source="unmapped">No audit of this version maps this claim.</p>
      {:else if project.combined && source}
        <p class="small evidence-from" class:filled={claim.filled} data-source={claim.filled ? "filled" : "default"}>
          {#if claim.filled}<strong>From another audit.</strong>{" The default audit does not map this claim; this is the evidence of the audit of "}{:else}{"From the audit of "}{/if}<code>{claim.evidence_from}</code>{source.author ? " by " + source.author : ""}{#if source.commit}{" at commit "}<code>{source.commit.slice(0, 12)}</code>{/if}.
        </p>
      {/if}
      {#if matched}
        <p class="small matched" data-matched="number">Matched by its printed number to the audit's entry{#if matched.version}{" for " + matched.version}{:else if matched.revision}{" for revision "}<code>{matched.revision.slice(0, 12)}</code>{/if}: the audit read another PDF of the paper than the one shown here.</p>
      {/if}
      {#each counterparts as cp}
        <p class="small counterpart" data-change={cp.change} data-version={cp.version}>{cp.before}{#each cp.claims as c, i}{#if i}{i === cp.claims.length - 1 ? " and " : ", "}{/if}<a href={c.href}>{c.number}</a>{/each}{cp.after}.</p>
      {/each}
      {#if claim.correspondence && !claim.step}
        {@const cor = claim.correspondence}
        {@const cv = coverageView(cor)}
        <div class="coverage" data-coverage={cv.coverage || "note"} data-basis={cv.basis || "unspecified"} data-tone={cv.tone}>
          <p class="small">{#if cv.headline}<strong>{cv.headline}</strong>{#if cor.confidence}{" "}<span class="faint">({cor.confidence} confidence)</span>{/if}{#if cor.note}{". "}{/if}{/if}{cor.note}</p>
          {#each cv.lines as line}
            <p class="small basis-line"><span class="faint">{line.label}:</span>
              {#each line.names || [] as n, i}{#if i}{", "}{/if}<button class="ref" onclick={() => showDecl(n)}><code>{n}</code></button>{/each}{#if line.names?.length && line.text}{". "}{/if}{#if line.text}<span class="basis-text">{line.text}</span>{/if}{#if line.note}{" "}<span class="faint">{line.note}</span>{/if}</p>
          {/each}
          <p class="faint small">{cor.source === "formalization.yaml" ? "The project's note in formalization.yaml" : "The auditor's reading" + (cor.by ? ", by " + cor.by : "")}</p>
        </div>
      {/if}
      {#each claim.reviews || [] as r}
        <details class="review" data-verdict={r.verdict.value}>
          <summary class="small"><strong>Review: {VERDICT_LABEL[r.verdict.value] || r.verdict.value}</strong>, by {reviewer(r)}, {(r.submitted_at || "").slice(0, 10)}{r.current === false ? (r.why === "source-changed" ? " · made on other paper text" : r.why === "source-unrecorded" ? " · does not record the paper text it read" : " · recorded for other declarations or statements") : r.current === null ? " · not compared with the current Lean" : ""}</summary>
          {#if r.verdict.detail}<p class="small pre">{r.verdict.detail}</p>{/if}
          {#if r.correspondence}
            {@const rc = coverageView(r.correspondence)}
            <div class="report-coverage" data-coverage={rc.coverage} data-basis={rc.basis || "unspecified"} data-tone={rc.tone}>
              <p class="small"><strong>{rc.headline}</strong> <span class="faint">(the reviewer's coverage, recorded with the verdict)</span></p>
              {#each rc.lines as line}
                <p class="small basis-line"><span class="faint">{line.label}:</span>
                  {#each line.names || [] as n, i}{#if i}{", "}{/if}<button class="ref" onclick={() => showDecl(n)}><code>{n}</code></button>{/each}{#if line.names?.length && line.text}{". "}{/if}{#if line.text}<span class="basis-text pre">{line.text}</span>{/if}{#if line.note}{" "}<span class="faint">{line.note}</span>{/if}</p>
              {/each}
              {#if recordedBasisText(r.correspondence)}<p class="faint small">{recordedBasisText(r.correspondence)}</p>{/if}
            </div>
          {/if}
          <p class="small pre">{r.comparison}</p>
          <details>
            <summary class="faint small">The reading, locked {r.locked_at} before the Lean was shown</summary>
            <p class="small pre">{r.reading}</p>
          </details>
        </details>
      {/each}
      <ProofStep {claim} {index} part="list" />
    </header>

    <Comparison {index} {inputs} {scope} bind:selection={selAt} mark={(spec, k) => (claim.clauses?.length ? markFor(k) : null)}
      onpinned={pinnedVar} {paperTools} {linkTools} {clauseTools} {leanFoot} {extra} />
    {#if editable}<Investigation {index} {claim} selection={selAt} {scope} />{/if}
    {#if claim.work}<PublishedWork {claim} />{/if}
    </div>
  </article>
{/if}

<style>
  .passport, .view { display: flex; flex-direction: column; gap: 18px; }
  header h1 { font-family: var(--serif); font-size: 24px; font-weight: 600; margin: 2px 0 10px; }
  .full header h1 { font-size: 30px; }
  .title { font-weight: 450; }
  .review { border-left: 3px solid var(--border); padding: 4px 0 4px 10px; margin-top: 8px; }
  .review[data-verdict="narrower"], .review[data-verdict="mismatched"], .review[data-verdict="vacuous"], .review[data-verdict="cannot determine"] { border-left-color: var(--tier-warning); }
  .review summary { cursor: pointer; }
  .pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  .coverage { border-left: 3px solid var(--border); padding: 4px 0 4px 10px; margin-top: 8px; }
  .coverage p { margin: 2px 0; }
  .coverage[data-tone="warning"] { border-left-color: var(--tier-warning); }
  .coverage[data-tone="full"] { border-left-color: var(--st-proved); }
  .coverage[data-tone="reading"], .coverage[data-tone="open"] { border-left-color: var(--accent); }
  .report-coverage { margin: 4px 0; }
  .report-coverage p { margin: 2px 0; }
  .basis-line .ref, .details .ref { font: inherit; padding: 0; border: 0; background: none; color: var(--accent); cursor: pointer; }
  .basis-line .ref:hover code { text-decoration: underline; }
  .basis-text { white-space: pre-line; }
  .basis-line code { overflow-wrap: anywhere; }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; text-decoration: none; }
  .act:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .summary { margin: 4px 0 8px; font-size: 13px; color: var(--muted); }
  .desc { margin: 2px 0 10px; font-size: 15px; color: var(--muted); line-height: 1.5; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 8px; }
  h3 { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .block { margin-bottom: 14px; }
  .block.suggestion { border: 1px dashed var(--border); border-radius: 8px; padding: 8px 10px; }
  ul.reasons { margin: 2px 0 6px; padding-left: 18px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .grow { flex: 1; }
  .chipbtn { border: 0; background: none; padding: 4px 0; cursor: pointer; }
  .menuwrap { position: relative; }
  .more { font-size: 15px; line-height: 1; padding: 3px 9px; }
  .menu { position: absolute; right: 0; top: calc(100% + 4px); z-index: 10; min-width: 200px; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 6px 20px rgb(0 0 0 / 0.14); padding: 4px; }
  .menu > a, .menu > button { text-align: left; font: inherit; font-size: 14px; padding: 7px 10px; border: 0; background: none; color: var(--text); border-radius: 6px; cursor: pointer; text-decoration: none; }
  .menu > a:hover, .menu > button:hover { background: var(--surface-2); }
  .copied { margin: 4px 0 0; }
  .marknote { margin: 4px 0; color: var(--tier-warning); }
  .evidence-from { margin: 6px 0 0; color: var(--muted); overflow-wrap: anywhere; }
  .evidence-from.filled, .evidence-from.missing { color: var(--text); border-left: 3px solid var(--accent); padding-left: 8px; }
  .counterpart { margin: 6px 0 0; color: var(--muted); overflow-wrap: anywhere; }
  .matched { margin: 6px 0 0; color: var(--muted); overflow-wrap: anywhere; }
  .recorded { margin: 0 0 8px; }
  .mklink { margin-top: 8px; border: 1px dashed var(--border); border-radius: 8px; padding: 6px 10px; }
  .mklink > summary { cursor: pointer; font-size: 13px; color: var(--muted); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { border: 1px solid var(--border); background: var(--surface); border-radius: 6px; padding: 0 6px; cursor: pointer; }
  .chip.on { border-color: var(--accent); background: var(--accent-soft); }
  .chip :global(.tex) { border: 0; padding: 0; margin: 0; background: none; font-size: 15px; }
  .who { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 12em; }
  .obj { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 16em; max-width: 100%; }
  .occ label { margin-right: 8px; }
  .stale-why { display: block; color: var(--muted); }
  .details h2 { margin-bottom: 4px; }
  .decl { margin: 0 0 6px; overflow-wrap: anywhere; }
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
  .pill { font-size: 11px; padding: 0 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: 4px; }
  .part-head { margin: 8px 0 2px; }
  .srctext { white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.5 var(--mono); background: var(--surface); padding: 8px 10px; border-radius: var(--radius); }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 6px 0 0; }
  .foot { margin-top: 16px; }
  @media (max-width: 700px) {
    .passport, .view { gap: 12px; }
    header h1 { font-size: 20px; margin: 0 0 6px; }
    .desc { font-size: 14px; margin: 0 0 6px; }
    .act { font-size: 12px; padding: 2px 8px; }
    .passport h2 { margin-bottom: 4px; }
  }
</style>
