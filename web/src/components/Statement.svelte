<script>
  import LeanText from "./LeanText.svelte";
  import Expansion from "./Expansion.svelte";
  import { gloss } from "../lib/gloss.js";
  import { carriedOf } from "../lib/carried.js";
  import { expansionFor, expansionsOf } from "../lib/expand.js";
  import { spineOf, conclusionOf, nodesOf, quantifies } from "../lib/tree.js";
  import { statementRows, exactPart } from "../lib/comparison.js";
  import { printedById } from "../lib/math.js";

  // A locked proposition as one tree (`tree`, from the probe), shown in rows: each object that
  // opens it with the conditions on it alone, each other condition, then the conclusion
  // (`comparison.statementRows`); a hypothesis that quantifies shows its own structure under it.
  // `ext` highlights from outside (a linked symbol of the paper): a variable ({var}) or a
  // binder's type ({type}); `onactive` hears which variable is highlighted here.
  // `onpinned` hears which variable is held (clicked), and `onterm` which sub-term is selected
  // ({where, k}: `b:<binder>` for a binder's type, `c` for the conclusion, `l:<n>` for the n-th
  // part of a conclusion split by its logic), for choosing one. `ext` may also be {at}: a
  // sub-term, or one occurrence of a variable, by its identity. `selId` is the sub-term selected in
  // another view of the same statement (the exact Lean), by that identity; `onselect` hears the
  // identity of the one selected here. `mark` lists positions of applications to mark (the
  // occurrences of a warning).
  //
  // In a comparison each row has a readable cell and, with `exact`, the exact Lean of that row
  // beside it; `readable` (a snippet of the row, the statement and what this view shares with it,
  // `ioOf`) replaces the readable cell's default rendering when a structured rendering of the row
  // is available. `paper` (a snippet of
  // the row's key and `spec`) fills a paper cell before each row; `after` (the same) is drawn
  // under each row, where its inspections open. `onref` hears a declaration opened and the row it was opened
  // from; `onproperty` hears a carried property chosen for inspection, with its object, how it
  // stands and its row.
  let { st, spec = null, onref, compact = false, ext = null, onactive = null, onpinned = null,
        onterm = null, selId = null, onselect = null, mark = null,
        exact = false, readable = null, paper = null, after = null, onproperty = null } = $props();

  // The binders that open the statement, each with what the tree gives it (its properties and,
  // for a hypothesis, its own tree), and the shape of the conclusion under them.
  const binders = $derived(spineOf(st));
  const shape = $derived(conclusionOf(st));
  const rows = $derived(statementRows(st));
  const groups = $derived(rows.filter((r) => !r.conclusion));
  const finalRow = $derived(rows.find((r) => r.conclusion) || null);
  const refs = $derived([...(st.closure || []), ...(st.direct || [])].sort((a, b) => b.length - a.length));
  const ROLE = { forall: "for all", exists: "there is", hypothesis: "assume", instance: "assume" };
  // An instance that supplies data (`[Inhabited E]`: a chosen element) is given, not assumed.
  const roleOf = (b) => (b.role === "instance" && b.supplies === "data" ? "given" : ROLE[b.role] || b.role);
  const refAt = (row) => (onref ? (name) => onref(name, row) : null);

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

  // A variable of the statement, highlighted while hovered or focused, and held by a click, with
  // the row it was held in (its note is drawn under that row).
  let hover = $state(null);
  let pinned = $state(null);
  let pinnedRow = $state(null);
  const active = $derived(hover ?? pinned ?? ext?.var ?? null);
  $effect(() => { onactive?.(hover ?? pinned); });
  $effect(() => { onpinned?.(pinned, pinned != null ? vars[pinned]?.name ?? null : null); });

  // A selected sub-term, where it is, and the row it is in.
  let termSel = $state(null);
  $effect(() => { onterm?.(termSel ? { where: termSel.where, k: termSel.k } : null); });
  const idOf = (sel) => (sel ? ppAt(sel.where)?.terms?.[sel.k]?.id ?? null : null);
  // A selection made in another view replaces the one made here.
  $effect(() => { if (selId != null && termSel && idOf(termSel) !== selId) termSel = null; });
  const outerId = $derived(termSel ? null : selId ?? ext?.at ?? null);
  const currentId = $derived(termSel ? idOf(termSel) : outerId);
  const termAt = (where) => where == null ? null
    : termSel?.where === where ? termSel.k : null;
  // Only a choice made here is reported: dropping this view's selection for one made in another
  // view must not clear that one.
  function setTerm(where, k, row) {
    alone = null;
    termSel = k == null ? null : { where, k, row };
    if (k != null) pinned = null;
    onselect?.(idOf(termSel));
  }
  // A sub-term chosen in a row's exact Lean is the same sub-term of its readable expression,
  // when that expression has it; otherwise it is selected by its identity for every view.
  function setExact(where, pp, k, row) {
    const id = k == null ? null : pp?.terms?.[k]?.id ?? null;
    const own = ppAt(where)?.terms?.findIndex((t) => t.id === id) ?? -1;
    if (id != null && own >= 0) return setTerm(where, own, row);
    termSel = null; alone = null;
    if (id != null) pinned = null;
    onselect?.(id);
  }
  // A sub-term chosen in a structured rendering of a row (`readable`): its identity as the exact
  // statement shows it (`id`), the identity of the application it renders (`at`) and its row.
  // It is the selection of every view, and a selection made in another view replaces it.
  let readSel = $state(null);
  $effect(() => { if (selId != null && readSel && readSel.id !== selId) readSel = null; });
  function selectId(id, at, row) {
    termSel = null; alone = null;
    readSel = id == null ? null : { id, at, row };
    if (id != null) pinned = null;
    onselect?.(id);
  }
  const readText = $derived(readSel ? exactPart(st, readSel.id)?.text ?? null : null);
  // The definition applied at the chosen sub-term, at its arguments.
  const readExpansion = $derived.by(() => {
    if (!readSel?.at) return null;
    for (const pp of printedById(st).values()) {
      const x = (pp.expansions || []).find((e) => e.at === readSel.at);
      if (x) return { x, text: readText };
    }
    return null;
  });
  // The place (`where`) of the printed expression with identity `id`: a binder's type, the
  // conclusion, a part of the conclusion or of a hypothesis, an inner binder's type or a
  // carried property.
  function whereOf(id) {
    if (id == null) return null;
    const i = binders.findIndex((b) => b.type?.id === id);
    if (i >= 0) return "b:" + i;
    if (st.conclusion?.id === id) return "c";
    for (const [n, k] of leafKeys) if (n.leaf?.id === id) return k;
    const v = vars.findIndex((b) => b?.inner && b.type?.id === id);
    if (v >= 0) return "x:" + v;
    const p = carriedPP.findIndex((pp) => pp?.id === id);
    return p >= 0 ? "p:" + p : null;
  }
  // What a structured rendering of row `g` shares with this view: the highlighted variable and
  // the handler of one hovered or held, the selected sub-term and the handler of one chosen
  // there, the marks, a linked symbol's highlight (`ext`), the handlers of a declaration, a
  // name's note and a carried property opened from the row, and the chips that expand the
  // definitions a printed expression applies (`chips`, a snippet of its identity and the row).
  const ioOf = (g) => ({ active, sel: currentId ?? readSel?.id ?? null, mark, ext, chips,
    onvar: onvarAt(g.key), ongloss: onglossAt(g.key), onref: refAt(g.key),
    onselect: (id, at) => selectId(id, at, g.key),
    onproperty: onproperty ? (p, how) => onproperty(p, null, how, g.key) : null });

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
  // printed expression gives no sub-term of its own (`alone`, with its row).
  let alone = $state(null);
  const termExpansion = $derived(termSel ? expansionFor(ppAt(termSel.where), termSel.k) : null);
  function expand(where, o, row) {
    if (o.k >= 0) setTerm(where, termSel?.where === where && termSel.k === o.k ? null : o.k, row);
    else { termSel = null; alone = alone?.x === o.x ? null : { x: o.x, row }; }
  }
  const termText = $derived.by(() => {
    if (!termSel) return null;
    const pp = ppAt(termSel.where), t = pp?.terms?.[termSel.k];
    return t ? pp.segments.slice(t.from, t.to).map((x) => x.t).join("") : null;
  });
  const onvarAt = (row) => (i, how) => {
    if (how === "pin") { pinned = pinned === i ? null : i; pinnedRow = row; noted = null; termSel = null; }
    else hover = i;
  };
  // A name's plain-English note, shown on request under its row.
  let noted = $state(null);
  const onglossAt = (row) => (name) => { noted = noted?.name === name ? null : { name, row }; pinned = null; };
  const groupOf = (i) => groups.find((g) => g.head === i || g.heads?.includes(i));

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

  // The exact Lean of a row, piece by piece as the exact statement opens: each object it
  // quantifies, each hypothesis and instance (the exact statement's own sub-term when it has
  // one), and the conclusion.
  const BIND = { explicit: ["(", ")"], implicit: ["{", "}"], "strict-implicit": ["⦃", "⦄"], instance: ["[", "]"] };
  const exactOf = (pp) => (pp?.id != null && exactPart(st, pp.id)) || pp;
  // Beside its readable cell when the statement is wide enough; else not drawn, since the
  // complete exact statement follows the rows.
  let width = $state(0);
  const besideExact = $derived(exact && width >= 620);
