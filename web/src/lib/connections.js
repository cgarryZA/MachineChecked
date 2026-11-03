// A connection between two objects of Lean results (a workspace's evidence reference
// `connection`, `connections.py`), in the words the engine uses for it (`connections.text`):
// its ends, its relation with its scope, the conditions under which it holds and what supports
// it. A published audit leaves out the Lean text of the ends and the scope when it does not
// publish the Lean; the words then name the ends by declaration and variable number.

function refWords(r) {
  if (r?.decl) return r.decl;
  if (r?.app) return `${r.app.callee} applied in ${r.app.caller}`;
  const f = r?.fact || {};
  return `${f.name || f.head || "a fact"} inside the proof of ${f.decl}`;
}

export function endText(e) {
  e = e || {};
  if (e.decl) {
    if (e.var != null) return `${e.name || "variable " + e.var} of ${e.decl}`;
    if (e.at) return e.target ? `\`${e.target}\` in ${e.decl}` : `the sub-term ${e.at} of ${e.decl}`;
    return e.decl;
  }
  if (e.app) return `${e.param} of ${e.app.callee} applied in ${e.app.caller}`;
  return `${e.local} in the proof of ${e.fact?.decl}`;
}

export function relationText(c) {
  const a = endText(c.from), b = endText(c.to);
  switch (c.relation) {
    case "definitional": return `${a} and ${b} are definitionally equal`;
    case "projection": return `${b} is the field ${c.field || "taken"} of ${a}`;
    case "equal": return `${a} and ${b} are equal`;
    case "equal on a domain": return `${a} and ${b} are equal on ${c.domain || "a domain"}`;
    case "eventually equal": return `${a} and ${b} are eventually equal along ${c.along || "a filter"}`;
    case "equal as classes": return `${a} and ${b} are equal as classes, modulo ${c.modulo || "an equivalence"}`;
    case "restriction": return `${b} is the restriction of ${a} to ${c.domain || "a domain"}`;
    case "coercion": return `${b} is ${a} coerced`;
    case "transformation": return `${b} is a transformation of ${a} preserving ${c.preserves || "a property"}`;
    case "shared witness": return `${a} and ${b} are one witness`;
    default: return `${a} and ${b}: ${c.relation}`;
  }
}

export function connectionText(c) {
  let out = relationText(c || {});
  if (c?.conditions?.length) out += `, when ${c.conditions.join("; ")}`;
  if (c?.unfolds?.length) out += ", unfolding " + c.unfolds.map((u) => u.decl).join(", ");
  if (c?.support?.length) out += ", by " + c.support.map(refWords).join("; ");
  return out;
}
