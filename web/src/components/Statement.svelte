<script>
  import LeanText from "./LeanText.svelte";
  import { gloss } from "../lib/gloss.js";

  // A locked proposition as its quantifier prefix and its conclusion.
  // `ext` highlights from outside (a linked symbol of the paper): a variable ({var}) or a
  // binder's type ({type}); `onactive` hears which variable is highlighted here.
  // `onpinned` hears which variable is held (clicked), and `onterm` which sub-term is selected
  // ({where, k}: `b:<binder>` for a binder's type, `c` for the conclusion, `l:<n>` for the n-th
  // part of a conclusion split by its logic), for choosing one. `ext` may also be {term}.
  let { st, spec = null, onref, compact = false, ext = null, onactive = null, onpinned = null,
        onterm = null } = $props();

  const binders = $derived(st.binders || []);
  const refs = $derived([...(st.closure || []), ...(st.direct || [])].sort((a, b) => b.length - a.length));
  const ROLE = { forall: "for all", exists: "there is", hypothesis: "assume", instance: "assume" };
  // An instance that supplies data (`[Inhabited E]`: a chosen element) is given, not assumed.
  const roleOf = (b) => (b.role === "instance" && b.supplies === "data" ? "given" : ROLE[b.role] || b.role);

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
  // The variables of the statement by number: the prefix's binders, then each "there is" inside
  // the conclusion (numbered by the probe after the prefix, each witness its own number).
  const vars = $derived.by(() => {
    const out = [...binders];
    const walk = (n) => {
      if (!n) return;
      if (n.op === "exists" || n.op === "forall") out[n.var] = { role: n.op, name: n.name, type: n.type, binder: "explicit", inner: true };
      (n.args || []).forEach(walk);
    };
    walk(st.conclusion?.logic);
    return out;
  });

  // A variable of the statement, highlighted while hovered or focused, and held by a click.
  let hover = $state(null);
  let pinned = $state(null);
  const active = $derived(hover ?? pinned ?? ext?.var ?? null);
  $effect(() => { onactive?.(hover ?? pinned); });
  $effect(() => { onpinned?.(pinned); });

  // A selected sub-term, and where it is.
  let termSel = $state(null);
  $effect(() => { onterm?.(termSel); });
  const termAt = (where) => where == null ? null
    : termSel?.where === where ? termSel.k : ext?.term?.where === where ? ext.term.k : null;
  function setTerm(where, k) { termSel = k == null ? null : { where, k }; if (k != null) pinned = null; }
  // The parts of a conclusion split by its logic, numbered in reading order.
  const leafIds = $derived.by(() => {
    const m = new Map();
    const walk = (n) => { if (!n) return; if (n.leaf) m.set(n, m.size); else (n.args || []).forEach(walk); };
    walk(st.conclusion?.logic);
    return m;
  });
  function ppAt(where) {
    if (!where) return null;
    if (where === "c") return st.conclusion;
    if (where.startsWith("b:")) return binders[+where.slice(2)]?.type;
    if (where.startsWith("x:")) return vars[+where.slice(2)]?.type;
    if (where.startsWith("l:")) return [...leafIds].find(([, i]) => i === +where.slice(2))?.[0]?.leaf;
    return null;
  }
  const termText = $derived.by(() => {
    if (!termSel) return null;
    const pp = ppAt(termSel.where), t = pp?.terms?.[termSel.k];
    return t ? pp.segments.slice(t.from, t.to).map((x) => x.t).join("") : null;
  });
  function onvar(i, how) {
    if (how === "pin") { pinned = pinned === i ? null : i; noted = null; termSel = null; }
    else hover = i;
  }
  // A name's plain-English note, shown on request beside the name.
  let noted = $state(null);
  function ongloss(name) { noted = noted === name ? null : name; pinned = null; }
  const groupOf = (i) => groups.find((g) => g.head === i);
</script>

