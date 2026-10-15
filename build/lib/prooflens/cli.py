"""`prooflens`: read a paper beside its Lean formalisation.

Everyday commands, run from anywhere inside a Lean project:

    prooflens view [paper]    open the reader (the paper is found if not given)
    prooflens build [paper]   write the reader as one HTML file to share
    prooflens check [paper]   report what the Lean side establishes, for CI

A project with a `prooflens.toml` (an acceptance layer: locked statements, reviews) gets the
full assessment; any other project gets the zero-configuration view, whose only file in the
repository is `prooflens.links.json`. The other commands are for that full assessment.
"""

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
    """The built web app: given with --web, else the one shipped in the package."""
    if arg:
        return Path(arg).resolve()
    shipped = Path(__file__).resolve().parent / "web"
    return shipped if (shipped / "index.html").exists() else None


# -- mode selection ---------------------------------------------------------------------------

def _assurance_config(a) -> Path | None:
    """The `prooflens.toml` that selects the full assessment: given with -c, or in the current
    directory."""
    if getattr(a, "config", None):
        return Path(a.config)
    p = Path("prooflens.toml")
    return p if p.exists() else None


def _simple_target(a):
    from .simple import find_lake_root, find_papers
    root = find_lake_root(Path.cwd().resolve())
    if root is None:
        sys.exit("no Lean project here: run prooflens inside a directory with a lakefile")
    if a.paper:
        paper = Path(a.paper).resolve()
        if not paper.exists():
            sys.exit(f"{a.paper}: no such file")
    else:
        found = find_papers(root)
        if not found:
            sys.exit("no paper found (no .tex with \\documentclass, no .pdf): pass its path")
        if len(found) > 1:
            print("Several papers found:")
            for i, f in enumerate(found, 1):
                print(f"  {i}. {f.relative_to(root)}")
            if not sys.stdin.isatty():
                sys.exit("pass the one to use: prooflens view <paper>")
            k = input("Which one? ")
            try:
                paper = found[int(k) - 1]
            except (ValueError, IndexError):
                sys.exit("no paper chosen")
        else:
            paper = found[0]
    try:
        paper.relative_to(root)
    except ValueError:
        sys.exit(f"{paper} is not inside the Lean project {root}")
    return root, paper


def _simple_site(root: Path, paper: Path, web: str | None):
    from .simple import build_view, write_view_site
    out = root / ".prooflens"
    view = build_view(root, paper, out, log=lambda m: print("  " + m))
    site = out / "site"
    index = write_view_site(view, site, _web_dist(web))
    return site, index, view


def _print_simple(index):
    for n in index.get("notes", []):
        print(f"note: {n}")
    for s, k in sorted(index["summary"]["P"].items()):
        print(f"  {k:4d}  {s}")


# -- everyday commands ------------------------------------------------------------------------

def cmd_view(a):
    if _assurance_config(a):
        from .pipeline import build
        from .server import serve
        cfg = cfgmod.load(_assurance_config(a))
        try:
            res = build(cfg, web_dist=_web_dist(a.web), reuse_lean=True)
        except RuntimeError:
            res = build(cfg, web_dist=_web_dist(a.web))
        serve(res["site"], a.port, None, not a.no_browser)
        return
    from .server import serve
    from .simple import save_link
    root, paper = _simple_target(a)
    print(f"ProofLens: {paper.relative_to(root)} in {root.name}")
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(index)
    key = view["body"]["paper"]

    def on_link(req):
        save_link(root, key, req["key"], req.get("lean"), req.get("reject"))
        _simple_site(root, paper, a.web)

    serve(site, a.port, on_link, not a.no_browser)


def cmd_build_simple(a):
    from .bundle import bundle
    root, paper = _simple_target(a)
    site, index, _ = _simple_site(root, paper, a.web)
    _print_simple(index)
    out = Path(a.out or (root / "ProofLens.html")).resolve()
    res = bundle(site, out, f"ProofLens — {index['papers'][0]['title']}")
    print(f"wrote {res['out']} ({res['size'] / 1e6:.1f} MB): open it in a browser")


