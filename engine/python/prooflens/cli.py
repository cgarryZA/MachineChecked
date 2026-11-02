"""`machinechecked`: read a paper beside its Lean formalisation.

Everyday commands, run from anywhere inside a Lean project:

    machinechecked view [paper]    open the reader (the paper is found if not given)
    machinechecked build [paper]   write the reader as one HTML file to share
    machinechecked check [paper]   report what the Lean side establishes, for CI
    machinechecked review next     the next claim to review, from the terminal

A project with a `machinechecked.toml` (an acceptance layer: locked statements, reviews) gets
the full assessment; any other project gets the zero-configuration view, whose only file in the
repository is `machinechecked.links.json` (its working files, a downloaded paper among them, are
in `.machinechecked/`, which Git ignores).
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
    "latexmk": "install TeX Live with latexmk, or give the paper's PDF",
    "synctex": "install TeX Live (it provides synctex)",
    "pdftohtml": "install poppler (poppler-utils) to read a PDF, or give the paper's LaTeX source",
    "pdfinfo": "install poppler (poppler-utils) to read a PDF, or give the paper's LaTeX source",
}


# -- the command list -------------------------------------------------------------------------

# Every command, by group, with what it does. `--help` lists the everyday group, `help --all`
# every group, and a command's own `--help` opens with its line. The reasons each command is kept
# where it is are in docs/DEVELOPMENT.md ("The command list").
EVERYDAY = "Everyday commands"
FULL = "The full assessment (a project with a machinechecked.toml)"
COMMANDS: list[tuple[str, str, str]] = [
    (EVERYDAY, "view", "open the reader"),
    (EVERYDAY, "build", "write the reader as one HTML file to share"),
    (EVERYDAY, "check", "report what the Lean side establishes (exit 1 if a linked declaration is "
                        "missing or unproved, 2 if the check could not run)"),
    (EVERYDAY, "review", "review the claims one at a time from the terminal; `review promote` "
                         "turns reports into review markers (maintainer)"),
    ("Recording and investigating", "link",
     "record, reject or clear a claim's links in the links file, as the reader does"),
    ("Recording and investigating", "workspace",
     "keep a saved investigation (readings, evidence, findings and questions), as the reader does"),
    ("Recording and investigating", "compare",
     "a claim's paper passage, Lean statements and definitions, from the last build (for scripts "
     "and agents)"),
    ("Recording and investigating", "inspect",
     "what a Lean declaration depends on, proofs included, or where it is used"),
    (FULL, "changes", "what changed between two releases and which evidence it reopens"),
    (FULL, "inventory", "pin the claims' source passages, and retire stale readings"),
    (FULL, "reassess", "assess the latest release again with the current reviews and dismissals, "
                       "without Lean"),
    (FULL, "site", "write the reader again from a stored release"),
    (FULL, "bundle", "write the built reader as one HTML file"),
    (FULL, "export", "write the audit's approved public files"),
    (FULL, "serve", "serve the built reader on this machine"),
    (FULL, "evidence", "list and prune the stored evidence"),
    (FULL, "symbol", "link a symbol of the paper to a Lean object (an assertion under your name; "
                     "display only)"),
    (FULL, "replay", "run Comparator and record the replay for the assessment"),
    ("The Lean build", "cache", "save and restore the Lean build as release assets"),
    ("Development", "validate", "check a JSON file against one of the engine's schemas"),
]


def _summary(name: str) -> str:
    return next(s for _, n, s in COMMANDS if n == name)


# -- where a command works --------------------------------------------------------------------

NO_PROJECT = "no Lean project here: run machinechecked inside a directory with a lakefile"


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


def _load_full(a, refusal: str | None = None) -> cfgmod.Config:
    """The full assessment's configuration, loaded, for a command that needs one: without it,
    stop, saying `refusal` (the command's own reason) or that there is none here."""
    if refusal and not _assurance_config(a):
        sys.exit(refusal)
    return cfgmod.load(_config_arg(a))


def _lean_root(given: str | None = None) -> Path:
    """The Lean project: `given` (--project), else the one the current directory is in."""
    from .simple import find_lake_root
    root = Path(given).resolve() if given else find_lake_root(Path.cwd().resolve())
    if root is None:
        sys.exit(NO_PROJECT)
    return root


def _built_work(a) -> tuple[Path, Path]:
    """The working directory of the last build and the Lean project: the full assessment's
    when a configuration selects it, else the zero-configuration view's in the project here.
    Nothing is built: the commands that read a build use the one `view` or `build` wrote, in
    `site/data` of the working directory."""
    if _assurance_config(a):
        cfg = _load_full(a)
        return cfg.out_dir, cfg.lean_root
    root = _lean_root()
    return root / cfgmod.work_dir_name(root), root


def _last_build(work: Path, required: bool = False):
    """The last build's site data in the working directory `work` (`targets.Snapshot`), or None
    when there is none; with `required`, stop instead, saying why."""
    from .targets import Snapshot, TargetError
    try:
        return Snapshot(work / "site" / "data")
    except TargetError as e:
        if required:
            sys.exit(str(e))
        return None


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
    """The Lean project here and the paper of a zero-configuration command: the one given, else
    the one found in the project, else one its formalization.yaml names by URL."""
    from .simple import find_papers
    root = _lean_root()
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


def _simple_view(root: Path, paper: Path, reuse_lean: bool = False,
                 refresh: bool = False) -> dict:
    """What the reader would show, without writing it (`check` needs no site). With
    `reuse_lean`, only stored Lean facts are used; with `refresh`, none."""
    from .simple import build_view
    out = root / cfgmod.work_dir_name(root)
    return build_view(root, paper, out, log=lambda m: print("  " + m, file=sys.stderr),
                      reuse_only=reuse_lean, refresh=refresh)


def _simple_site(root: Path, paper: Path, web: str | None, reuse_lean: bool = False,
                 refresh: bool = False):
    from .simple import write_view_site
    view = _simple_view(root, paper, reuse_lean, refresh)
    site = root / cfgmod.work_dir_name(root) / "site"
    index = write_view_site(view, site, _web_dist(web), root, site.parent)
    return site, index, view


def _check_summary(view: dict, root: Path) -> tuple[dict, dict]:
    """The semantic summary `check` gives in zero configuration, and each claim's facts: those
    of the site this view would write (`semantic.of_view`), with the findings in force of the
    working directory's workspaces checked against that site's data, which is written to a
    temporary directory for the purpose when there are any (`check` writes no site)."""
    from . import semantic
    work = root / cfgmod.work_dir_name(root)
    found = None
    if semantic.has_findings(work):
        import tempfile
        from .simple import write_view_site
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            write_view_site({**view, "pdf": None}, site, None, root)
            found = semantic.workspace_findings(work, site / "data", root)
    return semantic.of_view(view["body"], root, found)


def _print_simple(body, summary: dict | None = None):
    """A view's notes and warnings, its status counts and its semantic summary (`summary`, as
    `semantic.py` computes it)."""
    from .moddocs import stale_doc_message
    from .semantic import text
    from .simple import view_summary
    for n in body.get("notes", []):
        print(f"note: {n}")
    for d in body.get("module_docs", []):
        print(f"warning: {stale_doc_message(d)}")
    from . import numbering as nb
    for o in (body.get("numbering") or {}).get("references", []):
        if nb.suspect(o):
            print(f"warning: {nb.message(o)}")
    for s, k in sorted(view_summary(body).items()):
        print(f"  {k:4d}  {s}")
    for line in text(summary):
        print(line)
    from .semantic import in_text, reading_words
    for c in body.get("claims", []):
        cor = c.get("correspondence") or {}
        if cor.get("basis") == "reviewed_composition":
            # The reading's own coverage and basis: a composition may cover part of the claim,
            # or state it differently.
            words = reading_words(cor.get("coverage"), cor["basis"]) or "no coverage recorded"
            print(f"composition {c.get('number') or c['id']}: {in_text(words)}, which Lean has "
                  f"not checked. Next step: {cor['next_step']}")


# -- output -----------------------------------------------------------------------------------

def _print_json(obj, ensure_ascii: bool = False) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=ensure_ascii))


def _text_arg(v: str | None) -> str:
    if v is None:
        return ""
    return sys.stdin.read() if v == "-" else Path(v).read_text(encoding="utf-8")


def _link_failure(error: dict) -> dict:
    """`link --json` when nothing was recorded: the refusal, or why the command could not run."""
    return {"schema": "machinechecked/link@1", "ok": False, "written": False, "error": error}


def _not_run_json(a, error: dict) -> tuple[dict, bool] | None:
    """What `check`, `inspect` and `link` print with --json when they could not run: a document
    of their own schema with `ok` false and the error, so that a script never reads it as a
    result; with whether it is written in ASCII, as each command's documents are."""
    if not getattr(a, "json", False):
        return None
    if a.cmd == "check":
        return {"schema": "machinechecked/check@1", "ok": False, "error": error,
                "note": "Check unavailable; resolve the execution error and retry."}, True
    if a.cmd == "inspect":
        return {"schema": "machinechecked/inspect@1", "ok": False, "name": getattr(a, "name", None),
                "error": error,
                "note": "Inspection unavailable; resolve the execution error and retry."}, True
    if a.cmd == "link":
        return _link_failure(error), False
    return None


# -- view -------------------------------------------------------------------------------------

def cmd_view(a):
    if _assurance_config(a):
        return _view_full(a)
    _view_simple(a)


def _view_full(a):
    from .pipeline import build
    from .server import serve
    from .workspace import api
    _settings(a, None)
    cfg = _load_full(a)
    try:
        res = build(cfg, web_dist=_web_dist(a.web), reuse_lean=True)
    except RuntimeError:
        res = build(cfg, web_dist=_web_dist(a.web))

    def on_symbol(req):
        from .symbols import from_reader
        from_reader(cfg, req, _web_dist(a.web))

    serve(res["site"], a.port, None, not a.no_browser, on_symbol=on_symbol,
          api=_with_uses(api(cfg.out_dir, res["site"] / "data", cfg.lean_root), cfg.lean_root,
                         res["site"] / "data"))


def _view_simple(a):
    from . import authoring
    from .server import serve
    from .targets import Snapshot
    from .workspace import api
    root, paper = _simple_target(a)
    _settings(a, root)
    print(f"MachineChecked: {paper.relative_to(root)} in {root.name}")
    site, index, view = _simple_site(root, paper, a.web)
    _print_simple(view["body"], index.get("semantic"))
    key = view["body"]["paper"]

    def on_link(req):
        change = authoring.from_reader(root, key, Snapshot(site / "data"), req)
        _simple_site(root, paper, a.web)
        return {"claim": change["claim"], "changed": change["changed"]}

    serve(site, a.port, on_link, not a.no_browser,
          api=_with_uses(api(root / cfgmod.work_dir_name(root), site / "data", root), root,
                         site / "data"))


def _with_uses(api: tuple[dict, dict], root: Path, data: Path) -> tuple[dict, dict]:
    """The local server's routes, with the reader's question of where a declaration is used."""
    from .uses import route
    gets, posts = api
    return {**gets, "/api/uses": route(root, data)}, posts


# -- recording links and investigations -------------------------------------------------------

