// The review page's work as a workspace file (`prooflens/workspace@1`, the format `workspace.py`
// defines and `machinechecked workspace export` writes). A static copy of the site writes its
// work in that format, so that `machinechecked workspace import` and `machinechecked view`
// continue it, and reads what they export, so that work moves between them without loss. It keeps
// the parts of a workspace it does not use (findings and other records, where to resume,
// provenance) as the file gave them, and writes them back. Under `machinechecked view` the engine
// reads and writes the files; the page only chooses which of the reviewer's workspaces it works in.

import { now, reviewerId, READER_SEEN } from "./review.js";
import { newId } from "./workspace.js";

export const WORKSPACE_SCHEMA = "prooflens/workspace@1";
const MODES = ["independent", "informed"];
const STAGES = ["read", "compare", "author"];

const isObject = (v) => v != null && typeof v === "object" && !Array.isArray(v);
// JSON with its keys in order, to compare what the engine and the page wrote.
function canon(v) {
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (isObject(v)) return `{${Object.keys(v).sort().map((k) => `${JSON.stringify(k)}:${canon(v[k])}`).join(",")}}`;
  return JSON.stringify(v ?? null);
}
const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o?.[k] != null).map((k) => [k, o[k]]));
const count = (n, one, many = one + "s") => `${n} ${n === 1 ? one : many}`;

// Whether two reviewer ids name one reviewer, as the protocol keys a reviewer's work
// (`workspace.reviewer_slug`).
export function sameReviewer(a, b) {
  const slug = (s) => String(s).replace(/[^\p{L}\p{N}_.-]+/gu, "_");
  return !!a && !!b && slug(a) === slug(b);
}

// The page's reviewer as a workspace and a report name them (`review_cli.parse_reviewer`).
export function workspaceReviewer(r) {
  const model = r.kind === "model";
  return { id: r.id || reviewerId(r), kind: model ? "model" : "human", name: model ? null : r.name || null,
           model: model ? r.model || null : null, same_family_as_author: model ? r.sameFamily || "unknown" : "no",
           identity: "self-declared" };
}

// The page's reviewer from a workspace's.
function pageReviewer(r) {
  const model = r.kind === "model";
  const rest = String(r.id).replace(/^(human|llm):/, "");
  return { kind: model ? "model" : "human", name: model ? "" : r.name || rest.replace(/-/g, " "),
           model: model ? r.model || rest : "", sameFamily: model ? r.same_family_as_author || "unknown" : "no", id: r.id };
}

// A new workspace for an independent review, as `workspace.new` opens one, with the sources of
// this build (`targets.Snapshot.sources`). Its exposure and review are the page's own fields.
function newWorkspace(index, reviewer) {
  return {
    schema: WORKSPACE_SCHEMA, id: newId("ws"), created_at: now(), reviewer, mode: "independent", revision: 0,
    selection: {},
    sources: index ? { release: index.release ?? null, project: pick(index.project, ["name", "commit", "repository"]),
                       papers: (index.papers || []).map((p) => pick(p, ["id", "title", "revision", "pdf_sha256"])) } : {},
    records: {}, resume: {}, conflicts: [], provenance: [],
  };
}

// The workspace the page's work is in: opened the first time the work is written to a file, so
// that every file it writes is the same workspace. Returns whether it opened one.
export function ensureWorkspace(work, index) {
  if (work.workspace) return false;
  work.workspace = newWorkspace(index, workspaceReviewer(work.reviewer));
  return true;
}

// The page's work (`ensureWorkspace` first) as a workspace file. A draft in which an earlier
// version of the page recorded that the Lean was seen on a claim's page before its reading
// (`reader_exposure`) adds that exposure for the unit's claims, as the engine reads it.
export function workspaceFile(work, units) {
  const { workspace: ws, reviewer } = work;
  const me = reviewer ? workspaceReviewer(reviewer) : null;
  const exposure = [...(work.exposure || [])];
  for (const [id, d] of Object.entries(work.drafts || {})) {
    const u = units.find((x) => x.id === id);
    if (!d?.reader_exposure || d.stage !== "read" || !u) continue;
    const e = { what: ["Lean"], claims: u.claims.map((c) => c.id).sort(), how: READER_SEEN };
    if (!exposure.some((x) => canon(x) === canon(e))) exposure.push(e);
  }
  return { ...ws, reviewer: me && !sameReviewer(ws.reviewer?.id, me.id) ? me : ws.reviewer ?? me, exposure,
           review: { drafts: work.drafts || {}, reports: work.reports || [] }, exported_at: now() };
}

