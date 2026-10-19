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
    { value: "cannot determine", label: "Cannot determine", detail: "Say what would decide it." },
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

const EMPTY = () => ({ reviewer: null, drafts: {}, reports: [], skipped: [], exported: 0 });

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

// An issue the maintainer may file. A representation choice or a broader statement is a note
// explaining an accepted difference; the other verdicts other than faithful describe a defect.
export function issueDraft(unit, verdict, detail) {
  if (unit.kind === "step") return stepIssueDraft(unit, verdict, detail);
  if (verdict === "faithful") return null;
  const note = verdict === "faithful with representation choices" || verdict === "broader";
  const claims = unit.claims.map((c) => c.number || c.id).join(", ");
  return {
    kind: note ? "explanatory note" : "defect",
    title: `${unit.name}: ${verdict}${claims ? ` (${claims})` : ""}`,
    body: `Review unit \`${unit.id}\`, verdict **${verdict}**.\n\n${detail || ""}`.trim(),
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
