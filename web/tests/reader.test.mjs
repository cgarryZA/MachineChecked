// Browser tests of the built reader (engine/python/prooflens/web), in headless Chromium, at a
// laptop and a phone width. Run after `npm run build`: `node tests/reader.test.mjs`.
// Set CHROMIUM to a browser binary when Playwright's own is not installed, SHOTS to a directory
// to keep screenshots, and ONLY to a regular expression to run only the checks it matches.
//
// A paper page with two formalisations, written by the engine: the chosen project must drive
// every claim view, and the two projects' links must never show together. Needs the engine
// importable (`pip install -e .`); set PYTHON to choose the interpreter.
//
// The claim inspector is tested on the toy example's audit data (tests/fixtures/toy/data), as
// the engine exported it, served with the current reader. To refresh it after a change to the
// data format: `machinechecked build && machinechecked export --out OUT` in a copy of
// examples/toy-paper, then copy OUT/data there.

import "./presentation.test.mjs";
import "./review.test.mjs";
import "./coverage.test.mjs";
import "./retrieval.test.mjs";
import "./comparison.test.mjs";
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { GLOSS, gloss } from "../src/lib/gloss.js";

// Every plain-English note: a full Lean name, one short sentence or two, nothing about proofs.
for (const [name, text] of Object.entries(GLOSS)) {
  assert.match(name, /^[A-Z][\w.]*$/, `gloss key ${name}`);
  assert.ok(text.length > 10 && text.length <= 220 && /[.)]$/.test(text), `gloss of ${name}: ${text}`);
  assert.ok(!/verif|proved|proof|checked|correct/i.test(text), `gloss of ${name} speaks of proof`);
}
assert.equal(gloss("No.Such.Name"), null);
assert.equal(gloss("toString"), null, "only the table's own entries");

const here = path.dirname(fileURLToPath(import.meta.url));
const reader = path.resolve(here, "../../engine/python/prooflens/web");
const A = "alpha/project-a", B = "beta/project-b";

// The paper page is written by the engine (`prooflens.paper.write_paper_site`), as machinechecked.org
// writes its paper pages, so the test reads exactly the data a real page has.
const FIXTURE = String.raw`
import json, sys
from pathlib import Path
from prooflens.paper import claim_map, paper_claims, write_paper_site
A, B = "alpha/project-a", "beta/project-b"
def anchor(env, number, page, y0):
    return {"env": env, "number": number, "title": None, "begin": [page, 0, y0], "end": [page, 0, y0 + 40]}
def fy(rows):
    return {"sources": [{"title": "A paper with two formalisations", "relationship": "formalizes"}],
            "alignment": {"statements": [{"source": f"{k} {n}", "lean": names} for k, n, names in rows]}}
paper = {"id": "arxiv:2601.00001", "title": "A paper with two formalisations", "authors": ["A. Author"],
         "links": {}, "formalisations": [
             {"repository": A, "commit": "a" * 40, "stated_by": {"source": "formalization.yaml"},
              "report_url": "https://github.com/cgarryZA/machinechecked.org/issues/new?title=x"},
             {"repository": B, "commit": "b" * 40, "stated_by": {"source": "formalization.yaml"}}]}
anchors = [anchor("theorem", "1", 1, 100), anchor("theorem", "2", 1, 300),
           anchor("theorem", "3", 2, 100), anchor("lemma", "4", 2, 300)]
claims = paper_claims(anchors, paper["title"], [
    (paper["formalisations"][0], fy([("theorem", "1", ["A.Some.Rather.Long.Namespace.with_a_declaration_name_long_enough_to_overflow_a_phone"]), ("theorem", "3", ["A.three"])])),
    (paper["formalisations"][1], fy([("theorem", "2", ["B.two"]), ("theorem", "3", ["B.three"])]))])
write_paper_site(Path(sys.argv[1]), paper, claims, [612, 792], None, Path(sys.argv[2]))

# A long paper (30 pages), with statements early, in the middle and late, and its PDF.
def pdf(pages, text="Searchable paper page {n}. Alpha theorem."):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(pages)) +
            f"] /Count {pages} >>"]
    font = 3 + 2 * pages
    annot = font + 1
    objs += [f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {3 + pages + i} 0 R /Annots [{annot} 0 R] >>" for i in range(pages)]
    for i in range(pages):
        content = f"BT /F1 14 Tf 60 700 Td ({text.format(n=i + 1)}) Tj ET"
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objs.append("<< /Type /Annot /Subtype /Link /Rect [60 660 180 680] /A << /S /URI /URI (https://example.org/paper) >> >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
long_paper = {**paper, "id": "arxiv:2601.00002", "title": "A long paper", "formalisations": []}
long_claims = paper_claims([anchor("theorem", "2", 2, 300), anchor("theorem", "15", 15, 400),
                            anchor("theorem", "28", 28, 200)], long_paper["title"], [])
long_claims[0]["anchor"]["end"] = [3, 0, 150]
site = Path(sys.argv[1]).parent / "long"
write_paper_site(site, long_paper, long_claims, [612, 792], "paper.pdf", Path(sys.argv[2]))
(site / "paper.pdf").write_bytes(pdf(30))

# A long paper whose many claims have titles with mathematics, so the contents list is far taller
# than the window and holds KaTeX's absolutely positioned MathML.
tall_paper = {**paper, "id": "arxiv:2601.00004", "title": "A paper with many titled claims", "formalisations": []}
tall_anchors = [{**anchor("theorem", str(i), 1 + i // 2, 100 + 300 * (i % 2)), "title": f"Bound on $x_{{{i}}}^2 + \\sum_k a_k$"}
                for i in range(1, 61)]
tall_claims = paper_claims(tall_anchors, tall_paper["title"], [])
site = Path(sys.argv[1]).parent / "tall"
write_paper_site(site, tall_paper, tall_claims, [612, 792], "paper.pdf", Path(sys.argv[2]))
(site / "paper.pdf").write_bytes(pdf(31))

# A paper in two versions, one page each (as machinechecked.org writes them): arXiv v1, and the
# latest manuscript at a commit, whose claims are numbered differently and linked differently.
# Project A has an audit of each version (#42): the panel names each one's version and commit.
two = {**paper, "id": "arxiv:2601.00003", "title": "A paper in two versions",
       "formalisations": [{**paper["formalisations"][0], "audits": [
           {"url": "https://audit.example/a/v1/", "author": "A. Author"},
           {"url": "https://audit.example/a/latest", "author": "A. Author"}]},
                          paper["formalisations"][1]]}
versions = [{"id": "arxiv:2601.00003v1", "kind": "published", "href": "/versions/v1/",
             "pdf": "https://arxiv.org/pdf/2601.00003v1", "audits": [
                 {"url": "https://audit.example/a/v1/", "author": "A. Author", "repository": A, "commit": "1" * 40}]},
            {"id": "manuscript:abc1234", "kind": "manuscript", "revision": "abc1234" + "0" * 33,
             "href": "../latest/", "label": "arXiv v2", "audits": [
                 {"url": "https://audit.example/a/latest/", "author": "A. Author", "repository": A, "commit": "2" * 40}]}]
pages = {"v1": ([anchor("theorem", "1", 1, 100), anchor("theorem", "2", 1, 300),
                 anchor("theorem", "3", 1, 500)],
                [("theorem", "1", ["A.one"])], [("theorem", "2", ["B.two"])], "Version one text."),
         "latest": ([anchor("lemma", "1", 1, 100), anchor("theorem", "2", 1, 300),
                     anchor("theorem", "3", 1, 500)],
                    [("theorem", "3", ["A.three"])], [], "Latest manuscript text.")}
# The claim map between them (#225), from the two inventories: v1's Theorem 1 is the latest
# Theorem 3 with its statement changed (the same label), Theorem 2 became Lemma 1 (the same
# statement), Theorem 3 was removed, and the latest Theorem 2 is new (each has a label the other
# version lacks, so a removal and an addition are certain, #296).
inventory = {"v1": [("theorem-1", "Theorem 1", "thm:bound", "A bound."),
                    ("theorem-2", "Theorem 2", None, "An identity."),
                    ("theorem-3", "Theorem 3", "rem:old", "A remark.")],
             "latest": [("lemma-1", "Lemma 1", None, "An identity."),
                        ("theorem-2", "Theorem 2", "thm:new", "Another identity."),
                        ("theorem-3", "Theorem 3", "thm:bound", "A sharper bound.")]}
claim_maps = [claim_map(versions[0]["id"], [{"key": k, "number": n, "label": l, "statement": t}
                                            for k, n, l, t in inventory["v1"]],
                        versions[1]["id"], [{"key": k, "number": n, "label": l, "statement": t}
                                            for k, n, l, t in inventory["latest"]])]
for (name, (anchors, a_rows, b_rows, text)), v in zip(pages.items(), versions):
    site = Path(sys.argv[1]).parent / "versions" / name
    cl = paper_claims(anchors, two["title"], [(two["formalisations"][0], fy(a_rows)),
                                              (two["formalisations"][1], fy(b_rows))])
    write_paper_site(site, two, cl, [612, 792], "paper.pdf", Path(sys.argv[2]), audits={},
                     versions=versions, version=v["id"], claim_maps=claim_maps)
    (site / "paper.pdf").write_bytes(pdf(1, text))
    # On v1, project A's audit pins the version without pinning every claim; B's checks it.
    if name == "v1":
        idx = json.loads((site / "data" / "index.json").read_text())
        rec = {"kind": "published", "id": v["id"], "label": "arXiv v1"}
        idx["audits"] = {two["formalisations"][0]["repository"]: {"paper_version": {**rec, "checked": False}},
                         two["formalisations"][1]["repository"]: {"paper_version": {**rec, "checked": True}}}
        (site / "data" / "index.json").write_text(json.dumps(idx))
`;
const root = fs.mkdtempSync(path.join(os.tmpdir(), "mc-reader-"));
const made = spawnSync(process.env.PYTHON || "python3", ["-c", FIXTURE, path.join(root, "paper"), reader], { encoding: "utf8" });
if (made.status !== 0) throw new Error("the engine could not write the paper page:\n" + made.stderr);
fs.cpSync(reader, path.join(root, "toy"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "toy", "data"), path.join(root, "toy", "data"), { recursive: true });
const TOY = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "toy", "data", "index.json"), "utf8"));
fs.writeFileSync(path.join(root, "toy/audit.json"), JSON.stringify({ schema: "machinechecked/audit@1", data: "data/index.json", author: "A. Author" }));
// A synthetic statement with some shape (tests/fixtures/structure, regenerated by
// fixtures/make_structure.py): objects with their own conditions, a shared condition, an
// alternating prefix and a conjunction.
fs.cpSync(reader, path.join(root, "structure"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "structure", "data"), path.join(root, "structure", "data"), { recursive: true });
const SHAPE = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "structure", "data", "index.json"), "utf8"));
// Where a declaration is used (#144): the synthetic project tests/fixtures/uses, regenerated by
// fixtures/make_uses.py with the answers its local server gives.
fs.cpSync(reader, path.join(root, "uses"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "uses", "data"), path.join(root, "uses", "data"), { recursive: true });
const USES = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "uses", "data", "index.json"), "utf8"));
// The same claims with auditors' readings in the form the engine writes them (#138; see
// tests/simple/test_coverage_basis.py): full by composition, full through a checked bridge, and
// an unresolved question.
fs.cpSync(path.join(root, "structure"), path.join(root, "basis"), { recursive: true });
const READINGS = {
  "P:thm:layout": { coverage: "full", basis: "reviewed_composition", refs: ["Shape.layout"],
                    argument: "Apply Shape.layout twice, once for each bound." },
  "P:thm:witnesses": { coverage: "full", basis: "checked_bridge", refs: ["Shape.witnesses"],
                       bridge: { theorem: "Shape.witnesses", target: "Shape.Spec.witnesses", state: "checked", reasons: [],
                                 pinned: {}, current: {} } },
  "P:thm:shapes": { coverage: "unresolved", question: "Is the paper's set finite?", would_decide: "Its Section 1." },
};
// And reviewers' reports with the coverage recorded with their verdicts, as `simple.review_view`
// shows them: a checked bridge the engine reads as the reviewer's composition, and an unresolved
// coverage whose question is the verdict's detail.
const REPORT = (verdict, correspondence) => ({
  reviewer: { id: "human:B-Reviewer", kind: "human", name: "B. Reviewer", identity: "self-declared" },
  verdict, reading: "A synthetic reading.", comparison: "A synthetic comparison.", checklist: {},
  locked_at: "2026-01-01T00:00:00Z", submitted_at: "2026-01-01T00:05:00Z", reviewed: ["Shape.layout"],
  current: true, correspondence: { refs: [], argument: null, next_step: null, bridge: null, question: null, would_decide: null, ...correspondence } });
const REPORTS = {
  "P:thm:layout": [REPORT({ group: "matches", value: "faithful", detail: "" },
    { coverage: "full", basis: "reviewed_composition", refs: ["Shape.layout"], next_step: "State the combination as one Lean result.",
      recorded_basis: "checked_bridge", basis_reason: ["the target is not the version the reviewer read"],
      bridge: { theorem: "Shape.layout", target: "Shape.Spec.layout" } })],
  "P:thm:shapes": [REPORT({ group: "cannot", value: "cannot determine", detail: "Is the set finite?" },
    { coverage: "unresolved", basis: null, question: "Is the set finite?", would_decide: "Its Section 1." })],
};
for (const c of SHAPE.claims) {
  const f = path.join(root, "basis", "data", "claims", c.file);
  const chunk = JSON.parse(fs.readFileSync(f, "utf8"));
  chunk.correspondence = { source: "confirmed", basis: null, refs: [], argument: null, bridge: null, question: null,
                           would_decide: null, confidence: null, note: "", by: "A. Auditor", ...READINGS[c.id] };
  chunk.reviews = REPORTS[c.id] || [];
  fs.writeFileSync(f, JSON.stringify(chunk));
}

// Synthetic display excerpts as the engine writes them (fixtures/make_excerpt.py).
const excerpts = spawnSync(process.env.PYTHON || "python3", [path.join(here, "fixtures", "make_excerpt.py")], { encoding: "utf8" });
if (excerpts.status !== 0) throw new Error(excerpts.stderr);
const EXCERPTS = JSON.parse(excerpts.stdout);

const states = spawnSync(process.env.PYTHON || "python3", [path.join(here, "fixtures", "make_status.py"), root, reader], { encoding: "utf8" });
if (states.status !== 0) throw new Error(states.stderr);

const publication = spawnSync(process.env.PYTHON || "python3", [path.join(here, "../../tests/published_fixture.py"), path.join(root, "published"), reader], { encoding: "utf8" });
if (publication.status !== 0) throw new Error(publication.stderr);
const PUB = JSON.parse(fs.readFileSync(path.join(root, "published/data/index.json")));
// A paper page that joined a statement of its PDF to the audit's entry by printed number, as
// machinechecked.org writes it when it cannot show the PDF the audit read (`matched`); and the
// same page with a match that names the revision the audit read and no version.
const MATCHED = JSON.parse(fs.readFileSync(path.join(root, "matched/data/index.json")));
fs.cpSync(path.join(root, "matched"), path.join(root, "matched-revision"), { recursive: true });
{
  const dir = path.join(root, "matched-revision", "data");
  const unlabelled = (c) => { delete c.by_project["synthetic/alpha"].audit.matched.version; return c; };
  const idx = structuredClone(MATCHED);
  const row = idx.claims.find((c) => c.by_project?.["synthetic/alpha"]?.audit?.matched);
  unlabelled(row);
  fs.writeFileSync(path.join(dir, "index.json"), JSON.stringify(idx));
  const f = path.join(dir, "claims", row.file);
  fs.writeFileSync(f, JSON.stringify(unlabelled(JSON.parse(fs.readFileSync(f, "utf8")))));
}

// A synthetic review queue with a reviewed target after an unrelated pending unit.
fs.cpSync(path.join(root, "toy"), path.join(root, "review"), { recursive: true });
const reviewIndex = structuredClone(TOY);
reviewIndex.review_queue = "data/review-queue.json";
const reviewUnits = ["T:thm:bound", "T:thm:even-add"].map((id, i) => {
  const c = TOY.claims.find((c) => c.id === id);
  const claim = JSON.parse(fs.readFileSync(path.join(root, "toy/data/claims", c.file)));
  return { id: `spec:${claim.clauses[0].spec}`, kind: "spec", name: claim.clauses[0].spec,
    state: i ? "reviewed" : "pending", reason: "Synthetic review", fingerprint: "synthetic-" + i,
    claims: [{ id }], papers: ["T"], paper: "T", section: "2", reveals: { lean: [], author: [] },
    author_review: [{ by: "Synthetic author", text: "Synthetic author review kept until the verdict." }] };
});
fs.writeFileSync(path.join(root, "review/data/index.json"), JSON.stringify(reviewIndex));
fs.writeFileSync(path.join(root, "review/data/review-queue.json"), JSON.stringify({ authors: ["Synthetic author"], needs_statement: [], units: reviewUnits }));

// A review queue holding one proof step with no Lean link, as the engine writes it.
fs.cpSync(path.join(root, "toy"), path.join(root, "review-step"), { recursive: true });
const stepRow = TOY.claims.find((c) => c.id === "T:eq:bound-range");
const stepChunk = JSON.parse(fs.readFileSync(path.join(root, "toy/data/claims", stepRow.file)));
fs.writeFileSync(path.join(root, "review-step/data/index.json"), JSON.stringify(reviewIndex));
fs.writeFileSync(path.join(root, "review-step/data/review-queue.json"), JSON.stringify({ authors: [], needs_statement: [], units: [{
  id: "step:T:eq:bound-range", kind: "step", unit: "proof-equation", name: "Equation (3)", lean: [],
  route: ["Toy.Acceptance.thm_bound"], fingerprints: { source: stepChunk.source_sha256 },
  parent: { id: "T:thm:bound", number: "Theorem 2.5" }, state: "pending", reason: "Proof step of Theorem 2.5; no Lean is linked to it",
  claims: [{ id: "T:eq:bound-range" }], papers: ["T"], paper: "T", section: "2", author_review: [] }] }));

// The toy example's review queue as the engine builds it from the audit's data, with the paper's
// order (#128): `queueFor(DATA)` writes it beside the data and names it in the index.
const QUEUE = String.raw`
import json, sys
from pathlib import Path
from prooflens import review_queue as rq
d = Path(sys.argv[1])
index = json.loads((d / "index.json").read_text())
chunks = {c["file"]: json.loads((d / "claims" / c["file"]).read_text()) for c in index["claims"]}
store = {p.stem: json.loads(p.read_text()) for p in (d / "decls").glob("*.json")}
q = rq.prioritise(rq.assurance_queue(index, chunks, store, []), claims=index["claims"])
(d / "review-queue.json").write_text(json.dumps(q))
(d / "index.json").write_text(json.dumps({**index, "review_queue": "data/review-queue.json"}))
print(json.dumps(q))`;
function queueFor(data) {
  const r = spawnSync(process.env.PYTHON || "python3", ["-c", QUEUE, data], { encoding: "utf8" });
  if (r.status !== 0) throw new Error("the engine could not build the review queue:\n" + r.stderr);
  return JSON.parse(r.stdout);
}
fs.cpSync(path.join(root, "toy"), path.join(root, "review-order"), { recursive: true });
const ORDER_QUEUE = queueFor(path.join(root, "review-order", "data"));
const REVIEW_KEY = "prooflens-review:toy-paper";
const kindWord = (u) => ({ def: "Definition", link: "Linked claim", step: "Proof step" })[u.kind] || "Statement";
const whyIs = (pg, text) => pg.waitForFunction((t) => document.querySelector(".review .unit .why")?.textContent === t, text)
  .catch(async (e) => { throw new Error(`the card's reason is ${JSON.stringify(await pg.locator(".review .unit .why").textContent())}, not ${JSON.stringify(text)}`); });

// The same review queue on a build that holds the step's context in the proof only in part, as
// the engine records it (`context_cut`), and one whose evidence predates the record of where.
for (const [dir, cut] of [["cut-step", { file: "toy.tex", line: 71, end_line: 80, kept: 20000, chars: 28000 }], ["cut-step-old", { kept: 20000 }]]) {
  fs.cpSync(path.join(root, "review-step"), path.join(root, dir), { recursive: true });
  fs.writeFileSync(path.join(root, dir, "data/claims", stepRow.file), JSON.stringify({ ...stepChunk, context_cut: cut }));
}

// The toy audit with an auditor's published workspace records on Definition 1.1, in the form
// `published_work.py` writes them: the passport names their file.
fs.cpSync(path.join(root, "toy"), path.join(root, "toywork"), { recursive: true });
const workRow = TOY.claims.find((c) => c.id === "T:def:even");
const workPath = path.join(root, "toywork/data/claims", workRow.file);
fs.writeFileSync(workPath, JSON.stringify({ ...JSON.parse(fs.readFileSync(workPath)), work: "work/" + workRow.file }));
fs.mkdirSync(path.join(root, "toywork/data/work"), { recursive: true });
const cur = { state: "current", changes: [] };
fs.writeFileSync(path.join(root, "toywork/data/work", workRow.file), JSON.stringify({
  schema: "prooflens/published-work@1", release: TOY.release, claim: "T:def:even", readings: [{
    workspace: "ws-111111111111", mode: "independent", reviewer: { id: "llm:synthetic-model", kind: "model", model: "synthetic-model", identity: "self-declared" },
    requirements: [{ id: "q1", kind: "requirement", claim: "T:def:even", local_id: "even", form: "definition", text: "n is even when n = 2k", depth: 0, currency: cur }],
    fragments: [{ id: "p1", kind: "fragment", claim: "T:def:even", requirement: "even", role: "statement", origin: "printed", state: "accepted",
                  state_by: "llm:synthetic-model", region: { paper: "T", file: "toy.tex", start_line: 12, end_line: 12, sha256: "x", text: "A synthetic printed sentence." }, currency: cur }],
    alignments: [{ id: "a1", kind: "alignment", claim: "T:def:even", requirements: ["even"], relation: "corresponds",
                   lean: [{ decl: "Toy.IsEven" }], created_by: "llm:synthetic-model", currency: { state: "stale", changes: [{ decl: "Toy.IsEven", was: "a", now: "b" }] } },
                 { id: "a2", kind: "alignment", claim: "T:def:even", requirements: ["even"], fragments: ["p1"], relation: "corresponds",
                   lean: [{ decl: "Toy.IsEven", at: "/1/1/1/0/0/0", target: "n = 2 * k" }, { decl: "Toy.IsEven", var: 0, target: "n" }],
                   created_by: "llm:synthetic-model", currency: cur },
                 { id: "a3", kind: "alignment", claim: "T:def:even", requirements: ["even"], fragments: ["p-gone"], relation: "corresponds",
                   lean: [{ decl: "Toy.IsEven" }], created_by: "llm:synthetic-model",
                   currency: { state: "stale", changes: [{ fragment: "p-gone", was: "accepted", now: "missing" }] } }],
    findings: [
      { id: "f-c1", kind: "finding", claim: "T:def:even", coverage: "partial", basis: "reviewed_composition", composition: "c-1",
        state: "submitted", submitted_at: "2026-10-20T00:00:00Z", created_by: "llm:synthetic-model", evidence: [], in_force: true, currency: cur },
      { id: "f-c2", kind: "finding", claim: "T:def:even", coverage: "full", basis: "checked_bridge", composition: "c-2",
        state: "submitted", submitted_at: "2026-10-20T00:00:00Z", created_by: "llm:synthetic-model", evidence: [], in_force: true, currency: cur },
      { id: "f-c3", kind: "finding", claim: "T:def:even", coverage: "full", basis: "reviewed_composition", recorded_basis: "checked_bridge",
        basis_reason: ["Lean finds no such theorem"], bridge: { theorem: "Toy.no_such_bridge", target: "Toy.Spec.synthetic" },
        bridge_check: { state: "unchecked", reasons: ["Lean finds no such theorem"] },
        state: "submitted", submitted_at: "2026-10-20T00:00:00Z", created_by: "llm:synthetic-model", evidence: [], in_force: true, currency: cur }],
    evidence: [{ id: "e-1", kind: "evidence", claim: "T:def:even", role: "supports", ref: { decl: "Toy.IsEven" }, currency: cur },
               { id: "e-2", kind: "evidence", claim: "T:def:even", role: "supports",
                 ref: { app: { callee: "Toy.even_add", id: "app:Toy.synthetic:0", caller: "Toy.synthetic", app_hash: "x" } }, currency: { state: "unchecked", changes: [] } }],
    compositions: [
      { id: "c-1", kind: "composition", claim: "T:def:even", coverage: "partial", basis: "reviewed_composition", created_by: "llm:synthetic-model",
        steps: [{ id: "s1", establishes: "SYNTHETIC-STEP: some n is even", uses: ["e-1"] },
                { id: "s2", establishes: "some m is even", uses: ["e-2"], substitutions: [{ variable: "a", value: "m" }] }],
        obligations: [{ id: "o1", kind: "compatible witnesses", state: "open", text: "n and m may differ" }],
        evidence: ["e-1", "e-2"], gaps: { requirements: 1, uncovered: ["even"], open: ["o1"] }, complete: false,
        next_step: "State the combination as one Lean result.", currency: cur },
      { id: "c-2", kind: "composition", claim: "T:def:even", coverage: "full", basis: "checked_bridge", created_by: "llm:synthetic-model",
        steps: [{ id: "s1", establishes: "the whole definition", uses: ["e-1"], requirements: ["even"] }],
        evidence: ["e-1"], gaps: { requirements: 1, uncovered: [], open: [] }, complete: true, next_step: null,
        bridge: { theorem: "Toy.synthetic_bridge", target: "Toy.Spec.synthetic" }, bridge_check: { state: "checked", reasons: [] }, currency: cur }] }] }));

// #77: the toy audit with records people made about Theorem 2.1 (its symbol links, a
// correspondence note, and a published reading that aligns passages of the paper with rows of the
// Lean), with the review queue the engine builds for it: the reader draws them, independent
// Compare is given none of them.
fs.cpSync(path.join(root, "toy"), path.join(root, "toycmp"), { recursive: true });
{
  const row = TOY.claims.find((c) => c.id === "T:thm:even-add");
  const file = path.join(root, "toycmp/data/claims", row.file);
  const rec = JSON.parse(fs.readFileSync(file));
  const spec = rec.clauses[0].spec;
  rec.correspondence = { source: "confirmed", coverage: "full", basis: "direct", refs: [spec], note: "SYNTHETIC-NOTE: the author's reading of the sum.",
                         by: "A. Auditor", argument: null, bridge: null, question: null, would_decide: null, confidence: null };
  rec.work = "work/" + row.file;
  fs.writeFileSync(file, JSON.stringify(rec));
  fs.mkdirSync(path.join(root, "toycmp/data/work"), { recursive: true });
  const req = (local_id, form, text) => ({ id: "q-" + local_id, kind: "requirement", claim: row.id, local_id, form, text, depth: 0, currency: cur });
  const frag = (id, requirement, text) => ({ id, kind: "fragment", claim: row.id, requirement, role: "statement", origin: "printed", state: "accepted",
    state_by: "human:A-Auditor", region: { paper: "T", file: "toy.tex", start_line: 1, end_line: 1, sha256: "x", text }, currency: cur });
  fs.writeFileSync(path.join(root, "toycmp/data/work", row.file), JSON.stringify({
    schema: "prooflens/published-work@1", release: TOY.release, claim: row.id, readings: [{
      workspace: "ws-222222222222", mode: "informed", reviewer: { id: "human:A-Auditor", kind: "human", name: "A Auditor", identity: "self-declared" },
      requirements: [req("ab", "for every", "SYNTHETIC-REQUIREMENT: a and b, even natural numbers"), req("sum", "conclusion", "their sum is even")],
      fragments: [frag("p-ab", "ab", "SYNTHETIC-PASSAGE: if a and b are even natural numbers"), frag("p-sum", "sum", "then a + b is even")],
      alignments: [{ id: "al-ab", kind: "alignment", claim: row.id, requirements: ["ab"], relation: "corresponds",
                     lean: [{ decl: spec, var: 0 }, { decl: spec, var: 1 }], created_by: "human:A-Auditor", currency: cur },
                   { id: "al-sum", kind: "alignment", claim: row.id, requirements: ["sum"], relation: "corresponds",
                     lean: [{ decl: spec, conclusion: true }], created_by: "human:A-Auditor", currency: cur }],
      findings: [], evidence: [], compositions: [] }] }));
}
queueFor(path.join(root, "toycmp", "data"));

// The engine's semantic summary (#129, `semantic.refresh`) of copies of the toy audit, of the
// readings and reports above, and of the toy audit with its published workspace records, as a
// published audit carries it.
for (const [from, to] of [["toy", "toysem"], ["basis", "basissem"], ["toywork", "toyworksem"]]) fs.cpSync(path.join(root, from), path.join(root, to), { recursive: true });
const summarised = spawnSync(process.env.PYTHON || "python3", ["-c",
  "import sys\nfrom pathlib import Path\nfrom prooflens import semantic\nfor d in sys.argv[1:]: semantic.refresh(Path(d) / 'data', 'A. Author')",
  ...["toysem", "basissem", "toyworksem"].map((d) => path.join(root, d))], { encoding: "utf8" });
if (summarised.status !== 0) throw new Error("the engine could not summarise:\n" + summarised.stderr);
const SEM = Object.fromEntries(["toysem", "basissem", "toyworksem"].map((d) => [d, JSON.parse(fs.readFileSync(path.join(root, d, "data/index.json"), "utf8"))]));

