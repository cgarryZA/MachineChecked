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
import sys
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
def pdf(pages):
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{3 + i} 0 R" for i in range(pages)) +
            f"] /Count {pages} >>"]
    objs += ["<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"] * pages
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
site = Path(sys.argv[1]).parent / "long"
write_paper_site(site, long_paper, long_claims, [612, 792], "paper.pdf", Path(sys.argv[2]))
(site / "paper.pdf").write_bytes(pdf(30))
`;
const root = fs.mkdtempSync(path.join(os.tmpdir(), "mc-reader-"));
const made = spawnSync(process.env.PYTHON || "python3", ["-c", FIXTURE, path.join(root, "paper"), reader], { encoding: "utf8" });
if (made.status !== 0) throw new Error("the engine could not write the paper page:\n" + made.stderr);
fs.cpSync(reader, path.join(root, "toy"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "toy", "data"), path.join(root, "toy", "data"), { recursive: true });
const TOY = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "toy", "data", "index.json"), "utf8"));
// A synthetic statement with some shape (tests/fixtures/structure, regenerated by
// fixtures/make_structure.py): objects with their own conditions, a shared condition, an
// alternating prefix and a conjunction.
fs.cpSync(reader, path.join(root, "structure"), { recursive: true });
fs.cpSync(path.join(here, "fixtures", "structure", "data"), path.join(root, "structure", "data"), { recursive: true });
const SHAPE = JSON.parse(fs.readFileSync(path.join(here, "fixtures", "structure", "data", "index.json"), "utf8"));

const types = { ".pdf": "application/pdf", ".html": "text/html", ".json": "application/json", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" };
const server = http.createServer((req, res) => {
  let url = decodeURIComponent(req.url.split("?")[0]);
  if (url.endsWith("/")) url += "index.html";
  const p = path.join(root, url);
  if (!p.startsWith(root) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const origin = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
let failures = 0;

async function check(name, width, fn) {
  const pg = await browser.newPage({ viewport: { width, height: 900 } });
  const errors = [];
  pg.on("pageerror", (e) => errors.push(String(e)));
  try {
    await fn(pg);
    assert.deepEqual(errors, [], "no page errors");
    console.log(`ok   ${name} (${width}px)`);
  } catch (e) {
    failures++;
    console.log(`FAIL ${name} (${width}px): ${e.message}`);
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
const dots = async (pg) => pg.locator("nav.toc li .dot").evaluateAll((ds) => ds.map((d) => d.className));

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
    await pg.locator("nav.toc .n", { hasText: new RegExp(`^Theorem ${id.split("-")[1]}$`) }).click();
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

// The claim inspector on the toy audit: opening a definition replaces the panel's contents and
// leaves the paper where it was; Back brings the claim back as it was left.
const toyClaim = async (pg, id) => {
  await pg.goto(origin + `/toy/#/r/${TOY.release}/read/T/${encodeURIComponent(id)}`);
  await pg.waitForSelector("aside h1");
};
const scrollTops = (pg) => pg.evaluate(() => [document.querySelector("aside")?.scrollTop, document.querySelector(".paperpane")?.scrollTop]);

for (const width of [1300, 390]) {
  await check("opening a definition replaces the panel; Back restores the claim as it was", width, async (pg) => {
    await toyClaim(pg, "T:def:even");
    const ref = pg.locator("aside .lean button.ref", { hasText: "Toy.IsEven" });
    await ref.scrollIntoViewIfNeeded();
    const [panel, paper] = await scrollTops(pg);
    await ref.click();
    await pg.waitForSelector("aside .decl.inspector");
    assert.equal(await pg.locator("aside .view").isHidden(), true, "the claim view is replaced");
    assert.match(await pg.locator("aside .crumbs").textContent(), /Back.*IsEven/s);
    assert.equal((await scrollTops(pg))[1], paper, "the paper keeps its position");
    await pg.locator("aside .crumbs .back").click();
    await pg.waitForSelector("aside .view h1");
    assert.equal(await pg.locator("aside .decl.inspector").count(), 0);
    const [panel2, paper2] = await scrollTops(pg);
    assert.equal(panel2, panel, "the panel's scroll position comes back");
    assert.equal(paper2, paper, "the paper keeps its position");
  });

  await check("the main view is the paper and the Lean, with the assumptions shown", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    const view = pg.locator("aside .view");
    await view.locator(".lean .ribbon").waitFor();
    assert.deepEqual(await view.locator("h2").allTextContents(), ["Paper", "Lean"]);
    assert.equal(await view.locator(".lean .ribbon li").count(), 4, "a short statement is shown in full");
    assert.match(await view.locator(".chip").textContent(), /formal: accepted/, "the engine's words");
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
    await pg.locator("aside .lean button.r", { hasText: "IsEven" }).first().click();
    const insp = pg.locator("aside .decl.inspector");
    await insp.waitFor();
    await pg.locator("aside h2", { hasText: "Paper · Definition 1.1" }).waitFor();
    const extra = insp.locator("details.extra");
    assert.equal(await extra.getAttribute("open"), null, "Details is folded");
    assert.ok(!(await insp.locator(":scope > :not(details)").allTextContents()).join(" ").includes("a.referee"));
    await extra.locator("summary").click();
    assert.match(await extra.textContent(), /a\.referee/);
  });

  await check("the menu holds the occasional actions", width, async (pg) => {
    await toyClaim(pg, "T:thm:even-add");
    await pg.locator("aside button[aria-label='More']").click();
    const items = await pg.locator("aside .menu [role='menuitem']").allTextContents();
    assert.ok(items.includes("Open as a page") && items.some((i) => /Copy (link|reference)/.test(i)));
    const reports = pg.locator("aside .menu a", { hasText: "View existing reports" });
    assert.match(await reports.getAttribute("href"), /^https:\/\/github\.com\/cgarryZA\/MachineChecked\/issues\?q=.*T%3Athm%3Aeven-add/);
  });
}

for (const width of [1300, 390]) {
  await check("a statement keeps its order, with each object's own conditions beside it", width, async (pg) => {
    await pg.goto(origin + `/structure/#/r/${SHAPE.release}/read/P/${encodeURIComponent("P:thm:layout")}`);
    const st = pg.locator("aside .view .stmt");
    await st.locator(".ribbon").waitFor();
    const rows = (await st.locator(".ribbon > li").allTextContents()).map((t) => t.replace(/\s+/g, " ").trim());
    assert.equal(rows.length, 7, rows.join(" | "));
    assert.match(rows[0], /^for all E ?: ?Type assume instance Inhabited E$/i);
    assert.match(rows[1], /^for all j ?: ?Nat assume \(hj\) 1 ≤ j$/i);
    assert.match(rows[2], /^for all k ?: ?Nat$/i);
    assert.match(rows[3], /^assume \(hjk\) j ≤ k$/i, "a condition on two objects stays a row of its own");
    assert.match(rows[5], /^there is C ?: ?Nat$/i);
    assert.match(await st.locator(".concl .op").textContent(), /all of the following/);
    assert.equal(await st.locator(".concl .parts > li").count(), 2);
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

await browser.close();
server.close();
fs.rmSync(root, { recursive: true, force: true });
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all reader tests passed");
