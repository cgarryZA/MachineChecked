// Symbol links (docs/SYMBOL_LINKS.md) drawn in typeset mathematics. A symbol is wrapped in a
// colour of its own, which needs no trust from KaTeX; after rendering, the elements of that
// colour are marked (`data-sym`), given back the text's colour, and made inspectable.

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// A symbol is marked only as a whole token: `a` is not the a of `\mathbb`, nor `\nu` the start
// of `\nuexample`.
const token = (tex) => (/^[A-Za-z]/.test(tex) ? "(?<![A-Za-z\\\\])" : "") + escape(tex) +
  (/[A-Za-z]$/.test(tex) ? "(?![A-Za-z])" : "");
const color = (id) => "#01fe" + id.toString(16).padStart(2, "0");

// One piece of mathematics with every linked symbol wrapped, longest symbol first, so that a
// mark never lands inside another.
export function markMath(src, symbols) {
  if (!symbols.length) return src;
  const bySrc = new Map(symbols.map((x) => [x.tex, x.id]));
  const all = new RegExp([...bySrc.keys()].sort((p, q) => q.length - p.length).map(token).join("|"), "g");
  return src.replace(all, (t) => `\\textcolor{${color(bySrc.get(t))}}{${t}}`);
}

// After rendering into `el`: mark the symbols, and report them to `onsym` on hover (`hover`,
// or null on leaving) and on click or Enter (`pin`).
export function bindSymbols(el, symbols, onsym) {
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
    node.setAttribute("aria-label", "Inspect symbol " + (symbols.find((s) => s.id === id)?.tex || node.textContent));
    node.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onsym(id, "pin"); } });
    node.addEventListener("mouseenter", () => onsym(id, "hover"));
    node.addEventListener("mouseleave", () => onsym(null, "hover"));
    node.addEventListener("focus", () => onsym(id, "hover"));
    node.addEventListener("blur", () => onsym(null, "hover"));
    node.addEventListener("click", () => onsym(id, "pin"));
  }
}

export function highlightSymbols(el, active) {
  for (const node of el.querySelectorAll("[data-sym]")) node.classList.toggle("hl", active.includes(Number(node.dataset.sym)));
}