// #414: the page with two audits of one version (`combined`), as machinechecked.org writes it with
// each listed audit's semantic summary on its registry entry (its scripts/summary.py record: the
// counts of the audited paper, the sets of readings, and the pins it was checked against). The
// first repository's audit carries the counts of the readings and reports above (`basissem`); a
// further audit of it has a summary the site could not show; the second repository's audit
// exports none.
fs.cpSync(path.join(root, "combined"), path.join(root, "summaries"), { recursive: true });
const SUMMARY = SEM.basissem.semantic, SUMMARY_PAPER = Object.keys(SUMMARY.papers)[0];
const UNSUPPORTED = "MachineChecked 0.1.21, which builds this site, does not read prooflens/semantic-summary@1.";
{
  const file = path.join(root, "summaries", "data", "index.json");
  const idx = JSON.parse(fs.readFileSync(file, "utf8"));
  const alpha = idx.paper.formalisations[0], loaded = idx.audits[alpha.repository];
  const { revision, paper_version, ...counts } = SUMMARY.papers[SUMMARY_PAPER];
  alpha.audits[0].semantic = { url: alpha.audits[0].url + "data/index.json", schema: SUMMARY.schema,
    digest: SUMMARY.digest, state: "loaded", release: loaded.release, commit: loaded.commit,
    author: SUMMARY.audit.author, paper_key: SUMMARY_PAPER, revision, paper_version,
    selected: SUMMARY.selected, sets: SUMMARY.sets, paper: counts };
  alpha.audits.push({ url: "https://audit.example/other/", author: "C. Author",
    semantic: { url: "https://audit.example/other/data/index.json", schema: SUMMARY.schema,
                digest: "0".repeat(64), state: "unsupported", detail: UNSUPPORTED } });
  fs.writeFileSync(file, JSON.stringify(idx));
}

// The toy audit with the comparison to an earlier release (`changes.py`, prooflens/changes@1):
// a definition whose statement changed reopens the review that read it, a context change beside
// an unchanged display is reported with its pin, and an unchanged claim is hidden by default.
fs.cpSync(path.join(root, "toy"), path.join(root, "toychanges"), { recursive: true });
const marker = { by: "a.referee", kind: "human", provenance: "self-declared", file: "reviews/definitions.md", line: 10, hash: "pl-fp-v1:old", source: { "T:def:even": "d".repeat(64) } };
const unchangedRow = (cid) => ({ claim: cid, paper: "T", number: TOY.claims.find((c) => c.id === cid).number, kind: "theorem", scope: "formal",
  status: { from: { status: "formal: accepted", status_code: "formal.accepted" }, to: { status: "formal: accepted", status_code: "formal.accepted" } },
  paper_change: { class: "unchanged", reason: "the same text at the same place", context: [], from: "same", to: { location: "toy.tex", sha256: "e".repeat(64) } },
  lean_changed: false, lean: [], evidence: [{ target: "spec", name: "Toy.PaperSpec.thm_triangle", clause: "statement", outcome: "kept", from: { state: "reviewed", marker }, to: { state: "reviewed", marker: "same" } }], due: false });
const CHANGES = {
  schema: "prooflens/changes@1",
  from: { release: "r-earlier", evidence: "1".repeat(64), project: { commit: "a".repeat(40), dirty: false }, papers: { T: { revision: "b".repeat(40), mode: "latex" } } },
  to: { release: TOY.release, evidence: TOY.evidence, project: { commit: "c".repeat(40), dirty: false }, papers: { T: { revision: "b".repeat(40), mode: "latex" } } },
  paper_changed: { T: false }, lean_changed: true,
  counts: { claims: { "context-changed": 1, unchanged: 2 }, evidence: { reopened: 1, kept: 2 }, declarations: { statement: 1 }, status_changed: 1 },
  claims: [
    { claim: "T:def:even", paper: "T", number: "Definition 1.1", kind: "definition", scope: "definition",
      status: { from: { status: "definition: reviewed", status_code: "definition.reviewed" }, to: { status: "definition: review pending", status_code: "definition.review-pending" } },
      paper_change: { class: "unchanged", reason: "the same text at the same place", context: [], from: "same", to: { location: "toy.tex", sha256: "d".repeat(64) } },
      lean_changed: true, due: true,
      lean: [{ clause: "definition", in: "both", definitions: [{ name: "Toy.IsEven", change: "statement",
        from: { fingerprint: "pl-fp-v1:old", text: "Toy.IsEven : Nat → Prop\n∀ (n : Nat), Toy.IsEven n = ∃ (k : Nat), n = 2 * k" },
        to: { fingerprint: "pl-fp-v1:new", text: "Toy.IsEven : Nat → Prop\n∀ (n : Nat), Toy.IsEven n = ∃ (k : Nat), n = k + k <img src=x onerror=alert(1)>" } }], definitions_unchanged: 0, proofs: [] }],
      evidence: [{ target: "def", name: "Toy.IsEven", clause: "definition", outcome: "reopened", from: { state: "reviewed", marker }, to: { state: "stale", marker: null },
        because: [{ dependency: "lean", name: "Toy.IsEven", was: "pl-fp-v1:old", now: "pl-fp-v1:new" }],
        question: "Does Toy.IsEven still define what Definition 1.1 (T:def:even) prints, now that its definition has changed?" }] },
    { claim: "T:eq:bound-range", paper: "T", number: "Equation (3)", kind: "equation", scope: "proof-step",
      status: { from: { status: "out of scope: proof-step", status_code: "scope.proof-step" }, to: { status: "out of scope: proof-step", status_code: "scope.proof-step" } },
      paper_change: { class: "context-changed", reason: "its own passage is unchanged; the context its pin covers changed",
        context: [{ what: "passage", part: 1, change: "changed", from: { location: "toy.tex:71", sha256: "1".repeat(64) }, to: { location: "toy.tex:71", sha256: "2".repeat(64) } }],
        pin: "the inventory still pins the earlier text: the source check reports the difference, and a review of the earlier text counts only for that text until the passage is read again and pinned",
        from: { location: "toy.tex:75", sha256: "3".repeat(64), part_text: [{ location: "toy.tex:75", text: "n \\le k n^2" }, { location: "toy.tex:71", text: "Fix $n$." }] },
        to: { location: "toy.tex:75", sha256: "4".repeat(64), part_text: [{ location: "toy.tex:75", text: "n \\le k n^2" }, { location: "toy.tex:71", text: "Fix $n \\ge 1$." }] } },
      lean_changed: false, due: false, lean: [],
      evidence: [{ target: "step", name: "T:eq:bound-range", outcome: "kept", from: { state: "false" }, to: { state: "false" }, caveat: "counted against the pinned earlier text; the paper now prints another" }] },
    unchangedRow("T:thm:triangle")],
  declarations: [], note: "Each status is the one its own build computed. A reopened review needs a new reading at the later revision; the earlier reading stays in the review files as it was." };
fs.writeFileSync(path.join(root, "toychanges/data/changes.json"), JSON.stringify(CHANGES));
fs.writeFileSync(path.join(root, "toychanges/data/index.json"), JSON.stringify({ ...TOY, changes: "data/changes.json" }));

fs.cpSync(path.join(root, "toy"), path.join(root, "long-statement"), { recursive: true });
const longFile = TOY.claims.find((c) => c.id === "T:thm:even-add").file;
const longPath = path.join(root, "long-statement/data/claims", longFile);
const longClaim = JSON.parse(fs.readFileSync(longPath));
const longStatement = longClaim.clauses[0].statement;
longStatement.binders = Array.from({ length: 12 }, (_, i) => ({ name: `x${i}`, role: "forall", binder: "explicit", type: { text: "Nat" } }));
longStatement.conclusion = { text: "x0 = x0" };
longStatement.exact = { text: "∀ " + longStatement.binders.map((b) => `(${b.name} : Nat)`).join(" ") + ", x0 = x0" };
fs.writeFileSync(longPath, JSON.stringify(longClaim));

// Facts inside a proof (tests/fixtures/prooffacts, regenerated by fixtures/make_prooffacts.py):
// `/pfedit/` is that reader as the local `view` serves it, answering `api/proof-facts` with the
// engine's own answers and capturing the workspace edits it is sent.
fs.cpSync(reader, path.join(root, "prooffacts"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "prooffacts", "data"), path.join(root, "prooffacts", "data"), { recursive: true });
const PF = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "prooffacts", "data", "index.json"), "utf8"));
const PF_FACTS = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "prooffacts", "facts.json"), "utf8"));
const pfPosted = [], pfAsked = [];
const PF_WS = { id: "ws-facts", mode: "informed", reviewer: "human:Test", revision: 1, findings: 0, open_questions: 0, reports: 0, claims: {} };
function proofFactsApi(url, query, req, res) {
  const json = (o) => { res.writeHead(200, { "content-type": "application/json" }); res.end(JSON.stringify(o)); };
  if (url === "/pfedit/api/proof-facts") {
    const q = new URLSearchParams(query);
    pfAsked.push(q.get("name"));
    return json(PF_FACTS[q.get("name")]);
  }
  if (url === "/pfedit/api/workspaces") return json({ workspaces: [PF_WS] });
  if (url === "/pfedit/api/workspace" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => { pfPosted.push(JSON.parse(body)); json({ ok: true }); });
    return;
  }
  if (url === "/pfedit/api/workspace") return json(PF_WS);
  res.writeHead(404); res.end();
}

const types = { ".pdf": "application/pdf", ".html": "text/html", ".json": "application/json", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" };
// `/toyedit/` is the toy reader as the local `view` serves it: its index says it may edit, and
// symbol links it saves are captured here instead of written.
const posted = [];
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  if (url.startsWith("/pfedit/api/")) return proofFactsApi(url, req.url.split("?")[1] || "", req, res);
  if (url === "/pfedit/data/index.json") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ...PF, editable: true }));
  }
  if (url.startsWith("/pfedit/")) url = "/prooffacts/" + url.slice("/pfedit/".length);
  if (url === "/toyedit/api/symbol" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => { posted.push(JSON.parse(body)); res.writeHead(200, { "content-type": "application/json" }); res.end("{\"ok\": true}"); });
    return;
  }
  if (url === "/toyedit/data/index.json") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(JSON.stringify({ ...TOY, editable: true }));
  }
  if (url.startsWith("/toyedit/")) url = "/toy/" + url.slice("/toyedit/".length);
  if (url.endsWith("/")) url += "index.html";
  const p = path.join(root, url);
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const origin = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
let failures = 0;
if (process.env.SHOTS) fs.mkdirSync(process.env.SHOTS, { recursive: true });

// `ONLY` (a regular expression) runs only the checks whose name it matches.
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY) : null;
async function check(name, width, fn, height = 900) {
  if (ONLY && !ONLY.test(name)) return;
  const pg = await browser.newPage({ viewport: { width, height } });
  pg.setDefaultTimeout(10000);
  const errors = [];
  pg.on("pageerror", (e) => { errors.push(String(e)); console.log(`PAGE ERROR ${name}: ${e.stack || e}`); });
  try {
    await fn(pg);
    assert.deepEqual(errors, [], "no page errors");
    console.log(`ok   ${name} (${width}px)`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name} (${width}px): ${e.message}`);
    if (process.env.SHOTS) {
      await pg.screenshot({ path: path.join(process.env.SHOTS, `failure-${failures}-${width}.png`) });
      fs.writeFileSync(path.join(process.env.SHOTS, `failure-${failures}.json`), JSON.stringify({ name, errors, message: e.message, storage: await pg.evaluate(() => Object.fromEntries(Object.entries(localStorage))) }, null, 2));
    }
  } finally {
    await pg.close();
  }
}

// Whether `cond` holds within `ms` milliseconds, asked every 25 ms: for a state of this process
// (a request the test server received) that the page changes in its own time.
const until = async (cond, ms = 5000) => {
  for (const end = Date.now() + ms; !cond() && Date.now() < end;) await new Promise((r) => setTimeout(r, 25));
  return cond();
};

// The Lean names the open claim's panel lists.
const panelNames = async (pg) => (await pg.locator("aside .lean .block .decl code").allTextContents()).map((s) => s.trim());
const open = async (pg, claim) => {
  await pg.evaluate((id) => { location.hash = `#/r/paper/read/P/${encodeURIComponent(id)}`; }, claim);
  await pg.waitForSelector("aside h1");
};
const dots = async (pg) => pg.locator(".reader-layout > nav.toc li .dot").evaluateAll((ds) => ds.map((d) => d.className));

await check("a static page asks for nothing outside its directory, and nothing fails", 1300, async (pg) => {
  const outside = [], failed = [];
  pg.on("request", (r) => { const u = new URL(r.url()); if (u.origin === origin && !u.pathname.startsWith("/paper/")) outside.push(u.pathname); });
  pg.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
  await pg.goto(origin + "/paper/");
  await pg.waitForSelector("select[aria-label='Formalisation shown']");
  await pg.waitForLoadState("networkidle");
  assert.deepEqual(outside, [], "requests outside the page's directory");
  assert.deepEqual(failed, [], "failed requests");
});

for (const width of [1300, 390]) {
  await check("the first project is chosen by default, and only its links show", width, async (pg) => {
    await pg.goto(origin + "/paper/");
    await pg.waitForSelector("select[aria-label='Formalisation shown']");
    assert.equal(await pg.inputValue("select[aria-label='Formalisation shown']"), A);
    await open(pg, "P:theorem-3");
    assert.deepEqual(await panelNames(pg), ["A.three"]);
    await open(pg, "P:theorem-2");
    assert.deepEqual(await panelNames(pg), [], "B's link does not show under A");
    assert.match(await pg.locator("aside").textContent(), /not linked/);
  });

  if (width > 1180) await check("the panel gives the site's report link for the chosen listing", width, async (pg) => {
    await pg.goto(origin + "/paper/");
    const report = pg.locator("a", { hasText: "Report this listing" });
    await report.waitFor();
    assert.equal(await report.getAttribute("href"), "https://github.com/cgarryZA/machinechecked.org/issues/new?title=x");
    await pg.selectOption("select[aria-label='Formalisation shown']", B);
    await pg.waitForFunction(() => !document.body.textContent.includes("Report this listing"));
  });

  await check("choosing the other project changes every claim view and keeps the claim", width, async (pg) => {
    await pg.goto(origin + "/paper/#/r/paper/read/P/P%3Atheorem-3");
    await pg.waitForSelector("aside h1");
    await pg.selectOption("select[aria-label='Formalisation shown']", B);
    await pg.waitForFunction(() => document.querySelector("aside")?.textContent.includes("B.three"));
    assert.deepEqual(await panelNames(pg), ["B.three"], "never both projects' links");
    assert.equal(new URL(pg.url()).searchParams.get("project"), B, "the address keeps the choice");
    assert.match(pg.url(), /#\/r\/paper\/read\/P\/P%3Atheorem-3$/, "the selected claim stays open");
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `selector-${width}.png`) });
    await open(pg, "P:theorem-1");
    assert.deepEqual(await panelNames(pg), [], "A's link does not show under B");
  });

  await check("the address chooses the project, and the contents follow it", width, async (pg) => {
    await pg.goto(origin + `/paper/?project=${encodeURIComponent(B)}`);
    await pg.waitForSelector("select[aria-label='Formalisation shown']");
    assert.equal(await pg.inputValue("select[aria-label='Formalisation shown']"), B);
    if (width > 1180) {
      // Theorem 1 (A only), 2 (B only), 3 (both), Lemma 4 (none): under B, 2 and 3 are linked.
      assert.deepEqual((await dots(pg)).map((c) => c.includes("st-declared")), [false, true, true, false]);
    }
  });
}

await check("a long Lean name stays inside the claim panel on a phone", 390, async (pg) => {
  await pg.goto(origin + "/paper/");
  await pg.waitForSelector("select[aria-label='Formalisation shown']");
  await open(pg, "P:theorem-1");
  assert.deepEqual(await panelNames(pg), ["A.Some.Rather.Long.Namespace.with_a_declaration_name_long_enough_to_overflow_a_phone"]);
  const [scroll, client] = await pg.locator("aside").evaluate((a) => [a.scrollWidth, a.clientWidth]);
  assert.ok(scroll <= client, `the panel scrolls sideways (${scroll} > ${client})`);
});

// The paper pane shows a claim's band when the claim is chosen, wherever it is in a long paper,
// even though choosing it opens the side panel and narrows the pages.
const bandInView = (id) => {
  const band = document.querySelector(`[data-claim="${CSS.escape(id)}"]`);
  const pane = band?.closest(".paperpane");
  if (!band || !pane) return false;
  const b = band.getBoundingClientRect(), p = pane.getBoundingClientRect();
  return b.top >= p.top - 1 && b.top <= p.bottom;
};
// After `n` frames are drawn: the layout a change set off (a resize, the scroll that follows it)
// has run.
const frames = (pg, n) => pg.evaluate((n) => new Promise((done) => {
  const next = (k) => (k ? requestAnimationFrame(() => next(k - 1)) : done());
  next(n);
}), n);
// The band comes into view within a bounded time, and is still in view once the frames after
// it are drawn.
const comesIntoView = async (pg, id) => {
  if (!(await pg.waitForFunction(bandInView, id, { timeout: 10000 }).then(() => true, () => false))) return false;
  await frames(pg, 2);
  return pg.evaluate(bandInView, id);
};
const ids = ["P:theorem-2", "P:theorem-15", "P:theorem-28"];
await check("a claim chosen in a long paper stays in view (contents and deep links)", 1300, async (pg) => {
  await pg.goto(origin + "/long/");
  await pg.waitForSelector("nav.toc li");
  for (const id of [...ids, ids[0]]) {
    await pg.locator(".reader-layout > nav.toc strong", { hasText: new RegExp(`^Theorem ${id.split("-")[1]}$`) }).click();
    await pg.locator("aside h1", { hasText: new RegExp(`^Theorem ${id.split("-")[1]}\\b`) }).waitFor();
    assert.ok(await comesIntoView(pg, id), `${id} not in view after choosing it`);
  }
  for (const id of ids) {
    const cold = await browser.newPage({ viewport: { width: 1300, height: 900 } });
    await cold.goto(origin + `/long/#/r/paper/read/P/${encodeURIComponent(id)}`);
    await cold.waitForSelector("aside h1");
    assert.ok(await comesIntoView(cold, id), `${id} not in view when opened by its link`);
    await cold.close();
  }
});

// The reader fills the window and the document never scrolls (#65, #214): not after opening a
// claim deep in a long paper by its link, and not after wheel scrolling in any pane.
const pageScroll = (pg) => pg.evaluate(() => ({ height: innerHeight, scrollHeight: document.scrollingElement.scrollHeight, scrollY }));
const assertNoPageScroll = async (pg, when) => {
  const s = await pageScroll(pg);
  assert.equal(s.scrollHeight, s.height, `document taller than the window ${when}: ${JSON.stringify(s)}`);
  assert.equal(s.scrollY, 0, `document scrolled ${when}: ${JSON.stringify(s)}`);
};
for (const [width, height] of [[1440, 900], [2000, 1000], [390, 844]]) {
  await check("the document never scrolls after a deep link or scrolling a pane", width, async (pg) => {
    await pg.goto(origin + `/tall/#/r/paper/read/P/${encodeURIComponent("P:theorem-55")}`);
    await pg.waitForSelector("aside h1");
    await pg.waitForTimeout(1500);
    await assertNoPageScroll(pg, "after opening a claim by its link");
    const panes = { contents: ".reader-layout > nav.toc", paper: ".paperpane", claim: "aside.side" };
    let scrolled = 0;
    for (const [name, sel] of Object.entries(panes)) {
      const pane = pg.locator(sel);
      if (!(await pane.count()) || !(await pane.isVisible())) continue;
      const box = await pane.boundingBox();
      if (!box || box.width < 2 || box.height < 2) continue;
      await pg.mouse.move(box.x + box.width / 2, box.y + Math.min(box.height / 2, 200));
      for (const dy of [4000, -1500, 8000]) { await pg.mouse.wheel(0, dy); await pg.waitForTimeout(150); }
      await assertNoPageScroll(pg, `after scrolling the ${name} pane`);
      scrolled++;
    }
    assert.ok(scrolled >= 1, "no pane was scrolled");
    if (width > 1180) {
      assert.equal(scrolled, 3, "contents, paper and claim panes all scrolled");
      const toc = await pg.locator(".reader-layout > nav.toc").evaluate((n) => [n.scrollTop, n.scrollHeight > n.clientHeight]);
      assert.ok(toc[1] && toc[0] > 0, `the contents pane scrolls inside its own box (${toc})`);
    }
  }, height);
}

// A paper in two versions: the drop-down beside the project selector opens the other version's
// page, with its own PDF, claim numbers and statuses; the address keeps the version and the
// project; a deep link opens a claim in its version; switching changes no status.
const VERSION = "select[aria-label='Paper version shown']";
const statusOf = async (pg, claim) => {
  await open(pg, claim);
  return pg.locator("aside [data-status]").first().getAttribute("data-status");
};
const statuses = async (pg, claims) => {
  const out = [];
  for (const c of claims) out.push(await statusOf(pg, c));
  return out;
};
for (const width of [1300, 390]) {
  await check("the version drop-down switches the paper, its numbering and its statuses", width, async (pg) => {
    await pg.goto(origin + "/versions/v1/");
    await pg.waitForSelector(VERSION);
    assert.deepEqual((await pg.locator(VERSION + " option").allTextContents()).map((t) => t.trim()),
      ["arXiv v1", "Latest manuscript (commit abc1234)"], "labels from the version, never a number a manuscript lacks");
    assert.equal(await pg.inputValue(VERSION), "arxiv:2601.00003v1");
    await pg.waitForFunction(() => document.querySelector(".paperpane")?.textContent.includes("Version one text."));
    const v1 = await statuses(pg, ["P:theorem-1", "P:theorem-2"]);
    assert.deepEqual(v1, ["link.no-audit", "link.none"]);
    await pg.selectOption("select[aria-label='Formalisation shown']", A);
    await pg.waitForSelector(".version.unchecked");
    assert.match(await pg.locator(".version.unchecked").textContent(), /not checked against its claims/);
    await pg.selectOption("select[aria-label='Formalisation shown']", B);
    assert.equal(await pg.locator(".version.unchecked").count(), 0, "a checked version carries no note");
    const v1b = await statuses(pg, ["P:theorem-1", "P:theorem-2"]);
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `versions-${width}.png`) });

    await pg.selectOption(VERSION, "manuscript:abc1234");
    await pg.waitForURL(/\/versions\/latest\//);
    const u = new URL(pg.url());
    assert.equal(u.searchParams.get("project"), B, "the project goes with the version");
    assert.equal(u.hash.replace(/^#\/?$/, ""), "", "the claim does not: numbers differ between versions");
    await pg.waitForSelector(VERSION);
    assert.equal(await pg.inputValue(VERSION), "manuscript:abc1234");
    assert.equal(await pg.inputValue("select[aria-label='Formalisation shown']"), B);
    await pg.waitForFunction(() => document.querySelector(".paperpane")?.textContent.includes("Latest manuscript text."));
    // The chosen version's label is shown whole, at a phone's width too.
    const cut = await pg.locator(VERSION).evaluate((sel) => {
      const cs = getComputedStyle(sel);
      const ctx = document.createElement("canvas").getContext("2d");
      ctx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      const text = ctx.measureText(sel.selectedOptions[0].textContent.trim()).width;
      const room = sel.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 20;
      return text > room ? `${Math.round(text)} > ${Math.round(room)}` : null;
    });
    assert.equal(cut, null, `the version's label is cut off (${cut})`);
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `versions-latest-${width}.png`) });
    await pg.selectOption("select[aria-label='Formalisation shown']", A);
    assert.deepEqual(await statuses(pg, ["P:lemma-1", "P:theorem-2", "P:theorem-3"]), ["link.none", "link.none", "link.no-audit"]);

    await pg.selectOption(VERSION, "arxiv:2601.00003v1");
    await pg.waitForURL(/\/versions\/v1\//);
    await pg.waitForSelector(VERSION);
    assert.deepEqual(await statuses(pg, ["P:theorem-1", "P:theorem-2"]), v1, "statuses are unchanged by switching");
    await pg.selectOption("select[aria-label='Formalisation shown']", B);
    assert.deepEqual(await statuses(pg, ["P:theorem-1", "P:theorem-2"]), v1b);
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });

  await check("a deep link opens a claim in its version", width, async (pg) => {
    await pg.goto(origin + "/versions/latest/#/r/paper/read/P/P%3Atheorem-3");
    await pg.waitForSelector("aside h1");
    assert.match(await pg.locator("aside h1").textContent(), /Theorem 3/);
    assert.equal(await pg.inputValue(VERSION), "manuscript:abc1234");
    assert.equal(await pg.locator("aside [data-status]").first().getAttribute("data-status"), "link.no-audit");
    await pg.goto(origin + "/versions/v1/#/r/paper/read/P/P%3Atheorem-2");
    await pg.waitForSelector("aside h1");
    assert.match(await pg.locator("aside h1").textContent(), /Theorem 2/);
    assert.equal(await pg.inputValue(VERSION), "arxiv:2601.00003v1");
    assert.equal(await pg.locator("aside [data-status]").first().getAttribute("data-status"), "link.none");
  });
}

