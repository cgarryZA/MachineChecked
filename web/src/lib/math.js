// A Lean expression read as mathematics (#70). The probe gives each printed expression its
// `math`: the notions Lean elaborated, each node at the identity of the sub-term it renders
// (docs/DATA_MODEL.md). Here a node is laid out as pieces of notation: text, words, a variable,
// a declaration, a superscript or subscript, the exact Lean of a sub-term the probe kept as Lean,
// or a child node with the least precedence it may have without brackets. The words and the
// notation are the reader's; what each piece is comes from Lean.

const TYPES = { nat: "ℕ", int: "ℤ", rat: "ℚ", real: "ℝ", complex: "ℂ", nnreal: "ℝ≥0", ennreal: "[0, ∞]",
  ereal: "[−∞, ∞]", bool: "Bool", prop: "Prop" };
const REL = { eq: "=", ne: "≠", le: "≤", lt: "<", ge: "≥", gt: ">", mem: "∈", subset: "⊆", ssubset: "⊊",
  dvd: "∣", heq: "≍" };
const INFIX = { add: ["+", 6], sub: ["−", 6], mul: ["·", 7], div: ["/", 7], mod: [" mod ", 7], smul: ["•", 7],
  union: ["∪", 6], inter: ["∩", 7], sdiff: ["∖", 6], sup: ["⊔", 6], inf: ["⊓", 7], set_prod: ["×", 7] };
const INTERVAL = { Icc: ["[", "]"], Ico: ["[", ")"], Ioc: ["(", "]"], Ioo: ["(", ")"] };
const MAPS = { isometry_equiv: "≃ₗᵢ", isometry: "→ₗᵢ", continuous_linear_map: "→L", continuous_linear_equiv: "≃L",
  linear_map: "→ₗ", linear_equiv: "≃ₗ" };

// Precedences: a child laid out with a lower precedence than its place needs is bracketed.
const ATOM = 10, APP = 9, POW = 8, MUL = 7, ADD = 6, REL_P = 5, NOT = 4, AND = 3, OR = 2, IMP = 1, BIND = 0;

const n = (node, p) => ({ n: node, p });
const short = (name) => String(name || "").split(".").pop();
const join = (nodes, sep, p) => nodes.flatMap((x, i) => (i ? [sep, n(x, p)] : [n(x, p)]));
const isNat = (t) => t?.k === "type" && t.name === "nat";

// What stands between an object and its type: "∈" for a type read as a set of elements (ℕ, Lᵖ,
// ℝⁿ, a subtype), ":" otherwise (a proposition, a function, a structure).
export function sepOf(ty) {
  return ty && ((ty.k === "type" && ty.name !== "prop" && ty.name !== "bool") || ty.k === "fin" || ty.k === "lp" || ty.k === "euclidean"
    || ty.k === "coe" || ty.k === "set_type") ? " ∈ " : " : ";
}

// The pieces of a binder: its variable and the type it ranges over.
function over(m, word) {
  const ty = m.type;
  return [{ word }, " ", { b: m.binder, t: m.name }, ...(ty ? [sepOf(ty), n(ty, IMP)] : []), ", ", n(m.body, BIND)];
}

