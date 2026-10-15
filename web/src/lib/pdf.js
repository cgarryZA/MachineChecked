// pdf.js, loaded once, with its worker bundled beside the site.
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

const docs = new Map();

export function openPdf(url) {
  if (!docs.has(url)) docs.set(url, pdfjs.getDocument({ url, isEvalSupported: false }).promise);
  return docs.get(url);
}

// Render a page, or the band of it between y0 and y1 (PDF points from the top), into `canvas`
// at `cssWidth` pixels wide.
export async function renderPage(doc, pageNo, canvas, cssWidth, band = null) {
  const page = await doc.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  const scale = cssWidth / base.width;
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const vp = page.getViewport({ scale: scale * dpr });
  const top = band ? Math.max(0, band[0]) * scale * dpr : 0;
  const bottom = band ? Math.min(base.height, band[1]) * scale * dpr : vp.height;
  canvas.width = Math.floor(vp.width);
  canvas.height = Math.max(1, Math.floor(bottom - top));
  canvas.style.width = cssWidth + "px";
  canvas.style.height = canvas.height / dpr + "px";
  const ctx = canvas.getContext("2d");
  ctx.setTransform(1, 0, 0, 1, 0, -top);
  await page.render({ canvasContext: ctx, viewport: vp, canvas }).promise;
  return { width: base.width, height: base.height, scale };
}
