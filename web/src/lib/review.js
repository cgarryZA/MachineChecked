// The reviewer's work: drafts and finished reports, kept in this browser and exported as a file.
//
// A report records what the reviewer did, in the order the queue let them do it: their own
// reading of the paper (locked before the Lean was shown), their comparison and verdict, then
// their response to the author’s review. The maintainer evaluates the exported report.
// The report records the steps and prior exposure observed in this browser.

export const REPORT_SCHEMA = "prooflens/review-report@1";

// The precise verdicts of the review protocol, under the three first choices.
export const VERDICTS = {
  matches: [
    { value: "faithful", label: "Faithful" },
    { value: "faithful with representation choices", label: "Faithful with representation choices",
      detail: "List the representation choices, and say why each is harmless." },
    { value: "broader", label: "Broader; implies the printed claim",
      detail: "State the instantiation that gives the printed claim." },
  ],
  problem: [
    { value: "narrower", label: "Narrower",
      detail: "Say exactly how: which hypothesis is added, which case is lost." },
    { value: "mismatched", label: "Mismatched", detail: "Say what it states instead." },
    { value: "vacuous", label: "Vacuous",
      detail: "Say why the hypotheses cannot be met, or why the witness does not meet them." },
    { value: "refutation not valid", label: "Refutation not valid", refuteOnly: true,
      detail: "Say how the refuted proposition is stronger than the printed claim." },
  ],
  cannot: [
    { value: "cannot determine", label: "Cannot determine",
      detail: "State the open question, and what would decide it." },
  ],
};

// A proof step is reviewed as printed: does it hold? (`steps.VERDICTS` in the engine.) The
// review records the step's own finding, apart from the statement of its enclosing result.
export const STEP_VERDICTS = {
  matches: [
    { value: "holds as printed", label: "Holds as printed" },
    { value: "holds, with a gap in the argument", label: "Holds, with a gap in the argument",
      detail: "Give the argument the printed proof leaves out." },
  ],
  problem: [
    { value: "false as printed", label: "False as printed",
      detail: "Give the counterexample or the failing case, and what would repair the step." },
  ],
  cannot: [
    { value: "cannot determine", label: "Cannot determine", detail: "Say what would decide it." },
  ],
};
export const STEP_GROUPS = [
  { key: "matches", label: "The step holds" },
  { key: "problem", label: "It fails as printed" },
  { key: "cannot", label: "Cannot determine" },
];

// What to compare, item by item. The checklist guides the comparison and is kept in the report;
// the verdict and the written comparison remain what a maintainer reads.
export const CHECKLIST = {
  statement: [
    { key: "setting", label: "Setting and objects", hint: "the spaces, structures and standing assumptions" },
    { key: "hypotheses", label: "Each hypothesis", hint: "compare each hypothesis and its strength" },
    { key: "quantifiers", label: "Quantifiers and their order", hint: "for all / there is, and which comes first" },
    { key: "definitions", label: "Definitions it relies on", hint: "the Lean definitions mean what the paper's words mean" },
    { key: "conclusion", label: "The conclusion", hint: "compare the conclusion and its strength" },
    { key: "constants", label: "Constants", hint: "what each constant may depend on" },
    { key: "assumed", label: "Assumed results and axioms", hint: "compare which results each statement assumes and proves" },
  ],
  step: [
    { key: "fixed", label: "What is fixed before it", hint: "the quantities, domains and constants the proof has already chosen" },
    { key: "premises", label: "Its premises", hint: "the results and assumptions it cites, at the instances it uses them" },
    { key: "quantifiers", label: "Quantifiers and their ranges", hint: "for all / there is, their order and the range of each" },
    { key: "constants", label: "Constants", hint: "what each constant may depend on" },
    { key: "conclusion", label: "The conclusion", hint: "what the step asserts, and how the proof uses it next" },
  ],
  def: [
    { key: "object", label: "The object", hint: "it is the paper's object, built from the same parts" },
    { key: "parameters", label: "Its parameters", hint: "the same inputs, with the same types and conditions" },
    { key: "conventions", label: "Conventions and edge cases", hint: "junk values, truncated subtraction, division by zero" },
  ],
};
export const MARKS = [
  { value: "matches", label: "matches" },
  { value: "differs", label: "differs" },
  { value: "unsure", label: "unsure" },
];

export const GROUPS = [
  { key: "matches", label: "Matches the paper" },
  { key: "problem", label: "There's a problem" },
  { key: "cannot", label: "Cannot determine" },
];

// The orders of the queue, as `machinechecked review next --order` names them. The queue the
// build writes holds the first two; the informed order also reads the auditors' workspaces, so
// only the local server of `machinechecked view` gives it.
export const ORDERS = [
  { value: "priority", label: "Priority", hint: "Changed evidence and proof use first, then less effort" },
  { value: "document", label: "Paper order", hint: "The paper's order" },
  { value: "informed", label: "Informed", hint: "Also what the auditors' workspaces record as open: prior interpretations" },
];