def cmd_link(a):
    """`machinechecked link CLAIM [DECL ...]`: record, reject or clear a claim's links in the
    links file, checked against the last build (no Lean runs)."""
    from . import authoring
    from .simple import links_key, paper_title
    if _assurance_config(a):
        sys.exit("`link` records the links of the zero-configuration view; a full assessment "
                 "names its declarations in the inventory")
    if a.paper and not re.match(r"https?://", a.paper) and not Path(a.paper).exists():
        from .simple import find_lake_root, find_papers
        root = find_lake_root(Path.cwd().resolve())
        found = [str(f.relative_to(root)) for f in find_papers(root)] if root else []
        sys.exit(f"{a.paper}: no such paper" + (f"; the project's papers: {', '.join(found)}"
                                                 if found else ""))
    root, paper = _simple_target(a)
    snap = _last_build(root / cfgmod.work_dir_name(root), required=True)
    built_title = ((snap.index.get("papers") or [{}])[0]).get("title")
    if built_title != paper_title(paper):
        sys.exit(f"the last build is of another paper ({built_title}); run "
                 f"`machinechecked view {paper.relative_to(root)}` first")
    note = _text_arg(a.note_file) if a.note_file else a.note
    argument = _text_arg(a.argument_file) if a.argument_file else a.argument
    bridge = None
    if a.bridge:
        bridge = {"theorem": a.bridge[0], "target": a.bridge[1]}
        if a.bridge_pins:
            bridge.update(target_fingerprint=a.bridge_pins[0], source_sha256=a.bridge_pins[1])
    elif a.bridge_pins:
        sys.exit("--bridge-pins goes with --bridge THEOREM TARGET")
    try:
        change = authoring.plan(root, links_key(root, paper), snap, a.claim,
                                lean=None if a.route else a.decls or None, add=a.add, reject=a.reject or None,
                                clear=a.clear, note=note, coverage=a.coverage,
                                confidence=a.confidence, reason=a.reason, by=a.reviewer,
                                external=a.external, basis=a.basis, refs=a.refs,
                                argument=argument, bridge=bridge, question=a.question,
                                would_decide=a.would_decide,
                                route=(a.decls or []) if a.route else None)
        if not a.dry_run:
            authoring.write(root, change)
    except authoring.LinkError as e:
        if a.json:
            _print_json(_link_failure(e.to_json()))
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
    from .status import STATUSES
    for d in change["declarations"]:
        shown = (STATUSES.get(d.get("status_code")) or {}).get("label")
        state = {"built": "in the build", "unbuilt": "its module is not built: Lean has not "
                 "checked it", "not loaded": "its module could not be loaded",
                 "external": "not a project declaration: Lean checks it at the next build",
                 "as shown": "kept as the last build shows it" + (f" ({shown})" if shown
                                                                   else "")}
        print(f"  {d['name']}" + (f" ({d['module']})" if d.get("module") else "")
              + f": {state.get(d['build'], d['build'])}")
        if d.get("status_code") == "link.ambiguous":
            print(f"    several modules declare it: give it as MODULE:{d['name']}")
    if not change["changed"]:
        print(f"{c['id']} ({c['number']}): nothing to change")
    elif a.dry_run:
        print(f"{c['id']} ({c['number']}) would become:\n"
              + json.dumps(change["after"], indent=1, ensure_ascii=False))
    else:
        print(f"recorded for {c['id']} ({c['number']}) in {authoring.simple.links_file(root).name}"
              "; `machinechecked view` or `build` shows it")
    if (change["after"] or {}).get("basis") == "reviewed_composition":
        print("a composition: Lean has not checked the combination. Next step: "
              + authoring.simple.COMPOSITION_NEXT_STEP)


def _print_workspace(v: dict) -> None:
    from .estimates import certificate_scope
    from .workspace import ref_text
    print(f"workspace {v['id']} ({v['mode']}), {v['reviewer']}, revision {v['revision']}"
          + (f", made at release {v['release']}" if v.get("release") else ""))
    cur = (v.get("current_sources") or {}).get("release")
    if cur and cur != v.get("release"):
        print(f"  the current build is release {cur}")
    r = v.get("resume") or {}
    if r:
        print("  resume at " + ", ".join(f"{k} {r[k]}" for k in ("claim", "clause", "question")
                                          if r.get(k)))
    m = v.get("main_results")
    if m:
        print("  main results: " + ", ".join(e.get("claim") or e.get("decl")
                                             for e in m["selected"])
              + f" (saved by {m.get('by')} at {m.get('at')})")
        for p in m.get("problems") or []:
            print(f"    {p.get('claim') or p.get('decl')}: {p['problem']}")
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
            fact, cert = ref.get("fact"), ref.get("certificate")
            print(f"  evidence {e['id']}  {e['role']:9} {ref_text(ref)}  "
                  f"[{e['currency']['state']}]"
                  + (f" (module not built)" if ref.get("build") == "unbuilt" else ""))
            if fact:
                print(f"           {fact['basis']}"
                      + (f"; assuming {'; '.join(fact['assumptions'])}"
                         if fact.get("assumptions") else "")
                      + "".join(f"; {c}" for c in fact.get("cases") or []))
            if cert:
                print(f"           {certificate_scope(cert)}")
            for ch in e["currency"].get("changes") or []:
                if ch.get("reason"):
                    print(f"           {ch['reason']}")
            if e["currency"].get("state") == "unchecked" and e["currency"].get("reason"):
                print(f"           not known to be current: {e['currency']['reason']}")
        for f in c["findings"]:
            tag = f["state"] + ("" if f["in_force"] else ", superseded")
            print(f"  finding  {f['id']}  {tag}: coverage {f.get('coverage') or '-'}"
                  + (f", basis {f['basis']}" if f.get("basis") else "")
                  + (f", {f['verdict']}" if f.get("verdict") else "")
                  + (f", {f['difference']['feature']} difference on {f.get('requirement')}"
                     if f.get("difference") else "")
                  + f"  [{f['currency']['state']}]" + (f"  supersedes {f['supersedes']}: "
                                                     f"{f['reason']}" if f.get("supersedes")
                                                     else ""))
            if f.get("question"):
                print(f"           question: {f['question']}")
            if f.get("would_decide"):
                print(f"           would decide it: {f['would_decide']}")
            b = f.get("bridge_check") or {}
            if f.get("basis") == "checked_bridge" and b.get("state") == "checked":
                print(f"           bridge {b.get('theorem')} for {b.get('target')}: "
                      "Lean checks it")
            if f.get("recorded_basis"):
                print(f"           recorded as {f['recorded_basis']}; no bridge Lean checks "
                      "now" + (": " + "; ".join(f["basis_reason"])
                               if f.get("basis_reason") else ""))
            if f.get("basis") == "reviewed_composition":
                from .simple import COMPOSITION_NEXT_STEP
                print("           Lean has not checked this combination. Next step: "
                      + COMPOSITION_NEXT_STEP)
            if f.get("dependencies") is not None:
                from .dependencies import lines as dependency_lines
                print("\n".join(dependency_lines(f["dependencies"], f["currency"])))
        for q in c["questions"]:
            print(f"  question {q['id']}  {q['state']}: {q['text']}")
        for comp in c.get("compositions") or []:
            from .composition import lines as composition_lines
            print("\n".join(composition_lines(comp)))
        rd = c.get("reading") or {}
        if rd.get("requirements") or rd.get("alignments"):
            from .requirements import lines as reading_lines
            print("  requirements:")
            for line in reading_lines(rd):
                print("  " + line)
    rev = v.get("revisions") or {}
    if rev:
        from .reopen import lines as reopened_lines
        for doc in rev.get("maps") or []:
            print("\n".join(reopened_lines(doc)))
        for m in rev.get("other") or []:
            print(f"  a version map of paper {m['paper']} from release "
                  f"{m['from'].get('release')} to release {m['to'].get('release')} is kept; it "
                  f"judges the findings against a build of release {m['to'].get('release')}")


class _Workspaces:
    """What a `workspace` action works on: the working directory and Lean project of the last
    build, that build's site data (`snap`, None before the first build), and the workspace the
    command names (`--id`), else the reviewer's own."""

    def __init__(self, a):
        self.a = a
        self.work, self.root = _built_work(a)
        self.snap = _last_build(self.work)

    def reviewer(self):
        from . import review_cli as rc
        try:
            return rc.parse_reviewer(self.a.reviewer, getattr(self.a, "same_family", "unknown"))
        except rc.ReviewError as e:
            sys.exit(str(e))

    def path(self) -> Path:
        from . import workspace as wsp
        if getattr(self.a, "id", None):
            return wsp.find(self.work, self.a.id)
        return wsp.open_for(self.work, self.reviewer(), getattr(self.a, "mode", None),
                            sources=self.snap.sources() if self.snap else None)


def _workspace_list(a, w: _Workspaces) -> None:
    from . import workspace as wsp
    rows = [wsp.summary(ws) for _, ws in wsp.list_all(w.work)]
    if a.json:
        return _print_json({"schema": "prooflens/workspaces@1", "workspaces": rows})
    for r in rows:
        print(f"{r['id']}  {r['mode']:11} {r['reviewer']}  {r['findings']} finding(s), "
              f"{r['open_questions']} open question(s), {r['reports']} report(s)")
    if not rows:
        print("no workspace yet: `machinechecked workspace open --as human:NAME`")


def _workspace_show(a, w: _Workspaces) -> None:
    """`workspace open` and `workspace show`: a workspace's records per claim, opening the
    reviewer's own when none is named; `show` also checks the Lean facts they cite."""
    from . import workspace as wsp
    if a.action == "open" and a.id and a.mode:
        # Opening by id with another mode is refused by open_for, not changed silently.
        p = wsp.open_for(w.work, w.reviewer(), a.mode, a.id)
    else:
        p = w.path()
    claim = None
    if getattr(a, "claim", None):
        if w.snap is None:
            sys.exit("no build to resolve the claim against: run view or build first")
        claim = w.snap.resolve_claim(a.claim)
    ws = wsp.read(p)
    v = wsp.view(ws, w.snap, claim, w.root, check_facts=a.action == "show")
    if a.action == "show" and ws.get("version_maps"):
        # The findings each version map it keeps reopens, for the maps to this build.
        from .reopen import for_site
        v["revisions"] = for_site(ws, w.snap, w.root, w.work, True, v)
    if a.json:
        return _print_json({**v, "path": str(p)})
    _print_workspace(v)


def _workspace_update(a, w: _Workspaces) -> None:
    from . import workspace as wsp
    raw = json.loads(_text_arg(a.file))
    ops = raw.get("ops") if isinstance(raw, dict) else raw
    op_id = a.op_id or (raw.get("op_id") if isinstance(raw, dict) else None)
    p = w.path()
    _print_json(wsp.update(p, ops, w.snap, w.root, a.reviewer or None, op_id, a.dry_run))


def _workspace_suggest(a, w: _Workspaces) -> None:
    from . import workspace as wsp
    from .requirements import suggestion_ops
    if w.snap is None:
        sys.exit("no build to read the paper from: run view or build first")
    p = w.path()
    cid = w.snap.resolve_claim(a.claim)
    ops = suggestion_ops(wsp.read(p), w.snap, cid, a.requirement)
    if not a.apply:
        return _print_json({"ops": ops})
    if not ops:
        return _print_json({"ok": True, "changed": [], "suggested": 0})
    ack = wsp.update(p, ops, w.snap, w.root, a.reviewer or None, a.op_id)
    _print_json({**ack, "suggested": len(ops)})


def _workspace_export(a, w: _Workspaces) -> None:
    from . import workspace as wsp
    body = wsp.export(w.path())
    Path(a.out).write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"wrote {a.out} (workspace {body['id']}, {body['mode']})")


def _workspace_import(a, w: _Workspaces) -> None:
    from . import workspace as wsp
    res = wsp.import_(w.work, json.loads(_text_arg(a.file)), w.snap, a.reviewer,
                      None if a.file == "-" else Path(a.file).name)
    _print_json(res)
    if res["problems"] or res["conflicts"]:
        raise SystemExit(1)


