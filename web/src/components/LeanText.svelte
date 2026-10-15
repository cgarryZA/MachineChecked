<script>
  // Pretty-printed Lean with the constants it names made navigable.
  let { pp, onref = null, refs = null } = $props();

  // Names the probe could not tag are found by matching the known names in the text.
  function parts(pp) {
    const out = [];
    for (const s of pp?.segments || [{ t: pp?.text || "" }]) {
      if (s.ref || !refs?.length) { out.push(s); continue; }
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

<code class="lean">{#each parts(pp) as s}{#if s.ref && onref && isProject(s.ref)}<button class="r" onclick={() => onref(s.ref)}>{s.t}</button>{:else if s.ref}<span class="c" title={s.ref}>{s.t}</span>{:else}{s.t}{/if}{/each}</code>

<style>
  .lean { white-space: pre-wrap; word-break: break-word; }
  .r { border: 0; padding: 0; background: none; font: inherit; color: var(--accent); cursor: pointer; text-decoration: underline dotted; text-underline-offset: 3px; }
  .c { color: inherit; }
</style>