// The layout of a node: `{prec, pieces}`.
export function layout(m) {
  if (!m || typeof m !== "object") return { prec: ATOM, pieces: [] };
  const a = m.args || [];
  switch (m.k) {
    case "var": return { prec: ATOM, pieces: [{ v: m.var, t: m.name }] };
    case "bound": return { prec: ATOM, pieces: [{ b: m.binder, t: m.name }] };
    case "local": return { prec: ATOM, pieces: [{ t: m.name, italic: true }] };
    case "num": return { prec: ATOM, pieces: [String(m.value)] };
    case "str": return { prec: ATOM, pieces: ["“" + m.value + "”"] };
    case "true": return { prec: ATOM, pieces: ["true"] };
    case "false": return { prec: ATOM, pieces: ["false"] };
    case "type": return { prec: ATOM, pieces: [TYPES[m.name] || m.name] };
    case "universe": return { prec: ATOM, pieces: [m.level === "0" ? "Type" : "Type " + m.level] };
    case "sort": return { prec: ATOM, pieces: ["Sort " + m.level] };
    case "lean": return { prec: ATOM, pieces: [{ lean: m.cut ? "…" : m.text || "" }] };
    case "and": return { prec: AND, pieces: [n(a[0], AND + 1), " ∧ ", n(a[1], AND)] };
    case "or": return { prec: OR, pieces: [n(a[0], OR + 1), " ∨ ", n(a[1], OR)] };
    case "iff": return { prec: IMP, pieces: [n(a[0], IMP + 1), " ⟺ ", n(a[1], IMP + 1)] };
    case "implies": return { prec: IMP, pieces: [n(a[0], IMP + 1), " ⟹ ", n(a[1], IMP)] };
    case "not": return { prec: NOT, pieces: ["¬", n(m.arg, NOT)] };
    case "forall": return { prec: BIND, pieces: over(m, "for every") };
    case "exists": return { prec: BIND, pieces: over(m, "there is") };
    case "exists_unique": return { prec: BIND, pieces: over(m, "there is exactly one") };
    case "lambda": return { prec: BIND, pieces: [{ b: m.binder, t: m.name }, " ↦ ", n(m.body, BIND)] };
    case "pi": return { prec: BIND, pieces: ["Π ", { b: m.binder, t: m.name }, " : ", n(m.type, ADD), ", ", n(m.body, BIND)] };
    case "subtype": case "set_of":
      return { prec: ATOM, pieces: ["{", { b: m.binder, t: m.name }, ...(m.type ? [" ∈ ", n(m.type, ADD)] : []), " | ",
        n(m.body ?? m.pred, BIND), "}"] };
    case "rel": {
      if (m.op === "ae_eq") return { prec: REL_P, pieces: [n(a[0], ADD), " = ", n(a[1], ADD), " ", { word: "almost everywhere for" }, " ", n(m.measure, APP)] };
      if (m.op === "eventually_eq") return { prec: REL_P, pieces: [n(a[0], ADD), " = ", n(a[1], ADD), " ", { word: "eventually along" }, " ", n(m.filter, APP)] };
      return { prec: REL_P, pieces: [n(a[0], ADD), " " + (REL[m.op] || m.op) + " ", n(a[1], ADD)] };
    }
    case "op": {
      if (INFIX[m.op]) {
        const [sym, p] = INFIX[m.op];
        // Truncated subtraction and floor division are those of ℕ: said where they occur.
        const nat = isNat(m.in) && (m.op === "sub" || m.op === "div");
        return { prec: p, pieces: [n(a[0], p), (sym.startsWith(" ") ? sym : " " + sym + " "), ...(nat ? [{ sub: ["ℕ"] }, " "] : []), n(a[1], p + 1)] };
      }
      switch (m.op) {
        case "pow": return { prec: POW, pieces: [n(a[0], POW + 1), { sup: [n(a[1], BIND)] }] };
        case "neg": return { prec: NOT, pieces: ["−", n(a[0], POW)] };
        case "inv": return { prec: POW, pieces: [n(a[0], POW + 1), { sup: ["−1"] }] };
        case "abs": return { prec: ATOM, pieces: ["|", n(a[0], BIND), "|"] };
        case "norm": return { prec: ATOM, pieces: ["‖", n(a[0], BIND), "‖"] };
        case "inner": return { prec: ATOM, pieces: ["⟨", n(a[0], BIND), ", ", n(a[1], BIND), "⟩"] };
        case "compl": return { prec: POW, pieces: [n(a[0], POW + 1), { sup: ["c"] }] };
        case "succ": return { prec: ADD, pieces: [n(a[0], ADD), " + 1"] };
        case "card": return { prec: ATOM, pieces: ["#", n(a[0], APP)] };
        case "max": case "min": return { prec: APP, pieces: [m.op + "(", ...join(a, ", ", BIND), ")"] };
      }
      return { prec: APP, pieces: [m.op + "(", ...join(a, ", ", BIND), ")"] };
    }
    case "apply": {
      if (!a.length) return { prec: ATOM, pieces: [{ ref: m.name, t: short(m.name) }] };
      return { prec: APP, pieces: [{ ref: m.name, t: short(m.name) }, "(", ...join(a, ", ", BIND), ")"] };
    }
    case "app": return { prec: APP, pieces: [n(m.fn, APP), "(", ...join(a, ", ", BIND), ")"] };
    case "map_apply": return { prec: APP, pieces: [n(m.map, APP), "(", ...join(a, ", ", BIND), ")"] };
    case "field": return { prec: APP, pieces: [n(m.of, APP), "." + m.field] };
    case "coe":
      if (m.kind === "coe") return { prec: ATOM, pieces: ["(", n(m.of, BIND), ...(m.to ? [" ", { word: "in" }, " ", n(m.to, ADD)] : []), ")"] };
      return { prec: ATOM, pieces: [n(m.of, ATOM)] };
    case "rep": return { prec: ATOM, pieces: [{ rep: true }, n(m.of, ATOM), { sup: ["~"] }] };
    case "fun_type": return { prec: IMP, pieces: [n(a[0], IMP + 1), " → ", n(a[1], IMP)] };
    case "prod_type": return { prec: MUL, pieces: [n(m.left, MUL + 1), " × ", n(m.right, MUL + 1)] };
    case "fin": case "range": {
      // `Fin 3` is {0, 1, 2}: a numeral bound is counted out.
      const k = m.n?.k === "num" && /^\d+$/.test(String(m.n.value)) ? Number(m.n.value) : null;
      if (k === 0) return { prec: ATOM, pieces: ["∅"] };
      if (k != null && k <= 4) return { prec: ATOM, pieces: ["{" + [...Array(k).keys()].join(", ") + "}"] };
      if (k != null) return { prec: ATOM, pieces: ["{0, …, " + (k - 1) + "}"] };
      return { prec: ATOM, pieces: ["{0, …, ", n(m.n, ADD), " − 1}"] };
    }
    case "set_type": return { prec: APP, pieces: ["𝒫(", n(m.of, BIND), ")"] };
    case "finset_type": return { prec: APP, pieces: [{ word: "finite subsets of" }, " ", n(m.of, APP)] };
    case "interval": {
      if (INTERVAL[m.kind]) return { prec: ATOM, pieces: [INTERVAL[m.kind][0], n(m.lo, BIND), ", ", n(m.hi, BIND), INTERVAL[m.kind][1]] };
      if (m.kind === "Ici" || m.kind === "Ioi") return { prec: ATOM, pieces: [m.kind === "Ici" ? "[" : "(", n(m.lo, BIND), ", ∞)"] };
      return { prec: ATOM, pieces: ["(−∞, ", n(m.hi, BIND), m.kind === "Iic" ? "]" : ")"] };
    }
    case "univ": return { prec: ATOM, pieces: m.in ? [n(m.in, ATOM)] : ["univ"] };
    case "empty": return { prec: ATOM, pieces: ["∅"] };
    case "singleton": return { prec: ATOM, pieces: ["{", n(m.of, BIND), "}"] };
    case "top": return { prec: ATOM, pieces: [m.in?.k === "type" && (m.in.name === "ennreal" || m.in.name === "ereal") ? "∞" : "⊤"] };
    case "bot": return { prec: ATOM, pieces: [m.in?.k === "type" && m.in.name === "ereal" ? "−∞" : "⊥"] };
    case "sum": case "product":
      return { prec: ADD, pieces: [m.k === "sum" ? "∑" : "∏", { sub: m.over ? [{ b: m.binder, t: m.name }, " ∈ ", n(m.over, ADD)] : [] }, " ", n(m.body ?? m.pred, MUL)] };
    case "integral": case "lintegral":
      return { prec: ADD, pieces: [m.k === "integral" ? "∫ " : "∫⁻ ", n(m.body ?? m.pred, MUL), " d", n(m.measure, ATOM), m.name ? "(" : "", ...(m.name ? [{ b: m.binder, t: m.name }, ")"] : [])] };
    case "ae": return { prec: BIND, pieces: [{ word: "for almost every" }, " ", { b: m.binder, t: m.name }, ...(m.type ? [" ∈ ", n(m.type, ADD)] : []), " ", { word: "for" }, " ", n(m.measure, APP), ", ", n(m.body ?? m.pred, BIND)] };
    case "eventually": return { prec: BIND, pieces: [{ word: "eventually along" }, " ", n(m.filter, APP), ", ", n(m.body ?? m.pred, BIND)] };
    case "ae_filter": return { prec: ATOM, pieces: [{ word: "almost everywhere for" }, " ", n(m.measure, APP)] };
    case "prod_measure": return { prec: MUL, pieces: [n(m.left, MUL + 1), " ⊗ ", n(m.right, MUL + 1)] };
    case "volume": return { prec: ATOM, pieces: [{ word: "the volume on" }, " ", n(m.space, APP)] };
    case "measure_of": return { prec: APP, pieces: [n(m.measure, ATOM), "(", n(m.set, BIND), ")"] };
    case "measure_type": return { prec: APP, pieces: [{ word: "a measure on" }, " ", n(m.space, APP)] };
    case "sigma_algebra": return { prec: APP, pieces: [{ word: "a σ-algebra on" }, " ", n(m.space, APP)] };
    case "measure_space": return { prec: APP, pieces: [{ word: "a measure space structure on" }, " ", n(m.space, APP)] };
    case "sigma_finite": return { prec: REL_P, pieces: [n(m.measure, ATOM), " ", { word: "is σ-finite" }] };
    case "finite_measure": return { prec: REL_P, pieces: [n(m.measure, ATOM), " ", { word: "is a finite measure" }] };
    case "probability_measure": return { prec: REL_P, pieces: [n(m.measure, ATOM), " ", { word: "is a probability measure" }] };
    case "memlp": return { prec: REL_P, pieces: [n(m.fn, APP), " ∈ ", ...lp(m.exponent, m.measure, null)] };
    case "integrable": return { prec: REL_P, pieces: [n(m.fn, APP), " ", { word: "is integrable for" }, " ", n(m.measure, APP)] };
    case "lp": return { prec: ATOM, pieces: lp(m.exponent, m.measure, m.codomain) };
    case "euclidean": {
      const d = m.index?.k === "fin" ? m.index.n : null;
      return { prec: ATOM, pieces: [n(m.field, ATOM), { sup: [n(d || m.index, BIND)] }] };
    }
    default:
      if (MAPS[m.k]) return { prec: IMP, pieces: [n(m.domain, IMP + 1), " " + MAPS[m.k], { sub: [n(m.field || m.semilinear, BIND)] }, " ", n(m.codomain, IMP + 1)] };
      return { prec: ATOM, pieces: [{ lean: m.text || m.k }] };
  }
}