def _workspace_main(a, w: _Workspaces) -> None:
    """`workspace main [NAME...] [--clear]`: save the main results in the workspace, or show
    those it saves, or, when it saves none, the suggestion `compare --query impact` traces
    from."""
    from . import workspace as wsp
    snap, root, p = w.snap, w.root, w.path()
    if a.names and a.clear:
        sys.exit("machinechecked: give the main results or --clear, not both")
    changed = None
    if a.names or a.clear:
        changed = wsp.update(p, [{"op": wsp.MAIN_OP, "main": [] if a.clear else a.names}], snap,
                             root, a.reviewer or None)["changed"]
    ws = wsp.read(p)
    sel = wsp.main_results_view(ws, snap, root)
    suggested = None
    if sel is None and snap is not None:
        from . import compare as cmp
        from .impact import selection
        site = cmp.Site(snap.data)
        s = selection(site, None, cmp.linked_claims(site))
        suggested = {"rule": s["rule"],
                     "main_results": [{k: e[k] for k in ("name", "claims")}
                                      for e in s["main_results"]]}
    if a.json:
        return _print_json({"workspace": ws["id"], "main_results": sel, "suggested": suggested,
                            **({"changed": changed} if changed is not None else {})})
    if sel is None:
        print(f"workspace {ws['id']} saves no main results; `compare --query impact` traces "
              + (f"the suggestion ({suggested['rule']}):" if suggested else "the suggestion"))
        for e in (suggested or {}).get("main_results") or []:
            print(f"  {e['name']}" + (f"  [{', '.join(e['claims'])}]" if e["claims"] else ""))
        print("save others: machinechecked workspace main NAME... (a claim, for its linked "
              "Lean, or a declaration)")
        return
    from .impact import root_names
    pins = sel.get("pins") or {}
    print(f"workspace {ws['id']}: main results saved by {sel.get('by')} at {sel.get('at')}"
          + (f", against release {pins['release']}" if pins.get("release") else "")
          + (f", project commit {pins['commit'][:7]}" if pins.get("commit") else "") + ":")
    now = ((snap.sources() if snap is not None else {}).get("project") or {}).get("commit")
    if pins.get("commit") and now and now != pins["commit"]:
        print(f"  (this build is of commit {now[:7]})")
    problems = {(p_.get("claim"), p_.get("decl")): p_["problem"] for p_ in sel["problems"]}
    for e in sel["selected"]:
        why = problems.get((e.get("claim"), e.get("decl")))
        if e.get("claim"):
            ch = (snap.chunk(e["claim"]) if snap is not None else None) or {}
            line = f"  {e['claim']}" + (f" ({ch['number']})" if ch.get("number") else "")
            if not why:
                line += ", its linked Lean" if root_names(ch) else ": no Lean is linked to it"
        else:
            line = f"  {e['decl']}" + (f" ({e['module']})" if e.get("module") else "")
        print(line + (f": {why}" if why else ""))
    print("`machinechecked compare --query impact NAME` traces from these")


WORKSPACE_ACTIONS = {"list": _workspace_list, "open": _workspace_show, "show": _workspace_show,
                     "update": _workspace_update, "suggest": _workspace_suggest,
                     "main": _workspace_main, "export": _workspace_export,
                     "import": _workspace_import}


def cmd_workspace(a):
    """`machinechecked workspace ACTION`: the saved investigation (`workspace.py`), as the reader
    saves it. A refused edit prints its conflicts as JSON and exits 1; so does any error of an
    action that prints JSON."""
    from . import workspace as wsp
    from .targets import TargetError
    w = _Workspaces(a)
    try:
        WORKSPACE_ACTIONS[a.action](a, w)
    except wsp.Conflict as e:
        _print_json({"ok": False, "error": str(e), "conflicts": e.conflicts})
        raise SystemExit(1)
    except (wsp.WorkspaceError, TargetError, ValueError) as e:
        if getattr(a, "json", False) or a.action in ("update", "import", "suggest"):
            _print_json({"ok": False, "error": str(e),
                         **({"candidates": e.candidates} if isinstance(e, TargetError) else {})})
            raise SystemExit(1)
        sys.exit(f"machinechecked: {e}")


# -- build and check --------------------------------------------------------------------------

def _site_dest(site: str, root: Path) -> Path:
    """The directory `--site` names, refused when it is the project (or holds it), or when it
    has other content than a previous site: writing the site replaces it."""
    dest = Path(site).resolve()
    if dest == root.resolve() or root.resolve().is_relative_to(dest):
        sys.exit(f"--site {site}: choose a new directory, not the project")
    if dest.exists() and not (dest / "audit.json").exists() and any(dest.iterdir()):
        sys.exit(f"--site {site}: not empty and not a previous site; choose another")
    return dest


def _build_simple(a):
    """`build` in zero configuration: the reader as one HTML file, or with --site a directory to
    publish."""
    from .bundle import bundle
    root, paper = _simple_target(a)
    _settings(a, root)
    site, index, view = _simple_site(root, paper, a.web, a.reuse_lean, a.refresh)
    _print_simple(view["body"], index.get("semantic"))
    if a.site:
        import shutil
        dest = _site_dest(a.site, root)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(site, dest)
        # The workspace records the auditor accepted (published_work.py); a zero-configuration
        # audit publishes its source, Lean and reviews.
        from . import published_work
        from .config import Publish
        everything = Publish(pdf=True, source_text=True, lean=True, reviews=True)
        try:
            published_work.write(dest / "data", site.parent, lambda cid: everything,
                                 site.parent / "sources", root)
        except published_work.PublishError as e:
            shutil.rmtree(dest)
            sys.exit(f"machinechecked: {e}")
        # The semantic summary of what is published, the workspace readings included.
        from . import semantic
        semantic.refresh(dest / "data")
        print(f"wrote the reader to {dest}: publish this directory as it is "
              "(audit.json describes it)")
        return
    # By default inside the working directory, which Git ignores: the file embeds the paper,
    # so putting it where it could be committed takes a deliberate --out.
    out = Path(a.out or (root / cfgmod.work_dir_name(root) / "MachineChecked.html")).resolve()
    res = bundle(site, out, f"MachineChecked — {index['papers'][0]['title']}")
    print(f"wrote {res['out']} ({res['size'] / 1e6:.1f} MB): open it in a browser")
    for o in res["omitted"]:
        print(f"note: left out {o}")


def cmd_check(a):
    if a.json:
        return _check_json(a)
    if _assurance_config(a):
        # The full assessment's check is its build, which exits 1 on a violation.
        return _build_full(a, fix_modules=a.fix_modules, fail_on_violation=True)
    if a.fix_modules:
        sys.exit(NO_MODULES)
    _check_simple(a)


def _check_simple(a):
    """`check` in zero configuration: exit 1 if a linked declaration is missing or not proved."""
    root, paper = _simple_target(a)
    view = _simple_view(root, paper)
    _print_simple(view["body"], _check_summary(view, root)[0])
    bad = [(c["number"], l) for c in view["body"]["claims"]
           for l in c["links"] if l["class"] != "proved"]
    for number, l in bad:
        print(f"FAIL {number} -> {l['name']}: {l['status']}"
              + (f". {l['status_detail']}" if l.get("status_detail") else ""))
    if bad:
        sys.exit(1)
    n = sum(len(c["links"]) for c in view["body"]["claims"])
    if not n:
        print("no claim is linked yet: confirm links in `machinechecked view`")
        return
    print(f"Lean checked all {n} linked declaration(s)")


def _link_detail(l: dict) -> dict:
    """A link's `status_detail`, when the engine gave one: the module that is not built or could
    not be loaded, or the modules that declare an ambiguous name. It adds to the status, which
    stays the engine's."""
    return {"status_detail": l["status_detail"]} if l.get("status_detail") else {}


def _step_json(c: dict) -> dict:
    """A proof step's formal route and its own review, for `check --json`."""
    from .steps import review
    rv = review(c.get("step_reports", []), c.get("source_sha256"))
    return {"route": [{"name": l["name"], "status_code": l["status_code"], **_link_detail(l)}
                      for l in c.get("route_links", [])],
            "step_review": rv["state"],
            "finding": {"verdict": rv["finding"]["verdict"]["value"],
                        "reviewer": rv["finding"]["reviewer"]} if rv["finding"] else None}


CHECK_NOTE = "Results describe the linked Lean declarations; correspondence reviews compare them with the paper."

NO_MODULES = ("--fix-modules: only a project with a machinechecked.toml lists `modules`; "
              "zero configuration reads every built module")


FINDING_KEYS = ("id", "tier", "code", "subject", "message", "trigger", "file", "line",
                "fingerprint", "at", "dismissed", "dismissal_stale", "resolved", "occurrences",
                "occurrences_complete")


def _finding_details(cfg, eid: str) -> list[dict]:
    """The full assessment's findings, as stored with its evidence: what each says and which
    clause or claim it concerns (`subject`), violations first."""
    from . import evidence as ev
    found = ev.load(cfg.out_dir, eid)["body"]["assessment"]["findings"]
    order = {"violation": 0, "obligation": 1, "warning": 2}
    return [{k: f[k] for k in FINDING_KEYS if k in f}
            for f in sorted(found, key=lambda f: (order.get(f.get("tier"), 3), f.get("id", "")))]


def _witness_lists(cfg, eid: str) -> dict[str, dict]:
    """Per claim of the full assessment: the unreviewed declarations only its witnesses use
    (`witness_defs`, with the clause), and for a definition claim the witness-only declarations
    that use a definition it maps (`witness_candidates`). Advice; neither is a status."""
    from . import evidence as ev
    out = {}
    for c in ev.load(cfg.out_dir, eid)["body"]["assessment"]["claims"]:
        wd = [{"clause": cl.get("name"), **e} for cl in c.get("clauses") or []
              for e in cl.get("witness_defs") or []]
        wc = [e for cl in c.get("clauses") or [] for e in cl.get("witness_candidates") or []]
        if wd or wc:
            out[c["id"]] = {**({"witness_defs": wd} if wd else {}),
                            **({"witness_candidates": wc} if wc else {})}
    return out


def _replay_guard(cfg, eid: str) -> dict | None:
    from . import evidence as ev
    from .replay import guard_summary
    return guard_summary(ev.load(cfg.out_dir, eid)["body"]["assessment"])


def _reference_warnings(num: dict | None) -> list[dict]:
    """The references to the paper's numbers that disagree with the paper read here, as
    `check --json` warnings (`kind` `paper-reference`), with their sources."""
    from . import numbering as nb
    return [{"kind": "paper-reference", "file": o["source"].get("file"),
             "line": o["source"].get("line"), "reference": o["reference"],
             "status": o["status"], "id": o["id"], "message": nb.message(o),
             **({"paper": o["attributed"]} if o.get("attributed") else {})}
            for o in (num or {}).get("references", []) if nb.suspect(o)]