// #225: a claim shows what it is in the other version, from the site's claim map, with a link
// to that claim on the other version's page; a removed and a new claim say so. Statuses are each
// page's own.
const counterpart = async (pg, claim, number) => {
  await open(pg, claim);
  await pg.waitForFunction((n) => document.querySelector("aside h1")?.textContent.includes(n), number);
  return (await pg.locator("aside .counterpart").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
};
for (const width of [1300, 390]) {
  await check("a claim shows its counterpart in the other version and links there", width, async (pg) => {
    await pg.goto(origin + "/versions/v1/");
    await pg.waitForSelector(VERSION);
    assert.deepEqual(await counterpart(pg, "P:theorem-1", "Theorem 1"),
      ["Theorem 3 in Latest manuscript (commit abc1234), statement changed."]);
    assert.deepEqual(await counterpart(pg, "P:theorem-2", "Theorem 2"),
      ["Lemma 1 in Latest manuscript (commit abc1234), renumbered."]);
    assert.deepEqual(await counterpart(pg, "P:theorem-3", "Theorem 3"),
      ["Removed in Latest manuscript (commit abc1234)."]);
    assert.equal(await pg.locator("aside .counterpart a").count(), 0, "a removed claim links nowhere");
    assert.deepEqual(await statuses(pg, ["P:theorem-1", "P:theorem-2", "P:theorem-3"]), ["link.no-audit", "link.none", "link.none"]);
    if (process.env.SHOTS) {
      await counterpart(pg, "P:theorem-1", "Theorem 1");
      await pg.screenshot({ path: path.join(process.env.SHOTS, `counterpart-${width}.png`) });
    }

    await counterpart(pg, "P:theorem-1", "Theorem 1");
    await pg.locator("aside .counterpart a", { hasText: "Theorem 3" }).click();
    await pg.waitForURL(/\/versions\/latest\//);
    const u = new URL(pg.url());
    assert.equal(decodeURIComponent(u.hash), "#/r/paper/read/P/P:theorem-3");
    await pg.waitForFunction(() => document.querySelector("aside h1")?.textContent.includes("Theorem 3"));
    assert.equal(await pg.inputValue(VERSION), "manuscript:abc1234");
    assert.deepEqual((await pg.locator("aside .counterpart").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim()),
      ["Theorem 1 in arXiv v1, statement changed."]);
    assert.equal(await pg.locator("aside [data-status]").first().getAttribute("data-status"), "link.no-audit");
    assert.deepEqual(await counterpart(pg, "P:theorem-2", "Theorem 2"), ["New in this version: not in arXiv v1."]);
    assert.deepEqual(await counterpart(pg, "P:lemma-1", "Lemma 1"), ["Theorem 2 in arXiv v1, renumbered."]);
    await pg.locator("aside .counterpart a", { hasText: "Theorem 2" }).click();
    await pg.waitForURL(/\/versions\/v1\//);
    await pg.waitForFunction(() => document.querySelector("aside h1")?.textContent.includes("Theorem 2"));
    assert.equal(await pg.inputValue(VERSION), "arxiv:2601.00003v1");
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });
}

// #42: each audit in the panel names the version it pins and its commit; the audit of the page's
// version is the action, and audits of other versions link to their own pages.
const showPanel = async (pg, width) => {
  if (width <= 1180) await pg.locator(".reader-tools button", { hasText: "Formalisations" }).click();
  await pg.waitForSelector(".info .card");
};
for (const width of [1300, 390]) {
  await check("each audit names its version and commit; other versions link to their pages", width, async (pg) => {
    await pg.goto(origin + `/versions/v1/?project=${encodeURIComponent(A)}`);
    await showPanel(pg, width);
    const card = pg.locator(`.info .card[data-repository="${A}"]`);
    assert.deepEqual((await card.locator(".audit.here .btn").allTextContents()).map((t) => t.trim()), ["Open the audit of arXiv v1"]);
    assert.match(await card.locator(".audit.here").textContent(), /by A\. Author · commit 111111111111/);
    assert.equal(decodeURIComponent(await card.locator(".audit.here .btn").getAttribute("href")), "/read/?audit=https://audit.example/a/v1/");
    const other = card.locator(".elsewhere a");
    assert.deepEqual((await other.allTextContents()).map((t) => t.trim()), ["Latest manuscript (commit abc1234)"]);
    assert.match(await card.locator(".elsewhere li").textContent(), /commit 222222222222/);
    const to = new URL(await other.getAttribute("href"));
    assert.equal(to.pathname, "/versions/latest/");
    assert.equal(to.searchParams.get("project"), A);

    await pg.goto(origin + `/versions/latest/?project=${encodeURIComponent(A)}`);
    await showPanel(pg, width);
    assert.deepEqual((await pg.locator(".info .audit.here .btn").allTextContents()).map((t) => t.trim()), ["Open the audit of Latest manuscript (commit abc1234)"]);
    assert.deepEqual((await pg.locator(".info .elsewhere a").allTextContents()).map((t) => t.trim()), ["arXiv v1"]);
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });
}

// #398: an audit the site says did not load is shown with its reason, never as the page's audit;
// a loaded audit beside it stays the action; a page written before the site gave each audit its
// state shows its listing's reason and audit as it did.
for (const width of [1300, 390]) {
  await check("an audit that did not load is shown with its reason, not as the page's audit", width, async (pg) => {
    const card = (repo) => pg.locator(`.info .card[data-repository="${repo}"]`);
    const texts = async (loc) => (await loc.allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
    const open = async (repo) => {
      await pg.goto(origin + `/failed/?project=${encodeURIComponent(repo)}`);
      await showPanel(pg, width);
      await card(repo).waitFor();
    };
    await open("synthetic/alpha");
    assert.deepEqual(await texts(card("synthetic/alpha").locator(".audit.here .btn")), ["Open the audit"]);
    assert.match(await card("synthetic/alpha").locator(".audit.here").textContent(), /by A\. Author · commit aaaaaaaaaaaa/);
    const lost = card("synthetic/alpha").locator(".audit.failed");
    assert.deepEqual(await texts(lost), ["Audit unavailable: HTTP Error 404: Not Found Open the audit by A. Author"]);
    assert.equal(await lost.getAttribute("data-state"), "unavailable");
    assert.equal(await lost.locator(".btn").count(), 0, "a failed audit is not the page's action");
    assert.equal(decodeURIComponent(await lost.locator("a").getAttribute("href")), "/read/?audit=https://audit.example/latest/");
    assert.equal(await card("synthetic/alpha").locator(".audit").count(), 2);

    await open("synthetic/beta");
    const beta = card("synthetic/beta");
    assert.equal(await beta.locator(".btn").count(), 0);
    assert.deepEqual(await texts(beta.locator(".audit.failed")),
      ["Audit incompatible: Audit pins another version of the paper than the listing names Open the audit by B. Author"]);
    const text = await beta.textContent();
    assert.equal(text.split("Audit incompatible").length, 2, "the reason is given once");
    assert.doesNotMatch(text, /No claim-level audit|No audit of this version/);

    // Data without a state for each audit: as before.
    await open("synthetic/gamma");
    const gamma = card("synthetic/gamma");
    assert.equal(await gamma.locator(".audit.failed").count(), 0);
    assert.match(await gamma.textContent(), /Audit unavailable: HTTP Error 404: Not Found/);
    assert.deepEqual(await texts(gamma.locator(".audit.here .btn")), ["Open the audit"]);
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });
}

// #212: a page with two audits of one version opens on the most-starred one; a claim it does not
// map shows the next audit's evidence, labelled with that audit; choosing one audit shows only its
// evidence and flags the claims it does not map. Statuses are each one audit's, never combined.
const CA = "synthetic/alpha", CB = "synthetic/beta", FORMAL = "select[aria-label='Formalisation shown']";
const SOURCE = "aside [data-source]";
const sourceOf = async (pg) => (await pg.locator(SOURCE).count()) ? pg.locator(SOURCE).first().getAttribute("data-source") : null;
for (const width of [1300, 390]) {
  await check("the audits of a version open together, the most-starred first, each claim labelled", width, async (pg) => {
    await pg.goto(origin + "/combined/");
    await pg.waitForSelector(FORMAL);
    assert.equal(await pg.inputValue(FORMAL), "", "the audits together are the default");
    assert.equal((await pg.locator(FORMAL + " option").first().textContent()).trim(), "All audits, by stars");
    assert.match(await pg.locator("[data-together]").textContent(), /audit of synthetic\/alpha by A\. Author \(most GitHub stars\)/);
    assert.equal(await statusOf(pg, "P:theorem-1"), "formal.author-reviewed", "the default audit's status");
    assert.equal(await sourceOf(pg), "default");
    assert.match(await pg.locator(SOURCE).textContent(), /From the audit of synthetic\/alpha by A\. Author at commit aaaaaaaaaaaa/);
    assert.equal(await statusOf(pg, "P:theorem-2"), "formal.refuted.corrected", "the second audit's own status");
    assert.equal(await sourceOf(pg), "filled");
    assert.match(await pg.locator(SOURCE).textContent(), /From another audit\..*synthetic\/beta by B\. Author at commit cccccccccccc/s);
    assert.equal(await statusOf(pg, "P:theorem-3"), "link.none", "a claim no audit maps keeps the default's state");
    assert.equal(await sourceOf(pg), "unmapped", "and is attributed to no audit");
    if (width > 1180) {
      await pg.goto(origin + "/combined/");
      await pg.waitForSelector(".reader-layout > nav.toc li");
      assert.deepEqual(await pg.locator(".reader-layout > nav.toc li .from").allTextContents(), ["From synthetic/beta"]);
      assert.deepEqual(await pg.locator(".info .card .rank").allTextContents(), ["Default audit · 10 GitHub stars", "Audit 2 · 3 GitHub stars"]);
    }
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `combined-${width}.png`) });
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });

  await check("choosing one audit shows only its evidence and flags the claims it lacks", width, async (pg) => {
    await pg.goto(origin + "/combined/#/r/paper/read/P/P%3Atheorem-1");
    await pg.waitForSelector("aside h1");
    await pg.selectOption(FORMAL, CB);
    await pg.waitForFunction(() => document.querySelector("aside [data-status]")?.getAttribute("data-status") === "formal.open");
    assert.equal(new URL(pg.url()).searchParams.get("project"), CB);
    assert.equal(await sourceOf(pg), null, "one audit chosen: no attribution to another");
    assert.equal(await statusOf(pg, "P:theorem-3"), "link.none");
    assert.equal(await sourceOf(pg), "missing");
    assert.match(await pg.locator(SOURCE).textContent(), /Not in this audit: the audit of synthetic\/beta does not map this claim/);
    await pg.selectOption(FORMAL, CA);
    assert.equal(await statusOf(pg, "P:theorem-2"), "link.none", "never the other audit's status");
    assert.equal(await sourceOf(pg), "missing");
    if (width > 1180) {
      await pg.goto(origin + `/combined/?project=${encodeURIComponent(CA)}`);
      await pg.waitForSelector(".reader-layout > nav.toc li");
      assert.deepEqual(await pg.locator(".reader-layout > nav.toc li .from").allTextContents(), ["Not in this audit", "Not in this audit"]);
      assert.equal(await pg.locator(".info .card").count(), 1);
    }
    await pg.selectOption(FORMAL, "");
    assert.equal(new URL(pg.url()).searchParams.get("project"), null, "the audits together leave the address plain");
    assert.equal(await statusOf(pg, "P:theorem-2"), "formal.refuted.corrected");
  });

  await check("choosing another audit clears a selection made in the first one's statement", width, async (pg) => {
    // Both audits state Theorem 1 with a declaration of the same name; an expression selected in
    // one build names nothing in the other (#73).
    await pg.route("**/combined/data/claims/*theorem-1*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      const seg = (t) => ({ t });
      for (const p of Object.values(rec.by_project || {})) {
        const cl = p.record?.clauses?.[0];
        if (cl?.statement) cl.statement.conclusion = { id: "/", text: "a + b ≤ b + a",
          segments: ["a", " + ", "b", " ≤ ", "b + a"].map(seg),
          terms: [{ id: "/", from: 0, to: 5 }, { id: "/0/1", from: 0, to: 3 }] };
      }
      route.fulfill({ response, json: rec });
    });
    await pg.goto(origin + `/combined/?project=${encodeURIComponent(CA)}#/r/paper/read/P/P%3Atheorem-1`);
    const st = pg.locator("aside .view .stmt").first();
    await st.locator(".p", { hasText: "+" }).first().click();
    assert.equal((await st.locator(".in").allTextContents()).join(""), "a + b");
    await pg.selectOption(FORMAL, CB);
    await pg.waitForFunction(() => document.querySelector("aside [data-status]")?.getAttribute("data-status") === "formal.open");
    await st.locator(".p", { hasText: "+" }).first().waitFor();
    assert.equal(await pg.locator("aside .view .stmt .in").count(), 0, "nothing selected in the other audit's statement");
  });

  await check("the stars choose the default audit, and the listing's order holds without them", width, async (pg) => {
    await pg.goto(origin + "/combined-beta/");
    await pg.waitForSelector(FORMAL);
    assert.match(await pg.locator("[data-together]").textContent(), /audit of synthetic\/beta by B\. Author/);
    assert.equal(await statusOf(pg, "P:theorem-1"), "formal.open");
    assert.equal(await sourceOf(pg), "default");
    if (width > 1180) {
      await pg.goto(origin + "/combined-beta/");
      await pg.waitForSelector(".reader-layout > nav.toc li");
      const prose = pg.locator(".reader-layout > nav.toc li", { hasText: "Paragraph 2" });
      assert.equal((await prose.locator(".from").textContent()).trim(), "From synthetic/alpha");
    }
    await pg.goto(origin + "/combined-unranked/");
    await pg.waitForSelector(FORMAL);
    assert.equal((await pg.locator(FORMAL + " option").first().textContent()).trim(), "All audits, listing order");
    assert.doesNotMatch(await pg.locator("[data-together]").textContent(), /most GitHub stars/);
    assert.equal(await statusOf(pg, "P:theorem-1"), "formal.author-reviewed");
  });
}

// #414: each listed audit's semantic summary is under that audit's own line of the panel: per unit,
// the correspondence and evidence basis of its selected readings, its reviews and findings, each
// count in the summary's words and linked to that audit's filtered Overview; another set of
// readings is linked apart. An audit without a summary shows what it showed before, and one the
// site could not show says why.
const VOCAB = JSON.parse(fs.readFileSync(path.resolve(here, "../../engine/python/prooflens/data/semantic.json"), "utf8"));
for (const width of [1300, 390]) {
  await check("each listed audit shows its own semantic summary, each count linked to its Overview", width, async (pg) => {
    await pg.goto(origin + "/summaries/");
    await showPanel(pg, width);
    const alpha = pg.locator(`.info .card[data-repository="${CA}"]`), beta = pg.locator(`.info .card[data-repository="${CB}"]`);
    await alpha.locator(".semantic").waitFor();
    assert.equal(await pg.locator(".info .semantic").count(), 1, "one summary, on its own audit's line");
    const sum = alpha.locator(".semantic");
    assert.equal(await sum.getAttribute("data-audit"), "https://audit.example/");
    assert.equal(await sum.getAttribute("data-digest"), SUMMARY.digest);
    assert.match(await sum.locator("p").first().textContent(), /Correspondence and evidence basis: the audit's readings, by A\. Auditor\./);
    const block = SUMMARY.papers[SUMMARY_PAPER], set = SUMMARY.selected;
    const units = ["statements", "notation", "proof_steps"].filter((u) => block.inventory[u].records > 0);
    assert.deepEqual(await sum.locator(".unit").evaluateAll((els) => els.map((e) => e.dataset.unit)), units);
    const overview = (q) => "/read/?audit=" + encodeURIComponent("https://audit.example/") + "#/r/r-synthetic/overview?" + new URLSearchParams(q);
    for (const u of units) {
      const row = sum.locator(`.unit[data-unit="${u}"]`);
      assert.match(await row.locator(".head").textContent(), new RegExp(`^${block.inventory[u].records} `));
      for (const [dim, param, table, vocab] of [["coverage", "coverage", block.coverage[set][u], VOCAB.coverage],
                                                ["basis", "basis", block.basis[set][u], VOCAB.basis],
                                                ["review", "review", block.review[u], u === "proof_steps" ? VOCAB.step_review : VOCAB.review],
                                                ["findings", "finding", block.findings[u], VOCAB.findings]]) {
        const want = Object.keys(vocab).filter((k) => table[k] > 0)
          .map((k) => [k, `${vocab[k].label} (${table[k]})`, overview({ set, unit: u, [param]: k })]);
        const got = await row.locator(`[data-dimension="${dim}"] a`).evaluateAll((as) => as.map((a) => [a.dataset.key, a.textContent, a.getAttribute("href")]));
        assert.deepEqual(got, want, `${u} ${dim}`);
      }
    }
    // An open question is shown, distinct from what is not assessed.
    const statements = sum.locator('.unit[data-unit="statements"]');
    assert.equal(await statements.locator('[data-dimension="coverage"] a[data-key="unresolved"]').textContent(), `Unresolved (${block.coverage[set].statements.unresolved})`);
    assert.ok(await statements.locator('[data-dimension="coverage"] a[data-key="not_assessed"]').count());
    // The other set of readings is linked, counted apart.
    const others = SUMMARY.sets.filter((s) => s.id !== set);
    assert.deepEqual(await sum.locator(".others a").evaluateAll((as) => as.map((a) => [a.textContent, a.getAttribute("href")])),
      others.map((s) => [`Reviews by ${s.reviewer.name}`, overview({ set: s.id, unit: "statements" })]));
    assert.match(await sum.locator("details").textContent(), new RegExp(`release r-synthetic, project commit aaaaaaaaaaaa.*digest ${SUMMARY.digest.slice(0, 12)}`, "s"));
    // A count's link opens that audit's Overview on the claims it counts.
    const href = await statements.locator('[data-dimension="coverage"] a[data-key="unresolved"]').getAttribute("href");
    await pg.goto(origin + `/basissem/#/r/${SEM.basissem.release}/overview?` + href.split("?").pop());
    await pg.locator(".coverage .claims li").first().waitFor();
    assert.equal(await pg.locator(".coverage .claims li").count(), block.coverage[set].statements.unresolved);
    await pg.goto(origin + "/summaries/");
    await showPanel(pg, width);
    await alpha.locator(".semantic").waitFor();
    // An audit the site could not show a summary for says why, with no count; an audit without a
    // summary shows what it showed before.
    const other = alpha.locator('.semantic-state[data-audit="https://audit.example/other/"]');
    assert.equal(await other.getAttribute("data-state"), "unsupported");
    assert.equal((await other.textContent()).trim(), `Semantic summary unsupported: ${UNSUPPORTED}`);
    assert.equal(await beta.locator(".semantic, .semantic-state").count(), 0);
    assert.doesNotMatch(await beta.textContent(), /Semantic summary|\(\d+\)/);
    assert.match(await beta.locator(".audit.here").textContent(), /by B\. Author · commit cccccccccccc/);
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `summaries-${width}.png`), fullPage: true });
    const [scroll, client] = await pg.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
    assert.ok(scroll <= client, `the page scrolls sideways (${scroll} > ${client})`);
  });
}

