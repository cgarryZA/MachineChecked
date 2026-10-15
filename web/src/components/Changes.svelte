<script>
  // What changed between releases. Comparison needs two releases of the evidence; until there
  // is a second, this shows what this release was built from.
  let { index } = $props();
</script>

<main class="ch">
  <h1>Changes</h1>
  <p class="muted">
    A comparison lists, between two releases, every proposition and definition whose fingerprint
    changed, the reviews that reopened as a result, the manuscript claims whose source changed, and
    changes of toolchain or dependencies. This site holds one release.
  </p>
  <h2>This release</h2>
  <dl>
    <dt>Release</dt><dd><code>{index.release}</code></dd>
    <dt>Evidence</dt><dd><code>{index.evidence}</code></dd>
    <dt>Built</dt><dd>{index.created}</dd>
    {#if index.lean}<dt>Lean</dt><dd>{index.lean.lean} <span class="faint">({index.lean.githash?.slice(0, 12)})</span></dd>{/if}
    {#if index.project}
      <dt>Project</dt>
      <dd>{index.project.name} {#if index.project.commit}<code>{index.project.commit.slice(0, 12)}</code>{/if}{index.project.dirty ? " with uncommitted changes" : ""}</dd>
      {#if index.project.toolchain}<dt>Toolchain</dt><dd><code>{index.project.toolchain}</code></dd>{/if}
      {#each Object.entries(index.project.dependencies || {}) as [n, r]}
        <dt>{n}</dt><dd><code>{r}</code></dd>
      {/each}
    {/if}
    {#each index.papers as p}
      <dt>Paper {p.id}</dt>
      <dd>{p.mode === "latex" ? "LaTeX" : "PDF only"}{#if p.revision} at <code>{p.revision.slice(0, 12)}</code>{/if}{#if p.root}, root <code>{p.root}</code>{/if}{#if p.pdf_sha256}, PDF <code title={p.pdf_sha256}>{p.pdf_sha256.slice(0, 12)}</code>{/if}</dd>
    {/each}
    <dt>Tool</dt><dd>{index.tool?.name} {index.tool?.version} <span class="faint">({index.tool?.fingerprint})</span></dd>
  </dl>
</main>

<style>
  .ch { max-width: 860px; margin: 0 auto; padding: 28px 16px 80px; }
  h1 { font-family: var(--serif); font-size: 30px; font-weight: 600; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin-top: 24px; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 18px; }
  dt { color: var(--muted); }
  dd { margin: 0; word-break: break-all; }
</style>