</script>

{#snippet lean(pp, where, row)}<LeanText {pp} onref={refAt(row)} {refs} {active} onvar={onvarAt(row)} ongloss={onglossAt(row)} {mark} term={termAt(where)} selId={outerId} onterm={where == null ? null : (k) => setTerm(where, k, row)} />{#if where != null}{@render expandAt(pp, where, row)}{/if}{/snippet}

<!-- The definitions a printed expression applies, each to expand at its arguments. -->
{#snippet expandAt(pp, where, row)}{@const os = expansionsOf(pp)}{#if os.length}{" "}<span class="xs">expand{#each os as o}{" "}<button class="xb" class:on={o.k >= 0 ? termSel?.where === where && termSel.k === o.k : alone?.x === o.x} aria-label={"Expand " + o.text + " at its arguments"} onclick={() => expand(where, o, row)}>{o.label}</button>{/each}</span>{/if}{/snippet}

{#snippet chips(id, row)}{@const where = whereOf(id)}{#if where != null}{@render expandAt(ppAt(where), where, row)}{/if}{/snippet}

{#snippet xlean(pp, where, row)}<LeanText {pp} onref={refAt(row)} {refs} selId={currentId} onterm={(k) => setExact(where, pp, k, row)} />{/snippet}

{#snippet name(i, row)}<span class="v" class:hl={active === i} role="button" tabindex="0" onmouseenter={() => onvarAt(row)(i, "hover")} onmouseleave={() => onvarAt(row)(null, "hover")} onclick={() => onvarAt(row)(i, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvarAt(row)(i, "pin"))}>{vars[i].name}</span>{/snippet}

{#snippet carried(o, how, row)}
  {@const ps = o?.properties || []}
  {#if ps.length || o?.properties_error}
    {@const props = ps.filter((p) => p.kind === "proposition")}
    {@const data = ps.filter((p) => p.kind === "data")}
    <details class={"carried " + how} data-carried={how} open={ps.length <= FOLD}>
      <summary class="small faint basis">{BASIS[how]}{#if ps.length > FOLD}{" "}({props.length} propert{props.length === 1 ? "y" : "ies"}, {data.length} data field{data.length === 1 ? "" : "s"}){/if}</summary>
      {#each props as p (p.field)}
        <div class="line prop" data-field={p.field}><span class="role">{ROLE_P[how]}</span><span class="pbody">{@render lean(p.type, keyOf(p.type), row)}{#if onproperty}<button class="origin" data-property={p.type?.id} title={(p.projection || p.field) + (p.module ? " · " + p.module : "")} aria-label={"Inspect the property " + p.field + " of " + (o.name || "this object")} onclick={() => onproperty(p, o, how, row)}>field <code>{p.field}</code> of <code>{short(p.structure)}</code>{#if p.inherited}, from <code>{short(p.declared_in)}</code>{/if}</button>{:else}<span class="origin" title={(p.projection || p.field) + (p.module ? " · " + p.module : "")}>field <code>{p.field}</code> of <code>{short(p.structure)}</code>{#if p.inherited}, from <code>{short(p.declared_in)}</code>{/if}</span>{/if}</span></div>
      {/each}
      {#if data.length}
        <div class="line data"><span class="role">data</span><span class="fields">{#each data as p, k (p.field)}{#if k}{", "}{/if}<code>{p.term}</code>{" : "}{@render lean(p.type, null, row)}{/each}</span></div>
      {/if}
      {#if o.properties_omitted}<p class="small faint">{o.properties_omitted} further field{o.properties_omitted === 1 ? " of this type is" : "s of this type are"} not listed.</p>{/if}
      {#if o.properties_error}<p class="small bad">The fields of this type could not be read: {o.properties_error}</p>{/if}
    </details>
  {/if}
{/snippet}

{#snippet inside(b, row)}
  {#if b.logic && quantifies(b.logic)}
    <div class="inner within" data-within={b.id}>
      <p class="small faint">Inside this assumption:</p>
      <div class="body">{@render logic(b.logic, 1, true, row)}</div>
    </div>
  {/if}
  {#if b.logic_error}<p class="small bad">The structure of this assumption could not be read: {b.logic_error}</p>{/if}
  {#each b.objects || [] as o (o.id)}
    <div class="inner" data-inner={o.id}>
      <p class="small"><span class="faint">inside this assumption{#if o.scope.length}{" "}({o.scope.map((x) => SCOPE[x] || x).join(" › ")}){/if}:</span> {o.op === "exists" ? "there is" : "for every"} <code>{o.name}</code> : {@render lean(o.type, null, row)}</p>
      {@render carried(o, "inside", row)}
    </div>
  {/each}
{/snippet}

{#snippet condition(i, where, row)}
  {@const b = binders[i]}
  <span class="role">{roleOf(b)}</span>
  {#if b.role === "hypothesis"}<span class="hn">({b.name})</span>{:else}<span class="hn">instance</span>{/if}
  {@render lean(b.type, where, row)}
{/snippet}

{#snippet logic(node, depth, local, row)}
  {#if node.leaf}
    {@render lean(node.leaf, leafKeys.get(node), row)}
  {:else if node.op === "not"}
    <span class="op">it is not the case that</span>
    <div class="parts witness">{@render logic(node.args[0], depth + 1, true, row)}</div>
  {:else if node.op === "implies"}
    <div class="line"><span class="role">if</span><div class="body">{@render logic(node.args[0], depth + 1, true, row)}</div></div>
    <div class="line"><span class="role">then</span><div class="body">{@render logic(node.args[1], depth + 1, local, row)}</div></div>
  {:else if node.op === "exists" || node.op === "forall"}
    <div class="line"><span class="role">{node.op === "exists" ? "there is" : "for every"}</span>{@render name(node.var, row)}<span class="colon"> : </span><span class="ty" class:hl={ext?.type === node.var}>{@render lean(node.type, "x:" + node.var, row)}</span><span class="op">{node.op === "exists" ? "such that" : ","}</span></div>
    {@render carried(node, basisOf(node, local), row)}
    <div class="parts witness">{@render logic(node.args[0], depth + 1, local, row)}</div>
  {:else}
    <span class="op">{OP[node.op] || node.op}</span>
    <ul class="parts">
      {#each node.op === "iff" ? node.args : flat(node, node.op) as part}
        <li>{@render logic(part, depth + 1, local || node.op !== "and", row)}</li>
      {/each}
    </ul>
  {/if}
{/snippet}

<!-- The readable cell of a row: today's rendering of the Lean, unless a structured rendering of
     the row is given (`readable`). -->
{#snippet readableOf(g)}
  {#if readable}{@render readable(g, st, ioOf(g))}
  {:else if g.conclusion}
    {#if binders.length}<span class="role">then</span>{/if}
    <div class="body">{#if shape}{@render logic(shape, 0, false, g.key)}{:else}{@render lean(st.conclusion, "c", g.key)}{/if}</div>
  {:else if g.head != null}
    {#each g.heads || [g.head] as h (h)}
      {@const b = binders[h]}
      <div class="line">
        <span class="role">{roleOf(b)}</span>
        {@render name(h, g.key)}<span class="colon"> : </span>
        <span class="ty" class:hl={ext?.type === h}>{@render lean(b.type, "b:" + h, g.key)}</span>
      </div>
      {@render carried(b, howOf(b), g.key)}
    {/each}
    {#each g.members as m}
      <div class="line sub">{@render condition(m, "b:" + m, g.key)}</div>
      <div class="subc">{@render carried(binders[m], howOf(binders[m]), g.key)}{@render inside(binders[m], g.key)}</div>
    {/each}
  {:else}
    {@const m = g.members[0]}
    <div class="line">{@render condition(m, "b:" + m, g.key)}</div>{@render carried(binders[m], howOf(binders[m]), g.key)}{@render inside(binders[m], g.key)}
  {/if}
{/snippet}

<!-- The exact Lean of a row. -->
{#snippet exactRow(g)}
  <div class="xfrag" data-exact-row={g.key}>
    {#if g.conclusion}
      <code class="xl">{@render xlean(exactOf(st.conclusion), "c", g.key)}</code>
    {:else}
      {#each [...(g.heads || [g.head]), ...g.members].filter((i) => i != null) as i (i)}
        {@const b = binders[i]}
        {@const br = BIND[b.binder] || BIND.explicit}
        <code class="xl">{#if b.role === "forall"}∀ {br[0]}{b.name} : {@render xlean(b.type, "b:" + i, g.key)}{br[1]},{:else if b.role === "exists"}∃ {b.name} : {@render xlean(b.type, "b:" + i, g.key)},{:else if b.role === "instance"}[{@render xlean(exactOf(b.type), "b:" + i, g.key)}] →{:else}{@render xlean(exactOf(b.type), "b:" + i, g.key)} →{/if}</code>
      {/each}
    {/if}
  </div>
{/snippet}

<!-- What opens under a row: the held variable's note, the selected sub-term with the definition
     it applies at its arguments, a name's note, and the comparison's inspections. -->
{#snippet under(key)}
  {#if pinned != null && vars[pinned] && pinnedRow === key}
    {@const b = vars[pinned]}
    <div class="inspect" aria-live="polite">
      <p><span class="v">{b.name}</span><span class="colon"> : </span>{@render lean(b.type, null, key)}
        <button class="x" aria-label="Release" onclick={() => (pinned = null)}>×</button></p>
      <p class="small faint">{b.inner && b.scope ? standsOf(b) : b.inner && b.role === "exists" ? "Chosen by the statement (there is), for the part it belongs to" : b.inner ? "Any value (for every), in the part it belongs to" : b.role === "exists" ? "Chosen by the statement (there is)" : b.role === "forall" ? "Any value (for all)" : ROLE[b.role]}{#if b.binder === "implicit" || b.binder === "strict-implicit"}; written implicitly{/if}</p>
      {#each groupOf(pinned)?.members || [] as m}
        <p class="small">{@render condition(m, null, key)}</p>
      {/each}
    </div>
  {/if}
  {#if readSel && readSel.row === key && (readText || readExpansion)}
    <div class="inspect term" aria-live="polite">
      <p><span class="small faint">Sub-expression</span><button class="x" aria-label="Release" onclick={() => selectId(null)}>×</button></p>
      {#if readText}<p><code>{readText}</code></p>{/if}
      <p class="small faint">Activate it again to select the expression around it.</p>
      {#if readExpansion}<Expansion x={readExpansion.x} occ={readExpansion.text} onref={refAt(key)} {refs} />{/if}
    </div>
  {/if}
  {#if termText && termSel.row === key}
    <div class="inspect term" aria-live="polite">
      <p><span class="small faint">Sub-expression</span><button class="x" aria-label="Release" onclick={() => (termSel = null)}>×</button></p>
      <p><code>{termText}</code></p>
      <p class="small faint">Activate it again to select the expression around it.</p>
      {#if termExpansion}<Expansion x={termExpansion.x} occ={termExpansion.text} onref={refAt(key)} {refs} />{/if}
    </div>
  {/if}
  {#if alone && alone.row === key}
    <div class="inspect term" aria-live="polite">
      <Expansion x={alone.x} onref={refAt(key)} {refs} onclose={() => (alone = null)} />
    </div>
  {/if}
  {#if noted && noted.row === key && gloss(noted.name)}
    <div class="inspect note" aria-live="polite">
      <p><code>{noted.name}</code><button class="x" aria-label="Close" onclick={() => (noted = null)}>×</button></p>
      <p class="small">{gloss(noted.name)}</p>
      <p class="small faint">A plain-English note on this name; the Lean definition is what the statement uses.</p>
    </div>
  {/if}
  {@render after?.(key, spec)}
{/snippet}

{#snippet cells(g)}
  {#if paper}<div class="pcell" data-paper-row={g.key}>{@render paper(g.key, spec)}</div>{/if}
  <div class="lcell">
    <div class="rowbody" class:withexact={besideExact}>
      <div class="readable" data-slot="readable">{@render readableOf(g)}</div>
      {#if besideExact}{@render exactRow(g)}{/if}
    </div>
    {@render under(g.key)}
  </div>
{/snippet}

<div class="stmt" class:compact class:paired={!!paper} bind:clientWidth={width}>
  {#if !compact && spec}
    <p class="name"><code>{spec}</code></p>
  {/if}
  {#if groups.length}
    <ol class="ribbon" aria-label="Quantifiers and hypotheses, in order">
      {#each groups as g (g.key)}
        <li class={"b " + binders[g.head ?? g.members[0]].role} class:crow={!!paper} data-row={g.key}>{@render cells(g)}</li>
      {/each}
    </ol>
  {/if}
  {#if finalRow}
    <div class="concl" class:crow={!!paper} data-row="c">{@render cells(finalRow)}</div>
  {/if}
  {#if !compact && vars.some((b) => b?.role === "exists" && b.scope !== "assumed")}
    <p class="hint faint">
      The order of the rows is the order of the quantifiers: a “there is” above a “for all”
      chooses one value for every case below it.
    </p>
  {/if}
</div>

<style>
  .stmt { margin-top: 12px; font-size: 17px; container-type: inline-size; }
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
  .concl { margin-top: 6px; padding: 10px 0; border-top: 1px solid var(--border); }
  .concl .readable { display: flex; gap: 8px; align-items: baseline; }
  .concl .body { min-width: 0; flex: 1; }
  .op { font-size: 12px; color: var(--muted); }
  .parts { margin: 2px 0 0; padding-left: 18px; }
  .parts li { margin: 2px 0; }
  .witness { padding-left: 18px; border-left: 2px solid color-mix(in srgb, var(--st-refuted) 50%, transparent); margin: 2px 0 2px 4px; }
  .compact .concl { margin-top: 0; }
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
  button.origin { border: 0; background: none; padding: 0; font: inherit; font-size: 12px; color: var(--faint); cursor: pointer; text-align: left; text-decoration: underline dotted; text-underline-offset: 3px; }
  button.origin:hover, button.origin:focus-visible { color: var(--accent); }
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
  .readable { min-width: 0; }
  /* A row's exact Lean, beside its readable cell. */
  .rowbody.withexact { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 16px; align-items: start; }
  .xfrag { min-width: 0; padding-left: 12px; border-left: 1px dashed var(--border); }
  .xl { display: block; font: 14px/1.6 var(--mono); color: var(--muted); white-space: pre-wrap; overflow-wrap: anywhere; }
  .xfrag :global(.lean) { font-family: var(--mono); font-size: 14px; line-height: 1.6; }
  /* Paired rows: each row's paper cell beside its Lean cell, stacked paper first when narrow. */
  .crow { display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; padding: 8px 0; border-top: 1px solid var(--border); }
  .pcell { min-width: 0; font-size: 15px; }
  .lcell { min-width: 0; }
  @container (min-width: 760px) {
    .crow { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); gap: 20px; }
  }
</style>
