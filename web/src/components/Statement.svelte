<script>
  import LeanText from "./LeanText.svelte";

  // A locked proposition as its quantifier prefix and its conclusion.
  let { st, spec = null, onref, compact = false } = $props();

  // Compact, a statement shows its conclusion and one line naming its variables and counting its
  // assumptions; the ordered statement opens on request. A prefix with a "there is" is always
  // shown in order, since folding it would hide which choices depend on which.
  let expanded = $state(false);
  const binders = $derived(st.binders || []);
  const folded = $derived(compact && !expanded && binders.length > 0 && !binders.some((b) => b.role === "exists"));
  const summary = $derived.by(() => {
    const vars = binders.filter((b) => b.role === "forall").map((b) => b.name);
    const n = binders.filter((b) => b.role === "hypothesis" || b.role === "instance").length;
    const under = n ? `under ${n} assumption${n > 1 ? "s" : ""}` : "";
    if (!vars.length) return under.charAt(0).toUpperCase() + under.slice(1) + ":";
    return "For all " + vars.join(", ") + (under ? ", " + under : "") + ":";
  });
  const refs = $derived([...(st.closure || []), ...(st.direct || [])].sort((a, b) => b.length - a.length));
  const ROLE = { forall: "for all", exists: "there is", hypothesis: "assume", instance: "instance" };
</script>

<div class="stmt" class:compact>
  {#if !compact && spec}
    <p class="name"><code>{spec}</code></p>
  {/if}
  {#if folded}
    <p class="under">{summary}</p>
    {#if st.conclusion}<div class="concl result"><LeanText pp={st.conclusion} {onref} {refs} /></div>{/if}
    <button class="more" onclick={() => (expanded = true)}>Show the full statement ({binders.length + 1} lines, in order)</button>
  {:else}
  {#if st.binders?.length}
    <ol class="ribbon" aria-label="Quantifiers and hypotheses, in order">
      {#each binders as b, i}
        <li class={"b " + b.role}>
          <span class="role">{ROLE[b.role] || b.role}</span>
          {#if b.role === "hypothesis"}
            <span class="hn">({b.name})</span>
          {:else if b.role !== "instance"}
            <span class="v">{b.name}</span><span class="colon"> : </span>
          {/if}
          <LeanText pp={b.type} {onref} {refs} />
        </li>
      {/each}
    </ol>
  {/if}
  {#if st.conclusion}
    <div class="concl">
      {#if st.binders?.length}<span class="role">then</span>{/if}
      <LeanText pp={st.conclusion} {onref} {refs} />
    </div>
  {/if}
  {#if compact && expanded}
    <button class="more" onclick={() => (expanded = false)}>Show less</button>
  {/if}
  {/if}
  {#if !compact && st.binders?.some((b) => b.role === "exists")}
    <p class="hint faint">
      The order of the rows is the order of the quantifiers: a “there is” above a “for all”
      chooses one value for every case below it.
    </p>
  {/if}
</div>

<style>
  .stmt { margin-top: 12px; }
  .name { margin: 0 0 8px; font-size: 13px; color: var(--muted); }
  .ribbon { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .b { display: flex; gap: 8px; align-items: baseline; padding: 4px 10px; border-radius: 6px; background: var(--surface-2); border-left: 3px solid var(--border); flex-wrap: wrap; }
  .b.forall { border-left-color: var(--accent); }
  .b.exists { border-left-color: var(--st-refuted); }
  .b.hypothesis { border-left-color: var(--st-open); }
  .b.instance { border-left-color: var(--faint); }
  .role { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); min-width: 64px; }
  .v { font-family: var(--mono); font-weight: 600; }
  .hn { font-family: var(--mono); color: var(--faint); font-size: 12px; }
  .colon { color: var(--faint); }
  .concl { margin-top: 6px; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .compact .concl { margin-top: 0; }
  .under { margin: 0 0 6px; font-size: 13px; color: var(--muted); }
  .more { margin: 6px 0; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 13px; padding: 0; }
  .hint { font-size: 12px; margin: 6px 0 0; }
</style>
