// A statement as one tree (`tree`, from the probe): each binder that opens it is a node (`op`
// its role: forall, hypothesis, instance, exists) whose one part is the rest of the statement;
// under them, the conclusion's connectives, quantifiers and leaves; a hypothesis with a shape has
// its own tree (`logic`). Data written before the tree is rebuilt from its binders and the
// conclusion's `logic`, in the same form.

export function treeOf(st) {
  if (st?.tree && typeof st.tree === "object") return st.tree;
  const c = st?.conclusion;
  let node = c ? c.logic || { leaf: c } : null;
  const bs = st?.binders || [];
  for (let i = bs.length - 1; i >= 0; i--) node = { ...bs[i], op: bs[i].role, var: i, args: node ? [node] : [] };
  return node;
}

// The binders that open the statement, in order, each as a binder record (`role`) with what the
// tree gives it: its properties and, for a hypothesis, its own tree.
export function spineOf(st) {
  const out = [];
  let n = treeOf(st);
  const k = (st?.binders || []).length;
  for (let i = 0; i < k && n; i++) {
    out.push({ ...(st.binders[i] || {}), ...n, role: n.op });
    n = n.args?.[0];
  }
  return out;
}

// The part of the tree under the binders that open the statement: the conclusion's shape.
export function conclusionOf(st) {
  let n = treeOf(st);
  const k = (st?.binders || []).length;
  for (let i = 0; i < k && n; i++) n = n.args?.[0];
  return n?.leaf ? null : n || null;
}

// Every node of the tree, in reading order, hypotheses' own trees included.
export function nodesOf(st) {
  const out = [];
  const walk = (n) => {
    if (!n || typeof n !== "object") return;
    out.push(n);
    walk(n.logic);
    (n.args || []).forEach(walk);
  };
  walk(treeOf(st));
  return out;
}

// Whether a tree binds a variable anywhere: a "for every" or a "there is".
export const quantifies = (n) => !!n && (n.op === "forall" || n.op === "exists" || (n.args || []).some(quantifies));