// The claim's inspections on the toy audit: a definition opens beside the row it was opened from,
// with the claim and the paper left where they were; Back closes it and returns to the reference.
const toyClaim = async (pg, id) => {
  await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/${encodeURIComponent(id)}`);
  await pg.waitForSelector("aside h1");
};
const scrollTops = (pg) => pg.evaluate(() => [document.querySelector("aside")?.scrollTop, document.querySelector(".paperpane")?.scrollTop]);

// The paper's statement is typeset from its source only when all of it can be; otherwise the
// PDF excerpt is shown, never a partial rendering.
const withExcerpt = async (pg, excerpt) => {
  await pg.route("**/toy/data/claims/*even-add*", async (route) => {
    const response = await route.fetch();
    route.fulfill({ response, json: { ...(await response.json()), excerpt } });
  });
  await toyClaim(pg, "T:thm:even-add");
};
for (const width of [1300, 390]) {
  await check("a statement is typeset whole from its source, with the PDF and source on request", width, async (pg) => {
    await withExcerpt(pg, EXCERPTS.complete);
    const ex = pg.locator("aside .view .paper .excerpt");
    await ex.locator(".katex").first().waitFor();
    assert.equal(await ex.locator(".katex").count(), 3, "both inline formulas and the display");
    const text = (await ex.textContent()).replace(/\s+/g, " ");
    assert.match(text, /Then, as in \[1, Lemma 3\],/, "a citation with its note; the line after a comment is kept");
    assert.match(text, /Proposition 1\.2 applies to \(1\.1\)\./, "references as printed");
    assert.match(await ex.locator(".display .tag").textContent(), /\(1\.1\)/, "the equation's printed number");
    assert.ok(!(await pg.locator("aside .paper .crop").isVisible()), "the PDF excerpt is folded");
    await pg.locator("aside .paper summary", { hasText: "As printed in the PDF" }).click();
    await pg.locator("aside .paper .crop canvas").waitFor();
    await pg.locator("aside .paper summary", { hasText: "LaTeX source" }).click();
    assert.match(await pg.locator("aside .paper .rawsrc pre").textContent(), /% not printed\nThen/);
  });
}
for (const [name, why] of [["katex-refuses", "the reader cannot typeset its mathematics"], ["engine-refuses", "the engine found a command it does not reproduce"]]) {
  await check(`a statement falls back to the PDF whole when ${why}`, 1300, async (pg) => {
    await withExcerpt(pg, EXCERPTS[name]);
    await pg.locator("aside .paper .crop canvas").waitFor();
    assert.ok(await pg.locator("aside .paper .crop").isVisible());
    assert.equal(await pg.locator("aside .paper .excerpt:visible").count(), 0, "no partial rendering");
    assert.equal(await pg.locator("aside .paper summary", { hasText: "As printed in the PDF" }).count(), 0);
  });
}
// A totalisation warning lists the applications it read with their types, and marks them in
// its clause's statement on request.
for (const width of [1300, 390]) {
  await check("a warning shows the type of its operation and marks it in the statement", width, async (pg) => {
    await pg.route("**/toy/data/claims/*prop_pred*", async (route) => {
      const response = await route.fetch();
      const json = await response.json();
      json.findings = json.findings.map((f) => f.subject.endsWith("#0") ? { ...f, occurrences: [
        { operation: f.trigger, type: "Nat", type_head: "Nat", structure: null, state: "applies",
          rule: "truncated subtraction on ℕ: a - b = 0 when a < b", at: ["/1/0/1"] },
        { operation: f.trigger, type: "Nat", type_head: "Nat", structure: "group", state: "none", rule: null, at: [] }] }
        : f.dismissed ? { ...f, at: "/1/1/1", dismissed: { ...f.dismissed, form: "statement" } } : f);
      route.fulfill({ response, json });
    });
    await toyClaim(pg, "T:prop:pred");
    await pg.locator("aside .view .chipbtn").click();
    await pg.locator("aside details.warning summary").click();
    const item = pg.locator("aside [data-finding='totalised:T:prop:pred#0:instSubNat']");
    const occ = await item.locator(".occ li").allTextContents();
    assert.deepEqual(occ.map((t) => t.replace(/\s+/g, " ").trim()), [
      "in Nat: truncated subtraction on ℕ: a - b = 0 when a < b",
      "in Nat, a group: no exceptional case in this type"]);
    assert.equal(await pg.locator("aside [data-finding='totalised:T:prop:pred#1:instSubNat'] .show").count(), 0, "nothing to mark");
    // A dismissal of the operation in the whole statement says so.
    assert.match(await pg.locator("aside [data-finding='totalised:T:prop:pred#1:instSubNat'] .dz").textContent(),
      /dismissal of the operation in the whole statement/);
    await item.locator(".show").click();
    const view = pg.locator("aside .view");
    await view.locator(".mk").first().waitFor();
    assert.equal((await view.locator(".mk").allTextContents()).join(""), "n - 1", "the operation, not the whole statement");
    assert.equal(await view.locator(".block").nth(0).locator(".mk").count() > 0, true, "in the printed clause");
    assert.equal(await view.locator(".block").nth(1).locator(".mk").count(), 0, "not in the corrected one");
    assert.match(await view.locator(".marknote").textContent(), /in Nat/);
    assert.ok(await view.locator(".mk").first().isVisible());
    const box = await view.locator(".mk").first().boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= width, "on screen");
    await view.locator(".marknote button").click();
    assert.equal(await view.locator(".mk").count(), 0, "cleared");
  });
}
// A warning lists the conditions its rule needs at the application, with what establishes them;
// one whose conditions are all established reads as resolved.
for (const width of [1300, 390]) {
  await check("a warning shows the conditions of its rule and whether the statement supplies them", width, async (pg) => {
    await pg.route("**/toy/data/claims/*prop_pred*", async (route) => {
      const response = await route.fetch();
      const json = await response.json();
      json.findings = json.findings.map((f) => f.subject.endsWith("#0") ? { ...f, resolved: true, at: "/1/0/1", occurrences: [
        { operation: f.trigger, type: "Real", type_head: "Real", structure: "conditionally-complete-lattice", state: "applies",
          rule: "a supremum in ℝ is 0 when the set is unbounded or empty", at: ["/1/0/1"], condition_state: "established",
          conditions: [
            { condition: "bounded-above", state: "established", by: "premise", premise: "hf", statement: "BddAbove (Set.range f)" },
            { condition: "nonempty-index", state: "established", by: "type", statement: "Lean finds Nonempty ℕ" }] }] } : f);
      route.fulfill({ response, json });
    });
    await toyClaim(pg, "T:prop:pred");
    await pg.locator("aside .view .chipbtn").click();
    await pg.locator("aside details.warning summary").click();
    const item = pg.locator("aside [data-finding='totalised:T:prop:pred#0:instSubNat']");
    const conds = await item.locator(".conds li").allTextContents();
    assert.deepEqual(conds.map((t) => t.replace(/\s+/g, " ").trim()), [
      "needs bounded above: established by the premise hf : BddAbove (Set.range f)",
      "needs a nonempty index type: established (Lean finds Nonempty ℕ)"]);
    assert.match(await item.textContent(), /resolved: the statement supplies every condition/);
    const box = await item.locator(".conds li").first().boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= width, "on screen");
  });
}
await check("a theorem of the toy paper is typeset with its equation number", 1300, async (pg) => {
  await toyClaim(pg, "T:thm:triangle");
  const ex = pg.locator("aside .view .paper .excerpt");
  await ex.locator(".katex").first().waitFor();
  assert.match(await ex.locator(".display .tag").textContent(), /\(1\)/);
});

for (const width of [1300, 390]) {
  await check("a definition opens beside its row, the claim stays; Back returns to the reference as it was", width, async (pg) => {
    await toyClaim(pg, "T:def:even");
    const ref = pg.locator("aside .lean .ref", { hasText: "Toy.IsEven" });
    await ref.scrollIntoViewIfNeeded();
    const [panel, paper] = await scrollTops(pg);
    await ref.click();
    const insp = pg.locator("aside .inspection");
    await insp.locator(".decl.inspector").waitFor();
    assert.equal(await insp.evaluate((e) => e.closest("[data-row]")?.dataset.row), "Toy.IsEven::top", "under the definition's own row");
    assert.ok(await pg.locator("aside .view h1").isVisible(), "the claim stays");
    assert.ok(await pg.locator("aside .view .paper .excerpt").isVisible(), "the paper's passage stays");
    assert.equal(await pg.locator("aside .defn.readable[data-decl='Toy.triangle']").isVisible(), true, "the other definition stays");
    assert.match(await insp.locator(".crumbs").textContent(), /Back.*IsEven/s);
    assert.equal(await insp.locator(".crumbs .back").evaluate((e) => e === document.activeElement), true, "focus moves to the inspection");
    assert.equal((await scrollTops(pg))[1], paper, "the paper keeps its position");
    await insp.locator(".crumbs .back").click();
    await insp.waitFor({ state: "detached" });
    assert.equal(await pg.locator("aside .defn.exact:visible").count(), 2, "both exact definitions remain in the claim comparison");
    const [panel2, paper2] = await scrollTops(pg);
    assert.equal(panel2, panel, "the panel's scroll position comes back");
    assert.equal(paper2, paper, "the paper keeps its position");
    assert.equal(await ref.evaluate((e) => e === document.activeElement), true, "focus returns to the reference");
  });

  await check("a definition claim shows each definition as it is written, beside the paper", width, async (pg) => {
    await toyClaim(pg, "T:def:even");
    const view = pg.locator("aside .view");
    const even = view.locator(".lean .defn.readable[data-decl='Toy.IsEven']");
    const tri = view.locator(".lean .defn.readable[data-decl='Toy.triangle']");
    await tri.locator(".eq").first().waitFor();
    assert.ok(await view.locator(".paper").textContent().then((t) => /triangular number/.test(t)), "the paper passage is beside them");
    // Evenness by its body, with its parameter and the witness's type.
    assert.match(await even.locator(".head").textContent(), /Toy\.IsEven\s*\(n : Nat\)\s*:\s*Prop/);
    assert.equal((await even.locator(".body").textContent()).trim(), "∃ (k : Nat), n = 2 * k");
    // The triangular numbers by their two equations, as Lean states them; the compiled
    // recursion is folded away.
    const eqs = await tri.locator(".eq").allTextContents();
    assert.equal(eqs.length, 2);
    assert.match(eqs[0], /Toy\.triangle 0 = 0/);
    assert.match(eqs[1], /for\s*\(n : Nat\):\s*Toy\.triangle n\.succ = Toy\.triangle n \+ \(n \+ 1\)/);
    const exact = view.locator(".exact-pane .defn.exact[data-decl='Toy.triangle']");
    assert.match(await exact.locator(".src").textContent(), /\| n \+ 1 => triangle n \+ \(n \+ 1\)/);
    assert.deepEqual(await exact.locator(".thm .tn").allTextContents(), ["Toy.triangle.eq_1", "Toy.triangle.eq_2"]);
    assert.equal(await exact.locator("details.compiled").getAttribute("open"), null, "the compiled value is a secondary view");
    assert.match(await exact.locator("details.compiled").textContent(), /Nat\.brecOn/);
    assert.ok(!(await view.locator(".lean .defn.readable").allTextContents()).join(" ").includes("brecOn"), "no compiled recursion in the readable Lean");
    // A sub-term selected in the readable body is the same sub-term of the exact value.
    await even.locator(".body .p", { hasText: "2" }).first().click();
    const lit = view.locator(".exact-pane .defn.exact[data-decl='Toy.IsEven'] .in");
    assert.equal((await lit.allTextContents()).join(""), "2 * k");
    // Selecting in an equation selects the same sub-term of its theorem.
    await tri.locator(".eq").nth(1).locator(".body .p", { hasText: "1" }).last().click();
    const mine = (await tri.locator(".eq").nth(1).locator(".in").allTextContents()).join("");
    assert.match(mine, /^\(?n \+ 1\)?$/);
    assert.equal((await exact.locator(".thm[data-eq='Toy.triangle.eq_2'] .in").allTextContents()).join(""), mine);
  });

  await check("the main view is the paper and the Lean, with the assumptions shown", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    const view = pg.locator("aside .view");
    await view.locator(".lean .ribbon").waitFor();
    assert.deepEqual(await view.locator(".cmp .grid > section > h2").allTextContents(), ["Paper", "Lean"]);
    assert.equal(await view.locator(".lean .exact-pane .exact pre").count(), 1, "the complete exact statement follows the rows");
    assert.equal(await view.locator(".lean .ribbon li").count(), 4, "a short statement is shown in full");
    assert.equal(await view.locator(".chipbtn [data-status]").getAttribute("data-status"), "formal.accepted", "the engine status is preserved");
    const text = await view.textContent();
    for (const gone of ["not accepted", "Comparator", "a.referee", "pl-fp-v1", "Toy.Defs", "its meaning reviewed"])
      assert.ok(!text.includes(gone), `"${gone}" is not in the main view`);
    // A statement whose prefix chooses a value is shown in order.
    await toyClaim(pg, "T:thm:bound");
    const bound = pg.locator("aside .view .lean .block").first();
    await bound.locator(".ribbon").waitFor();
    assert.match(await bound.locator(".ribbon li").first().textContent(), /there is/i);
  });

  await check("the status opens the audit details, where an accepted claim's missing replay is a further check", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside .chipbtn").click();
    const details = pg.locator("aside .details");
    await details.waitFor();
    const text = await details.textContent();
    assert.match(text, /Checks and evidence/);
    assert.match(text, /Independent replay: not recorded/);
    assert.ok(!/not accepted/i.test(text), "no 'not accepted' heading on an accepted claim");
    await pg.locator("aside .crumbs .back").click();
    await pg.waitForSelector("aside .view h1");
  });

  await check("the audit details list the unreviewed declarations only a witness uses, and a definition's candidates", width, async (pg) => {
    const W = "Toy.Acceptance.thm_even_add_hypotheses";
    const patch = (glob, extra) => pg.route(glob, async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      rec.clauses[0] = { ...rec.clauses[0], ...extra };
      route.fulfill({ response, json: rec });
    });
    await patch("**/toy/data/claims/*even-add*", { witness_defs: [{ name: "Toy.triangle", witnesses: [W], state: "pending" }] });
    await patch("**/toy/data/claims/*def_even*", { witness_candidates: [{ name: "Toy.triangle", uses: ["Toy.IsEven"], witnesses: [W] }] });
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside .chipbtn").click();
    const list = pg.locator("aside .details .witness-defs");
    await list.waitFor();
    assert.match(await list.textContent(), /Toy\.triangle\s*— no review/);
    await list.locator("button.ref").click();
    await pg.waitForSelector("aside .decl.inspector");
    await toyClaim(pg, "T:def:even");
    await pg.locator("aside .chipbtn").click();
    const cands = pg.locator("aside .details .witness-candidates");
    await cands.waitFor();
    assert.match(await cands.textContent(), /Toy\.triangle\s*— uses Toy\.IsEven; used by Toy\.Acceptance\.thm_even_add_hypotheses/);
  });

  // #179: a full assessment's claim lists the Lean's references to the paper's numbers that
  // disagree with the paper; one that agrees is not listed.
  await check("a full-assessment claim lists the stale paper numbers in its Lean", width, async (pg) => {
    const src = { declaration: "Toy.PaperSpec.thm_bound", module: "Toy.PaperSpec", file: "Toy/PaperSpec.lean", line: 25, where: "docstring" };
    await pg.route("**/toy/data/claims/T_thm_bound-*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      rec.references = [
        { id: "ref:000000000001", reference: "Theorem 2.4", status: "other-kind", source: src,
          message: "the docstring of Toy.PaperSpec.thm_bound (Toy/PaperSpec.lean:25) cites Theorem 2.4: the paper's 2.4 is Remark 2.4, not a theorem" },
        { id: "ref:000000000002", reference: "Theorem 2.5", status: "exact", source: src, message: "an exact reference" }];
      route.fulfill({ response, json: rec });
    });
    await toyClaim(pg, "T:thm:bound");
    const h = pg.locator("aside h3", { hasText: "Paper numbers in the Lean" });
    await h.waitFor();
    const items = await h.locator("xpath=following-sibling::ul[1]/li").allTextContents();
    assert.deepEqual(items, ["the docstring of Toy.PaperSpec.thm_bound (Toy/PaperSpec.lean:25) cites Theorem 2.4: the paper's 2.4 is Remark 2.4, not a theorem"]);
  });

  // #348: a docstring that repeats a stale number gives two references, and the claim lists
  // both, also from data whose two references share an id (as an earlier engine wrote them).
  await check("a stale number repeated in one docstring is listed twice", width, async (pg) => {
    const src = { declaration: "Toy.PaperSpec.thm_bound", module: "Toy.PaperSpec", file: "Toy/PaperSpec.lean", line: 25, where: "docstring" };
    const message = "the docstring of Toy.PaperSpec.thm_bound (Toy/PaperSpec.lean:25) cites Lemma 7.7: this version of the paper has no statement numbered 7.7";
    await pg.route("**/toy/data/claims/T_thm_bound-*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      rec.references = [0, 21].map((at) => ({ id: "ref:000000000003", reference: "Lemma 7.7", status: "absent", source: src, at, message }));
      route.fulfill({ response, json: rec });
    });
    await toyClaim(pg, "T:thm:bound");
    const h = pg.locator("aside h3", { hasText: "Paper numbers in the Lean" });
    await h.waitFor();
    assert.deepEqual(await h.locator("xpath=following-sibling::ul[1]/li").allTextContents(), [message, message]);
  });

  await check("a definition opens beside its paper definition; reviews and provenance are under Details", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside .lean .r", { hasText: "IsEven" }).first().click();
    const insp = pg.locator("aside .decl.inspector");
    await insp.waitFor();
    await pg.locator("aside h2", { hasText: "Paper · Definition 1.1" }).waitFor();
    const def = pg.locator("aside .inspection .paper-def", { has: pg.locator("h2", { hasText: "Paper · Definition 1.1" }) });
    await def.locator(".excerpt .katex").first().waitFor();
    assert.match(await def.locator(".excerpt").textContent(), /triangular number/, "the paper's definition, typeset from its source");
    const extra = insp.locator("details.extra");
    assert.equal(await extra.getAttribute("open"), null, "Details is folded");
    assert.ok(!(await insp.locator(":scope > :not(details)").allTextContents()).join(" ").includes("a.referee"));
    await extra.locator("summary").click();
    assert.match(await extra.textContent(), /a\.referee/);
  });

  await check("the menu holds the occasional actions", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside button[aria-label='More']").click();
    const items = await pg.locator("aside .menu > a, aside .menu > button").allTextContents();
    assert.ok(items.includes("Open as a page") && items.some((i) => /Copy (link|reference)/.test(i)));
    const reports = pg.locator("aside .menu a", { hasText: "View existing reports" });
    assert.match(await reports.getAttribute("href"), /^https:\/\/github\.com\/cgarryZA\/MachineChecked\/issues\?q=.*T%3Athm%3Aeven-add/);
  });
}

for (const width of [1300, 390]) {
    await check("a linked symbol of the paper and its Lean variable highlight each other", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    const tex = pg.locator("aside .view .paper .tex");
    await tex.locator("[data-sym]").first().waitFor();
    assert.equal(await tex.locator("[data-sym]").count(), 4, "a and b, twice each, in the mathematics only");
    await tex.locator("[data-sym]").first().hover();
    const lean = pg.locator("aside .view .lean");
    assert.ok(await lean.locator(".var.hl[data-var='0']").count() > 0, "a is highlighted in the Lean");
    assert.equal(await lean.locator(".v.hl").textContent(), "a");
    assert.match(await pg.locator("aside .view .linkby").textContent(), /Symbol correspondence by human:A-Referee/);
    await pg.mouse.move(0, 0);
    await lean.locator(".concl .var[data-var='1']").first().hover();
    assert.equal(await tex.locator("[data-sym].hl").count(), 2, "both b in the paper");
  });
}

for (const width of [1300, 390]) {
  await check("a link to one occurrence of a variable lights that occurrence only", width, async (pg) => {
    // The probe gives each occurrence of a variable its own identity (`at`) beside the variable's
    // number (#73); a link may name one occurrence.
    await pg.route("**/toy/data/claims/*even-add*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      const cl = rec.clauses.find((c) => c.spec === "Toy.PaperSpec.thm_even_add");
      // An identity no sub-term of the data has: the occurrence's own.
      const at = "/occurrence-of-b";
      cl.statement.conclusion.segments = cl.statement.conclusion.segments.map((x) => x.var === 1 ? { ...x, at } : x);
      rec.symbols = [{ symbol: { tex: "b", occurrence: "all" }, lean: { decl: cl.spec, at }, by: "human:A-Referee", stale: false }];
      route.fulfill({ response, json: rec });
    });
    await toyClaim(pg, "T:thm:even-add");
    const tex = pg.locator("aside .view .paper .tex");
    await tex.locator("[data-sym]").first().waitFor();
    await tex.locator("[data-sym]").first().hover();
    const lean = pg.locator("aside .view .lean");
    assert.deepEqual(await lean.locator(".in").allTextContents(), ["b"], "the conclusion's b, not the binder");
    assert.equal(await lean.locator(".var.hl").count(), 0, "a link to an occurrence is not a link to the variable");
  });

await check("in the local reader a symbol is linked by choosing it and clicking its variable", width, async (pg) => {
    await pg.goto(origin + `/toyedit/#/r/${TOY.release}/read/T/${encodeURIComponent("T:thm:even-add")}`);
    await pg.waitForSelector("aside .view h1");
    const mk = pg.locator("aside .mklink");
    await mk.locator("summary").click();
    const chips = await mk.locator(".chip").evaluateAll((cs) => cs.map((c) => c.dataset.tex));
    assert.ok(chips.includes("a") && chips.includes("b"), chips.join(","));
    await mk.locator(".chip[data-tex='a']").click();
    await pg.locator("aside .view .lean .ribbon .v", { hasText: /^a$/ }).click();
    await mk.locator("input.who").fill("Test Referee");
    assert.match(await mk.textContent(), /to the variable a of Toy\.PaperSpec\.thm_even_add/);
    // Saving posts the link, then reloads the page.
    const sent = posted.length, reloaded = pg.waitForEvent("load").then(() => true, () => false);
    await mk.locator("button", { hasText: "Save link" }).click();
    assert.ok(await until(() => posted.length > sent), "the link is posted");
    assert.ok(await reloaded, "the page reloads after saving");
    // The variable is sent by its number: two variables can share a name (#73).
    assert.deepEqual(posted.at(-1), { action: "add", claim: "T:thm:even-add", tex: "a",
      decl: "Toy.PaperSpec.thm_even_add", var: "0", by: "human:Test-Referee" });
    // A published audit offers no such control.
    await toyClaim(pg, "T:thm:even-add");
    assert.equal(await pg.locator("aside .mklink").count(), 0);
  });

  await check("a link that takes some occurrences of a symbol marks only those", width, async (pg) => {
    // Two objects printed with one symbol are linked apart, each naming its occurrences (#99).
    await pg.route("**/toy/data/claims/*even-add*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      const spec = "Toy.PaperSpec.thm_even_add";
      rec.symbols = [
        { symbol: { tex: "a", occurrence: [2], of: 2, object: "a in the sum" }, lean: { decl: spec, var: 0 }, by: "human:A-Referee", stale: false },
        { symbol: { tex: "b", occurrence: "all" }, lean: { decl: spec, var: 1 }, by: "human:A-Referee", stale: false }];
      route.fulfill({ response, json: rec });
    });
    await toyClaim(pg, "T:thm:even-add");
    const tex = pg.locator("aside .view .paper .tex");
    await tex.locator("[data-sym]").first().waitFor();
    assert.deepEqual(await tex.locator("[data-sym]").allTextContents(), ["b", "a", "b"], "the a of the sum only");
    await tex.locator("[data-sym]", { hasText: "a" }).hover();
    assert.match(await pg.locator("aside .view .linkby").textContent(), /Symbol correspondence by human:A-Referee for a in the sum\./);
  });

  await check("in the local reader a definition's symbol is linked at the occurrences chosen", width, async (pg) => {
    await pg.goto(origin + `/toyedit/#/r/${TOY.release}/read/T/${encodeURIComponent("T:def:even")}`);
    await pg.waitForSelector("aside .view h1");
    const mk = pg.locator("aside .mklink");
    await mk.locator("summary").click();
    await mk.locator(".chip[data-tex='n']").click();
    assert.match(await mk.locator(".occ").textContent(), /It occurs 5 times/);
    await mk.locator("[data-occ='1']").check();
    await mk.locator("[data-occ='2']").check();
    // A claim that only defines: a sub-term of the definition's body is the link's Lean side.
    const even = pg.locator("aside .view .lean .defn.readable[data-decl='Toy.IsEven']");
    await even.locator(".body .p", { hasText: "2" }).first().click();
    await mk.locator("input.who").fill("Test Referee");
    const save = mk.locator("button", { hasText: "Save link" });
    assert.ok(await save.isDisabled(), "occurrences linked apart are one object, which the link names");
    await mk.getByRole("textbox", { name: "The object of the paper" }).fill("n, the number defined");
    const sent = posted.length, reloaded = pg.waitForEvent("load").then(() => true, () => false);
    await save.click();
    assert.ok(await until(() => posted.length > sent), "the link is posted");
    assert.ok(await reloaded, "the page reloads after saving");
    const at = posted.at(-1).at;
    assert.ok(typeof at === "string" && at.startsWith("/"), "a sub-term, by its identity: " + at);
    assert.deepEqual(posted.at(-1), { action: "add", claim: "T:def:even", tex: "n", decl: "Toy.IsEven", at,
      by: "human:Test-Referee", occurrences: [1, 2], object: "n, the number defined" });
  });

  await check("a link that no longer holds says why, and is not drawn", width, async (pg) => {
    await pg.route("**/toyedit/data/claims/*even-add*", async (route) => {
      const response = await route.fetch();
      const rec = await response.json();
      rec.symbols = [{ symbol: { tex: "b" }, lean: { decl: "Toy.PaperSpec.thm_even_add", term: 3, in: "c" }, by: "human:Old",
                       stale: true, stale_because: ["positional"] }];
      route.fulfill({ response, json: rec });
    });
    await pg.goto(origin + `/toyedit/#/r/${TOY.release}/read/T/${encodeURIComponent("T:thm:even-add")}`);
    await pg.waitForSelector("aside .view h1");
    const mk = pg.locator("aside .mklink");
    await mk.locator("summary").click();
    const old = mk.locator("[data-link='b']");
    assert.match((await old.textContent()).replace(/\s+/g, " "), /\(stale\).*Not shown: it names its Lean object by place and number in an earlier display\. Link it again, or remove it\./);
    assert.equal(await pg.locator("aside .view .paper .tex [data-sym]").count(), 0, "a stale link is not drawn");
  });

  await check("a linked definition keeps its parameters in order, and a recursive one shows its equations", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:def:multiple")}`);
    const lean = pg.locator("aside .view section.lean");
    const mult = lean.locator(".defn.readable[data-decl='Shape.MultipleAbove']");
    await mult.waitFor();
    assert.match(await mult.locator(".head").textContent(), /\(b : Nat\)\s*\{m : Nat\}\s*\(n : Nat\)\s*:\s*Prop/);
    assert.equal((await mult.locator(".body").textContent()).trim(), "∃ (q : Nat), b ≤ q ∧ n = m * q");
    const fib = lean.locator(".defn.readable[data-decl='Shape.fib'] .eq");
    assert.equal(await fib.count(), 3);
    assert.match(await fib.nth(0).textContent(), /Shape\.fib 0 = 0/);
    const exact = pg.locator("aside .view .exact-pane .defn.exact[data-decl='Shape.fib']");
    assert.equal(await exact.locator(".thm").count(), 3);
    assert.match(await exact.locator(".src").textContent(), /\| n \+ 2 => fib n \+ fib \(n \+ 1\)/);
  });

  await check("properties carried by a type stay with their object: given, assumed or produced", width, async (pg) => {
    const open = async (id) => {
      await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      const st = pg.locator("aside .view :not(.suggestion) > .stmt");
      await st.waitFor();
      return st;
    };
    // A supplied solution: its proof fields are in its type, one inherited from its parent; the
    // extra assumption is a row of its own.
    let st = await open("P:thm:supplied");
    const given = st.locator(".ribbon .carried.given");
    assert.equal(await given.count(), 1);
    const start = given.locator(".prop[data-field='start']");
    assert.match(await start.textContent(), /s\.path 0 = d.*field start of Solution, from Base/s);
    assert.match(await given.locator(".prop[data-field='le_bound']").textContent(), /∀ \(n : Nat\), s\.path n ≤ s\.bound/);
    assert.match(await given.locator(".data").textContent(), /s\.path : Nat → Nat, s\.bound : Nat/);
    // The extra assumption is about s alone, so it is shown under s, as a condition of its own.
    assert.match(await st.locator(".ribbon .line.sub").textContent(), /assume\s*\(h\)\s*s\.bound ≤ 5/);
    assert.equal(await st.locator(".ribbon .subc .carried").count(), 0, "an assumption is not a property of a type");
    // The assumed existence keeps its solution inside the assumption; the result's own solution
    // is produced.
    st = await open("P:thm:assumed");
    const inner = st.locator(".ribbon li.hypothesis .inner");
    assert.equal(await inner.count(), 1);
    assert.match(await inner.textContent(), /Inside this assumption:\s*for every\s*d.*if\s*Shape\.Admissible d\s*then\s*there is\s*s/s);
    assert.equal(await inner.locator(".carried.inside .prop").count(), 2);
    assert.equal(await st.locator(".ribbon > li.exists .carried.produced").count(), 1);
    // An established solution is produced under the condition on d.
    st = await open("P:thm:produced");
    assert.deepEqual(await st.locator(".ribbon > li").evaluateAll((ls) => ls.map((l) => l.className.split(" ").find((c) => ["forall", "hypothesis", "exists"].includes(c)))), ["forall", "exists"]);
    assert.match(await st.locator(".ribbon > li.forall .line.sub").textContent(), /assume\s*\(h1\)\s*Shape\.Admissible d/);
    assert.match(await st.locator(".carried.produced .basis").textContent(), /Producing this object establishes/);
    // A subtype's predicate is in its type; a class instance stays an input with its law.
    st = await open("P:thm:positive");
    assert.match(await st.locator(".carried.given .prop[data-field='property']").textContent(), /0 < p\.val/);
    st = await open("P:thm:single");
    assert.match(await st.locator(".carried.given .prop[data-field='uniq']").textContent(), /∀ \(a : T\), a = default.*field uniq of Single/s);
    assert.match(await st.locator(".concl").textContent(), /Subsingleton T/);
    // A supplied measure space carries its laws; that it is a probability space is an assumption
    // stating what its field says.
    st = await open("P:thm:probability");
    assert.match(await st.locator(".carried.given .prop[data-field='measure_empty']").textContent(), /field measure_empty of MeasureData/);
    assert.match(await st.locator(".carried.states .prop[data-field='measure_univ']").textContent(), /it states.*= 1/s);
    assert.equal(await st.locator(".carried.produced").count(), 0);
    // Inside a negation the solution is not produced: its properties stay local to that claim.
    st = await open("P:thm:none-large");
    assert.equal(await st.locator(".carried.produced").count(), 0, "a negated existence produces nothing");
    assert.match(await st.locator(".concl .carried.local .basis").textContent(), /within the clause that contains it/);
    // A sub-term of a property can be selected, and the exact Lean selects the same one.
    await open("P:thm:supplied");
    await pg.locator("aside .view .carried .prop[data-field='start'] .p", { hasText: "0" }).first().click();
    assert.ok(await pg.locator("aside .view .carried .prop[data-field='start'] .in").count() > 0);
    const exactField = pg.locator(".exact-pane .carried .field[data-field='start']");
    assert.match(await exactField.textContent(), /s\.start : s\.path 0 = d/);
    assert.match(await exactField.locator(".origin").textContent(), /Shape\.Base\.start/);
    assert.ok(await exactField.locator(".in").count() > 0, "the exact view selects the same sub-term");
  });

  await check("a structure shows the fields it adds to its parent, and a construction what its value carries", width, async (pg) => {
    const open = async (id) => {
      await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      await pg.locator("aside .view section.lean .defn").first().waitFor();
      return pg.locator("aside .view section.lean");
    };
    // The concrete structure extends the abstract one: its inherited fields are listed under
    // the parent, and what it adds apart, each stated of an object `self`.
    let lean = await open("P:def:profile");
    const con = lean.locator(".defn.readable[data-decl='Shape.Concrete'] .made");
    await con.waitFor();
    const names = (loc) => loc.evaluateAll((ls) => ls.map((l) => l.dataset.field));
    assert.match(await con.locator(".lbl").first().textContent(), /inherited from\s*Profile/i);
    assert.deepEqual(await names(con.locator(".fields:not(.added) .field")), ["f", "C", "bound"]);
    assert.deepEqual(await names(con.locator(".fields.added .field")), ["N", "support", "p", "periodic"]);
    assert.match(await con.locator(".field[data-field='support']").textContent(), /support\s*:\s*∀ \(n : Nat\), self\.N ≤ n → self\.f n = 0/);
    assert.match(await con.locator(".field[data-field='N']").textContent(), /data/);
    const prof = lean.locator(".defn.readable[data-decl='Shape.Profile'] .made");
    assert.deepEqual(await names(prof.locator(".field")), ["f", "C", "bound"]);
    assert.equal(await prof.locator(".fields.added").count(), 0, "a structure without a parent adds to none");
    const exact = pg.locator("aside .view .exact-pane .defn.exact[data-decl='Shape.Concrete']");
    assert.match(await exact.locator(".thm[data-field='support']").textContent(), /Shape\.Concrete\.support.*self\.N ≤ n/s);
    // A construction's value carries the fields its definition establishes; a helper that
    // accepts the structure has them in its input's type, apart from its hypothesis.
    lean = await open("P:thm:build");
    const val = lean.locator(".defn.readable[data-decl='Shape.build'] .made.value");
    await val.waitFor();
    assert.match(await val.textContent(), /Established by this definition/);
    assert.match(await val.locator(".field[data-field='support']").textContent(), /\(Shape\.build N\)\.N ≤ n → \(Shape\.build N\)\.f n = 0/);
    assert.equal(await val.locator(".field[data-field='N']").count(), 0, "data is not a property");
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:vanishes")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt");
    await st.waitFor();
    assert.match(await st.locator(".carried.given .prop[data-field='support']").textContent(), /c\.N ≤ n → c\.f n = 0.*field support of Concrete/s);
    assert.match(await st.locator(".ribbon > li.hypothesis").textContent(), /assume\s*\(h\)\s*c\.N ≤ n/);
  });

  await check("a definition expands at the arguments of each application, beside the statement", width, async (pg) => {
    // An expansion is fetched from its own file when it is opened, not with the claim.
    const fetched = [];
    pg.on("request", (r) => { if (r.url().includes("/data/expansions/")) fetched.push(r.url()); });
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:jet")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
    await st.locator(".ribbon").waitFor();
    assert.equal(fetched.length, 0, "no expansion is fetched before one is opened");
    // The assumption at order n + 5 and the conclusion at n + 4 are different applications.
    const chips = st.locator("button.xb");
    assert.equal(await chips.count(), 2);
    await chips.nth(0).click();
    let xp = st.locator(".inspect .xp");
    await xp.waitFor();
    assert.match(await xp.locator(".occ").textContent(), /Shape\.JetBound f S \(n \+ 5\) C/);
    assert.match((await xp.locator(".args").textContent()).replace(/\s+/g, " "), /k := n \+ 5/);
    assert.match(await xp.locator(".body").textContent(), /∀ \(j : Nat\), j ≤ n \+ 5 → ∀ \(x : Nat\), S x → f j x ≤ C/);
    assert.equal(fetched.length, 1, "opening an expansion fetches it");
    assert.equal(await st.locator(".ribbon .in").count() > 0, true, "the application stays visible and selected");
    await chips.nth(1).click();
    xp = st.locator(".inspect .xp");
    assert.match(await xp.locator(".body").textContent(), /j ≤ n \+ 4/);
    assert.doesNotMatch(await xp.locator(".body").textContent(), /n \+ 5/);

    // A partial application keeps the parameter it still needs; the definition it is passed to
    // expands with it applied, and that application expands in turn.
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:below")}`);
    const every = pg.locator("aside .view :not(.suggestion) > .stmt").filter({ hasText: "Shape.Every" }).first();
    await every.locator(".ribbon").waitFor();
    await every.locator("button.xb", { hasText: /^Shape\.AllBelow 7$/ }).click();
    xp = every.locator(".inspect .xp").first();
    assert.match((await xp.locator(".line").textContent()).replace(/\s+/g, " "), /still to supply \(v : Fin 2 → Nat\): ∀ \(i : Fin 2\), v i ≤ 7/);
    assert.match((await xp.locator(".args").textContent()).replace(/\s+/g, " "), /α := Nat \(implicit\) ?instance := instLENat ?bound := 7 ?n := 2 \(implicit\)/);
    await every.locator("button.xb", { hasText: /^Shape\.Every/ }).first().click();
    xp = every.locator(".inspect .xp").first();
    await xp.locator("button.xb").click();
    assert.match(await xp.locator(".xp .body").textContent(), /∀ \(i : Fin 2\), v i ≤ 7/);
    // A bound variable of the definition is renamed apart from the statement's own i.
    const below = pg.locator("aside .view :not(.suggestion) > .stmt").filter({ hasText: "Shape.AllBelow i v" }).first();
    await below.locator("button.xb").first().click();
    assert.match(await below.locator(".inspect .xp .body").textContent(), /∀ \(i_1 : Fin 3\), v i_1 ≤ i$/);

    // A definition by equations shows the equation that applies, specialised, with its case
    // condition and its theorem's name.
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:steps")}`);
    const steps = pg.locator("aside .view :not(.suggestion) > .stmt").filter({ hasText: "Shape.steps" }).first();
    await steps.locator(".concl").waitFor();
    await steps.locator("button.xb").click();
    xp = steps.locator(".inspect .xp");
    assert.match((await xp.locator(".eq").textContent()).replace(/\s+/g, " "), /Shape\.steps \(k \+ 3\) = if h : k \+ 3 = 0 then 0 else Shape\.steps \(k \+ 3 - 1\) \+ 1 expand Shape\.steps \(k \+ 3 - 1\) Shape\.steps\.eq_1/);
    const pick = pg.locator("aside .view :not(.suggestion) > .stmt").filter({ hasText: "Shape.pick" }).first();
    await pick.locator("button.xb").click();
    xp = pick.locator(".inspect .xp");
    assert.match((await xp.locator(".eq").textContent()).replace(/\s+/g, " "), /provided \(x_3 : k \+ 1 = 0 → False\): Shape\.pick \(k \+ 1\) 0 = 1 Shape\.pick\.eq_2/);
    assert.match(await xp.textContent(), /Not applying here: Shape\.pick\.eq_1, Shape\.pick\.eq_3/);
    assert.match((await xp.locator(".args").textContent()).replace(/\s+/g, " "), /argument 1 := k \+ 1/);
    if (width === 1300) await pg.screenshot({ path: process.env.SHOT_DIR ? path.join(process.env.SHOT_DIR, "expansion.png") : path.join(os.tmpdir(), "mc-expansion.png") });
  });

  await check("a definition with more equations than its record lists loads the others when asked", width, async (pg) => {
    const fetched = [];
    pg.on("request", (r) => { if (r.url().includes("/data/expansions/")) fetched.push(r.url()); });
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:def:digit")}`);
    const view = pg.locator("aside .view");
    const val = view.locator(".lean .defn.readable[data-decl='Shape.Digit.val']");
    await val.locator(".eq").first().waitFor();
    // A definition by equations shows its type, then the first 64 of its seventy equations.
    assert.match(await val.locator(".head").textContent(), /Shape\.Digit\.val\s*:\s*Shape\.Digit → Nat/);
    assert.equal(await val.locator(".eq").count(), 64);
    assert.equal(fetched.length, 0, "the further equations are fetched only when asked for");
    assert.match(await val.locator("button.more").textContent(), /Show the 6 further equations/);
    await val.locator("button.more").click();
    await val.locator(".eq[data-eq='Shape.Digit.val.eq_70']").waitFor();
    assert.equal(await val.locator(".eq").count(), 70);
    assert.equal(fetched.length, 1, "one page holds the six");
    assert.equal(await val.locator("button.more").count(), 0);
    const exact = view.locator(".exact-pane .defn.exact[data-decl='Shape.Digit.val']");
    assert.equal(await exact.locator(".thm").count(), 64);
    await exact.locator("button.more").click();
    await exact.locator(".thm[data-eq='Shape.Digit.val.eq_70']").waitFor();
    assert.equal(await exact.locator(".thm").count(), 70);
    // At the last digit the seventieth equation applies; the 69 others are named, folded.
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:digit")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
    await st.locator("button.xb").click();
    const xp = st.locator(".inspect .xp");
    assert.match(await xp.locator(".eq").textContent(), /Shape\.Digit\.val\.eq_70/);
    assert.match(await xp.locator("details.na summary").textContent(), /^Not applying here: Shape\.Digit\.val\.eq_1, .* and 57 more$/);
  });

  await check("a statement keeps its order, with each object's own conditions beside it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt");
    await st.locator(".ribbon").waitFor();
    const rows = (await st.locator(".ribbon > li").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
    assert.equal(rows.length, 7, rows.join(" | "));
    assert.match(rows[0], /^for all E ?: ?Type given instance Inhabited E$/i, "an instance that supplies data is given");
    assert.match(rows[1], /^for all j ?: ?Nat assume \(hj\) 1 ≤ j$/i);
    assert.match(rows[2], /^for all k ?: ?Nat$/i);
    assert.match(rows[3], /^assume \(hjk\) j ≤ k$/i, "a condition on two objects stays a row of its own");
    assert.match(rows[5], /^there is C ?: ?Nat$/i);
    assert.match(await st.locator(".concl .op").textContent(), /all of the following/);
    assert.equal(await st.locator(".concl .parts > li").count(), 2);
  });

  await check("a reading shows its coverage and, separately, its basis", width, async (pg) => {
    const reading = async (id) => {
      await pg.goto(origin + `/basis/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      const box = pg.locator(".coverage[data-basis]");
      await box.waitFor();
      return { text: (await box.textContent()).replace(/\s+/g, " ").trim(), basis: await box.getAttribute("data-basis"),
               tone: await box.getAttribute("data-tone") };
    };
    const comp = await reading("P:thm:layout");
    assert.equal(comp.basis, "reviewed_composition");
    assert.match(comp.text, /^Every clause, by an argument combining Lean results/);
    assert.match(comp.text, /The auditor's argument: Apply Shape\.layout twice, once for each bound\. Lean has not checked this combination\.\s*Next step: State the combination as one Lean result\./);
    assert.match(comp.text, /The auditor's reading, by A\. Auditor/);
    assert.notEqual(comp.tone, "full", "a composition is not drawn as a Lean result");
    const bridge = await reading("P:thm:witnesses");
    assert.equal(bridge.basis, "checked_bridge");
    assert.match(bridge.text, /^Every clause, through a checked bridge/);
    assert.match(bridge.text, /Bridge: Shape\.witnesses\. Lean checks its proof and that its type is exactly the target\./);
    assert.match(bridge.text, /Target: Shape\.Spec\.witnesses\. The auditor read it against the paper\./);
    const open = await reading("P:thm:shapes");
    assert.equal(open.basis, "unspecified");
    assert.match(open.text, /^Unresolved/);
    assert.match(open.text, /Open question: Is the paper's set finite\?\s*Would decide it: Its Section 1\./);
    // A referenced declaration opens in the inspector.
    await reading("P:thm:layout");
    await pg.locator(".coverage[data-basis] button.ref").first().click();
    await pg.waitForFunction(() => decodeURIComponent(location.hash).includes("Shape.layout"));
  });

  await check("a review shows the coverage recorded with its verdict, never more than the engine read", width, async (pg) => {
    const report = async (id) => {
      await pg.goto(origin + `/basis/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      const r = pg.locator("details.review");
      await r.locator(":scope > summary").click();
      const box = r.locator(".report-coverage");
      await box.waitFor();
      return { text: (await box.textContent()).replace(/\s+/g, " ").trim(), basis: await box.getAttribute("data-basis") };
    };
    const bridge = await report("P:thm:layout");
    assert.equal(bridge.basis, "reviewed_composition");
    assert.match(bridge.text, /^Every clause, by an argument combining Lean results \(the reviewer's coverage, recorded with the verdict\)/);
    assert.match(bridge.text, /Lean has not checked this combination\.\s*Next step: State the combination as one Lean result\./);
    assert.match(bridge.text, /Recorded as a checked bridge \(Shape\.layout for Shape\.Spec\.layout\); no bridge Lean checks now: the target is not the version the reviewer read\./);
    assert.doesNotMatch(bridge.text, /through a checked bridge/);
    const open = await report("P:thm:shapes");
    assert.equal(open.basis, "unspecified");
    assert.match(open.text, /^Unresolved/);
    assert.match(open.text, /Open question: Is the set finite\?\s*Would decide it: Its Section 1\./);
  });

  await check("a \"there is\" inside a conclusion shows its witness's type and scope", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:witnesses")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
    await st.locator(".concl").waitFor();
    const parts = (await st.locator(".concl .body > .parts > li").allTextContents()).map((t) => t.replace(/\s+/g, ""));
    assert.equal(parts.length, 2, parts.join(" | "));
    assert.equal(parts[0], "thereisx:Nat→Natsuchthatallofthefollowingxj=jj≤xj");
    assert.equal(parts[1], "thereisx:Boolsuchthatx=true");
    // The two x are different variables: pointing at one highlights only its own occurrences.
    await st.locator(".concl .var[data-var='1']").first().hover();
    assert.equal(await st.locator(".concl .var.hl").count(), 2, "both occurrences of the first x");
    assert.equal(await st.locator(".var.hl[data-var='2']").count(), 0, "not the other x");
    await st.locator(".concl .var[data-var='2']").first().click();
    await pg.mouse.move(0, 0);
    assert.match((await st.locator(".inspect").textContent()).replace(/\s+/g, " "), /x ?: ?Bool.*there is/);
  });

  await check("negation, implication and \"for every\" inside a conclusion keep their scope", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:shapes")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
    await st.locator(".concl").waitFor();
    assert.match((await st.locator(".ribbon").textContent()).replace(/\s+/g, " "), /assume instance Nonempty E/);
    const parts = (await st.locator(".concl .body > .parts > li").allTextContents()).map((t) => t.replace(/\s+/g, ""));
    assert.equal(parts.length, 2, parts.join(" | "));
    assert.equal(parts[0], "itisnotthecasethatthereisx:Natsuchthatx<0");
    assert.equal(parts[1], "atleastoneofthefollowingforeveryn:Nat,0≤nif1=1thenthereism:Natsuchthatm=1");
  });

  await check("each binder reads in its scope: an assumption's own existence stays inside it", width, async (pg) => {
    const open = async (id) => {
      await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
      await st.locator(".concl").waitFor();
      return st;
    };
    const flat = (t) => t.replace(/\s+/g, "");
    const reading = async (st, v) => {
      await st.locator(`.var[data-var='${v}']`).first().click();
      await pg.mouse.move(0, 0);
      return (await st.locator(".inspect").textContent()).replace(/\s+/g, " ");
    };
    // (h : ∀ x, A x → ∃ y, B x y): the assumption's structure is shown inside it, and its y is
    // a variable of its own, apart from the y the statement establishes.
    let st = await open("P:thm:conditional");
    const within = st.locator(".ribbon li .inner.within");
    assert.equal(await within.count(), 1, "only the assumption that quantifies shows its structure");
    assert.equal(flat(await within.textContent()), "Insidethisassumption:foreveryx:Nat,ifAxthenthereisy:NatsuchthatBxy");
    const rows = (await st.locator(".ribbon > li").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
    assert.match(rows.at(-1), /^there is y ?: ?Nat$/);
    await within.locator(".var[data-var='7']").first().hover();
    assert.equal(await st.locator(".var.hl").count(), 1, "only the assumption's y");
    assert.equal(await st.locator(".concl .var.hl").count(), 0, "not the statement's y");
    assert.match(await reading(st, 7), /y ?: ?Nat.*Inside an assumption: not chosen by the statement/);
    assert.match(await reading(st, 5), /y ?: ?Nat.*Chosen by the statement \(there is\)/);
    // An existence established under a premise, one inside a side of an equivalence and one in
    // an alternative: each keeps its place.
    st = await open("P:thm:premised");
    const parts = (await st.locator(".concl .body > .parts > li").allTextContents()).map(flat);
    assert.deepEqual(parts, ["ifPthenthereisx:Natsuchthatx=0",
      "thefollowingareequivalentQthereisn:Natsuchthatn=n",
      "atleastoneofthefollowingthereisx:Natsuchthatx=1Q"]);
    // P, Q and hq are 0, 1 and 2; the variables bound inside the conclusion follow them.
    const vs = await st.locator(".concl .var").evaluateAll((es) => [...new Set(es.map((e) => +e.dataset.var))].filter((v) => v >= 3).sort());
    assert.deepEqual(vs, [3, 4, 5], "three variables bound inside, two of them named x");
    assert.match(await reading(st, vs[0]), /Chosen by the statement \(there is\), for the part it belongs to/);
    assert.match(await reading(st, vs[1]), /Inside one side of an equivalence/);
    assert.match(await reading(st, vs[2]), /Inside one alternative of an “or”/);
    // ∃ Φ : G →[Nat] H, A Φ ∧ B Φ: one witness with its whole type, in both parts; each
    // assumption's Φ is its own.
    st = await open("P:thm:one-map");
    const last = (await st.locator(".ribbon > li").allTextContents()).at(-1).replace(/\s+/g, " ").trim();
    assert.match(last, /^there is Φ ?: ?G →\[Nat\] H$/);
    await st.locator(".concl .var[data-var='7']").first().hover();
    assert.equal(await st.locator(".var.hl").count(), 2, "the witness in both of its parts");
    assert.equal(await st.locator(".ribbon .inner.within").count(), 2);
    assert.equal(await st.locator(".ribbon .inner.within .var.hl").count(), 0, "not the assumptions' Φ");
  });

  await check("clicking inside an expression selects it, and each click widens it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt");
    await st.locator(".ribbon").waitFor();
    const plus = st.locator(".concl .parts > li").nth(1).locator(".p", { hasText: "+" }).first();
    const text = async () => (await st.locator(".inspect.term code").textContent()).trim();
    await plus.click();
    assert.equal(await text(), "n + x");
    await plus.click();
    assert.equal(await text(), "n + x ≤ n + C");
    await plus.click();
    assert.equal(await st.locator(".inspect.term").count(), 0, "a click past the largest releases it");
  });

  await check("a sub-term selected in one view of a statement is selected in the other", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
    await st.locator(".ribbon").waitFor();
    const exact = pg.locator("aside .exact pre").first();
    await exact.waitFor();
    const lit = async (loc) => (await loc.locator(".in").allTextContents()).join("").trim();
    // Chosen in the readable statement: the same sub-term, found by its identity in the
    // proposition, is lit in the exact Lean (#73).
    await st.locator(".concl .parts > li").nth(1).locator(".p", { hasText: "+" }).first().click();
    assert.equal(await lit(st), "n + x", "readable: " + await lit(st));
    assert.equal(await lit(exact), "n + x", "exact: " + await lit(exact));
    // And the reverse: chosen in the exact Lean, lit in the readable statement.
    await exact.locator(".c.p, .p", { hasText: "≤" }).first().click();
    const there = await lit(exact);
    assert.ok(there.includes("≤"), there);
    assert.equal(await lit(st), there);
  });

  await check("a selection belongs to its claim: choosing another claim clears it", width, async (pg) => {
    const go = async (id) => {
      await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent(id)}`);
      const st = pg.locator("aside .view :not(.suggestion) > .stmt").first();
      await st.locator(".concl").waitFor();
      return st;
    };
    let st = await go("P:thm:layout");
    await st.locator(".concl .parts > li").nth(1).locator(".p", { hasText: "+" }).first().click();
    const exact = pg.locator("aside .exact pre").first();
    assert.equal((await exact.locator(".in").allTextContents()).join("").trim(), "n + x");
    await go("P:thm:witnesses");
    st = await go("P:thm:layout");
    await exact.waitFor();
    assert.equal(await st.locator(".in").count(), 0, "nothing selected in the readable statement");
    assert.equal(await exact.locator(".in").count(), 0, "nor in the exact Lean");
  });

  await check("a name's plain-English note appears only on request, beside the name", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt");
    await st.locator(".ribbon").waitFor();
    assert.equal(await st.locator(".note").count(), 0, "no note by default");
    await st.locator("button.g", { hasText: "Inhabited" }).click();
    const note = st.locator(".note");
    assert.match(await note.textContent(), /Inhabited.*designated element.*the Lean definition is what the statement uses/s);
    await st.locator("button.g", { hasText: "Inhabited" }).click();
    assert.equal(await st.locator(".note").count(), 0, "a second click closes it");
  });

  await check("hovering a variable highlights it everywhere; a click holds it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view :not(.suggestion) > .stmt");
    await st.locator(".ribbon").waitFor();
    const x = st.locator(".concl .var[data-var='6']").first();
    await x.hover();
    assert.equal(await st.locator(".var.hl").count(), 2, "both occurrences of x in the conclusion");
    assert.equal(await st.locator(".v.hl").textContent(), "x", "and its binder");
    await x.click();
    await pg.mouse.move(0, 0);
    const insp = st.locator(".inspect");
    assert.match((await insp.textContent()).replace(/\s+/g, " "), /x ?: ?Nat.*Any value \(for all\)/);
    await st.locator(".ribbon .v", { hasText: "j" }).click();
    assert.match((await insp.textContent()).replace(/\s+/g, " "), /j ?: ?Nat.*1 ≤ j/);
    await st.locator(".ribbon .v", { hasText: "C" }).click();
    assert.match(await insp.textContent(), /Chosen by the statement \(there is\)/);
  });
}

for (const width of [1300, 390]) {
  await check("structured statuses agree across coverage, passport, evidence and public paper", width, async (pg) => {
    const cases = [
      ["pending", 1, "formal.review-pending", "pending", "not-run"],
      ["author", 2, "formal.author-reviewed", "author-reviewed", "not-run"],
      ["accepted", 3, "formal.accepted", "reviewed", "not-run"],
      ["replayed", 4, "formal.review-pending", "pending", "pass"],
      ["stale-replay", 5, "formal.accepted", "reviewed", "unverified"],
      ["pdf", 6, "formal.accepted", "reviewed", "pass"],
      ["source-mismatch", 7, "formal.accepted", "reviewed", "pass"],
    ];
    for (const [name, number, code, review, replay] of cases) {
      await pg.goto(origin + "/states/#/r/states/coverage");
      assert.match(await pg.locator(".coverage h1").textContent(), /Overview/);
      const cov = pg.locator(".coverage .paper").filter({ has: pg.locator("h2", { hasText: new RegExp(`^${name}$`) }) });
      const chip = cov.locator(`.claims li[data-status='${code}'] [data-status]`);
      await chip.waitFor();
      const label = await chip.textContent();
      await pg.goto(origin + `/states/#/r/states/claim/${encodeURIComponent(name + ":claim")}`);
      const passport = pg.locator(".view .chipbtn [data-status]");
      await passport.waitFor();
      assert.equal(await passport.textContent(), label);
      assert.equal(await passport.getAttribute("data-status"), code);
      assert.ok(!/deliberately misleading/.test(await pg.locator(".view").textContent()));
      assert.equal(await pg.locator(".view .verdict").count(), 0, "single proved clause adds no redundant verdict");
      await pg.locator(".view .chipbtn").click();
      for (const [dim, state] of [["formal", "proved"], ["review", review], ["replay", replay]]) {
        const rung = pg.locator(`.details [data-dimension='${dim}']`);
        assert.equal(await rung.getAttribute("data-state"), state);
      }
      if (name === "pdf") assert.match(await pg.locator("[data-dimension='source']").textContent(), /PDF hash matched.*approximate location/);
      if (name === "source-mismatch") assert.equal(await pg.locator("[data-dimension='source']").getAttribute("data-state"), "fail");
      await pg.goto(origin + `/states-public/#/r/paper/claim/${encodeURIComponent("P:" + name + ":claim")}`);
      await pg.locator(".view .chipbtn [data-status]").waitFor();
      assert.equal(await pg.locator(".view .chipbtn [data-status]").getAttribute("data-status"), code);
      assert.match(await pg.locator(".recorded").textContent(), /Synthetic reviewer/);
      assert.ok(!(await pg.locator(".recorded").textContent()).includes(label), "attribution does not repeat the verdict");
    }
    await pg.goto(origin + "/states-public/?project=b%2Fproject#/r/paper/claim/P%3Aunlisted");
    await pg.locator(".view .chipbtn [data-status]").waitFor();
    assert.equal(await pg.locator(".view .chipbtn [data-status]").getAttribute("data-status"), "link.no-audit");
  });
}

