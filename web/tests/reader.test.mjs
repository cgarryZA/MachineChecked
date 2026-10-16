// Browser tests of the built reader (engine/python/prooflens/web), in headless Chromium, at a
// laptop and a phone width. Run after `npm run build`: `node tests/reader.test.mjs`.
// Set CHROMIUM to a browser binary when Playwright's own is not installed, and SHOTS to a
// directory to keep screenshots.
//
// A paper page with two formalisations, written by the engine: the chosen project must drive
// every claim view, and the two projects' links must never show together. Needs the engine
// importable (`pip install -e .`); set PYTHON to choose the interpreter.

import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import os from "node:os";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

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
    (paper["formalisations"][0], fy([("theorem", "1", ["A.one"]), ("theorem", "3", ["A.three"])])),
    (paper["formalisations"][1], fy([("theorem", "2", ["B.two"]), ("theorem", "3", ["B.three"])]))])
write_paper_site(Path(sys.argv[1]), paper, claims, [612, 792], None, Path(sys.argv[2]))
`;
const root = fs.mkdtempSync(path.join(os.tmpdir(), "mc-reader-"));
const made = spawnSync(process.env.PYTHON || "python3", ["-c", FIXTURE, path.join(root, "paper"), reader], { encoding: "utf8" });
if (made.status !== 0) throw new Error("the engine could not write the paper page:\n" + made.stderr);

const types = { ".html": "text/html", ".json": "application/json", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" };
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
const panelNames = async (pg) => (await pg.locator("aside .card code").allTextContents()).map((s) => s.trim());
const open = async (pg, claim) => {
  await pg.evaluate((id) => { location.hash = `#/r/paper/read/P/${encodeURIComponent(id)}`; }, claim);
  await pg.waitForSelector("aside h1");
};
const dots = async (pg) => pg.locator("nav.toc li .dot").evaluateAll((ds) => ds.map((d) => d.className));

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

await browser.close();
server.close();
fs.rmSync(root, { recursive: true, force: true });
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all reader tests passed");
