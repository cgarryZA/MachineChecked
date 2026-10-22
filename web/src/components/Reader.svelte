<script>
  import { onDestroy } from "svelte";
  import { inScope, statusView } from "../lib/presentation.js";
  import TexInline from "./TexInline.svelte";
  import { href, go, route, withQuery } from "../lib/route.svelte.js";
  import PdfView from "./PdfView.svelte";
  import Passport from "./Passport.svelte";
  import PaperInfo from "./PaperInfo.svelte";
  import { project, chooseEdition } from "../lib/project.svelte.js";
  import { projectClaims } from "../lib/data.js";
  let { index, paperId, claimId, editable = false } = $props();
  let viewport = $state(window.innerWidth), layout = $state(), side = $state(), contentsDialog = $state();
  const narrow = $derived(viewport <= 1180);
  const original = $derived(index.papers.find((p) => p.id === paperId));
  const paper = $derived((index.editions || []).find((p) => p.edition === project.edition) || original);
  const claims = $derived(projectClaims(index).filter((c) => c.paper === paperId));
  let showScope = $state(false), showAllClaims = $state(false);
  const scoped = $derived(claims.filter((c) => !inScope(c)).length);
  const ordered = $derived([...claims].filter((c) => showScope || inScope(c)).sort((a, b) =>
    (a.anchor ? 0 : 1) - (b.anchor ? 0 : 1) || (a.anchor?.page ?? 0) - (b.anchor?.page ?? 0) || (a.anchor?.y0 ?? 0) - (b.anchor?.y0 ?? 0)));
  const paperMode = $derived(index.mode === "paper");
  let showContents = $state(window.innerWidth > 1180);
  let showInfo = $state(window.innerWidth > 1180);
  const isEnv = (c) => /^[A-Z][a-z]+ (?:[A-Z](?:\.[0-9]+)+|[A-Z]?[0-9][0-9.]*)[a-z]?$/.test(c.number || "");
  const listed = $derived(showAllClaims ? ordered : ordered.filter(isEnv));
  const others = $derived(ordered.filter((c) => !isEnv(c)).length);
  const comparing = $derived(!!claimId && route.compare);
  const saved = (() => { try { return Number(localStorage.getItem("mc-side-width")) || 480; } catch { return 480; } })();
  let sideWidth = $state(Math.min(900, Math.max(320, saved)));
  const maxWidth = $derived(Math.max(320, Math.min(900, viewport - (showContents && !narrow ? 280 : 0) - 360)));
  function resize(w) { sideWidth = Math.min(maxWidth, Math.max(320, w)); }
  function remember() { try { localStorage.setItem("mc-side-width", String(sideWidth)); } catch {} }
  let dragging;
  let focusClaim = $state(null), contentsOpen = $state(false);
  function drag(e) {
    e.preventDefault(); dragging?.abort(); dragging = new AbortController();
    const move = (ev) => resize(layout.getBoundingClientRect().right - ev.clientX);
    const end = () => { remember(); dragging.abort(); };
    window.addEventListener("pointermove", move, { signal: dragging.signal });
    window.addEventListener("pointerup", end, { signal: dragging.signal });
    window.addEventListener("pointercancel", end, { signal: dragging.signal });
  }
  onDestroy(() => dragging?.abort());
  function resizeKey(e) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter"].includes(e.key)) return;
    e.preventDefault();
    resize(e.key === "Home" ? 320 : e.key === "End" ? maxWidth : e.key === "Enter" ? 480
      : (side?.clientWidth || sideWidth) + (e.key === "ArrowLeft" ? 24 : -24));
    remember();
  }
  function contents() {
    if (narrow) { contentsOpen = true; contentsDialog.showModal(); }
    else showContents = !showContents;
  }
  $effect(() => { if (!narrow) contentsDialog?.close(); });
  function select(id) {
    contentsDialog?.close();
    if (narrow) focusClaim = id;
    go(withQuery(href(index.release, "read", paperId, id), { compare: comparing ? "1" : null }));
  }
  $effect(() => { if (focusClaim && focusClaim === claimId && side) { side.focus({ preventScroll: true }); focusClaim = null; } });
  function close() { go(href(index.release, "read", paperId)); }