for (const width of [1300, 390]) {
  await check("complete published audit, independent evidence and PDF revision", width, async (pg) => {
    await pg.goto(origin + "/published/#/r/paper/read/P/P%3Atheorem-1");
    await pg.waitForSelector("aside .lean .block");
    assert.match(await pg.locator("aside .paper h2").textContent(), /audited revision/);
    assert.equal(await pg.locator("aside .crop").count(), 1, "full audited PDF crop is available");
    assert.doesNotMatch(await pg.locator("aside .crop").textContent(), /Estimated/);
    // The auditor's accepted workspace records, read-only and attributed.
    const work = pg.locator("aside .published-work");
    await work.waitFor();
    assert.match(await work.textContent(), /Reading by A Auditor \(self-declared\)/);
    assert.match(await work.locator("[data-req='r1']").textContent(), /the synthetic bound holds/);
    assert.match(await work.locator("[data-alignment='a1']").textContent(), /Synthetic\.bound.*corresponds.*A-Auditor/);
    assert.deepEqual(await work.locator("[data-kind='finding']").evaluateAll((es) => es.map((e) => e.classList.contains("old"))), [true, false]);
    assert.match(await work.textContent(), /Supersedes f1: A synthetic stronger theorem/);
    // A counterexample on the requirement, with what it can show and what its certificate checks.
    const cx = work.locator("[data-cx='x1']");
    assert.equal(await cx.getAttribute("data-standing"), "candidate");
    assert.match(await cx.textContent(), /Counterexample · a candidate counterexample: not yet shown admissible · by human:A-Auditor[\s\S]*Against: the synthetic bound holds[\s\S]*n = 0 reduces the reading to 1 ≤ 0, which fails/);
    assert.match(await cx.textContent(), /Certificate: Synthetic\.no_bound: Lean checks that its type is the negation of Synthetic\.Bound; it certifies that proposition only/);
    assert.equal(await work.locator("button, input, textarea, select").count(), 0, "nothing to edit");
    assert.equal(await pg.locator(".edition select").inputValue(), "original");
    await pg.locator(".view .chipbtn").click();
    for (const [dim, state] of [["formal","proved"],["review","author-reviewed"],["source","fail"],["replay","not-run"]]) {
      assert.equal(await pg.locator(`.details [data-dimension='${dim}']`).getAttribute("data-state"), state);
    }
    assert.match(await pg.locator(".details").textContent(), /Synthetic statement review/);
    assert.match(await pg.locator(".details .foot").textContent(), /r-synthetic.*aaaaaaaaaaaa/);
    await pg.locator(".details details.decl summary").click();
    await pg.waitForFunction(() => document.body.textContent.includes("Synthetic definition review."));
    const source = pg.locator(".details a.src-link, .details .decl a").filter({ hasText: "Lean source" });
    assert.match(await source.first().getAttribute("href"), /synthetic\/alpha\/blob\/a{40}/);
    await pg.locator(".back").first().click();
    await pg.selectOption("select[aria-label='Formalisation shown']", "synthetic/beta");
    await pg.waitForFunction(() => document.querySelector(".view .chipbtn [data-status]")?.dataset.status === "link.none");
    assert.equal(await pg.locator(".view .lean .statement").count(), 0);
    assert.doesNotMatch(await pg.locator("aside").textContent(), /Synthetic statement review/);
    assert.equal(await pg.locator("aside .published-work").count(), 0, "another project's readings are not shown");
    assert.equal(await pg.locator(".edition select").inputValue(), "original", "project choice keeps the paper");
    await pg.selectOption("select[aria-label='Formalisation shown']", "synthetic/alpha");
    // Close the panel so the PDF control is reachable on a phone.
    await pg.getByRole("button", { name: "Back to paper", exact: true }).click();
    await pg.selectOption("select[aria-label='Paper revision']", PUB.editions[0].edition);
    assert.equal(new URL(pg.url()).searchParams.get("edition"), PUB.editions[0].edition);
    await pg.waitForSelector(".paperpane [data-claim='P:theorem-1']");
    const extra = PUB.claims.find((c) => c.id !== "P:theorem-1");
    await open(pg, extra.id);
    await pg.waitForFunction(() => document.querySelector(".view .chipbtn [data-status]")?.dataset.status === "formal.refuted.corrected");
    assert.equal(await pg.locator("aside .lean .block").count(), 2);
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `published-${width}.png`) });
  });
}

// A claim joined to an audit's entry by printed number, on a page that cannot show the PDF the
// audit read, says so beside the audit's status (#408). The audit's own entry, and a claim whose
// record has no `matched`, look as before; the status is the engine's in every case.
for (const width of [1300, 390]) {
  await check("a claim matched by printed number to an audit of another PDF says so", width, async (pg) => {
    const status = pg.locator("aside .view .chipbtn [data-status]");
    const note = pg.locator("aside .view .matched");
    const after = ": the audit read another PDF of the paper than the one shown here.";
    await pg.goto(origin + "/matched/#/r/paper/read/P/P%3Atheorem-1");
    await status.waitFor();
    assert.equal(await status.getAttribute("data-status"), "formal.author-reviewed");
    assert.equal(await note.getAttribute("data-matched"), "number");
    assert.equal((await note.textContent()).trim(),
      "Matched by its printed number to the audit's entry for Latest manuscript (commit 956fe0b)" + after);
    assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `matched-${width}.png`) });
    // The audit's own entry is joined to no statement of this PDF.
    const own = MATCHED.claims.find((c) => c.projects);
    await open(pg, own.id);
    await pg.waitForFunction(() => document.querySelector("aside .view .chipbtn [data-status]")?.dataset.status === "formal.refuted.corrected");
    assert.equal(await note.count(), 0);
    // Without the version's label, the note names the revision the audit read.
    await pg.goto(origin + "/matched-revision/#/r/paper/read/P/P%3Atheorem-1");
    await note.waitFor();
    assert.equal(await status.getAttribute("data-status"), "formal.author-reviewed");
    assert.equal((await note.textContent()).trim(),
      "Matched by its printed number to the audit's entry for revision dddddddddddd" + after);
    // A record without `matched` has no note.
    await pg.goto(origin + "/published/#/r/paper/read/P/P%3Atheorem-1");
    await status.waitFor();
    assert.equal(await status.getAttribute("data-status"), "formal.author-reviewed");
    assert.equal(await note.count(), 0);
  });
}

for (const width of [1300, 390]) {
  await check("the changes since the earlier release name what changed and what is due for review", width, async (pg) => {
    await pg.goto(origin + "/toy/" + `#/r/${TOY.release}/changes`);
    await pg.waitForSelector("main.ch");
    assert.equal(await pg.locator("[data-changes]").count(), 0, "a release without an earlier one shows no comparison");
    await pg.goto(origin + "/toychanges/" + `#/r/${TOY.release}/changes`);
    const section = pg.locator("[data-changes]");
    await section.waitFor();
    assert.match(await section.locator("h2").textContent(), /Changes since release r-earlier/);
    // The unchanged claim is listed only on request.
    assert.equal(await section.locator("article.claim").count(), 2);
    const def = section.locator("article[data-claim='T:def:even']");
    // Both builds' statuses, each as its own build recorded it.
    assert.deepEqual(await def.locator(".status [data-status]").evaluateAll((xs) => xs.map((x) => x.dataset.status)), ["definition.reviewed", "definition.review-pending"]);
    const reopened = def.locator("[data-outcome='reopened']");
    assert.match(await reopened.textContent(), /Due for review: review of Toy\.IsEven by a\.referee/);
    assert.match(await reopened.textContent(), /Because Toy\.IsEven changed\./);
    assert.match(await reopened.locator(".question").textContent(), /still define what Definition 1\.1/);
    const was = await def.locator(".lean pre").allTextContents();
    assert.match(was[0], /n = 2 \* k/);
    assert.match(was[1], /n = k \+ k <img src=x onerror=alert\(1\)>/, "a string is shown as text");
    assert.equal(await def.locator(".lean img").count(), 0);
    assert.equal(await def.locator("h3 a").getAttribute("href"), `#/r/${TOY.release}/claim/T%3Adef%3Aeven`);
    const ctx = section.locator("article[data-claim='T:eq:bound-range']");
    assert.match(await ctx.locator(".pc").textContent(), /Context changed/);
    assert.match(await ctx.locator(".ctx").textContent(), /passage toy\.tex:71 changed/);
    assert.match(await ctx.textContent(), /the inventory still pins the earlier text/);
    // The sentence that changed, in both versions; the unchanged display is not repeated.
    assert.deepEqual(await ctx.locator(".text pre").allTextContents(), ["Fix $n$.", "Fix $n \\ge 1$."]);
    assert.match(await ctx.locator(".text").first().textContent(), /Earlier context \(toy\.tex:71\)/);
    assert.match(await ctx.locator("[data-outcome='kept']").textContent(), /counted against the pinned earlier text/);
    await section.locator("label.all input").check();
    assert.equal(await section.locator("article.claim").count(), 3);
    const box = await section.boundingBox();
    assert.ok(box.x >= 0 && box.x + box.width <= width + 1, "the comparison fits the page");
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `changes-${width}.png`), fullPage: true });
  });
}

await check("direct audit has compact attribution with provenance on request", 390, async (pg) => {
  await pg.goto(origin + "/toy/?audit=" + encodeURIComponent(origin + "/toy/"));
  const banner = pg.locator(".attribution");
  await banner.waitFor();
  assert.match(await banner.textContent(), /Audit by A. Author/);
  assert.ok((await banner.boundingBox()).height < 50);
  await banner.locator("a").click();
  await pg.waitForSelector("main.ch");
  assert.match(await pg.locator("main.ch").textContent(), /A. Author/);
});

// #77: a published reading pairs a definition's row with the passages aligned with it: each passage
// printed once in the row, a passage no longer kept and a stale alignment marked, attributed.
await check("a definition's row is paired with the passages a published reading aligns with it", 1300, async (pg) => {
  await pg.goto(origin + `/toywork/#/r/${TOY.release}/claim/${encodeURIComponent("T:def:even")}`);
  const cell = pg.locator(".cmp .defrow[data-row='Toy.IsEven::top'] .pcell");
  await cell.locator(".aligned").first().waitFor();
  assert.match(await pg.getByRole("combobox", { name: "Rows" }).locator("option:checked").textContent(), /Aligned with the paper by the AI model synthetic-model/);
  assert.deepEqual(await cell.locator(".aligned").evaluateAll((es) => es.map((e) => e.dataset.alignment)), ["a1", "a2", "a3"]);
  assert.deepEqual(await cell.locator("pre.frag").allTextContents(), ["A synthetic printed sentence."], "the passage once in the row");
  assert.match(await cell.locator("[data-alignment='a1']").textContent(), /even definition: n is even when n = 2k[\s\S]*recorded by llm:synthetic-model · changed since it was recorded/);
  assert.match((await cell.locator("[data-alignment='a2']").textContent()).replace(/\s+/g, " "), /The passage above\..*Toy\.IsEven \(sub-term: n = 2 \* k\); Toy\.IsEven \(variable: n\) · recorded by llm:synthetic-model/);
  assert.match(await cell.locator("[data-alignment='a3']").textContent(), /a passage no longer kept/);
  assert.match(await pg.locator(".cmp .defrow[data-row='Toy.triangle::top'] .pcell").textContent(), /Not aligned with the paper in this reading/);
  assert.equal(await pg.locator(".cmp .paper.whole .excerpt").count(), 1, "the printed passage stays whole above the rows");
});

await check("a direct audit shows its published readings beside an unchanged status", 1300, async (pg) => {
  const at = `#/r/${TOY.release}/read/T/T%3Adef%3Aeven`;
  await pg.goto(origin + "/toy/?audit=" + encodeURIComponent(origin + "/toy/") + at);
  await pg.waitForSelector("aside .view .chipbtn [data-status]");
  const before = await pg.locator("aside .view .chipbtn [data-status]").getAttribute("data-status");
  assert.equal(await pg.locator("aside .published-work").count(), 0);
  await pg.goto(origin + "/toywork/?audit=" + encodeURIComponent(origin + "/toywork/") + at);
  const work = pg.locator("aside .published-work");
  await work.waitFor();
  assert.equal(await pg.locator("aside .view .chipbtn [data-status]").getAttribute("data-status"), before);
  assert.match(await work.textContent(), /Reading by the AI model synthetic-model · independent review/);
  assert.equal(await work.locator("pre.src").textContent(), "A synthetic printed sentence.");
  assert.match(await work.locator("[data-role='statement']").textContent(), /toy\.tex:12 · printed for this claim · accepted by llm:synthetic-model/);
  assert.match(await work.locator("[data-alignment='a1']").textContent(), /Toy\.IsEven.*the Lean changed since it was recorded/);
  // An alignment that names its passage shows it; one whose passage is no longer kept says so.
  assert.match((await work.locator("[data-alignment='a2']").textContent()).replace(/\s+/g, " "), /^On toy\.tex:12: Lean: Toy\.IsEven \(sub-term: n = 2 \* k\); Toy\.IsEven \(variable: n\) · corresponds · recorded by llm:synthetic-model$/);
  assert.match((await work.locator("[data-alignment='a3']").textContent()).replace(/\s+/g, " "), /^On a passage no longer kept: Lean: Toy\.IsEven · corresponds · recorded by llm:synthetic-model · a passage it names no longer governs the reading$/);
  // Each finding resting on a composition shows it: the auditor's argument with its open
  // obligation and the next step, or a checked bridge; neither reads as a direct result.
  const findings = work.locator("[data-kind='finding']");
  assert.match(await findings.nth(0).locator("strong").first().textContent(), /^Part of the claim, by an argument combining Lean results$/);
  const c1 = work.locator("[data-composition='c-1']");
  const t1 = (await c1.textContent()).replace(/\s+/g, " ");
  assert.match(t1, /s1 SYNTHETIC-STEP: some n is even · from Toy\.IsEven/);
  assert.match(t1, /s2 some m is even · from Toy\.even_add applied in Toy\.synthetic · with a := m/);
  assert.match(t1, /Open: compatible witness choices n and m may differ/);
  assert.match(t1, /No step establishes even\./);
  assert.match(t1, /Lean has not checked this combination\. Next step: State the combination as one Lean result\./);
  assert.match(await findings.nth(1).locator("strong").first().textContent(), /^Every clause, through a checked bridge$/);
  const t2 = (await work.locator("[data-composition='c-2']").textContent()).replace(/\s+/g, " ");
  assert.match(t2, /Bridge: Toy\.synthetic_bridge for the target Toy\.Spec\.synthetic\. Lean checks its proof/);
  assert.doesNotMatch(t2, /Next step/);
  // A finding recorded as a checked bridge of its own, which Lean does not check, reads as the
  // auditor's composition and says what it was recorded as.
  assert.match(await findings.nth(2).locator("strong").first().textContent(), /^Every clause, by an argument combining Lean results$/);
  assert.equal(await findings.nth(2).locator("[data-line='recorded']").textContent(),
               "Recorded as a checked bridge (Toy.no_such_bridge for Toy.Spec.synthetic); no bridge Lean checks now: Lean finds no such theorem.");
  assert.doesNotMatch(await findings.nth(2).textContent(), /through a checked bridge/);
  assert.doesNotMatch(await work.textContent(), /in one Lean statement/);
});

for (const width of [1440, 1000, 390, 320]) {
  await check("comparison keeps all three representations and long assumptions visible", width, async (pg) => {
    await pg.goto(origin + `/long-statement/#/r/${TOY.release}/read/T/T%3Athm%3Aeven-add?compare=1`);
    await pg.locator("aside .exact pre").waitFor();
    assert.deepEqual(await pg.locator(".cmp .grid > section > h2").allTextContents(), ["Paper", "Lean"]);
    assert.equal(await pg.locator(".lean .ribbon > li").count(), 12);
    assert.match(await pg.locator(".exact pre").textContent(), /x11 : Nat/);
    assert.equal(await pg.locator(".paperpane").isHidden(), true);
    const sizes = await pg.evaluate(() => ({ width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth, bottom: document.documentElement.scrollHeight }));
    assert.ok(sizes.scroll <= sizes.width + 1, JSON.stringify(sizes));
    assert.ok(sizes.bottom <= sizes.height + 1, JSON.stringify(sizes));
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `comparison-${width}.png`) });
  });
}

// #77: one comparison renderer. The reader, the claim page and the review page's Compare stage
// draw a claim's rows with the same components, so a statement keeps the same scope, and a
// definition claim both its definitions, in each.
const REVIEW_SHAPE = "prooflens-review:structure";
// The review page at its Compare stage for `unit`: a reviewer and a reading locked for it.
// Every other unit of the queue is skipped, so the page comes to this one.
async function compareStage(pg, site, release, storageKey, unit, claimId) {
  const queue = JSON.parse(fs.readFileSync(path.join(root, site, "data", "review-queue.json"), "utf8"));
  const skipped = queue.units.map((u) => u.id).filter((id) => id !== unit);
  await pg.goto(origin + `/${site}/`);
  await pg.evaluate(([k, id, skipped]) => localStorage.setItem(k, JSON.stringify({ reviewer: { kind: "human", name: "Synthetic reviewer" }, skipped,
    drafts: { [id]: { stage: "compare", reading: "A synthetic reading, locked before the Lean was shown.", locked_at: "2026-01-01T00:00:00Z", revealed_by: [] } } })), [storageKey, unit, skipped]);
  await pg.goto(origin + `/${site}/#/r/${release}/review` + (claimId ? `?claim=${encodeURIComponent(claimId)}` : ""));
  const cmp = pg.locator(".review .unit .cmp");
  await cmp.waitFor();
  return cmp;
}
// A statement's rows as they read: each row's role, how its objects' properties stand, what
// stays inside an assumption, and its readable text.
const scopeOf = (cmp) => cmp.locator(".stmt").first().evaluate((st) => [...st.querySelectorAll(":scope > .ribbon > li, :scope > .concl")].map((r) => ({
  row: r.dataset.row, role: (r.className.match(/\b(forall|exists|hypothesis|instance)\b/) || ["conclusion"])[0],
  carried: [...r.querySelectorAll("[data-carried]")].map((c) => c.dataset.carried),
  inside: r.querySelectorAll(".inner, .within").length,
  text: r.querySelector(".readable").textContent.replace(/\s+/g, " ").trim() })));
await check("the reader, the claim page and review's Compare draw one comparison, with the same scope", 1300, async (pg) => {
  const cases = [["toycmp", TOY.release, "T", "T:thm:even-add", REVIEW_KEY, "spec:Toy.PaperSpec.thm_even_add"],
    ...["supplied", "assumed", "produced", "witnesses", "conditional", "none-large"].map((n) =>
      ["structure", SHAPE.release, "P", "P:thm:" + n, REVIEW_SHAPE, "link:thm:" + n])];
  for (const [site, release, paper, claim, key, unit] of cases) {
    await pg.goto(origin + `/${site}/#/r/${release}/read/${paper}/${encodeURIComponent(claim)}`);
    const inReader = pg.locator("aside .cmp");
    await inReader.locator(".stmt .readable").first().waitFor();
    const reader = await scopeOf(inReader);
    await pg.goto(origin + `/${site}/#/r/${release}/claim/${encodeURIComponent(claim)}`);
    const onPage = pg.locator("main.page .cmp");
    await onPage.locator(".stmt .readable").first().waitFor();
    assert.deepEqual(await scopeOf(onPage), reader, `${claim}: the claim page`);
    const inReview = await compareStage(pg, site, release, key, unit, claim);
    await inReview.locator(".stmt .readable").first().waitFor();
    assert.deepEqual(await scopeOf(inReview), reader, `${claim}: review's Compare`);
    assert.ok(reader.length && reader.at(-1).role === "conclusion", claim);
    for (const cmp of [inReview]) {
      assert.equal(await cmp.locator(".exact-pane .exact > pre").count(), 1, `${claim}: the complete exact statement`);
      assert.ok(await cmp.locator(".paper .passage").count() >= 1, `${claim}: the paper's passage`);
    }
  }
});

