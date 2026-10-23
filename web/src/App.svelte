<script>
  import { loadIndex, canEdit, auditInfo, AUDIT, auditOf } from "./lib/data.js";
  import { project, chooseProject } from "./lib/project.svelte.js";
  import { route, href } from "./lib/route.svelte.js";
  import { pageVersions, versionHref, versionLabel } from "./lib/versions.js";
  import Coverage from "./components/Coverage.svelte";
  import Reader from "./components/Reader.svelte";
  import Passport from "./components/Passport.svelte";
  import Changes from "./components/Changes.svelte";
  import Search from "./components/Search.svelte";
  import TexInline from "./components/TexInline.svelte";
  import Review from "./components/Review.svelte";

  let index = $state(null);
  let error = $state(null);
  let editable = $state(false);
  loadIndex().then((i) => { index = i; editable = canEdit(i); }).catch((e) => (error = String(e)));

  const firstPaper = $derived(index?.papers[0]?.id);
  const paperId = $derived(route.paper || firstPaper);
  const paper = $derived(index?.papers.find((p) => p.id === paperId));
  const versions = $derived(pageVersions(index));
  const thisVersion = $derived(versions.find((v) => v.id === index?.version));
  const docNames = $derived((index?.findings?.general || []).filter((f) => f.code === "module-doc-name"));
  // The chosen project's audit pins this version; when some of its claims carry no revision,
  // the version is only as its author declares it, and the page says so.
  const unchecked = $derived(thisVersion && index?.audits?.[project.repo]?.paper_version &&
                             index.audits[project.repo].paper_version.checked !== true);
  function chooseVersion(id) {
    const v = versions.find((x) => x.id === id);
    const to = v && v.id !== index.version ? versionHref(v, project.combined ? null : project.repo) : null;
    if (to) location.assign(to);
  }
  const releaseMismatch = $derived(index && route.release && route.release !== index.release);
  // With the audits shown together: the default audit, and how the audits are ordered.
  const lead = $derived(project.combined ? auditOf(index, project.repo) : null);
  const byStars = $derived(index?.audit_order_by === "stars");
</script>

