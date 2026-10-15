"""Zero-configuration mode: a paper and the Lean project it sits in, nothing else.

`prooflens view` finds the Lake project and the paper, takes the claims from the compiled paper,
indexes the declarations of the project's own built modules, suggests links, and shows what is
linked. Links the reader confirms are kept in `prooflens.links.json` at the project root, the
only file this mode writes into the repository.

A link says that someone associated a printed claim with a Lean declaration; it is never shown as
a check that the two say the same thing. A suggestion is shown as a suggestion.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from importlib import resources
from pathlib import Path

from . import evidence as ev
from .config import STANDARD_AXIOMS, Config, Paper, Publish
from .probe import fingerprint
from .sources import SourceError, acquire
from .tex import DEFAULT_ENVS, TexError, anchors_for, theorem_envs
from .util import content_id, read_json, sha256_file, write_json

LINKS = "prooflens.links.json"
SKIP_DIRS = {".lake", ".git", ".prooflens", "node_modules", "build", "_build", ".venv"}
DEFINITION_ENVS = {"definition", "assumption", "convention", "hypothesis", "notation"}
ENV_WORDS = {"thm", "theorem", "lem", "lemma", "prop", "proposition", "cor", "corollary",
             "def", "definition", "rem", "remark", "ex", "example", "eq", "ass", "assumption"}


class ViewError(RuntimeError):
    pass


# -- discovery -------------------------------------------------------------------------------

def find_lake_root(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        if (d / "lakefile.toml").exists() or (d / "lakefile.lean").exists():
            return d
    return None


def lib_names(root: Path) -> list[str]:
    """The `lean_lib` names of the project's lakefile."""
    names = []
    t = root / "lakefile.toml"
    if t.exists():
        cfg = tomllib.loads(t.read_text(encoding="utf-8"))
        names = [lib["name"] for lib in cfg.get("lean_lib", [])]
        if not names and cfg.get("name"):
            names = [str(cfg["name"]).capitalize()]
    l = root / "lakefile.lean"
    if l.exists():
        names += re.findall(r"^\s*lean_lib\s+«?([\w.]+)»?", l.read_text(encoding="utf-8"), re.M)
    return list(dict.fromkeys(names))


def built_modules(root: Path, libs: list[str]) -> tuple[list[str], list[str]]:
    """(built, unbuilt) modules of the project's libraries: a module is built when Lake has
    written its `.olean`. Modules are found from the source tree, so modules outside the import
    graph of a library's root are found too."""
    olean = root / ".lake" / "build" / "lib" / "lean"
    if not olean.exists():
        olean = root / ".lake" / "build" / "lib"
    built, unbuilt = [], []
    for lib in libs:
        base = lib.split(".")[0]
        sources = [root / f"{base}.lean"] + sorted((root / base).rglob("*.lean")) \
            if (root / base).is_dir() else [root / f"{base}.lean"]
        for src in sources:
            if not src.exists():
                continue
            mod = ".".join(src.relative_to(root).with_suffix("").parts)
            (built if (olean / src.relative_to(root).with_suffix(".olean")).exists()
             else unbuilt).append(mod)
    return built, unbuilt


def find_papers(root: Path) -> list[Path]:
    """LaTeX roots (files with \\documentclass) of the repository, else its PDFs."""
    tex, pdf = [], []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(dirpath) / f
            if f.endswith(".tex"):
                try:
                    if re.search(r"^[^%\n]*\\documentclass", p.read_text(errors="replace"), re.M):
                        tex.append(p)
                except OSError:
                    pass
            elif f.endswith(".pdf"):
                pdf.append(p)
    # A leanblueprint keeps the plasTeX input `web.tex` beside the LaTeX root `print.tex`.
    tex = [p for p in tex if not (p.name == "web.tex" and (p.parent / "print.tex") in tex)]
    return sorted(tex) or sorted(pdf)


# -- claims from the paper -------------------------------------------------------------------

def claims_from_anchors(pid: str, anchors: list[dict], snap: Path) -> list[dict]:
    claims = []
    for a in anchors:
        env = a["env"]
        num = a.get("number")
        key = a.get("label") or (f"{env}-{num}" if num else f"{env}@{a['file']}:{a['line']}")
        title, tags = "", []
        try:
            lines = (snap / a["file"]).read_text(encoding="utf-8", errors="replace").split("\n")
            title = a.get("title") or ""
            tags = source_tags(lines, a["line"], env)
        except OSError:
            pass
        claims.append({
            "id": f"{pid}:{key}", "key": key, "paper": pid, "kind": env,
            "number": f"{env.capitalize()} {num}" if num else env.capitalize(), "title": title,
            "label": a.get("label"), "location": a["file"], "source_sha256": a["source_sha256"],
            "scope": "definition" if env in DEFINITION_ENVS else "formal",
            "scope_note": "", "scope_reviewed": True, "clauses": [], "tags": tags})
    return claims


