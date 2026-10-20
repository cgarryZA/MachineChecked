"""Serve a copy of the reader as `machinechecked view` does, answering `GET /api/uses` with the
answers the engine gave for the synthetic project (fixtures/uses/api-uses.json, written by
make_uses.py), for the browser test of a declaration's uses. Prints the port, then serves.

    python3 uses_server.py SITE ANSWERS
"""

import json
import sys
from pathlib import Path

from prooflens.server import make_server

site, answers = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))


def get(q):
    name = (q.get("name") or [""])[0]
    if name not in answers:
        raise ValueError(f"{name}: not in this fixture")
    return answers[name]


httpd = make_server(site, 0, on_link=lambda req: {}, api=({"/api/uses": get}, {}))
print(httpd.server_address[1], flush=True)
httpd.serve_forever()
