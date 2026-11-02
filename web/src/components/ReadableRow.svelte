<script>
  import MathNode from "./MathNode.svelte";
  import { loadExpansion } from "../lib/data.js";
  import { readableOf, printedById, exactIds, exactKey, hasRep, sepOf } from "../lib/math.js";

  // One row of a statement read as mathematics (#70): the rows of the engine's readable statement
  // (`statement.readable`, `readable.py`) that the comparison's row `g` holds, each with its role
  // and where what it says comes from, and each fragment the sub-term of the exact Lean it
  // renders (its identity): choosing a fragment selects that sub-term in the exact Lean, and the
  // one selected there is highlighted here. Only what Lean elaborated is drawn: the words are the
  // reader's, and nothing a person wrote is part of it. `io` is what the statement's view shares
  // with the row (`Statement.svelte`, `ioOf`): the highlighted variable, the selection, the
  // marks, a linked symbol's highlight and the handlers of what is opened from the row.
  let { g, st, io = {} } = $props();

  const rows = $derived(readableOf(st, g) || []);
  const pps = $derived(printedById(st));
  const ids = $derived(exactIds(st));
  const refs = $derived([...(st.closure || []), ...(st.direct || [])]);
  const opening = $derived((st.binders || []).length);
  const members = $derived(new Set(g.head != null ? g.members || [] : []));
  // A fragment can be chosen when the exact statement shows its sub-term.
  const keyOf = (id) => { const k = exactKey(ids, id); return k != null && ids.has(k) ? k : null; };
  const ctx = $derived({ key: keyOf, sel: io.sel ?? null, mark: io.mark ?? null, onselect: io.onselect ?? null,
    onref: io.onref ?? null, refs, ongloss: io.ongloss ?? null, active: io.active ?? null, onvar: io.onvar ?? null });
  const mathAt = (id) => pps.get(id)?.math ?? null;
  const textAt = (id) => pps.get(id)?.text ?? "";
  const short = (n) => String(n || "").split(".").pop();

  const LEAD = { forall: "for every", exists: "there is" };
  const ROLE = { input: "given", output: "established by the statement", assumption: "inside an assumption" };
  // Where objects stand: given, produced by the statement, inside an assumption, or in a part of
  // the conclusion that is denied, one alternative or one side of an equivalence.
  const SCOPE = { denied: "inside a negation", alternative: "in one alternative", equivalent: "in one side of an equivalence" };
  // The names of the statement's objects, by number.
  const names = $derived.by(() => {
    const out = new Map();
    const walk = (rs) => (rs || []).forEach((r) => {
      if (r.k === "objects") r.objects.forEach((o) => out.set(o.var, o.name));
      (r.parts || []).forEach(walk);
      walk(r.rows);
    });
    walk(st.readable?.rows);
    return out;
  });
  function standing(r, rs, i, top) {
    if (SCOPE[r.scope]) return SCOPE[r.scope];
    // Inside an assumption's own rows, that it is inside goes without saying.
    if (r.quantifier !== "exists") return r.role === "output" ? "in what is established" : !top && r.role === "assumption" ? "" : ROLE[r.role] || r.role;
    if (r.role === "assumption") return "assumed to exist";
    // A choice made before objects that follow it is one choice for all of them: in the
    // statement's own rows when the row opens the statement.
    const all = top ? st.readable?.rows || [] : rs;
    const at = top ? all.findIndex((x) => x.k === "objects" && x.objects.some((o) => o.var === r.objects[0].var)) : i;
    const later = all.slice(at + 1).some((x) => x.k === "objects" && x.quantifier === "forall");
    const after = (r.after || []).map((v) => names.get(v)).filter(Boolean);
    return "produced by the statement" + (after.length && after.length <= 3 ? ", depending on " + after.join(", ")
      : after.length ? ", depending on the objects before it" : later ? ", one for all the objects below" : "");
  }
  // What a claim's or a condition's line opens with: "such that" after the "there is" it belongs
  // to; for a claim, "then" after the statement's objects and assumptions; for a condition of the
  // statement, "assume".
  const suchThat = (rs, i) => rs[i - 1]?.k === "objects" && rs[i - 1].quantifier === "exists";
  function leadOf(r, rs, i, top) {
    const prev = rs[i - 1];
    if (prev?.k === "objects" && prev.quantifier === "exists") return "such that";
    if (r.k === "condition") return top ? "assume" : "";
    if (prev?.k === "objects") return "";
    if (prev) return "then";
    return top && opening ? "then" : "";
  }
  const OP = { and: "all of the following", or: "at least one of the following", iff: "the following are equivalent" };

  // How an object's properties stand (the words `Statement.svelte` uses): given with a supplied
  // object, produced with a witness, inside an assumption, local to the clause that contains it,
  // or what an assumption states; and where each property comes from (#70's origins).
  const BASIS = {
    given: "Included in the type of the given object.",
    states: "What this assumption states, field by field.",
    produced: "Producing this object establishes these properties of its type.",
    local: "Part of this object's type, within the clause that contains it.",
    inside: "Part of this assumption's object.",
  };
  const howOf = (r) => r.scope === "given" || r.scope === "produced" ? r.scope
    : r.scope === "assumed" && r.within?.[0] === "assume" ? "inside" : "local";
  const ORIGIN = { type: "included in its type", established: "established here", assumed: "assumed here", proved: "proved by" };
  // More fields than this are folded under their summary.
  const FOLD = 8;

  // Whether rows introduce objects: an assumption that quantifies shows its own rows.
  const quantifies = (rs) => (rs || []).some((r) => r.k === "objects" || (r.parts || []).some(quantifies) || quantifies(r.rows));

  // The definitions applied in a row, at their actual arguments: each expansion is found by its
  // application in the row's printed expression and read with the row (the site stores each
  // apart), so that what a definition says is shown without opening it.
  const expansionOf = (r, d) => (pps.get(r.at)?.expansions || []).find((x) => x.at === d.at) || null;
  let loaded = $state({});
  $effect(() => {
    const want = new Set();
    const walk = (rs) => (rs || []).forEach((r) => {
      for (const d of r.definitions || []) {
        const x = expansionOf(r, d);
        if (x?.key && !x.defined_by && !(x.key in loaded)) want.add(x.key);
      }
      (r.parts || []).forEach(walk);
      walk(r.rows);
    });
    walk(rows);
    if (!want.size) return;
    loaded = { ...loaded, ...Object.fromEntries([...want].map((k) => [k, null])) };
    for (const k of want) {
      loadExpansion(k).then((x) => (loaded = { ...loaded, [k]: x }), () => (loaded = { ...loaded, [k]: { error: true } }));
    }
  });
  const full = (x) => (x?.key && !x.defined_by ? loaded[x.key] : x);
  const anyRep = $derived(g.conclusion && [...pps.values()].some((pp) => hasRep(pp.math)));
