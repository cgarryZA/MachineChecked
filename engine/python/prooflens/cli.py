"""`machinechecked`: read a paper beside its Lean formalisation.

Everyday commands, run from anywhere inside a Lean project:

    machinechecked view [paper]    open the reader (the paper is found if not given)
    machinechecked build [paper]   write the reader as one HTML file to share
    machinechecked check [paper]   report what the Lean side establishes, for CI

A project with a `machinechecked.toml` (an acceptance layer: locked statements, reviews) gets
the full assessment; any other project gets the zero-configuration view, whose only file in the
repository is `machinechecked.links.json` (its working files, a downloaded paper among them, are
in `.machinechecked/`, which Git ignores). The full assessment has further commands: reassess,
site, bundle, export, serve, review promote and validate; `cache` saves and restores the Lean
build (each with --help).
`prooflens` is another name for the same command.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
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


MISSING = {
    "lake": "install elan (https://github.com/leanprover/elan) and put ~/.elan/bin on PATH",
    "latexmk": "install TeX Live with latexmk, or point ProofLens at the paper's PDF",
    "synctex": "install TeX Live (it provides synctex)",
    "pdftohtml": "install poppler (poppler-utils) to read a PDF, or give the paper's LaTeX source",
    "pdfinfo": "install poppler (poppler-utils) to read a PDF, or give the paper's LaTeX source",
}


# -- mode selection ---------------------------------------------------------------------------

def _found_config() -> Path | None:
    return next((Path(n) for n in cfgmod.CONFIG_NAMES if Path(n).exists()), None)


def _config_arg(a) -> Path:
    """The configuration of the full assessment: given with -c, else the one in the current
    directory."""
    c = getattr(a, "config", None) or _found_config()
    if c is None:
        sys.exit("no machinechecked.toml here (pass one with -c)")
    return Path(c)


def _assurance_config(a) -> Path | None:
    """The configuration that selects the full assessment: given with -c, or in the current
    directory."""
    if getattr(a, "config", None):
        return Path(a.config)
    return _found_config()


def _require(root: Path, paper_kind: str) -> None:
    """Check, before any work, that the programs this run needs are installed: poppler for a
    PDF, latexmk and synctex for LaTeX, and Lake when the project has built modules to inspect.
    A missing one stops the run as `could not run` (exit 2), with how to install it."""
    import shutil
    from .probe import lib_names
    from .simple import built_modules
    need = ["pdftohtml", "pdfinfo"] if paper_kind == "pdf" else ["latexmk", "synctex"]
    libs = lib_names(root)
    if libs and built_modules(root, libs)[0]:
        need.append("lake")
    for tool in need:
        if shutil.which(tool) is None:
            raise FileNotFoundError(2, "not found", tool)


def _simple_target(a):
    from .simple import find_lake_root, find_papers
    root = find_lake_root(Path.cwd().resolve())
    if root is None:
        sys.exit("no Lean project here: run machinechecked inside a directory with a lakefile")
    if a.paper and re.match(r"https?://", a.paper):
        from . import formalization as fz
        fy = fz.load(root) or {}
        title = next((s.get("title") for s in fz.formalized_sources(fy) if "error" not in fy
                      and s.get("id") == a.paper), None)
        _require(root, "pdf")
        paper = _fetch_paper(root, a.paper, title)
    elif a.paper:
        paper = Path(a.paper).resolve()
        if not paper.exists():
            sys.exit(f"{a.paper}: no such file")
    else:
        found = find_papers(root)
        if not found:
            from . import formalization as fz
            fy = fz.load(root) or {}
            urls = [s for s in fz.formalized_sources(fy) if "error" not in fy
                    and re.match(r"https?://", str(s.get("id") or ""))]
            if not urls:
                sys.exit("no paper found (no .tex with \\documentclass, no .pdf): pass its path "
                         "or URL")
            print("The paper is not in the repository; its formalization.yaml names:")
            for i, s in enumerate(urls, 1):
                print(f"  {i}. {s.get('title') or s['id']}\n     {s['id']}")
            if len(urls) == 1:
                k = "1"
            elif not sys.stdin.isatty():
                sys.exit("pass the one to use: machinechecked view <URL>")
            else:
                k = input("Which one? ")
            try:
                s = urls[int(k) - 1]
            except (ValueError, IndexError):
                sys.exit("no paper chosen")
            _require(root, "pdf")
            return root, _fetch_paper(root, s["id"], s.get("title"))
        if len(found) > 1:
            print("Several papers found:")
            for i, f in enumerate(found, 1):
                print(f"  {i}. {f.relative_to(root)}")
            if not sys.stdin.isatty():
                sys.exit("pass the one to use: machinechecked view <paper>")
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
    _require(root, "tex" if paper.suffix == ".tex" else "pdf")
    return root, paper


def _settings(a, root: Path | None):
    """Record --issues and --site-url: in the links file (zero configuration); a full
    assessment sets them in its configuration."""
    issues, url = getattr(a, "issues", None), getattr(a, "site_url", None)
    author = getattr(a, "author", None)
    private = getattr(a, "private_repository", None)
    if not issues and not url and not author and private is None:
        return
    if root is None:
        sys.exit("set `issues`, `site_url`, `author` and `repository_private` under [project] in "
                 "machinechecked.toml")
    from .simple import save_settings
    try:
        save_settings(root, issues=cfgmod.issue_repo(issues, "--issues") if issues else None,
                      site_url=url, author=author, repository_private=private)
    except cfgmod.ConfigError as e:
        sys.exit(str(e))


def _fetch_paper(root: Path, url: str, title: str | None = None) -> Path:
    """A paper given by URL, downloaded once into the working directory (never into the
    repository), with its address and title beside it."""
    import hashlib
    import urllib.request
    from .util import prepare_work_dir
    d = prepare_work_dir(root / cfgmod.work_dir_name(root)) / "papers"
    name = re.sub(r"[^\w.-]+", "_", url.rstrip("/").rsplit("/", 1)[-1]) or "paper"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    out = d / f"{hashlib.sha256(url.encode()).hexdigest()[:10]}-{name}"
    if not out.exists():
        d.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}", file=sys.stderr)
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                data = r.read(200_000_001)
        except Exception as e:
            sys.exit(f"could not download {url}: {e}")
        if len(data) > 200_000_000 or not data.startswith(b"%PDF"):
            sys.exit(f"{url} is not a PDF (or is larger than 200 MB)")
        out.write_bytes(data)
    out.with_suffix(".json").write_text(json.dumps({"url": url, "title": title}))
    return out


def _simple_view(root: Path, paper: Path) -> dict:
    """What the reader would show, without writing it (`check` needs no site)."""
    from .simple import build_view
    out = root / cfgmod.work_dir_name(root)
    return build_view(root, paper, out, log=lambda m: print("  " + m, file=sys.stderr))


def _simple_site(root: Path, paper: Path, web: str | None):
    from .simple import write_view_site
    view = _simple_view(root, paper)
    site = root / cfgmod.work_dir_name(root) / "site"
    index = write_view_site(view, site, _web_dist(web), root)
    return site, index, view


def _print_simple(body):
    from .simple import view_summary
    for n in body.get("notes", []):
        print(f"note: {n}")
    for s, k in sorted(view_summary(body).items()):
        print(f"  {k:4d}  {s}")


# -- everyday commands ------------------------------------------------------------------------

def cmd_view(a):
    if _assurance_config(a):
        from .pipeline import build
        from .server import serve
        _settings(a, None)
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
    _settings(a, root)
    print(f"MachineChecked: {paper.relative_to(root)} in {root.name}")
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(view["body"])
    key = view["body"]["paper"]

    def on_link(req):
        save_link(root, key, req["key"], req.get("lean"), req.get("reject"))
        _simple_site(root, paper, a.web)

    serve(site, a.port, on_link, not a.no_browser)


def cmd_build_simple(a):
    from .bundle import bundle
    root, paper = _simple_target(a)
    _settings(a, root)
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(view["body"])
    if a.site:
        import shutil
        dest = Path(a.site).resolve()
        if dest == root.resolve() or root.resolve().is_relative_to(dest):
            sys.exit(f"--site {a.site}: choose a new directory, not the project")
        if dest.exists():
            if not (dest / "audit.json").exists() and any(dest.iterdir()):
                sys.exit(f"--site {a.site}: not empty and not a previous site; choose another")
            shutil.rmtree(dest)
        shutil.copytree(site, dest)
        print(f"wrote the reader to {dest}: publish this directory as it is "
              "(audit.json describes it)")
        return
    # By default inside the working directory, which Git ignores: the file embeds the paper,
    # so putting it where it could be committed takes a deliberate --out.
    out = Path(a.out or (root / cfgmod.work_dir_name(root) / "MachineChecked.html")).resolve()
    res = bundle(site, out, f"MachineChecked — {index['papers'][0]['title']}")
    print(f"wrote {res['out']} ({res['size'] / 1e6:.1f} MB): open it in a browser")


def cmd_check(a):
    if getattr(a, "json", False):
        return _check_json(a)
    if _assurance_config(a):
        a.config = str(_assurance_config(a))
        a.release = None; a.skip_lean = a.skip_tex = False; a.lake = "lake"
        a.no_lean_build = False; a.reuse_lean = False; a.fail_on_violation = True
        return cmd_build(a)
    root, paper = _simple_target(a)
    view = _simple_view(root, paper)
    _print_simple(view["body"])
    bad = [(c["number"], l["name"], l["status"]) for c in view["body"]["claims"]
           for l in c["links"] if l["class"] != "proved"]
    for b in bad:
        print(f"FAIL {b[0]} -> {b[1]}: {b[2]}")
    if bad:
        sys.exit(1)
    n = sum(len(c["links"]) for c in view["body"]["claims"])
    if not n:
        print("no claim is linked yet: confirm links in `machinechecked view`")
        return
    print(f"all {n} linked declaration(s) are checked by Lean (whether each says what the paper "
          "says is not reviewed by this check)")


CHECK_NOTE = ("Statuses say what Lean establishes about the linked declarations. Whether a Lean "
              "statement says what the paper says is not checked here; that takes a reviewer.")


FINDING_KEYS = ("id", "tier", "code", "subject", "message", "trigger", "dismissed")


def _finding_details(cfg, eid: str) -> list[dict]:
    """The full assessment's findings, as stored with its evidence: what each says and which
    clause or claim it concerns (`subject`), violations first."""
    from . import evidence as ev
    found = ev.load(cfg.out_dir, eid)["body"]["assessment"]["findings"]
    order = {"violation": 0, "obligation": 1, "warning": 2}
    return [{k: f[k] for k in FINDING_KEYS if k in f}
            for f in sorted(found, key=lambda f: (order.get(f.get("tier"), 3), f.get("id", "")))]


def _check_json(a):
    """`check --json`: every claim with its status and links, as one JSON document on stdout
    (progress goes to stderr). Exit 1 if a linked declaration is missing or not proved."""
    import contextlib
    import json
    with contextlib.redirect_stdout(sys.stderr):
        if _assurance_config(a):
            from .pipeline import build
            cfg = cfgmod.load(_assurance_config(a))
            res = build(cfg, web_dist=_web_dist(a.web))
            idx = res["index"]
            claims = [{"id": c["id"], "paper": c["paper"], "number": c.get("number"),
                       "title": c.get("title"), "status": c["status"], "class": c["class"]}
                      for c in idx["claims"]]
            out = {"mode": "full", "release": idx["release"],
                   "project": idx.get("project", {}).get("commit"),
                   "findings": idx["findings"]["total"],
                   "finding_details": _finding_details(cfg, res["evidence"])}
            failed = bool(idx["findings"]["total"].get("violation"))
        else:
            root, paper = _simple_target(a)
            from .simple import view_release
            view = _simple_view(root, paper)
            body = view["body"]
            claims = [{"id": c["id"], "number": c["number"], "title": c["title"],
                       "status": c["status"], "class": c["class"],
                       "links": [{"name": l["name"], "status": l["status"], "class": l["class"],
                                  "source": l.get("source")} for l in c["links"]],
                       "suggestions": [{"name": x["name"], "why": x.get("why")}
                                       for x in c.get("suggestions", [])]}
                      for c in body["claims"]]
            out = {"mode": "simple", "paper": body["paper"], "title": body["title"],
                   "release": view_release(body), "commit": body.get("commit"),
                   "modules": {"built": body["project"]["built"],
                               "not_built": body["project"]["unbuilt"]},
                   "notes": body["notes"]}
            failed = any(l["class"] != "proved" for c in claims for l in c["links"])
    summary = {}
    for c in claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    print(json.dumps({"schema": "machinechecked/check@1", "version": tool_version(), **out,
                      "summary": summary,
                      "claims": claims, "ok": not failed, "note": CHECK_NOTE}, indent=1))
    if failed:
        sys.exit(1)


def cmd_build(a):
    if not _assurance_config(a):
        return cmd_build_simple(a)
    from .pipeline import build
    cfg = cfgmod.load(_config_arg(a))
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
    # Violations and obligations, one per line: they are few, and they block acceptance.
    for f in _finding_details(cfg, res["evidence"]):
        if f["tier"] in ("violation", "obligation") and not f.get("dismissed"):
            print(f"  {f['tier']}  {f['subject']}: {f['message']}")
    if idx["findings"]["total"].get("warning"):
        print("  (warnings: see `check --json` or the reader)")
    if a.fail_on_violation and idx["findings"]["total"].get("violation"):
        sys.exit(1)


def cmd_site(a):
    from .pipeline import rebuild_site
    cfg = cfgmod.load(_config_arg(a))
    res = rebuild_site(cfg, _web_dist(a.web), a.release)
    print(f"site of release {res['release']} written to {res['site']}")


def cmd_reassess(a):
    from .pipeline import reassess
    cfg = cfgmod.load(_config_arg(a))
    res = reassess(cfg, _web_dist(a.web), a.release)
    print(f"site of release {res['release']} written to {res['site']}")


def cmd_bundle(a):
    from .bundle import bundle
    cfg = cfgmod.load(_config_arg(a))
    site = Path(a.site).resolve() if a.site else cfg.out_dir / "site"
    res = bundle(site, Path(a.out).resolve(), a.title)
    print(f"wrote {res['out']}: {res['size'] / 1e6:.1f} MB, {res['files']} data files, "
          f"{res['pdfs']} PDFs; open it in a browser, no server needed")


def cmd_export(a):
    from .export import ExportError, export
    cfg = cfgmod.load(_config_arg(a))
    try:
        res = export(cfg, Path(a.out).resolve(), a.release,
                     None if a.data_only else _web_dist(a.web))
    except ExportError as e:
        sys.exit(str(e))
    print(f"exported release {res['release']} to {res['out']}")


def cmd_cache(a):
    from . import cache
    from .simple import find_lake_root
    if a.action == "prune":
        cache.prune(a.repo, a.keep, log=lambda m: print(m, file=sys.stderr))
        return
    project = Path(a.project).resolve() if a.project else find_lake_root(Path.cwd().resolve())
    if project is None:
        sys.exit("no Lean project here: run machinechecked inside a directory with a lakefile")
    out = Path(a.out).resolve() if getattr(a, "out", None) else project / ".lean-cache"
    if a.action == "save":
        cache.save(project, out, a.target, a.pin_file, log=lambda m: print(m, file=sys.stderr))
    elif a.action == "publish":
        cache.publish(project, out, a.repo, log=lambda m: print(m, file=sys.stderr))
    else:
        if not a.repo and not a.from_dir:
            sys.exit("say where to restore from: OWNER/REPO, or --from DIR")
        cache.restore(project, a.repo, Path(a.from_dir).resolve() if a.from_dir else None,
                      a.build, log=lambda m: print(m, file=sys.stderr))


def cmd_serve(a):
    cfg = cfgmod.load(_config_arg(a))
    site = Path(a.dir).resolve() if a.dir else cfg.out_dir / "site"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    print(f"serving {site} on http://127.0.0.1:{a.port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def cmd_review(a):
    import shlex
    import subprocess
    from . import promote as pr
    from .pipeline import reassess
    cfg = cfgmod.load(_config_arg(a))
    try:
        steps = pr.plan(cfg, pr.load_reports([Path(f) for f in a.reports]),
                        a.accept_same_family)
    except pr.PromoteError as e:
        sys.exit(f"machinechecked: {e}")
    ok = []
    for r, cur, why in steps:
        u = r.get("unit", {})
        head = f"{u.get('name')} ({u.get('kind')}) by {r.get('reviewer', {}).get('id')}: " \
               f"{r.get('verdict', {}).get('value')}"
        if why:
            print(f"REFUSED  {head}")
            for w in why:
                print(f"           - {w}")
        else:
            print(f"OK       {head}\n           {pr.marker(r, cur)}")
            ok.append((r, cur))
    if not ok:
        sys.exit("nothing to promote")
    if not a.yes:
        if not sys.stdin.isatty():
            sys.exit("pass --yes to write the markers without a prompt")
        if input(f"Write {len(ok)} marker(s) and archive the report(s)? [y/N] ").strip().lower() \
                not in ("y", "yes"):
            sys.exit("nothing written")
    done = pr.apply(cfg, ok)
    for d in done:
        print(f"wrote {d['marker']} to {d['file']}")
    old = {c["id"]: c["status"] for c in pr.latest_record(cfg)["body"]["assessment"]["claims"]}
    res = reassess(cfg, _web_dist(None))
    for c in res["index"]["claims"]:
        if old.get(c["id"]) != c["status"]:
            print(f"  {c['id']}: {old.get(c['id'])} -> {c['status']}")
    if cfg.review_check:
        print(f"running {cfg.review_check}")
        r = subprocess.run(shlex.split(cfg.review_check), cwd=cfg.root)
        if r.returncode:
            sys.exit(r.returncode)


def cmd_validate(a):
    validate(json.loads(Path(a.file).read_text()), a.schema)
    print(f"{a.file}: valid {a.schema}")


def main(argv=None):
    name = Path(sys.argv[0]).name
    p = argparse.ArgumentParser(prog=name if name in ("machinechecked", "prooflens")
                                else "machinechecked", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="\n\n".join(__doc__.split("\n\n")[1:]))
    p.add_argument("--version", action="version", version=f"%(prog)s {tool_version()}")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="{view,build,check}")

    w = sub.add_parser("view", help="open the reader")
    w.add_argument("paper", nargs="?",
                   help="the paper: a .tex (its LaTeX root), a .pdf, or a URL of a PDF; "
                   "found in the project when not given")
    w.add_argument("--issues", metavar="OWNER/REPO",
                        help="the GitHub repository where the reader's Raise issue opens reports")
    w.add_argument("--site-url", help="the public address of the published reader, "
                        "for links to claims")
    w.add_argument("--author", help="the name the audit is published under (in audit.json)")
    w.add_argument("--private-repository", action=argparse.BooleanOptionalAction, default=None,
                   help="the Lean repository is private: the reader does not show its name "
                   "(its source links still name it, and open only for people with access)")
    w.add_argument("-c", "--config", help=argparse.SUPPRESS)
    w.add_argument("--port", type=int, default=8017)
    w.add_argument("--no-browser", action="store_true")
    w.add_argument("--web", help=argparse.SUPPRESS)
    w.set_defaults(func=cmd_view)

    b = sub.add_parser("build", help="write the reader as one HTML file to share")
    b.add_argument("paper", nargs="?",
                   help="the paper: a .tex (its LaTeX root), a .pdf, or a URL of a PDF; "
                   "found in the project when not given")
    b.add_argument("--issues", metavar="OWNER/REPO",
                        help="the GitHub repository where the reader's Raise issue opens reports")
    b.add_argument("--site-url", help="the public address of the published reader, "
                        "for links to claims")
    b.add_argument("--author", help="the name the audit is published under (in audit.json)")
    b.add_argument("--private-repository", action=argparse.BooleanOptionalAction, default=None,
                   help="the Lean repository is private: the reader does not show its name "
                   "(its source links still name it, and open only for people with access)")
    b.add_argument("--out", help="the HTML file (default: .machinechecked/MachineChecked.html, "
                   "which Git ignores; it embeds the paper)")
    b.add_argument("--site", metavar="DIR", help="write the reader as a directory to publish "
                   "(for example on GitHub Pages) instead of one HTML file")
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
                                     "linked declaration is missing or unproved, 2 if the check "
                                     "could not run)")
    k.add_argument("paper", nargs="?",
                   help="the paper: a .tex (its LaTeX root), a .pdf, or a URL of a PDF; "
                   "found in the project when not given")
    k.add_argument("--json", action="store_true",
                   help="print every claim's status and links as JSON (for scripts and agents)")
    k.add_argument("-c", "--config", help=argparse.SUPPRESS)
    k.add_argument("--web", help=argparse.SUPPRESS)
    k.set_defaults(func=cmd_check)

    # The full assessment's own operations; not listed.
    t = sub.add_parser("site")
    t.add_argument("-c", "--config", default=None)
    t.add_argument("--release")
    t.add_argument("--web")
    t.set_defaults(func=cmd_site)

    r = sub.add_parser("reassess")
    r.add_argument("-c", "--config", default=None)
    r.add_argument("--release")
    r.add_argument("--web")
    r.set_defaults(func=cmd_reassess)

    n = sub.add_parser("bundle")
    n.add_argument("-c", "--config", default=None)
    n.add_argument("--site")
    n.add_argument("--out", required=True)
    n.add_argument("--title")
    n.set_defaults(func=cmd_bundle)

    e = sub.add_parser("export")
    e.add_argument("-c", "--config", default=None)
    e.add_argument("--release")
    e.add_argument("--out", required=True)
    e.add_argument("--web")
    e.add_argument("--data-only", action="store_true",
                   help="write the audit's data only, without the reader (for a site that "
                   "reads it with its own reader, such as machinechecked.org)")
    e.set_defaults(func=cmd_export)

    ca = sub.add_parser("cache", help="save and restore the Lean build as release assets")
    cas = ca.add_subparsers(dest="action", required=True)
    cs = cas.add_parser("save", help="build, then archive the build output in .lean-cache/")
    cs.add_argument("--target", action="append", default=[],
                    help="a Lake target to build and archive (default: the default targets)")
    cs.add_argument("--pin-file", help=argparse.SUPPRESS)
    cp = cas.add_parser("publish", help="upload the saved archive to the build-cache release")
    cp.add_argument("repo", metavar="OWNER/REPO")
    cpr = cas.add_parser("prune", help="delete all but the newest saved builds")
    cpr.add_argument("repo", metavar="OWNER/REPO")
    cpr.add_argument("--keep", type=int, required=True,
                     help="how many to keep per package, platform and Lean version")
    cpr.add_argument("--project", help=argparse.SUPPRESS)
    cr = cas.add_parser("restore", help="restore the nearest compatible saved build")
    cr.add_argument("repo", nargs="?", metavar="OWNER/REPO")
    cr.add_argument("--from", dest="from_dir", metavar="DIR",
                    help="restore from a directory of saved archives instead of a release")
    cr.add_argument("--build", action="store_true",
                    help="then run `lake build --rehash` (rebuilds only what changed)")
    for x in (cs, cp, cr):
        x.add_argument("--project", help="the Lean project (default: the one here)")
    for x in (cs, cp):
        x.add_argument("--out", help="where archives are saved (default: .lean-cache/)")
    ca.set_defaults(func=cmd_cache)

    s = sub.add_parser("serve")
    s.add_argument("-c", "--config", default=None)
    s.add_argument("--dir")
    s.add_argument("--port", type=int, default=8017)
    s.set_defaults(func=cmd_serve)

    rv = sub.add_parser("review")
    rvs = rv.add_subparsers(dest="action", required=True)
    pm = rvs.add_parser("promote", help="turn review reports into review markers (maintainer)")
    pm.add_argument("reports", nargs="+", help="files exported from the review queue")
    pm.add_argument("-c", "--config", default=None)
    pm.add_argument("--yes", action="store_true", help="write without asking")
    pm.add_argument("--accept-same-family", action="store_true",
                    help="accept a model reviewer of the author's family, or of unknown family")
    pm.set_defaults(func=cmd_review)

    v = sub.add_parser("validate")
    v.add_argument("file")
    v.add_argument("--schema", required=True,
                   choices=["inventory", "evidence", "manifest-index", "manifest-claim"])
    v.set_defaults(func=cmd_validate)

    a = p.parse_args(argv)
    try:
        a.func(a)
    except SystemExit as e:
        # `sys.exit("message")` is a command that could not do its job; an integer is its result.
        if isinstance(e.code, str):
            _could_not_run(a, "error", e.code.removeprefix("machinechecked: "))
        raise
    except FileNotFoundError as e:
        tool = Path(str(e.filename or "")).name
        if tool in MISSING:
            _could_not_run(a, "missing-tool", f"`{tool}` not found: {MISSING[tool]}", tool=tool)
        _could_not_run(a, "internal", _crash(e))
    except (RuntimeError, ValueError, OSError) as e:
        # The engine's own errors (the Lean probe, TeX, the paper's sources, the configuration,
        # stored evidence) say what went wrong in their message.
        if type(e).__module__.startswith("prooflens"):
            _could_not_run(a, "error", str(e))
        _could_not_run(a, "internal", _crash(e))
    except Exception as e:
        _could_not_run(a, "internal", _crash(e))


# Exit codes: 0 the command did its job (and `check` found nothing wrong), 1 `check` (or
# `build --fail-on-violation`) found a problem, 2 the command could not run.
COULD_NOT_RUN = 2


def tool_version() -> str:
    """The installed MachineChecked version."""
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("machinechecked")
    except PackageNotFoundError:
        return "unknown"


def _crash(e: Exception) -> str:
    """An unexpected error: its traceback on stderr, for a bug report, and a one-line message."""
    import traceback
    traceback.print_exc()
    return f"unexpected error ({type(e).__name__}: {e}); please report it with the traceback above"


def _could_not_run(a, kind: str, message: str, **extra):
    """Stop with exit 2: the message on stderr and, for `check --json`, one JSON document on
    stdout saying the check did not run."""
    print(f"machinechecked: {message}", file=sys.stderr)
    if getattr(a, "func", None) is cmd_check and getattr(a, "json", False):
        import json
        print(json.dumps({"schema": "machinechecked/check@1", "ok": False,
                          "error": {"kind": kind, "message": message, **extra},
                          "note": "The check did not run; nothing is known about the claims."},
                         indent=1))
    raise SystemExit(COULD_NOT_RUN)


if __name__ == "__main__":
    main()
