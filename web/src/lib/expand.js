// Definitions expanded at their applications (#97): a printed expression's `expansions`, each
// at the identity (`at`) of the application it expands.

// The selected sub-term `k` of `pp` as an application to expand: the sub-term itself, or the
// smallest application around it that has an expansion; with the application's text.
export function expansionFor(pp, k) {
  const xs = pp?.expansions, ts = pp?.terms || [];
  if (!xs?.length || k == null || !ts[k]) return null;
  const t = ts[k];
  const around = ts.filter((u) => u.from <= t.from && t.to <= u.to)
    .sort((a, b) => (a.to - a.from) - (b.to - b.from));
  for (const u of around) {
    const x = xs.find((x) => x.at === u.id);
    if (x) return { x, text: textOf(pp, u) };
  }
  return null;
}

// The text of a sub-term of a printed expression, without the parentheses that enclose an
// argument (`(Shape.AllBelow 7)` is the application `Shape.AllBelow 7`).
export const textOf = (pp, t) => bare(pp.segments.slice(t.from, t.to).map((s) => s.t).join(""));

function bare(s) {
  if (!(s.startsWith("(") && s.endsWith(")"))) return s;
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "(") depth++;
    else if (s[i] === ")" && --depth === 0 && i < s.length - 1) return s;
  }
  return s.slice(1, -1);
}

// Each expansion of `pp` with the index of the sub-term it expands (-1 when the printed
// expression gives that application no sub-term of its own) and a short label.
export function expansionsOf(pp) {
  const ts = pp?.terms || [];
  return (pp?.expansions || []).map((x) => {
    const k = ts.findIndex((t) => t.id === x.at);
    const text = k >= 0 ? textOf(pp, ts[k]) : x.name;
    return { x, k, text, label: text.length > 48 ? text.slice(0, 47) + "…" : text };
  });
}
