// The properties carried by the types of a statement's objects (`properties`, from the probe),
// in reading order: those of the prefix's objects (and of the objects inside an assumption),
// then those of the objects quantified in the conclusion. Each is `{owner, prop}`, `owner` the
// object (a binder, an object inside an assumption, or a node of the conclusion's logic).
export function carriedOf(st) {
  const out = [];
  const add = (o) => (o?.properties || []).forEach((prop) => out.push({ owner: o, prop }));
  (st?.binders || []).forEach((b) => { add(b); (b.objects || []).forEach(add); });
  const walk = (n) => { if (!n) return; add(n); (n.args || []).forEach(walk); };
  walk(st?.conclusion?.logic);
  return out;
}
