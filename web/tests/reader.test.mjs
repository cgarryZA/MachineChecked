// Browser tests of the built reader (engine/python/prooflens/web), in headless Chromium, at a
// laptop and a phone width. Run after `npm run build`: `node tests/reader.test.mjs`.
// Set CHROMIUM to a browser binary when Playwright's own is not installed, and SHOTS to a
// directory to keep screenshots.
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
from prooflens.paper import paper_claims, write_paper_site
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

# A paper in two versions, one page each (as machinechecked.org writes them): arXiv v1, and the
# latest manuscript at a commit, whose claims are numbered differently and linked differently.
two = {**paper, "id": "arxiv:2601.00003", "title": "A paper in two versions"}
versions = [{"id": "arxiv:2601.00003v1", "kind": "published", "href": "/versions/v1/",
             "pdf": "https://arxiv.org/pdf/2601.00003v1", "audits": []},
            {"id": "manuscript:abc1234", "kind": "manuscript", "revision": "abc1234" + "0" * 33,
             "href": "../latest/", "label": "arXiv v2", "audits": []}]
pages = {"v1": ([anchor("theorem", "1", 1, 100), anchor("theorem", "2", 1, 300)],
                [("theorem", "1", ["A.one"])], [("theorem", "2", ["B.two"])], "Version one text."),
         "latest": ([anchor("lemma", "1", 1, 100), anchor("theorem", "2", 1, 300),
                     anchor("theorem", "3", 1, 500)],
                    [("theorem", "3", ["A.three"])], [], "Latest manuscript text.")}
