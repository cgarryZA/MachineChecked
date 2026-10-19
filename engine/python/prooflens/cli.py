"""`machinechecked`: read a paper beside its Lean formalisation.

Everyday commands, run from anywhere inside a Lean project:

    machinechecked view [paper]    open the reader (the paper is found if not given)
    machinechecked build [paper]   write the reader as one HTML file to share
    machinechecked check [paper]   report what the Lean side establishes, for CI

A project with a `machinechecked.toml` (an acceptance layer: locked statements, reviews) gets
the full assessment; any other project gets the zero-configuration view, whose only file in the
repository is `machinechecked.links.json` (its working files, a downloaded paper among them, are
in `.machinechecked/`, which Git ignores). The full assessment has further commands: reassess,
site, bundle, export, serve, review promote, replay and validate; `cache` saves and restores
the Lean build (each with --help). `link` records a claim's links from the terminal, and
`workspace` keeps a saved investigation, as the reader does.
`prooflens` is another name for the same command.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import os
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

        def on_symbol(req):
            from .symbols import from_reader
            from_reader(cfg, req, _web_dist(a.web))

        from .workspace import api
        serve(res["site"], a.port, None, not a.no_browser, on_symbol=on_symbol,
              api=api(cfg.out_dir, res["site"] / "data", cfg.root))
        return
    from . import authoring
    from .server import serve
    from .targets import Snapshot
    from .workspace import api
    root, paper = _simple_target(a)
    _settings(a, root)
    print(f"MachineChecked: {paper.relative_to(root)} in {root.name}")
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(view["body"])
    key = view["body"]["paper"]

    def on_link(req):
        change = authoring.from_reader(root, key, Snapshot(site / "data"), req)
        _simple_site(root, paper, a.web)
        return {"claim": change["claim"], "changed": change["changed"]}

    serve(site, a.port, on_link, not a.no_browser,
          api=api(root / cfgmod.work_dir_name(root), site / "data", root))


# -- recording links and investigations -------------------------------------------------------

def _print_json(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def cmd_link(a):
    """`machinechecked link CLAIM [DECL ...]`: record, reject or clear a claim's links in the
    links file, checked against the last build (no Lean runs)."""
    from . import authoring
    from .simple import links_key, paper_title
    from .targets import Snapshot, TargetError
    if _assurance_config(a):
        sys.exit("`link` records the links of the zero-configuration view; a full assessment "
                 "names its declarations in the inventory")
    root, paper = _simple_target(a)
    try:
        snap = Snapshot(root / cfgmod.work_dir_name(root) / "site" / "data")
    except TargetError as e:
        sys.exit(str(e))
    built_title = ((snap.index.get("papers") or [{}])[0]).get("title")
    if built_title != paper_title(paper):
        sys.exit(f"the last build is of another paper ({built_title}); run "
                 f"`machinechecked view {paper.relative_to(root)}` first")
    note = _text_arg(a.note_file) if a.note_file else a.note
    try:
        change = authoring.plan(root, links_key(root, paper), snap, a.claim,
                                lean=a.decls or None, add=a.add, reject=a.reject or None,
                                clear=a.clear, note=note, coverage=a.coverage,
                                confidence=a.confidence, reason=a.reason, by=a.reviewer,
                                external=a.external)
        if not a.dry_run:
            authoring.write(root, change)
    except authoring.LinkError as e:
        if a.json:
            _print_json({"schema": "machinechecked/link@1", "ok": False, "written": False,
                         "error": e.to_json()})
            raise SystemExit(1)
        lines = [f"machinechecked: {e}"] + [
            "  " + (f"{c['id']}  {c.get('number') or ''}".rstrip() if "id" in c
                    else f"{c.get('name')}" + (f"  ({c['module']})" if c.get("module") else "")
                    if isinstance(c, dict) and "name" in c else json.dumps(c, ensure_ascii=False))
            for c in e.candidates]
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(1)
    written = change["changed"] and not a.dry_run
    if a.json:
        _print_json({"schema": "machinechecked/link@1", "ok": True, "written": written,
                     "dry_run": a.dry_run, **change})
        return
    c = change["claim"]
    for d in change["declarations"]:
        state = {"built": "in the build", "unbuilt": "its module is not built: Lean has not "
                 "checked it", "not loaded": "its module could not be loaded",
                 "external": "not a project declaration: Lean checks it at the next build"}
        print(f"  {d['name']}: {state.get(d['build'], d['build'])}")
    if not change["changed"]:
        print(f"{c['id']} ({c['number']}): nothing to change")
    elif a.dry_run:
        print(f"{c['id']} ({c['number']}) would become:\n"
              + json.dumps(change["after"], indent=1, ensure_ascii=False))
    else:
        print(f"recorded for {c['id']} ({c['number']}) in {authoring.simple.links_file(root).name}"
              "; `machinechecked view` or `build` shows it")


def _workspace_place(a):
    """The working directory, the build's site data and the project of a workspace command."""
    if _assurance_config(a):
        cfg = cfgmod.load(_assurance_config(a))
        return cfg.out_dir, cfg.out_dir / "site" / "data", cfg.root
    from .simple import find_lake_root
    root = find_lake_root(Path.cwd().resolve())
    if root is None:
        sys.exit("no Lean project here: run machinechecked inside a directory with a lakefile")
    work = root / cfgmod.work_dir_name(root)
    return work, work / "site" / "data", root