// How a report names what showed its reviewer prior interpretations through the informed order
// (`review_cli.ORDER_EXPOSURE`, which the command line records in the reviewer's workspace).
export const ORDER_EXPOSURE = "interpretation-informed review order";
export const ORDER_SEEN = `review page (${ORDER_EXPOSURE})`;
// The signals the informed order adds from the workspaces (`review_queue.workspace_signals`).
const WORKSPACE_SIGNALS = ["open question", "difference", "hint"];

// The queue's units in an order the engine arranged: `arranged` lists open units with their
// reasons (and priority records), as the build's paper order or the local server's informed
// order gives them. Units it does not list (reviewed ones) follow in the queue's order; without
// a list, the queue's own order stands.
export function orderedUnits(units, arranged) {
  if (!arranged) return units;
  const byId = new Map(units.map((u) => [u.id, u]));
  const listed = arranged.filter((x) => byId.has(x.id))
    .map((x) => ({ ...byId.get(x.id), reason: x.reason, ...(x.priority ? { priority: x.priority } : {}) }));
  const placed = new Set(listed.map((u) => u.id));
  return [...listed, ...units.filter((u) => !placed.has(u.id))];
}

// Records in the reviewer's work that they have seen prior interpretations of `claims` (the
// claims the informed order drew on), unless an entry already covers them all, as
// `Session.expose` does. Returns whether it recorded anything.
export function recordExposure(work, claims, at) {
  if (!claims?.length) return false;
  const covered = (work.exposure || []).some((e) => (e.what || []).includes("prior interpretations")
    && (e.claims == null || claims.every((c) => e.claims.includes(c))));
  if (covered) return false;
  work.exposure = [...(work.exposure || []),
    { what: ["prior interpretations"], claims: [...claims].sort(), how: ORDER_EXPOSURE, at }];
  return true;
}

// What the recorded exposure says this reviewer had seen of unit `u`, in the form of
// `reading.revealed_by`: prior interpretations of one of its claims count, as on the command
// line, as its author's review.
export function exposureOf(work, u) {
  const ids = (u.claims || []).map((c) => c.id);
  const seen = (work.exposure || []).some((e) => (e.what || []).includes("prior interpretations")
    && (e.claims == null || e.claims.some((c) => ids.includes(c))));
  return seen ? [{ unit: ORDER_SEEN, what: "author's review" }] : [];
}

// Whether the card holds back the informed order's reason for unit `u`: the reviewer locked its
// reading without having seen the workspaces' records of it, and has not recorded a verdict.
// Those records are prior interpretations, which the protocol shows only after the verdict.
export function holdsBack(order, u, draft) {
  return order === "informed" && draft?.stage === "compare"
    && (u.priority?.signals || []).some((s) => WORKSPACE_SIGNALS.includes(s.kind))
    && !(draft.revealed_by || []).some((s) => s.unit === ORDER_SEEN);
}

const EMPTY = () => ({ reviewer: null, drafts: {}, reports: [], skipped: [], exported: 0, exposure: [] });

function storeKey(project) {
  return `prooflens-review:${project || "project"}`;
}

export function loadWork(project) {
  try {
    const raw = localStorage.getItem(storeKey(project));
    return raw ? { ...EMPTY(), ...JSON.parse(raw) } : EMPTY();
  } catch {
    return EMPTY();
  }
}

// Returns false when the browser would not keep it (private window, storage off): the page then
// says so, and the reviewer should export after every report.
export function saveWork(project, work) {
  try {
    localStorage.setItem(storeKey(project), JSON.stringify(work));
    return true;
  } catch {
    return false;
  }
}

export function now() {
  return new Date().toISOString().replace(/\.\d+Z$/, "Z");
}

// The reviewer id of the protocol: `human:<name>` for a person, `llm:<model>-<date>` for a model.
export function reviewerId(r) {
  if (!r) return "";
  const slug = (s) => String(s || "").trim().replace(/\s+/g, "-");
  if (r.kind === "model") return `llm:${slug(r.model)}-${new Date().toISOString().slice(0, 10)}`;
  return `human:${slug(r.name)}`;
}

export function needsDetail(verdict) {
  return [...Object.values(VERDICTS).flat(), ...Object.values(STEP_VERDICTS).flat()]
    .find((v) => v.value === verdict)?.detail || null;
}

