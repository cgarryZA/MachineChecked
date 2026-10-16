// Screenshots of the demo reader for the landing page, light and dark, taken with headless
// Chromium from an exported site. Usage: node scripts/site_preview.mjs <export dir> <out dir>
// Needs the `playwright` package; set CHROMIUM to a browser binary if Playwright has none.
// The landing page (repository cgarryZA/machinechecked.org) uses them as WebP
// (site/preview-*.webp there), converted with Pillow:
//   python3 -c "from PIL import Image as I; [I.open(f'preview-{s}.png').convert('RGB')
//     .save(f'preview-{s}.webp', quality=82, method=6) for s in ('light', 'dark')]"
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const [root, out] = process.argv.slice(2);
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".json": "application/json", ".pdf": "application/pdf", ".svg": "image/svg+xml",
  ".woff2": "font/woff2", ".mjs": "text/javascript" };
const server = http.createServer((req, res) => {
  let p = path.join(root, decodeURIComponent(req.url.split("?")[0]));
  if (fs.existsSync(p) && fs.statSync(p).isDirectory()) p = path.join(p, "index.html");
  if (!fs.existsSync(p)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": types[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
}).listen(0);
const port = server.address().port;
const index = JSON.parse(fs.readFileSync(path.join(root, "data", "index.json")));
const claim = process.env.CLAIM || "T:prop:pred";
const paper = index.papers[0].id;
const url = `http://127.0.0.1:${port}/#/r/${encodeURIComponent(index.release)}/read/` +
  `${encodeURIComponent(paper)}/${encodeURIComponent(claim)}`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || undefined });
fs.mkdirSync(out, { recursive: true });
for (const scheme of ["light", "dark"]) {
  const page = await browser.newPage({ viewport: { width: 1360, height: 820 },
    deviceScaleFactor: 2, colorScheme: scheme });
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(out, `preview-${scheme}.png`) });
  await page.close();
}
await browser.close();
server.close();