for (name, (anchors, a_rows, b_rows, text)), v in zip(pages.items(), versions):
    site = Path(sys.argv[1]).parent / "versions" / name
    cl = paper_claims(anchors, two["title"], [(two["formalisations"][0], fy(a_rows)),
                                              (two["formalisations"][1], fy(b_rows))])
    write_paper_site(site, two, cl, [612, 792], "paper.pdf", Path(sys.argv[2]),
                     versions=versions, version=v["id"])
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
for (const c of SHAPE.claims) {
  const f = path.join(root, "basis", "data", "claims", c.file);
  const chunk = JSON.parse(fs.readFileSync(f, "utf8"));
  chunk.correspondence = { source: "confirmed", basis: null, refs: [], argument: null, bridge: null, question: null,
                           would_decide: null, confidence: null, note: "", by: "A. Auditor", ...READINGS[c.id] };
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

fs.cpSync(path.join(root, "toy"), path.join(root, "long-statement"), { recursive: true });
const longFile = TOY.claims.find((c) => c.id === "T:thm:even-add").file;
const longPath = path.join(root, "long-statement/data/claims", longFile);
const longClaim = JSON.parse(fs.readFileSync(longPath));
const longStatement = longClaim.clauses[0].statement;
longStatement.binders = Array.from({ length: 12 }, (_, i) => ({ name: `x${i}`, role: "forall", binder: "explicit", type: { text: "Nat" } }));
longStatement.conclusion = { text: "x0 = x0" };
longStatement.exact = { text: "∀ " + longStatement.binders.map((b) => `(${b.name} : Nat)`).join(" ") + ", x0 = x0" };
fs.writeFileSync(longPath, JSON.stringify(longClaim));

const types = { ".pdf": "application/pdf", ".html": "text/html", ".json": "application/json", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" };
// `/toyedit/` is the toy reader as the local `view` serves it: its index says it may edit, and
// symbol links it saves are captured here instead of written.
const posted = [];
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
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

async function check(name, width, fn) {
  const pg = await browser.newPage({ viewport: { width, height: 900 } });
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
const inView = (pg, id) => pg.evaluate((id) => {
  const band = document.querySelector(`[data-claim="${CSS.escape(id)}"]`);
  const pane = band?.closest(".paperpane");
  if (!band || !pane) return false;
  const b = band.getBoundingClientRect(), p = pane.getBoundingClientRect();
  return b.top >= p.top - 1 && b.top <= p.bottom;
}, id);
const ids = ["P:theorem-2", "P:theorem-15", "P:theorem-28"];
await check("a claim chosen in a long paper stays in view (contents and deep links)", 1300, async (pg) => {
  await pg.goto(origin + "/long/");
  await pg.waitForSelector("nav.toc li");
  for (const id of [...ids, ids[0]]) {
    await pg.locator(".reader-layout > nav.toc strong", { hasText: new RegExp(`^Theorem ${id.split("-")[1]}$`) }).click();
    await pg.waitForTimeout(600);
    assert.ok(await inView(pg, id), `${id} not in view after choosing it`);
  }
  for (const id of ids) {
    const cold = await browser.newPage({ viewport: { width: 1300, height: 900 } });
    await cold.goto(origin + `/long/#/r/paper/read/P/${encodeURIComponent(id)}`);
    await cold.waitForSelector("aside h1");
    await cold.waitForTimeout(800);
    assert.ok(await inView(cold, id), `${id} not in view when opened by its link`);
    await cold.close();
  }
});

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

// The claim inspector on the toy audit: opening a definition replaces the panel's contents and
// leaves the paper where it was; Back brings the claim back as it was left.
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
await check("a theorem of the toy paper is typeset with its equation number", 1300, async (pg) => {
  await toyClaim(pg, "T:thm:triangle");
  const ex = pg.locator("aside .view .paper .excerpt");
  await ex.locator(".katex").first().waitFor();
  assert.match(await ex.locator(".display .tag").textContent(), /\(1\)/);
});

for (const width of [1300, 390]) {
  await check("opening a definition replaces the panel; Back restores the claim as it was", width, async (pg) => {
    await toyClaim(pg, "T:def:even");
    const ref = pg.locator("aside .lean .ref", { hasText: "Toy.IsEven" });
    await ref.scrollIntoViewIfNeeded();
    const [panel, paper] = await scrollTops(pg);
    await ref.click();
    await pg.waitForSelector("aside .crumbs");
    await pg.waitForSelector("aside .decl.inspector");
    assert.equal(await pg.locator("aside .view").isHidden(), true, "the claim view is replaced");
    assert.match(await pg.locator("aside .crumbs").textContent(), /Back.*IsEven/s);
    assert.equal((await scrollTops(pg))[1], paper, "the paper keeps its position");
    await pg.locator("aside .crumbs .back").click();
    await pg.waitForSelector("aside .view h1");
    assert.equal(await pg.locator("aside .decl.inspector:visible").count(), 2, "both exact definitions remain in the claim comparison");
    const [panel2, paper2] = await scrollTops(pg);
    assert.equal(panel2, panel, "the panel's scroll position comes back");
    assert.equal(paper2, paper, "the paper keeps its position");
  });

  await check("the main view is the paper and the Lean, with the assumptions shown", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    const view = pg.locator("aside .view");
    await view.locator(".lean .ribbon").waitFor();
    assert.deepEqual(await view.locator("h2").allTextContents(), ["Paper", "Readable Lean", "Exact Lean"]);
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

  await check("a definition opens beside its paper definition; reviews and provenance are under Details", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside .lean .r", { hasText: "IsEven" }).first().click();
    const insp = pg.locator("aside .decl.inspector");
    await insp.waitFor();
    await pg.locator("aside h2", { hasText: "Paper · Definition 1.1" }).waitFor();
    const def = pg.locator("aside section.paper", { has: pg.locator("h2", { hasText: "Paper · Definition 1.1" }) });
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
    await mk.locator("button", { hasText: "Save link" }).click();
    await pg.waitForTimeout(500);
    assert.deepEqual(posted.at(-1), { action: "add", claim: "T:thm:even-add", tex: "a",
      decl: "Toy.PaperSpec.thm_even_add", var: "a", by: "human:Test-Referee" });
    // A published audit offers no such control.
    await toyClaim(pg, "T:thm:even-add");
    assert.equal(await pg.locator("aside .mklink").count(), 0);
  });

  await check("a statement keeps its order, with each object's own conditions beside it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view .stmt");
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
    assert.match(comp.text, /^Every clause, by the auditor's composition/);
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

  await check("a \"there is\" inside a conclusion shows its witness's type and scope", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:witnesses")}`);
    const st = pg.locator("aside .view .stmt").first();
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
    const st = pg.locator("aside .view .stmt").first();
    await st.locator(".concl").waitFor();
    assert.match((await st.locator(".ribbon").textContent()).replace(/\s+/g, " "), /assume instance Nonempty E/);
    const parts = (await st.locator(".concl .body > .parts > li").allTextContents()).map((t) => t.replace(/\s+/g, ""));
    assert.equal(parts.length, 2, parts.join(" | "));
    assert.equal(parts[0], "itisnotthecasethatthereisx:Natsuchthatx<0");
    assert.equal(parts[1], "atleastoneofthefollowingforeveryn:Nat,0≤nif1=1thenthereism:Natsuchthatm=1");
  });

  await check("clicking inside an expression selects it, and each click widens it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view .stmt");
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
    const st = pg.locator("aside .view .stmt").first();
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

  await check("a name's plain-English note appears only on request, beside the name", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view .stmt");
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
    const st = pg.locator("aside .view .stmt");
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

for (const width of [1440, 1000, 390, 320]) {
  await check("comparison keeps all three representations and long assumptions visible", width, async (pg) => {
    await pg.goto(origin + `/long-statement/#/r/${TOY.release}/read/T/T%3Athm%3Aeven-add?compare=1`);
    await pg.locator("aside .exact pre").waitFor();
    assert.deepEqual(await pg.locator(".comparison-grid > section > h2").allTextContents(), ["Paper", "Readable Lean", "Exact Lean"]);
    assert.equal(await pg.locator(".lean .ribbon > li").count(), 12);
    assert.match(await pg.locator(".exact pre").textContent(), /x11 : Nat/);
    assert.equal(await pg.locator(".paperpane").isHidden(), true);
    const sizes = await pg.evaluate(() => ({ width: innerWidth, height: innerHeight, scroll: document.documentElement.scrollWidth, bottom: document.documentElement.scrollHeight }));
    assert.ok(sizes.scroll <= sizes.width + 1, JSON.stringify(sizes));
    assert.ok(sizes.bottom <= sizes.height + 1, JSON.stringify(sizes));
    if (process.env.SHOTS) await pg.screenshot({ path: path.join(process.env.SHOTS, `comparison-${width}.png`) });
  });
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
  await pg.locator(".review .unit h2").waitFor();
  assert.match(await pg.locator(".review .unit h2").textContent(), /Theorem 2.1/);
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
  await pg.getByRole("button", { name: "Record verdict and show the author's review" }).click();
  await pg.locator(".review .author").waitFor();
  await pg.getByRole("button", { name: "Save report", exact: true }).click();
  await pg.getByRole("button", { name: "Export reports (1 new)", exact: true }).waitFor();
  const report = await pg.evaluate(() => JSON.parse(localStorage.getItem("prooflens-review:toy-paper")).reports[0]);
  assert.deepEqual(report.unit.claims, ["T:thm:even-add"]);
  assert.equal(report.reading.revealed_by[0].what, "Lean");
  assert.equal(report.verdict.value, "faithful");
  assert.equal(await pg.evaluate((id) => JSON.parse(localStorage.getItem("prooflens-review:toy-paper")).drafts[id].reading, reviewUnits[0].id), "Preserve this other unfinished reading.");
  const download = pg.waitForEvent("download");
  await pg.getByRole("button", { name: "Export reports (1 new)", exact: true }).click();
  const file = await download; const exported = JSON.parse(fs.readFileSync(await file.path()));
  assert.deepEqual(exported.reports[0], report);
});

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
    await view.locator(".paper .finding .context summary").click();
    assert.match(await view.locator(".paper .finding .context").textContent(), /k = 1/);
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

await check("the overview counts statements and proof steps apart", 1300, async (pg) => {
  await pg.goto(origin + `/toy/#/r/${TOY.release}/overview`);
  await pg.getByRole("button", { name: /^Proof steps \(2\)$/ }).click();
  assert.equal(await pg.locator(".coverage .claims li").count(), 2);
  assert.match(await pg.locator(".coverage .claims").textContent(), /Review of the printed step: false as printed/);
  await pg.getByRole("button", { name: /^Statements \(\d+\)$/ }).click();
  assert.equal(await pg.locator(".coverage .claims li").count(), TOY.claims.length - 2);
});

await check("a proof step with no Lean link is reviewed as printed and reported as a step", 390, async (pg) => {
  await pg.goto(origin + `/review-step/#/r/${TOY.release}/review?claim=T%3Aeq%3Abound-range`);
  await pg.getByRole("textbox", { name: "Your name" }).fill("Synthetic reviewer");
  await pg.getByRole("button", { name: "Start", exact: true }).click();
  await pg.locator(".review .unit h2").waitFor();
  assert.match(await pg.locator(".review .unit").textContent(), /Proof step.*A step of the proof of Theorem 2\.5/s);
  await pg.getByRole("textbox", { name: "Your reading", exact: true }).fill("For every k >= 0, with n fixed, the step says n <= k n^2.");
  await pg.getByRole("button", { name: "Lock my reading and show the Lean" }).click();
  await pg.getByText("Different formal route used instead").waitFor();
  await pg.getByRole("textbox", { name: "Comparison", exact: true }).fill("At k = 0 and n = 1 it reads 1 <= 0.");
  await pg.getByRole("button", { name: "It fails as printed", exact: true }).click();
  await pg.getByRole("radio", { name: "False as printed", exact: true }).check();
  await pg.locator("#verdict-detail").fill("Fails at k = 0, n = 1; holds for k >= 1.");
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
  assert.equal(report.issue_draft.title, "Equation (3) in the proof of Theorem 2.5: false as printed");
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
      await inv.getByRole("combobox").selectOption("changed");
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
        await inv.getByRole("combobox").selectOption("composition");
        await inv.getByRole("textbox", { name: "Argument" }).fill("Apply it to each summand.");
        await inv.getByRole("textbox", { name: "Note" }).fill("Two results combined.");
        await inv.getByRole("button", { name: "Save draft" }).click();
        const comp = inv.locator("[data-kind=finding]", { hasText: "Apply it to each summand." });
        await comp.waitFor();
        assert.match((await comp.textContent()).replace(/\s+/g, " "),
          /^Every clause, by the auditor's composition.*Lean has not checked this combination\..*Next step: State the combination as one Lean result\./);
      } finally { await pg2.close(); }
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