{#if error}
  <main class="state"><h1>MachineChecked</h1><p>The site's data could not be loaded: {error}</p></main>
{:else if !index}
  <main class="state"><p class="muted">Loading…</p></main>
{:else}
  <div class="app-shell" class:reading={route.view === "read"}>
  <div class="shell-top">
  <header class="top">
    <a class="brand" href={index.mode === "paper" ? "/" : href(index.release, "read", firstPaper)} aria-label={index.mode === "paper" ? "MachineChecked home" : "Back to the paper"}>
      <svg viewBox="0 0 32 32" width="20" height="20" aria-hidden="true"
        ><circle cx="13" cy="13" r="9" fill="none" stroke="currentColor" stroke-width="3" /><path
          d="M20 20l8 8" stroke="currentColor" stroke-width="3" stroke-linecap="round" /></svg
      >
      <span>MachineChecked</span>
    </a>
    {#if index.papers.length > 1}
      <nav class="papers">
        {#each index.papers as p}
          <a class:on={route.view === "read" && p.id === paperId} href={href(index.release, "read", p.id)} title={p.title}>Paper {p.id}</a>
        {/each}
      </nav>
    {:else if paper}
      <span class="ptitle" title={paper.title}><TexInline text={paper.title} /></span>
    {/if}
    {#if index.mode === "paper"}
      {@const repos = index.projects || []}
      {#if thisVersion || repos.length > 1}
      <div class="choices">
      {#if versions.length > 1 && thisVersion}
        <label class="project" title="Choose the version of the paper: each has its own PDF, claim numbers and audits">
          <span>Version</span>
          <select value={thisVersion.id} onchange={(e) => chooseVersion(e.currentTarget.value)} aria-label="Paper version shown">
            {#each versions as v}<option value={v.id}>{versionLabel(v)}</option>{/each}
          </select>
        </label>
      {:else if thisVersion}
        <span class="version" title="The version of the paper shown">{versionLabel(thisVersion)}</span>
      {/if}
      {#if unchecked}
        <span class="version unchecked" title="Some of this audit's claims record no revision of the paper, so the version is as the audit's author declares it">Version declared by the audit's author, not checked against its claims</span>
      {/if}
      {#if repos.length > 1}
        <label class="project" title="Choose the project whose evidence to show, or every audit of this version">
          <span>Formalisation</span>
          <select value={project.combined ? "" : project.repo} onchange={(e) => chooseProject(e.currentTarget.value)} aria-label="Formalisation shown">
            {#if project.order.length > 1}<option value="">All audits, {byStars ? "by stars" : "listing order"}</option>{/if}
            {#each repos as r}<option value={r}>{r}</option>{/each}
          </select>
        </label>
      {/if}
      </div>
      {/if}
      <a class="aux" href="/papers/">Papers</a>
    {:else}
    {#if index.review_queue}
      <a class="aux" class:on={route.view === "review"} href={href(index.release, "review")}>Review</a>
    {/if}
    <a class="aux" class:on={route.view === "coverage"} href={href(index.release, "coverage")}>Overview</a>
    {/if}
    <Search {index} />
  </header>

  {#if AUDIT && auditInfo}
    <div class="banner attribution">
      <span>Audit by {auditInfo.author || "the project"}</span>
      <a href={href(index.release, "changes")}>Details</a>
    </div>
  {/if}
  {#if lead}
    <div class="banner together" data-together title="Each claim shows the status of one audit, named in its panel">
      Showing the audit of <code>{project.repo}</code>{lead.author ? " by " + lead.author : ""}{byStars ? " (most GitHub stars)" : ""}. Claims it does not map show the next audit that does, labelled.
    </div>
  {/if}
  {#if releaseMismatch}
    <div class="banner" role="alert">
      Showing release <code>{index.release}</code>. The link requests <code>{route.release}</code>.
    </div>
  {/if}
  {#if index.notes?.length}
    <div class="banner">{#each index.notes as n}<div>{n}</div>{/each}</div>
  {/if}
  {#if docNames.length}
    <details class="banner docnames">
      <summary>Warning: {docNames.filter((f) => !f.dismissed).length} name(s) in module docstrings are not declared in the project or its dependencies{docNames.some((f) => f.dismissed) ? ` (${docNames.filter((f) => f.dismissed).length} dismissed)` : ""}</summary>
      <ul>
        {#each docNames as f (f.id)}
          <li class:dismissed={f.dismissed}>{f.message}{#if f.dismissed}<span class="dz"> · dismissed by {f.dismissed.by}: “{f.dismissed.rationale}”</span>{:else if f.dismissal_stale}<span class="dz"> · an earlier dismissal no longer applies</span>{/if}</li>
        {/each}
      </ul>
    </details>
  {/if}

  </div>
  <div class="workspace">
  {#if route.view === "claim" && route.claim}
    <main class="page"><Passport {index} claimId={route.claim} full {editable} /></main>
  {:else if route.view === "coverage"}
    <Coverage {index} />
  {:else if route.view === "changes"}
    <Changes {index} />
  {:else if route.view === "review" && index.review_queue}
    <Review {index} />
  {:else}
    <Reader {index} paperId={paperId} claimId={route.claim} {editable} />
  {/if}
  </div>
  </div>
{/if}

<style>
  .app-shell { min-height: 100dvh; display: grid; grid-template-rows: auto minmax(0, 1fr); }
  .app-shell.reading { height: 100dvh; }
  .shell-top { min-width: 0; z-index: 20; }
  .workspace { min-width: 0; min-height: 0; }
  /* On a reader route nothing in the workspace lengthens the page or is scrolled into view by it. */
  .reading .workspace { position: relative; overflow: clip; }
  .state { max-width: 640px; margin: 15vh auto; padding: 0 16px; }
  .top {
    position: sticky; top: 0; z-index: 20;
    display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px;
    padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .brand { display: flex; align-items: center; gap: 6px; color: var(--accent); font-family: var(--serif); font-weight: 600; }
  .ptitle { font-family: var(--serif); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40vw; }
  .papers { display: flex; gap: 4px; }
  .papers a, .aux { padding: 4px 10px; border-radius: 6px; color: var(--muted); white-space: nowrap; }
  .papers a:hover, .aux:hover { background: var(--surface-2); text-decoration: none; }
  .papers a.on, .aux.on { background: var(--accent-soft); color: var(--text); }
  .aux { font-size: 14px; }
  :global(.top .aux:first-of-type) { margin-left: auto; }
  .banner { padding: 8px 16px; background: var(--surface-2); border-bottom: 1px solid var(--border); font-size: 14px; }
  .docnames summary { cursor: pointer; }
  .docnames ul { margin: 6px 0 0; padding-left: 18px; font-size: 13px; }
  .docnames .dismissed { color: var(--faint); }
  .docnames .dz { color: var(--muted); }
  .together code { overflow-wrap: anywhere; }
  .attribution { display: flex; gap: 12px; align-items: baseline; font-size: 13px; }
  .page { max-width: 1560px; margin: 0 auto; padding: 24px 16px 80px; }
  @media (max-width: 640px) {
    .top { gap: 8px; padding: 8px 12px; flex-wrap: wrap; }
    .ptitle { max-width: 100%; flex: 1 1 180px; font-size: 14px; }
    .brand span { display: none; }
  }
  .choices { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin-left: auto; min-width: 0; }
  .project { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); min-width: 0; }
  .version { font-size: 13px; color: var(--muted); white-space: nowrap; }
  .version.unchecked { white-space: normal; font-style: italic; }
  .project select { font: inherit; min-width: 0; max-width: min(42vw, 320px); padding: 3px 6px; border-radius: 6px; border: 1px solid var(--accent); background: var(--surface); color: var(--text); }
  /* On a phone each selector takes its own row, so a long label ("Latest manuscript (commit …)")
     is shown whole. */
  @media (max-width: 640px) {
    .choices { flex: 1 1 100%; }
    .project { flex: 1 1 100%; }
    .project select { flex: 1 1 auto; max-width: none; }
  }
</style>
