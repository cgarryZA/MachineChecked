"""Serve a copy of the reader as `machinechecked view` does, with the workspace routes, for the
browser test of a saved investigation. Prints the port, then serves until killed.

    python3 workspace_server.py SITE WORK
"""

import sys
from pathlib import Path

from prooflens import workspace as wsp
from prooflens.server import make_server

site, work = Path(sys.argv[1]), Path(sys.argv[2])
httpd = make_server(site, 0, on_symbol=lambda req: None, api=wsp.api(work, site / "data"))
print(httpd.server_address[1], flush=True)
httpd.serve_forever()
