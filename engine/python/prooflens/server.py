"""The local server of `prooflens view`: the site, and saving links into the repository.

It listens on 127.0.0.1 only. `GET /api/status` tells the reader it may edit; `POST /api/link`
with `{"key", "lean": [names] | null, "reject": [names]}` records a link (or removes it, or
rejects suggestions) in `prooflens.links.json` and rebuilds the view.
"""

from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path


def serve(site: Path, port: int, on_link=None, open_browser: bool = True):
    lock = threading.Lock()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code: int, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path == "/api/status":
                return self._json(200, {"editable": on_link is not None})
            return super().do_GET()

        def do_POST(self):
            if self.path != "/api/link" or on_link is None:
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(n) or b"{}")
                with lock:
                    on_link(req)
                return self._json(200, {"ok": True})
            except Exception as e:  # the reader shows the message
                return self._json(400, {"error": str(e)})

    handler = functools.partial(Handler, directory=str(site))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"ProofLens: {url}  (Ctrl-C to stop)")
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return url
