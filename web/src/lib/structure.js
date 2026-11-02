// What a structure is made of (`structure` on its declaration record, from the probe): its
// fields grouped by where they come from, those it inherits from each parent (by the parent
// projection they come through, in the order of its parents) and those it declares. For a
// structure that extends another, `declares` is exactly what it adds. The engine groups them the
// same way (`objects.structure_view`).
export function structureOf(rec) {
  const st = rec?.structure;
  if (!st || typeof st !== "object") return null;
  const parentOf = new Map((st.parents || []).map((p) => [p.projection, p.structure]));
  const declares = [];
  const inherits = new Map();
  for (const f of st.fields || []) {
    if (f.declared_in === rec.name || !f.inherited) { declares.push(f); continue; }
    const parent = (f.via?.length && parentOf.get(f.via[0])) || f.declared_in;
    if (!inherits.has(parent)) inherits.set(parent, []);
    inherits.get(parent).push(f);
  }
  return { ...st, declares, inherits: [...inherits].map(([parent, fields]) => ({ parent, fields })) };
}

// The propositions a construction's value carries (`result_properties`): the fields of its value
// that are propositions, each established by the definition.
export const carriedByValue = (rec) => (rec?.result_properties || []).filter((p) => p.kind === "proposition");
