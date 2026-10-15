"""The build: acquire the papers, run the probe, compile with anchors, assess, store the
evidence, and write the private preview site."""

from __future__ import annotations

import os
import shutil
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import evidence as ev
from . import manifest as mf
from .assess import Assessor
from .config import Config
from .probe import FINGERPRINT_VERSION, requests_from_inventory, run_probe
from .reviews import load_dismissals, load_reviews
from .schemas import validate
from .sources import acquire
from .tex import DEFAULT_ENVS, TexError, anchors_for, theorem_envs
from .assess import line_location
from .util import (git_dirty, git_head, norm_ws, read_json, sha256_file, sha256_text,
                   write_json)


def tool_version() -> str:
    try:
        return version("prooflens")
    except PackageNotFoundError:
        return "0.1.0+src"


def project_provenance(cfg: Config) -> dict:
    lr = cfg.lean_root
    tc = lr / "lean-toolchain"
    lm = lr / "lake-manifest.json"
    prov = {"name": cfg.name, "commit": git_head(cfg.root), "dirty": git_dirty(cfg.root),
            "toolchain": tc.read_text().strip() if tc.exists() else None,
            "lake_manifest_sha256": sha256_file(lm) if lm.exists() else None,
            "dependencies": {}}
    if lm.exists():
        for p in read_json(lm).get("packages", []):
            prov["dependencies"][p.get("name")] = p.get("rev")
    return prov


def build(cfg: Config, release: str | None = None, skip_lean: bool = False,
          skip_tex: bool = False, lake: str = "lake", web_dist: Path | None = None,
          lean_build: bool = True, log=print) -> dict:
    inv = read_json(cfg.inventory)
    validate(inv, "inventory")
    reviews, review_hashes = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    dismissals = load_dismissals(cfg.dismissals)

    lean = None
    if not skip_lean:
        log(f"probe: {len(requests_from_inventory(inv))} requests in {cfg.lean_root}")
        lean = run_probe(cfg, requests_from_inventory(inv), lake=lake, build=lean_build)

    tex, papers_prov, pdfs = {}, {}, {}
    for paper in cfg.papers:
        snap = acquire(cfg, paper, cfg.out_dir / "sources" / paper.id)
        prov = {"title": paper.title, "kind": snap.kind, "revision": snap.revision,
                "mode": snap.mode, "root": snap.root, "note": snap.note,
                "committed_pdf": snap.pdf,
                "committed_pdf_sha256": sha256_file(snap.dir / snap.pdf) if snap.pdf else None}
        t = None
        if snap.mode == "latex" and not skip_tex:
            envs = paper.envs or sorted(set(DEFAULT_ENVS) | set(theorem_envs(snap.dir)))
            log(f"tex: compiling {paper.id} ({snap.root})")
            try:
                t = anchors_for(snap, cfg.out_dir / "build" / paper.id, envs)
            except TexError as e:
                # The sandbox is not weakened to make a document compile: the source's own
                # PDF is used instead, and the paper is marked as not compiled.
                prov["compile_error"] = str(e)[-2000:]
                log(f"tex: {paper.id} did not compile; using its committed PDF if any")
        if t is not None:
            tex[paper.id] = {"mode": "latex", "envs": envs, "page_size": t["page_size"],
                             "inputs": t["inputs"],
                             "anchors": [a.to_json() for a in t["anchors"]]}
            prov["pdf_sha256"] = t["pdf_sha256"]
            prov["pdf_origin"] = "compiled"
            pdfs[paper.id] = t["pdf"]
        elif snap.pdf:
            tex[paper.id] = {"mode": "pdf", "anchors": [], "page_size": None, "inputs": []}
            prov["mode"] = "pdf"
            prov["pdf_sha256"] = prov["committed_pdf_sha256"]
            prov["pdf_origin"] = "committed"
            pdfs[paper.id] = snap.dir / snap.pdf
        if paper.id in tex:
            tex[paper.id]["lines"] = line_hashes(inv, paper.id, snap.dir)
        papers_prov[paper.id] = prov

    comp = cfg.comparator_log
    comp_text = comp.read_text(errors="replace") if comp and comp.exists() else None
    assessment = Assessor(cfg, inv, lean, tex, reviews, dismissals, comp_text,
                          git_head(cfg.lean_root)).run()
    body = {
        "provenance": {"tool": {"name": "prooflens", "version": tool_version(),
                                "fingerprint": FINGERPRINT_VERSION},
                       "lean": (lean or {}).get("env"), "project": project_provenance(cfg),
                       "papers": papers_prov,
                       "comparator_log_sha256": sha256_file(comp) if comp_text else None},
        "inventory": {"file": os.path.relpath(cfg.inventory, cfg.root), "claims": inv["claims"]},
        "reviews": {"files": review_hashes, "records": [r.to_json() for r in reviews]},
        "dismissals": dismissals,
        "lean": lean, "tex": tex, "assessment": assessment}
    eid = ev.store(cfg.out_dir, body)
    rel = release or f"r-{eid[:12]}"
    ev.record_release(cfg.out_dir, rel, eid)
    record = ev.load(cfg.out_dir, eid)
    index, chunks, store = mf.build(record, rel)
    site = cfg.out_dir / "site"
    write_preview(site, index, chunks, store, pdfs, web_dist)
    log(f"evidence {eid[:12]}  release {rel}  site {site}")
    return {"evidence": eid, "release": rel, "site": site, "index": index}