def _print_workspace(v: dict) -> None:
    print(f"workspace {v['id']} ({v['mode']}), {v['reviewer']}, revision {v['revision']}"
          + (f", made at release {v['release']}" if v.get("release") else ""))
    cur = (v.get("current_sources") or {}).get("release")
    if cur and cur != v.get("release"):
        print(f"  the current build is release {cur}")
    r = v.get("resume") or {}
    if r:
        print("  resume at " + ", ".join(f"{k} {r[k]}" for k in ("claim", "clause", "question")
                                          if r.get(k)))
    for e in v.get("exposure") or []:
        print(f"  had seen: {', '.join(e['what'])} of "
              f"{'every claim' if e.get('claims') is None else ', '.join(e['claims'])} "
              f"({e.get('how')}, {e.get('at')})")
    if v.get("conflicts"):
        print(f"  {len(v['conflicts'])} refused conflicting edit(s) kept (see --json)")
    for cid, c in v["claims"].items():
        print(cid)
        for e in c["evidence"]:
            ref = e["ref"]
            what = ref.get("decl") or (ref.get("source") or {}).get("file") or "paper passage"
            print(f"  evidence {e['id']}  {e['role']:9} {what}  [{e['currency']['state']}]"
                  + (f" (module not built)" if ref.get("build") == "unbuilt" else ""))
        for f in c["findings"]:
            tag = f["state"] + ("" if f["in_force"] else ", superseded")
            print(f"  finding  {f['id']}  {tag}: coverage {f.get('coverage') or '-'}"
                  f"  [{f['currency']['state']}]" + (f"  supersedes {f['supersedes']}: "
                                                     f"{f['reason']}" if f.get("supersedes")
                                                     else ""))
            if f.get("question"):
                print(f"           question: {f['question']}")
        for q in c["questions"]:
            print(f"  question {q['id']}  {q['state']}: {q['text']}")


