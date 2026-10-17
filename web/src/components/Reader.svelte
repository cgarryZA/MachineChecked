<script>
  import TexInline from "./TexInline.svelte";
  import { href, go } from "../lib/route.svelte.js";
  import PdfView from "./PdfView.svelte";
  import Passport from "./Passport.svelte";
  import PaperInfo from "./PaperInfo.svelte";
  import { projectClaims } from "../lib/data.js";

  // The paper, a contents list of its claims, and the claim chosen.
  let { index, paperId, claimId, editable = false } = $props();

  const paper = $derived(index.papers.find((p) => p.id === paperId));
  const claims = $derived(projectClaims(index).filter((c) => c.paper === paperId));
  const inScope = (c) => !String(c.status).startsWith("out of scope");
  const ordered = $derived(
    [...claims].filter(inScope).sort((a, b) =>
      (a.anchor ? 0 : 1) - (b.anchor ? 0 : 1) || (a.anchor?.page ?? 0) - (b.anchor?.page ?? 0) || (a.anchor?.y0 ?? 0) - (b.anchor?.y0 ?? 0)),
  );
  const paperMode = $derived(index.mode === "paper");
  let showContents = $state(typeof window !== "undefined" && window.innerWidth > 1180 && (index.mode !== "paper" || index.claims.length > 0));
  // On a narrow screen the paper page's formalisation panel opens on request.
  let showInfo = $state(typeof window !== "undefined" && window.innerWidth > 1180);
  let showAllClaims = $state(false);
  // A numbered statement ("Theorem 3.1") as against an equation, a part or a prose claim.
  const isEnv = (c) => /^[A-Z][a-z]+ (?:[A-Z](?:\.[0-9]+)+|[A-Z]?[0-9][0-9.]*)[a-z]?$/.test(c.number || "");
  const listed = $derived(showAllClaims ? ordered : ordered.filter(isEnv));
  const others = $derived(ordered.filter((c) => !isEnv(c)).length);

  // The side panel's width, set by dragging its edge on a wide screen and remembered here.
  const saved = (() => { try { return Number(localStorage.getItem("mc-side-width")) || 0; } catch { return 0; } })();
  let sideWidth = $state(saved >= 320 && saved <= 900 ? saved : 0);
  function drag(e) {
    if (window.innerWidth <= 1180) return;
    e.preventDefault();
    const move = (ev) => { sideWidth = Math.min(900, Math.max(320, window.innerWidth - ev.clientX)); };
    const up = () => {
      window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      try { localStorage.setItem("mc-side-width", String(Math.round(sideWidth))); } catch {}
    };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  }

  function select(id) { go(href(index.release, "read", paperId, id)); }
  function close() { go(href(index.release, "read", paperId)); }
</script>

