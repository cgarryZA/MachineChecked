import { nodesOf } from "./tree.js";

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