// `Lᵖ(μ; E)`: the space of classes, with its exponent, measure and codomain.
function lp(p, mu, E) {
  return ["L", { sup: [n(p, BIND)] }, "(", n(mu, BIND), ...(E ? ["; ", n(E, BIND)] : []), ")"];
}

// Whether a node's tree holds a representative of an a.e. class (which the reader explains).
export function hasRep(m) {
  if (!m || typeof m !== "object") return false;
  if (m.k === "rep") return true;
  return Object.values(m).some((v) => (Array.isArray(v) ? v.some(hasRep) : typeof v === "object" && hasRep(v)));
}

// Every printed expression of a statement record by its identity: the binders' types, the leaves
// and types of its tree (the hypotheses' own trees included) and the properties its objects'
// types carry.
export function printedById(st) {
  const out = new Map();
  const add = (pp) => { if (pp && typeof pp === "object" && pp.id != null && !out.has(pp.id)) out.set(pp.id, pp); };
  const walk = (x) => {
    if (!x || typeof x !== "object") return;
    add(x.leaf); add(x.type);
    for (const p of x.properties || []) add(p.type);
    walk(x.logic);
    (x.args || []).forEach(walk);
  };
  for (const b of st?.binders || []) add(b.type);
  add(st?.conclusion);
  walk(st?.tree);
  return out;
}