{#if !paper}
  <main class="msg"><p>No paper <code>{paperId}</code> here.</p></main>
{:else}
  <div class="reader" class:open={!!claimId || (paperMode && showInfo)} class:contents={showContents} class:paper={paperMode} class:sized={sideWidth > 0} style:--side-w={sideWidth ? sideWidth + "px" : null}>
    {#if paperMode && !showInfo && !claimId}
      <button class="info-open" onclick={() => (showInfo = true)}>Formalisations ›</button>
    {/if}
    {#if showContents}
      <nav class="toc" aria-label="Claims of the paper">
        <div class="toc-head">
          <span>Contents</span>
          <button class="x" onclick={() => (showContents = false)} aria-label="Hide contents">‹</button>
        </div>
        <ol>
          {#each listed as c (c.id)}
            <li>
              <button class:sel={c.id === claimId} onclick={() => select(c.id)} title={c.status}>
                <span class={"dot st-" + c.class} aria-hidden="true"></span>
                <span class="n">{c.number || c.id}</span>
                {#if c.heading || c.title}<span class="t"><TexInline text={c.heading || c.title} /></span>{/if}
                {#if !c.anchor}<span class="na" title="not located in the PDF">·</span>{/if}
              </button>
            </li>
          {/each}
        </ol>
        {#if others}
          <button class="more" onclick={() => (showAllClaims = !showAllClaims)}>
            {showAllClaims ? "Only numbered statements" : `Also equations and prose claims (${others})`}
          </button>
        {/if}
      </nav>
    {:else if claims.length}
      <button class="toc-open" onclick={() => (showContents = true)} aria-label="Show contents">Contents ›</button>
    {/if}
    <section class="paperpane" aria-label="Paper">
      {#if paper.pdf_url || paper.pdf}
        <PdfView url={paper.pdf_url || "data/" + paper.pdf} {claims} selected={claimId} onselect={select} />
      {:else}
        <div class="msg"><p>The PDF of this paper is not part of this site; choose a claim from the contents.</p></div>
      {/if}
    </section>
    {#if paperMode && showInfo && !claimId}
      <aside class="side" aria-label="Formalisations of this paper">
        <div class="drag" role="separator" aria-orientation="vertical" aria-label="Drag to resize" onpointerdown={drag}></div>
        <div class="side-head">
          <span class="muted">About this paper</span>
          <button class="x" onclick={() => (showInfo = false)} aria-label="Close">×</button>
        </div>
        <PaperInfo paper={index.paper} />
      </aside>
    {:else if claimId}
      <aside class="side" aria-label="The claim">
        <div class="drag" role="separator" aria-orientation="vertical" aria-label="Drag to resize" onpointerdown={drag}></div>
        <div class="side-head">
          <span></span>
          <button class="x" onclick={close} aria-label="Close">×</button>
        </div>
        <Passport {index} {claimId} {editable} />
      </aside>
    {/if}
  </div>
{/if}

<style>
  .reader { display: grid; grid-template-columns: minmax(0, 1fr); height: calc(100vh - 49px); position: relative; }
  .reader.contents { grid-template-columns: 260px minmax(0, 1fr); }
  .reader.open { grid-template-columns: minmax(0, 1.1fr) minmax(380px, 0.9fr); }
  .reader.contents.open { grid-template-columns: 260px minmax(0, 1.1fr) minmax(380px, 0.9fr); }
  .reader.paper.open { grid-template-columns: minmax(0, 1fr) minmax(340px, 420px); }
  .reader.paper.contents.open { grid-template-columns: 260px minmax(0, 1fr) minmax(340px, 420px); }
  .toc { overflow: auto; border-right: 1px solid var(--border); background: var(--surface); }
  .toc-head { position: sticky; top: 0; display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; background: var(--surface); font-weight: 600; font-size: 13px; color: var(--muted); border-bottom: 1px solid var(--border); }
  .toc ol { list-style: none; margin: 0; padding: 4px; }
  .toc li button { display: flex; gap: 6px; align-items: baseline; width: 100%; text-align: left; border: 0; background: none; padding: 4px 8px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .toc li button:hover { background: var(--surface-2); }
  .toc li button.sel { background: var(--accent-soft); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--st); flex: none; align-self: center; }
  .n { font-weight: 600; white-space: nowrap; }
  .t { color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .na { color: var(--faint); margin-left: auto; }
  .more { margin: 4px 12px 16px; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 13px; padding: 0; }
  .info-open { position: absolute; right: 12px; bottom: 16px; z-index: 5; border: 1px solid var(--accent); background: var(--surface); color: var(--accent); border-radius: 18px; padding: 8px 16px; cursor: pointer; font-size: 14px; box-shadow: 0 4px 14px rgb(0 0 0 / 0.12); }
  .toc-open { position: absolute; left: 8px; top: 8px; z-index: 5; border: 1px solid var(--border); background: var(--surface); border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 13px; }
  .paperpane { overflow: auto; background: var(--surface-2); }
  .side { overflow: auto; border-left: 1px solid var(--border); background: var(--bg); padding: 0 20px 60px; }
  .side-head { position: sticky; top: 0; z-index: 2; display: flex; justify-content: space-between; align-items: center; padding: 4px 0; background: var(--bg); margin-bottom: 4px; font-size: 14px; }
  .reader.sized.open { grid-template-columns: minmax(0, 1fr) var(--side-w); }
  .reader.sized.contents.open { grid-template-columns: 260px minmax(0, 1fr) var(--side-w); }
  .side { position: relative; }
  .drag { position: absolute; left: -3px; top: 0; bottom: 0; width: 7px; cursor: col-resize; z-index: 4; }
  .drag:hover, .drag:active { background: color-mix(in srgb, var(--accent) 35%, transparent); }
  .x { border: 0; background: none; font-size: 20px; line-height: 1; cursor: pointer; color: var(--muted); padding: 0 4px; }
  .msg { padding: 24px; }
  @media (max-width: 1180px) {
    .reader.contents, .reader.contents.open { grid-template-columns: 240px minmax(0, 1fr); }
    .reader.contents.open .side, .reader.open .side { position: fixed; right: 0; top: 49px; bottom: 0; width: min(480px, 100vw); z-index: 30; box-shadow: -8px 0 24px rgb(0 0 0 / 0.15); }
    .reader.open, .reader.sized.open { grid-template-columns: minmax(0, 1fr); }
    .reader.sized.contents.open { grid-template-columns: 240px minmax(0, 1fr); }
    .drag { display: none; }
  }
  @media (max-width: 700px) {
    .reader.contents { grid-template-columns: minmax(0, 1fr); }
    .toc { position: fixed; left: 0; top: 49px; bottom: 0; width: 80vw; z-index: 31; box-shadow: 8px 0 24px rgb(0 0 0 / 0.15); }
    .reader.open .side { top: auto; height: 70vh; width: 100vw; border-radius: 14px 14px 0 0; }
  }
</style>
