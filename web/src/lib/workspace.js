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

// `ops` are applied together or not at all. The request id makes a retried request harmless.
export const updateWorkspace = (id, ops) =>
  call("api/workspace", { action: "update", id, ops, op_id: newId("req") });

// Attach the passages near a claim that the engine proposes as context of a requirement; each
// stays a proposal until the auditor accepts or removes it.
export const suggestContext = (id, claim, requirement) =>
  call("api/workspace", { action: "suggest", id, claim, requirement, op_id: newId("req") });

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