def cmd_workspace(a):
    """`machinechecked workspace open|list|show|update|export|import`: the saved investigation
    (`workspace.py`), as the reader saves it."""
    from . import review_cli as rc
    from . import workspace as wsp
    from .targets import Snapshot, TargetError
    work, data, root = _workspace_place(a)
    try:
        snap = Snapshot(data)
    except TargetError:
        snap = None

    def who():
        try:
            return rc.parse_reviewer(a.reviewer, getattr(a, "same_family", "unknown"))
        except rc.ReviewError as e:
            sys.exit(str(e))

    def path():
        if getattr(a, "id", None):
            return wsp.find(work, a.id)
        return wsp.open_for(work, who(), getattr(a, "mode", None),
                            sources=snap.sources() if snap else None)

    try:
        if a.action == "list":
            rows = [wsp.summary(ws) for _, ws in wsp.list_all(work)]
            if a.json:
                return _print_json({"schema": "prooflens/workspaces@1", "workspaces": rows})
            for r in rows:
                print(f"{r['id']}  {r['mode']:11} {r['reviewer']}  {r['findings']} finding(s), "
                      f"{r['open_questions']} open question(s), {r['reports']} report(s)")
            if not rows:
                print("no workspace yet: `machinechecked workspace open --as human:NAME`")
        elif a.action in ("open", "show"):
            if a.action == "open" and a.id and a.mode:
                # Opening by id with another mode is refused by open_for, not changed silently.
                p = wsp.open_for(work, who(), a.mode, a.id)
            else:
                p = path()
            claim = None
            if getattr(a, "claim", None):
                if snap is None:
                    sys.exit("no build to resolve the claim against: run view or build first")
                claim = snap.resolve_claim(a.claim)
            v = wsp.view(wsp.read(p), snap, claim)
            if a.json:
                return _print_json({**v, "path": str(p)})
            _print_workspace(v)
        elif a.action == "update":
            raw = json.loads(_text_arg(a.file))
            ops = raw.get("ops") if isinstance(raw, dict) else raw
            op_id = a.op_id or (raw.get("op_id") if isinstance(raw, dict) else None)
            p = path()
            ack = wsp.update(p, ops, snap, root, a.reviewer or None, op_id, a.dry_run)
            _print_json(ack)
        elif a.action == "export":
            body = wsp.export(path())
            Path(a.out).write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
            print(f"wrote {a.out} (workspace {body['id']}, {body['mode']})")
        elif a.action == "import":
            res = wsp.import_(work, json.loads(_text_arg(a.file)), snap, a.reviewer,
                              None if a.file == "-" else Path(a.file).name)
            _print_json(res)
            if res["problems"] or res["conflicts"]:
                raise SystemExit(1)
    except wsp.Conflict as e:
        _print_json({"ok": False, "error": str(e), "conflicts": e.conflicts})
        raise SystemExit(1)
    except (wsp.WorkspaceError, TargetError, ValueError) as e:
        if getattr(a, "json", False) or a.action in ("update", "import"):
            _print_json({"ok": False, "error": str(e),
                         **({"candidates": e.candidates} if isinstance(e, TargetError) else {})})
            raise SystemExit(1)
        sys.exit(f"machinechecked: {e}")


def _site_dest(site: str, root: Path) -> Path:
    """The directory `--site` names, refused when it is the project (or holds it), or when it
    has other content than a previous site: writing the site replaces it."""
    dest = Path(site).resolve()
    if dest == root.resolve() or root.resolve().is_relative_to(dest):
        sys.exit(f"--site {site}: choose a new directory, not the project")
    if dest.exists() and not (dest / "audit.json").exists() and any(dest.iterdir()):
        sys.exit(f"--site {site}: not empty and not a previous site; choose another")
    return dest


def cmd_build_simple(a):
    from .bundle import bundle
    root, paper = _simple_target(a)
    _settings(a, root)
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(view["body"])
    if a.site:
        import shutil
        dest = _site_dest(a.site, root)
        if dest.exists():
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
    print(f"Lean checked all {n} linked declaration(s)")


CHECK_NOTE = "Results describe the linked Lean declarations; correspondence reviews compare them with the paper."


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
                       "title": c.get("title"), "status": c["status"], "status_code": c["status_code"], "class": c["class"]}
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
                       "status": c["status"], "status_code": c["status_code"], "class": c["class"],
                       "links": [{"name": l["name"], "status": l["status"], "status_code": l["status_code"], "class": l["class"],
                                  "source": l.get("source")} for l in c["links"]],
                       "correspondence": c.get("correspondence"),
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
    dest = _site_dest(a.site, cfg.root) if getattr(a, "site", None) else None
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
    if dest is not None:
        # The site to publish is the audit's public export: what the configuration publishes,
        # scanned for private material, as `export --out` writes it.
        from .export import ExportError, export
        try:
            out = export(cfg, dest, res["release"], _web_dist(a.web))
        except ExportError as e:
            sys.exit(str(e))
        print(f"wrote the audit to {out['out']}: publish this directory as it is "
              "(audit.json describes it)")
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
                     None if a.data_only else _web_dist(a.web), paper=a.paper)
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


