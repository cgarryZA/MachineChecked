// pdf.js, loaded once, with its worker bundled beside the site.
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { resolve } from "./data.js";

// In a one-file bundle the worker's code and the PDFs are carried in the page.
if (window.__PROOFLENS_WORKER__) {
  const blob = new Blob([window.__PROOFLENS_WORKER__], { type: "text/javascript" });
  pdfjs.GlobalWorkerOptions.workerSrc = URL.createObjectURL(blob);
} else {
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
}

const docs = new Map();

function base64Bytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function openPdf(url) {
  if (!docs.has(url)) {
    const b64 = window.__PROOFLENS_PDF__?.[url];
    let src;
    try {
      src = b64 ? { data: base64Bytes(b64) } : { url: resolve(url), withCredentials: false };
    } catch (e) {
      return Promise.reject(e);
    }
    docs.set(url, pdfjs.getDocument({ ...src, isEvalSupported: false }).promise);
  }
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
