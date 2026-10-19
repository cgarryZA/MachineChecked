import katex from "katex";

// A paper passage the engine parsed from its pinned LaTeX source (`claim.excerpt`, scheme
// tex-excerpt-v1), typeset whole or not at all. Every piece of mathematics is typeset by KaTeX
// in strict mode with errors thrown, under the paper's own definitions in effect at the passage;
// one failure, or any node this renderer does not know, fails the whole passage, and the reader
// shows the PDF instead. Nothing is skipped to obtain a render. The passage is built as DOM
// nodes: its text is never parsed as HTML.

export const SCHEME = "tex-excerpt-v1";

const STYLE = { em: ["em"], it: ["i"], bf: ["b"], sc: ["span", "sc"], tt: ["span", "tt"], rm: ["span", "rm"], sf: ["span", "sf"] };

// The paper's definitions as TeX, read before each piece of mathematics.
export function definitions(macros = {}) {
  return Object.entries(macros).map(([name, d]) => {
    if (!/^\\([A-Za-z@]+|.)$/.test(name) || !Number.isInteger(d.params) || d.params < 0 || d.params > 9) throw new Error(`unusable definition of ${name}`);
    return "\\def" + name + Array.from({ length: d.params }, (_, i) => "#" + (i + 1)).join("") + "{" + d.body + "}";
  }).join("");
}

// The whole passage as a document fragment, or an error. `mark` rewrites each piece of
// mathematics before it is typeset (symbol links).
export function renderExcerpt(excerpt, doc = document, mark = (s) => s) {
  try {
    if (!excerpt || excerpt.scheme !== SCHEME || !excerpt.ready || !Array.isArray(excerpt.blocks) || !excerpt.blocks.length) {
      throw new Error((excerpt?.reasons || [])[0] || "no typeset passage");
    }
    const defs = definitions(excerpt.macros);
    const el = (tag, cls, children = []) => {
      const e = doc.createElement(tag);
      if (cls) e.className = cls;
      for (const c of children) e.append(c);
      return e;
    };
    const math = (src, displayMode) => {
      const box = el(displayMode ? "div" : "span", displayMode ? "display" : null);
      katex.render(defs + mark(src), box, { displayMode, throwOnError: true, strict: "error", trust: false });
      return box;
    };
    const inline = (nodes) => nodes.map((n) => {
      if (typeof n.text === "string") return doc.createTextNode(n.text);
      if (typeof n.math === "string") return math(n.math, false);
      if (n.br) return el("br");
      if (typeof n.ref === "string") return el("span", "ref", [n.ref]);
      if (Array.isArray(n.cite) && n.cite.length) return el("span", "cite", ["[" + n.cite.join(", ") + (n.note ? ", " + n.note : "") + "]"]);
      if (Array.isArray(n.children) && n.style === null) return el("span", null, inline(n.children));
      if (Array.isArray(n.children) && Object.hasOwn(STYLE, n.style)) {
        const [tag, cls] = STYLE[n.style];
        return el(tag, cls || null, inline(n.children));
      }
      throw new Error("an unknown part of the passage");
    });
    const blocks = (bs) => bs.map((b) => {
      if (Array.isArray(b.p)) return el("p", null, inline(b.p));
      if (typeof b.math === "string" && b.display) return math(b.math, true);
      if ((b.list === "itemize" || b.list === "enumerate") && Array.isArray(b.items)) {
        const labelled = b.items.some((it) => it.label != null);
        return el(b.list === "itemize" ? "ul" : "ol", labelled ? "labelled" : null, b.items.map((it) =>
          el("li", null, [...(it.label != null ? [el("span", "lbl", [it.label])] : []), ...blocks(it.blocks || [])])));
      }
      throw new Error("an unknown block of the passage");
    });
    const frag = doc.createDocumentFragment();
    frag.append(...blocks(excerpt.blocks));
    return { ok: true, node: frag };
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  }
}
