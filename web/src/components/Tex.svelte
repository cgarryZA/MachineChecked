<script>
  import renderMathInElement from "katex/contrib/auto-render";

  // Manuscript source with its inline and display mathematics typeset; macros the page does not
  // know are shown as source. Linked symbols (`symbols`, [{tex, id}]) are marked in the
  // mathematics, highlighted while `active` holds their id, and reported to `onsym` on hover
  // (`hover`, or null on leaving) and on click (`pin`).
  let { text, symbols = [], active = [], onsym = null } = $props();
  let el;

  const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // A symbol is marked only inside mathematics, and only as a whole token: `a` is not the a of
  // `\\mathbb`, nor `\\nu` the start of `\\nuexample`.
  const MATH = /\$\$[\s\S]*?\$\$|\$[\s\S]*?\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\\begin\{equation\*?\}[\s\S]*?\\end\{equation\*?\}/g;
  const token = (tex) => (/^[A-Za-z]/.test(tex) ? "(?<![A-Za-z\\\\])" : "") + escape(tex) +
    (/[A-Za-z]$/.test(tex) ? "(?![A-Za-z])" : "");
  // A symbol is wrapped in a colour of its own, which needs no trust from KaTeX; after rendering,
  // the elements of that colour are marked (`data-sym`) and given back the text's colour.
  const color = (id) => "#01fe" + id.toString(16).padStart(2, "0");
  // One pass over each piece of mathematics, longest symbol first, so that a mark never lands
  // inside another.
  function marked(src) {
    if (!symbols.length) return src;
    const bySrc = new Map(symbols.map((x) => [x.tex, x.id]));
    const all = new RegExp([...bySrc.keys()].sort((p, q) => q.length - p.length).map(token).join("|"), "g");
    return src.replace(MATH, (m) => m.replace(all, (t) => `\\textcolor{${color(bySrc.get(t))}}{${t}}`));
  }

  $effect(() => {
    if (!el) return;
    el.textContent = marked(text
      .replace(/\\label\{[^}]*\}/g, "")
      .replace(/\\(emph|textit|textbf)\{([^}]*)\}/g, "$2")
      .replace(/~/g, " "));
    renderMathInElement(el, {
      delimiters: [
        { left: "\\[", right: "\\]", display: true },
        { left: "\\begin{equation}", right: "\\end{equation}", display: true },
        { left: "$$", right: "$$", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
    for (const s of symbols.slice(0, 256)) {
      const want = `rgb(1, 254, ${s.id})`;
      for (const node of el.querySelectorAll(".katex [style*='color']")) {
        if (node.style.color === want) { node.dataset.sym = s.id; node.style.color = ""; }
      }
    }
    if (!onsym) return;
    for (const node of el.querySelectorAll("[data-sym]")) {
      const id = Number(node.dataset.sym);
      node.setAttribute("tabindex", "0");
      node.setAttribute("role", "button");
      node.addEventListener("mouseenter", () => onsym(id, "hover"));
      node.addEventListener("mouseleave", () => onsym(null, "hover"));
      node.addEventListener("focus", () => onsym(id, "hover"));
      node.addEventListener("blur", () => onsym(null, "hover"));
      node.addEventListener("click", () => onsym(id, "pin"));
    }
  });

  $effect(() => {
    if (!el) return;
    for (const node of el.querySelectorAll("[data-sym]")) node.classList.toggle("hl", active.includes(Number(node.dataset.sym)));
  });
</script>

<div class="tex" bind:this={el}></div>

<style>
  .tex { font-family: var(--serif); font-size: 16px; line-height: 1.6; padding: 10px 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-top: 6px; }
  .tex :global([data-sym]) { cursor: pointer; border-bottom: 1px dotted var(--accent); }
  .tex :global([data-sym].hl) { background: color-mix(in srgb, var(--accent) 22%, transparent); outline: 1px solid color-mix(in srgb, var(--accent) 45%, transparent); border-radius: 3px; }
</style>