// The kind of issue each verdict's draft is: a note explaining an accepted difference, a defect
// the reviewer found, or a question the reviewer could not decide. A faithful verdict, or one
// this table does not know, has no draft. The command line writes the same drafts
// (`review_cli.issue_draft`).
const DRAFT_KIND = {
  "faithful with representation choices": "explanatory note",
  broader: "explanatory note",
  ...Object.fromEntries(VERDICTS.problem.map((v) => [v.value, "defect"])),
  "cannot determine": "unresolved question",
};
const UNRESOLVED_BODY = "The reviewer could not determine whether the Lean statement says what the "
  + "paper says; this is an open question.";

export function issueDraft(unit, verdict, detail) {
  if (unit.kind === "step") return stepIssueDraft(unit, verdict, detail);
  const kind = Object.hasOwn(DRAFT_KIND, verdict) ? DRAFT_KIND[verdict] : null;
  if (!kind) return null;
  const claims = unit.claims.map((c) => c.number || c.id).join(", ");
  const suffix = claims ? ` (${claims})` : "";
  const text = String(detail || "").trim();
  if (kind === "unresolved question") {
    return {
      kind, title: `${unit.name}: open question${suffix}`,
      body: `Review unit \`${unit.id}\`, verdict **${verdict}**. ${UNRESOLVED_BODY}`
        + (text ? `\n\n**Open question.** ${text}` : ""),
    };
  }
  return {
    kind, title: `${unit.name}: ${verdict}${suffix}`,
    body: `Review unit \`${unit.id}\`, verdict **${verdict}**.\n\n${text}`.trim(),
  };
}

// An issue about a proof step names the step, its proof and the question it answers: a finding
// on the printed step, never on the enclosing statement (as `review_cli.step_issue_draft`).
export function stepIssueDraft(unit, verdict, detail) {
  if (verdict === "holds as printed") return null;
  const par = unit.parent?.number || unit.parent?.id || "";
  const kind = { "false as printed": "finding on a proof step", "holds, with a gap in the argument": "explanatory note",
                 "cannot determine": "unresolved question" }[verdict] || "finding on a proof step";
  return {
    kind,
    title: `${unit.name}${par ? ` in the proof of ${par}` : ""}: ${verdict}`,
    body: `Review unit \`${unit.id}\` (a proof step, not the statement of ${par || "its result"}), verdict **${verdict}**.\n\n${detail || ""}`.trim(),
  };
}

export function buildReport({ index, unit, draft, reviewer }) {
  const papers = Object.fromEntries((index.papers || []).map((p) => [p.id, p.revision || null]));
  const verdict = draft.verdict;
  return {
    schema: REPORT_SCHEMA,
    unit: { id: unit.id, kind: unit.kind, name: unit.name,
            lean: unit.kind === "step" ? unit.lean || [] : unit.lean || [unit.name],
            claims: unit.claims.map((c) => c.id), papers: unit.papers || [],
            ...(unit.kind === "step" ? { target: unit.unit, parent: unit.parent || null, route: unit.route || [] } : {}) },
    pins: {
      release: index.release,
      project_commit: index.project?.commit || null,
      manuscripts: Object.fromEntries((unit.papers || []).map((p) => [p, papers[p] ?? null])),
      legacy_hash: unit.legacy_hash || null,
      fingerprint: unit.fingerprint || null,
      fingerprints: unit.fingerprints || null,
      // The digests of the paper passages shown when the reading was locked.
      source_sha256: draft.source_sha256 ?? null,
    },
    reviewer: {
      id: reviewerId(reviewer), kind: reviewer.kind, name: reviewer.name || null,
      model: reviewer.kind === "model" ? reviewer.model : null,
      same_family_as_author: reviewer.sameFamily || "unknown",
      identity: "self-declared",
    },
    // The units whose Lean or author's review this reviewer had seen, in this browser, before
    // locking this reading: empty when the reading was blind as far as the page can tell.
    reading: { text: draft.reading, locked_at: draft.locked_at, revealed_by: draft.revealed_by || [] },
    comparison: { text: draft.comparison || "", witness: draft.witness || "",
                  checklist: draft.checklist || {}, decided_at: draft.decided_at },
    verdict: { group: draft.group, value: verdict, detail: draft.detail || "" },
    author_review: { shown_at: draft.author_shown_at, disagreements: draft.disagreements || "none" },
    submitted_at: now(),
    issue_draft: issueDraft(unit, verdict, draft.detail),
  };
}

export function exportFile(index, work) {
  const body = {
    schema: "prooflens/review-reports@1", project: index.project?.name || null,
    release: index.release, exported_at: now(), reports: work.reports,
  };
  const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  const who = (work.reports.at(-1)?.reviewer?.id || "reviewer").replace(/[^\w.-]+/g, "_");
  a.href = URL.createObjectURL(blob);
  a.download = `machinechecked-reviews-${who}-${body.exported_at.replace(/[:]/g, "")}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