await check("a definition claim shows both its definitions in the reader, on its page and in review's Compare", 1300, async (pg) => {
  const defs = async (cmp) => {
    await cmp.locator(".defn.readable[data-decl='Toy.triangle'] .eq").first().waitFor();
    return { even: (await cmp.locator(".defn.readable[data-decl='Toy.IsEven'] .body").textContent()).trim(),
             triangle: (await cmp.locator(".defn.readable[data-decl='Toy.triangle'] .eq").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim()),
             exact: await cmp.locator(".exact-pane .defn.exact").count() };
  };
  await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/${encodeURIComponent("T:def:even")}`);
  const reader = await defs(pg.locator("aside .cmp"));
  assert.equal(reader.even, "∃ (k : Nat), n = 2 * k");
  assert.equal(reader.triangle.length, 2);
  assert.equal(reader.exact, 2);
  await pg.goto(origin + `/toy/#/r/${TOY.release}/claim/${encodeURIComponent("T:def:even")}`);
  assert.deepEqual(await defs(pg.locator("main.page .cmp")), reader);
  // Each definition's own review unit draws it with the same components.
  let cmp = await compareStage(pg, "review-order", TOY.release, REVIEW_KEY, "def:Toy.IsEven", "T:def:even");
  await cmp.locator(".defn.readable[data-decl='Toy.IsEven'] .body").waitFor();
  assert.equal((await cmp.locator(".defn.readable[data-decl='Toy.IsEven'] .body").textContent()).trim(), reader.even);
  assert.equal(await cmp.locator(".defn.exact[data-decl='Toy.IsEven']").count(), 1);
  cmp = await compareStage(pg, "review-order", TOY.release, REVIEW_KEY, "def:Toy.triangle", "T:def:even");
  await cmp.locator(".defn.readable[data-decl='Toy.triangle'] .eq").first().waitFor();
  assert.deepEqual((await cmp.locator(".defn.readable[data-decl='Toy.triangle'] .eq").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim()), reader.triangle);
  // A linked definition claim of the structure fixture, reviewed as one unit: both definitions.
  cmp = await compareStage(pg, "structure", SHAPE.release, REVIEW_SHAPE, "link:def:multiple", "P:def:multiple");
  await cmp.locator(".defn.readable[data-decl='Shape.fib'] .eq").first().waitFor();
  assert.equal(await cmp.locator(".defn.readable[data-decl='Shape.MultipleAbove']").count(), 1);
  assert.equal(await cmp.locator(".defn.readable[data-decl='Shape.fib'] .eq").count(), 3);
});

// #77: a definition opened from a row opens below that row: the paper's bound, the theorem and the
// selected sub-term stay on the page, on a desktop, a short desktop and a phone.
for (const [width, height, where] of [[1300, 900, "claim"], [1300, 560, "claim"], [1300, 560, "expanded"], [390, 844, "read"]]) {
  await check(`a definition opened from a row keeps the paper's bound, the theorem and the selection (${where}, ${height}px high)`, width, async (pg) => {
    const page = where === "claim" ? `claim/${encodeURIComponent("P:thm:jet")}` : `read/P/${encodeURIComponent("P:thm:jet")}` + (where === "expanded" ? "?compare=1" : "");
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/${page}`);
    const cmp = pg.locator(".cmp");
    const hyp = cmp.locator(".stmt [data-row]").filter({ has: pg.locator("[data-slot=readable]", { hasText: "Shape.JetBound f S (n + 5) C" }) });
    await hyp.waitFor();
    await hyp.locator("[data-slot=readable] .p", { hasText: "+" }).first().click();
    const picked = (await hyp.locator("[data-slot=readable] .in").allTextContents()).join("");
    assert.match(picked, /^\(?n \+ 5\)?$/);
    await hyp.locator("[data-slot=readable] a.r", { hasText: "Shape.JetBound" }).click();
    const insp = hyp.locator(".inspection");
    await insp.locator(".decl.inspector").waitFor();
    assert.match((await insp.textContent()).replace(/\s+/g, " "), /∀ \(j : Nat\), j ≤ k → ∀ \(x : Nat\), S x → f j x ≤ C/, "the definition's own bound");
    assert.equal((await hyp.locator("[data-slot=readable] .in").allTextContents()).join(""), picked, "the selected sub-term stays selected");
    assert.equal((await cmp.locator(".exact-pane .exact > pre .in").allTextContents()).join(""), picked, "in the exact statement too");
    const passage = cmp.locator(".paper .excerpt");
    assert.match(await passage.textContent(), /first\s*n\s*\+\s*5/);
    for (const [what, loc] of [["the paper's passage", passage], ["the claim", pg.locator("h1")], ["the theorem's row", hyp.locator("[data-slot=readable]")], ["its conclusion", cmp.locator(".stmt .concl")]])
      assert.ok(await loc.isVisible(), what + " stays on the page");
    const inView = (loc) => loc.evaluate((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.bottom > 0 && r.top < innerHeight; });
    assert.ok(await inView(insp), "the definition is in view");
    if (width > 800) assert.ok(await inView(passage), "the paper's bound is in view beside it");
    // Back closes it and leaves the selection; Forward opens it again in its place.
    await pg.goBack();
    await insp.waitFor({ state: "detached" });
    assert.equal((await hyp.locator("[data-slot=readable] .in").allTextContents()).join(""), picked);
    await pg.goForward();
    await insp.locator(".decl.inspector").waitFor();
    assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "no sideways scroll");
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `inspect-${where}-${width}x${height}.png`) });
  }, height);
}

// #77: pins. A property pinned on one object stays with it while another is opened, and is not
// shown for another claim's object of the same name, nor in another audit.
await check("a pinned property stays with its own witness, claim and audit", 1300, async (pg) => {
  const claimPage = (id) => pg.evaluate(([r, c]) => { location.hash = `#/r/${r}/claim/${encodeURIComponent(c)}`; }, [SHAPE.release, id]);
  await pg.goto(origin + `/structure/#/r/${SHAPE.release}/claim/${encodeURIComponent("P:thm:two-solutions")}`);
  const s = pg.locator(".stmt [data-row='b:1']"), t = pg.locator(".stmt [data-row='b:2']");
  await s.locator(".prop[data-field='start'] button.origin").click();
  const sPanel = s.locator(".inspection");
  await sPanel.waitFor();
  assert.match((await sPanel.textContent()).replace(/\s+/g, " "), /s\.start : s\.path 0 = d/);
  assert.match(await sPanel.textContent(), /A field of the given object s: part of what the statement is given/);
  assert.match(await sPanel.textContent(), /Field start of Shape\.Solution, inherited from Shape\.Base/);
  await sPanel.getByRole("button", { name: "Pin" }).click();
  assert.equal(await sPanel.getByRole("button", { name: "Pinned" }).getAttribute("aria-pressed"), "true");
  // The other witness's property opens beside its own row; the pin stays with s.
  await t.locator(".prop[data-field='start'] button.origin").click();
  const tPanel = t.locator(".inspection");
  await tPanel.waitFor();
  assert.match((await tPanel.textContent()).replace(/\s+/g, " "), /t\.start : t\.path 0 = d/);
  assert.equal(await s.locator(".inspection.pinned").count(), 1, "s's property is still open");
  assert.match((await s.locator(".inspection.pinned").textContent()).replace(/\s+/g, " "), /s\.start : s\.path 0 = d/);
  assert.equal(await t.locator(".inspection.pinned").count(), 0, "t's is not pinned");
  await tPanel.locator(".back").click();
  await tPanel.waitFor({ state: "detached" });
  assert.equal(await s.locator(".inspection.pinned").count(), 1);
  // Another claim's solution s, with its own property start: the pin is not shown there.
  await claimPage("P:thm:supplied");
  await pg.locator("h1", { hasText: "Theorem 4" }).waitFor();
  await pg.locator(".stmt [data-row='b:1'] .prop[data-field='start']").waitFor();
  assert.equal(await pg.locator(".inspection").count(), 0, "no pin of another claim's object");
  await claimPage("P:thm:two-solutions");
  await pg.locator(".stmt [data-row='b:1'] .inspection.pinned").waitFor();
  // A pin made in one audit of a paper is not shown in another audit of it.
  await pg.goto(origin + `/combined/?project=${encodeURIComponent(CA)}#/r/paper/read/P/P%3Atheorem-1`);
  await pg.locator("aside .chipbtn").click();
  const details = pg.locator("aside .inspection[data-kind='details']");
  await details.waitFor();
  await details.getByRole("button", { name: "Pin" }).click();
  await pg.locator("aside .crumbs .back").click();
  assert.equal(await pg.locator("aside .inspection.pinned[data-kind='details']").count(), 1, "pinned in this audit");
  await pg.selectOption(FORMAL, CB);
  await pg.waitForFunction(() => document.querySelector("aside [data-status]")?.getAttribute("data-status") === "formal.open");
  assert.equal(await pg.locator("aside .inspection").count(), 0, "not in the other audit");
  await pg.selectOption(FORMAL, CA);
  await pg.locator("aside .inspection.pinned[data-kind='details']").waitFor();
});

// #77: the review input boundary. The reader draws what people recorded about a claim, attributed;
// independent Compare is given the complete mathematics and none of it, in its data (nothing is
// fetched or written to the page and hidden); after the verdict the later stage shows it.
await check("independent Compare is given the complete mathematics and no prior interpretation", 1300, async (pg) => {
  const fetched = [];
  pg.on("request", (r) => fetched.push(new URL(r.url()).pathname));
  await pg.goto(origin + `/toycmp/#/r/${TOY.release}/read/T/${encodeURIComponent("T:thm:even-add")}`);
  const reader = pg.locator("aside .cmp");
  await reader.locator(".stmt [data-row='b:0'] .pcell .aligned").waitFor();
  assert.match(await reader.getByRole("combobox", { name: "Rows" }).locator("option:checked").textContent(), /Aligned with the paper by A Auditor/);
  assert.match((await reader.locator(".stmt [data-row='b:0'] .pcell").textContent()).replace(/\s+/g, " "),
    /SYNTHETIC-PASSAGE: if a and b are even natural numbers\s*ab\s*for every: SYNTHETIC-REQUIREMENT: a and b, even natural numbers\s*corresponds · recorded by human:A-Auditor/);
  assert.match(await reader.locator(".stmt [data-row='b:1'] .pcell").textContent(), /The passages aligned above \(ab\), also here/);
  assert.match(await reader.locator(".stmt [data-row='c'] .pcell").textContent(), /then a \+ b is even[\s\S]*sum/);
  assert.match(await reader.locator(".stmt [data-row='b:2'] .pcell").textContent(), /Not aligned with the paper in this reading/);
  assert.equal(await reader.locator(".paper.whole .excerpt").count(), 1, "the printed passage once, whole");
  assert.ok(await reader.locator(".paper [data-sym]").count() > 0, "and the symbol links");
  // The Lean's own rows beside the whole passage, on request.
  await reader.getByRole("combobox", { name: "Rows" }).selectOption("none");
  await reader.locator(".grid > section.lean").waitFor();
  assert.equal(await reader.locator(".pcell").count(), 0);

  fetched.length = 0;
  const cmp = await compareStage(pg, "toycmp", TOY.release, REVIEW_KEY, "spec:Toy.PaperSpec.thm_even_add", "T:thm:even-add");
  await cmp.locator(".stmt .ribbon > li").first().waitFor();
  // The complete mathematics: the passage, every row, the conclusion and the exact statement.
  await cmp.locator(".paper .excerpt .katex").first().waitFor();
  assert.match(await cmp.locator(".paper .excerpt").textContent(), /are even natural numbers/);
  assert.equal(await cmp.locator(".stmt .ribbon > li").count(), 4);
  assert.match(await cmp.locator(".stmt .concl").textContent(), /Toy\.IsEven \(a \+ b\)/);
  assert.match(await cmp.locator(".exact-pane .exact pre").textContent(), /∀ \(a b : Nat\), Toy\.IsEven a → Toy\.IsEven b → Toy\.IsEven \(a \+ b\)/);
  // Without anything people recorded: no symbol link, no alignment, no row pairing.
  assert.equal(await cmp.locator("[data-sym], .pcell, [data-alignment], select[aria-label='Rows'], .linkby").count(), 0);
  // A definition opened from its row comes without its review or the paper definition linked to it.
  await cmp.locator(".stmt [data-row='b:2'] [data-slot=readable] a.r", { hasText: "Toy.IsEven" }).click();
  const insp = cmp.locator(".stmt [data-row='b:2'] .inspection");
  await insp.locator(".decl.inspector").waitFor();
  await insp.locator("details.extra summary").click();
  await pg.waitForLoadState("networkidle");
  const html = await pg.evaluate(() => document.body.innerHTML);
  for (const absent of ["A-Referee", "A-Auditor", "SYNTHETIC-NOTE", "SYNTHETIC-PASSAGE", "SYNTHETIC-REQUIREMENT", "a.referee", "Paper · Definition"])
    assert.ok(!html.includes(absent), `${absent} is not on the page`);
  assert.deepEqual(fetched.filter((p) => p.includes("/data/work/")), [], "nor fetched");
  await insp.locator(".back").click();
  // After the verdict, the later stage shows what people recorded, attributed.
  await pg.getByRole("textbox", { name: "Comparison", exact: true }).fill("A synthetic comparison.");
  await pg.getByRole("button", { name: "Matches the paper", exact: true }).click();
  await pg.getByRole("radio", { name: "Faithful", exact: true }).check();
  await pg.getByRole("button", { name: "Record verdict and show the author's review" }).click();
  await cmp.locator(".paper [data-sym]").first().waitFor();
  await cmp.locator(".stmt [data-row='b:0'] .pcell .aligned").waitFor();
});

// #77: on a desktop, a short desktop and a phone, the comparison keeps its complete content, its
// sources, keyboard operation and the browser's history.
for (const [width, height] of [[1300, 900], [1300, 520], [390, 844]]) {
  await check(`the comparison keeps its content, sources, keyboard and history (${width}x${height})`, width, async (pg) => {
    await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/${encodeURIComponent("T:thm:even-add")}`);
    const cmp = pg.locator("aside .cmp");
    await cmp.locator(".stmt .ribbon > li").first().waitFor();
    assert.equal(await cmp.locator(".stmt .ribbon > li").count(), 4, "every row");
    for (const [what, loc] of [["the conclusion", cmp.locator(".stmt .concl")], ["the exact statement", cmp.locator(".exact-pane .exact pre")], ["the passage", cmp.locator(".paper .excerpt")]]) {
      await loc.scrollIntoViewIfNeeded();
      assert.ok(await loc.isVisible(), what);
    }
    // The source of the passage and of the Lean, on request.
    await cmp.locator(".paper summary", { hasText: "LaTeX source" }).click();
    assert.match(await cmp.locator(".paper .rawsrc pre").textContent(), /\\begin\{theorem\}|even/);
    // A reference opens by keyboard; focus moves into the inspection, and Escape returns it.
    const ref = cmp.locator(".stmt [data-row='b:2'] [data-slot=readable] a.r", { hasText: "Toy.IsEven" });
    await ref.focus();
    await pg.keyboard.press("Enter");
    const insp = cmp.locator(".inspection");
    await insp.locator(".decl.inspector").waitFor();
    assert.equal(await insp.locator(".back").evaluate((e) => e === document.activeElement), true, "focus is in the inspection");
    await insp.locator("details.extra summary").click();
    assert.match(await insp.locator(".extra").textContent(), /Toy\.Defs/, "the declaration's source");
    await pg.keyboard.press("Escape");
    await insp.waitFor({ state: "detached" });
    assert.equal(await ref.evaluate((e) => e === document.activeElement), true, "focus is back on the reference");
    // Back and Forward close and reopen it.
    await ref.click();
    await insp.locator(".decl.inspector").waitFor();
    await pg.goBack();
    await insp.waitFor({ state: "detached" });
    await pg.goForward();
    await insp.locator(".decl.inspector").waitFor();
    assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "no sideways scroll");
  }, height);
}

await check("search supports Tab and Enter, definition targets and Escape", 1300, async (pg) => {
  await pg.goto(origin + "/toy/");
  const input = pg.getByRole("combobox", { name: "Search claims and definitions" });
  await input.fill("even");
  await pg.locator(".search [role=option]").first().waitFor();
  await input.press("Tab");
  await pg.keyboard.press("Enter");
  await pg.locator("aside h1").waitFor();
  await input.fill("Toy.IsEven");
  const definition = pg.locator(".search [role=option]").filter({ has: pg.locator("code", { hasText: "Toy.IsEven" }) });
  await definition.focus(); await definition.press("Enter");
  await pg.locator(".crumbs").waitFor();
  assert.match(pg.url(), /inspect=Toy.IsEven/);
  assert.match(await pg.locator(".decl.inspector:visible").first().textContent(), /Toy.IsEven/);
  await input.fill("even"); await input.press("Escape");
  assert.equal(await pg.locator(".search .results").count(), 0);
});

await check("canonical paper search follows the selected project", 1300, async (pg) => {
  await pg.goto(origin + "/paper/?project=beta%2Fproject-b");
  const search = pg.getByRole("combobox", { name: "Search claims and definitions" });
  await search.fill("B.three");
  await pg.locator(".search [role=option]").first().waitFor();
  await search.press("Enter");
  await pg.waitForFunction(() => document.querySelector("aside")?.textContent.includes("B.three"));
  assert.deepEqual(await panelNames(pg), ["B.three"]);
});

await check("menus dismiss with Escape and return focus", 390, async (pg) => {
  await toyClaim(pg, "T:thm:even-add");
  const more = pg.getByRole("button", { name: "More", exact: true });
  await more.click(); await pg.keyboard.press("Tab"); await pg.keyboard.press("Escape");
  assert.equal(await more.getAttribute("aria-expanded"), "false");
  assert.equal(await more.evaluate((e) => e === document.activeElement), true);
});

await check("browser Back and Forward restore definition inspection", 1300, async (pg) => {
  await toyClaim(pg, "T:thm:even-add");
  const before = pg.url();
  const reference = pg.locator("aside .lean a.r", { hasText: "Toy.IsEven" }).first();
  assert.match(await reference.getAttribute("href"), /inspect=Toy.IsEven/);
  await reference.click(); await pg.locator(".crumbs").waitFor();
  await pg.goBack(); await pg.waitForSelector(".view h1"); assert.equal(pg.url(), before);
  await pg.goForward(); await pg.locator(".crumbs").waitFor();
  assert.match(await pg.locator(".decl.inspector:visible").first().textContent(), /Toy.IsEven/);
});

await check("late claim responses cannot overwrite a newer selection", 1300, async (pg) => {
  let finish, started;
  const wait = new Promise((r) => finish = r), requested = new Promise((r) => started = r);
  await pg.route("**/toy/data/claims/*even-add*", async (route) => { started(); await wait; await route.continue(); });
  await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/T%3Athm%3Aeven-add`);
  await requested;
  await pg.evaluate((release) => location.hash = `#/r/${release}/read/T/T%3Athm%3Abound`, TOY.release);
  await pg.locator("aside h1", { hasText: "Theorem 2.5" }).waitFor();
  finish(); await pg.waitForLoadState("networkidle");
  assert.match(await pg.locator("aside h1").textContent(), /Theorem 2.5/);
});

await check("failed claim loads can be retried", 1300, async (pg) => {
  let attempts = 0;
  await pg.route("**/toy/data/claims/*even-add*", (route) => ++attempts === 1 ? route.fulfill({ status: 503, body: "Unavailable" }) : route.continue());
  await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/T%3Athm%3Aeven-add`);
  await pg.locator("aside").getByRole("button", { name: "Try again" }).click();
  await pg.locator("aside h1").waitFor(); assert.equal(attempts, 2);
});

await check("names in module docstrings that nothing declares are listed, dismissals shown", 1300, async (pg) => {
  const mk = (name, line, dismissed) => ({ id: `module-doc-name:Toy.Defs:${name}`, tier: "warning", code: "module-doc-name", subject: "Toy.Defs", trigger: name,
    message: `Toy/Defs.lean:${line}: module docstring names ${name}, which is not declared`, ...(dismissed ? { dismissed } : {}) });
  const general = [mk("Toy.gone_lemma", 7), mk("Toy.old_bound", 8, { by: "auditor", rationale: "kept as a pointer" })];
  await pg.route("**/toy/data/index.json", (r) => r.fulfill({ contentType: "application/json", body: JSON.stringify({ ...TOY, findings: { ...TOY.findings, general } }) }));
  await pg.goto(origin + "/toy/");
  const banner = pg.locator("details.docnames");
  assert.match(await banner.locator("summary").textContent(), /^Warning: 1 name\(s\) in module docstrings are not declared .*\(1 dismissed\)$/);
  await banner.locator("summary").click();
  const items = await banner.locator("li").allTextContents();
  assert.equal(items.length, 2);
  assert.match(items[0], /Toy\/Defs.lean:7: module docstring names Toy.gone_lemma, which is not declared/);
  assert.match(items[1], /dismissed by auditor: “kept as a pointer”/);
});

await check("contents close after a mobile selection", 390, async (pg) => {
  await pg.goto(origin + "/paper/");
  await pg.getByRole("button", { name: "Contents", exact: true }).click();
  assert.equal(await pg.getByRole("button", { name: "Contents", exact: true }).getAttribute("aria-expanded"), "true");
  await pg.locator("dialog[open] a", { hasText: "Theorem 3" }).click();
  await pg.locator("aside h1").waitFor();
  assert.equal(await pg.locator("dialog[open]").count(), 0);
  assert.equal(await pg.locator("aside").evaluate((e) => e === document.activeElement), true);
});

await check("PDF text, links, page search and zoom work together", 1300, async (pg) => {
  await pg.goto(origin + "/long/");
  await pg.locator(".textLayer span", { hasText: "Alpha theorem" }).first().waitFor();
  assert.equal(await pg.locator(".pdf-links a").first().getAttribute("href"), "https://example.org/paper");
  await pg.getByRole("searchbox", { name: "Find in paper" }).fill("page 15.");
  await pg.getByRole("button", { name: "Find", exact: true }).click();
  await pg.waitForFunction(() => document.querySelector(".find-status")?.textContent.includes("1 of 1"));
  assert.equal(await pg.getByRole("spinbutton", { name: "Page number" }).inputValue(), "15");
  await pg.getByRole("combobox", { name: "PDF zoom" }).selectOption("1.5");
  // The zoom keeps the page the reader was on.
  await pg.locator('[data-page="15"] .textLayer span').first().waitFor();
  await pg.waitForTimeout(300);
  assert.equal(await pg.getByRole("spinbutton", { name: "Page number" }).inputValue(), "15", "the zoom keeps the page");
  const top15 = await pg.locator('[data-page="15"]').evaluate((e) => e.getBoundingClientRect().top - e.closest(".pdf").parentElement.getBoundingClientRect().top);
  assert.ok(top15 >= 0 && top15 < 300, `page 15 stays at the top of the view (${top15})`);
  // A page number typed while the view moves is the one opened.
  await pg.getByRole("spinbutton", { name: "Page number" }).fill("2");
  await pg.locator(".pdf").evaluate((e) => { e.parentElement.scrollTop += 40; });
  await pg.waitForTimeout(300);
  assert.equal(await pg.getByRole("spinbutton", { name: "Page number" }).inputValue(), "2", "the page tracker leaves a typed number alone");
  await pg.getByRole("spinbutton", { name: "Page number" }).press("Tab");
  await pg.locator('[data-page="2"] .textLayer span').first().waitFor();
  assert.ok((await pg.locator(".band").first().boundingBox()).width <= 32, "claim marker occupies the margin");
});

await check("expression controls have names and pane resizing works by keyboard", 1440, async (pg) => {
  await toyClaim(pg, "T:thm:even-add");
  const empty = await pg.locator(".lean [role=button]").evaluateAll((es) => es.filter((e) => !/[\p{L}\p{N}∀∃∈≤≥=+×→↔∧∨¬]/u.test(e.textContent)).map((e) => e.textContent));
  assert.deepEqual(empty, []);
  const splitter = pg.getByRole("separator", { name: "Claim panel width" });
  await splitter.focus(); const before = Number(await splitter.getAttribute("aria-valuenow"));
  await splitter.press("ArrowRight"); assert.ok(Number(await splitter.getAttribute("aria-valuenow")) < before);
  // The separator names the panel it resizes and how its keys work; the value is the width.
  const panel = await splitter.getAttribute("aria-controls");
  assert.equal(await pg.locator(`#${panel}`).evaluate((e) => e.tagName), "ASIDE");
  assert.match(await pg.locator("#" + await splitter.getAttribute("aria-describedby")).textContent(), /arrows widen and narrow the panel/);
  assert.equal(await splitter.getAttribute("aria-valuetext"), `${await splitter.getAttribute("aria-valuenow")} pixels`);
  await splitter.press("Home"); assert.equal(await splitter.getAttribute("aria-valuenow"), "320");
  await splitter.press("End"); assert.equal(await splitter.getAttribute("aria-valuenow"), await splitter.getAttribute("aria-valuemax"));
  // The paper's pages are a labelled region with a tab stop, which scrolls by keyboard.
  const pages = pg.getByRole("region", { name: "Paper pages" });
  assert.equal(await pages.getAttribute("tabindex"), "0");
  assert.match(await pg.locator("#" + await pages.getAttribute("aria-describedby")).textContent(), /arrow keys, Page Up and Page Down/);
  await pg.locator(".pdf canvas").first().waitFor();
  // End widened the panel. The pages take their new width a frame later and scroll to keep the
  // claim in view; until then the pane's position is the one of the earlier width, so it is read
  // once those frames are drawn.
  await frames(pg, 2);
  const scroller = await pages.evaluateHandle((e) => [e, e.parentElement].find((x) => x.scrollHeight > x.clientHeight));
  const top = await scroller.evaluate((e) => e.scrollTop);
  await pages.focus(); await pg.keyboard.press("PageDown");
  // The browser scrolls after the key, sooner or later on a loaded machine.
  const scrolled = await pg.waitForFunction(([e, from]) => e.scrollTop > from, [scroller, top], { timeout: 5000 })
    .then(() => true, () => false);
  assert.ok(scrolled, "Page Down scrolls the pages");
});

for (const scheme of ["light", "dark"]) await check(`${scheme} theme text meets contrast requirements`, 1300, async (pg) => {
  await pg.emulateMedia({ colorScheme: scheme }); await toyClaim(pg, "T:thm:even-add");
  const ratios = await pg.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const luminance = (hex) => { const rgb = hex.trim().replace("#", "").replace(/^([0-9a-f])([0-9a-f])([0-9a-f])$/i, "$1$1$2$2$3$3").match(/../g).map((s) => parseInt(s, 16) / 255).map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4); return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722; };
    return [["--faint", "--bg"], ["--faint", "--surface-2"], ["--on-accent", "--accent"], ["--tier-warning", "--bg"], ["--tier-warning", "--surface"]].map(([a,b]) => { const x = luminance(style.getPropertyValue(a)), y = luminance(style.getPropertyValue(b)); return (Math.max(x,y)+.05)/(Math.min(x,y)+.05); });
  });
  assert.ok(ratios.every((r) => r >= 4.5), JSON.stringify(ratios));
  if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `theme-${scheme}.png`) });
});

await check("multi-page excerpts include both pages", 390, async (pg) => {
  await pg.goto(origin + "/long/#/r/paper/read/P/P%3Atheorem-2?compare=1");
  await pg.locator("aside .crop canvas").last().waitFor();
  assert.equal(await pg.locator("aside .crop canvas").count(), 2);
  assert.deepEqual(await pg.locator("aside .crop .page-label").allTextContents(), ["Page 2", "Page 3"]);
});

await check("search retries after a failed index request", 1300, async (pg) => {
  let attempts = 0;
  await pg.route("**/toy/data/search.json", (r) => ++attempts === 1 ? r.fulfill({ status: 503 }) : r.continue());
  await pg.goto(origin + "/toy/");
  await pg.getByRole("combobox", { name: "Search claims and definitions" }).fill("even");
  await pg.locator(".search").getByRole("button", { name: "Try again" }).click();
  await pg.locator(".search [role=option]").first().waitFor(); assert.equal(attempts, 2);
});

await check("review opens the selected claim, keeps protocol order and exports a saved report", 390, async (pg) => {
  await pg.addInitScript(([unit, next]) => localStorage.setItem("prooflens-review:toy-paper", JSON.stringify({
    selection: { paper: "unrelated-paper", group: "sec:unrelated:1" },
    drafts: { [unit]: { stage: "read", reading: "A previously started blind draft." },
      [next]: { stage: "read", reading: "Preserve this other unfinished reading." } }
  })), [reviewUnits[1].id, reviewUnits[0].id]);
  await pg.goto(origin + `/review/#/r/${TOY.release}/read/T/T%3Athm%3Aeven-add`);
  await pg.getByRole("button", { name: "More", exact: true }).click();
  await pg.getByRole("link", { name: "Review it", exact: true }).click();
  await pg.getByRole("textbox", { name: "Your name" }).fill("Synthetic reviewer");
  await pg.getByRole("button", { name: "Start", exact: true }).click();
  await pg.locator(".review .unit .pnum").waitFor();
  assert.match(await pg.locator(".review .unit .pnum").textContent(), /Theorem 2.1/);
  await pg.locator(".review .unit .excerpt .katex").first().waitFor();
  assert.match(await pg.locator(".review .unit .excerpt").textContent(), /are even natural numbers/, "the statement as typeset from its source");
  assert.match(await pg.locator(".review .warn").textContent(), /prior exposure/);
  assert.equal(await pg.locator(".review .stmt").count(), 0);
  assert.equal(await pg.locator(".review .author").count(), 0);
  await pg.getByRole("textbox", { name: "Your reading", exact: true }).fill("Every pair of even natural numbers has an even sum.");
  await pg.getByRole("button", { name: "Lock my reading and show the Lean" }).click();
  await pg.locator(".review .stmt").waitFor();
  assert.equal(await pg.locator(".review .author").count(), 0);
  await pg.getByRole("textbox", { name: "Comparison", exact: true }).fill("The quantifiers and conclusion agree in this synthetic example.");
  await pg.getByRole("button", { name: "Matches the paper", exact: true }).click();
  await pg.getByRole("radio", { name: "Faithful", exact: true }).check();
  // The coverage is recorded with the verdict, from the values that agree with it, and its
  // basis separately; the author's review is still hidden.
  const coverage = pg.getByRole("combobox", { name: "Coverage of the claim", exact: true });
  assert.deepEqual(await coverage.locator("option").allTextContents(), ["Not recorded", "Every clause", "Part of the claim"]);
  await coverage.selectOption({ label: "Every clause" });
  await pg.getByRole("combobox", { name: "How it is supported", exact: true }).selectOption({ label: "By an argument combining Lean results" });
  await pg.getByRole("textbox", { name: "Your argument: how these results together give the claim" }).fill("The sum of two even numbers is even, applied once.");
  assert.equal(await pg.locator(".review .author").count(), 0);
  await pg.getByRole("button", { name: "Record verdict and show the author's review" }).click();
  await pg.locator(".review .author").waitFor();
  assert.match(await pg.locator(".review .unit").textContent(), /Your coverage: Every clause, by an argument combining Lean results/);
  await pg.getByRole("button", { name: "Save report", exact: true }).click();
  await pg.getByRole("button", { name: "Export reports (1 new)", exact: true }).waitFor();
  const report = await pg.evaluate(() => JSON.parse(localStorage.getItem("prooflens-review:toy-paper")).reports[0]);
  assert.deepEqual(report.unit.claims, ["T:thm:even-add"]);
  assert.equal(report.reading.revealed_by[0].what, "Lean");
  assert.equal(report.verdict.value, "faithful");
  assert.deepEqual(report.correspondence, { coverage: "full", basis: "reviewed_composition",
                                            argument: "The sum of two even numbers is even, applied once." });
  assert.ok(report.reading.locked_at <= report.comparison.decided_at && report.comparison.decided_at <= report.author_review.shown_at);
  assert.equal(await pg.evaluate((id) => JSON.parse(localStorage.getItem("prooflens-review:toy-paper")).drafts[id].reading, reviewUnits[0].id), "Preserve this other unfinished reading.");
  const download = pg.waitForEvent("download");
  await pg.getByRole("button", { name: "Export reports (1 new)", exact: true }).click();
  const file = await download; const exported = JSON.parse(fs.readFileSync(await file.path()));
  assert.deepEqual(exported.reports[0], report);
});