def _check_json(a):
    """`check --json`: every claim with its status and links, as one JSON document on stdout
    (progress goes to stderr). Exit 1 if a linked declaration is missing or not proved."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr):
        if _assurance_config(a):
            out, claims, failed = _check_full_json(a)
        else:
            if a.fix_modules:
                sys.exit(NO_MODULES)
            out, claims, failed = _check_simple_json(a)
    summary = {}
    for c in claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    _print_json({"schema": "machinechecked/check@1", "version": tool_version(), **out,
                 "summary": summary, "claims": claims, "ok": not failed, "note": CHECK_NOTE},
                ensure_ascii=True)
    if failed:
        sys.exit(1)


def _check_full_json(a) -> tuple[dict, list[dict], bool]:
    """`check --json` with a machinechecked.toml: the document's fields, its claims, and whether
    the assessment found a violation."""
    cfg, res, added = _assess(a, _load_full(a), a.fix_modules)
    idx = res["index"]
    wit = _witness_lists(cfg, res["evidence"])
    claims = [{"id": c["id"], "paper": c["paper"], "number": c.get("number"),
               "title": c.get("title"), "status": c["status"], "status_code": c["status_code"], "class": c["class"],
               "unit": c.get("unit", "statement"), "parent": c.get("parent"),
               **({"step_review": c["step_review"]} if "step_review" in c else {}),
               **wit.get(c["id"], {})}
              for c in idx["claims"]]
    facts = {c["id"]: c.get("semantic") for c in idx["claims"]}
    for c in claims:
        c["semantic"] = facts.get(c["id"])
    out = {"mode": "full", "release": idx["release"],
           "project": idx.get("project", {}).get("commit"),
           "semantic": idx.get("semantic"),
           "findings": idx["findings"]["total"],
           "finding_details": _finding_details(cfg, res["evidence"]),
           "replay": _replay_guard(cfg, res["evidence"]),
           **({"modules_added": added} if added is not None else {})}
    num = (res.get("content") or {}).get("numbering")
    if num is not None:
        out["warnings"] = _reference_warnings(num)
        out["numbering"] = num
        # With several papers, each paper's references and warnings by themselves.
        if num.get("papers"):
            from .numbering import paper_view
            out["papers"] = {pid: {"warnings": _reference_warnings(paper_view(num, pid)),
                                   "numbering": paper_view(num, pid)}
                             for pid in num["papers"]}
    return out, claims, bool(idx["findings"]["total"].get("violation"))


def _check_simple_json(a) -> tuple[dict, list[dict], bool]:
    """`check --json` in zero configuration: the document's fields, its claims, and whether a
    linked declaration is missing or not proved."""
    from .moddocs import stale_doc_message
    from .simple import view_release
    root, paper = _simple_target(a)
    view = _simple_view(root, paper)
    body = view["body"]
    claims = [{"id": c["id"], "number": c["number"], "title": c["title"],
               "status": c["status"], "status_code": c["status_code"], "class": c["class"],
               "links": [{"name": l["name"], "status": l["status"], "status_code": l["status_code"], "class": l["class"],
                          **_link_detail(l), "source": l.get("source")}
                         for l in c["links"]],
               "correspondence": c.get("correspondence"),
               "reviews": [{"reviewer": r["reviewer"], "verdict": r["verdict"]["value"],
                            "correspondence": r.get("correspondence"),
                            "submitted_at": r["submitted_at"], "current": r["current"],
                            **({"why": r["why"]} if r.get("why") else {})}
                           for r in c.get("reviews", [])],
               "suggestions": [{"name": x["name"], "why": x.get("why"),
                                "reasons": x.get("reasons", [])}
                               for x in c.get("suggestions", [])],
               "references": [o["id"] for o in c.get("references", [])],
               "unit": c.get("unit", "statement"), "parent": c.get("parent"),
               **(_step_json(c) if c.get("unit") else {})}
              for c in body["claims"]]
    summary, facts = _check_summary(view, root)
    for c in claims:
        c["semantic"] = facts.get(c["id"])
    num = body.get("numbering") or {"references": [], "pattern": None}
    out = {"mode": "simple", "paper": body["paper"], "title": body["title"],
           "release": view_release(body), "commit": body.get("commit"),
           "semantic": summary,
           "modules": {"built": body["project"]["built"],
                       "not_built": body["project"]["unbuilt"]},
           "notes": body["notes"],
           "warnings": [{"kind": "module-doc-name", "file": d["file"], "line": d["line"],
                         "name": d["name"], "message": stale_doc_message(d)}
                        for d in body.get("module_docs", [])]
           + _reference_warnings(num),
           "numbering": num}
    return out, claims, any(l["class"] != "proved" for c in claims for l in c["links"])


def _forget_indexes(cfg) -> None:
    """`build --refresh` in a full assessment. Its probe asks Lean afresh on every build without
    `--reuse-lean`; the module indexes and recorded load failures kept in the facts store
    (`facts.py`) are discarded, so the build extracts again whatever it reads from there."""
    from .facts import Store
    st = Store(cfg.lean_root, [], cfg.out_dir / "build", [])
    with st.lock(lambda m: print(m, file=sys.stderr)):
        for kind in ("index", "failed", "attempt"):
            st.drop(kind)


def cmd_build(a):
    if not _assurance_config(a):
        return _build_simple(a)
    _build_full(a, site=a.site, refresh=a.refresh, fail_on_violation=a.fail_on_violation,
                release=a.release, skip_lean=a.skip_lean, skip_tex=a.skip_tex, lake=a.lake,
                lean_build=not a.no_lean_build, reuse_lean=a.reuse_lean)


def _assess(a, cfg, fix_modules: bool = False, **settings):
    """Build and assess `cfg` (`pipeline.build`, with `settings`); with `fix_modules`, add the
    modules the assessment found missing to `modules` and build again (`_fix_modules`). Returns
    the configuration, the build and the modules added (None without `fix_modules`)."""
    from .pipeline import build

    def run(c):
        return build(c, web_dist=_web_dist(a.web), **settings)
    res = run(cfg)
    return _fix_modules(cfg, res, run) if fix_modules else (cfg, res, None)


def _build_full(a, site: str | None = None, refresh: bool = False, fix_modules: bool = False,
                fail_on_violation: bool = False, **settings):
    """`build`, and `check` without --json, with a machinechecked.toml: build and assess
    (`_assess`), print each paper's statuses and what blocks acceptance, and with `site` write
    the audit's public export there. With `fail_on_violation`, exit 1 on a violation."""
    cfg = _load_full(a)
    dest = _site_dest(site, cfg.root) if site else None
    if refresh:
        _forget_indexes(cfg)
    cfg, res, _ = _assess(a, cfg, fix_modules, **settings)
    idx = res["index"]
    for pid, s in idx["summary"].items():
        print(f"paper {pid}:")
        for k, v in sorted(s.items()):
            print(f"  {v:4d}  {k}")
    print("findings:", ", ".join(f"{v} {k}" for k, v in sorted(idx["findings"]["total"].items()))
          or "none")
    from .semantic import text
    for line in text(idx.get("semantic")):
        print(line)
    # Violations and obligations, one per line: they are few, and they block acceptance.
    details = _finding_details(cfg, res["evidence"])
    for f in details:
        if f["tier"] in ("violation", "obligation") and not f.get("dismissed"):
            print(f"  {f['tier']}  {f['subject']}: {f['message']}")
    # Names in module docstrings that nothing declares, names or files review text cites that
    # nothing resolves (with file and line), and the unreviewed declarations only witnesses use.
    for f in details:
        if f["code"] in ("module-doc-name", "review-citation", "witness-def-review") \
                and f["tier"] == "warning" \
                and not f.get("dismissed"):
            print(f"  warning  {f['message']}")
    # The Lean's references to the paper's numbers that disagree with it (`numbering.py`).
    for w in _reference_warnings((res.get("content") or {}).get("numbering")):
        print(f"  warning  {w['message']}")
    if idx["findings"]["total"].get("warning"):
        print("  (warnings: see `check --json` or the reader)")
    whole = [f for f in details if (f.get("dismissed") or {}).get("form") == "statement"]
    if whole:
        print(f"note: {len(whole)} totalisation warning(s) are dismissed by a dismissal of the "
              "operation in the whole statement, which holds until the statement changes; a "
              "dismissal with the warning's `at` and `fingerprint` names one application")
    rg = _replay_guard(cfg, res["evidence"])
    if rg and rg["message"]:
        print(f"note: independent replay: {rg['message']}")
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
    if fail_on_violation and idx["findings"]["total"].get("violation"):
        sys.exit(1)


def _fix_modules(cfg, res, rebuild):
    """`check --fix-modules`: add to `modules` each project module that the assessment of the
    build `res` names as the one module declaring a name the probe did not find
    (`Assessor.not_found`), say what it added, and build again with them. A name that several
    unlisted modules declare adds none. Returns the configuration, the build and the modules
    added."""
    from . import evidence as ev
    found = ev.load(cfg.out_dir, res["evidence"])["body"]["assessment"].get(
        "unlisted_modules") or {}
    names: dict[str, list[str]] = {}
    for name, mods in found.items():
        if len(mods) == 1:
            names.setdefault(mods[0], []).append(name)
        else:
            print(f"--fix-modules: {name} is declared in {', '.join(mods[:-1])} and {mods[-1]}, "
                  "none of which is listed in `modules`: list the one meant")
    try:
        added = cfgmod.add_modules(cfg.path, sorted(names))
    except cfgmod.ConfigError as e:
        whole = cfg.modules + [m for m in sorted(names) if m not in cfg.modules]
        sys.exit(f"{e}; list them by hand: modules = {json.dumps(whole, ensure_ascii=False)}")
    if not added:
        print("--fix-modules: nothing to add to `modules`")
        return cfg, res, []
    print(f"--fix-modules: added to `modules` in {cfg.path.name}:")
    for m in added:
        print(f"  {m}, which declares {', '.join(names[m])}")
    print("--fix-modules: assessing again with them")
    cfg = cfgmod.load(cfg.path)
    return cfg, rebuild(cfg), added


# -- the full assessment's other commands -----------------------------------------------------

def cmd_site(a):
    """`site` writes the reader again from a stored release (`pipeline.rebuild_site`);
    `reassess` first assesses the latest release's evidence again with the current reviews and
    dismissals (`pipeline.reassess`). Neither runs Lean or TeX."""
    from . import pipeline
    write = pipeline.reassess if a.cmd == "reassess" else pipeline.rebuild_site
    res = write(_load_full(a), _web_dist(a.web), a.release)
    print(f"site of release {res['release']} written to {res['site']}")


def cmd_changes(a):
    """`machinechecked changes`: what changed between two releases of the full assessment and
    which evidence that reopens (`changes.py`). It reads stored evidence and changes nothing."""
    from . import changes as chg
    from . import evidence as ev
    from .util import read_json
    cfg = _load_full(a, "`changes` compares releases of the full assessment: run it beside "
                        "machinechecked.toml (or pass -c)")
    if a.map:
        return _changes_map(a, cfg)
    if a.paper or a.match or a.save:
        sys.exit("--paper, --match and --save belong to the version map: add --map")
    try:
        doc = chg.between(cfg.out_dir, a.from_release, a.to_release)
    except chg.ChangesError as e:
        sys.exit(str(e))
    if a.from_source or a.to_source:
        recs = [ev.load(cfg.out_dir, read_json(cfg.out_dir / "releases" / f"{r}.json")
                        ["evidence"]) for r in (doc["from"]["release"], doc["to"]["release"])]
        chg.with_texts(doc, recs[0], recs[1], a.from_source, a.to_source)
    if a.workspace:
        from . import workspace as wsp
        snap = _last_build(cfg.out_dir)
        if snap is None:
            sys.exit("no site of the later release: run `machinechecked site --release "
                     f"{doc['to']['release']}` first")
        if snap.index.get("release") != doc["to"]["release"]:
            sys.exit(f"the site is of release {snap.index.get('release')}, not "
                     f"{doc['to']['release']}: the workspace is checked against the site; run "
                     f"`machinechecked site --release {doc['to']['release']}` first")
        try:
            ws = wsp.read(wsp.find(cfg.out_dir, a.workspace))
        except wsp.WorkspaceError as e:
            sys.exit(str(e))
        doc["workspace"] = chg.workspace_due(wsp.view(ws, snap, None, cfg.lean_root), ws["id"])
    if a.json:
        return _print_json(doc)
    print(chg.text(doc, a.all))


def _changes_map(a, cfg):
    """`machinechecked changes --map`: the version map of a paper between two releases
    (`version_map.py`): each claim of the earlier revision matched to the later one by its
    passage, with both sides' facts; with `--workspace`, the workspace's findings it reopens
    (`reopen.py`). It reads stored evidence and the manuscripts, and changes nothing but, with
    `--save`, the version maps the workspace keeps."""
    from . import version_map as vm
    resolve = []
    for m in a.match:
        old, sep, new = m.partition("=")
        if not (sep and old and new):
            sys.exit(f"--match {m}: give it as EARLIER=LATER, an earlier and a later claim id")
        resolve.append((old, new))
    ws = path = None
    if a.workspace:
        from . import workspace as wsp
        try:
            path = wsp.find(cfg.out_dir, a.workspace)
            ws = wsp.read(path)
        except wsp.WorkspaceError as e:
            sys.exit(str(e))
    elif a.save:
        sys.exit("--save keeps the version map in a workspace: add --workspace ID")
    from . import reopen as ro
    try:
        paper = vm._paper(cfg, a.paper)
        doc = vm.between(cfg, paper.id, a.from_release, a.to_release, a.from_source,
                         a.to_source, resolve, ro.regions_of(ws, paper.id) if ws else ())
    except (ValueError, RuntimeError, OSError) as e:
        sys.exit(f"changes --map: {e}")
    if ws is not None:
        _map_workspace(cfg, doc, ws, path, a.save)
    if a.json:
        return _print_json(doc)
    print(vm.text(doc, a.all))
    if ws is not None:
        print()
        print("\n".join(ro.lines(doc["workspace"])))
        if a.save:
            print(f"  kept the version map in workspace {ws['id']}: the reader's Details page, "
                  "`workspace show` and its export judge its findings with it")