def cmd_replay(a):
    from .replay import replay
    cfg = cfgmod.load(_config_arg(a))
    out = Path(a.out).resolve() if a.out else cfg.comparator_log
    if out is None:
        sys.exit("say where to write the record: --out FILE, or `comparator_log` in "
                 "machinechecked.toml (which the assessment then reads)")
    rec = replay(cfg.lean_root, Path(a.comparator_config).resolve(), out, a.comparator)
    print(f"Comparator {'passed' if rec['passed'] else 'did not pass'} on commit "
          f"{rec['commit'][:12]}: {len(rec['replayed'])} theorem(s) replayed; record in {out}")
    if not rec["passed"]:
        sys.exit(1)


def cmd_inspect(a):
    import json
    from .deps import inspect
    from .simple import find_lake_root
    root = Path(a.project).resolve() if a.project else find_lake_root(Path.cwd().resolve())
    if root is None:
        sys.exit("no Lean project here: run machinechecked inside a directory with a lakefile")
    log = (lambda m: print(m, file=sys.stderr))
    out = inspect(root, a.name, a.module, log=log, refresh=a.refresh)
    if not a.dependencies and out.get("closure"):
        out["closure"] = {k: v for k, v in out["closure"].items() if k != "members"}
    if a.json:
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        _print_inspect(out, a.dependencies)
    if not out["ok"]:
        sys.exit(1)


def _print_inspect(out: dict, dependencies: bool):
    if not out["ok"]:
        where = ", ".join(out.get("modules") or [])
        print(f"{out['name']}: {out['status']}" + (f" ({where})" if where else "")
              + (f": {out['reason']}" if out.get("reason") else ""))
        if out["status"] == "ambiguous":
            print("  name the module that declares it with --module")
        return
    d = out["declaration"]
    line = (d.get("range") or {}).get("line")
    print(f"{d['name']}  ({d['kind']}, {d['file']}" + (f":{line}" if line else "") + ")")
    print(f"  statement: {d['statement']}")
    print(f"  axioms: {', '.join(d['axioms']) or 'none'}" + ("  (uses sorry)" if d["sorry"] else ""))
    for label, key in (("statement uses", "statement_dependencies"),
                       (f"{out['value_kind']} uses", "proof_dependencies")):
        names = out[key]
        shown = ", ".join(names[:12]) + (f", … ({len(names)} in all)" if len(names) > 12 else "")
        print(f"  {label} (this project): {shown or 'nothing'}")
    ext = out["external_dependencies"]
    print(f"  outside this project: {len(ext['statement'])} in the statement, "
          f"{len(ext['proof'])} in the {out['value_kind']}")
    c = out["closure"]
    by = ", ".join(f"{k} {v}" for k, v in list(c["external"]["by_package"].items())[:5])
    print(f"  reaches {c['declarations']} declaration(s) of this project (deepest {c['deepest']} "
          f"step(s)), and {c['external']['constants']} constant(s) outside it" +
          (f": {by}" if by else ""))
    if dependencies:
        for m in c["members"]:
            print(f"    {m['depth']:>3}  {m['name']}  ({m['kind']}, {m['module']})")
    print(f"  {out['note']}")
    if out.get("cache", {}).get("hit"):
        print("  (from the cache: no Lean input changed)")


def cmd_symbol(a):
    from . import symbols as sy
    cfg = cfgmod.load(_config_arg(a))
    try:
        if a.action == "add":
            ln = sy.add(cfg, a.claim, a.tex, a.decl, a.reviewer, var=a.var, type_of=a.type_of,
                        term=a.term, at=a.at)
            print(f"linked {a.tex} in {a.claim} to {ln['lean']} (by {ln['by']}); "
                  "rebuild the site to show it")
        elif a.action == "remove":
            print(f"removed {sy.remove(cfg, a.claim, a.tex)} link(s)")
        else:
            print(sy.listing(cfg))
    except (sy.SymbolError, OSError) as e:
        sys.exit(f"machinechecked: {e}")


