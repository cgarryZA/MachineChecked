// The auditor's saved investigation (`prooflens/workspace@1`), read and updated through the local
// server of `machinechecked view`. The engine validates and saves every edit (the same service
// as `machinechecked workspace`), so the reader keeps no copy of its own; it remembers only which
// workspace this browser last opened.

const REMEMBER = "machinechecked-workspace";

async function call(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  let out = {};
  try { out = await r.json(); } catch { /* not this server's answer */ }
  if (!r.ok) {
    const e = new Error(out.error || `${r.status} ${r.statusText}`);
    e.status = r.status;
    e.conflicts = out.conflicts || null;
    e.candidates = out.candidates || null;
    throw e;
  }
  return out;
}

export const listWorkspaces = () => call("api/workspaces");

export const openWorkspace = (reviewer, mode, id) =>
  call("api/workspace", { action: "open", reviewer, mode, id });

export const showWorkspace = (id, claim) =>
  call(`api/workspace?id=${encodeURIComponent(id)}${claim ? `&claim=${encodeURIComponent(claim)}` : ""}`);

// The findings of a workspace that a revision of the paper reopens, for each version map it keeps
// to this site's release (`reopen.for_site` of the engine), with the Lean side against this build.
export const revisionOf = (id) => call(`api/workspace/revision?id=${encodeURIComponent(id)}`);

// `ops` are applied together or not at all. The request id makes a retried request harmless.
export const updateWorkspace = (id, ops) =>
  call("api/workspace", { action: "update", id, ops, op_id: newId("req") });

// A page of the typed facts inside one declaration's proof (`compare --query proof-facts`): the
// facts after the fact `after` (its id) when given, ranked by `match` when given. Lean reads each
// page on its first request; the engine caches the answer.
export const proofFacts = (name, match, after) =>
  call(`api/proof-facts?name=${encodeURIComponent(name)}${match ? `&match=${encodeURIComponent(match)}` : ""}${after ? `&after=${encodeURIComponent(after)}` : ""}`);

// Attach the passages near a claim that the engine proposes as context of a requirement; each
// stays a proposal until the auditor accepts or removes it.
export const suggestContext = (id, claim, requirement) =>
  call("api/workspace", { action: "suggest", id, claim, requirement, op_id: newId("req") });

// A workspace as a file to hand on (`machinechecked workspace export`), and a file brought in
// (`machinechecked workspace import`): `{workspace, added, conflicts, problems}`.
export const exportWorkspace = (id) => call(`api/workspace/export?id=${encodeURIComponent(id)}`);
// `replace_drafts` takes the file's drafts that differ only in what was typed (`merge_drafts`);
// `dry_run` saves nothing and says what the import would do.
export const importWorkspace = (data, by, { replace_drafts = false, dry_run = false } = {}) =>
  call("api/workspace", { action: "import", data, by, replace_drafts, dry_run });

export function newId(prefix) {
  const r = globalThis.crypto?.randomUUID?.() || Math.random().toString(16).slice(2) + Date.now().toString(16);
  return `${prefix}-${r.replace(/-/g, "").slice(0, 12)}`;
}

export function rememberedWorkspace() {
  try { return localStorage.getItem(REMEMBER); } catch { return null; }
}

export function rememberWorkspace(id) {
  try { id ? localStorage.setItem(REMEMBER, id) : localStorage.removeItem(REMEMBER); } catch { /* storage off */ }
}

// A person's reviewer id, as the review protocol writes it.
export function humanId(name) {
  const slug = String(name || "").trim().replace(/\s+/g, "-");
  return slug ? `human:${slug}` : "";
}

// -- writing a composition ------------------------------------------------------------------
// A composition (`composition.py`) as the reader's form holds it, and the `put` the engine
// checks. The engine refuses what does not hold (a step resting on nothing, an `after` that is not
// an earlier step, a retained witness of a step it does not follow, full coverage with a printed
// requirement no step establishes or an obligation open, a bridge Lean does not check) and adds
// the obligations an identification through a partial connection leaves; the reader sends the
// form as it is and shows the refusal as the engine words it.

export const COMPOSITION_RELATIONS = ["same object", "equal", "restriction", "coercion", "other"];
export const COMPOSITION_HOW = ["evidence", "retained witness", "definition"];
export const OBLIGATION_KINDS = ["compatible witnesses", "local to global", "equality transport",
  "constant dependence", "genericity", "side condition", "other"];

const freshId = (prefix, taken) => {
  let n = 1;
  while (taken.includes(prefix + n)) n++;
  return prefix + n;
};
export const newStep = (steps = []) => ({ id: freshId("s", steps.map((s) => s.id)), establishes: "", requirements: [],
  uses: [], after: [], substitutions: [], inference: "" });