def _map_workspace(cfg, doc: dict, ws: dict, path: Path, save: bool) -> None:
    """`changes --map --workspace ID`: the workspace's findings judged across the version map
    `doc` (`reopen.py`), their Lean side against the later release's site when it is built, as
    `doc['workspace']`; with `save`, the map kept in the workspace."""
    from . import reopen as ro
    from . import workspace as wsp
    snap = _last_build(cfg.out_dir)
    if snap is not None and snap.index.get("release") != doc["to"].get("release"):
        snap = None
    view = wsp.view(ws, snap, None, cfg.lean_root) if snap is not None else None
    doc["workspace"] = ro.reopen(doc, ws, snap, cfg.lean_root, ro.lean_texts(cfg.out_dir, doc),
                                 view=view)
    if save:
        try:
            wsp.update(path, [{"op": "version-map", "map": doc}], snap, cfg.lean_root)
        except wsp.WorkspaceError as e:
            sys.exit(f"changes --map --save: {e}")


def cmd_bundle(a):
    from .bundle import bundle
    cfg = _load_full(a)
    site = Path(a.site).resolve() if a.site else cfg.out_dir / "site"
    res = bundle(site, Path(a.out).resolve(), a.title)
    print(f"wrote {res['out']}: {res['size'] / 1e6:.1f} MB, {res['files']} data files, "
          f"{res['pdfs']} PDFs; open it in a browser, no server needed")
    for o in res["omitted"]:
        print(f"note: left out {o}")


def cmd_export(a):
    from .export import ExportError, export
    cfg = _load_full(a)
    try:
        res = export(cfg, Path(a.out).resolve(), a.release,
                     None if a.data_only else _web_dist(a.web), paper=a.paper)
    except ExportError as e:
        sys.exit(str(e))
    print(f"exported release {res['release']} to {res['out']}")


def cmd_evidence(a):
    """`machinechecked evidence list|prune`: the full assessment's stored evidence, one file per
    build, and deleting what no release still needs with the releases that name it
    (`evidence.prune`)."""
    cfg = _load_full(a, "`evidence` manages the full assessment's stored evidence: run it beside "
                        "machinechecked.toml (or pass -c)")
    (_evidence_list if a.action == "list" else _evidence_prune)(a, cfg.out_dir)


def _mb(n: int) -> str:
    return f"{n / 1e6:.1f} MB"


def _evidence_list(a, out: Path) -> None:
    from . import content as content_mod
    from . import evidence as ev
    from .util import read_json
    rels = [read_json(p) for p in ev.releases(out)]
    gone = ev.pruned_releases(out)
    if not rels and not gone:
        print("no release: run `machinechecked build` first")
        return
    latest = (ev.latest(out) or {}).get("release")
    size = lambda eid: sum(f.stat().st_size for f in (out / "evidence" / f"{eid}.json",
                                                      content_mod.path(out, eid))
                           if f.exists())
    for r in sorted(rels + list(gone.values()), key=lambda r: str(r.get("created") or ""),
                    reverse=True):
        eid = r["evidence"]
        if r["release"] in gone:
            state = ("evidence missing, release pruned on " if r["missing"] else
                     "evidence pruned on ") + r["pruned"][:10]
        elif (out / "evidence" / f"{eid}.json").exists():
            state = _mb(size(eid)) + ("  (latest)" if r["release"] == latest else "")
        else:
            state = "evidence " + ev.absence(out, eid).removeprefix("is ")
        print(f"{r['release']}  evidence {eid[:12]}  {r.get('created', '')}  {state}")
    stored = {p.stem for d in ("evidence", "content") for p in (out / d).glob("*.json")}
    loose = stored - {r["evidence"] for r in rels}
    print(f"{len(stored)} evidence record(s) on disk, {_mb(sum(size(e) for e in stored))} with "
          "their content" + (f"; no release names {len(loose)} of them" if loose else ""))
    print("`machinechecked evidence prune --dry-run` lists what pruning would delete")


def _evidence_prune(a, out: Path) -> None:
    from . import evidence as ev
    res = ev.prune(out, a.keep, dry_run=a.dry_run)
    verb = "would delete" if a.dry_run else "deleted"
    for eid, names in res["deleted"].items():
        print(f"{verb} {eid[:12]}" + (f" and release {', '.join(names)}" if names else ""))
    for eid, why in res["kept"].items():
        print(f"kept {eid[:12]}: {'; '.join(why)}")
    names = sum(len(n) for n in res["deleted"].values())
    print(f"{verb} {len(res['deleted'])} evidence record(s) and {names} release(s), "
          f"{_mb(res['bytes'])}")


# -- further commands -------------------------------------------------------------------------

def cmd_cache(a):
    from . import cache
    if a.action == "prune":
        cache.prune(a.repo, a.keep, log=lambda m: print(m, file=sys.stderr))
        return
    project = _lean_root(a.project)
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
    cfg = _load_full(a)
    out = Path(a.out).resolve() if a.out else cfg.comparator_log
    if out is None:
        sys.exit("say where to write the record: --out FILE, or `comparator_log` in "
                 "machinechecked.toml (which the assessment then reads)")
    rec = replay(cfg.lean_root, Path(a.comparator_config).resolve(), out, a.comparator,
                 guard=not a.no_guard)
    how = rec["conditions"]
    print(f"Comparator {'passed' if rec['passed'] else 'did not pass'} on commit "
          f"{rec['commit'][:12]}: {len(rec['replayed'])} theorem(s) replayed"
          + (" under the sandbox guard" if how["guard"] != "none" else "")
          + f"; record in {out}")
    if how["guard"] == "none":
        why = ("--no-guard was given" if how["guard_mode"] == "opted-out" else
               "this machine cannot start it: it needs `systemd-run` and a user systemd manager "
               "that applies RestrictAddressFamilies")
        print(f"note: replayed without the sandbox guard ({why}); the replay still counts, and "
              "the record and the audit say so. See `machinechecked replay --help`.",
              file=sys.stderr)
    if how["landrun"] is None:
        print("note: no `landrun` was found; the record says so.", file=sys.stderr)
    if not rec["passed"]:
        sys.exit(1)


def cmd_inspect(a):
    from .deps import inspect
    root = _lean_root(a.project)
    log = (lambda m: print(m, file=sys.stderr))
    if a.within and not a.used_by:
        sys.exit("--in goes with --used-by: the applications of NAME inside one declaration")
    if a.used_by:
        from .uses import text, uses
        out = uses(root, a.name, a.module, log=log, refresh=a.refresh, within=a.within)
        if a.json:
            _print_json(out)
        else:
            print(text(out, module=a.module))
        if not out["ok"]:
            sys.exit(1)
        return
    out = inspect(root, a.name, a.module, log=log, refresh=a.refresh)
    if not a.dependencies and out.get("closure"):
        out["closure"] = {k: v for k, v in out["closure"].items() if k != "members"}
    if a.json:
        _print_json(out)
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
    if d.get("statement_note"):
        print(f"  ({d['statement_note']})")
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
    cfg = _load_full(a)
    try:
        if a.action == "add":
            ln = sy.add(cfg, a.claim, a.tex, a.decl, a.reviewer, var=a.var, type_of=a.type_of,
                        term=a.term, at=a.at, occurrence=a.occurrence,
                        paper_object=a.paper_object)
            print(f"linked {sy.symbol_text(ln['symbol'])} in {a.claim} to {ln['lean']} "
                  f"(by {ln['by']}); rebuild the site to show it")
        elif a.action == "remove":
            print(f"removed {sy.remove(cfg, a.claim, a.tex, a.paper_object)} link(s)")
        else:
            print(sy.listing(cfg))
    except (sy.SymbolError, OSError) as e:
        sys.exit(f"machinechecked: {e}")


def cmd_serve(a):
    cfg = _load_full(a)
    site = Path(a.dir).resolve() if a.dir else cfg.out_dir / "site"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    print(f"serving {site} on http://127.0.0.1:{a.port}")
    http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler).serve_forever()


def cmd_compare(a):
    """`compare CLAIM`: a claim's comparison packet; `compare --query OP TARGET`: a targeted
    query (`compare.py`). Both read the last build and change nothing."""
    from . import compare as cmp
    work, root = _built_work(a)
    try:
        site = cmp.Site(work / "site" / "data")
        if a.query:
            op, target = a.query
            out = cmp.query(site, op, target, a.limit, a.after, root,
                            log=lambda m: print(m, file=sys.stderr), match=a.match,
                            workspace=a.workspace, main=a.main,
                            every_library=a.all_libraries, within=a.within)
            if a.json:
                return _print_json(out)
            if not out["available"]:
                print(out["reason"])
                return
            if op == "uses":
                from .uses import text
                claims = cmp.linked_claims(site)
                for r in out["results"]:
                    print(text(r, claims))
                return
            if op == "impact":
                from .impact import text as impact_text
                for r in out["results"]:
                    print(impact_text(r))
                return
            if op == "search":
                print(cmp.search_text(out))
                return
            if op == "proof-facts":
                print(cmp.proof_facts_text(out))
                return
            if op == "composition":
                from .composition import lines as composition_lines
                for c in out["results"]:
                    print(f"{c['workspace']} ({c['mode']}), {c['reviewer']}:")
                    print("\n".join(composition_lines(c)))
                if not out["results"]:
                    print(f"no composition is recorded for {out['subject']['claim']}")
                return
            for r in out["results"]:
                print("\n".join(cmp.statement_lines(r)) if "statement" not in r
                      or isinstance(r.get("statement"), dict) else
                      f"{r['name']}: {r['statement']}" + ("" if r.get("complete") else " …"))
            if out["retrieval"]["next"]:
                print(f"(more: --after {out['retrieval']['next']})")
            return
        if not a.claim:
            sys.exit("name a claim (its id, key or number), or give --query OP TARGET")
        reading = None
        if a.workspace:
            from . import workspace as wsp
            from .targets import Snapshot
            cid = site.resolve_claim(a.claim)
            try:
                ws = wsp.read(wsp.find(work, a.workspace))
            except wsp.WorkspaceError as e:
                raise cmp.CompareError(str(e), "unknown-workspace") from None
            v = wsp.view(ws, Snapshot(work / "site" / "data"), cid, root)
            from .objects import derivations
            reading = {"workspace": ws["id"], "reviewer": v["reviewer"], "mode": v["mode"],
                       **((v["claims"].get(cid) or {}).get("reading")
                          or {"requirements": [], "witnesses": [], "alignments": [],
                              "questions": []}),
                       "compositions": (v["claims"].get(cid) or {}).get("compositions") or [],
                       "derivations": derivations((v["claims"].get(cid) or {}).get("evidence"))}
        out = cmp.claim_packet(site, a.claim, a.stage, a.limit, a.after, reading)
    except cmp.CompareError as e:
        if e.kind in ("no-build", "no-project") and not a.json:
            sys.exit(f"machinechecked: {e}")
        if a.json:
            _print_json({"schema": cmp.PACKET_SCHEMA if not a.query else cmp.QUERY_SCHEMA,
                         "ok": False, "error": e.to_json()})
            raise SystemExit(2 if e.kind in ("no-build", "no-project") else 1)
        print(f"machinechecked: {e}" + (f" (did you mean: {', '.join(map(str, e.candidates))})"
                                         if e.candidates else ""), file=sys.stderr)
        raise SystemExit(1)
    if a.json:
        return _print_json(out)
    print(cmp.packet_text(out))
    nxt = (out["retrieval"].get("definitions") or {}).get("next")
    if nxt:
        print(f"\n(more definitions: --after {nxt})")


