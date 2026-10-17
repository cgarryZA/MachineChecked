<script>
  // Pretty-printed Lean with the constants it names made navigable. An occurrence of one of the
  // statement's variables (`var`, its binder's index) is marked, highlighted while `active` is
  // that variable, and reported to `onvar` on hover (`hover`, or null on leaving) and on click
  // (`pin`).
  let { pp, onref = null, refs = null, active = null, onvar = null } = $props();

  // Names the probe could not tag are found by matching the known names in the text.
  function parts(pp) {
    const out = [];
    for (const s of pp?.segments || [{ t: pp?.text || "" }]) {
      if (s.ref || s.var != null || !refs?.length) { out.push(s); continue; }
      let rest = s.t;
      while (rest) {
        let best = null;
        for (const r of refs) {
          const i = rest.indexOf(r);
          if (i >= 0 && (best === null || i < best.i || (i === best.i && r.length > best.r.length))) best = { i, r };
        }
        if (!best) { out.push({ t: rest }); break; }
        if (best.i) out.push({ t: rest.slice(0, best.i) });
        out.push({ t: best.r, ref: best.r });
        rest = rest.slice(best.i + best.r.length);
      }
    }
    return out;
  }
  const isProject = (r) => refs?.includes(r);
</script>

<code class="lean">{#each parts(pp) as s}{#if s.ref && onref && isProject(s.ref)}<button class="r" onclick={() => onref(s.ref)}>{s.t}</button>{:else if s.ref}<span class="c" title={s.ref}>{s.t}</span>{:else if s.var != null && onvar}<span class="var" class:hl={active === s.var} role="button" tabindex="0" data-var={s.var} onmouseenter={() => onvar(s.var, "hover")} onmouseleave={() => onvar(null, "hover")} onfocus={() => onvar(s.var, "hover")} onblur={() => onvar(null, "hover")} onclick={() => onvar(s.var, "pin")} onkeydown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onvar(s.var, "pin"))}>{s.t}</span>{:else}{s.t}{/if}{/each}</code>

<style>
  .lean { white-space: pre-wrap; word-break: break-word; }
  .r { border: 0; padding: 0; background: none; font: inherit; color: var(--accent); cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; text-align: left; overflow-wrap: anywhere; }
  .c { color: inherit; }
  .var { cursor: pointer; border-radius: 3px; }
  .var.hl { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); }
</style>