// The review page's order (#128): the queue's priority order, or the paper's order the build
// wrote, each with the engine's reasons; a static copy offers no informed order.
await check("the review page offers the priority and paper orders with the engine's reasons", 390, async (pg) => {
  await pg.goto(origin + `/review-order/#/r/${TOY.release}/review`);
  await pg.evaluate((k) => localStorage.setItem(k, JSON.stringify({ reviewer: { kind: "human", name: "Synthetic reviewer" } })), REVIEW_KEY);
  await pg.reload();
  const order = pg.getByRole("combobox", { name: "Order", exact: true });
  const first = ORDER_QUEUE.units.find((u) => u.state !== "reviewed");
  await whyIs(pg, `${kindWord(first)} · ${first.reason}`);
  assert.equal(await order.inputValue(), "priority");
  const disabled = (v) => order.locator(`option[value=${v}]`).evaluate((o) => o.disabled);
  assert.equal(await disabled("informed"), true, "a static copy has no informed order");
  assert.equal(await disabled("document"), false);
  await order.selectOption("document");
  const paper = ORDER_QUEUE.orders.document[0], unit = ORDER_QUEUE.units.find((u) => u.id === paper.id);
  assert.match(paper.reason, /^In the paper's order; /);
  assert.notEqual(paper.id, first.id, "the paper's order starts elsewhere");
  await whyIs(pg, `${kindWord(unit)} · ${paper.reason}`);
  assert.equal(await pg.evaluate((k) => JSON.parse(localStorage.getItem(k)).order, REVIEW_KEY), "document");
  // The choice is kept, and the next unit is the paper order's next.
  await pg.reload();
  await whyIs(pg, `${kindWord(unit)} · ${paper.reason}`);
  assert.equal(await order.inputValue(), "document");
  await pg.getByRole("button", { name: "Skip", exact: true }).click();
  const second = ORDER_QUEUE.orders.document[1];
  await whyIs(pg, `${kindWord(ORDER_QUEUE.units.find((u) => u.id === second.id))} · ${second.reason}`);
  await order.selectOption("priority");
  await whyIs(pg, `${kindWord(first)} · ${first.reason}`);
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "no horizontal scroll");
});

