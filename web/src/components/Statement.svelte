<script>
  import LeanText from "./LeanText.svelte";
  import Expansion from "./Expansion.svelte";
  import { gloss } from "../lib/gloss.js";
  import { carriedOf } from "../lib/carried.js";
  import { expansionFor, expansionsOf } from "../lib/expand.js";
  import { spineOf, conclusionOf, nodesOf, quantifies } from "../lib/tree.js";

  // A locked proposition as one tree (`tree`, from the probe), shown as the binders that open it,
  // in order, and its conclusion; a hypothesis that quantifies shows its own structure under it.
  // `ext` highlights from outside (a linked symbol of the paper): a variable ({var}) or a
  // binder's type ({type}); `onactive` hears which variable is highlighted here.
  // `onpinned` hears which variable is held (clicked), and `onterm` which sub-term is selected
  // ({where, k}: `b:<binder>` for a binder's type, `c` for the conclusion, `l:<n>` for the n-th
  // part of a conclusion split by its logic), for choosing one. `ext` may also be {at}: a
  // sub-term, or one occurrence of a variable, by its identity. `selId` is the sub-term selected in
  // another view of the same statement (the exact Lean), by that identity; `onselect` hears the
  // identity of the one selected here. `mark` lists positions of applications to mark (the
  // occurrences of a warning).
  let { st, spec = null, onref, compact = false, ext = null, onactive = null, onpinned = null,
        onterm = null, selId = null, onselect = null, mark = null } = $props();

  // The binders that open the statement, each with what the tree gives it (its properties and,
  // for a hypothesis, its own tree), and the shape of the conclusion under them.
  const binders = $derived(spineOf(st));
  const shape = $derived(conclusionOf(st));
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
  // The variables of the statement by number: the binders that open it, then each variable
  // bound inside the conclusion and inside a hypothesis (numbered by the probe after them, each
  // its own number).
  const vars = $derived.by(() => {
    const out = [...binders];
    for (const n of nodesOf(st)) {
      if ((n.op === "exists" || n.op === "forall") && n.var >= binders.length)
        out[n.var] = { role: n.op, name: n.name, type: n.type, binder: n.binder || "explicit", scope: n.scope, within: n.within || [], inner: true };
    }
    return out;
  });

  // A variable of the statement, highlighted while hovered or focused, and held by a click.
  let hover = $state(null);
  let pinned = $state(null);
  const active = $derived(hover ?? pinned ?? ext?.var ?? null);
  $effect(() => { onactive?.(hover ?? pinned); });
  $effect(() => { onpinned?.(pinned, pinned != null ? vars[pinned]?.name ?? null : null); });

  // A selected sub-term, and where it is.
  let termSel = $state(null);
  $effect(() => { onterm?.(termSel); });
  const idOf = (sel) => (sel ? ppAt(sel.where)?.terms?.[sel.k]?.id ?? null : null);
  // A selection made in another view replaces the one made here.
  $effect(() => { if (selId != null && termSel && idOf(termSel) !== selId) termSel = null; });
  const outerId = $derived(termSel ? null : selId ?? ext?.at ?? null);
  const termAt = (where) => where == null ? null
    : termSel?.where === where ? termSel.k : null;
  // Only a choice made here is reported: dropping this view's selection for one made in another
  // view must not clear that one.
  function setTerm(where, k) {
    alone = null;
    termSel = k == null ? null : { where, k };
    if (k != null) pinned = null;
    onselect?.(idOf(termSel));
  }
  // The parts of the conclusion, numbered in reading order (`l:<n>`), and those of the
  // hypotheses' own trees (`h:<n>`).
  const leafKeys = $derived.by(() => {
    const m = new Map();
    const walk = (n, tag) => {
      if (!n) return;
      if (n.leaf) m.set(n, tag + [...m.values()].filter((k) => k.startsWith(tag)).length);
      else (n.args || []).forEach((a) => walk(a, tag));
    };
    walk(shape, "l:");
    binders.forEach((b) => walk(b.logic, "h:"));
    return m;
  });
  function ppAt(where) {
    if (!where) return null;
    if (where === "c") return st.conclusion;
    if (where.startsWith("b:")) return binders[+where.slice(2)]?.type;
    if (where.startsWith("x:")) return vars[+where.slice(2)]?.type;
    if (where.startsWith("l:") || where.startsWith("h:")) return [...leafKeys].find(([, k]) => k === where)?.[0]?.leaf;
    if (where.startsWith("p:")) return carriedPP[+where.slice(2)] || null;
    return null;
  }
  // A definition expanded at one of its applications: the selected sub-term's, or one the
  // printed expression gives no sub-term of its own (`alone`).
  let alone = $state(null);
  const termExpansion = $derived(termSel ? expansionFor(ppAt(termSel.where), termSel.k) : null);
  function expand(where, o) {
    if (o.k >= 0) setTerm(where, termSel?.where === where && termSel.k === o.k ? null : o.k);
    else { termSel = null; alone = alone === o.x ? null : o.x; }
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

  // Properties carried by an object's type (`properties`, from the probe): the fields of a
  // subtype, structure or class, as they apply to that object, with where each comes from. A
  // given object's properties are part of what is given; a witness's are established with it;
  // an object inside an assumption keeps its properties inside that assumption. Every printed
  // property is numbered (`p:<n>`) so that a sub-term of it can be selected.
  const carriedPP = $derived(carriedOf(st).map((c) => c.prop.type));
  const keyOf = (pp) => "p:" + carriedPP.indexOf(pp);
  const short = (n) => (n || "").split(".").pop();
  // How an object's properties stand in the statement: given with a supplied object, stated by
  // an assumption whose type is a structure of propositions, established with a witness the
  // statement produces, or local to the clause or assumption that contains the object (inside a
  // negation, an alternative, an equivalence or the premise of an implication).
  const BASIS = {
    given: "Included in the type of the given object.",
    states: "What this assumption states, field by field.",
    produced: "Producing this object establishes these properties of its type.",
    local: "Part of this object's type, within the clause that contains it.",
    inside: "Part of this assumption's object.",
  };
  const ROLE_P = { given: "in its type", states: "it states", produced: "with it", local: "in its type", inside: "in its type" };
  // More fields than this are folded under their summary.
  const FOLD = 8;
  const howOf = (b) => b.role === "exists" ? "produced"
    : b.role === "hypothesis" || (b.role === "instance" && b.supplies === "proposition") ? "states" : "given";
  // How the properties of a quantified object stand, from where the probe places it (`scope`):
  // given or produced; inside a hypothesis of the statement; or local to the negation,
  // alternative, equivalence or premise that contains it. Older data says only whether the
  // object is local (`local`).
  const basisOf = (n, local) => !n.scope ? (local ? "local" : n.op === "exists" ? "produced" : "given")
    : n.scope === "given" || n.scope === "produced" ? n.scope
    : n.scope === "assumed" && n.within?.[0] === "assume" ? "inside" : "local";
  // What a variable bound inside the statement is, from where it stands.
  const STANDS = {
    produced: "Chosen by the statement (there is), for the part it belongs to",
    given: "Any value (for every), in the part it belongs to",
    denied: "Inside a negation: the statement says there is no such value",
    alternative: "Inside one alternative of an “or”: chosen only in that case",
    equivalent: "Inside one side of an equivalence",
  };
  function standsOf(b) {
    if (b.scope === "assumed") {
      const where = b.within?.[0] === "assume" ? "Inside an assumption" : "Inside the premise of an “if”";
      return where + (b.role === "exists" ? ": not chosen by the statement" : ": any value");
    }
    if (b.scope === "denied" && b.role !== "exists") return "Inside a negation";
    return STANDS[b.scope];
  }
  const SCOPE = { forall: "for every", exists: "there is", if: "if", then: "then", and: "and", or: "or", iff: "iff", not: "not" };
</script>

{#snippet lean(pp, where = null)}<LeanText {pp} {onref} {refs} {active} {onvar} {ongloss} {mark} term={termAt(where)} selId={outerId} onterm={where == null ? null : (k) => setTerm(where, k)} />{#if where != null}{@const os = expansionsOf(pp)}{#if os.length}{" "}<span class="xs">expand{#each os as o}{" "}<button class="xb" class:on={o.k >= 0 ? termSel?.where === where && termSel.k === o.k : alone === o.x} aria-label={"Expand " + o.text + " at its arguments"} onclick={() => expand(where, o)}>{o.label}</button>{/each}</span>{/if}{/if}{/snippet}

{#snippet name(i)}<span class="v" class:hl={active === i} role="button" tabindex="0" onmouseenter={() => onvar(i, "hover")} onmouseleave={() => onvar(null, "hover")} onclick={() => onvar(i, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvar(i, "pin"))}>{vars[i].name}</span>{/snippet}

{#snippet carried(o, how)}
  {@const ps = o?.properties || []}
  {#if ps.length || o?.properties_error}
    {@const props = ps.filter((p) => p.kind === "proposition")}
    {@const data = ps.filter((p) => p.kind === "data")}
    <details class={"carried " + how} data-carried={how} open={ps.length <= FOLD}>
      <summary class="small faint basis">{BASIS[how]}{#if ps.length > FOLD}{" "}({props.length} propert{props.length === 1 ? "y" : "ies"}, {data.length} data field{data.length === 1 ? "" : "s"}){/if}</summary>
      {#each props as p (p.field)}
        <div class="line prop" data-field={p.field}><span class="role">{ROLE_P[how]}</span><span class="pbody">{@render lean(p.type, keyOf(p.type))}<span class="origin" title={(p.projection || p.field) + (p.module ? " · " + p.module : "")}>field <code>{p.field}</code> of <code>{short(p.structure)}</code>{#if p.inherited}, from <code>{short(p.declared_in)}</code>{/if}</span></span></div>
      {/each}
      {#if data.length}
        <div class="line data"><span class="role">data</span><span class="fields">{#each data as p, k (p.field)}{#if k}{", "}{/if}<code>{p.term}</code>{" : "}{@render lean(p.type)}{/each}</span></div>
      {/if}
      {#if o.properties_omitted}<p class="small faint">{o.properties_omitted} further field{o.properties_omitted === 1 ? " of this type is" : "s of this type are"} not listed.</p>{/if}
      {#if o.properties_error}<p class="small bad">The fields of this type could not be read: {o.properties_error}</p>{/if}
    </details>
  {/if}
{/snippet}

{#snippet inside(b)}
  {#if b.logic && quantifies(b.logic)}
    <div class="inner within" data-within={b.id}>
      <p class="small faint">Inside this assumption:</p>
      <div class="body">{@render logic(b.logic, 1, true)}</div>
    </div>
  {/if}
  {#if b.logic_error}<p class="small bad">The structure of this assumption could not be read: {b.logic_error}</p>{/if}
  {#each b.objects || [] as o (o.id)}
    <div class="inner" data-inner={o.id}>
      <p class="small"><span class="faint">inside this assumption{#if o.scope.length}{" "}({o.scope.map((x) => SCOPE[x] || x).join(" › ")}){/if}:</span> {o.op === "exists" ? "there is" : "for every"} <code>{o.name}</code> : {@render lean(o.type)}</p>
      {@render carried(o, "inside")}
    </div>
  {/each}
{/snippet}

{#snippet condition(i, where = null)}
  {@const b = binders[i]}
  <span class="role">{roleOf(b)}</span>
  {#if b.role === "hypothesis"}<span class="hn">({b.name})</span>{:else}<span class="hn">instance</span>{/if}
  {@render lean(b.type, where)}
{/snippet}

{#snippet logic(node, depth, local = false)}
  {#if node.leaf}
    {@render lean(node.leaf, leafKeys.get(node))}
  {:else if node.op === "not"}
    <span class="op">it is not the case that</span>
    <div class="parts witness">{@render logic(node.args[0], depth + 1, true)}</div>
  {:else if node.op === "implies"}
    <div class="line"><span class="role">if</span><div class="body">{@render logic(node.args[0], depth + 1, true)}</div></div>
    <div class="line"><span class="role">then</span><div class="body">{@render logic(node.args[1], depth + 1, local)}</div></div>
  {:else if node.op === "exists" || node.op === "forall"}
    <div class="line"><span class="role">{node.op === "exists" ? "there is" : "for every"}</span>{@render name(node.var)}<span class="colon"> : </span><span class="ty" class:hl={ext?.type === node.var}>{@render lean(node.type, "x:" + node.var)}</span><span class="op">{node.op === "exists" ? "such that" : ","}</span></div>
    {@render carried(node, basisOf(node, local))}
    <div class="parts witness">{@render logic(node.args[0], depth + 1, local)}</div>
  {:else}
    <span class="op">{OP[node.op] || node.op}</span>
    <ul class="parts">
      {#each node.op === "iff" ? node.args : flat(node, node.op) as part}
        <li>{@render logic(part, depth + 1, local || node.op !== "and")}</li>
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
            {@render carried(b, howOf(b))}
            {#each g.members as m}
              <div class="line sub">{@render condition(m, "b:" + m)}</div>
              <div class="subc">{@render carried(binders[m], howOf(binders[m]))}{@render inside(binders[m])}</div>
            {/each}
          </li>
        {:else}
          {@const m = g.members[0]}
          <li class={"b " + binders[m].role}><div class="line">{@render condition(m, "b:" + m)}</div>{@render carried(binders[m], howOf(binders[m]))}{@render inside(binders[m])}</li>
        {/if}
      {/each}
    </ol>
  {/if}
  {#if st.conclusion}
    <div class="concl">
      {#if binders.length}<span class="role">then</span>{/if}
      <div class="body">
        {#if shape}{@render logic(shape, 0)}{:else}{@render lean(st.conclusion, "c")}{/if}
      </div>
    </div>
  {/if}
  {#if pinned != null && vars[pinned]}
    {@const b = vars[pinned]}
    <div class="inspect" aria-live="polite">
      <p><span class="v">{b.name}</span><span class="colon"> : </span>{@render lean(b.type)}
        <button class="x" aria-label="Release" onclick={() => (pinned = null)}>×</button></p>
      <p class="small faint">{b.inner && b.scope ? standsOf(b) : b.inner && b.role === "exists" ? "Chosen by the statement (there is), for the part it belongs to" : b.inner ? "Any value (for every), in the part it belongs to" : b.role === "exists" ? "Chosen by the statement (there is)" : b.role === "forall" ? "Any value (for all)" : ROLE[b.role]}{#if b.binder === "implicit" || b.binder === "strict-implicit"}; written implicitly{/if}</p>
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
      {#if termExpansion}<Expansion x={termExpansion.x} occ={termExpansion.text} {onref} {refs} />{/if}
    </div>
  {/if}
  {#if alone}
    <div class="inspect term" aria-live="polite">
      <Expansion x={alone} {onref} {refs} onclose={() => (alone = null)} />
    </div>
  {/if}
  {#if noted && gloss(noted)}
    <div class="inspect note" aria-live="polite">
      <p><code>{noted}</code><button class="x" aria-label="Close" onclick={() => (noted = null)}>×</button></p>
      <p class="small">{gloss(noted)}</p>
      <p class="small faint">A plain-English note on this name; the Lean definition is what the statement uses.</p>
    </div>
  {/if}
  {#if !compact && vars.some((b) => b?.role === "exists" && b.scope !== "assumed")}
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
  .carried { margin: 2px 0 4px 18px; padding-left: 10px; border-left: 2px solid var(--border); }
  .carried.produced { border-left-color: color-mix(in srgb, var(--st-refuted) 50%, transparent); }
  .carried .role { min-width: 74px; font-size: 13px; }
  .carried :global(.lean) { font-size: 16px; }
  .pbody { min-width: 0; flex: 1; }
  .origin { display: block; font-size: 12px; color: var(--faint); }
  .origin code, .fields code { font-size: 12px; }
  .fields { font-size: 13px; color: var(--muted); }
  .basis { margin: 2px 0; cursor: pointer; }
  .inner { margin: 2px 0 4px 18px; }
  .inner p { margin: 2px 0; }
  .subc:empty { display: none; }
  .bad { color: var(--st-malformed); }
  .xs { font-size: 12px; color: var(--faint); font-family: var(--sans, inherit); white-space: normal; }
  .xb { border: 1px solid var(--border); border-radius: 10px; background: none; color: var(--accent); cursor: pointer; font: 12px var(--mono); padding: 0 6px; min-height: 0; }
  .xb.on { background: color-mix(in srgb, var(--st-open) 22%, transparent); }
</style>
