<script>
  import { claimLink, claimReference, issueUrl, sourceUrl, sourceLabel, sourceTitle } from "../lib/issue.js";
  import TexInline from "./TexInline.svelte";
  import { loadClaim, saveLink } from "../lib/data.js";
  import { href } from "../lib/route.svelte.js";
  import StatusChip from "./StatusChip.svelte";
  import PdfCrop from "./PdfCrop.svelte";
  import Statement from "./Statement.svelte";
  import Ladder from "./Ladder.svelte";
  import Findings from "./Findings.svelte";
  import Decl from "./Decl.svelte";
  import Tex from "./Tex.svelte";
  import LinkPicker from "./LinkPicker.svelte";

  // One claim: the mathematics first (as printed, then in Lean), then one line on what Lean
  // establishes; the evidence behind that line is folded into "Technical details".
  let { index, claimId, full = false, editable = false } = $props();

  let claim = $state(null);
  let error = $state(null);
  let openDecl = $state(null);
  let showAll = $state(false);
  let busy = $state(null);
  let saveError = $state(null);
  const RANK = { stale: 0, pending: 1, "author-reviewed": 2, reviewed: 3 };

  $effect(() => {
    claim = null; error = null; openDecl = null; showAll = false; saveError = null;
    loadClaim(index, claimId).then((c) => (claim = c)).catch((e) => (error = String(e)));
  });

  const paper = $derived(claim && index.papers.find((p) => p.id === claim.paper));
  const meta = $derived(index.claims.find((c) => c.id === claimId));
  const simple = $derived(claim?.mode === "simple");

  function showDecl(name) {
    openDecl = name;
    queueMicrotask(() => document.getElementById("decl-" + name)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
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

  // One line on what the Lean side of a clause establishes, in words.
  function verdict(cl) {
    const ch = cl.checks || {};
    const p = ch.accept || ch.refute;
    if (cl.state === "unchecked") return "The Lean project was not checked in this build.";
    if (cl.state === "unspecified") return "No Lean statement has been written for it yet.";
    if (cl.state === "stated") return "Stated in Lean as definitions.";
    if (!p) return "A Lean statement exists; it has no proof yet.";
    if (!p.ok) return "The Lean proof fails a check: " + p.errors.join(", ") + ".";
    const replay = ch.replay?.state === "pass" ? ", replayed independently" : "";
    const rev = { reviewed: "its meaning reviewed independently", "author-reviewed": "its meaning reviewed only by its author", pending: "its meaning not yet reviewed" }[cl.review] || "";
    return (cl.state === "refuted" ? "Lean proves the printed statement false" : "Proved in Lean") + replay + (rev ? "; " + rev : "") + ".";
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
    if (s.includes("not checked")) return "Lean has not been run on it here: the project is not built, so whether it is proved is not known.";
    if (s.includes("not found")) return "Not found in the built modules.";
    if (s.includes("definition")) return `A Lean ${l.kind || "definition"}.`;
    if (s.includes("incomplete")) return "Its Lean proof is incomplete (it uses sorry).";
    if (s.includes("further axioms")) return "Its proof uses axioms beyond the standard three: " + (l.axioms || []).join(", ") + ".";
    if (s === "linked: Lean proof checked") return "Proved in Lean. Whether it says what the paper says has not been reviewed.";
    return s;
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
        {#if index.papers.length > 1}Paper {claim.paper} · {/if}<code>{claim.id}</code>
        {#if full && meta?.anchor}· <a href={href(index.release, "read", claim.paper, claim.id)}>show in the paper</a>{/if}
      </p>
      <h1>{claim.number || claim.id}{#if claim.heading}<span class="title">&nbsp;— <TexInline text={claim.heading} /></span>{/if}</h1>
      {#if !claim.heading && claim.title}<p class="desc"><TexInline text={claim.title} /></p>{/if}
      <StatusChip status={claim.status} cls={claim.class} />
      <div class="actions">
        <button class="act" onclick={copyLink} title={claimLink(index, claim) || "No public address: copies the claim's reference"}>{copied || "Copy link"}</button>
        {#if index.review_queue && claim.scope !== "out-of-scope" && !String(claim.status).startsWith("out of scope")}
          <a class="act" href={href(index.release, "review")} title="Compare the paper's statement with the Lean, one unit at a time, and record what you find">Review it</a>
        {/if}
        {#if issueUrl(index, claim)}
          <a class="act" href={issueUrl(index, claim)} target="_blank" rel="noopener" title={"Opens a draft issue in " + index.issues + " with this claim's details filled in"}>Raise issue ↗</a>
        {/if}
      </div>
    </header>

    <section>
      {#if paper?.pdf && claim.anchor?.begin}
        <PdfCrop url={"data/" + paper.pdf} anchor={claim.anchor} />
      {:else if claim.statement_tex}
        <Tex text={claim.statement_tex} />
      {:else}
        <p class="muted">The printed statement is not part of this site.</p>
      {/if}
    </section>

    <section class="lean">
      <h2>In Lean</h2>
      {#if simple}
        {#each claim.links as l (l.name)}
          <div class="card">
            <p class="decl"><code>{l.name}</code>{#if l.module}<span class="faint"> · {l.module}{l.range ? ":" + l.range.line : ""}</span>{/if}
              {#if sourceUrl(index, l.path, l.range?.line)}<a class="src-link small" href={sourceUrl(index, l.path, l.range?.line)} target="_blank" rel="noopener" title={sourceTitle(index)}>{sourceLabel(index)}</a>{/if}</p>
            <p class="faint small src">{l.source === "paper" ? "Linked by a \\lean{…} tag in the paper's source" : l.source === "formalization.yaml" ? "Declared in the project's formalization.yaml" + (index.formalization?.review_status ? ` (the project describes its review as “${index.formalization.review_status}”)` : "") : "Linked in the reader (machinechecked.links.json)"}</p>
            <p class="verdict top">{linkVerdict(l)}</p>
            {#if l.statement}<Statement st={l.statement} onref={showDecl} compact />{/if}
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
            <div class="card suggestion">
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
          <div class="card" class:refuted={cl.state === "refuted"}>
            {#if claim.clauses.length > 1}<p class="cname"><TexInline text={cl.label || cl.name} />{#if cl.corrects}<span class="faint">&nbsp;— corrects “<TexInline text={cl.corrects_label || cl.corrects} />”</span>{/if}</p>{/if}
            <p class="verdict top">{verdict(cl)}</p>
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
              <Statement st={cl.statement} spec={cl.spec} onref={showDecl} compact />
            {:else if cl.defs?.length}
              <p>{#each cl.defs as d, i}{#if i}, {/if}<button class="ref" onclick={() => showDecl(d)}>{d}</button>{/each}</p>
            {/if}
          </div>
        {:else}
          <p class="muted">No Lean statement has been written for this claim.</p>
        {/each}
        {#if claim.blockers?.length}
          <details class="why">
            <summary>Why is this claim not accepted? <span class="faint">({claim.blockers.length})</span></summary>
            <ul>{#each claim.blockers as b}<li><TexInline text={b} /></li>{/each}</ul>
          </details>
        {/if}
      {/if}
    </section>

    <details class="tech" open={!!openDecl}>
      <summary>Technical details</summary>
      {#if claim.number_note}
        <h3>Number</h3>
        <p class="summary">{claim.number} <span class="faint">({claim.number_note})</span></p>
      {/if}
      {#if claim.statement_tex && paper?.pdf && claim.anchor?.begin}
        <h3>Source text</h3>
        <Tex text={claim.statement_tex} />
        {#if claim.anchor?.file}<p class="faint small"><code>{claim.anchor.file}:{claim.anchor.line}</code>
          {#if claim.anchor.kind === "approximate"} · located approximately{/if}
          {#if claim.source_matches === false}<span class="bad"> · differs from the frozen inventory</span>{/if}</p>{/if}
      {/if}
      {#if claim.scope_note}<p class="muted small">{claim.scope_note}</p>{/if}

      {#each claim.clauses as cl, k (k)}
        <h3>{#if claim.clauses.length > 1}<TexInline text={cl.label || cl.name} />{:else}Evidence{/if}</h3>
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

      {#if Object.keys(claim.decls || {}).length || openDecl}
        {@const ds = Object.keys(claim.decls || {})}
        <h3>Definitions ({ds.length})</h3>
        {#if openDecl && !(openDecl in (claim.decls || {}))}
          <Decl name={openDecl} key={null} open onref={showDecl} />
        {/if}
        {#each ds as n (n)}
          {#if ds.length <= 40 || openDecl === n || showAll}
            <Decl name={n} key={claim.decls[n]} open={openDecl === n} onref={showDecl} />
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
    </details>
  </article>
{/if}

<style>
  .passport { display: flex; flex-direction: column; gap: 18px; }
  header h1 { font-family: var(--serif); font-size: 24px; font-weight: 600; margin: 2px 0 10px; }
  .full header h1 { font-size: 30px; }
  .title { font-weight: 450; }
  .actions { display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; text-decoration: none; }
  .act:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }
  .summary { margin: 4px 0 8px; font-size: 13px; color: var(--muted); }
  .desc { margin: 2px 0 10px; font-size: 15px; color: var(--muted); line-height: 1.5; }
  .eyebrow { margin: 0; color: var(--muted); font-size: 13px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; margin: 0 0 8px; }
  h3 { font-size: 14px; font-weight: 600; margin: 14px 0 6px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; }
  .card.refuted { border-left: 4px solid var(--st-refuted); }
  .card.suggestion { border-style: dashed; }
  .cname { font-weight: 600; margin: 0 0 8px; }
  .changes { border-left: 3px solid var(--st-open, #b7791f); background: var(--surface-2, transparent); padding: 6px 10px; margin: 0 0 10px; border-radius: 0 6px 6px 0; }
  .changes p { margin: 0 0 4px; }
  .changes ul { margin: 0; padding-left: 18px; }
  .changes code { font-size: 12px; }
  .src-link { margin-left: 8px; white-space: nowrap; }
  .decl { margin: 0 0 6px; }
  .verdict { margin: 10px 0 0; font-size: 14px; }
  .verdict.top { margin: 0 0 8px; }
  .row { display: flex; gap: 8px; margin-top: 10px; }
  .btn { border: 1px solid var(--accent); background: var(--accent); color: white; border-radius: 6px; padding: 4px 12px; cursor: pointer; font-size: 13px; margin-top: 8px; }
  .row .btn { margin-top: 0; }
  .btn.ghost { background: transparent; color: var(--accent); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .why { margin-top: 6px; padding: 8px 12px; border: 1px solid var(--border); border-left: 4px solid var(--st-open); border-radius: 8px; background: var(--surface); }
  .why summary { cursor: pointer; font-weight: 600; }
  .why ul { margin: 6px 0 2px; padding-left: 18px; }
  .tech { border-top: 1px solid var(--border); padding-top: 10px; }
  .tech > summary { cursor: pointer; color: var(--muted); font-weight: 600; }
  .small { font-size: 13px; }
  .bad { color: var(--st-malformed); }
  .proof { margin: 10px 0 0; }
  .proof dt { font-size: 12px; color: var(--muted); }
  .proof dd { margin: 0 0 6px; }
  .review { border-left: 3px solid var(--border); padding-left: 10px; margin: 8px 0; }
  .pill { font-size: 11px; padding: 0 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); margin-left: 4px; }
  .rtext { white-space: pre-wrap; font: 13px/1.5 var(--sans); color: var(--muted); margin: 6px 0 0; }
  .ref { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; font-family: var(--mono); font-size: 0.92em; }
  .foot { margin-top: 16px; }
</style>
