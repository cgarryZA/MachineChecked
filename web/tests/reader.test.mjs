// Browser tests of the built reader (engine/python/prooflens/web), in headless Chromium, at a
// laptop and a phone width. Run after `npm run build`: `node tests/reader.test.mjs`.
// Set CHROMIUM to a browser binary when Playwright's own is not installed, and SHOTS to a
// directory to keep screenshots.
//
// A paper page with two formalisations: the chosen project must drive every claim view, and
// the two projects' links must never show together.

import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const reader = path.resolve(here, "../../engine/python/prooflens/web");
const NOT_CHECKED = "linked: Lean not checked here (no audit published)";
const A = "alpha/project-a", B = "beta/project-b";
const link = (name, repository) => ({ name, repository, commit: "a".repeat(40), source: "formalization.yaml", status: NOT_CHECKED });
const anchor = (page, y0) => ({ kind: "approximate", page, y0, y1: y0 + 40, page_end: page });

const paper = {
  id: "arxiv:2601.00001", title: "A paper with two formalisations", authors: ["A. Author"],
  listing: "arxiv", links: {},
  formalisations: [
    { repository: A, commit: "a".repeat(40), stated_by: { source: "formalization.yaml" } },
    { repository: B, commit: "b".repeat(40), stated_by: { source: "formalization.yaml" } },
  ],
  claims: [
    { id: "P:theorem-1", number: "Theorem 1", kind: "theorem", anchor: anchor(1, 100), links: [link("A.one", A)] },
    { id: "P:theorem-2", number: "Theorem 2", kind: "theorem", anchor: anchor(1, 300), links: [link("B.two", B)] },
    { id: "P:theorem-3", number: "Theorem 3", kind: "theorem", anchor: anchor(2, 100), links: [link("A.three", A), link("B.three", B)] },
    { id: "P:lemma-4", number: "Lemma 4", kind: "lemma", anchor: anchor(2, 300), links: [] },
  ],
};

function page() {
  const index = fs.readFileSync(path.join(reader, "index.html"), "utf8");
  const tags = index.match(/<(?:script|link)\b[^>]*(?:src|href)="\.\/assets\/[^"]+"[^>]*>(?:<\/script>)?/g).join("\n");
  return `<!doctype html><html><head><meta charset="utf-8">
<script>window.__MACHINECHECKED_PAPER__ = ${JSON.stringify(paper).replace(/</g, "\\u003c")};</script>
${tags.replaceAll('"./assets/', '"/assets/')}</head><body><div id="app"></div></body></html>`;
}

const types = { ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2" };
const server = http.createServer((req, res) => {
  const url = req.url.split("?")[0];
  if (url === "/" || url === "/paper/") { res.writeHead(200, { "content-type": "text/html" }); return res.end(page()); }
  const p = path.join(reader, decodeURIComponent(url));
  if (!p.startsWith(reader) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
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
if (failures) {
  console.log(`${failures} failure(s)`);
  process.exit(1);
}
console.log("all reader tests passed");