def source_tags(lines: list[str], line: int, env: str) -> list[str]:
    """The arguments of the `\\lean{…}` tags in the environment `env` opening on `line`, with
    TeX comments removed (a commented-out tag is no tag)."""
    out, depth = [], 0
    pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
    for l in lines[line - 1:]:
        l = re.sub(r"(?<!\\)%.*", "", l)
        out += re.findall(r"\\lean\{([^}]*)\}", l)
        for m in pat.finditer(l):
            depth += 1 if m.group(1) == "begin" else -1
        if depth <= 0:
            break
    return out


# -- suggestions -----------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return {t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if len(t) > 1}


def suggest(claim: dict, index: list[dict], limit: int = 3) -> list[dict]:
    """Candidate declarations for a claim, best first, each with the reason it is suggested."""
    out: dict[str, dict] = {}
    names = {d["name"]: d for d in index}

    def add(name, score, why):
        if name in names and (name not in out or out[name]["score"] < score):
            out[name] = {"name": name, "score": score, "why": why, "kind": names[name]["kind"]}

    # Name and title resemblance proposes declarations of the claim's own sort: theorems for a
    # theorem, definitions for a definition.
    wants_def = claim["kind"] in DEFINITION_ENVS

    def sort_ok(d):
        return d["kind"] != "theorem" if wants_def else d["kind"] == "theorem"

    number = claim["number"]
    num_re = re.compile(r"\b" + re.escape(number) + r"\b", re.I)
    label = set(_tokens(claim.get("label") or "")) - ENV_WORDS
    words = _tokens(claim.get("title") or "")
    for d in index:
        doc = d.get("doc") or ""
        if doc and num_re.search(doc):
            add(d["name"], 0.9, f"its docstring cites {number}")
        if not sort_ok(d):
            continue
        short = d["name"].rsplit(".", 1)[-1]
        nt = _tokens(short)
        if label and nt:
            j = len(label & nt) / len(label | nt)
            if j >= 0.5:
                add(d["name"], 0.4 + 0.4 * j, "its name resembles the label")
        if words and nt and len(words & nt) >= 2:
            add(d["name"], 0.35, "its name shares words with the title")
    return sorted(out.values(), key=lambda x: -x["score"])[:limit]


def tagged_names(claim: dict) -> list[str]:
    """The declarations a claim's `\\lean{…}` tags name, in order."""
    out = []
    for tag in claim.get("tags", []):
        for n in (t.strip() for t in tag.split(",")):
            if n and n not in out:
                out.append(n)
    return out


def linked_names(claim: dict, entry: dict) -> list[str]:
    """The declarations a claim is linked to: those confirmed in the reader (the links file
    holds the whole list, possibly empty), else those its `\\lean{…}` tags name, less the ones
    rejected in the reader. A tag is a link its author wrote into the paper's source."""
    if "lean" in entry:
        return list(entry["lean"])
    return [n for n in tagged_names(claim) if n not in entry.get("rejected", [])]


# -- links file ------------------------------------------------------------------------------

def load_links(root: Path) -> dict:
    p = root / LINKS
    if not p.exists():
        return {"version": 1, "papers": {}}
    return read_json(p)