// The identities the exact Lean gives sub-terms and occurrences: those of the exact statement,
// and of the properties its objects' types carry, which it lists with their fields.
export function exactIds(st) {
  const out = new Set();
  const add = (pp) => {
    if (!pp || typeof pp !== "object") return;
    if (pp.id != null) out.add(pp.id);
    for (const t of pp.terms || []) out.add(t.id);
    for (const s of pp.segments || []) if (s.at) out.add(s.at);
  };
  add(typeof st?.exact === "object" ? st.exact : null);
  const walk = (x) => {
    if (!x || typeof x !== "object") return;
    for (const p of x.properties || []) add(p.type);
    walk(x.logic);
    (x.args || []).forEach(walk);
  };
  walk(st?.tree);
  return out;
}

// The identity under which the exact statement shows the sub-term at `id`: `id` itself, or, for
// an application printed with notation by a probe that tagged it at its head (before #457),
// that head's position.
export function exactKey(ids, id) {
  if (id == null || ids.has(id)) return id;
  for (let k = id + "/0"; k.length < id.length + 40; k += "/0") if (ids.has(k)) return k;
  return id;
}

// The rows of the readable statement (`readable.rows`) that one row of the comparison
// (`comparison.statementRows`) shows: the objects of its binders, its conditions and supplied
// structure, and, for the conclusion's row, everything after the binders that open the statement.
export function readableOf(st, g) {
  const rows = st?.readable?.rows;
  if (!Array.isArray(rows)) return null;
  const opening = (st.binders || []).length;
  const mine = new Set([...(g.heads || (g.head != null ? [g.head] : [])), ...(g.members || [])]);
  const isOpening = (r) => r.k === "objects" ? r.objects.some((o) => o.var < opening)
    : (r.k === "condition" || r.k === "structure") && r.var != null && r.var < opening;
  if (g.conclusion) return rows.filter((r) => !isOpening(r));
  // Objects introduced together share a row of the comparison (`heads`); one the comparison
  // shows alone is drawn with its own type's expression.
  const out = [];
  for (const r of rows) {
    if (!isOpening(r)) continue;
    if (r.k === "objects") {
      const objs = r.objects.filter((o) => mine.has(o.var));
      if (objs.length) out.push({ ...r, objects: objs, at: objs.length === r.objects.length ? r.at : objs[0].at ?? r.at,
        properties: (r.properties || []).filter((p) => mine.has(p.object)),
        data: (r.data || []).filter((p) => mine.has(p.object)) });
    } else if (mine.has(r.var)) out.push(r);
  }
  return out;
}
