<script>
  // The semantic summary of one listed audit, under that audit's line of the paper panel.
  // machinechecked.org gives it on the audit's registry entry (`semantic`): read from that audit's
  // own `prooflens/semantic-summary@1` and checked against it, with the counts of this paper.
  // Shown per unit: the claims and their links, the correspondence and evidence basis of the
  // summary's selected set of readings, the reviews and the recorded findings, each count linked
  // to those claims in that audit's Overview, and the other sets of readings, counted apart.
  // Every count is the summary's own, in its words (lib/semantic.js): nothing is computed here,
  // no count is added to another, and a count the summary does not give is not shown. A summary
  // the site could not show is said with why; an audit without one shows nothing here.
  import { UNITS, keys, words, setLabel, unitInventoryText } from "../lib/semantic.js";
  let { audit } = $props();

  const https = (u) => typeof u === "string" && /^https:\/\/[^\s"'<>]+$/.test(u);
  const positive = (n) => Number.isInteger(n) && n > 0;
  const text = (v) => (typeof v === "string" && v ? v : null);
  const s = $derived(audit?.semantic && typeof audit.semantic === "object" ? audit.semantic : null);
  const shown = $derived(s && s.state === "loaded" && https(audit.url) && s.paper && typeof s.paper === "object" &&
    text(s.release) && text(s.selected) ? s : null);
  const sets = $derived(Array.isArray(shown?.sets) ? shown.sets.filter((x) => x && typeof x.id === "string") : []);
  const selected = $derived(sets.find((x) => x.id === shown?.selected) || { id: shown?.selected });
  const others = $derived(sets.filter((x) => x.id !== shown?.selected));

  // The audit's Overview, at the summary's release, filtered as the address says.
  function overview(filters) {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v));
    return "/read/?audit=" + encodeURIComponent(audit.url) + "#/r/" + encodeURIComponent(shown.release) +
      "/overview" + (q.size ? "?" + q : "");
  }

  // A set of readings in the summary's words, with the authors of the audit's own readings.
  function whose(set) {
    const by = set?.kind === "audit" && Array.isArray(set.by) ? set.by.filter(text) : [];
    return (setLabel(set) || set?.id || "") + (by.length ? `, by ${by.join(", ")}` : "");
  }

  // A unit's counts in one dimension: the selected set's for correspondence and basis.
  function table(dimension, unit) {
    const p = shown.paper;
    const t = dimension === "coverage" || dimension === "basis" ? p[dimension]?.[shown.selected]?.[unit] : p[dimension]?.[unit];
    return t && typeof t === "object" ? t : {};
  }
  const DIMENSIONS = [["Correspondence", "coverage", "coverage"], ["Evidence basis", "basis", "basis"],
                      ["Reviews", "review", "review"], ["Recorded findings (a claim may have several kinds)", "findings", "finding"]];
  const rows = $derived(shown ? UNITS.map((unit) => ({
    unit, head: unitInventoryText(shown.paper, unit),
    dims: DIMENSIONS.map(([label, dimension, param]) => {
      const t = table(dimension, unit);
      return { label, dimension, items: keys(dimension).filter((k) => Object.hasOwn(t, k) && positive(t[k]))
        .map((k) => ({ key: k, n: t[k], ...words(dimension, k, unit), href: overview({ set: shown.selected, unit, [param]: k }) })) };
    }).filter((d) => d.items.length),
  })).filter((r) => r.head) : []);
  const lead = $derived(whose(selected));
</script>

{#if shown && rows.length}
  <div class="semantic small" data-audit={audit.url} data-digest={text(shown.digest) || ""}>
    <p>Semantic summary. Correspondence and evidence basis: {lead.slice(0, 1).toLowerCase() + lead.slice(1)}.</p>
    {#each rows as r (r.unit)}
      <div class="unit" data-unit={r.unit}>
        <p class="head">{r.head}</p>
        {#each r.dims as d (d.dimension)}
          <p data-dimension={d.dimension}>{d.label}:{" "}{#each d.items as it, i (it.key)}{#if i}{" · "}{/if}<a href={it.href} title={it.explanation || null} data-key={it.key}>{it.label} ({it.n})</a>{/each}</p>
        {/each}
      </div>
    {/each}
    {#if others.length}
      <p class="others">Counted apart:{" "}{#each others as o, i (o.id)}{#if i}{" · "}{/if}<a href={overview({ set: o.id, unit: "statements" })}>{whose(o)}</a>{/each}</p>
    {/if}
    <details>
      <summary>Source</summary>
      Read from {#if https(shown.url)}<a href={shown.url} target="_blank" rel="noopener">its data</a>{:else}its data{/if},
      <code>{text(shown.schema) || "prooflens/semantic-summary@1"}</code>, release <code>{shown.release}</code>{#if text(shown.commit)}, project commit <code>{shown.commit.slice(0, 12)}</code>{/if}{#if text(shown.revision)}, paper revision <code>{shown.revision.slice(0, 12)}</code>{/if}{#if text(shown.digest)}, digest <code>{shown.digest.slice(0, 12)}</code>{/if}.
    </details>
  </div>
{:else if s && text(s.state) && s.state !== "loaded"}
  <p class="semantic-state small muted" data-audit={audit.url} data-state={s.state}>Semantic summary {s.state}{text(s.detail) ? ": " + s.detail : ""}</p>
{/if}

<style>
  .semantic { margin: 4px 0 8px; padding-left: 10px; border-left: 2px solid var(--border); overflow-wrap: anywhere; }
  .semantic p { margin: 3px 0; }
  .unit { margin: 6px 0; }
  .head { font-weight: 600; }
  details summary { cursor: pointer; color: var(--muted); }
  code { font-size: 12px; }
  .semantic-state { margin: 2px 0 6px; overflow-wrap: anywhere; }
  .small { font-size: 13px; }
  .muted { color: var(--muted); }
</style>
