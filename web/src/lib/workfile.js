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
const clone = (v) => JSON.parse(JSON.stringify(v ?? null));

// The steps of a review draft and what each records once it is taken, and what a draft records
// as seen (`workspace.TAKEN` and `CARRIED`).
const TAKEN = [
  ["locked_at", ["reading", "locked_at", "revealed_by", "source_sha256"], "its reading was locked differently here"],
  ["decided_at", ["group", "verdict", "detail", "comparison", "witness", "checklist", "correspondence", "decided_at", "lean"],
   "its verdict was recorded differently here"],
  ["author_shown_at", ["author_shown_at"], "the author's review was shown at another time here"],
];
const CARRIED = ["reader_exposure", "shown_fingerprint"];
const stepOf = (d) => STAGES.indexOf(d.stage) + 1;

// The review drafts of the page's work (`here`) after an import brings in `theirs`, by the rules
// of `workspace.merge_drafts`, which `machinechecked workspace import` and `view` use: a draft
// here that the file lacks is kept; the file's is added when here has none (unless a report here
// was made from it), and replaces the one here when it continues it; an older one is left; one
// that differs only in what was typed at the same step replaces it only with `replace`; one whose
// taken steps differ is left. So no import unlocks a reading, changes a recorded verdict, or
// forgets what a draft records as seen. Returns `{drafts, applied, not_applied, kept}`, as the
// engine does.
export function mergeDrafts(here, theirs, reports, replace = false) {
  const drafts = clone(here);
  const applied = [], notApplied = [], kept = [];
  for (const uid of Object.keys(theirs).sort()) {
    const f = theirs[uid], h = here[uid];
    if (h == null) {
      if (f.locked_at && reports.some((r) => r.unit?.id === uid && r.reading?.locked_at === f.locked_at)) {
        notApplied.push({ unit: uid, kind: "submitted", why: "submitted here as a report" });
        continue;
      }
      drafts[uid] = clone(f);
      applied.push({ unit: uid, how: "added" });
      continue;
    }
    if (canon(f) === canon(h)) continue;
    const takenH = TAKEN.filter(([k]) => h[k]).map(([k]) => k), takenF = TAKEN.filter(([k]) => f[k]).map(([k]) => k);
    const differs = TAKEN.find(([k, fields]) => takenH.includes(k) && takenF.includes(k)
      && fields.some((x) => canon(h[x]) !== canon(f[x])))?.[2] ?? null;
    const sh = stepOf(h), sf = stepOf(f);
    const later = (a, b, sa, sb) => b.every((x) => a.includes(x)) && (sa > sb || (sa === sb && a.length > b.length));
    let how;
    if (differs == null && later(takenF, takenH, sf, sh)) how = `advanced from step ${sh} to step ${sf}`;
    else if (differs == null && later(takenH, takenF, sh, sf)) {
      notApplied.push({ unit: uid, kind: "older", why: `older than the draft here (step ${sf} in the file, step ${sh} here)` });
      continue;
    } else if (differs == null && canon(takenH) === canon(takenF) && sh === sf) {
      if (!replace) {
        notApplied.push({ unit: uid, kind: "typed", why: `differs from the draft here only in what was typed at step ${sh}; kept as here` });
        kept.push({ unit: uid, current: clone(h), proposed: clone(f) });
        continue;
      }
      how = `replaced what was typed at step ${sh}`;
    } else {
      notApplied.push({ unit: uid, kind: "diverged", why: `${differs ?? "it has taken other steps than the draft here"}; kept as here` });
      kept.push({ unit: uid, current: clone(h), proposed: clone(f) });
      continue;
    }
    const d = clone(f);
    for (const k of CARRIED) if (h[k] && !d[k]) d[k] = h[k];
    drafts[uid] = d;
    applied.push({ unit: uid, how });
    if (how.startsWith("replaced")) kept.push({ unit: uid, current: clone(d), proposed: clone(h) });
  }
  return { drafts, applied, not_applied: notApplied, kept };
}