await check("a declaration lists its users; a static copy names the command for its applications", 390, async (pg) => {
  await pg.goto(origin + `/uses/#/r/${USES.release}/read/P/${encodeURIComponent("P:lem:half")}?inspect=Uses.half_lt`);
  const uses = pg.locator("aside .decl.inspector details.uses");
  await uses.locator("summary").click();
  await uses.locator(".list li").first().waitFor();
  const users = (await uses.locator(".list li").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
  assert.deepEqual(users.map((u) => u.split(" ")[0]),
    ["Uses.caller_assumes", "Uses.caller_proves", "Uses.half_lt_four", "Uses.main_bound"]);
  assert.match(users[3], /proof · Uses\.Paper/);
  assert.match(await uses.textContent(), /machinechecked compare --query uses Uses\.half_lt/);
  assert.equal(await uses.getByRole("button", { name: "Show each application" }).count(), 0, "a static copy asks no server");
  // A user opens in the inspector, and its own users are listed there.
  await uses.getByRole("button", { name: "Uses.half_lt_four" }).click();
  await pg.waitForURL(/inspect=Uses.half_lt_four/);
  const next = pg.locator("aside .decl.inspector:visible details.uses");
  await next.locator("summary").click();
  assert.match(await next.locator(".list").textContent(), /Uses\.main_bound/);
});

// The applications, from the engine's answer under a local server like `machinechecked view`'s.
{
  const { spawn } = await import("node:child_process");
  const py = spawn(process.env.PYTHON || "python3", [path.join(here, "fixtures", "uses_server.py"), path.join(root, "uses"), path.join(here, "fixtures", "uses", "api-uses.json")]);
  const port = await new Promise((ok, fail) => {
    py.stdout.once("data", (d) => ok(String(d).trim()));
    py.once("exit", (c) => fail(new Error("the uses server stopped: " + c)));
  });
  try {
    for (const width of [1300, 390]) {
      await check("each application shows its arguments and whether the caller assumes or proves each premise", width, async (pg) => {
        await pg.goto(`http://127.0.0.1:${port}/#/r/${USES.release}/read/P/${encodeURIComponent("P:lem:half")}?inspect=Uses.half_lt`);
        const uses = pg.locator("aside .decl.inspector details.uses");
        await uses.locator("summary").click();
        await uses.getByRole("button", { name: "Show each application" }).click();
        await uses.locator(".app").first().waitFor();
        const apps = uses.locator(".app");
        assert.equal(await apps.count(), 4);
        const app = (caller) => apps.filter({ has: pg.locator(".ahead", { hasText: caller }) });
        const assumes = app("Uses.caller_assumes");
        const h = assumes.locator("li.role-premise").first();
        assert.match(await h.textContent(), /Uses\.Good m/);
        assert.match(await h.locator(".d").textContent(), /assumed by the caller/);
        assert.match(await h.textContent(), /the caller's hypothesis hm/);
        const proves = app("Uses.caller_proves");
        const hp = proves.locator("li.role-premise").first();
        assert.match(await hp.textContent(), /Uses\.Good \(2 \* \(m \+ 1\)\)/);
        assert.match(await hp.locator(".d").textContent(), /proved in the caller/);
        assert.match(await hp.textContent(), /Uses\.good_double/);
        assert.match(await proves.textContent(), /gives\s*2 \* \(m \+ 1\) \/ 2 < 2 \* \(m \+ 1\)/);
        // The general wrapper the paper's theorem is linked to is marked as such.
        assert.match(await app("Uses.main_bound").locator(".ahead").textContent(), /linked to P:thm:main/);
        assert.equal(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "no horizontal scroll");
      });
    }
  } finally { py.kill(); }
}


for (const width of [1300, 390]) {
  await check("a proof step shows its own finding beside the equation, apart from its parent", width, async (pg) => {
    await toyClaim(pg, "T:eq:bound-range");
    const view = pg.locator("aside .view");
    assert.equal(await view.locator(".chipbtn [data-status]").getAttribute("data-status"), "scope.proof-step", "the scope decision is the status");
    const finding = view.locator(".paper .finding");
    assert.equal(await finding.getAttribute("data-review"), "false");
    assert.match(await finding.textContent(), /false as printed.*k = 0/s);
    assert.match(await finding.textContent(), /Theorem 2\.5/);
    assert.match(await view.locator("section.lean").textContent(), /No Lean declaration is linked as establishing this step/);
    assert.match(await view.locator("section.lean").textContent(), /Different formal route used instead.*Toy\.Acceptance\.thm_bound/s);
    await view.locator(".paper .context summary").click();
    assert.match(await view.locator(".paper .context").textContent(), /k = 1/);
    // A linked step that no one has reviewed reads as not reviewed.
    await toyClaim(pg, "T:eq:bound-sum");
    assert.equal(await pg.locator("aside .view .paper .finding").getAttribute("data-review"), "unreviewed");
    assert.match(await pg.locator("aside .view .paper .finding").textContent(), /not reviewed/);
    assert.match(await pg.locator("aside .view section.lean").textContent(), /Toy\.Acceptance\.thm_triangle/);
    // The parent keeps its own status and lists its steps.
    await toyClaim(pg, "T:thm:bound");
    assert.equal(await pg.locator("aside .view .chipbtn [data-status]").getAttribute("data-status"), "formal.review-pending");
    const rows = pg.locator("aside .view .steps li");
    assert.equal(await rows.count(), 2);
    assert.match(await rows.nth(1).textContent(), /Equation \(3\).*false as printed/s);
    assert.equal(await pg.locator("aside .view .paper .finding").count(), 0, "the parent has no step finding");
    await rows.nth(1).locator("a").click();
    await pg.waitForFunction(() => decodeURIComponent(location.hash).endsWith("T:eq:bound-range"));
  });
}

// A context the build holds only in part is drawn as partial, with where it was cut, in the step
// view and on the review page; a whole context carries no such mark.
for (const width of [1300, 390]) {
  await check("a proof step's cut context says where it was cut, in the reader and the review", width, async (pg) => {
    await toyClaim(pg, "T:eq:bound-range");
    const whole = pg.locator("aside .view .paper .context");
    assert.equal(await whole.getAttribute("data-cut"), "whole");
    assert.equal((await whole.locator("summary").textContent()).trim(), "Its context in the proof");
    assert.equal(await whole.locator(".cut, .cut-end").count(), 0);

    await pg.goto(origin + `/cut-step/#/r/${TOY.release}/read/T/${encodeURIComponent("T:eq:bound-range")}`);
    await pg.waitForSelector("aside h1");
    const ctx = pg.locator("aside .view .paper .context");
    assert.equal(await ctx.getAttribute("data-cut"), "cut");
    assert.equal((await ctx.locator("summary").textContent()).trim(), "Its context in the proof (cut)");
    await ctx.locator("summary").click();
    assert.equal(await pg.getByRole("note").filter({ hasText: "Cut at" }).textContent(),
      "Cut at toy.tex:71. This shows the first 20000 of its 28000 characters; the context runs on to line 80. Read the rest in the paper.");
    assert.ok(await ctx.locator(".cut-end").isVisible(), "the text ends with a mark at the cut");
    assert.match(await ctx.locator(".tex").textContent(), /k = 1/, "the kept text is still shown");
    assert.equal(await pg.locator("aside .view .chipbtn [data-status]").getAttribute("data-status"), "scope.proof-step", "the status is unchanged");

    // The review page shows the same cut before the reading is locked.
    await pg.goto(origin + `/cut-step/#/r/${TOY.release}/review?claim=T%3Aeq%3Abound-range`);
    await pg.getByRole("textbox", { name: "Your name" }).fill("Synthetic reviewer");
    await pg.getByRole("button", { name: "Start", exact: true }).click();
    const rctx = pg.locator(".review .unit .context");
    await rctx.waitFor();
    assert.equal(await rctx.getAttribute("data-cut"), "cut");
    assert.match(await rctx.locator(".cut").textContent(), /^Cut at toy\.tex:71\. This shows the first 20000 of its 28000 characters/);
    assert.ok(await rctx.locator(".cut").isVisible(), "the note is shown with the context, open");

    // Evidence that does not record where it was cut says only how much is shown.
    await pg.goto(origin + `/cut-step-old/#/r/${TOY.release}/read/T/${encodeURIComponent("T:eq:bound-range")}`);
    await pg.waitForSelector("aside h1");
    await pg.locator("aside .view .paper .context summary").click();
    assert.equal(await pg.locator("aside .view .paper .context .cut").textContent(),
      "This shows only its first 20000 characters; the build does not record where it was cut. Read the rest in the paper.");
    assert.equal(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "no horizontal scroll");
  });
}

await check("the overview counts statements and proof steps apart", 1300, async (pg) => {
  await pg.goto(origin + `/toy/#/r/${TOY.release}/overview`);
  await pg.getByRole("button", { name: /^Proof steps \(2\)$/ }).click();
  assert.equal(await pg.locator(".coverage .claims li").count(), 2);
  assert.match(await pg.locator(".coverage .claims").textContent(), /Review of the printed step: false as printed/);
  await pg.getByRole("button", { name: /^Statements \(\d+\)$/ }).click();
  assert.equal(await pg.locator(".coverage .claims li").count(), TOY.claims.length - 2);
});

for (const width of [1300, 390]) {
  await check("the overview shows the engine's semantic summary and filters by it", width, async (pg) => {
    await pg.goto(origin + `/basissem/#/r/${SHAPE.release}/overview`);
    const sem = pg.locator(".coverage .semantic");
    await sem.waitFor();
    assert.equal(await sem.getAttribute("data-digest"), SEM.basissem.semantic.digest);
    const buttons = (dim) => pg.locator(`.semantic [data-dimension="${dim}"] button`).allTextContents();
    // The engine's counts, each claim once: the same coverage with different bases, and an
    // unresolved question; nothing is added into a total.
    assert.deepEqual(await buttons("coverage"), ["Any", "Every clause (2 statements)", "Unresolved (1 statement)", `Not assessed (${SHAPE.claims.length - 3} statements)`]);
    assert.deepEqual(await buttons("basis"), ["Any", "By an argument combining Lean results (1 statement)", "Through a checked bridge (1 statement)", "Basis not recorded (1 statement)"]);
    assert.deepEqual(await buttons("findings"), ["Any", "Open questions (1 statement)"]);
    assert.match(await pg.locator(".coverage .inventory").textContent(), new RegExp(`^${SHAPE.claims.length} statements, ${SHAPE.claims.length} linked to \\d+ declarations$`));
    assert.doesNotMatch(await pg.locator(".coverage").textContent(), /%/);
    // A count applies its filter; the address names the subset, and opening it shows the same.
    await pg.getByRole("button", { name: "Unresolved (1 statement)", exact: true }).click();
    assert.equal(await pg.locator(".coverage .claims li").count(), 1);
    assert.equal(await pg.locator(".coverage .claims li .question").textContent(), "Is the paper's set finite?");
    assert.match(await pg.evaluate(() => location.hash), /\/overview\?coverage=unresolved$/);
    await pg.reload();
    await pg.locator(".coverage .claims li").first().waitFor();
    assert.equal(await pg.locator(".coverage .claims li").count(), 1);
    assert.equal(await pg.getByRole("button", { name: "Unresolved (1 statement)", exact: true }).getAttribute("aria-pressed"), "true");
    // Another reviewer's readings are a set of their own, chosen explicitly.
    const readings = pg.getByRole("combobox", { name: "Readings shown" });
    assert.deepEqual(await readings.locator("option").allTextContents(), ["The audit's readings", "Reviews by B. Reviewer"]);
    await readings.selectOption({ label: "Reviews by B. Reviewer" });
    assert.match(await pg.evaluate(() => location.hash), /set=review%3Ahuman%3AB-Reviewer/);
    await pg.getByRole("button", { name: "Any" }).first().click();
    assert.deepEqual(await buttons("coverage"), ["Any", "Every clause (1 statement)", "Unresolved (1 statement)", `Not assessed (${SHAPE.claims.length - 2} statements)`]);
    await pg.getByRole("button", { name: "Every clause (1 statement)", exact: true }).click();
    assert.equal(await pg.locator(".coverage .claims li").count(), 1);
    assert.match(await pg.locator(".coverage .claims li").textContent(), /By an argument combining Lean results \(recorded as through a checked bridge\)/);
    assert.match(await pg.locator(".coverage .claims li").textContent(), /Current, informed/);
    assert.equal(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true, "no horizontal scroll");
  });
}

await check("the overview keeps units apart and shows a workspace's readings as their own set", 1300, async (pg) => {
  await pg.goto(origin + `/toysem/#/r/${TOY.release}/overview?unit=proof_steps`);
  await pg.locator(".coverage .semantic").waitFor();
  assert.equal(await pg.getByRole("button", { name: /^Proof steps \(2\)$/ }).getAttribute("aria-pressed"), "true");
  assert.deepEqual(await pg.locator('.semantic [data-dimension="coverage"] button').allTextContents(), ["Any", "Every clause (1)", "Not assessed (1)"]);
  assert.match(await pg.locator(".coverage .inventory").textContent(), /^8 statements, 6 linked to 8 declarations · 2 proof steps \(2 equations\), 1 linked to 1 declaration$/);
  // With every unit shown, each count names its unit.
  await pg.getByRole("button", { name: /^Statements and proof steps/ }).click();
  assert.deepEqual(await pg.locator('.semantic [data-dimension="review"] button').allTextContents(),
    ["Any", "Current, independent (1 statement)", "Current, by an author (3 statements)", "Not reviewed (4 statements)", "False as printed (1 proof step)", "Printed step not reviewed (1 proof step)"]);
  await pg.goto(origin + `/toyworksem/#/r/${TOY.release}/overview`);
  const readings = pg.getByRole("combobox", { name: "Readings shown" });
  await readings.selectOption({ label: "Workspace readings by llm:synthetic-model (independent)" });
  await pg.getByRole("button", { name: "Every clause (1 statement)", exact: true }).click();
  assert.equal(await pg.locator(".coverage .claims li").count(), 1);
  assert.match(await pg.locator(".coverage .claims li").textContent(), /Definition 1\.1.*Every clause.*By an argument combining Lean results \(recorded as through a checked bridge\)/s);
});

await check("a proof step with no Lean link is reviewed as printed and reported as a step", 390, async (pg) => {
  await pg.goto(origin + `/review-step/#/r/${TOY.release}/review?claim=T%3Aeq%3Abound-range`);
  await pg.getByRole("textbox", { name: "Your name" }).fill("Synthetic reviewer");
  await pg.getByRole("button", { name: "Start", exact: true }).click();
  await pg.locator(".review .unit .pnum").waitFor();
  assert.match(await pg.locator(".review .unit").textContent(), /Proof step.*A step of the proof of Theorem 2\.5/s);
  await pg.getByRole("textbox", { name: "Your reading", exact: true }).fill("For every k >= 0, with n fixed, the step says n <= k n^2.");
  await pg.getByRole("button", { name: "Lock my reading and show the Lean" }).click();
  await pg.getByText("Different formal route used instead").waitFor();
  await pg.getByRole("textbox", { name: "Comparison", exact: true }).fill("At k = 0 and n = 1 it reads 1 <= 0.");
  await pg.getByRole("button", { name: "It fails as printed", exact: true }).click();
  await pg.getByRole("radio", { name: "False as printed", exact: true }).check();
  await pg.locator("#verdict-detail").fill("Fails at k = 0, n = 1; holds for k >= 1.");
  assert.equal(await pg.locator(".review .cover").count(), 0, "a step's review records no coverage");
  await pg.getByRole("button", { name: "Record verdict and show the author's review" }).click();
  await pg.getByRole("button", { name: "Save report", exact: true }).click();
  await pg.getByRole("button", { name: "Export reports (1 new)", exact: true }).waitFor();
  const report = await pg.evaluate(() => JSON.parse(localStorage.getItem("prooflens-review:toy-paper")).reports[0]);
  assert.equal(report.unit.kind, "step");
  assert.equal(report.unit.target, "proof-equation");
  assert.deepEqual(report.unit.lean, []);
  assert.deepEqual(report.unit.parent, { id: "T:thm:bound", number: "Theorem 2.5" });
  assert.equal(report.pins.fingerprints.source, stepChunk.source_sha256);
  assert.equal(report.verdict.value, "false as printed");
  assert.equal(report.correspondence, null);
  assert.equal(report.issue_draft.title, "Equation (3) in the proof of Theorem 2.5: false as printed");
});

// Under `view`, a linked theorem's proof is read on request: each fact with the assumptions it
// needs and the case it lies in, the weakening with the local that supplies each hypothesis, and
// a citation that keeps the fact's basis. A static copy offers none of this.
await check("the facts inside a linked theorem's proof are read on request and cited", 1300, async (pg) => {
  await pg.addInitScript(() => localStorage.setItem("machinechecked-workspace", "ws-facts"));
  await pg.goto(origin + `/pfedit/#/r/${PF.release}/claim/${encodeURIComponent("P:lem:sharp")}`);
  const panel = pg.locator("details.facts[data-decl='Facts.bound']");
  await panel.locator("summary").click();
  assert.deepEqual(pfAsked, [], "nothing is read before it is asked for");
  await panel.getByRole("button", { name: "Read the proof" }).click();
  const strong = panel.locator(".fact[data-kind=have]");
  await strong.waitFor();
  const text = (await strong.textContent()).replace(/\s+/g, " ");
  assert.match(text, /strong/);
  assert.match(text, /x ≤ C \* h/);
  assert.match(text, /assuming hx : x \+ 1 ≤ C \* h/);
  assert.match(text, /established inside this proof under this context/);
  const weaken = (await panel.locator(".fact[data-kind=application]").textContent()).replace(/\s+/g, " ");
  assert.match(weaken, /Facts\.weaken/);
  assert.match(weaken, /needs hC : 0 ≤ C, supplied by hC/);
  assert.match(weaken, /needs hx : x ≤ C \* h, supplied by strong/);
  assert.deepEqual(pfAsked, ["Facts.bound"]);
  await strong.getByRole("button", { name: "Cite in the investigation" }).click();
  await strong.getByText("cited").waitFor();
  const put = pfPosted.at(-1);
  assert.equal(put.action, "update");
  assert.equal(put.id, "ws-facts");
  const rec = put.ops[0].record;
  const expected = PF_FACTS["Facts.bound"].results.find((f) => f.name === "strong").ref;
  assert.deepEqual(rec.ref, { fact: expected });
  assert.equal(rec.role, "supports");
  assert.equal(rec.claim, "P:lem:sharp");
});

await check("a fact established in one case shows that case", 390, async (pg) => {
  await pg.goto(origin + `/pfedit/#/r/${PF.release}/claim/${encodeURIComponent("P:thm:cases")}`);
  const panel = pg.locator("details.facts[data-decl='Facts.bound_cases']");
  await panel.locator("summary").click();
  await panel.getByRole("button", { name: "Read the proof" }).click();
  const doubled = panel.locator(".fact[data-kind=have]");
  await doubled.waitFor();
  assert.match((await doubled.textContent()).replace(/\s+/g, " "), /in the case hh : 0 ≤ h/);
  assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "no horizontal scroll");
});

await check("a static copy of the reader offers no proof reading", 1300, async (pg) => {
  await pg.goto(origin + `/prooffacts/#/r/${PF.release}/claim/${encodeURIComponent("P:lem:sharp")}`);
  await pg.locator("section.lean").waitFor();
  assert.equal(await pg.locator("details.facts").count(), 0);
});

// A saved investigation, under the engine's own local server: started in the reader, resumed
// and edited through the engine's workspace service (as `machinechecked workspace` does), and
// reopened in the reader with the same question and finding.
{
  fs.cpSync(path.join(root, "toy"), path.join(root, "toyws"), { recursive: true });
  const work = path.join(root, "toyws-work");
  const { spawn } = await import("node:child_process");
  const py = spawn(process.env.PYTHON || "python3", [path.join(here, "fixtures", "workspace_server.py"), path.join(root, "toyws"), work]);
  const port = await new Promise((ok, fail) => {
    py.stdout.once("data", (d) => ok(String(d).trim()));
    py.once("exit", (c) => fail(new Error("the workspace server stopped: " + c)));
  });
  const engine = (code) => {
    const r = spawnSync(process.env.PYTHON || "python3", ["-c", code, work], { encoding: "utf8" });
    if (r.status !== 0) throw new Error(r.stderr);
    return r.stdout ? JSON.parse(r.stdout) : null;
  };
  const claimUrl = `http://127.0.0.1:${port}/#/r/${TOY.release}/claim/${encodeURIComponent("T:thm:even-add")}`;
  try {
    await check("an investigation started in the reader is resumed and edited from the terminal", 1300, async (pg) => {
      await pg.goto(claimUrl);
      const inv = pg.locator("section.investigation");
      await inv.waitFor();
      assert.match(await inv.textContent(), /informed investigation/);
      await inv.getByRole("textbox", { name: "Your name" }).fill("Test Auditor");
      await inv.getByRole("button", { name: "Start an investigation" }).click();
      await inv.locator("summary", { hasText: "Ask a question" }).click();
      await inv.getByRole("textbox", { name: "Question" }).fill("Does “even” mean ∃ k, n = 2k here?\nCheck the definition.");
      await inv.getByRole("button", { name: "Save question" }).click();
      await inv.locator("[data-kind=question]").waitFor();
      await inv.locator("summary", { hasText: "Record a finding" }).click();
      await inv.getByRole("combobox", { name: "Coverage" }).selectOption("changed");
      await inv.getByRole("textbox", { name: "Note" }).fill("The Lean adds a hypothesis.");
      await inv.getByRole("button", { name: "Save draft" }).click();
      await inv.locator("[data-kind=finding]").waitFor();

      // The terminal sees the same records, and edits the finding.
      const saved = engine(String.raw`
import json, sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
f = next(r for r in ws["records"].values() if r["kind"] == "finding")
wsp.update(p, [{"op": "put", "base_rev": f["rev"], "record": {**{k: f[k] for k in ("id", "claim", "note")}, "kind": "finding", "coverage": "full", "note": "Edited in the terminal: the hypothesis is implied."}}], Snapshot(Path(sys.argv[1]).parent / "toyws" / "data"))
print(json.dumps(wsp.read(p)))`);
      assert.equal(saved.mode, "informed");
      assert.equal(saved.reviewer.id, "human:Test-Auditor");
      assert.equal(saved.resume.claim, "T:thm:even-add");
      const q = Object.values(saved.records).find((r) => r.kind === "question");
      assert.equal(q.text, "Does “even” mean ∃ k, n = 2k here?\nCheck the definition.");
      assert.equal(saved.resume.question, q.id);

      // Reopened in a new browser context (nothing kept in the page), the edit is there.
      const pg2 = await browser.newPage({ viewport: { width: 1300, height: 900 } });
      try {
        await pg2.goto(claimUrl);
        const inv2 = pg2.locator("section.investigation");
        await inv2.getByRole("button", { name: /^Continue ws-/ }).click();
        await inv2.locator("[data-kind=finding]").waitFor();
        assert.match(await inv2.locator("[data-kind=finding]").textContent(), /Every clause[\s\S]*Edited in the terminal/);
        assert.match(await inv2.locator("[data-kind=question] .text").textContent(), /Check the definition/);
        // A stale edit from the first page is refused, and the terminal's version shown.
        await inv.getByRole("button", { name: "Submit" }).click();
        await inv.locator("[role=alert]").waitFor();
        assert.match(await inv.locator("[role=alert]").textContent(), /changed elsewhere/);
        await inv.locator("[data-kind=finding]", { hasText: "Edited in the terminal" }).waitFor();
        // A finding by composition is recorded as full coverage with its basis, and never
        // reads as a direct result.
        const add = inv.locator("details.add", { hasText: "Record a finding" });
        if (!(await add.evaluate((d) => d.open))) await add.locator("summary").click();
        await inv.getByRole("combobox", { name: "Coverage" }).selectOption("composition");
        await inv.getByRole("textbox", { name: "Argument" }).fill("Apply it to each summand.");
        await inv.getByRole("textbox", { name: "Note" }).fill("Two results combined.");
        await inv.getByRole("button", { name: "Save draft" }).click();
        const comp = inv.locator("[data-kind=finding]", { hasText: "Apply it to each summand." });
        await comp.waitFor();
        assert.match((await comp.textContent()).replace(/\s+/g, " "),
          /^Every clause, by an argument combining Lean results.*Lean has not checked this combination\..*Next step: State the combination as one Lean result\./);
      } finally { await pg2.close(); }
    });

    // A requirement of Theorem 2.2 with its source: the sentence that sets the quantifier's
    // domain is suggested from the paper's source, accepted, and a wrong suggestion removed
    // with its reason; a later use and an alignment saved from the terminal are shown apart.
    fs.mkdirSync(path.join(root, "sources", "T"), { recursive: true });
    fs.copyFileSync(path.join(here, "..", "..", "examples", "toy-paper", "paper", "toy.tex"), path.join(root, "sources", "T", "toy.tex"));
    await check("a requirement keeps the passages that govern it", 1300, async (pg) => {
      await pg.goto(`http://127.0.0.1:${port}/#/r/${TOY.release}/claim/${encodeURIComponent("T:thm:triangle")}`);
      const inv = pg.locator("section.investigation");
      await inv.getByRole("button", { name: /^Continue ws-/ }).click();
      await inv.locator("summary", { hasText: "Add a requirement" }).click();
      await inv.getByRole("textbox", { name: "Local id" }).fill("r1");
      await inv.getByRole("combobox", { name: "Form" }).selectOption("for every");
      await inv.getByRole("textbox", { name: "Variables" }).fill("n");
      await inv.getByRole("textbox", { name: "Requirement" }).fill("for every natural number n");
      await inv.getByRole("button", { name: "Save requirement" }).click();
      const req = inv.locator("[data-req=r1]");
      await req.waitFor();
      assert.match(await req.textContent(), /r1 for every n: for every natural number n[\s\S]*the statement · this claim's passage · printed for this claim/);
      await req.getByRole("button", { name: "Suggest nearby context" }).click();
      const proposed = req.locator(".frag.proposed", { hasText: "For every natural number $n$," });
      await proposed.waitFor();
      assert.match(await proposed.textContent(), /Suggested: domain of a quantifier · toy\.tex:46/);
      await proposed.getByRole("button", { name: "Accept" }).click();
      const accepted = req.locator(".frag[data-role='quantifier domain']:not(.proposed)");
      await accepted.waitFor();
      assert.match(await accepted.textContent(), /For every natural number \$n\$,[\s\S]*domain of a quantifier · toy\.tex:46 · printed for this claim · by human:Test-Auditor \(suggested by MachineChecked\)/);
      // A later use and an alignment, saved through the engine.
      engine(String.raw`
import json, sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
s = Snapshot(Path(sys.argv[1]).parent / "toyws" / "data")
wsp.update(p, [{"op": "put", "record": {"kind": "fragment", "claim": "T:thm:triangle", "requirement": "r1", "role": "later use", "region": {"file": "toy.tex", "start_line": 79}}},
               {"op": "put", "record": {"kind": "fragment", "claim": "T:thm:triangle", "requirement": "r1", "role": "context", "origin": "inferred", "state": "proposed", "region": {"file": "toy.tex", "start_line": 41}}},
               {"op": "put", "record": {"kind": "alignment", "claim": "T:thm:triangle", "requirements": ["r1"], "lean": [{"decl": "Toy.PaperSpec.thm_triangle", "var": "n"}]}}], s)
print("null")`);
      await pg.reload();
      await req.locator(".frag.use").waitFor();
      assert.match(await req.locator(".frag.use").textContent(), /Used later at toy\.tex:79: a use of the result; this reading is unchanged/);
      assert.match(await req.locator("[data-alignment]").textContent(), /Lean: Toy\.PaperSpec\.thm_triangle \(variable: n\) · corresponds · recorded by human:Test-Auditor/);
      assert.equal(await inv.locator(".witness").count(), 0);
      // A wrong proposal is removed with its reason, and kept as removed.
      const wrong = req.locator(".frag.proposed");
      await wrong.getByRole("button", { name: "Remove" }).click();
      await req.getByRole("textbox", { name: "Why remove it" }).fill("Not about n.");
      await req.getByRole("button", { name: "Remove passage" }).click();
      await req.locator("details.removed").waitFor();
      assert.equal(await req.locator(".frag.proposed").count(), 0);
      await req.locator("details.removed summary").click();
      assert.match(await req.locator("details.removed").textContent(), /toy\.tex:41 \(context\), removed by human:Test-Auditor: Not about n\./);

      // A composition saved from the terminal is shown with its steps and obligations, as the
      // auditor's argument with the next step.
      engine(String.raw`
import sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
s = Snapshot(Path(sys.argv[1]).parent / "toyws" / "data")
wsp.update(p, [{"op": "put", "record": {"id": "e-tri", "kind": "evidence", "claim": "T:thm:triangle", "role": "supports", "ref": {"decl": "Toy.Acceptance.thm_triangle", "external": True}}},
               {"op": "put", "record": {"id": "c-tri", "kind": "composition", "claim": "T:thm:triangle", "coverage": "full", "steps": [
                   {"id": "s1", "establishes": "the closed form for every n", "uses": ["e-tri"], "requirements": ["r1"]}]}},
               {"op": "put", "record": {"id": "f-tri", "kind": "finding", "claim": "T:thm:triangle", "coverage": "full", "basis": "reviewed_composition", "composition": "c-tri", "note": "By the composition."}}], s)
print("null")`);
      await pg.reload();
      const comp = inv.locator("[data-composition='c-tri']");
      await comp.waitFor();
      assert.match((await comp.textContent()).replace(/\s+/g, " "),
        /^Every clause, by an argument combining Lean results · composition c-tri · human:Test-Auditor s1 the closed form for every n · from Toy\.Acceptance\.thm_triangle · establishes r1 Lean has not checked this combination\. Next step: State the combination as one Lean result\.$/);
      const f = inv.locator("[data-kind=finding]", { hasText: "By the composition." });
      assert.match((await f.textContent()).replace(/\s+/g, " "), /^Every clause, by an argument combining Lean results.*Rests on composition c-tri\./);
    });


    // An alignment made in the reader (#99): a requirement's passage, the expression selected in
    // the Lean, and a whole declaration, saved together and removed again.
    await check("an alignment is made in the reader from a passage and the selected expression", 1300, async (pg) => {
      await pg.goto(`http://127.0.0.1:${port}/#/r/${TOY.release}/claim/${encodeURIComponent("T:thm:triangle")}`);
      const inv = pg.locator("section.investigation");
      await inv.getByRole("button", { name: /^Continue ws-/ }).click();
      const form = inv.locator("details.align");
      await form.locator("summary").click();
      await form.locator("[data-al-req='r1']").check();
      await form.locator("label", { hasText: "toy.tex:46" }).locator("input").check();
      await pg.locator("section.lean .concl .p", { hasText: "+" }).first().click();
      await form.getByRole("button", { name: "Add the expression selected in Toy.PaperSpec.thm_triangle" }).click();
      await form.getByRole("combobox", { name: "A whole declaration" }).selectOption("Toy.PaperSpec.thm_triangle");
      await form.getByRole("button", { name: "Add", exact: true }).click();
      assert.equal(await form.locator(".target").count(), 2);
      await form.getByRole("textbox", { name: "Alignment note" }).fill("The sum is the triangular number.");
      await form.getByRole("button", { name: "Save alignment" }).click();
      const req = inv.locator("[data-req=r1]");
      const made = req.locator("[data-alignment]", { hasText: "On toy.tex:46" });
      await made.waitFor();
      assert.match((await made.textContent()).replace(/\s+/g, " "),
        /^On toy\.tex:46: Lean: Toy\.PaperSpec\.thm_triangle \(sub-term: \(?n \+ 1\)?\); Toy\.PaperSpec\.thm_triangle · corresponds · recorded by human:Test-Auditor The sum is the triangular number\. · Remove$/);
      const id = await made.getAttribute("data-alignment");
      const saved = engine(String.raw`
import json, sys
from pathlib import Path
from prooflens import workspace as wsp
(p, ws), = wsp.list_all(Path(sys.argv[1]))
print(json.dumps(ws["records"][sys.argv[2]]))`.replace("sys.argv[2]", JSON.stringify(id)));
      assert.deepEqual(saved.requirements, ["r1"]);
      assert.equal(saved.fragments.length, 1);
      assert.ok(saved.lean[0].at && saved.lean[0].target.includes("+"), JSON.stringify(saved.lean));
      await made.getByRole("button", { name: "Remove" }).click();
      await req.locator("[data-alignment]", { hasText: "On toy.tex:46" }).waitFor({ state: "detached" });
      assert.equal(await req.locator("[data-alignment]", { hasText: "On toy.tex:46" }).count(), 0);
    });

    // A printed proof step refuted by a counterexample (#111): the step's reading with the
    // order of its quantifiers, the counterexample and what its certificate checks, the
    // finding on the step, and the corrected reading with its own evidence, apart.
    await check("a refuted proof step shows its counterexample and the corrected reading apart", 1300, async (pg) => {
      engine(String.raw`
import sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
s = Snapshot(Path(sys.argv[1]).parent / "toyws" / "data")
C = "T:eq:bound-range"
def req(lid, form, text, **kw):
    return {"op": "put", "record": {"kind": "requirement", "claim": C, "local_id": lid, "form": form, "text": text, **kw}}
def cert(theorem, target, certifies, stmt):
    return {"certificate": {"theorem": theorem, "target": target, "certifies": certifies, "type": ("¬" if certifies == "refutes" else "") + target, "target_statement": stmt, "target_fingerprint": "0" * 16, "result": "checked", "reasons": []}}
wsp.update(p, [
  req("n", "for every", "the n fixed by the proof", binds=["n"], domain="n ≥ 0"),
  req("n.k", "for every", "every natural number k ≥ 0", binds=["k"], domain="k ≥ 0", parent="n"),
  req("n.k.1", "conclusion", "n ≤ k n²", parent="n.k"),
  {"op": "put", "record": {"kind": "fragment", "claim": C, "requirement": "n.k.1", "role": "statement", "passage": {"claim": C}}},
  req("n.kc", "for every", "every natural number k ≥ 1", binds=["k"], domain="k ≥ 1", parent="n", origin="correction", corrects="n.k"),
  {"op": "put", "record": {"kind": "fragment", "claim": C, "requirement": "n.kc", "role": "proposed correction", "passage": {"claim": C}}},
  {"op": "put", "record": {"id": "e-ref", "kind": "evidence", "claim": C, "role": "supports", "ref": cert("ToyAudit.bound_range_at_one_false", "ToyAudit.bound_range_at_one", "refutes", "∀ (k : Nat), 1 ≤ k * 1 ^ 2")}},
  {"op": "put", "record": {"id": "x-zero", "kind": "counterexample", "claim": C, "requirement": "n.k.1", "specialisation": {"assign": {"n": 1, "k": 0}}, "reduced": "1 ≤ k · 1²", "violation": "at k = 0 it reads 1 ≤ 0", "admissibility": [{"obligation": "k = 0 satisfies k ≥ 0", "state": "verified", "method": "arithmetic"}], "evidence": ["e-ref"]}},
  {"op": "put", "record": {"id": "f-false", "kind": "finding", "claim": C, "requirement": "n.k.1", "verdict": "false as printed", "counterexamples": ["x-zero"], "note": "k = 0, n = 1."}},
  {"op": "put", "record": {"id": "e-pro", "kind": "evidence", "claim": C, "role": "supports", "ref": cert("ToyAudit.bound_range_corrected_holds", "ToyAudit.bound_range_corrected", "proves", "∀ (n k : Nat), 1 ≤ k → n ≤ k * n ^ 2")}},
  {"op": "put", "record": {"id": "f-fixed", "kind": "finding", "claim": C, "requirement": "n.kc", "coverage": "full", "basis": "checked_bridge", "evidence": ["e-pro"], "note": "holds for k ≥ 1"}},
  {"op": "put", "record": {"id": "f-order", "kind": "finding", "claim": C, "requirement": "n.k.1", "difference": {"feature": "domain", "paper": "k ≥ 0", "lean": "1 ≤ k", "outcome": "difference", "transport": "none applies: k = 0 is excluded"}, "note": "the Lean adds k ≥ 1"}}], s)
print("null")`);
      await pg.goto(`http://127.0.0.1:${port}/#/r/${TOY.release}/claim/${encodeURIComponent("T:eq:bound-range")}`);
      const inv = pg.locator("section.investigation");
      await inv.getByRole("button", { name: /^Continue ws-/ }).click();
      const req = inv.locator("[data-req='n.k.1']");
      await req.waitFor();
      const printed = req.locator(".estimate[data-reading=printed]");
      assert.match(await printed.textContent(), /Read as printed: for every n \(n ≥ 0\); for every k \(k ≥ 0\): n ≤ k n²/);
      const cx = printed.locator("[data-cx=x-zero]");
      assert.equal(await cx.getAttribute("data-standing"), "admissible counterexample");
      assert.match(await cx.textContent(), /n = 1, k = 0 reduces the reading to 1 ≤ k · 1², which fails \(at k = 0 it reads 1 ≤ 0\)\./);
      assert.match(await cx.locator(".cert").textContent(), /^Lean checks that the type of ToyAudit\.bound_range_at_one_false is the negation of ToyAudit\.bound_range_at_one \(∀ \(k : Nat\), 1 ≤ k \* 1 \^ 2\)\. It certifies that proposition only, not the reading it is attached to\./);
      assert.match(await printed.locator(".verdict").textContent(), /The printed step: false as printed/);
      // The corrected reading has its own evidence; the printed requirement stays.
      const corrected = req.locator(".estimate[data-reading='n.kc']");
      assert.match(await corrected.textContent(), /Read with the correction n\.kc: for every n \(n ≥ 0\); for every k \(k ≥ 1\): n ≤ k n²/);
      assert.equal(await corrected.locator("[data-cx]").count(), 0);
      assert.match(await corrected.locator(".cert").textContent(), /ToyAudit\.bound_range_corrected_holds is exactly ToyAudit\.bound_range_corrected/);
      assert.match(await inv.locator("[data-req='n.k']").textContent(), /n\.k for every k \(k ≥ 0\): every natural number k ≥ 0/);
      assert.match(await req.locator(".diff[data-feature=domain]").textContent(), /Domain, a difference: paper k ≥ 0; Lean 1 ≤ k · transport inspected: none applies/);
      assert.match(await inv.locator("[data-kind=finding]", { hasText: "k = 0, n = 1." }).textContent(), /The printed step: false as printed/);
      // A finding recorded as a checked bridge with no bridge reads as the auditor's composition.
      const fixed = inv.locator("[data-kind=finding]", { hasText: "holds for k ≥ 1" });
      assert.match(await fixed.locator("strong").first().textContent(), /^Every clause, by an argument combining Lean results$/);
      assert.equal(await fixed.locator("[data-line='recorded']").textContent(),
                   "Recorded as a checked bridge; no bridge Lean checks now: no bridge is recorded.");
    });

    // #77: an informed investigation opens its saved evidence beside the claim, and keeps the
    // comparison's pins in its resume state: a resumed investigation shows them where they were,
    // on the same build only.
    await check("an investigation opens its saved evidence beside the claim and resumes its pins", 1300, async (pg) => {
      engine(String.raw`
import sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
wsp.update(p, [{"op": "put", "record": {"id": "e-even", "kind": "evidence", "claim": "T:thm:even-add", "ref": {"decl": "Toy.IsEven"}, "role": "supports"}}], Snapshot(Path(sys.argv[1]).parent / "toyws" / "data"))
print("null")`);
      const resume = () => engine(String.raw`
import json, sys
from pathlib import Path
from prooflens import workspace as wsp
(p, ws), = wsp.list_all(Path(sys.argv[1]))
print(json.dumps(ws["resume"]))`);
      await pg.goto(claimUrl);
      const inv = pg.locator("section.investigation");
      await inv.getByRole("button", { name: /^Continue ws-/ }).click();
      await inv.locator("button.ev[data-evidence='e-even']").click();
      const saved = pg.locator(".cmp .inspection[data-kind='evidence']");
      await saved.locator(".decl.inspector").waitFor();
      assert.match(await saved.textContent(), /Saved in the investigation ws-\w+ as supports/);
      assert.match(await saved.locator(".decl.inspector").textContent(), /Toy\.IsEven/);
      assert.ok(await pg.locator("h1").isVisible() && await pg.locator(".cmp .stmt .concl").isVisible(), "the claim stays");
      await saved.locator(".back").click();
      await saved.waitFor({ state: "detached" });
      // A definition pinned beside its row is saved where the investigation resumes.
      const row = pg.locator(".stmt [data-row='b:2']");
      await row.locator("[data-slot=readable] a.r", { hasText: "Toy.IsEven" }).click();
      const panel = row.locator(".inspection");
      await panel.locator(".decl.inspector").waitFor();
      await panel.getByRole("button", { name: "Pin" }).click();
      assert.ok(await until(() => (resume().pinned || []).length === 1, 8000), "the pin is saved");
      const r = resume();
      assert.equal(r.claim, "T:thm:even-add");
      assert.deepEqual(r.pinned.map((x) => [x.token, x.at, x.release]), [["Toy.IsEven", "Toy.PaperSpec.thm_even_add::b:2", TOY.release]]);
      // Resumed in a new browser, the pin is where it was.
      const pg2 = await browser.newPage({ viewport: { width: 1300, height: 900 } });
      try {
        await pg2.goto(claimUrl);
        await pg2.locator("section.investigation").getByRole("button", { name: /^Continue ws-/ }).click();
        await pg2.locator(".stmt [data-row='b:2'] .inspection.pinned .decl.inspector").waitFor();
      } finally { await pg2.close(); }
      // A pin saved on another build of the project is not shown on this one.
      engine(String.raw`
import sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
(p, ws), = wsp.list_all(Path(sys.argv[1]))
pinned = [{**x, "release": "r-another-build"} for x in ws["resume"]["pinned"]]
wsp.update(p, [{"op": "resume", "state": {"claim": "T:thm:even-add", "pinned": pinned}}], Snapshot(Path(sys.argv[1]).parent / "toyws" / "data"))
print("null")`);
      const pg3 = await browser.newPage({ viewport: { width: 1300, height: 900 } });
      try {
        await pg3.goto(claimUrl);
        const inv3 = pg3.locator("section.investigation");
        await inv3.getByRole("button", { name: /^Continue ws-/ }).click();
        await inv3.locator("button.ev[data-evidence='e-even']").waitFor();
        assert.equal(await pg3.locator(".inspection").count(), 0, "no pin from another build");
        assert.equal(resume().pinned[0].release, "r-another-build", "and the saved one is left as it was");
      } finally { await pg3.close(); }
    });

    // The informed order (#128), from the engine's own local server: asked for before anything is
    // fetched, its exposure recorded before it is shown, the order and reasons the engine gives,
    // and held back from a reading locked without it until that reading's verdict.
    await check("the informed review order is asked for, recorded as exposure and held back before a verdict", 1300, async (pg) => {
      const queue = queueFor(path.join(root, "toyws", "data"));
      const expected = engine(String.raw`
import json, sys
from pathlib import Path
from prooflens import workspace as wsp
from prooflens.review_cli import order_route
from prooflens.targets import Snapshot
work = Path(sys.argv[1])
data = work.parent / "toyws" / "data"
(p, ws), = wsp.list_all(work)
wsp.update(p, [{"op": "put", "record": {"kind": "question", "claim": "T:prop:pred", "text": "Is n = 0 allowed?"}},
               {"op": "put", "record": {"kind": "finding", "claim": "T:cor:even-triangle", "coverage": "changed", "note": "Stated for n ≥ 1."}}], Snapshot(data))
print(json.dumps(order_route(work, data)({"order": ["informed"]})))`);
      const byId = Object.fromEntries(queue.units.map((u) => [u.id, u]));
      const locked = "spec:Toy.PaperSpec.prop_pred";
      assert.equal(queue.units[0].id, locked, "first in the queue's order");
      assert.equal(expected.units[0].id, locked, "first in the informed order");
      assert.match(expected.units[0].reason, /^An open question is recorded; /);
      assert.ok(expected.drawn.includes("T:prop:pred") && expected.drawn.includes("T:cor:even-triangle"));
      assert.notDeepEqual(expected.units.map((u) => u.id), queue.units.filter((u) => u.state !== "reviewed").map((u) => u.id));
      const saved = () => pg.evaluate((k) => JSON.parse(localStorage.getItem(k) || "{}"), REVIEW_KEY);
      await pg.goto(`http://127.0.0.1:${port}/#/r/${TOY.release}/review`);
      // A reading locked before the informed order is chosen; its verdict is not yet recorded.
      await pg.evaluate(([k, id]) => localStorage.setItem(k, JSON.stringify({ reviewer: { kind: "human", name: "Synthetic reviewer" },
        drafts: { [id]: { stage: "compare", reading: "A reading locked before the informed order.", locked_at: "2026-01-01T00:00:00Z", revealed_by: [] } } })), [REVIEW_KEY, locked]);
      const asked = [];
      pg.on("request", (r) => { if (r.url().includes("/api/review-order")) asked.push(r.url()); });
      await pg.reload();
      await whyIs(pg, `Statement · ${byId[locked].reason}`);
      const order = pg.getByRole("combobox", { name: "Order", exact: true });
      assert.equal(await order.locator("option[value=informed]").evaluate((o) => o.disabled), false, "the local server offers it");
      // Choosing it asks first; nothing is fetched or recorded until the reviewer agrees.
      await order.selectOption("informed");
      const ask = pg.getByRole("region", { name: "The informed order" });
      await ask.waitFor();
      assert.match(await ask.textContent(), /prior interpretations[\s\S]*recorded as not blind/);
      assert.equal(await order.inputValue(), "priority");
      await ask.getByRole("button", { name: "Keep the priority order" }).click();
      assert.equal(await ask.count(), 0);
      assert.deepEqual(asked, []);
      assert.deepEqual((await saved()).exposure || [], []);
      await order.selectOption("informed");
      await ask.getByRole("button", { name: "Use the informed order" }).click();
      await pg.locator(".review [role=status]", { hasText: "draws on the workspaces' records" }).waitFor();
      let work = await saved();
      assert.equal(work.order, "informed");
      assert.deepEqual(work.exposure.map((e) => [e.what, e.claims, e.how]),
                       [[["prior interpretations"], [...expected.drawn].sort(), "interpretation-informed review order"]]);
      // The reading locked without it: its card keeps the queue's reason until the verdict.
      await whyIs(pg, `Statement · ${byId[locked].reason} · the informed order's reason for it is shown after your verdict`);
      await pg.getByRole("textbox", { name: "Comparison", exact: true }).fill("The synthetic comparison of this reading.");
      await pg.getByRole("button", { name: "Matches the paper", exact: true }).click();
      await pg.getByRole("radio", { name: "Faithful", exact: true }).check();
      await pg.getByRole("button", { name: "Record verdict and show the author's review" }).click();
      await whyIs(pg, `Statement · ${expected.units[0].reason}`);
      await pg.getByRole("button", { name: "Save report", exact: true }).click();
      assert.deepEqual((await saved()).reports[0].reading.revealed_by, [], "that reading was blind");
      // The next units come in the engine's informed order, with its reasons; a reading of a claim
      // the order drew on is recorded as not blind.
      const next = expected.units[1];
      assert.match(next.reason, /^An open question is recorded; /);
      await whyIs(pg, `${kindWord(byId[next.id])} · ${next.reason}`);
      assert.match(await pg.locator(".review .unit .warn").textContent(), /prior interpretations of its claims \(through the informed order\)/);
      await pg.getByRole("textbox", { name: "Your reading", exact: true }).fill("A reading made after choosing the informed order.");
      await pg.getByRole("button", { name: "Lock my reading and show the Lean" }).click();
      await whyIs(pg, `${kindWord(byId[next.id])} · ${next.reason}`);
      work = await saved();
      assert.deepEqual(work.drafts[next.id].revealed_by, [{ unit: "review page (interpretation-informed review order)", what: "author's review" }]);
      await pg.getByRole("button", { name: "Skip", exact: true }).click();
      for (const u of expected.units.slice(2, 5)) {
        await whyIs(pg, `${kindWord(byId[u.id])} · ${u.reason}`);
        await pg.getByRole("button", { name: "Skip", exact: true }).click();
      }
      // The choice is kept; loading it again records nothing new.
      await pg.reload();
      await pg.locator(".review [role=status]", { hasText: "draws on the workspaces' records" }).waitFor();
      assert.equal(await order.inputValue(), "informed");
      assert.equal((await saved()).exposure.length, 1);
    });
  } finally { py.kill(); }
}

// The findings a revision of the paper reopens (#120), under the engine's own local server: a
// workspace made by the engine against the toy build, with the version map it keeps from an
// earlier release to this one (a synthetic map of the toy's claims: one moved and renumbered,
// one changed, one ambiguous), and a declaration changed in this build since.
{
  fs.cpSync(path.join(root, "toy"), path.join(root, "toyrev"), { recursive: true });
  const work = path.join(root, "toyrev-work");
  const made = spawnSync(process.env.PYTHON || "python3", ["-c", String.raw`
import json, sys
from pathlib import Path
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot
work, data, release = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
s = Snapshot(data)
p = wsp.open_for(work, rc.parse_reviewer("human:Test-Auditor"), "informed", sources=s.sources())
put = lambda r: {"op": "put", "record": r}
wsp.update(p, [
  put({"id": "e-even", "kind": "evidence", "claim": "T:thm:even-add", "role": "supports", "ref": {"decl": "Toy.PaperSpec.thm_even_add"}}),
  put({"id": "f-moved", "kind": "finding", "claim": "T:thm:even-add", "coverage": "full", "basis": "direct", "evidence": ["e-even"], "note": "SYNTHETIC: the Lean states it."}),
  put({"id": "f-quiet", "kind": "finding", "claim": "T:thm:even-add", "coverage": "partial", "note": "SYNTHETIC: a note on the moved theorem."}),
  put({"id": "f-bound", "kind": "finding", "claim": "T:thm:bound", "coverage": "full", "note": "SYNTHETIC: the bound with its constant."}),
  put({"id": "f-pred", "kind": "finding", "claim": "T:prop:pred", "coverage": "partial", "note": "SYNTHETIC: the predecessor."})], s)
wsp.update(p, [{"op": "submit", "id": i, "base_rev": 1} for i in ("f-moved", "f-quiet", "f-bound", "f-pred")], s)
def side(cid, number, line, sha=None):
    return {"claim": cid, "number": number, "location": f"toy.tex:{line}", "sha256": sha or s.chunk(cid)["source_sha256"]}
doc = {"schema": "prooflens/version-map@1", "paper": "T", "from": {"release": "r-earlier"}, "to": {"release": release},
  "claims": [
    {"class": "moved", "reason": "the same text at another place, now Theorem 2.2", "by": ["text"], "renumbered": True, "moved": True,
     "from": side("T:thm:even-add", "Theorem 2.1", 40), "to": side("T:thm:even-add", "Theorem 2.2", 44)},
    {"class": "changed", "reason": "its label leads to a passage with other text", "by": ["label"],
     "from": side("T:thm:bound", "Theorem 2.5", 70), "to": side("T:thm:bound", "Theorem 2.6", 74, "f" * 64),
     "change": {"diff": ["--- toy.tex:70 at r1", "+++ toy.tex:74 at r2", "@@ -1 +1 @@", "-such that $T_n \\le C n^2$", "+such that $T_n \\le C n^2 + 1$ <img src=x onerror=alert(1)>"]}},
    {"class": "ambiguous", "reason": "label prop:pred occurs 2 times", "by": [], "from": side("T:prop:pred", "Proposition 2.3", 50), "to": None,
     "candidates": [{"claim": "T:prop:pred", "by": ["label"]}, {"claim": "T:rem:pred", "by": ["label"]}]}],
  "passages": []}
wsp.update(p, [{"op": "version-map", "map": doc}], s)
# A declaration the moved theorem's finding cites changes in this build.
for f in (data / "claims").glob("*.json"):
    t = f.read_text()
    fp = s.fingerprints()["Toy.PaperSpec.thm_even_add"]
    if fp in t:
        f.write_text(t.replace(fp, "pl-fp-v1:synthetic-later"))
print(json.dumps({"id": wsp.read(p)["id"]}))`, work, path.join(root, "toyrev", "data"), TOY.release], { encoding: "utf8" });
  if (made.status !== 0) throw new Error("the engine could not make the workspace:\n" + made.stderr);
  const wsId = JSON.parse(made.stdout).id;
  const { spawn } = await import("node:child_process");
  const py = spawn(process.env.PYTHON || "python3", [path.join(here, "fixtures", "workspace_server.py"), path.join(root, "toyrev"), work]);
  const port = await new Promise((ok, fail) => {
    py.stdout.once("data", (d) => ok(String(d).trim()));
    py.once("exit", (c) => fail(new Error("the workspace server stopped: " + c)));
  });
  try {
    for (const width of [390, 1300]) {
      await check("the changes view shows the findings a revision of the paper reopens", width, async (pg) => {
        await pg.goto(`http://127.0.0.1:${port}/#/r/${TOY.release}/changes`);
        const section = pg.locator("[data-revision]");
        await section.waitFor();
        assert.match(await section.locator(".where").textContent(), new RegExp(`Workspace ${wsId}, paper T: release r-earlier → ${TOY.release}; version map kept by human:Test-Auditor`));
        // The changed theorem first: the earlier finding, the change with both texts, the
        // dependency and the question; the diff is text.
        const bound = section.locator("article[data-claim='T:thm:bound']");
        assert.match(await bound.locator("h3").textContent(), /Theorem 2\.5 → Theorem 2\.6\s*Passage changed/);
        assert.equal(await bound.locator("h3 a").getAttribute("href"), `#/r/${TOY.release}/claim/T%3Athm%3Abound`);
        const fb = bound.locator("[data-finding='f-bound']");
        assert.equal(await fb.getAttribute("data-state"), "reopened");
        assert.match(await fb.locator("p").first().textContent(), /^Due for review: finding f-bound by human:Test-Auditor: Every clause$/);
        assert.equal(await fb.locator(".earlier").textContent(), "SYNTHETIC: the bound with its constant.");
        assert.match(await fb.locator(".dep p").first().textContent(), /^Changed: the passage of T:thm:bound \(toy\.tex:70 → toy\.tex:74\): its label leads to a passage with other text\.$/);
        assert.deepEqual(await fb.locator(".diff .del").allTextContents(), ["-such that $T_n \\le C n^2$"]);
        assert.deepEqual(await fb.locator(".diff .add").allTextContents(), ["+such that $T_n \\le C n^2 + 1$ <img src=x onerror=alert(1)>"]);
        assert.equal(await fb.locator(".diff img").count(), 0);
        assert.equal(await fb.locator(".question").textContent(), "Does finding f-bound still hold for the changed text of Theorem 2.6 (T:thm:bound)?");
        // The ambiguous claim: not known to be current, with the candidates.
        const pred = section.locator("[data-finding='f-pred']");
        assert.equal(await pred.getAttribute("data-state"), "unchecked");
        assert.match(await pred.locator(".dep p").textContent(), /^Not known: the passage of T:prop:pred \(toy\.tex:50\): the version map cannot tell which later claim Proposition 2\.3 \(T:prop:pred\) is: .*candidates: T:prop:pred, T:rem:pred.*--match\.$/);
        // The moved theorem: its passage keeps both findings current; the declaration one cites
        // changed in this build, which reopens that one only.
        const moved = section.locator("article[data-claim='T:thm:even-add']");
        assert.match(await moved.locator("h3").textContent(), /Theorem 2\.1 → Theorem 2\.2\s*Moved/);
        const fm = moved.locator("[data-finding='f-moved']");
        assert.equal(await fm.getAttribute("data-state"), "reopened");
        assert.match(await fm.locator(".kept").textContent(), /^Still current: the passage of T:thm:even-add: the same text at another place, now Theorem 2\.2\.$/);
        assert.equal(await fm.locator("[data-dep=build] p").first().textContent(), "Changed in this build: Toy.PaperSpec.thm_even_add changed.");
        const fq = moved.locator("[data-finding='f-quiet']");
        assert.equal(await fq.getAttribute("data-state"), "current");
        assert.match(await fq.textContent(), /Still current: finding f-quiet by human:Test-Auditor: Part of the claim[\s\S]*Still current: the passage of T:thm:even-add/);
        // Those with something to review come first.
        assert.deepEqual(await section.locator("article.claim").evaluateAll((xs) => xs.map((x) => x.dataset.claim)),
                         ["T:thm:bound", "T:thm:even-add", "T:prop:pred"]);
        assert.ok(await pg.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "no horizontal scroll");
        if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `revision-${width}.png`), fullPage: true });
      });
    }
    await check("a static copy of the site shows no workspace across the revision", 1300, async (pg) => {
      await pg.goto(origin + "/toychanges/" + `#/r/${TOY.release}/changes`);
      await pg.locator("[data-changes]").waitFor();
      assert.equal(await pg.locator("[data-revision]").count(), 0);
    });
  } finally { py.kill(); }
}

await browser.close();
server.close();
fs.rmSync(root, { recursive: true, force: true });
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all reader tests passed");