// The workspace a file holds, read as `machinechecked workspace import` reads it
// (`workspace.upgrade` and `import_`): a workspace, or the older review work file. Throws the
// reason when it is not one this version reads, when a part is not what a workspace holds, or
// when it is an informed investigation, which a static copy cannot continue: its reviews are
// independent.
export function readWorkspaceFile(text) {
  let raw;
  try { raw = JSON.parse(text); } catch { throw new Error("not a JSON file"); }
  if (!isObject(raw)) throw new Error("not a workspace or review work file");
  let ws = raw;
  if (raw.schema !== WORKSPACE_SCHEMA) {
    if (raw.schema) throw new Error(`not a workspace this version can read (schema '${raw.schema}')`);
    if (!isObject(raw.drafts) || !Array.isArray(raw.reports)) throw new Error("not a workspace or review work file");
    ws = { ...newWorkspace(null, raw.reviewer || {}), exposure: [], review: { drafts: raw.drafts, reports: raw.reports },
           provenance: [{ event: "upgraded from a review work file", at: now() }] };
  }
  if (!MODES.includes(ws.mode)) throw new Error(`mode '${ws.mode}' is not one of: ${MODES.join(", ")}`);
  if (ws.mode === "informed") {
    throw new Error("it is an informed investigation, which a static copy of the site cannot continue: "
      + "its reviews are independent. Continue it under machinechecked view");
  }
  const review = ws.review ?? { drafts: {}, reports: [] };
  const bad = (what) => { throw new Error(`not a workspace: ${what}`); };
  if (typeof ws.id !== "string" || !ws.id) bad("it has no id");
  if (ws.reviewer != null && !(isObject(ws.reviewer) && (ws.reviewer.id == null || typeof ws.reviewer.id === "string"))) bad("its reviewer is not a reviewer");
  if (!isObject(review) || !isObject(review.drafts ?? {}) || !Array.isArray(review.reports ?? [])) bad("its review work is not drafts and reports");
  for (const [id, d] of Object.entries(review.drafts ?? {})) {
    if (!isObject(d) || !STAGES.includes(d.stage)) bad(`the draft of ${id} is at no step`);
  }
  for (const r of review.reports ?? []) if (!isObject(r) || typeof r.unit?.id !== "string" || !isObject(r.pins)) bad("a report has no unit or pins");
  if (!Array.isArray(ws.exposure ?? []) || !(ws.exposure ?? []).every((e) => isObject(e) && Array.isArray(e.what))) bad("its exposure is not a list of what was seen");
  if (!isObject(ws.records ?? {})) bad("its records are not an object");
  return { ...ws, exposure: ws.exposure ?? [], records: ws.records ?? {},
           review: { drafts: review.drafts ?? {}, reports: review.reports ?? [] } };
}

const begun = (d) => d && (d.stage !== "read" || (d.reading || "").trim() || d.reader_exposure);

// What importing workspace `ws` would do to the page's work: refused (`error`) when the browser
// holds the work of another reviewer; else what of the browser's work the file does not hold and
// the import replaces (`losing`, in words; empty when it loses nothing). The file's drafts replace
// the browser's. The browser's exposure is kept, and so are its reports when the file is the same
// workspace, as `machinechecked workspace import` keeps them.
export function importPlan(work, ws) {
  const mine = work.reviewer ? work.reviewer.id || reviewerId(work.reviewer) : null;
  const theirs = ws.reviewer?.id || null;
  const records = work.workspace?.records || {};
  const held = Object.values(work.drafts || {}).some(begun) || (work.reports || []).length
    || (work.exposure || []).length || Object.keys(records).length;
  if (mine && theirs && !sameReviewer(mine, theirs) && held) {
    return { error: `the file is the workspace of ${theirs}, and this browser holds the review work of ${mine}` };
  }
  const losing = Object.entries(work.drafts || {}).filter(([id, d]) => begun(d) && canon(d) !== canon(ws.review.drafts[id]))
    .map(([id]) => `your draft of ${id}`);
  if (work.workspace?.id !== ws.id) {
    const known = new Set(ws.review.reports.map(canon));
    const extra = (work.reports || []).filter((r) => !known.has(canon(r))).length;
    if (extra) losing.push(count(extra, "report"));
    const other = Object.keys(records).filter((k) => canon(records[k]) !== canon(ws.records[k])).length;
    if (other) losing.push(`${count(other, "record")} of workspace ${work.workspace.id}`);
  }
  return { losing };
}

// The import itself (`importPlan` first): the page's work becomes the file's workspace, keeping
// what `importPlan` says it keeps, and the workspace records that it was imported here.
export function applyImport(work, ws, from) {
  const mine = work.reviewer ? work.reviewer.id || reviewerId(work.reviewer) : null;
  const same = work.workspace?.id === ws.id;
  const { review, exposure, exported_at: _at, ops: _ops, ...shell } = ws;
  const reports = [...review.reports];
  const exp = [...exposure];
  const add = (list, x) => { if (!list.some((y) => canon(y) === canon(x))) list.push(x); };
  if (same) {
    for (const r of work.reports || []) add(reports, r);
    shell.records = { ...(work.workspace.records || {}), ...shell.records };
  }
  if (!mine || !ws.reviewer?.id || sameReviewer(mine, ws.reviewer.id)) for (const e of work.exposure || []) add(exp, e);
  if (ws.reviewer?.id) work.reviewer = pageReviewer(ws.reviewer);
  shell.provenance = [...(shell.provenance || []),
    { event: "imported", at: now(), by: work.reviewer ? work.reviewer.id || reviewerId(work.reviewer) : null, from }];
  work.workspace = shell;
  work.drafts = { ...review.drafts };
  work.reports = reports;
  work.exposure = exp;
  work.exported = Math.min(work.exported || 0, reports.length);
}

// What an import brought, in words.
export function importedWords(ws) {
  const recs = Object.keys(ws.records || {}).length;
  return `${count(Object.keys(ws.review.drafts).length, "draft")}, ${count(ws.review.reports.length, "report")}`
    + `, ${count(recs, "record")}`;
}

// A file for the reader to save.
export function saveFile(name, body) {
  const blob = new Blob([JSON.stringify(body, null, 1) + "\n"], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

// Under `machinechecked view`, the workspace of the reviewer's that the review page works in
// (`--workspace` of `machinechecked review`), as this browser remembers it for the project; none
// is their first workspace.
const CHOSEN = (project) => `machinechecked-review-workspace:${project || "project"}`;
export function chosenWorkspace(project) {
  try { return localStorage.getItem(CHOSEN(project)) || null; } catch { return null; }
}
export function chooseWorkspace(project, id) {
  try { id ? localStorage.setItem(CHOSEN(project), id) : localStorage.removeItem(CHOSEN(project)); } catch { /* storage off */ }
}