def cmd_check(a):
    if _assurance_config(a):
        a.config = str(_assurance_config(a))
        a.release = None; a.skip_lean = a.skip_tex = False; a.lake = "lake"
        a.no_lean_build = False; a.reuse_lean = False; a.fail_on_violation = True
        return cmd_build(a)
    root, paper = _simple_target(a)
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(index)
    bad = [(c["number"], l["name"], l["status"]) for c in view["body"]["claims"]
           for l in c["links"] if l["class"] != "proved"]
    for b in bad:
        print(f"FAIL {b[0]} -> {b[1]}: {b[2]}")
    if bad:
        sys.exit(1)
    print("every linked declaration is checked by Lean (correspondence with the paper is not "
          "reviewed by this check)")


def cmd_build(a):
    if not getattr(a, "config", None) and not Path("prooflens.toml").exists():
        return cmd_build_simple(a)
    from .pipeline import build
    cfg = cfgmod.load(a.config or "prooflens.toml")
    res = build(cfg, release=a.release, skip_lean=a.skip_lean, skip_tex=a.skip_tex, lake=a.lake,
                web_dist=_web_dist(a.web), lean_build=not a.no_lean_build,
                reuse_lean=a.reuse_lean)
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
    p = argparse.ArgumentParser(prog="prooflens", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n\n".join(__doc__.split("\n\n")[1:]))
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{view,build,check}")

    w = sub.add_parser("view", help="open the reader")
    w.add_argument("paper", nargs="?")
    w.add_argument("-c", "--config", help=argparse.SUPPRESS)
    w.add_argument("--port", type=int, default=8017)
    w.add_argument("--no-browser", action="store_true")
    w.add_argument("--web", help=argparse.SUPPRESS)
    w.set_defaults(func=cmd_view)

    b = sub.add_parser("build", help="write the reader as one HTML file to share")
    b.add_argument("paper", nargs="?")
    b.add_argument("--out", help="the HTML file (default: ProofLens.html at the project root)")
    b.add_argument("-c", "--config", help=argparse.SUPPRESS)
    b.add_argument("--release", help=argparse.SUPPRESS)
    b.add_argument("--skip-lean", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--skip-tex", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--lake", default="lake", help=argparse.SUPPRESS)
    b.add_argument("--no-lean-build", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--reuse-lean", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--web", help=argparse.SUPPRESS)
    b.add_argument("--fail-on-violation", action="store_true", help=argparse.SUPPRESS)
    b.set_defaults(func=cmd_build)

    k = sub.add_parser("check", help="report what the Lean side establishes (exit 1 if a "
                                     "linked declaration is missing or unproved)")
    k.add_argument("paper", nargs="?")
    k.add_argument("-c", "--config", help=argparse.SUPPRESS)
    k.add_argument("--web", help=argparse.SUPPRESS)
    k.set_defaults(func=cmd_check)

    # The full assessment's own operations; not listed.
    t = sub.add_parser("site")
    t.add_argument("-c", "--config", default="prooflens.toml")
    t.add_argument("--release")
    t.add_argument("--web")
    t.set_defaults(func=cmd_site)

    r = sub.add_parser("reassess")
    r.add_argument("-c", "--config", default="prooflens.toml")
    r.add_argument("--release")
    r.add_argument("--web")
    r.set_defaults(func=cmd_reassess)

    n = sub.add_parser("bundle")
    n.add_argument("-c", "--config", default="prooflens.toml")
    n.add_argument("--site")
    n.add_argument("--out", required=True)
    n.add_argument("--title")
    n.set_defaults(func=cmd_bundle)

    e = sub.add_parser("export")
    e.add_argument("-c", "--config", default="prooflens.toml")
    e.add_argument("--release")
    e.add_argument("--out", required=True)
    e.add_argument("--web")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("serve")
    s.add_argument("-c", "--config", default="prooflens.toml")
    s.add_argument("--dir")
    s.add_argument("--port", type=int, default=8017)
    s.set_defaults(func=cmd_serve)

    v = sub.add_parser("validate")
    v.add_argument("file")
    v.add_argument("--schema", required=True,
                   choices=["inventory", "evidence", "manifest-index", "manifest-claim"])
    v.set_defaults(func=cmd_validate)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