</script>

{#snippet math(id, root = true)}{#if mathAt(id)}<MathNode m={mathAt(id)} {ctx} {root} />{:else}<code class="xl">{textAt(id)}</code>{/if}{/snippet}

{#snippet expr(id)}<span class="ex">{@render math(id)}</span>{@render io.chips?.(id, g.key)}{/snippet}

{#snippet pmath(pp)}{#if pp?.math}<MathNode m={pp.math} {ctx} root />{:else}<code class="xl">{pp?.text}</code>{/if}{/snippet}

{#snippet defs(r)}
  {#each r.definitions || [] as d (d.at)}
    {@const x = full(expansionOf(r, d))}
    <div class="line def" data-definition={d.name} data-origin="defined">
      <span class="role">defined by</span>
      <span class="pbody">{#if io.onref && refs.includes(d.name)}<button class="ref" title={d.name} onclick={() => io.onref(d.name)}>{short(d.name)}</button>{:else}<code>{short(d.name)}</code>{/if}{#if x?.defined_by === "body" && x.body}{": "}{#if x.params?.length}{#each x.params as p, j (p.id ?? j)}{#if j}{", "}{/if}<i>{p.name}</i>{/each}{" ↦ "}{/if}{@render pmath(x.body)}{:else if x?.defined_by === "equations"}{#each x.equations || [] as e, j (e.name ?? j)}{j ? "; " : ": "}{@render pmath(e.equation)}{:else}<span class="small faint">: by equations, none of which applies to these arguments as written</span>{/each}{:else if x?.error}<span class="small faint">: its definition could not be read</span>{:else if x}{" "}<span class="small faint">({x.defined_by || "not unfolded"})</span>{/if}</span>
    </div>
  {/each}
{/snippet}

{#snippet carried(r, how)}
  {@const ps = r.properties || []}
  {@const data = r.data || []}
  {#if ps.length || data.length || r.properties_error}
    <details class={"carried " + how} data-carried={how} open={ps.length + data.length <= FOLD}>
      <summary class="small faint basis">{BASIS[how]}{#if ps.length + data.length > FOLD}{" "}({ps.length} propert{ps.length === 1 ? "y" : "ies"}, {data.length} data field{data.length === 1 ? "" : "s"}){/if}</summary>
      {#each ps as p, j (p.object + ":" + (p.field ?? p.ref ?? j))}
        <div class="line prop" data-field={p.field} data-origin={p.origin}>
          <span class="role">{ORIGIN[p.origin] || p.origin}</span>
          <span class="pbody">{#if p.origin === "proved"}<code>{p.ref}</code>{#if p.statement}: <code class="xl">{p.statement}</code>{/if}{:else if p.at}{@render expr(p.at)}{:else}<code class="xl">{p.statement}</code>{/if}
            {#if p.field}{" "}{#if io.onproperty}<button class="origin" data-property={p.at} title={(p.projection || p.field) + (p.module ? " · " + p.module : "")} aria-label={"Inspect the property " + p.field} onclick={() => io.onproperty({ type: { id: p.at }, field: p.field }, how)}>field <code>{p.field}</code> of <code>{short(p.structure)}</code>{#if p.inherited}, from <code>{short(p.declared_in)}</code>{/if}</button>{:else}<span class="origin" title={(p.projection || p.field) + (p.module ? " · " + p.module : "")}>field <code>{p.field}</code> of <code>{short(p.structure)}</code>{#if p.inherited}, from <code>{short(p.declared_in)}</code>{/if}</span>{/if}{/if}</span>
        </div>
      {/each}
      {#if data.length}
        <div class="line data"><span class="role">data</span> <span class="fields">{#each data as d, j (d.object + ":" + d.field)}{#if j}{", "}{/if}<code>{d.term}</code>{" : "}{#if d.at}{@render math(d.at)}{/if}{/each}</span></div>
      {/if}
      {#if r.properties_omitted}<p class="small faint">{r.properties_omitted} further field{r.properties_omitted === 1 ? " of this type is" : "s of this type are"} not listed.</p>{/if}
      {#if r.properties_error}<p class="small bad">The fields of this type could not be read: {r.properties_error}</p>{/if}
    </details>
  {/if}
{/snippet}

{#snippet name(o)}<span class="v" class:hl={io.active === o.var} data-var={o.var} role="button" tabindex="0" onmouseenter={() => io.onvar?.(o.var, "hover")} onmouseleave={() => io.onvar?.(null, "hover")} onfocus={() => io.onvar?.(o.var, "hover")} onblur={() => io.onvar?.(null, "hover")} onclick={() => io.onvar?.(o.var, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), io.onvar?.(o.var, "pin"))}>{o.name}</span>{/snippet}

{#snippet seq(rs, top)}
  {#each rs as r, i}
    {#if r.k === "objects"}
      <div class="line obj" data-role={r.role} data-scope={r.scope} data-quantifier={r.quantifier}>
        <span class="role">{LEAD[r.quantifier]}</span>
        <span class="pbody">{#each r.objects as o, j (o.var)}{#if j}{", "}{/if}{@render name(o)}{/each}<span class="colon">{sepOf(mathAt(r.at))}</span><span class="ty" class:hl={r.objects.some((o) => io.ext?.type === o.var)}>{@render expr(r.at)}</span>
          {#if standing(r, rs, i, top)}<span class="stand small faint">{standing(r, rs, i, top)}</span>{/if}</span>
      </div>
      {@render carried(r, howOf(r))}
      {@render defs(r)}
    {:else if r.k === "structure"}
      {@const member = top && r.var != null && members.has(r.var)}
      <div class="line struct" class:sub={member} data-role={r.role} data-origin={r.origin}>
        <span class="role">given</span> <span class="pbody">{@render expr(r.at)} <span class="stand small faint">supplied structure</span></span>
      </div>
      <div class:subc={member}>{@render carried(r, "given")}</div>
    {:else if r.k === "condition"}
      {@const member = top && r.var != null && members.has(r.var)}
      {@const lead = leadOf(r, rs, i, top)}
      <div class="line cond" class:sub={member} data-role={r.role} data-origin={r.origin}>
        {#if lead}<span class="role">{lead}</span>{/if} <span class="pbody">{@render expr(r.at)}{#if top}{" "}<span class="stand small faint">{r.joint ? "assumed, relating several objects" : "assumed"}</span>{/if}</span>
      </div>
      <div class:subc={member}>
        {#if r.states?.length}{@render carried({ ...r, properties: r.states, data: [] }, "states")}{/if}
        {@render defs(r)}
        {#if quantifies(r.rows)}
          <div class="inner within" data-within={r.id}>
            <p class="small faint">Inside this assumption:</p>
            <div class="body">{@render seq(r.rows, false)}</div>
          </div>
        {/if}
      </div>
    {:else if r.k === "claim"}
      {@const lead = leadOf(r, rs, i, top)}
      <div class="line claim" data-role={r.role} data-origin={r.origin}>
        {#if lead}<span class="role">{lead}</span>{/if} <span class="pbody">{@render expr(r.at)}</span>
      </div>
      {@render defs(r)}
    {:else if r.k === "implies"}
      {#if suchThat(rs, i)}<span class="op">such that</span>{/if}
      <div class="line"><span class="role">if</span> <div class="body">{@render seq(r.parts[0], false)}</div></div>
      <div class="line"><span class="role">then</span> <div class="body">{@render seq(r.parts[1], false)}</div></div>
    {:else if r.k === "not"}
      <span class="op">{suchThat(rs, i) ? "such that " : ""}it is not the case that</span>
      <div class="parts witness">{@render seq(r.parts[0], false)}</div>
    {:else}
      <span class="op">{suchThat(rs, i) ? "such that " : ""}{OP[r.k] || r.k}</span>
      <ul class="parts">{#each r.parts as part, j (j)}<li>{@render seq(part, false)}</li>{/each}</ul>
    {/if}
  {/each}
{/snippet}

<div class="rd" data-readable={g.key}>
  {@render seq(rows, true)}
  {#if anyRep}<p class="small faint legend">F<sup>~</sup> is a representative of the class F: a function equal to it almost everywhere.</p>{/if}
</div>

<style>
  .rd { min-width: 0; font-family: var(--serif); font-size: 18px; line-height: 1.6; }
  .line { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
  .role, .op { font-family: var(--sans, inherit); font-size: 14px; color: var(--muted); min-width: 64px; }
  .op { display: block; }
  .pbody, .body { min-width: 0; }
  .stand { font-family: var(--sans, inherit); }
  .v { font-style: italic; cursor: pointer; border-radius: 3px; }
  .v.hl, .ty.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
  .carried, .def { margin: 0 0 2px 18px; padding-left: 10px; border-left: 2px solid var(--border); }
  .carried > summary { cursor: pointer; }
  .carried.produced { border-left-color: color-mix(in srgb, var(--accent) 45%, transparent); }
  .prop, .def, .data { font-size: 16px; }
  .prop .role, .def .role, .data .role { font-size: 12px; color: var(--faint); min-width: 74px; }
  .origin { border: 0; background: none; padding: 0; font: 12px var(--sans, inherit); color: var(--faint); cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
  span.origin { cursor: default; text-decoration: none; }
  .origin code { font-size: 12px; }
  .ref { border: 0; padding: 0; background: none; font: inherit; min-height: 0; color: var(--accent); cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
  .sub { margin-left: 18px; }
  .subc { margin-left: 18px; }
  .inner { margin: 2px 0 4px 18px; }
  .inner p { margin: 2px 0; }
  .parts { margin: 2px 0 0; padding-left: 18px; }
  .parts > li { margin: 2px 0; }
  .witness { margin-left: 18px; }
  .xl { font-family: var(--mono); font-size: 14px; color: var(--muted); }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  .bad { color: var(--st-refuted); }
  .legend { margin: 6px 0 0; font-family: var(--sans, inherit); }
</style>
