<script>
  import LeanText from "./LeanText.svelte";
  import { gloss } from "../lib/gloss.js";

  // A locked proposition as its quantifier prefix and its conclusion.
  let { st, spec = null, onref, compact = false } = $props();

  // A statement is shown in full: its assumptions are what a reader compares with the paper.
  // Only a long one, in a compact view, folds to its conclusion and one line naming its
  // variables and counting its assumptions, with the ordered statement on request. A prefix with
  // a "there is" is never folded, since that would hide which choices depend on which.
  let expanded = $state(false);
  const binders = $derived(st.binders || []);
  const textOf = (pp) => (typeof pp === "string" ? pp : pp?.text ?? (pp?.segments || []).map((x) => x.t).join(""));
  const long = $derived(binders.length > 8 || binders.reduce((n, b) => n + textOf(b.type).length, 0) > 900);
  const folded = $derived(compact && long && !expanded && !binders.some((b) => b.role === "exists"));
  const summary = $derived.by(() => {
    const vars = binders.filter((b) => b.role === "forall").map((b) => b.name);
    const n = binders.filter((b) => b.role === "hypothesis" || b.role === "instance").length;
    const under = n ? `under ${n} assumption${n > 1 ? "s" : ""}` : "";
    if (!vars.length) return under.charAt(0).toUpperCase() + under.slice(1) + ":";
    return "For all " + vars.join(", ") + (under ? ", " + under : "") + ":";
  });
  const refs = $derived([...(st.closure || []), ...(st.direct || [])].sort((a, b) => b.length - a.length));
  const ROLE = { forall: "for all", exists: "there is", hypothesis: "assume", instance: "assume" };

  // The prefix in its own order, with an object's conditions beside it: a condition (a
  // hypothesis or an instance) that directly follows an object of a "for all", or that object's
  // other conditions, and mentions that object only, is shown under it. Nothing moves: a
  // condition on several objects, or on an earlier one, stays a row of its own, and nothing is
  // grouped with a "there is".
  const varsOf = (pp) => new Set((pp?.segments || []).filter((x) => x.var != null).map((x) => x.var));
  const groups = $derived.by(() => {
    const out = [];
    binders.forEach((b, i) => {
      if (b.role === "forall" || b.role === "exists") { out.push({ head: i, members: [] }); return; }
      const last = out.at(-1), vs = varsOf(b.type);
      if (last?.head != null && binders[last.head].role === "forall" && vs.size === 1 && vs.has(last.head)) last.members.push(i);
      else out.push({ head: null, members: [i] });
    });
    return out;
  });

  // The conclusion by its logical shape (`logic`, from the probe): a conjunction, disjunction or
  // equivalence lists its parts; a chain of the same connective is one list.
  const flat = (node, op) => (node.op === op ? node.args.flatMap((a) => flat(a, op)) : [node]);
  const OP = { and: "all of the following", or: "at least one of the following", iff: "the following are equivalent" };

  // A variable of the statement, highlighted while hovered or focused, and held by a click.
  let hover = $state(null);
  let pinned = $state(null);
  const active = $derived(hover ?? pinned);
  function onvar(i, how) {
    if (how === "pin") { pinned = pinned === i ? null : i; noted = null; }
    else hover = i;
  }
  // A name's plain-English note, shown on request beside the name.
  let noted = $state(null);
  function ongloss(name) { noted = noted === name ? null : name; pinned = null; }
  const groupOf = (i) => groups.find((g) => g.head === i);
</script>