# -- review -----------------------------------------------------------------------------------

def _review_here(s) -> dict:
    """The workspace a review session keeps its work in (no id until the first step saves it)."""
    return {"id": s.workspace["id"] if s.path.exists() else None, "mode": s.mode}


def _review_next(a, s) -> None:
    here = _review_here(s)
    u = next(iter(s.open_units(a.order)), None)
    if a.json:
        _print_json({"schema": "machinechecked/review-next@1",
                     "release": s.index["release"], "mode": s.queue.get("mode"),
                     "workspace": here, "order": a.order,
                     "unit": u and {k: u.get(k) for k in ("id", "kind", "reason", "priority")}})
        return
    print(f"{u['id']}  ({u['reason']})" if u else "nothing left to review")
    for sig in ((u or {}).get("priority") or {}).get("signals") or []:
        for q in sig.get("questions") or []:
            print(f"  question: {q}")


def _review_status(a, s) -> None:
    here = _review_here(s)
    units = s.open_units(a.order)
    if a.json:
        _print_json({"schema": "machinechecked/review-status@1",
                     "release": s.index["release"], "mode": s.queue.get("mode"),
                     "workspace": here, "reports": len(s.work["reports"]),
                     "drafts": {i: d["stage"] for i, d in s.work["drafts"].items()},
                     "order": {"by": a.order, **({"queue": s.queue["order"]}
                                                 if s.queue.get("order") else {}),
                               **({"informed": s.order_record} if s.order_record else {})},
                     "open": [u["id"] for u in units]})
        return
    print(f"{len(s.work['reports'])} report(s), {len(s.work['drafts'])} in progress, "
          f"{len(units)} unit(s) left to review (release {s.index['release']})")
    if here["id"]:
        print(f"  workspace {here['id']} ({here['mode']}"
              + ("; your readings here are not blind" if s.informed else "") + ")")
    for uid, d in s.work["drafts"].items():
        print(f"  {uid}: at step '{d['stage']}'")
    for name, sig in [*((s.queue.get("order") or {}).get("signals") or {}).items(),
                      *(s.order_record or {}).items()]:
        if sig.get("state") != "read":
            print(f"  order: {name} {sig['state']}: {sig.get('why')}")


def _review_text(a, s) -> None:
    """`review read`, `show` and `author`: what that step of the protocol shows of a unit."""
    out = getattr(s, a.action)(a.unit, a.json)
    _print_json(out) if a.json else print(out)


def _review_lock(a, s) -> None:
    s.lock(a.unit, _text_arg(a.text))
    print(f"reading recorded (not blind: the session is informed); `review show {a.unit}` "
          "shows the Lean" if s.informed else
          f"reading locked; `review show {a.unit}` shows the Lean")


def _review_decide(a, s) -> None:
    s.decide(a.unit, a.verdict, _text_arg(a.comparison), _text_arg(a.detail),
             _text_arg(a.witness),
             {"coverage": a.coverage, "basis": a.basis,
              "argument": _text_arg(a.argument),
              "bridge": dict(zip(("theorem", "target"), a.bridge)) if a.bridge else None,
              "would_decide": _text_arg(a.would_decide)})
    print(f"verdict recorded; `review author {a.unit}` shows the author's review")


def _review_submit(a, s) -> None:
    r = s.submit(a.unit, _text_arg(a.text).strip())
    print(f"report recorded: {r['unit']['id']}, {r['verdict']['value']}; "
          "`review export --out FILE` writes your reports for the maintainer")


def _review_export(a, s) -> None:
    print(f"wrote {s.export(Path(a.out))}")


# The protocol's steps, for a reviewer without a browser (`review_cli`), with what each does.
REVIEW_STEPS = {
    "next": (_review_next, "the next unit to review"),
    "read": (_review_text, "step 1: the paper's statement of a unit"),
    "lock": (_review_lock, "lock your reading (a file, or - for standard input)"),
    "show": (_review_text, "step 2, after lock: the unit's Lean"),
    "decide": (_review_decide, "record your verdict and comparison"),
    "author": (_review_text, "step 3, after decide: the author's review"),
    "submit": (_review_submit, "record your disagreements with it and finish the report"),
    "status": (_review_status, "your progress on this release's queue"),
    "export": (_review_export, "write your reports as one file, for the maintainer"),
}


def cmd_review_step(a):
    """One step of the review protocol, in the reviewer's session (`review_cli.Session`). A step
    that could not be taken exits 2; with --json, it also prints the refusal as a document."""
    from . import review_cli as rc
    work, root = _built_work(a)
    try:
        s = rc.Session(work, rc.parse_reviewer(a.reviewer, a.same_family), a.workspace, a.mode,
                       root=root)
        REVIEW_STEPS[a.action][0](a, s)
    except rc.ReviewError as e:
        if a.json:
            _print_json({"schema": "machinechecked/review-error@1", "ok": False,
                         "error": e.to_json()})
        sys.exit(f"machinechecked: {e}")
    except OSError as e:
        sys.exit(f"machinechecked: {e}")


def cmd_review_promote(a):
    import shlex
    import subprocess
    from . import promote as pr
    from .pipeline import reassess
    cfg = _load_full(a)
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
        if pr.coverage_text(r):
            head += f"; coverage: {pr.coverage_text(r)}"
        if why:
            print(f"REFUSED  {head}")
            for w in why:
                print(f"           - {w}")
        else:
            print(f"OK       {head}\n           "
                  f"{pr.marker(r, cur, pr.report_source(r))}")
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


INVENTORY = {"regions": "source_regions", "repin": "repin", "rebound": "rebound",
             "retire": "retire"}


def cmd_inventory(a):
    """Run one of the inventory's source-pin commands, with the configuration found here when
    none is given."""
    import importlib
    rest = list(a.rest)
    if not any(x == "--config" or x.startswith("--config=") for x in rest):
        rest = ["--config", str(_config_arg(a))] + rest
    module = importlib.import_module(f".{INVENTORY[a.action]}", __package__)
    sys.exit(module.main(rest))


def cmd_validate(a):
    validate(json.loads(Path(a.file).read_text()), a.schema)
    print(f"{a.file}: valid {a.schema}")


# -- the command line -------------------------------------------------------------------------

PAPER_HELP = ("the paper: a .tex (its LaTeX root), a .pdf, or a URL of a PDF; found in the "
              "project when not given")


def _command(sub, name: str, **kw) -> argparse.ArgumentParser:
    """A command's parser, opening its `--help` with what it does (`COMMANDS`); `--help` lists
    it only when it is an everyday command."""
    if next(g for g, n, _ in COMMANDS if n == name) == EVERYDAY:
        kw.setdefault("help", _summary(name))
    kw.setdefault("description", _summary(name))
    return sub.add_parser(name, **kw)


def _config_option(p, shown: bool = True) -> None:
    """-c CONFIG: the full assessment's configuration. The everyday commands find it, so they
    do not list it."""
    p.add_argument("-c", "--config", default=None,
                   help="the full assessment's configuration (default: machinechecked.toml here)"
                   if shown else argparse.SUPPRESS)


def _reviewer_option(p) -> None:
    p.add_argument("--as", dest="reviewer", default=os.environ.get("MACHINECHECKED_REVIEWER"),
                   help="human:NAME or llm:MODEL (default: $MACHINECHECKED_REVIEWER)")


def _reader_options(p) -> None:
    """`view` and `build`: the paper, and what the reader says about the audit."""
    p.add_argument("paper", nargs="?", help=PAPER_HELP)
    p.add_argument("--issues", metavar="OWNER/REPO",
                   help="the GitHub repository where the reader's Report issue opens reports")
    p.add_argument("--site-url", help="the public address of the published reader, "
                   "for links to claims")
    p.add_argument("--author", help="the name the audit is published under (in audit.json)")
    p.add_argument("--private-repository", action=argparse.BooleanOptionalAction, default=None,
                   help="the Lean repository is private: the reader does not show its name "
                   "(its source links still name it, and open only for people with access)")


def _add_view(sub) -> None:
    w = _command(sub, "view")
    _reader_options(w)
    _config_option(w, shown=False)
    w.add_argument("--port", type=int, default=8017)
    w.add_argument("--no-browser", action="store_true")
    w.add_argument("--web", help=argparse.SUPPRESS)
    w.set_defaults(func=cmd_view)