</script>
<svelte:window bind:innerWidth={viewport} />

{#snippet contentsList()}
  <nav class="toc" aria-label="Claims of the paper">
    <div class="toc-head"><strong>Contents</strong><button class="x" onclick={() => { showContents = false; contentsDialog?.close(); }} aria-label="Hide contents">×</button></div>
    <ol>{#each listed as c (c.id)}
      <li><a class:sel={c.id === claimId} href={href(index.release, "read", paperId, c.id)} title={statusView(c).label}
        onclick={(e) => { if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); select(c.id); } }}>
        <span class={"dot st-" + statusView(c).class} aria-hidden="true"></span>
        <span><strong>{c.number || c.id}</strong>{#if c.heading || c.title}<span class="t"><TexInline text={c.heading || c.title} /></span>{/if}{#if c.filled}<span class="from" data-from={c.evidence_from}>From {c.evidence_from}</span>{:else if c.missing}<span class="from" data-from="missing">Not in this audit</span>{/if}</span>
      </a></li>
    {/each}</ol>
    {#if scoped}<button class="more" onclick={() => showScope = !showScope}>{showScope ? "Hide scope decisions" : `Include scope decisions (${scoped})`}</button>{/if}
    {#if others}<button class="more" onclick={() => showAllClaims = !showAllClaims}>{showAllClaims ? "Only numbered statements" : `Include equations and prose (${others})`}</button>{/if}
  </nav>
{/snippet}

{#if !paper}<main class="msg"><p>No paper <code>{paperId}</code> here.</p></main>
{:else}
  <div class="reader">
    <div class="reader-tools">
      {#if claims.length}<button onclick={contents} aria-expanded={narrow ? contentsOpen : showContents}>Contents</button>{/if}
      {#if index.editions?.length}
        <label class="edition">PDF <select aria-label="Paper revision" value={paper.edition || "original"} onchange={(e) => chooseEdition(e.currentTarget.value)}>
          <option value="original">Original paper</option>
          {#each index.editions as p}<option value={p.edition}>Audited revision · {p.author || p.repository} · {p.revision.slice(0, 12)}</option>{/each}
        </select></label>
      {/if}
      <span class="grow"></span>
      {#if claimId}
        <button class="compare-button" aria-pressed={comparing} onclick={() => { if (!comparing) showContents = false; go(withQuery(location.hash, { compare: comparing ? null : "1" })); }}>{comparing ? "Return to reader" : "Expand comparison"}</button>
        <button onclick={close}>Back to paper</button>
      {:else if paperMode}<button onclick={() => showInfo = !showInfo} aria-expanded={showInfo}>Formalisations</button>{/if}
    </div>
    <div class="reader-layout" class:open={!!claimId || (paperMode && showInfo)} class:contents={showContents && !narrow}
      class:comparing class:claim-open={!!claimId} style:--side-w={Math.min(sideWidth, maxWidth) + "px"} bind:this={layout}>
      {#if showContents && !narrow}{@render contentsList()}{/if}
      <section class="paperpane" class:concealed={comparing} aria-label="Paper">
        {#if paper.pdf_url || paper.pdf}<PdfView url={paper.pdf_url || "data/" + paper.pdf} {claims} selected={claimId} onselect={select} />
        {:else}<div class="msg"><p>Choose a claim to read its statements and evidence.</p></div>{/if}
      </section>
      {#if claimId || (paperMode && showInfo)}
        <aside class="side" aria-label={claimId ? "The claim" : "Formalisations of this paper"} tabindex="-1" bind:this={side}>
          {#if !comparing}<div class="drag" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Claim panel width"
            aria-valuemin="320" aria-valuemax={maxWidth} aria-valuenow={Math.min(sideWidth, maxWidth)} aria-valuetext={`${Math.min(sideWidth, maxWidth)} pixels`}
            onpointerdown={drag} onkeydown={resizeKey}></div>{/if}
          {#if claimId}<Passport {index} {claimId} {editable} comparison={comparing} />
          {:else}<div class="side-head"><strong>About this paper</strong><button class="x" onclick={() => showInfo = false} aria-label="Close formalisations">×</button></div><PaperInfo paper={index.paper} {index} />{/if}
        </aside>
      {/if}
    </div>
  </div>
  <dialog class="contents-dialog" bind:this={contentsDialog} onclose={() => contentsOpen = false} aria-label="Contents" onclick={(e) => { if (e.target === contentsDialog) contentsDialog.close(); }} onkeydown={() => {}}>
    {@render contentsList()}
  </dialog>
{/if}

<style>
  .reader { height: 100%; min-height: 0; display: flex; flex-direction: column; }
  .reader-tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 6px 12px; background: var(--surface); border-bottom: 1px solid var(--border); }
  .reader-tools button, .reader-tools select { font: inherit; font-size: 14px; border: 1px solid var(--border); background: var(--surface); color: var(--text); border-radius: var(--radius); padding: 4px 10px; cursor: pointer; }
  .reader-tools .compare-button { color: var(--on-accent); background: var(--accent); border-color: var(--accent); }
  .grow { flex: 1; }
  .edition { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 14px; }
  .edition select { min-width: 0; max-width: min(440px, 65vw); }
  /* Each pane is the containing block of its absolutely positioned content (KaTeX's hidden
     MathML among it), so that content scrolls inside the pane and never lengthens the page. */
  .reader-layout { display: grid; grid-template-columns: minmax(0, 1fr); flex: 1; min-height: 0; }
  .reader-layout.contents { grid-template-columns: 260px minmax(0, 1fr); }
  .reader-layout.open { grid-template-columns: minmax(0, 1fr) minmax(320px, var(--side-w)); }
  .reader-layout.contents.open { grid-template-columns: 260px minmax(0, 1fr) minmax(320px, var(--side-w)); }
  .reader-layout.comparing { grid-template-columns: minmax(0, 1fr); }
  .reader-layout.contents.comparing { grid-template-columns: 260px minmax(0, 1fr); }
  .paperpane { position: relative; min-width: 0; min-height: 0; overflow: auto; background: var(--surface-2); }
  .concealed { display: none; }
  .side { position: relative; min-width: 0; min-height: 0; overflow: auto; border-left: 1px solid var(--border); padding: 20px 20px 48px; }
  .side-head, .toc-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .drag { position: absolute; left: 0; top: 0; bottom: 0; width: 8px; cursor: col-resize; z-index: 4; }
  .drag:hover, .drag:focus-visible { background: var(--accent-soft); }
  .toc { position: relative; overflow: auto; background: var(--surface); border-right: 1px solid var(--border); min-height: 0; }
  .toc-head { position: sticky; top: 0; background: var(--surface); padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .toc ol { list-style: none; margin: 0; padding: 6px; }
  .toc a { display: flex; gap: 8px; padding: 8px; border-radius: var(--radius); color: var(--text); font-size: 14px; text-decoration: none; }
  .toc a:hover { background: var(--surface-2); }
  .toc a.sel { background: var(--accent-soft); }
  .from { display: block; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
  .t { display: block; color: var(--muted); line-height: 1.4; overflow-wrap: anywhere; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--st); flex: none; margin-top: 7px; }
  .x { border: 0; background: none; font-size: 22px; cursor: pointer; min-width: var(--control-height); }
  .more { margin: 4px 12px; background: none; border: 0; color: var(--accent); cursor: pointer; text-align: left; font-size: 14px; }
  .contents-dialog { padding: 0; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: var(--text); width: min(440px, calc(100vw - 24px)); max-height: calc(100dvh - 32px); }
  .contents-dialog::backdrop { background: #0006; }
  .msg { padding: 24px; }
  @media (max-width: 1180px) { .drag { display: none; } .reader-layout.open { grid-template-columns: minmax(0, 1fr) minmax(320px, 46%); } .reader-layout.comparing { grid-template-columns: minmax(0, 1fr); } }
  @media (max-width: 800px) { .reader-layout.open { grid-template-columns: minmax(0, 1fr); } .reader-layout.open .paperpane { display: none; } .side { border-left: 0; padding: 16px 12px 40px; } .reader-tools { padding: 6px 8px; } }
</style>
