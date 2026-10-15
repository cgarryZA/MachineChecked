"""One self-contained HTML file of a site, readable straight from disk.

Browsers refuse `fetch` from pages opened as files, so the bundle carries everything in the page:
the app's script and styles (fonts as data URIs, WOFF2 only), the pdf.js worker's code, every
data file of the site in `window.__PROOFLENS__` (keyed by the path the app would fetch), and the
PDFs, base64, in `window.__PROOFLENS_PDF__`. The data scripts come first, so they are defined
before the app (a deferred module) runs.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path


def _script_safe(text: str) -> str:
    """Text that cannot close the <script> element it sits in."""
    return text.replace("</", "<\\/")


def _inline_css(css: str, assets: Path) -> str:
    def font(m):
        name = m.group(1)
        f = assets / name
        if not f.exists():
            return m.group(0)
        b64 = base64.b64encode(f.read_bytes()).decode()
        return f'url(data:font/woff2;base64,{b64}) format("woff2")'
    # Keep only the WOFF2 source of each font face, inlined.
    css = re.sub(r',\s*url\([^)]*\.(?:woff|ttf)\)\s*format\("(?:woff|truetype)"\)', "", css)
    return re.sub(r'url\((?:\./)?(?:assets/)?([^)]+\.woff2)\)\s*format\("woff2"\)', font, css)


def bundle(site: Path, out: Path, title: str | None = None) -> dict:
    html = (site / "index.html").read_text(encoding="utf-8")
    assets = site / "assets"
    js_src = re.search(r'<script type="module"[^>]*src="\./(assets/[^"]+\.js)"[^>]*></script>', html)
    css_href = re.search(r'<link rel="stylesheet"[^>]*href="\./(assets/[^"]+\.css)"[^>]*>', html)
    if not js_src or not css_href:
        raise RuntimeError("the site's index.html does not reference its script and styles")
    js = (site / js_src.group(1)).read_text(encoding="utf-8")
    css = _inline_css((site / css_href.group(1)).read_text(encoding="utf-8"), assets)
    worker = next(assets.glob("pdf.worker*.mjs"), None)

    data = {}
    for f in sorted((site / "data").rglob("*.json")):
        data[str(f.relative_to(site))] = json.loads(f.read_text(encoding="utf-8"))
    pdfs = {str(f.relative_to(site)): base64.b64encode(f.read_bytes()).decode()
            for f in sorted((site / "data").rglob("*.pdf"))}

    head = ["<script>window.__PROOFLENS__ = " +
            _script_safe(json.dumps(data, ensure_ascii=False, separators=(",", ":"))) +
            ";</script>",
            "<script>window.__PROOFLENS_PDF__ = " + json.dumps(pdfs) + ";</script>"]
    if worker:
        head.append("<script>window.__PROOFLENS_WORKER__ = " +
                    _script_safe(json.dumps(worker.read_text(encoding="utf-8"))) + ";</script>")
    head.append("<style>" + css + "</style>")
    html = html.replace(css_href.group(0), "")
    html = html.replace(js_src.group(0), "")
    html = html.replace("</head>", "\n".join(head) + "\n</head>", 1)
    html = html.replace("</body>", '<script type="module">' + _script_safe(js) +
                        "</script>\n</body>", 1)
    if title:
        html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return {"out": out, "size": out.stat().st_size, "files": len(data), "pdfs": len(pdfs)}