def cmd_serve(a):
    cfg = cfgmod.load(_config_arg(a))
    site = Path(a.dir).resolve() if a.dir else cfg.out_dir / "site"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    print(f"serving {site} on http://127.0.0.1:{a.port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def _text_arg(v: str | None) -> str:
    if v is None:
        return ""
    return sys.stdin.read() if v == "-" else Path(v).read_text(encoding="utf-8")


def cmd_review_step(a):
    from . import review_cli as rc
    cfg = cfgmod.load(_config_arg(a))
    try:
        s = rc.Session(cfg, rc.parse_reviewer(a.reviewer, a.same_family))
        if a.action == "next":
            u = next(iter(s.open_units()), None)
            print(f"{u['id']}  ({u['reason']})" if u else "nothing left to review")
        elif a.action == "status":
            print(f"{len(s.work['reports'])} report(s), {len(s.work['drafts'])} in progress, "
                  f"{len(s.open_units())} unit(s) left to review (release {s.index['release']})")
            for uid, d in s.work["drafts"].items():
                print(f"  {uid}: at step '{d['stage']}'")
        elif a.action == "read":
            print(s.read(a.unit))
        elif a.action == "lock":
            s.lock(a.unit, _text_arg(a.text))
            print(f"reading locked; `review show {a.unit}` shows the Lean")
        elif a.action == "show":
            print(s.show(a.unit))
        elif a.action == "decide":
            s.decide(a.unit, a.verdict, _text_arg(a.comparison), _text_arg(a.detail),
                     _text_arg(a.witness))
            print(f"verdict recorded; `review author {a.unit}` shows the author's review")
        elif a.action == "author":
            print(s.author(a.unit))
        elif a.action == "submit":
            r = s.submit(a.unit, _text_arg(a.text).strip())
            print(f"report recorded: {r['unit']['id']}, {r['verdict']['value']}; "
                  "`review export --out FILE` writes your reports for the maintainer")
        elif a.action == "export":
            print(f"wrote {s.export(Path(a.out))}")
    except (rc.ReviewError, OSError) as e:
        sys.exit(f"machinechecked: {e}")


def cmd_review(a):
    import shlex
    import subprocess
    from . import promote as pr
    from .pipeline import reassess
    cfg = cfgmod.load(_config_arg(a))
    try:
        steps = pr.plan(cfg, pr.load_reports([Path(f) for f in a.reports]),
                        a.accept_same_family, a.allow_revealed)
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
    b.add_argument("--reuse-lean", action="store_true",
                   help="reuse the last Lean results when no Lean input changed (after an edit to "
                        "the claim inventory or the reviews, say)")
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
    e.add_argument("--paper", metavar="ID",
                   help="export only this paper: its claims, the declarations they depend on and "
                   "their reviews; the export is also scanned for the other papers' material")
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

    rp = sub.add_parser("replay", help="run Comparator and record the replay for the "
                        "assessment")
    rp.add_argument("comparator_config", metavar="CONFIG",
                    help="the Comparator configuration (its theorem_names are the proofs "
                    "replayed)")
    rp.add_argument("-c", "--config", default=None, help=argparse.SUPPRESS)
    rp.add_argument("--out", help="the record (default: comparator_log in machinechecked.toml)")
    rp.add_argument("--comparator", default="comparator", help="the Comparator program")
    rp.set_defaults(func=cmd_replay)

    ins = sub.add_parser("inspect", help="what a Lean declaration depends on, proofs included")
    ins.add_argument("name", help="the declaration's full name, e.g. Foo.main_theorem")
    ins.add_argument("--module", help="the module that declares it, when several declare the name")
    ins.add_argument("--dependencies", action="store_true",
                     help="list every declaration of the project it depends on")
    ins.add_argument("--json", action="store_true",
                     help="print one JSON document (for scripts and agents)")
    ins.add_argument("--project", help="the Lean project (default: the one here)")
    ins.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)
    ins.set_defaults(func=cmd_inspect)

    sy = sub.add_parser("symbol", help="link a symbol of the paper to a Lean object (an assertion "
                        "under your name; display only)")
    sys_ = sy.add_subparsers(dest="action", required=True)
    for name in ("add", "remove", "list"):
        p_ = sys_.add_parser(name)
        if name != "list":
            p_.add_argument("claim", help="the claim id, e.g. P:thm:main")
            p_.add_argument("tex", help="the symbol as the paper's TeX writes it, e.g. '\\nu'")
        if name == "add":
            p_.add_argument("decl", help="the claim's Lean statement")
            p_.add_argument("--var", help="the variable it is (a binder's name or index)")
            p_.add_argument("--type-of", dest="type_of", help="the binder whose type it is")
            p_.add_argument("--term", help="the sub-term it is, as WHERE#K: b:<binder>, c (the "
                                           "conclusion) or l:<part>, and the sub-term's number")
            p_.add_argument("--at", help="the sub-term it is, by its identity in the proposition "
                                         "(the `id` the reader's data gives it)")
            p_.add_argument("--as", dest="reviewer",
                            default=os.environ.get("MACHINECHECKED_REVIEWER"),
                            help="human:NAME or llm:MODEL (default: $MACHINECHECKED_REVIEWER)")
        p_.add_argument("-c", "--config", default=None)
        p_.set_defaults(func=cmd_symbol)

    s = sub.add_parser("serve")
    s.add_argument("-c", "--config", default=None)
    s.add_argument("--dir")
    s.add_argument("--port", type=int, default=8017)
    s.set_defaults(func=cmd_serve)

    lk = sub.add_parser("link")
    lk.add_argument("claim", help="the claim: its id or key (thm:main), or its number "
                    "(\"Lemma 2.3\", or 2.3 when only one claim has it)")
    lk.add_argument("decls", nargs="*", metavar="DECL",
                    help="the declarations that state it (they replace the confirmed list)")
    lk.add_argument("--add", action="store_true", help="add DECL to the confirmed list")
    lk.add_argument("--reject", nargs="+", metavar="DECL", help="record suggestions as not this "
                    "claim's")
    lk.add_argument("--reason", help="why they are rejected")
    lk.add_argument("--clear", action="store_true", help="remove the confirmed list (the "
                    "paper's \\lean tags and formalization.yaml apply again)")
    lk.add_argument("--coverage", help="how far the declarations state the claim")
    lk.add_argument("--confidence", help="high, medium or low")
    lk.add_argument("--note", help="the note on the correspondence")
    lk.add_argument("--note-file", help="a file holding the note, or - for standard input")
    lk.add_argument("--as", dest="reviewer", help="the name the link is recorded under")
    lk.add_argument("--external", action="store_true", help="accept a declaration from a "
                    "dependency, which the project's index does not hold")
    lk.add_argument("--paper", help="the paper (default: the one found)")
    lk.add_argument("--dry-run", action="store_true", help="show the change, write nothing")
    lk.add_argument("--json", action="store_true", help="print one JSON document")
    lk.add_argument("-c", "--config", help=argparse.SUPPRESS)
    lk.set_defaults(func=cmd_link)

    ws = sub.add_parser("workspace")
    wss = ws.add_subparsers(dest="action", required=True)
    for name, help_ in {"open": "open or resume your workspace",
                        "list": "the workspaces of this project",
                        "show": "a workspace: evidence, findings and questions per claim",
                        "update": "apply operations (a JSON file, or - for standard input)",
                        "export": "write a workspace as one file",
                        "import": "bring in an exported workspace"}.items():
        sp = wss.add_parser(name, help=help_)
        if name in ("update", "import"):
            sp.add_argument("file", help="a JSON file, or - for standard input")
        if name in ("open", "show", "update", "export"):
            sp.add_argument("--id", help="the workspace (default: yours)")
        if name == "open":
            sp.add_argument("--mode", choices=["independent", "informed"],
                            help="independent review (blind reading first) or informed "
                                 "investigation; fixed when the workspace is made")
        if name in ("open", "show"):
            sp.add_argument("--claim", help="show only this claim")
        if name in ("open", "show", "list"):
            sp.add_argument("--json", action="store_true")
        if name == "update":
            sp.add_argument("--op-id", help="an identifier of this request: repeating it changes "
                            "nothing")
            sp.add_argument("--dry-run", action="store_true", help="show the result, save nothing")
        if name == "export":
            sp.add_argument("--out", required=True)
        sp.add_argument("--as", dest="reviewer", default=os.environ.get("MACHINECHECKED_REVIEWER"),
                        help="human:NAME or llm:MODEL (default: $MACHINECHECKED_REVIEWER)")
        sp.add_argument("--same-family", choices=["yes", "no", "unknown"], default="unknown",
                        help=argparse.SUPPRESS)
        sp.add_argument("-c", "--config", default=None)
        sp.set_defaults(func=cmd_workspace)

    rv = sub.add_parser("review")
    rvs = rv.add_subparsers(dest="action", required=True)
    pm = rvs.add_parser("promote", help="turn review reports into review markers (maintainer)")
    pm.add_argument("reports", nargs="+", help="files exported from the review queue")
    pm.add_argument("-c", "--config", default=None)
    pm.add_argument("--yes", action="store_true", help="write without asking")
    pm.add_argument("--accept-same-family", action="store_true",
                    help="accept a model reviewer of the author's family, or of unknown family")
    pm.add_argument("--allow-revealed", action="store_true",
                    help="accept a report whose reviewer had seen the unit's Lean or author's "
                         "review before writing their reading")
    pm.set_defaults(func=cmd_review)
    # The protocol's steps, for a reviewer without a browser (`review_cli`).
    steps = {
        "next": "the next unit to review",
        "read": "step 1: the paper's statement of a unit",
        "lock": "lock your reading (a file, or - for standard input)",
        "show": "step 2, after lock: the unit's Lean",
        "decide": "record your verdict and comparison",
        "author": "step 3, after decide: the author's review",
        "submit": "record your disagreements with it and finish the report",
        "status": "your progress on this release's queue",
        "export": "write your reports as one file, for the maintainer",
    }
    for name, help_ in steps.items():
        sp = rvs.add_parser(name, help=help_)
        if name not in ("next", "status", "export"):
            sp.add_argument("unit", help="a unit id of the queue, e.g. spec:Foo.thm_bar")
        if name in ("lock", "submit"):
            sp.add_argument("text", help="a file holding your text, or - to read it from standard input")
        if name == "decide":
            sp.add_argument("verdict")
            sp.add_argument("comparison", help="a file holding your comparison, or -")
            sp.add_argument("--detail", help="a file holding what the verdict needs said")
            sp.add_argument("--witness", help="a file holding your note on the witness")
        if name == "export":
            sp.add_argument("--out", required=True)
        sp.add_argument("--as", dest="reviewer", default=os.environ.get("MACHINECHECKED_REVIEWER"),
                        help="human:NAME or llm:MODEL (default: $MACHINECHECKED_REVIEWER)")
        sp.add_argument("--same-family", choices=["yes", "no", "unknown"], default="unknown",
                        help="for a model: whether it is of the statements' author's family")
        sp.add_argument("-c", "--config", default=None)
        sp.set_defaults(func=cmd_review_step)

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
                          "note": "Check unavailable; resolve the execution error and retry."},
                         indent=1))
    elif getattr(a, "func", None) is cmd_inspect and getattr(a, "json", False):
        import json
        print(json.dumps({"schema": "machinechecked/inspect@1", "ok": False,
                          "name": getattr(a, "name", None),
                          "error": {"kind": kind, "message": message, **extra},
                          "note": "Inspection unavailable; resolve the execution error and retry."},
                         indent=1))
    raise SystemExit(COULD_NOT_RUN)


if __name__ == "__main__":
    main()