export const newIdentification = (steps = []) => ({ left: { step: steps[0]?.id || "", object: "" },
  right: { step: steps.at(-1)?.id || "", object: "" }, relation: "same object", how: "evidence", evidence: [] });
export const newObligation = (obligations = []) => ({ id: freshId("o", obligations.map((o) => o.id)), kind: "compatible witnesses",
  text: "", state: "open", steps: [], evidence: [] });
export const newComposition = () => ({ id: null, rev: null, statement: "", steps: [newStep()], identifications: [],
  obligations: [], coverage: "", bridge: { theorem: "", target: "" } });

// A saved composition (`workspace.view`) as the form edits it.
export function compositionDraft(c) {
  return {
    id: c.id, rev: c.rev ?? null, statement: c.statement || "",
    steps: (c.steps || []).map((s) => ({ id: s.id, establishes: s.establishes || "", requirements: [...(s.requirements || [])],
      uses: [...(s.uses || [])], after: [...(s.after || [])],
      substitutions: (s.substitutions || []).map((x) => ({ variable: x.variable, value: x.value, in: x.in || "" })),
      inference: s.inference || "" })),
    identifications: (c.identifications || []).map((x) => ({ left: { ...x.left }, right: { ...x.right },
      relation: x.relation, how: x.how, evidence: [...(x.evidence || [])] })),
    obligations: (c.obligations || []).map((o) => ({ id: o.id, kind: o.kind, text: o.text || "", state: o.state,
      steps: [...(o.by?.steps || [])], evidence: [...(o.by?.evidence || [])], ...(o.connection ? { connection: o.connection } : {}) })),
    coverage: c.coverage || "", bridge: { theorem: c.bridge?.theorem || "", target: c.bridge?.target || "" },
  };
}

// The draft without step `id`, and without the references to it the form shows as choices (the
// steps another follows from, the steps that discharge an obligation). An identification that
// names it stays, for the engine to refuse.
export function withoutStep(draft, id) {
  return { ...draft, steps: draft.steps.filter((s) => s.id !== id).map((s) => ({ ...s, after: s.after.filter((a) => a !== id) })),
    obligations: draft.obligations.map((o) => ({ ...o, steps: o.steps.filter((s) => s !== id) })) };
}

const words = (v) => (typeof v === "string" ? v.trim() : "");

// The `put` that saves the draft for `claim`: a new composition, or the next revision of the one
// it edits (`base_rev`). Empty optional fields are left out; nothing else is changed.
export function compositionOp(draft, claim) {
  const rec = { kind: "composition", claim,
    steps: draft.steps.map((s) => ({ id: s.id, establishes: s.establishes,
      ...(s.requirements.length ? { requirements: s.requirements } : {}),
      ...(s.uses.length ? { uses: s.uses } : {}), ...(s.after.length ? { after: s.after } : {}),
      ...(s.substitutions.length ? { substitutions: s.substitutions.map((x) => ({ variable: x.variable, value: x.value, ...(x.in ? { in: x.in } : {}) })) } : {}),
      ...(words(s.inference) ? { inference: s.inference } : {}) })) };
  if (words(draft.statement)) rec.statement = draft.statement;
  if (draft.identifications.length) {
    rec.identifications = draft.identifications.map((x) => ({ left: x.left, right: x.right, relation: x.relation, how: x.how,
      ...(x.evidence.length ? { evidence: x.evidence } : {}) }));
  }
  if (draft.obligations.length) {
    rec.obligations = draft.obligations.map((o) => ({ id: o.id, kind: o.kind, text: o.text, state: o.state,
      ...(o.steps.length || o.evidence.length ? { by: { ...(o.steps.length ? { steps: o.steps } : {}), ...(o.evidence.length ? { evidence: o.evidence } : {}) } } : {}),
      ...(o.connection ? { connection: o.connection } : {}) }));
  }
  if (draft.coverage) rec.coverage = draft.coverage;
  if (words(draft.bridge.theorem) || words(draft.bridge.target)) rec.bridge = { theorem: words(draft.bridge.theorem), target: words(draft.bridge.target) };
  return { op: "put", ...(draft.id ? { id: draft.id, base_rev: draft.rev, record: { id: draft.id, ...rec } } : { record: { id: newId("c"), ...rec } }) };
}

// The evidence records of a claim a composition can cite: a step rests on a declaration, an
// application or a fact inside a proof; an identification or a discharge may also rest on a
// connection between objects. A rejected candidate is cited by neither.
const usable = (e) => e?.role !== "rejected";
export const stepEvidence = (evidence) => (evidence || []).filter((e) => usable(e) && (e.ref?.decl || e.ref?.app || e.ref?.fact));
export const linkEvidence = (evidence) => (evidence || []).filter((e) => usable(e) && (e.ref?.decl || e.ref?.app || e.ref?.fact || e.ref?.connection));
