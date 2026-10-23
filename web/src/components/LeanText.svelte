<script>
  // Pretty-printed Lean with the constants it names made navigable. An occurrence of one of the
  // statement's variables (`var`, its binder's index) is marked, highlighted while `active` is
  // that variable, and reported to `onvar` on hover (`hover`, or null on leaving) and on click
  // (`pin`).
  // A constant with a plain-English note (`gloss`) is selectable: `ongloss` receives it, or,
  // without one, the note is the name's tooltip.
  // A sub-term (`pp.terms`, ranges of segments) is selected by clicking plain text: the smallest
  // sub-term around it, then the next larger on each click; `term` is the selected one's index,
  // reported to `onterm` (null to release). `selId` selects a sub-term by its identity in the
  // proposition (`id`), as another view of the same statement selected it. `mark` lists the
  // positions of applications to mark (a warning's occurrences): a sub-term at one of them, or
  // reached from it through function positions only (how an operator's notation is tagged).
  let { pp, onref = null, refs = null, active = null, onvar = null, ongloss = null, term = null,
        onterm = null, selId = null, mark = null } = $props();
  import { getContext } from "svelte";
  const refHref = getContext("declarationHref");
  const meaningful = (s) => /[\p{L}\p{N}∀∃∈≤≥=+×→↔∧∨¬]/u.test(s.t);
  function follow(e, name) { if (!e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) { e.preventDefault(); onref(name); } }
  import { gloss } from "../lib/gloss.js";

  // Names the probe could not tag are found by matching the known names in the text.
  function parts(pp) {
    const out = [];
    (pp?.segments || [{ t: pp?.text || "" }]).forEach((s, i) => {
      if (s.ref || s.var != null || !refs?.length) { out.push({ ...s, i }); return; }
      let rest = s.t;
      while (rest) {
        let best = null;
        for (const r of refs) {
          const i = rest.indexOf(r);
          if (i >= 0 && (best === null || i < best.i || (i === best.i && r.length > best.r.length))) best = { i, r };
        }
        if (!best) { out.push({ t: rest, i }); break; }
        if (best.i) out.push({ t: rest.slice(0, best.i), i });
        out.push({ t: best.r, ref: best.r, i });
        rest = rest.slice(best.i + best.r.length);
      }
    });
    return out;
  }
  const terms = $derived(pp?.terms || []);
  const cur = $derived(term ?? (selId != null ? terms.findIndex((t) => t.id === selId) : -1));
  const sel = $derived(cur != null && cur >= 0 ? terms[cur] : null);
  // A selection by identity may also name one occurrence of a variable (its segment's `at`).
  const lit = (i) => (!!sel && sel.from <= i && i < sel.to) || (selId != null && pp?.segments?.[i]?.at === selId);
  const at = (id, a) => id === a || (id.startsWith(a + "/") && /^(\/0)+$/.test(id.slice(a.length)));
  const marked = $derived.by(() => {
    if (!mark?.length) return [];
    // The outermost sub-term of each position.
    const out = [];
    for (const a of mark) {
      const t = terms.filter((t) => at(t.id, a)).sort((x, y) => x.id.length - y.id.length)[0];
      if (t) out.push(t);
    }
    return out;
  });
  const mk = (i) => marked.some((t) => t.from <= i && i < t.to);
  function pick(i) {
    const around = terms.map((t, k) => ({ ...t, k })).filter((t) => t.from <= i && i < t.to)
      .sort((a, b) => (a.to - a.from) - (b.to - b.from));
    if (!around.length) return;
    const at = around.findIndex((t) => t.k === cur);
    onterm(at < 0 ? around[0].k : around[at + 1]?.k ?? null);
  }
  const isProject = (r) => refs?.includes(r);
</script>

<code class="lean">{#each parts(pp) as s}{#if s.ref && onref && isProject(s.ref)}{#if refHref}<a class="r" class:in={lit(s.i)} class:mk={mk(s.i)} href={refHref(s.ref)} onclick={(e) => follow(e, s.ref)}>{s.t}</a>{:else}<button class="r" class:in={lit(s.i)} class:mk={mk(s.i)} onclick={() => onref(s.ref)}>{s.t}</button>{/if}{:else if s.ref && gloss(s.ref) && ongloss}<button class="g" class:in={lit(s.i)} class:mk={mk(s.i)} title={s.ref} onclick={() => ongloss(s.ref)}>{s.t}</button>{:else if s.ref && onterm && terms.length && meaningful(s)}<span class="c p" class:in={lit(s.i)} class:mk={mk(s.i)} title={gloss(s.ref) ? s.ref + ": " + gloss(s.ref) : s.ref} role="button" tabindex="0" aria-label={"Inspect expression " + s.t.trim()} onclick={() => pick(s.i)} onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(s.i); } }}>{s.t}</span>{:else if s.ref}<span class="c" class:in={lit(s.i)} class:mk={mk(s.i)} title={gloss(s.ref) ? s.ref + ": " + gloss(s.ref) : s.ref}>{s.t}</span>{:else if s.var != null && onvar}<span class="var" class:hl={active === s.var} class:in={lit(s.i)} class:mk={mk(s.i)} role="button" tabindex="0" data-var={s.var} onmouseenter={() => onvar(s.var, "hover")} onmouseleave={() => onvar(null, "hover")} onfocus={() => onvar(s.var, "hover")} onblur={() => onvar(null, "hover")} onclick={() => onvar(s.var, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvar(s.var, "pin"))}>{s.t}</span>{:else if onterm && terms.length && meaningful(s)}<span class="p" class:in={lit(s.i)} class:mk={mk(s.i)} role="button" tabindex="0" aria-label={"Inspect expression " + s.t.trim()} onclick={() => pick(s.i)} onkeydown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(s.i); } }}>{s.t}</span>{:else if mk(s.i)}<mark class="mk">{s.t}</mark>{:else}{s.t}{/if}{/each}</code>

<style>
  .lean { user-select: text; white-space: pre-wrap; word-break: break-word; }
  .r { border: 0; padding: 0; background: none; font: inherit; min-height: 0; color: var(--accent); cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; text-align: left; overflow-wrap: anywhere; }
  .c { color: inherit; }
  .p { cursor: pointer; }
  .in { background: color-mix(in srgb, var(--st-open) 22%, transparent); }
  .mk { background: color-mix(in srgb, var(--tier-warning) 20%, transparent); color: inherit; border-bottom: 2px solid var(--tier-warning); }
  .g { border: 0; padding: 0; background: none; font: inherit; color: inherit; cursor: help; text-decoration: underline dotted var(--faint); text-underline-offset: 3px; }
  .var { cursor: pointer; border-radius: 3px; }
  .var.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
</style>
