"""`prooflens`: build the evidence and the reader of a formalised paper."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import sys
from pathlib import Path

from . import config as cfgmod
from .schemas import validate


def _web_dist(arg: str | None) -> Path | None:
    if arg:
        return Path(arg).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "web" / "dist"
        if cand.exists():
            return cand
    return None


def cmd_build(a):
    from .pipeline import build
    cfg = cfgmod.load(a.config)
    res = build(cfg, release=a.release, skip_lean=a.skip_lean, skip_tex=a.skip_tex, lake=a.lake,
                web_dist=_web_dist(a.web), lean_build=not a.no_lean_build)
    idx = res["index"]
    for pid, s in idx["summary"].items():
        print(f"paper {pid}:")
        for k, v in sorted(s.items()):
            print(f"  {v:4d}  {k}")
    print("findings:", ", ".join(f"{v} {k}" for k, v in sorted(idx["findings"]["total"].items()))
          or "none")
    if a.fail_on_violation and idx["findings"]["total"].get("violation"):
        sys.exit(1)


def cmd_site(a):
    from .pipeline import rebuild_site
    cfg = cfgmod.load(a.config)
    res = rebuild_site(cfg, _web_dist(a.web), a.release)
    print(f"site of release {res['release']} written to {res['site']}")


def cmd_reassess(a):
    from .pipeline import reassess
    cfg = cfgmod.load(a.config)
    res = reassess(cfg, _web_dist(a.web), a.release)
    print(f"site of release {res['release']} written to {res['site']}")


def cmd_bundle(a):
    from .bundle import bundle
    cfg = cfgmod.load(a.config)
    site = Path(a.site).resolve() if a.site else cfg.out_dir / "site"
    res = bundle(site, Path(a.out).resolve(), a.title)
    print(f"wrote {res['out']}: {res['size'] / 1e6:.1f} MB, {res['files']} data files, "
          f"{res['pdfs']} PDFs; open it in a browser, no server needed")


def cmd_export(a):
    from .export import ExportError, export
    cfg = cfgmod.load(a.config)
    try:
        res = export(cfg, Path(a.out).resolve(), a.release, _web_dist(a.web))
    except ExportError as e:
        sys.exit(str(e))
    print(f"exported release {res['release']} to {res['out']}")


def cmd_serve(a):
    cfg = cfgmod.load(a.config)
    site = Path(a.dir).resolve() if a.dir else cfg.out_dir / "site"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    print(f"serving {site} on http://127.0.0.1:{a.port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def cmd_validate(a):
    validate(json.loads(Path(a.file).read_text()), a.schema)
    print(f"{a.file}: valid {a.schema}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="prooflens")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="probe, compile, assess, and write the private preview")
    b.add_argument("-c", "--config", default="prooflens.toml")
    b.add_argument("--release")
    b.add_argument("--skip-lean", action="store_true")
    b.add_argument("--skip-tex", action="store_true")
    b.add_argument("--lake", default="lake")
    b.add_argument("--no-lean-build", action="store_true",
                   help="do not run `lake build` first (the project is already built)")
    b.add_argument("--web", help="the built web app (default: web/dist of this checkout)")
    b.add_argument("--fail-on-violation", action="store_true")
    b.set_defaults(func=cmd_build)

    t = sub.add_parser("site", help="rewrite the preview from a stored release, without probing")
    t.add_argument("-c", "--config", default="prooflens.toml")
    t.add_argument("--release")
    t.add_argument("--web")
    t.set_defaults(func=cmd_site)

    r = sub.add_parser("reassess", help="assess the stored evidence again (current rules and "
                                        "reviews), without probing; a new evidence record")
    r.add_argument("-c", "--config", default="prooflens.toml")
    r.add_argument("--release")
    r.add_argument("--web")
    r.set_defaults(func=cmd_reassess)

    n = sub.add_parser("bundle", help="write the site as one HTML file that opens from disk")
    n.add_argument("-c", "--config", default="prooflens.toml")
    n.add_argument("--site", help="the site to bundle (default: the private preview)")
    n.add_argument("--out", required=True)
    n.add_argument("--title")
    n.set_defaults(func=cmd_bundle)

    e = sub.add_parser("export", help="assemble the public site from approved fields")
    e.add_argument("-c", "--config", default="prooflens.toml")
    e.add_argument("--release")
    e.add_argument("--out", required=True)
    e.add_argument("--web")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("serve", help="serve the preview site locally")
    s.add_argument("-c", "--config", default="prooflens.toml")
    s.add_argument("--dir")
    s.add_argument("--port", type=int, default=8017)
    s.set_defaults(func=cmd_serve)

    v = sub.add_parser("validate", help="validate a JSON file against a ProofLens schema")
    v.add_argument("file")
    v.add_argument("--schema", required=True,
                   choices=["inventory", "evidence", "manifest-index", "manifest-claim"])
    v.set_defaults(func=cmd_validate)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