const workOf = (work) => (work.reviewer ? work.reviewer.id || reviewerId(work.reviewer) : null);
const union = (a, b) => { const out = clone(a || []); for (const x of b || []) if (!out.some((y) => canon(y) === canon(x))) out.push(clone(x)); return out; };

// What importing workspace `ws` would do to the page's work. Refused (`error`) when the browser
// holds the review work of another reviewer, or of another workspace (a static copy keeps one).
// Else `merge` (`mergeDrafts` without `replace`) and `typed`, the drafts that differ only in what
// was typed, which the reader may choose to take from the file.
export function importPlan(work, ws) {
  const mine = workOf(work), theirs = ws.reviewer?.id || null;
  const held = Object.values(work.drafts || {}).some(begun) || (work.reports || []).length
    || (work.exposure || []).length || Object.keys(work.workspace?.records || {}).length;
  if (mine && theirs && !sameReviewer(mine, theirs) && held) {
    return { error: `the file is the workspace of ${theirs}, and this browser holds the review work of ${mine}` };
  }
  if (work.workspace?.id !== ws.id && held) {
    return { error: `the file is workspace ${ws.id}, and this browser holds the review work of `
      + (work.workspace ? `workspace ${work.workspace.id}` : "a workspace it has not exported")
      + "; a static copy keeps one workspace, so import the file where no review work is kept" };
  }
  if (work.workspace?.id !== ws.id) return { merge: null, typed: [] };
  const merge = mergeDrafts(work.drafts || {}, ws.review.drafts, union(work.reports, ws.review.reports));
  return { merge, typed: merge.not_applied.filter((n) => n.kind === "typed") };
}

// The import itself (`importPlan` first). Into the same workspace, as `machinechecked workspace
// import` brings a file into one it holds: the drafts merge (`mergeDrafts`, with `replace`), the
// reports, exposure, conflicts and provenance are kept with the file's, a draft that differed is
// kept with both versions under `conflicts`, and the records the page does not use are the file's.
// Else the page's work becomes the file's workspace. The workspace records the import. Returns the
// merge, for what was not applied.
export function applyImport(work, ws, from, replace = false) {
  const here = clone({ drafts: work.drafts || {}, reports: work.reports || [], exposure: work.exposure || [],
                       workspace: work.workspace || null });
  const same = here.workspace?.id === ws.id;
  const { review, exposure, exported_at: _at, ops: _ops, ...shell } = clone(ws);
  let drafts = review.drafts, reports = review.reports, exp = exposure, merge = null;
  if (same) {
    reports = union(here.reports, review.reports);
    exp = union(here.exposure, exposure);
    merge = mergeDrafts(here.drafts, review.drafts, reports, replace);
    drafts = merge.drafts;
    shell.records = { ...(here.workspace.records || {}), ...shell.records };
    const at = now(), applied = new Set(merge.applied.map((a) => a.unit));
    shell.conflicts = [...union(here.workspace.conflicts, shell.conflicts),
      ...merge.kept.map((k) => ({ id: `draft ${k.unit}`, current: k.current, proposed: k.proposed, at,
                                  by: workOf(work), how: applied.has(k.unit) ? "import, replaced" : "import" }))];
    shell.provenance = union(here.workspace.provenance, shell.provenance);
  } else {
    const mine = workOf(work);
    if (!mine || !ws.reviewer?.id || sameReviewer(mine, ws.reviewer.id)) exp = union(here.exposure, exposure);
  }
  if (ws.reviewer?.id) work.reviewer = pageReviewer(ws.reviewer);
  shell.provenance = [...(shell.provenance || []), { event: "imported", at: now(), by: workOf(work), from }];
  work.workspace = shell;
  work.drafts = drafts;
  work.reports = reports;
  work.exposure = exp;
  work.exported = Math.min(work.exported || 0, reports.length);
  return merge;
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