def save_link(root: Path, paper: str, key: str, lean: list[str] | None, rejected: list[str]
              | None = None, by: str = "") -> dict:
    """Record (or with `lean=None`, remove) the link of claim `key` of `paper`."""
    data = load_links(root)
    links = data.setdefault("papers", {}).setdefault(paper, {})
    if lean is None and not rejected:
        links.pop(key, None)
    else:
        entry = links.setdefault(key, {})
        if lean is not None:
            entry["lean"] = lean
            entry["at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            if by:
                entry["by"] = by
        if rejected is not None:
            entry["rejected"] = sorted(set(entry.get("rejected", [])) | set(rejected))
    write_json(root / LINKS, data)
    return data


# -- the Lean side ---------------------------------------------------------------------------

def run_simple_probe(root: Path, modules: list[str], libs: list[str], requests: list[dict],
                     lake: str = "lake", timeout: int = 3600) -> list[dict]:
    body = resources.files("prooflens").joinpath("data/ProofLensProbe.lean").read_text()
    header = "import Lean\n" + "".join(f"import {m}\n" for m in modules) + "\n"
    with tempfile.TemporaryDirectory(prefix="prooflens-view-") as tmp:
        tmp = Path(tmp)
        (tmp / "Probe.lean").write_text(header + body)
        (tmp / "query.json").write_text(json.dumps({
            "scope_roots": [l.split(".")[0] for l in libs], "spec_prefix": "",
            "accept_prefix": "", "allowed_axioms": STANDARD_AXIOMS, "requests": requests}))
        env = dict(os.environ, PROOFLENS_QUERY=str(tmp / "query.json"),
                   PROOFLENS_OUT=str(tmp / "out.jsonl"))
        r = subprocess.run([lake, "env", "lean", str(tmp / "Probe.lean")], cwd=root, env=env,
                           capture_output=True, text=True, timeout=timeout)
        out = tmp / "out.jsonl"
        if r.returncode != 0 or not out.exists():
            raise ViewError(f"the Lean probe failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        recs = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
    for rec in recs:
        for d in [rec, rec.get("decl")]:
            if isinstance(d, dict) and "canon" in d:
                d["fingerprint"] = fingerprint(d.pop("canon"))
    return recs


def link_state(rec: dict | None) -> tuple[str, str]:
    """The status of a confirmed link from its probe record, and its class."""
    if rec is None or "missing" in rec.get("errors", []):
        return "linked: Lean declaration not found", "malformed"
    if rec.get("kind") != "theorem":
        return "linked: Lean definition", "proved"
    if rec.get("sorry"):
        return "linked: Lean proof incomplete (sorry)", "open"
    if rec.get("errors"):
        return "linked: Lean proof uses further axioms", "open"
    return "linked: Lean proof checked", "proved"


# -- the whole view --------------------------------------------------------------------------

def tex_machinery_digest() -> str:
    """The digest of what turns LaTeX into anchors: a change to it invalidates cached anchors."""
    h = hashlib.sha256()
    for f in ("data/prooflens.sty", "tex.py"):
        h.update(resources.files("prooflens").joinpath(f).read_bytes())
    return h.hexdigest()[:16]


def tree_digest(d: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def lean_digest(root: Path) -> str:
    """The content of every Lean input of the project and its path dependencies, and whether
    each module is built."""
    import hashlib
    from .pipeline import lean_inputs_digest
    h = hashlib.sha256()
    for f in sorted((root / ".lake" / "build").rglob("*.olean")) if (root / ".lake").exists() \
            else []:
        h.update(str(f.relative_to(root)).encode())
        h.update(str(f.stat().st_mtime_ns).encode())
    fake = type("C", (), {"lean_root": root})()
    h.update(lean_inputs_digest(fake).encode())
    return h.hexdigest()


def view_config(root: Path, paper_path: Path, out_dir: Path, libs: list[str]) -> Config:
    rel = paper_path.relative_to(root)
    source = {"path": str(rel.parent)}
    paper = Paper(id="P", title=paper_title(paper_path), source=source,
                  root=rel.name if paper_path.suffix == ".tex" else None,
                  pdf=rel.name if paper_path.suffix == ".pdf" else None,
                  publish=Publish(pdf=True, source_text=True, lean=True, reviews=True))
    return Config(path=root / "prooflens.toml", name=root.name, lean_root=root,
                  modules=[], scope_roots=[l.split(".")[0] for l in libs], spec_prefix="",
                  accept_prefix="", allowed_axioms=STANDARD_AXIOMS, inventory=root / LINKS,
                  reviews=[], statement_authors=[], ai_reviewers=[], dismissals=None,
                  comparator_log=None, papers=[paper], out_dir=out_dir)


def paper_title(p: Path) -> str:
    if p.suffix == ".tex":
        m = re.search(r"\\title\{([^}]*)\}", p.read_text(errors="replace"))
        if m:
            return re.sub(r"\\\\|\s+", " ", m.group(1)).strip()
    return p.stem


def build_view(root: Path, paper_path: Path, out_dir: Path, lake: str = "lake",
               log=print) -> dict:
    """Everything the reader shows for `paper_path` in the Lean project at `root`."""
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    cfg = view_config(root, paper_path, out_dir, libs)
    paper = cfg.papers[0]
    notes = []

    # The paper.
    snap = acquire(cfg, paper, out_dir / "sources" / paper.id)
    tex, pdf, claims = {"mode": snap.mode}, None, []
    if snap.mode == "latex":
        envs = sorted(set(DEFAULT_ENVS) | set(theorem_envs(snap.dir)))
        # The compiled paper is reused while its sources are unchanged (a link changes nothing
        # in the paper).
        cache = out_dir / "build" / "tex-cache.json"
        digest = tree_digest(snap.dir) + ":" + tex_machinery_digest()
        cached = read_json(cache) if cache.exists() else {}
        try:
            if cached.get("digest") == digest and Path(cached.get("pdf", "")).exists():
                t = {"page_size": cached["page_size"], "anchors": cached["anchors"],
                     "pdf": Path(cached["pdf"])}
            else:
                r = anchors_for(snap, out_dir / "build" / paper.id, envs)
                t = {"page_size": r["page_size"], "anchors": [a.to_json() for a in r["anchors"]],
                     "pdf": r["pdf"]}
                write_json(cache, {"digest": digest, "page_size": t["page_size"],
                                   "anchors": t["anchors"], "pdf": str(t["pdf"])}, indent=None)
            anchors = t["anchors"]
            tex.update(page_size=t["page_size"], anchors=anchors, envs=envs)
            pdf = t["pdf"]
            claims = claims_from_anchors(paper.id, anchors, snap.dir)
        except TexError as e:
            notes.append("the paper did not compile, so its claims are not listed: "
                         + str(e).splitlines()[0])
            tex["mode"] = "pdf"
    if pdf is None and snap.pdf:
        pdf = snap.dir / snap.pdf
    paper_key = str(paper_path.relative_to(root))

    # The Lean project.
    index, linkrecs, decls = [], {}, {}
    links = load_links(root).get("papers", {}).get(paper_key, {})
    if not libs:
        notes.append("no Lean library found in the lakefile")
    elif not built:
        notes.append("the Lean project is not built (run `lake build`); Lean information is "
                     "not shown")
    else:
        if unbuilt:
            notes.append(f"{len(unbuilt)} module(s) of the project are not built and are not "
                         f"indexed")
        # The index is reused while no Lean input of the project changed.
        icache = out_dir / "build" / "index-cache.json"
        idigest = lean_digest(root)
        cached = read_json(icache) if icache.exists() else {}
        if cached.get("digest") == idigest:
            index = cached["index"]
        else:
            log(f"lean: indexing {len(built)} built module(s)")
            recs = run_simple_probe(root, built, libs, [{"kind": "index", "name": ""}], lake)
            index = [r for r in recs if r["record"] == "index"]
            write_json(icache, {"digest": idigest, "index": index}, indent=None)
        wanted = set()
        for c in claims:
            entry = links.get(c["key"], {})
            c["link_names"] = linked_names(c, entry)
            c["suggestions"] = [s for s in suggest(c, index)
                                if s["name"] not in entry.get("rejected", [])
                                and s["name"] not in c["link_names"]]
            wanted |= set(c["link_names"])
            wanted |= {s["name"] for s in c["suggestions"][:1] if s.get("kind")}
        if wanted:
            log(f"lean: checking {len(wanted)} linked or suggested declaration(s)")
            recs = run_simple_probe(root, built, libs,
                                    [{"kind": "link", "name": n} for n in sorted(wanted)], lake)
            linkrecs = {r["name"]: r for r in recs if r["record"] == "link"}
            decls = {r["name"]: r for r in recs if r["record"] == "decl"}

    # Statuses.
    for c in claims:
        entry = links.get(c["key"], {})
        source = "confirmed" if "lean" in entry else "paper"
        c["links"] = []
        for n in c.pop("link_names", None) or linked_names(c, entry):
            status, cls = link_state(linkrecs.get(n)) if built else \
                ("linked: Lean not checked (the project is not built)", "unspecified")
            c["links"].append({"name": n, "status": status, "class": cls, "source": source,
                               "record": linkrecs.get(n)})
        for s in c.get("suggestions", []):
            s["record"] = linkrecs.get(s["name"])
        if c["links"]:
            worst = max(c["links"], key=lambda l: ["proved", "open", "malformed"]
                        .index(l["class"]))
            c["status"], c["class"] = worst["status"], worst["class"]
        elif c.get("suggestions"):
            c["status"], c["class"] = "suggested link, not confirmed", "unspecified"
        else:
            c["status"], c["class"] = "not linked", "unspecified"

    body = {"mode": "simple", "paper": paper_key, "title": paper.title, "notes": notes,
            "project": {"name": root.name, "libs": libs, "built": len(built),
                        "unbuilt": len(unbuilt)},
            "links_sha256": sha256_file(root / LINKS) if (root / LINKS).exists() else None,
            "pdf_sha256": sha256_file(pdf) if pdf else None, "tex": tex,
            "claims": claims, "index": index, "decls": decls}
    return {"body": body, "pdf": pdf, "cfg": cfg}


def write_view_site(view: dict, site: Path, web_dist: Path | None) -> dict:
    """The site of a view: the same app as the full reader, in its simple mode."""
    from . import manifest as mf
    body = view["body"]
    eid = content_id(body)
    release = f"v-{eid[:12]}"
    store = {}
    keys = {}
    for n, d in body["decls"].items():
        rec = {k: v for k, v in d.items() if k != "record"}
        k = mf.record_key(rec)
        keys[n], store[k] = k, rec
    index_claims, chunks = [], {}
    for c in body["claims"]:
        anchor = next((a for a in body["tex"].get("anchors", [])
                       if (a.get("label") or f"{a['env']}-{a.get('number')}") == c["key"]), None)
        fname = mf.claim_file(c["id"])
        top = mf.top_of({**anchor, "kind": "exact"}) if anchor and anchor.get("begin") else None
        index_claims.append({
            "id": c["id"], "paper": c["paper"], "number": c["number"], "title": c["title"],
            "heading": c["title"] or None, "kind": c["kind"], "scope": c["scope"],
            "status": c["status"], "class": c["class"],
            "anchor": {"kind": "exact", "page": top[0], "y0": top[1],
                       "y1": anchor["end"][2] if anchor.get("end") and
                       anchor["end"][0] == anchor["begin"][0] else None,
                       "page_end": anchor["end"][0] if anchor.get("end") else None}
            if top else None,
            "counts": {}, "file": fname, "linked": len(c["links"]),
            "suggested": len(c.get("suggestions", []))})
        names = set()
        for l in c["links"] + c.get("suggestions", []):
            rec = l.get("record") or {}
            names |= set(rec.get("closure", []))
        chunks[fname] = {
            "schema": "prooflens/manifest@0", "mode": "simple", "release": release,
            "id": c["id"], "key": c["key"], "paper": c["paper"], "number": c["number"],
            "title": c["title"], "heading": c["title"] or None, "kind": c["kind"], "scope": c["scope"], "scope_note": "",
            "scope_reviewed": True, "location": c["location"],
            "source_sha256": c["source_sha256"], "status": c["status"], "class": c["class"],
            "anchor": {**anchor, "kind": "exact"} if anchor else None, "source_matches": None,
            "statement_tex": (anchor or {}).get("statement"), "blockers": [],
            "links": [_link_view(l) for l in c["links"]],
            "suggestions": [_link_view(s) for s in c.get("suggestions", [])],
            "clauses": [], "decls": {n: keys[n] for n in sorted(names) if n in keys},
            "findings": []}
    summary = {}
    for c in index_claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    classes = {c["status"]: c["class"] for c in index_claims}
    index = {"schema": "prooflens/manifest@0", "mode": "simple", "release": release,
             "evidence": eid, "created": _dt.datetime.now(_dt.timezone.utc)
             .isoformat(timespec="seconds"),
             "project": {"name": body["project"]["name"]}, "tool": {"name": "prooflens"},
             "lean": None, "notes": body["notes"],
             "papers": [{"id": "P", "title": body["title"], "mode": body["tex"]["mode"],
                         "pdf": "papers/P.pdf" if view["pdf"] else None,
                         "page_size": body["tex"].get("page_size"), "note": ""}],
             "summary": {"P": summary}, "classes": classes,
             "findings": {"total": {}, "general": []}, "gates": {}, "claims": index_claims,
             "search": "data/search.json", "lean_index": "data/lean-index.json",
             "editable": False}
    from .pipeline import write_preview
    from .review_queue import simple_queue
    write_preview(site, index, chunks, store, {"P": view["pdf"]} if view["pdf"] else {},
                  web_dist, simple_queue(index, chunks))
    index["review_queue"] = "data/review-queue.json"
    write_json(site / "data" / "lean-index.json",
               [{"name": d["name"], "kind": d["kind"], "module": d["module"],
                 "type": d["type"][:300], "doc": (d.get("doc") or "")[:300]}
                for d in body["index"]], indent=None)
    return index


def _link_view(l: dict) -> dict:
    rec = l.get("record") or {}
    return {"name": l["name"], "status": l.get("status"), "class": l.get("class"),
            "why": l.get("why"), "source": l.get("source"),
            "fingerprint": rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint"),
            "kind": rec.get("kind") or l.get("kind"),
            "axioms": rec.get("axioms"), "sorry": rec.get("sorry"),
            "errors": rec.get("errors"),
            "statement": {"binders": rec.get("binders", []), "conclusion": rec.get("conclusion"),
                          "closure": rec.get("closure", []), "direct": []} if rec else None,
            "range": (rec.get("decl") or {}).get("range"),
            "module": (rec.get("decl") or {}).get("module"),
            "doc": (rec.get("decl") or {}).get("doc")}
