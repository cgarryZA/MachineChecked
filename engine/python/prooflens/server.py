"""The local server of `prooflens view`: the site, and saving links into the repository.

It listens on 127.0.0.1 only. `GET /api/status` tells the reader it may edit; `POST /api/link`
with `{"key", "lean": [names] | null, "reject": [names]}` records a link (or removes it, or
rejects suggestions) in `prooflens.links.json` and rebuilds the view. In a full assessment,
`POST /api/symbol` with `{"action": "add" | "remove", "claim", "tex", "decl", "var" | "type_of",
"by"}` records or removes a symbol link (docs/SYMBOL_LINKS.md) and rewrites the site. The
workspace routes (`workspace.api`) read and update the auditor's saved investigation, and `GET
/api/uses?name=` answers where a declaration is used (`uses.route`). A refused
edit answers 400 with its message (and `candidates` when a name did not resolve); an edit of a
record changed meanwhile answers 409 with `conflicts`, each holding both versions.
"""

from __future__ import annotations

import functools
import http.server
import json
import threading
import urllib.parse
from pathlib import Path


def serve(site: Path, port: int, on_link=None, open_browser: bool = True, on_symbol=None,
          api: tuple[dict, dict] | None = None):
    httpd = make_server(site, port, on_link, on_symbol, api)
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


def make_server(site: Path, port: int, on_link=None, on_symbol=None,
                api: tuple[dict, dict] | None = None) -> http.server.ThreadingHTTPServer:
    """The server, bound to 127.0.0.1:`port` (0: any free port), not yet serving."""
    lock = threading.Lock()
    editable = on_link is not None or on_symbol is not None
    gets, posts = api or ({}, {})
    routes = {"/api/link": on_link, "/api/symbol": on_symbol, **posts}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code: int, obj):
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def _error(self, e: Exception):
            if getattr(e, "conflicts", None) is not None:
                return self._json(409, {"error": str(e), "conflicts": e.conflicts})
            extra = e.to_json() if hasattr(e, "to_json") else {}
            return self._json(400, {**extra, "error": str(e)})

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/api/status":
                return self._json(200, {"editable": editable,
                                        "workspace": "/api/workspace" in gets,
                                        "uses": "/api/uses" in gets})
            if path in gets:
                try:
                    with lock:
                        return self._json(200, gets[path](urllib.parse.parse_qs(query)))
                except Exception as e:
                    return self._error(e)
            # The data index says the page may edit (only this local server says so; a static
            # copy of the site never asks a server anything).
            if self.path.split("?")[0] == "/data/index.json" and editable:
                try:
                    data = json.loads((site / "data" / "index.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    return super().do_GET()
                return self._json(200, {**data, "editable": True})
            return super().do_GET()

        def do_POST(self):
            handle = routes.get(self.path)
            if handle is None:
                return self._json(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length", "0"))
                req = json.loads(self.rfile.read(n) or b"{}")
                with lock:
                    out = handle(req)
                return self._json(200, {"ok": True, **(out if isinstance(out, dict) else {})})
            except Exception as e:  # the reader shows the message
                return self._error(e)

    handler = functools.partial(Handler, directory=str(site))
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
