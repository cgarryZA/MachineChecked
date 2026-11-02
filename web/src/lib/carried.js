import { nodesOf, spineOf, conclusionOf } from "./tree.js";

// The properties carried by the types of a statement's objects (`properties`, from the probe),
// in reading order over the statement's tree: those of each binder that opens it, followed by
// those of the objects inside it when it is a hypothesis, then those of the objects quantified
// in the conclusion. Each is `{owner, prop}`, `owner` the node of the object. Data written before
// the tree lists the objects inside a hypothesis as its `objects`.
export function carriedOf(st) {
  const out = [];
  const add = (o) => (o?.properties || []).forEach((prop) => out.push({ owner: o, prop }));
  nodesOf(st).forEach((n) => { add(n); (n.objects || []).forEach(add); });
  return out;
}

// How a carried property stands in its statement, found by the property's identity (its type's
// `id`): `given` (a field of an object the statement is given), `produced` (of a witness it
// produces), `states` (what an assumption whose type is a structure of propositions states),
// `inside` (of an object inside an assumption) or `local` (of an object within the negation,
// alternative, equivalence or premise that contains it), as the statement view
// (Statement.svelte) decides it. With the property and its object; null when the statement has
// no property of that identity.
export function propertyStanding(st, id) {
  const found = (o) => (o?.properties || []).find((p) => p.type?.id === id);
  const binderHow = (b) => b.role === "exists" ? "produced"
    : b.role === "hypothesis" || (b.role === "instance" && b.supplies === "proposition") ? "states" : "given";
  for (const b of spineOf(st)) {
    const p = found(b);
    if (p) return { prop: p, owner: b, how: binderHow(b) };
    for (const o of b.objects || []) {
      const q = found(o);
      if (q) return { prop: q, owner: o, how: "inside" };
    }
    const inner = within(b.logic, true, found);
    if (inner) return inner;
  }
  return within(conclusionOf(st), false, found);
}

const nodeHow = (n, local) => !n.scope ? (local ? "local" : n.op === "exists" ? "produced" : "given")
  : n.scope === "given" || n.scope === "produced" ? n.scope
  : n.scope === "assumed" && n.within?.[0] === "assume" ? "inside" : "local";

// The quantified objects of a tree, each local when a negation, an alternative, an equivalence
// or the premise of an implication contains it.
function within(node, local, found) {
  if (!node || node.leaf) return null;
  if (node.op === "exists" || node.op === "forall") {
    const p = found(node);
    return p ? { prop: p, owner: node, how: nodeHow(node, local) } : within(node.args?.[0], local, found);
  }
  if (node.op === "not") return within(node.args?.[0], true, found);
  if (node.op === "implies") return within(node.args?.[0], true, found) || within(node.args?.[1], local, found);
  for (const a of node.args || []) {
    const r = within(a, local || node.op !== "and", found);
    if (r) return r;
  }
  return null;
}