def _add_build(sub) -> None:
    b = _command(sub, "build")
    _reader_options(b)
    b.add_argument("--out", help="the HTML file (default: .machinechecked/MachineChecked.html, "
                   "which Git ignores; it embeds the paper)")
    b.add_argument("--site", metavar="DIR", help="write the reader as a directory to publish "
                   "(for example on GitHub Pages) instead of one HTML file")
    _config_option(b, shown=False)
    b.add_argument("--release", help=argparse.SUPPRESS)
    b.add_argument("--skip-lean", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--skip-tex", action="store_true", help=argparse.SUPPRESS)
    b.add_argument("--lake", default="lake", help=argparse.SUPPRESS)
    b.add_argument("--no-lean-build", action="store_true", help=argparse.SUPPRESS)
    lean_facts = b.add_mutually_exclusive_group()
    lean_facts.add_argument("--reuse-lean", action="store_true",
                            help="use only the stored Lean results, starting no Lean session; "
                                 "stop and say what must be extracted when they do not cover "
                                 "the build")
    lean_facts.add_argument("--refresh", action="store_true",
                            help="ask Lean again for every Lean fact this build reads (the index "
                                 "of each module it indexes, the records of linked and suggested "
                                 "declarations, the modules recorded as failing to load) instead "
                                 "of reusing those kept in .machinechecked/build/facts, and keep "
                                 "the new ones in their place; the other kept facts (inspect "
                                 "answers, the libraries of other papers) stay")
    b.add_argument("--web", help=argparse.SUPPRESS)
    b.add_argument("--fail-on-violation", action="store_true", help=argparse.SUPPRESS)
    b.set_defaults(func=cmd_build)


def _add_check(sub) -> None:
    k = _command(sub, "check")
    k.add_argument("paper", nargs="?", help=PAPER_HELP)
    k.add_argument("--json", action="store_true",
                   help="print every claim's status and links as JSON (for scripts and agents)")
    k.add_argument("--fix-modules", action="store_true",
                   help="with a machinechecked.toml: add to `modules` each project module that "
                        "declares a proposition, proof, witness or definition the claims name "
                        "and the check did not find, then check again")
    _config_option(k, shown=False)
    k.add_argument("--web", help=argparse.SUPPRESS)
    k.set_defaults(func=cmd_check)


def _add_review(sub) -> None:
    rv = _command(sub, "review")
    rvs = rv.add_subparsers(dest="action", required=True)
    pm = rvs.add_parser("promote", help="turn review reports into review markers (maintainer)")
    pm.add_argument("reports", nargs="+", help="files exported from the review queue, or directories of them")
    _config_option(pm)
    pm.add_argument("--yes", action="store_true", help="write without asking")
    pm.add_argument("--accept-same-family", action="store_true",
                    help="accept a model reviewer of the author's family, or of unknown family")
    pm.add_argument("--allow-revealed", action="store_true",
                    help="accept a report whose reviewer had seen the unit's Lean or author's "
                         "review before writing their reading")
    pm.set_defaults(func=cmd_review_promote)
    for name, (_, help_) in REVIEW_STEPS.items():
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
            sp.add_argument("--coverage", help="how far the unit's Lean states the claim, agreeing "
                            "with the verdict: full or partial (a match); partial, changed or "
                            "related (a problem); unresolved (cannot determine)")
            sp.add_argument("--basis", help="how that coverage is supported: direct (one Lean "
                            "statement), reviewed_composition (your argument) or checked_bridge")
            sp.add_argument("--argument", help="a file holding a reviewed composition's argument")
            sp.add_argument("--bridge", nargs=2, metavar=("THEOREM", "TARGET"),
                            help="a checked bridge: one of the unit's theorems, whose type is "
                                 "exactly TARGET")
            sp.add_argument("--would-decide", help="a file holding what would decide an "
                            "unresolved coverage")
        if name == "export":
            sp.add_argument("--out", required=True)
        if name in ("next", "status", "read", "show", "author"):
            sp.add_argument("--json", action="store_true",
                            help="print one JSON document holding only what this step shows")
        else:
            sp.set_defaults(json=False)
        if name in ("next", "status"):
            sp.add_argument("--order", choices=["priority", "document", "informed"],
                            default="priority",
                            help="priority: changed evidence and proof use first (default); "
                                 "document: the paper's order; informed: also what the "
                                 "auditors' workspaces record as open, which records that "
                                 "you have seen prior interpretations")
        _reviewer_option(sp)
        sp.add_argument("--same-family", choices=["yes", "no", "unknown"], default="unknown",
                        help="for a model: whether it is of the statements' author's family")
        sp.add_argument("--workspace", metavar="ID",
                        help="review in this workspace of yours (default: your first one, which "
                             "the review page under `machinechecked view` uses too)")
        sp.add_argument("--mode", choices=["independent", "informed"],
                        help="review in your workspace of this mode, opening one if you have "
                             "none; informed: you have seen the Lean and earlier "
                             "interpretations, so no step is locked and the report says so")
        _config_option(sp)
        sp.set_defaults(func=cmd_review_step)


def _add_link(sub) -> None:
    lk = _command(sub, "link")
    lk.add_argument("claim", help="the claim: its id or key (thm:main), or its number "
                    "(\"Lemma 2.3\", or 2.3 when only one claim has it)")
    lk.add_argument("decls", nargs="*", metavar="DECL",
                    help="the declarations that state it (they replace the confirmed list); "
                    "MODULE:NAME when several modules declare NAME")
    lk.add_argument("--add", action="store_true", help="add DECL to the confirmed list")
    lk.add_argument("--route", action="store_true", help="for a proof step: DECL is the "
                    "different formal route used instead of the printed step (none: clear it)")
    lk.add_argument("--reject", nargs="+", metavar="DECL", help="record suggestions as not this "
                    "claim's")
    lk.add_argument("--reason", help="why they are rejected")
    lk.add_argument("--clear", action="store_true", help="remove the confirmed list (the "
                    "paper's \\lean tags and formalization.yaml apply again)")
    lk.add_argument("--coverage", help="how far the declarations state the claim: full, "
                    "partial, changed, related or unresolved")
    lk.add_argument("--basis", help="how full coverage is supported: direct (one Lean "
                    "statement), reviewed_composition (your argument) or checked_bridge")
    lk.add_argument("--refs", nargs="+", metavar="DECL", help="the linked declarations the "
                    "basis rests on (default: all)")
    lk.add_argument("--argument", help="a reviewed composition's argument")
    lk.add_argument("--argument-file", help="a file holding the argument, or - for standard "
                    "input")
    lk.add_argument("--bridge", nargs=2, metavar=("THEOREM", "TARGET"), help="a checked "
                    "bridge: a linked theorem whose type is exactly TARGET")
    lk.add_argument("--bridge-pins", nargs=2, metavar=("TARGET_FINGERPRINT", "SOURCE_SHA256"),
                    help="the versions of the target and the passage you read (`check --json` "
                    "gives them as correspondence.bridge.current)")
    lk.add_argument("--question", help="an unresolved reading's open question")
    lk.add_argument("--would-decide", help="what would decide the open question")
    lk.add_argument("--confidence", help="high, medium or low")
    lk.add_argument("--note", help="the note on the correspondence")
    lk.add_argument("--note-file", help="a file holding the note, or - for standard input")
    lk.add_argument("--as", dest="reviewer", help="the name the link is recorded under")
    lk.add_argument("--external", action="store_true", help="accept a declaration from a "
                    "dependency, which the project's index does not hold")
    lk.add_argument("--paper", help="the paper (default: the one found)")
    lk.add_argument("--dry-run", action="store_true", help="show the change, write nothing")
    lk.add_argument("--json", action="store_true", help="print one JSON document")
    _config_option(lk, shown=False)
    lk.set_defaults(func=cmd_link)


def _add_workspace(sub) -> None:
    ws = _command(sub, "workspace")
    wss = ws.add_subparsers(dest="action", required=True)
    for name, help_ in {"open": "open or resume your workspace",
                        "list": "the workspaces of this project",
                        "show": "a workspace: evidence, findings and questions per claim",
                        "update": "apply operations (a JSON file, or - for standard input)",
                        "suggest": "propose the passages near a claim that may govern a "
                                   "requirement (printed as operations, or saved with --apply)",
                        "export": "write a workspace as one file",
                        "import": "bring in an exported workspace",
                        "main": "save the paper's main results, which `compare --query impact` "
                                "traces from (without NAME: show them)"}.items():
        sp = wss.add_parser(name, help=help_)
        if name in ("update", "import"):
            sp.add_argument("file", help="a JSON file, or - for standard input")
        if name in ("open", "show", "update", "export", "suggest", "main"):
            sp.add_argument("--id", help="the workspace (default: yours)")
        if name == "main":
            sp.add_argument("names", nargs="*", metavar="NAME",
                            help="a claim (id, key or number; its linked Lean) or a declaration "
                                 "(MODULE:NAME when several modules declare it); they replace "
                                 "the main results saved")
            sp.add_argument("--clear", action="store_true",
                            help="remove the main results saved (impact traces the suggestion "
                                 "again)")
            sp.add_argument("--json", action="store_true")
        if name == "suggest":
            sp.add_argument("--claim", required=True, help="the claim (id, key or number)")
            sp.add_argument("--requirement", required=True,
                            help="the requirement's local id the passages are proposed for")
            sp.add_argument("--apply", action="store_true",
                            help="save the proposals (each stays a proposal until accepted)")
            sp.add_argument("--op-id", help="an identifier of this request")
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
        _reviewer_option(sp)
        sp.add_argument("--same-family", choices=["yes", "no", "unknown"], default="unknown",
                        help=argparse.SUPPRESS)
        _config_option(sp)
        sp.set_defaults(func=cmd_workspace)


def _add_compare(sub) -> None:
    co = _command(sub, "compare")
    co.add_argument("claim", nargs="?", help="the claim: its id (P:thm:main), key (thm:main) or "
                    "number (\"Theorem 2.1\")")
    co.add_argument("--stage", choices=["read", "compare", "informed"], default="informed",
                    help="read: the paper only; compare: and the Lean; informed (default): and "
                    "what people have recorded (notes, reviews, statuses)")
    co.add_argument("--query", nargs=2, metavar=("OP", "TARGET"),
                    help="a targeted query: definition NAME, mentions NAME, dependencies NAME, "
                    "search CLAIM-OR-TEXT (the project's declarations by statement content), "
                    "proof-facts NAME (the facts inside its proof), uses NAME (where it is "
                    "applied, with the source of each premise), composition CLAIM (the "
                    "auditors' compositions for it, with --workspace for one workspace), impact "
                    "NAME (how each main result uses it, and which claims' Lean uses it), "
                    "expansion KEY (a definition at the arguments of one application, by the "
                    "key a statement gives it)")
    co.add_argument("--in", dest="within", metavar="CALLER",
                    help="with uses: only the applications inside this declaration, or the one "
                    "application with this id (app:CALLER:N), each with every local of its "
                    "context")
    co.add_argument("--match", metavar="TEXT",
                    help="with proof-facts: rank the facts by the symbols they share with TEXT")
    co.add_argument("--main", action="append", metavar="NAME",
                    help="with impact: a main result to trace from, a declaration or a claim "
                    "(its linked Lean); repeat for several (default: those `workspace main` "
                    "saved, else the declarations linked to the paper's theorems)")
    co.add_argument("--limit", type=int, help="return at most this many definitions or results")
    co.add_argument("--after", metavar="ID", help="continue a list after this item")
    co.add_argument("--workspace", metavar="ID", help="include this workspace's requirements and "
                    "compositions of the claim (informed stage only); with --query composition, "
                    "only this workspace's; with --query impact, the main results it saves")
    co.add_argument("--all-libraries", action="store_true",
                    help="with --query search: search every library of the project, also those "
                    "the paper's build leaves out because formalization.yaml maps them only to "
                    "other papers (Lean indexes what the facts store does not hold)")
    co.add_argument("--json", action="store_true", help="print one JSON document")
    _config_option(co, shown=False)
    co.set_defaults(func=cmd_compare)


def _add_inspect(sub) -> None:
    ins = _command(sub, "inspect")
    ins.add_argument("name", help="the declaration's full name, e.g. Foo.main_theorem")
    ins.add_argument("--module", help="the module that declares it, when several declare the name")
    ins.add_argument("--dependencies", action="store_true",
                     help="list every declaration of the project it depends on")
    ins.add_argument("--used-by", action="store_true",
                     help="where it is used instead: the declarations that use it, each "
                          "application's arguments and the source of each premise")
    ins.add_argument("--in", dest="within", metavar="CALLER",
                     help="with --used-by: only the applications inside this declaration, or "
                          "the one application with this id (app:CALLER:N), each with every "
                          "local of its context")
    ins.add_argument("--json", action="store_true",
                     help="print one JSON document (for scripts and agents)")
    ins.add_argument("--project", help="the Lean project (default: the one here)")
    ins.add_argument("--refresh", action="store_true", help=argparse.SUPPRESS)
    ins.set_defaults(func=cmd_inspect)


def _add_changes(sub) -> None:
    ch = _command(
        sub, "changes",
        description="Compare two releases of the full assessment (by default the latest and "
        "the one before it): each claim's passage, its Lean statements and definitions, each "
        "build's status, and every review the later build no longer counts, with the change "
        "it depends on and the question a new reading answers. Nothing is changed.")
    _config_option(ch)
    ch.add_argument("--from", dest="from_release", metavar="RELEASE",
                    help="the earlier release (default: the one before --to)")
    ch.add_argument("--to", dest="to_release", metavar="RELEASE",
                    help="the later release (default: the latest)")
    ch.add_argument("--from-source", metavar="DIR",
                    help="the manuscript folder of the earlier revision, to show changed text "
                    "(with --map, also git:REV: the configured folder as committed at REV)")
    ch.add_argument("--to-source", metavar="DIR",
                    help="the manuscript folder of the later revision, to show changed text "
                    "(with --map, also git:REV)")
    ch.add_argument("--workspace", metavar="ID",
                    help="also list this workspace's records that are no longer current (with "
                    "--map: its findings each paper change reopens, with the change and what "
                    "they rest on)")
    ch.add_argument("--save", action="store_true",
                    help="with --map and --workspace: keep the version map in the workspace, for "
                    "the reader, `workspace show` and its export")
    ch.add_argument("--map", action="store_true",
                    help="the version map: match each claim of the earlier paper revision to "
                    "the later one by its passage (unchanged, moved, changed, context-changed, "
                    "removed, new or ambiguous), with each release's own status and reviews; "
                    "the manuscripts are read from --from-source and --to-source, else at each "
                    "release's revision")
    ch.add_argument("--paper", metavar="ID", help="with --map: the paper (needed when the "
                    "configuration has several)")
    ch.add_argument("--match", action="append", default=[], metavar="EARLIER=LATER",
                    help="with --map: the maintainer's match of an earlier claim that no passage "
                    "or label matched to a later claim nothing else is matched to; repeatable")
    ch.add_argument("--all", action="store_true", help="list unchanged claims too")
    ch.add_argument("--json", action="store_true")
    ch.set_defaults(func=cmd_changes)


def _add_inventory(sub) -> None:
    iv = _command(
        sub, "inventory",
        description="regions: hash line pins as regions at the revision they were pinned at "
        "(docs/SOURCE_REGIONS.md); rebound: change the bounds of claims' regions there; repin: "
        "move the claims to a new revision of the paper; retire: remove the readings review markers "
        "record of passages that no longer use their declaration. "
        "Each prints a plan, and changes files only with --write; pass --help after the action "
        "for its options.")
    iv.add_argument("action", choices=sorted(INVENTORY))
    _config_option(iv, shown=False)
    iv.add_argument("rest", nargs=argparse.REMAINDER)
    iv.set_defaults(func=cmd_inventory)


def _add_stored_release(sub) -> None:
    """`site` and `reassess`: the reader again from stored evidence, without Lean or TeX."""
    for name in ("site", "reassess"):
        t = _command(sub, name)
        _config_option(t)
        t.add_argument("--release", help="the release (default: the latest)" if name == "site"
                       else "the name of the release it writes (default: r- and its evidence "
                       "id, or when nothing changed the release it read)")
        t.add_argument("--web", help=argparse.SUPPRESS)
        t.set_defaults(func=cmd_site)


def _add_bundle(sub) -> None:
    n = _command(sub, "bundle")
    _config_option(n)
    n.add_argument("--site", help="the site directory (default: the last build's)")
    n.add_argument("--out", required=True, help="the HTML file")
    n.add_argument("--title", help="the page's title")
    n.set_defaults(func=cmd_bundle)


def _add_export(sub) -> None:
    e = _command(sub, "export")
    _config_option(e)
    e.add_argument("--release", help="the release (default: the latest)")
    e.add_argument("--out", required=True, help="the directory to write")
    e.add_argument("--web", help=argparse.SUPPRESS)
    e.add_argument("--paper", metavar="ID",
                   help="export only this paper: its claims, the declarations they depend on and "
                   "their reviews; the export is also scanned for the other papers' material")
    e.add_argument("--data-only", action="store_true",
                   help="write the audit's data only, without the reader (for a site that "
                   "reads it with its own reader, such as machinechecked.org)")
    e.set_defaults(func=cmd_export)


def _add_serve(sub) -> None:
    s = _command(sub, "serve")
    _config_option(s)
    s.add_argument("--dir", help="the directory to serve (default: the last build's site)")
    s.add_argument("--port", type=int, default=8017)
    s.set_defaults(func=cmd_serve)


def _add_evidence(sub) -> None:
    evp = _command(sub, "evidence", description="List and prune the full assessment's stored "
                   "evidence (one file per build, in .machinechecked/evidence/).")
    evs = evp.add_subparsers(dest="action", required=True)
    eli = evs.add_parser("list", help="each release, newest first, with the size of its "
                         "evidence, or when it was pruned")
    epr = evs.add_parser(
        "prune", help="delete the evidence no release still needs, with its releases",
        description="Delete stored evidence with the release records that name it, keeping the "
        "newest KEEP distinct records (the latest, which `reassess`, `site` and `export` read "
        "and the next build compares with, and the one the latest is compared with), the "
        "evidence of every release given its own name with `build --release NAME`, of the "
        "releases a workspace's version map compares, and what a kept record was "
        "reassessed from. What was pruned is recorded in .machinechecked/pruned.json, so a "
        "comparison with a pruned release says that its evidence was pruned.")
    epr.add_argument("--keep", type=int, default=2,
                     help="how many of the newest evidence records to keep (at least 2; "
                     "default 2)")
    epr.add_argument("--dry-run", action="store_true", help="list what would be deleted")
    for x in (eli, epr):
        _config_option(x)
    evp.set_defaults(func=cmd_evidence)


def _add_symbol(sub) -> None:
    sy = _command(sub, "symbol")
    sys_ = sy.add_subparsers(dest="action", required=True)
    for name in ("add", "remove", "list"):
        p_ = sys_.add_parser(name)
        if name != "list":
            p_.add_argument("claim", help="the claim id, e.g. P:thm:main")
            p_.add_argument("tex", help="the symbol as the paper's TeX writes it, e.g. '\\nu'")
            p_.add_argument("--object", dest="paper_object",
                            help="the object of the paper the symbol's occurrences are (with "
                                 "remove: only that object's link)")
        if name == "add":
            p_.add_argument("--occurrence", type=int, action="append",
                            help="link only this occurrence of the symbol, numbered from 1 in "
                                 "reading order (repeat for several; needs --object)")
            p_.add_argument("decl", help="the claim's Lean statement")
            p_.add_argument("--var", help="the variable it is (a binder's name or index)")
            p_.add_argument("--type-of", dest="type_of", help="the binder whose type it is")
            p_.add_argument("--term", help="the sub-term it is, as WHERE#K: b:<binder>, c (the "
                                           "conclusion) or l:<part>, and the sub-term's number")
            p_.add_argument("--at", help="the sub-term it is, by its identity in the proposition "
                                         "(the `id` the reader's data gives it)")
            _reviewer_option(p_)
        _config_option(p_)
        p_.set_defaults(func=cmd_symbol)


def _add_replay(sub) -> None:
    rp = _command(
        sub, "replay",
        description="Run Comparator (`lake env comparator CONFIG`) in the Lean project and record "
        "the replay. Comparator's trust model asks for a checking environment in which the "
        "solution was not compiled before, `landrun` on PATH, and the whole run under "
        "`systemd-run --user --property=RestrictAddressFamilies=~AF_UNIX`. This command starts "
        "that sandbox guard itself when the machine has `systemd-run` and a user systemd "
        "manager that applies it (or runs directly when it is already under it); --no-guard "
        "opts out. A replay without the guard still counts, and the audit says it was replayed "
        "without the sandbox guard. The record says how the run went: the guard, the systemd "
        "unit, the Landlock ABI, and which comparator, landrun, lean4export and nanoda_bin it "
        "used, with their SHA-256.")
    rp.add_argument("comparator_config", metavar="CONFIG",
                    help="the Comparator configuration (its theorem_names are the proofs "
                    "replayed)")
    _config_option(rp)
    rp.add_argument("--out", help="the record (default: comparator_log in machinechecked.toml)")
    rp.add_argument("--comparator", default="comparator", help="the Comparator program")
    rp.add_argument("--no-guard", action="store_true",
                    help="run Comparator without the systemd-run sandbox guard")
    rp.set_defaults(func=cmd_replay)


def _add_cache(sub) -> None:
    ca = _command(sub, "cache")
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


def _add_validate(sub) -> None:
    v = _command(sub, "validate")
    v.add_argument("file")
    v.add_argument("--schema", required=True,
                   choices=["inventory", "evidence", "manifest-index", "manifest-claim"])
    v.set_defaults(func=cmd_validate)


def _command_list(prog: str) -> str:
    """`help --all`: every command by group, with what it does."""
    import textwrap
    width = max(len(n) for _, n, _ in COMMANDS) + 2
    out, group = [], None
    for g, name, what in COMMANDS:
        if g != group:
            out += ([""] if out else []) + [f"{g}:"]
            group = g
        out += textwrap.wrap(what, 98, initial_indent=f"  {name:<{width}}",
                             subsequent_indent=" " * (width + 2))
    return "\n".join(out + ["", f"`{prog} COMMAND --help` gives a command's options."])


def cmd_help(a, parser: argparse.ArgumentParser, commands: dict) -> None:
    """`help`: the everyday commands, as --help does; with --all, every command; with a command,
    its options, as COMMAND --help does."""
    if a.command:
        if a.command not in commands:
            sys.exit(f"no command {a.command!r}: `{parser.prog} help --all` lists them")
        commands[a.command].print_help()
    elif a.all:
        print(_command_list(parser.prog))
    else:
        parser.print_help()


def _parser() -> argparse.ArgumentParser:
    import textwrap
    name = Path(sys.argv[0]).name
    prog = name if name in ("machinechecked", "prooflens") else "machinechecked"
    further = [n for g, n, _ in COMMANDS if g != EVERYDAY]
    epilog = ("\n\n".join(__doc__.split("\n\n")[1:]).rstrip() + "\n\n"
              + textwrap.fill(f"Further commands: {', '.join(further)}. `{prog} help --all` says "
                              f"what each does, and `{prog} COMMAND --help` gives its options.", 96)
              + "\n`prooflens` is another name for the same command.")
    p = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=epilog)
    p.add_argument("--version", action="version", version=f"%(prog)s {tool_version()}")
    sub = p.add_subparsers(dest="cmd", required=True,
                           metavar="{" + ",".join(n for g, n, _ in COMMANDS if g == EVERYDAY) + "}")
    for add in (_add_view, _add_build, _add_check, _add_review, _add_link, _add_workspace,
                _add_compare, _add_inspect, _add_changes, _add_inventory, _add_stored_release,
                _add_bundle, _add_export, _add_serve, _add_evidence, _add_symbol, _add_replay,
                _add_cache, _add_validate):
        add(sub)
    h = sub.add_parser("help", description="the everyday commands; with --all, every command")
    h.add_argument("command", nargs="?", help="a command: its options")
    h.add_argument("--all", action="store_true", help="every command, with what it does")
    h.set_defaults(func=functools.partial(cmd_help, parser=p, commands=sub.choices))
    return p


