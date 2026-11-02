// Inspections beside a comparison: a definition, a property carried by an object's type, an
// application of a theorem, a fact inside a proof, a saved piece of evidence or the audit's
// details, opened next to the comparison row it concerns while the claim stays on the page.
//
// The open inspection is a trail in the page's address (`?inspect=A&inspect=B&at=<row>`), so
// browser Back and Forward close and reopen it. A pin keeps an inspection open while another
// reference is opened; pins live in this page (and, in an investigation, in the workspace's
// resume state, which `Investigation.svelte` writes).

import { route, go, withQuery } from "./route.svelte.js";
import { sameScope } from "./comparison.js";

export const DETAILS = "@details";

// An inspection's token in the address, and back. A plain name is a declaration.
export function tokenOf(item) {
  switch (item.kind) {
    case "details": return DETAILS;
    case "property": return `property:${item.spec}|${item.id}`;
    case "fact": return `fact:${item.decl}|${item.id}`;
    case "application": return `application:${item.callee}|${item.id}`;
    case "evidence": return `evidence:${item.ws}|${item.id}`;
    default: return item.name;
  }
}

export function itemOf(token) {
  if (token === DETAILS) return { kind: "details" };
  const m = /^(property|fact|application|evidence):(.*)\|([^|]*)$/.exec(token || "");
  if (!m) return { kind: "decl", name: token };
  const [, kind, a, id] = m;
  return kind === "property" ? { kind, spec: a, id } : kind === "fact" ? { kind, decl: a, id }
    : kind === "application" ? { kind, callee: a, id } : { kind, ws: a, id };
}

// The open trail and the row it is beside (`top` when none is named: above the comparison).
export const trail = () => route.inspection || [];
export const anchor = () => (trail().length ? route.at || "top" : null);

// The element that had focus when each inspection of the trail was opened, to return to.
const openers = [];

// Open an inspection beside row `at`. From inside an open inspection (`nested`) it continues that
// trail; otherwise it starts a new one beside its row.
export function openInspection(token, at = "top", { nested = false } = {}) {
  const t = trail();
  const here = nested && t.length ? route.at || "top" : at;
  const next = nested && t.length ? [...t, token] : [token];
  if (t.length === next.length && t.every((x, i) => x === next[i]) && (route.at || "top") === here) return;
  openers[next.length - 1] = document.activeElement;
  go(withQuery(location.hash, { inspect: next, at: here === "top" ? null : here }));
}

export function backTo(n) {
  const t = trail();
  go(withQuery(location.hash, { inspect: t.slice(0, n), at: n ? route.at : null }));
}

export const opener = (depth) => openers[depth];

// Pins: `{token, at, scope, ident, label}`. `scope` is the view the pin was made in
// (`comparison.pinScope`) and `ident` the identity of what it shows there.
export const pins = $state({ list: [] });

export const pinsIn = (scope) => pins.list.filter((p) => sameScope(p.scope, scope));
export const pinOf = (scope, token) => pins.list.find((p) => sameScope(p.scope, scope) && p.token === token) || null;

export function togglePin(pin) {
  const had = pinOf(pin.scope, pin.token);
  pins.list = had ? pins.list.filter((p) => p !== had) : [...pins.list, pin];
}

// Replace the pins of one view (a resumed investigation's).
export function setPins(scope, list) {
  pins.list = [...pins.list.filter((p) => !sameScope(p.scope, scope)), ...list.map((p) => ({ ...p, scope }))];
}

// Facts inside a proof and applications of a declaration, as Lean last gave them in this page
// (under `machinechecked view`), so that an inspection of one can show it.
export const facts = new Map();
export const applications = new Map();

// The open investigation's workspace, when one is open in this page: its saved evidence opens as
// an inspection.
export const workspace = $state({ id: null, view: null });