def line_hashes(inv: dict, pid: str, src: Path) -> dict:
    """The hash of every source line a claim of the paper is recorded at."""
    out = {}
    for c in inv["claims"]:
        if c["paper"] != pid or line_location(c) is None:
            continue
        path, _, n = c["location"].rpartition(":")
        try:
            lines = (src / path).read_text(encoding="utf-8").split("\n")
            out[c["location"]] = sha256_text(norm_ws(lines[int(n) - 1]))
        except (OSError, IndexError):
            pass
    return out


def reassess(cfg: Config, web_dist: Path | None = None, release: str | None = None,
             log=print) -> dict:
    """Assess the latest evidence again with the current rules and the current review files,
    without probing or compiling, and store the result as a new evidence record and release."""
    rels = sorted((cfg.out_dir / "releases").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not rels:
        raise RuntimeError("no release: run `prooflens build` first")
    old = ev.load(cfg.out_dir, read_json(rels[-1])["evidence"])["body"]
    inv = read_json(cfg.inventory)
    validate(inv, "inventory")
    reviews, review_hashes = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    dismissals = load_dismissals(cfg.dismissals)
    comp = cfg.comparator_log
    comp_text = comp.read_text(errors="replace") if comp and comp.exists() else None
    assessment = Assessor(cfg, inv, old["lean"], old["tex"], reviews, dismissals, comp_text,
                          old["provenance"]["project"].get("commit")).run()
    body = {**old, "inventory": {"file": os.path.relpath(cfg.inventory, cfg.root),
                                 "claims": inv["claims"]},
            "reviews": {"files": review_hashes, "records": [r.to_json() for r in reviews]},
            "dismissals": dismissals, "assessment": assessment,
            "provenance": {**old["provenance"],
                           "tool": {**old["provenance"]["tool"], "version": tool_version()},
                           "comparator_log_sha256": sha256_file(comp) if comp_text else None,
                           "reassessed_from": read_json(rels[-1])["evidence"]}}
    body.pop("schema", None)
    eid = ev.store(cfg.out_dir, body)
    rel = release or f"r-{eid[:12]}"
    ev.record_release(cfg.out_dir, rel, eid)
    log(f"evidence {eid[:12]}  release {rel} (reassessed)")
    return rebuild_site(cfg, web_dist, rel)


def pdf_paths(cfg: Config, body: dict) -> dict:
    """The PDF each paper's evidence was built with: the compiled one, or the committed one."""
    out = {}
    for pid, prov in body["provenance"]["papers"].items():
        if prov.get("pdf_origin") == "compiled" and prov.get("root"):
            p = cfg.out_dir / "build" / pid / Path(prov["root"]).with_suffix(".pdf")
        elif prov.get("committed_pdf"):
            p = cfg.out_dir / "sources" / pid / prov["committed_pdf"]
        else:
            continue
        if p.exists() and sha256_file(p) == prov.get("pdf_sha256"):
            out[pid] = p
    return out


def rebuild_site(cfg: Config, web_dist: Path | None = None, release: str | None = None) -> dict:
    """The preview site again from a stored release, without probing or compiling. A PDF is
    included only if the one on disk is the one the evidence records."""
    rels = sorted((cfg.out_dir / "releases").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not rels:
        raise RuntimeError("no release: run `prooflens build` first")
    rel = read_json(cfg.out_dir / "releases" / f"{release}.json") if release else \
        read_json(rels[-1])
    record = ev.load(cfg.out_dir, rel["evidence"])
    index, chunks, store = mf.build(record, rel["release"])
    site = cfg.out_dir / "site"
    write_preview(site, index, chunks, store, pdf_paths(cfg, record["body"]), web_dist)
    return {"release": rel["release"], "site": site, "index": index}


def write_preview(site: Path, index: dict, chunks: dict, store: dict, pdfs: dict,
                  web_dist: Path | None):
    if site.exists():
        shutil.rmtree(site)
    if web_dist and web_dist.exists():
        shutil.copytree(web_dist, site)
    data = site / "data"
    validate(index, "manifest-index")
    write_json(data / "index.json", index, indent=None)
    for name, chunk in chunks.items():
        validate(chunk, "manifest-claim")
        write_json(data / "claims" / name, chunk, indent=None)
    for key, record in store.items():
        write_json(data / "decls" / f"{key}.json", record, indent=None)
    write_json(data / "search.json", mf.search_index(index, chunks), indent=None)
    for pid, pdf in pdfs.items():
        (data / "papers").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, data / "papers" / f"{pid}.pdf")