def main(argv=None):
    a = _parser().parse_args(argv)
    try:
        a.func(a)
        sys.stdout.flush()  # what is still buffered, so that a closed pipe is handled below
    except SystemExit as e:
        # `sys.exit("message")` is a command that could not do its job; an integer is its result.
        if isinstance(e.code, str):
            _could_not_run(a, "error", e.code.removeprefix("machinechecked: "))
        _flush_output()
        raise
    except BrokenPipeError as e:
        # The output's reader stopped reading (`… | head`); any other broken pipe is unexpected.
        _stop_if_reader_gone()
        _could_not_run(a, "internal", _crash(e))
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
# `build --fail-on-violation`) found a problem, 2 the command could not run; 141 (128 + SIGPIPE)
# the reader of its output stopped reading.
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


def _flush_output() -> None:
    """Write what is still buffered of standard output, stopping quietly if its reader has
    gone (`_stop_if_reader_gone`)."""
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        _stop_if_reader_gone()
        raise


def _stop_if_reader_gone() -> None:
    """Exit quietly if the reader of standard output or error has closed its end
    (`machinechecked … | head`, once `head` has its lines): no message, and the status of a
    program stopped by SIGPIPE, 128 + 13. What is left to write goes to /dev/null, so that
    Python's flush at exit does not fail again. Without `poll` (Windows) a broken pipe is taken
    to be the output's."""
    import select
    import signal
    gone = []
    for stream in (sys.stdout, sys.stderr):
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            continue
        if hasattr(select, "poll"):
            poll = select.poll()
            poll.register(fd, select.POLLOUT)
            if not any(ev & (select.POLLERR | select.POLLHUP) for _, ev in poll.poll(0)):
                continue
        gone.append(fd)
    if gone:
        null = os.open(os.devnull, os.O_WRONLY)
        for fd in gone:
            os.dup2(null, fd)
        raise SystemExit(128 + getattr(signal, "SIGPIPE", 13))


def _could_not_run(a, kind: str, message: str, **extra):
    """Stop with exit 2: the message on stderr and, for `check`, `inspect` or `link` with
    --json, one JSON document on stdout saying the command did not run (`_not_run_json`)."""
    print(f"machinechecked: {message}", file=sys.stderr)
    doc = _not_run_json(a, {"kind": kind, "message": message, **extra})
    if doc is not None:
        _print_json(*doc)
    raise SystemExit(COULD_NOT_RUN)


if __name__ == "__main__":
    main()
