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

// The reviewer's coverage, recorded with the verdict: how far the unit's Lean states the claim
// (the links file's words), and separately how that is supported. A verdict allows the coverage
// that agrees with it (`review_cli.COVERAGE_FOR`); with "Cannot determine" it is unresolved, and
// the verdict's detail is the open question.
export const COVERAGE_FOR = {
  matches: ["full", "partial"],
  problem: ["partial", "changed", "related"],
  cannot: ["unresolved"],
};
export const COVERAGE_CHOICES = [
  { value: "full", label: "Every clause" },
  { value: "partial", label: "Part of the claim" },
  { value: "changed", label: "States it differently" },
  { value: "related", label: "A related result, not this claim" },
  { value: "unresolved", label: "Unresolved" },
];
export const BASIS_CHOICES = [
  { value: "direct", label: "In one Lean statement" },
  { value: "reviewed_composition", label: "By my composition of these results" },
  { value: "checked_bridge", label: "Through a checked bridge" },
];
const COVERAGE = COVERAGE_CHOICES.map((c) => c.value);
const BASIS = BASIS_CHOICES.map((b) => b.value);
const ARGUMENT_CHARS = 8000;
const NOTE_CHARS = 2000;

export function verdictGroup(unit, verdict) {
  const table = unit?.kind === "step" ? STEP_VERDICTS : VERDICTS;
  return Object.keys(table).find((g) => table[g].some((v) => v.value === verdict)) || null;
}

const isObject = (v) => v != null && typeof v === "object" && !Array.isArray(v);

// `{correspondence, problems}`: the coverage a report records beside the verdict, and what is
// wrong with `given` (`{coverage, basis, argument, bridge, would_decide}`), as the command line's
// `review_cli.correspondence` says: a basis needs a coverage, an argument belongs to a reviewed
// composition, a bridge (one of the unit's theorems, and its target) to a checked bridge, and what
// would decide it to an unresolved coverage. Null when nothing is given; a proof step records none.
export function reportCorrespondence(unit, verdict, given) {
  given = isObject(given) ? given : {};
  const why = [];
  const text = (v, what) => {
    if (v == null || typeof v === "string") return (v || "").trim();
    why.push(`${what} is not text`);
    return "";
  };
  const cov = text(given.coverage, "the coverage"), basis = text(given.basis, "the basis");
  const argument = text(given.argument, "the argument");
  const would = text(given.would_decide, "what would decide it");
  if (given.bridge != null && !isObject(given.bridge)) why.push("a bridge is {theorem, target}");
  const b = isObject(given.bridge) ? given.bridge : {};
  const bridge = { theorem: text(b.theorem, "the bridge's theorem"), target: text(b.target, "the bridge's target") };
  if (!(cov || basis || argument || would || bridge.theorem || bridge.target)) return { correspondence: null, problems: why };
  const out = { coverage: cov || null };
  if (unit?.kind === "step") why.push("a review of a proof step records whether the step holds, not a coverage");
  if (cov && !COVERAGE.includes(cov)) why.push(`coverage '${cov}' is not one of: ${COVERAGE.join(", ")}`);
  const group = verdictGroup(unit, verdict);
  if (COVERAGE.includes(cov) && COVERAGE_FOR[group] && !COVERAGE_FOR[group].includes(cov)) {
    why.push(`coverage '${cov}' does not agree with the verdict '${verdict}': with it the coverage is ${COVERAGE_FOR[group].join(" or ")}`);
  }
  if (basis) {
    out.basis = basis;
    if (!BASIS.includes(basis)) why.push(`basis '${basis}' is not one of: ${BASIS.join(", ")}`);
    if (!cov) why.push("a basis says how a coverage is supported: give the coverage too");
  }
  if (argument) {
    out.argument = argument;
    if (basis !== "reviewed_composition") why.push("an argument belongs to a reviewed composition (basis reviewed_composition)");
    if (argument.length > ARGUMENT_CHARS) why.push(`the argument is longer than ${ARGUMENT_CHARS} characters`);
  }
  if ((bridge.theorem || bridge.target) && basis !== "checked_bridge") why.push("a bridge belongs to a checked bridge (basis checked_bridge)");
  if (basis === "checked_bridge") {
    const lean = Array.isArray(unit?.lean) && unit.lean.length ? unit.lean : [unit?.name];
    if (!(bridge.theorem && bridge.target)) why.push("a checked bridge names its theorem and its target");
    else if (!lean.includes(bridge.theorem)) why.push(`the bridge theorem ${bridge.theorem} is not one of the unit's declarations (${lean.join(", ")})`);
    // The version of the target the reviewer was shown, when the build checks this bridge.
    const pin = b.target_fingerprint;
    out.bridge = { ...bridge, target_fingerprint: typeof pin === "string" && pin ? pin : null };
  }
  if (would) {
    out.would_decide = would;
    if (cov !== "unresolved") why.push("what would decide it belongs to an unresolved coverage");
    if (would.length > NOTE_CHARS) why.push(`what would decide it is longer than ${NOTE_CHARS} characters`);
  }
  return { correspondence: out, problems: why };
}

// The coverage fields of the review page's draft as the reviewer has chosen them: a field the
// chosen coverage or basis does not have is left out.
export function draftCoverage(draft) {
  const cov = draft?.coverage || null;
  const basis = cov ? draft.basis || null : null;
  return {
    coverage: cov, basis,
    argument: basis === "reviewed_composition" ? draft.argument || null : null,
    bridge: basis === "checked_bridge" ? draft.bridge || null : null,
    would_decide: cov === "unresolved" ? draft.would_decide || null : null,
  };
}

// The recorded coverage in words, for the reviewer's own record of it.
export function coverageWords(cor) {
  const c = COVERAGE_CHOICES.find((x) => x.value === cor?.coverage);
  if (!c) return null;
  const b = BASIS_CHOICES.find((x) => x.value === cor.basis);
  return c.label + (b ? ", " + b.label.toLowerCase() : "");
}

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
  + "paper says. This is an open question, not a difference that was found.";

// An open question carries what would decide it, when the report's coverage (`cor`) says.
export function issueDraft(unit, verdict, detail, cor = null) {
  if (unit.kind === "step") return stepIssueDraft(unit, verdict, detail);
  const kind = Object.hasOwn(DRAFT_KIND, verdict) ? DRAFT_KIND[verdict] : null;
  if (!kind) return null;
  const claims = unit.claims.map((c) => c.number || c.id).join(", ");
  const suffix = claims ? ` (${claims})` : "";
  const text = String(detail || "").trim();
  if (kind === "unresolved question") {
    const would = String(cor?.would_decide || "").trim();
    return {
      kind, title: `${unit.name}: open question${suffix}`,
      body: `Review unit \`${unit.id}\`, verdict **${verdict}**. ${UNRESOLVED_BODY}`
        + (text ? `\n\n**Open question.** ${text}` : "")
        + (would ? `\n\n**Would decide it.** ${would}` : ""),
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
    // Recorded with the verdict (`reportCorrespondence`); null when the reviewer recorded no coverage.
    correspondence: draft.correspondence ?? null,
    author_review: { shown_at: draft.author_shown_at, disagreements: draft.disagreements || "none" },
    submitted_at: now(),
    issue_draft: issueDraft(unit, verdict, draft.detail, draft.correspondence ?? null),
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
