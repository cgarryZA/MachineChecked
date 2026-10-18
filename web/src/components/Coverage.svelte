<script>
  import TexInline from "./TexInline.svelte";
  import { notProved, projectClaims } from "../lib/data.js";
  import { statusView, statusSummary } from "../lib/presentation.js";
  import { href } from "../lib/route.svelte.js";
  import StatusChip from "./StatusChip.svelte";

  let { index } = $props();
  let onlyNotProved = $state(false);

  // A numbered environment ("Theorem 2.1") as against an equation, part or prose claim.
  const isEnv = (c) => /^[A-Z][a-z]+ (?:[A-Z](?:\.[0-9]+)+|[A-Z]?[0-9][0-9.]*)[a-z]?$/.test(c.number || "");
  const short = (c) => (isEnv(c) ? c.number.replace(/^[A-Za-z]+ /, "") : c.number || c.id);

  const papers = $derived(
    index.papers.map((p) => {
      const claims = projectClaims(index).filter((c) => c.paper === p.id);
      return { ...p, claims, shown: onlyNotProved ? claims.filter(notProved) : claims };
    }),
  );
  const tiers = $derived(index.findings.total || {});
</script>

<main class="cov">
  <section class="intro">
    <h1>Coverage</h1>
    <p class="muted">
      Every listed claim, with the status recorded by the engine.
      For claims marked “{statusView({ status_code: "formal.accepted" }).label}”:
      {statusView({ status_code: "formal.accepted" }).explanation}
    </p>
    <div class="tools">
      <label><input type="checkbox" bind:checked={onlyNotProved} /> Show only what is not accepted</label>
      <span class="findings">
        {#each ["violation", "warning", "obligation"] as t}
          <span class={"tier " + t} title={t === "warning" ? "heuristics that may be wrong; not defects" : ""}>{tiers[t] || 0} {t}{(tiers[t] || 0) === 1 ? "" : "s"}{t === "warning" ? " (heuristic)" : ""}</span>
        {/each}
      </span>
    </div>
  </section>

  {#each papers as p (p.id)}
    <section class="paper">
      <div class="phead">
        <h2>{p.title}</h2>
        <a href={href(index.release, "read", p.id)}>Read the paper →</a>
      </div>
      <p class="prov faint">
        Paper {p.id} · {p.mode === "latex" ? "from LaTeX source" : "PDF only: statements not hashed from source"}
        {#if p.revision}· revision <code>{p.revision.slice(0, 12)}</code>{/if}
      </p>

      {#if index.gates?.[p.id]}
        {@const g = index.gates[p.id]}
        <div class="gates">
          {#if g.source === "pdf"}
            <p class="source">Source: the paper's PDF, as its authors published it (no LaTeX). Its hash is pinned and checked; claims are found by their headings, so their positions are approximate.</p>
          {/if}
          <details class={"gate " + (g.consistency.pass ? "pass" : "fail")}>
            <summary><strong>Consistency check</strong>: {g.consistency.pass ? "passed" : `failed (${g.consistency.failures.length})`}
              <span class="faint">· every check runs; open or unreviewed claims are statuses, not failures</span></summary>
            {#if g.consistency.failures.length}
              <ul>{#each g.consistency.failures as f}<li>{f}</li>{/each}</ul>
            {/if}
          </details>
          <details class={"gate " + (g.release.pass ? "pass" : "fail")}>
            <summary><strong>Release gate</strong>: {g.release.pass ? "passed" : `not passed (${g.release.reasons.length} reasons)`}
              <span class="faint">· the paper as a whole: every claim accepted, every scope decision reviewed, a Comparator replay</span></summary>
            {#if g.release.reasons.length}
              <ul>{#each g.release.reasons as r}<li>{r}</li>{/each}</ul>
            {/if}
          </details>
        </div>
      {/if}

      {#each [["Numbered statements", p.shown.filter(isEnv)], ["Equations, parts and prose claims", p.shown.filter((c) => !isEnv(c))]] as [label, group]}
        {#if group.length}
          <h3 class="glabel">{label} <span class="faint">({group.length})</span></h3>
          <div class="grid" role="list">
            {#each group as c (c.id)}
              <a role="listitem" class={"cell st-" + statusView(c).class} href={href(index.release, "read", p.id, c.id)}
                title={`${c.number || c.id}: ${statusView(c).label}`}>
                <span class="num">{short(c)}</span>
                <span class="kind">{isEnv(c) ? (c.number || "").split(" ")[0] : c.kind}</span>
              </a>
            {/each}
          </div>
        {/if}
      {:else}
        <p class="muted">Every claim of this paper in scope is accepted.</p>
      {/each}

      <table class="sum">
        <thead><tr><th>Status</th><th class="n">Claims</th></tr></thead>
        <tbody>
          {#each statusSummary(p.claims) as s}
            <tr><td><StatusChip record={s} /></td><td class="n">{s.count}</td></tr>
          {/each}
        </tbody>
      </table>

      <details class="list">
        <summary>All claims as a list</summary>
        <ul>
          {#each p.shown as c (c.id)}
            <li>
              <a href={href(index.release, "claim", c.id)}>{c.number || c.id}</a>
              {#if c.heading || c.title}<span class="muted"><TexInline text={c.heading || c.title} /></span>{/if}
              <StatusChip record={c} small />
            </li>
          {/each}
        </ul>
      </details>
    </section>
  {/each}
</main>


<style>
  .cov { max-width: 1040px; margin: 0 auto; padding: 28px 16px 80px; }
  .intro h1 { font-family: var(--serif); font-size: 30px; font-weight: 600; }
  .intro p { max-width: 70ch; }
  .tools { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; margin-top: 8px; }
  .findings { display: flex; gap: 12px; font-size: 13px; }
  .tier { padding: 2px 8px; border-radius: 999px; border: 1px solid var(--border); }
  .tier.violation { color: var(--tier-violation); }
  .tier.warning { color: var(--tier-warning); }
  .tier.obligation { color: var(--tier-obligation); }
  .paper { margin-top: 32px; padding: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
  .phead { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }
  .phead h2 { font-family: var(--serif); font-size: 21px; font-weight: 600; }
  .prov { margin: 4px 0 16px; font-size: 13px; }
  .gates { display: flex; flex-direction: column; gap: 6px; margin: 0 0 16px; }
  .source { margin: 0; color: var(--muted); font-size: 13px; }
  .gate { border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; border-left: 4px solid var(--st-unspecified); }
  .gate.pass { border-left-color: var(--st-accepted); }
  .gate.fail { border-left-color: var(--st-open); }
  .gate summary { cursor: pointer; }
  .gate ul { margin: 6px 0 4px; padding-left: 18px; max-height: 320px; overflow: auto; font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(64px, 1fr)); gap: 6px; }
  .cell {
    display: flex; flex-direction: column; justify-content: center; align-items: center;
    height: 56px; border-radius: 6px; color: var(--text);
    background: color-mix(in srgb, var(--st) 18%, var(--surface));
    border: 1px solid color-mix(in srgb, var(--st) 55%, var(--surface));
    border-left: 5px solid var(--st);
  }
  .cell.st-out-of-scope { background: repeating-linear-gradient(135deg, var(--surface-2) 0 6px, var(--surface) 6px 12px); }
  .cell:hover { text-decoration: none; filter: brightness(0.96); }
  .num { font-weight: 600; font-variant-numeric: tabular-nums; max-width: 100%; padding: 0 4px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .glabel { font-size: 13px; font-weight: 600; color: var(--muted); margin: 16px 0 8px; }
  .kind { font-size: 11px; color: var(--muted); max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 4px; }
  .sum { margin-top: 18px; border-collapse: collapse; min-width: 320px; }
  .sum th, .sum td { text-align: left; padding: 4px 12px 4px 0; border-bottom: 1px solid var(--border); }
  .sum th { font-size: 12px; color: var(--muted); font-weight: 500; }
  .n { text-align: right !important; font-variant-numeric: tabular-nums; }
  .list { margin-top: 14px; }
  .list summary { cursor: pointer; color: var(--muted); }
  .list ul { list-style: none; padding: 0; }
  .list li { display: flex; gap: 10px; align-items: center; padding: 4px 0; flex-wrap: wrap; }
</style>