{#snippet lean(pp)}<LeanText {pp} {onref} {refs} {active} {onvar} {ongloss} />{/snippet}

{#snippet name(i)}<span class="v" class:hl={active === i} role="button" tabindex="0" onmouseenter={() => onvar(i, "hover")} onmouseleave={() => onvar(null, "hover")} onclick={() => onvar(i, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvar(i, "pin"))}>{binders[i].name}</span>{/snippet}

{#snippet condition(i)}
  {@const b = binders[i]}
  <span class="role">{ROLE[b.role] || b.role}</span>
  {#if b.role === "hypothesis"}<span class="hn">({b.name})</span>{:else}<span class="hn">instance</span>{/if}
  {@render lean(b.type)}
{/snippet}

{#snippet logic(node, depth)}
  {#if node.leaf}
    {@render lean(node.leaf)}
  {:else}
    <span class="op">{OP[node.op] || node.op}</span>
    <ul class="parts">
      {#each node.op === "iff" ? node.args : flat(node, node.op) as part}
        <li>{@render logic(part, depth + 1)}</li>
      {/each}
    </ul>
  {/if}
{/snippet}

<div class="stmt" class:compact>
  {#if !compact && spec}
    <p class="name"><code>{spec}</code></p>
  {/if}
  {#if folded}
    <p class="under">{summary}</p>
    {#if st.conclusion}<div class="concl result">{@render lean(st.conclusion)}</div>{/if}
    <button class="more" onclick={() => (expanded = true)}>Show the full statement ({binders.length + 1} lines, in order)</button>
  {:else}
  {#if binders.length}
    <ol class="ribbon" aria-label="Quantifiers and hypotheses, in order">
      {#each groups as g}
        {#if g.head != null}
          {@const b = binders[g.head]}
          <li class={"b " + b.role}>
            <div class="line">
              <span class="role">{ROLE[b.role] || b.role}</span>
              {@render name(g.head)}<span class="colon"> : </span>
              {@render lean(b.type)}
            </div>
            {#each g.members as m}
              <div class="line sub">{@render condition(m)}</div>
            {/each}
          </li>
        {:else}
          <li class={"b " + binders[g.members[0]].role}><div class="line">{@render condition(g.members[0])}</div></li>
        {/if}
      {/each}
    </ol>
  {/if}
  {#if st.conclusion}
    <div class="concl">
      {#if binders.length}<span class="role">then</span>{/if}
      <div class="body">
        {#if st.conclusion.logic}{@render logic(st.conclusion.logic, 0)}{:else}{@render lean(st.conclusion)}{/if}
      </div>
    </div>
  {/if}
  {#if pinned != null && binders[pinned]}
    {@const b = binders[pinned]}
    <div class="inspect" aria-live="polite">
      <p><span class="v">{b.name}</span><span class="colon"> : </span>{@render lean(b.type)}
        <button class="x" aria-label="Release" onclick={() => (pinned = null)}>×</button></p>
      <p class="small faint">{b.role === "exists" ? "Chosen by the statement (there is)" : b.role === "forall" ? "Any value (for all)" : ROLE[b.role]}{#if b.binder === "implicit" || b.binder === "strict-implicit"}; written implicitly{/if}</p>
      {#each groupOf(pinned)?.members || [] as m}
        <p class="small">{@render condition(m)}</p>
      {/each}
    </div>
  {/if}
  {#if noted && gloss(noted)}
    <div class="inspect note" aria-live="polite">
      <p><code>{noted}</code><button class="x" aria-label="Close" onclick={() => (noted = null)}>×</button></p>
      <p class="small">{gloss(noted)}</p>
      <p class="small faint">A plain-English note on this name; the Lean definition is what the statement uses.</p>
    </div>
  {/if}
  {#if compact && long && expanded}
    <button class="more" onclick={() => (expanded = false)}>Show less</button>
  {/if}
  {/if}
  {#if !compact && binders.some((b) => b.role === "exists")}
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
  .b { padding: 4px 10px; border-radius: 6px; background: var(--surface-2); border-left: 3px solid var(--border); }
  .line { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .line.sub { margin: 2px 0 0 18px; }
  .b.forall { border-left-color: var(--accent); }
  .b.exists { border-left-color: var(--st-refuted); }
  .b.hypothesis { border-left-color: var(--st-open); }
  .b.instance { border-left-color: var(--faint); }
  .role { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); min-width: 64px; }
  .sub .role { min-width: 46px; }
  .v { font-family: var(--mono); font-weight: 600; cursor: pointer; border-radius: 3px; }
  .v.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
  .hn { font-family: var(--mono); color: var(--faint); font-size: 12px; }
  .colon { color: var(--faint); }
  .concl { margin-top: 6px; padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border); display: flex; gap: 8px; align-items: baseline; }
  .concl .body { min-width: 0; flex: 1; }
  .op { font-size: 12px; color: var(--muted); }
  .parts { margin: 2px 0 0; padding-left: 18px; }
  .parts li { margin: 2px 0; }
  .compact .concl { margin-top: 0; }
  .under { margin: 0 0 6px; font-size: 13px; color: var(--muted); }
  .more { margin: 6px 0; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 13px; padding: 0; }
  .hint { font-size: 12px; margin: 6px 0 0; }
  .inspect { margin-top: 8px; padding: 6px 10px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 6px; background: var(--surface); }
  .inspect p { margin: 2px 0; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
  .inspect .x { margin-left: auto; border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 16px; line-height: 1; }
  .small { font-size: 13px; }
</style>