{#snippet lean(pp, where = null)}<LeanText {pp} {onref} {refs} {active} {onvar} {ongloss} term={termAt(where)} onterm={where == null ? null : (k) => setTerm(where, k)} />{/snippet}

{#snippet name(i)}<span class="v" class:hl={active === i} role="button" tabindex="0" onmouseenter={() => onvar(i, "hover")} onmouseleave={() => onvar(null, "hover")} onclick={() => onvar(i, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvar(i, "pin"))}>{vars[i].name}</span>{/snippet}

{#snippet condition(i, where = null)}
  {@const b = binders[i]}
  <span class="role">{roleOf(b)}</span>
  {#if b.role === "hypothesis"}<span class="hn">({b.name})</span>{:else}<span class="hn">instance</span>{/if}
  {@render lean(b.type, where)}
{/snippet}

{#snippet logic(node, depth)}
  {#if node.leaf}
    {@render lean(node.leaf, "l:" + leafIds.get(node))}
  {:else if node.op === "not"}
    <span class="op">it is not the case that</span>
    <div class="parts witness">{@render logic(node.args[0], depth + 1)}</div>
  {:else if node.op === "implies"}
    <div class="line"><span class="role">if</span><div class="body">{@render logic(node.args[0], depth + 1)}</div></div>
    <div class="line"><span class="role">then</span><div class="body">{@render logic(node.args[1], depth + 1)}</div></div>
  {:else if node.op === "exists" || node.op === "forall"}
    <div class="line"><span class="role">{node.op === "exists" ? "there is" : "for every"}</span>{@render name(node.var)}<span class="colon"> : </span><span class="ty" class:hl={ext?.type === node.var}>{@render lean(node.type, "x:" + node.var)}</span><span class="op">{node.op === "exists" ? "such that" : ","}</span></div>
    <div class="parts witness">{@render logic(node.args[0], depth + 1)}</div>
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
  {#if binders.length}
    <ol class="ribbon" aria-label="Quantifiers and hypotheses, in order">
      {#each groups as g}
        {#if g.head != null}
          {@const b = binders[g.head]}
          <li class={"b " + b.role}>
            <div class="line">
              <span class="role">{roleOf(b)}</span>
              {@render name(g.head)}<span class="colon"> : </span>
              <span class="ty" class:hl={ext?.type === g.head}>{@render lean(b.type, "b:" + g.head)}</span>
            </div>
            {#each g.members as m}
              <div class="line sub">{@render condition(m, "b:" + m)}</div>
            {/each}
          </li>
        {:else}
          <li class={"b " + binders[g.members[0]].role}><div class="line">{@render condition(g.members[0], "b:" + g.members[0])}</div></li>
        {/if}
      {/each}
    </ol>
  {/if}
  {#if st.conclusion}
    <div class="concl">
      {#if binders.length}<span class="role">then</span>{/if}
      <div class="body">
        {#if st.conclusion.logic}{@render logic(st.conclusion.logic, 0)}{:else}{@render lean(st.conclusion, "c")}{/if}
      </div>
    </div>
  {/if}
  {#if pinned != null && vars[pinned]}
    {@const b = vars[pinned]}
    <div class="inspect" aria-live="polite">
      <p><span class="v">{b.name}</span><span class="colon"> : </span>{@render lean(b.type)}
        <button class="x" aria-label="Release" onclick={() => (pinned = null)}>×</button></p>
      <p class="small faint">{b.inner && b.role === "exists" ? "Chosen by the statement (there is), for the part it belongs to" : b.inner ? "Any value (for every), in the part it belongs to" : b.role === "exists" ? "Chosen by the statement (there is)" : b.role === "forall" ? "Any value (for all)" : ROLE[b.role]}{#if b.binder === "implicit" || b.binder === "strict-implicit"}; written implicitly{/if}</p>
      {#each groupOf(pinned)?.members || [] as m}
        <p class="small">{@render condition(m)}</p>
      {/each}
    </div>
  {/if}
  {#if termText}
    <div class="inspect term" aria-live="polite">
      <p><span class="small faint">Sub-expression</span><button class="x" aria-label="Release" onclick={() => (termSel = null)}>×</button></p>
      <p><code>{termText}</code></p>
      <p class="small faint">Activate it again to select the expression around it.</p>
    </div>
  {/if}
  {#if noted && gloss(noted)}
    <div class="inspect note" aria-live="polite">
      <p><code>{noted}</code><button class="x" aria-label="Close" onclick={() => (noted = null)}>×</button></p>
      <p class="small">{gloss(noted)}</p>
      <p class="small faint">A plain-English note on this name; the Lean definition is what the statement uses.</p>
    </div>
  {/if}
  {#if !compact && vars.some((b) => b?.role === "exists")}
    <p class="hint faint">
      The order of the rows is the order of the quantifiers: a “there is” above a “for all”
      chooses one value for every case below it.
    </p>
  {/if}
</div>

<style>
  .stmt { margin-top: 12px; font-size: 17px; }
  .stmt :global(.lean) { font-family: var(--serif); font-size: 18px; line-height: 1.6; }
  .stmt :global(.lean button), .stmt :global(.lean a) { min-height: 0; }
  .name { margin: 0 0 8px; font-size: 13px; color: var(--muted); }
  .ribbon { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .b { padding: 3px 0; }
  .line { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .line.sub { margin: 2px 0 0 18px; }




  .role { font-size: 14px; color: var(--muted); min-width: 64px; }
  .sub .role { min-width: 46px; }
  .v { font-family: var(--mono); font-weight: 600; cursor: pointer; border-radius: 3px; }
  .v.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
  .ty.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 3px; }
  .hn { font-family: var(--mono); color: var(--faint); font-size: 12px; }
  .colon { color: var(--faint); }
  .concl { margin-top: 6px; padding: 10px 0; border-top: 1px solid var(--border); display: flex; gap: 8px; align-items: baseline; }
  .concl .body { min-width: 0; flex: 1; }
  .op { font-size: 12px; color: var(--muted); }
  .parts { margin: 2px 0 0; padding-left: 18px; }
  .parts li { margin: 2px 0; }
  .witness { padding-left: 18px; border-left: 2px solid color-mix(in srgb, var(--st-refuted) 50%, transparent); margin: 2px 0 2px 4px; }
  .compact .concl { margin-top: 0; }
  .under { margin: 0 0 6px; font-size: 13px; color: var(--muted); }
  .more { margin: 6px 0; border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 13px; padding: 0; }
  .hint { font-size: 12px; margin: 6px 0 0; }
  .inspect { margin-top: 8px; padding: 6px 10px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 6px; background: var(--surface); }
  .inspect p { margin: 2px 0; display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
  .inspect .x { margin-left: auto; border: 0; background: none; cursor: pointer; color: var(--muted); font-size: 16px; line-height: 1; }
  .small { font-size: 13px; }
</style>
