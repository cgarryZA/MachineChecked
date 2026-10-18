// pdf.js, loaded once, with its worker bundled beside the site.
import * as pdfjs from "pdfjs-dist";
import "pdfjs-dist/web/pdf_viewer.css";
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
    // A failed load is forgotten, so that trying again loads it afresh.
    const p = pdfjs.getDocument({ ...src, isEvalSupported: false }).promise;
    docs.set(url, p);
    p.catch(() => docs.get(url) === p && docs.delete(url));
  }
  return docs.get(url);
}

// Render a page, or the band of it between y0 and y1 (PDF points from the top), into `canvas`
// at `cssWidth` pixels wide.
export async function renderPage(doc, pageNo, canvas, cssWidth, band = null, signal = null) {
  const page = await doc.getPage(pageNo);
  if (signal?.aborted) return;
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
  const task = page.render({ canvasContext: ctx, viewport: vp, canvas });
  const cancel = () => task.cancel();
  signal?.addEventListener("abort", cancel, { once: true });
  try { await task.promise; } finally { signal?.removeEventListener("abort", cancel); }
  return { width: base.width, height: base.height, scale };
}

// A horizontal band of a page (`band`, in PDF points from the top), trimmed of its blank margins
// so the text fills `cssWidth`: the claim reads at a useful size in a narrow panel. The scale is
// capped at `maxScale` (CSS pixels per point), so a short line is not blown up.
export async function renderBand(doc, pageNo, canvas, cssWidth, band, maxScale = 1.6, signal = null) {
  const page = await doc.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  const dpr = Math.min(window.devicePixelRatio || 1, 3);
  const s = Math.max(cssWidth / base.width, maxScale) * dpr;
  const vp = page.getViewport({ scale: s });
  const top = Math.max(0, band[0]) * s;
  const bottom = Math.min(base.height, band[1]) * s;
  const off = document.createElement("canvas");
  off.width = Math.floor(vp.width);
  off.height = Math.max(1, Math.floor(bottom - top));
  const octx = off.getContext("2d", { willReadFrequently: true });
  octx.fillStyle = "white";
  octx.fillRect(0, 0, off.width, off.height);
  octx.setTransform(1, 0, 0, 1, 0, -top);
  if (signal?.aborted) return;
  const task = page.render({ canvasContext: octx, viewport: vp, canvas: off });
  const cancel = () => task.cancel();
  signal?.addEventListener("abort", cancel, { once: true });
  try { await task.promise; } finally { signal?.removeEventListener("abort", cancel); }
  if (signal?.aborted) return;
  octx.setTransform(1, 0, 0, 1, 0, 0);
  // The columns holding ink.
  const { data } = octx.getImageData(0, 0, off.width, off.height);
  const w = off.width, h = off.height;
  let x0 = w, x1 = -1;
  for (let y = 0; y < h; y += 2) {
    const row = y * w * 4;
    for (let x = 0; x < x0; x++) {
      const i = row + x * 4;
      if (data[i] < 200 || data[i + 1] < 200 || data[i + 2] < 200) { x0 = x; break; }
    }
    for (let x = w - 1; x > x1; x--) {
      const i = row + x * 4;
      if (data[i] < 200 || data[i + 1] < 200 || data[i + 2] < 200) { x1 = x; break; }
    }
  }
  if (x1 < x0) { x0 = 0; x1 = w - 1; }
  const pad = Math.round(6 * s);
  x0 = Math.max(0, x0 - pad);
  x1 = Math.min(w - 1, x1 + pad);
  const wpt = (x1 - x0 + 1) / s;
  const scale = Math.min(cssWidth / wpt, maxScale);
  const cssW = wpt * scale, cssH = (h / s) * scale;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.max(1, Math.round(cssH * dpr));
  canvas.style.width = cssW + "px";
  canvas.style.height = cssH + "px";
  canvas.getContext("2d").drawImage(off, x0, 0, x1 - x0 + 1, h, 0, 0, canvas.width, canvas.height);
  return { scale };
}


const originals = new Map();
export function pdfUrl(url) {
  const encoded = window.__PROOFLENS_PDF__?.[url];
  if (!encoded) return resolve(url);
  if (!originals.has(url)) originals.set(url, URL.createObjectURL(new Blob([base64Bytes(encoded)], { type: "application/pdf" })));
  return originals.get(url);
}

// Render nearby pages with PDF.js's selectable text and the PDF's link annotations.
export function documentPage(node, initial) {
  let args = initial, visible = false, rendered = null, controller, textLayer;
  const canvas = node.querySelector("canvas"), text = node.querySelector(".textLayer"), links = node.querySelector(".pdf-links");
  function cancel() { controller?.abort(); textLayer?.cancel(); }
  async function draw() {
    const key = `${args.no}:${args.width}`;
    if (!visible || !args.doc || rendered === key) return;
    cancel(); controller = new AbortController();
    const signal = controller.signal, current = args;
    rendered = key;
    try {
      const page = await current.doc.getPage(current.no);
      if (signal.aborted) return;
      await renderPage(current.doc, current.no, canvas, current.width, null, signal);
      if (signal.aborted) return;
      const viewport = page.getViewport({ scale: current.width / page.getViewport({ scale: 1 }).width });
      node.style.setProperty("--scale-factor", viewport.scale);
      text.replaceChildren(); links.replaceChildren();
      const content = await page.getTextContent();
      if (signal.aborted) return;
      textLayer = new pdfjs.TextLayer({ textContentSource: content, container: text, viewport });
      await textLayer.render();
      if (signal.aborted) return;
      for (const a of await page.getAnnotations({ intent: "display" })) {
        if (signal.aborted) return;
        if (a.subtype !== "Link" || (!a.url && !a.dest)) continue;
        let destination = null;
        if (a.dest) {
          const dest = typeof a.dest === "string" ? await current.doc.getDestination(a.dest) : a.dest;
          if (dest?.length) destination = typeof dest[0] === "number" ? dest[0] + 1 : (await current.doc.getPageIndex(dest[0])) + 1;
        }
        if (signal.aborted) return;
        if (a.url && !/^(https?:|mailto:)/i.test(a.url)) continue;
        const link = document.createElement("a");
        link.href = a.url || `${current.original}#page=${destination}`;
        link.setAttribute("aria-label", a.url ? `Open ${a.url}` : `Go to page ${destination}`);
        if (a.url) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
        else link.addEventListener("click", (e) => { if (!e.ctrlKey && !e.metaKey && !e.shiftKey && destination) { e.preventDefault(); current.onpage(destination); } });
        const rect = viewport.convertToViewportRectangle(a.rect);
        Object.assign(link.style, { left: Math.min(rect[0], rect[2]) + "px", top: Math.min(rect[1], rect[3]) + "px", width: Math.abs(rect[2] - rect[0]) + "px", height: Math.abs(rect[3] - rect[1]) + "px" });
        links.append(link);
      }
      if (!signal.aborted) current.onrender?.();
    } catch (e) {
      if (!signal.aborted && e.name !== "RenderingCancelledException" && e.name !== "AbortException") {
        rendered = null; current.onerror?.(String(e.message || e));
      }
    }
  }
  const observer = new IntersectionObserver((entries) => { visible = entries.some((e) => e.isIntersecting); if (visible) draw(); }, { rootMargin: "600px" });
  observer.observe(node);
  return {
    update(next) { const changed = args.doc !== next.doc || args.width !== next.width || args.no !== next.no; args = next; if (changed) { cancel(); rendered = null; draw(); } },
    destroy() { cancel(); observer.disconnect(); }
  };
}
