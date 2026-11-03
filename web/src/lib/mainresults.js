// The main results a workspace saves (#112), in the reader's words: the claims and declarations
// `compare --query impact` traces each declaration's use from. A saved selection names who saved
// it, when, the release and project commit it was checked against (`pins`) and what the build
// lacks of it (`problems`), all as the engine gives them (`impact.workspace_selection` under
// `machinechecked view`, `published_work.main_results` in a published audit). A claim stands for
// its linked Lean. Choosing main results changes no status.

const short = (c) => (typeof c === "string" ? c.slice(0, 7) : c);

// A saved selection's pins in words.
export function pinsText(pins) {
  const p = pins || {};
  const parts = [p.release ? `release ${p.release}` : "", p.commit ? `project commit ${short(p.commit)}` : ""].filter(Boolean);
  return parts.length ? "against " + parts.join(", ") : "";
}

// Who saved a selection and when, with its pins: "Saved by X on T, against …".
export function savedText(sel) {
  return [`Saved by ${sel?.by || "an unnamed auditor"}${sel?.at ? " on " + sel.at : ""}`, pinsText(sel?.pins)].filter(Boolean).join(", ") + ".";
}

const claimLabel = (id, claims) => {
  const row = (claims || []).find((c) => c.id === id);
  return row?.number ? `${row.number} (${id})` : id;
};
const problemOf = (e, problems) => (problems || []).find((p) =>
  (e.claim && p.claim === e.claim) || (e.decl && p.decl === e.decl && (p.module ?? null) === (e.module ?? null)))?.problem || null;

// An entry of a selection as the engine accepts it back (`workspace.main_result_entries`).
export const editable = (e) => (e.claim ? { claim: e.claim } : { decl: e.decl, ...(e.module ? { module: e.module } : {}) });

// The entries of a selection, each with its label, what it stands for and its problem. `doc` is
// a workspace's selection as the engine traces from it, whose `main_results` name the
// declarations each entry stands for and whose `unlinked_claims` have no Lean; a published
// selection has neither, and a claim then reads as standing for its linked Lean.
export function entriesOf(sel, claims) {
  const traced = Array.isArray(sel?.main_results) ? sel.main_results : null;
  return (sel?.selected || []).map((e) => {
    const problem = problemOf(e, sel.problems);
    if (e.claim) {
      const names = traced ? traced.filter((m) => (m.selected || []).includes(e.claim)).map((m) => m.name) : null;
      const detail = problem ? null : !traced ? "stands for its linked Lean"
        : (sel.unlinked_claims || []).includes(e.claim) || !names.length ? "no Lean is linked to it"
        : "its linked Lean: " + names.join(", ");
      return { key: "claim:" + e.claim, label: claimLabel(e.claim, claims), detail, problem, entry: editable(e) };
    }
    return { key: "decl:" + e.decl + "|" + (e.module || ""), label: e.decl, detail: e.module ? "in " + e.module : null, problem, entry: editable(e) };
  });
}

// The suggestion the engine traces from when nothing is saved: each declaration with the claims
// it is linked to.
export function suggestedOf(doc, claims) {
  return (doc?.main_results || []).map((m) => ({ key: "suggested:" + m.name, label: m.name,
    detail: (m.claims || []).length ? "linked to " + m.claims.map((c) => claimLabel(c, claims)).join(", ") : null }));
}

// The selection with `name` added, or without its entry `i`, as the engine takes it back.
export const withAdded = (sel, name) => [...(sel?.selected || []).map(editable), name];
export const without = (sel, i) => (sel?.selected || []).filter((_, j) => j !== i).map(editable);
// Whether the selection saved now is the one shown: an edit replaces the whole selection, so the
// reader saves only over the one it shows.
export const sameSelection = (a, b) => JSON.stringify((a?.selected || []).map(editable)) === JSON.stringify((b?.selected || []).map(editable));
