// Symbol links (docs/SYMBOL_LINKS.md) drawn in typeset mathematics. A symbol is wrapped in a
// colour of its own, which needs no trust from KaTeX; after rendering, the elements of that
// colour are marked (`data-sym`), given back the text's colour, and made inspectable.

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// A symbol is marked only as a whole token: `a` is not the a of `\mathbb`, nor `\nu` the start
// of `\nuexample`. The engine counts occurrences by the same pattern (`symbols.token`).
const token = (tex) => (/^[A-Za-z]/.test(tex) ? "(?<![A-Za-z\\\\])" : "") + escape(tex) +
  (/[A-Za-z]$/.test(tex) ? "(?![A-Za-z])" : "");
const color = (id) => "#01fe" + id.toString(16).padStart(2, "0");

// Whether a link takes the k-th occurrence of its symbol: every one, or those it numbers (from
// 1, in reading order), which are one object of the paper.
const takes = (s, k) => !Array.isArray(s.occurrence) || s.occurrence.includes(k);

// One piece of mathematics with every linked symbol wrapped, longest symbol first, so that a
// mark never lands inside another. `seen` counts each symbol's occurrences in the pieces before
// this one, so that a link naming occurrences marks only those; an occurrence no link takes is
// left as it is.
export function markMath(src, symbols, seen = new Map()) {
  if (!symbols.length) return src;
  const texs = [...new Set(symbols.map((x) => x.tex))];
  const nth = new Map();
  for (const t of texs) {
    const at = new Map();
    let k = seen.get(t) || 0;
    for (const m of src.matchAll(new RegExp(token(t), "g"))) at.set(m.index, ++k);
    seen.set(t, k);
    nth.set(t, at);
  }
  const all = new RegExp(texs.sort((p, q) => q.length - p.length).map(token).join("|"), "g");
  return src.replace(all, (t, offset) => {
    const k = nth.get(t)?.get(offset);
    const s = k && symbols.find((x) => x.tex === t && takes(x, k));
    return s ? `\\textcolor{${color(s.id)}}{${t}}` : t;
  });
}

// The pieces of mathematics of a typeset passage (`claim.excerpt`), in the order lib/excerpt.js
// typesets them.
export function excerptMath(excerpt) {
  const out = [];
  const inline = (nodes) => {
    for (const n of nodes || []) {
      if (typeof n?.text === "string") continue;
      if (typeof n?.math === "string") out.push(n.math);
      else if (Array.isArray(n?.children)) inline(n.children);
    }
  };
  const blocks = (bs) => {
    for (const b of bs || []) {
      if (Array.isArray(b?.p)) inline(b.p);
      else if (typeof b?.math === "string") out.push(b.math);
      else if (Array.isArray(b?.items)) for (const it of b.items) blocks(it?.blocks);
    }
  };
  blocks(excerpt?.blocks);
  return out;
}

// How many times `tex` occurs in a typeset passage: its occurrences are numbered from 1 in this
// order.
export function occurrenceCount(excerpt, tex) {
  const re = new RegExp(token(tex), "g");
  return excerptMath(excerpt).reduce((n, m) => n + [...m.matchAll(re)].length, 0);
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
