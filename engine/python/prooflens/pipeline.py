"""The build: acquire the papers, run the probe, compile with anchors, assess, store the
evidence, and write the private preview site."""

from __future__ import annotations

import os
import shutil
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import evidence as ev
from . import manifest as mf
from . import review_queue as rq
from .assess import Assessor, line_location
from .config import Config
from .probe import FINGERPRINT_VERSION, requests_from_inventory, run_probe
from .reviews import load_dismissals, load_reviews
from .schemas import validate
from .sources import acquire
from .excerpt import collect as collect_excerpts, read_aux
from .source_regions import collect as collect_source_regions
from .tex import DEFAULT_ENVS, TexError, anchors_for, theorem_envs
from .util import (canonical_json, git_dirty, git_head, link_or_copy, prepare_work_dir,
                   read_json, sha256_file, sha256_text, write_json)


def tool_version() -> str:
    """The installed MachineChecked release (`prooflens` was the package's earlier name)."""
    for dist in ("machinechecked", "prooflens"):
        try:
            return version(dist)
        except PackageNotFoundError:
            pass
    return "0.1.0+src"


def project_provenance(cfg: Config) -> dict:
    lr = cfg.lean_root
    tc = lr / "lean-toolchain"
    lm = lr / "lake-manifest.json"
    # The Lean project's own commit, wherever the configuration file is kept.
    prov = {"name": cfg.name, "commit": git_head(lr), "dirty": git_dirty(lr),
            "toolchain": tc.read_text().strip() if tc.exists() else None,
            "lake_manifest_sha256": sha256_file(lm) if lm.exists() else None,
            "dependencies": {}}
    if lm.exists():
        for p in read_json(lm).get("packages", []):
            prov["dependencies"][p.get("name")] = p.get("rev")
    return prov


def build(cfg: Config, release: str | None = None, skip_lean: bool = False,
          skip_tex: bool = False, lake: str = "lake", web_dist: Path | None = None,
          lean_build: bool = True, reuse_lean: bool = False, log=print) -> dict:
    prepare_work_dir(cfg.out_dir)
    inv = read_json(cfg.inventory)
    validate(inv, "inventory")
    reviews, review_hashes = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    dismissals = load_dismissals(cfg.dismissals)

    # Every paper's source is acquired and checked (one LaTeX root, the PDF present) before Lean
    # runs: a problem there should not wait for a probe that can take hours.
    snaps = {paper.id: acquire(cfg, paper, cfg.out_dir / "sources" / paper.id)
             for paper in cfg.papers}

    lean = None
    lean_digest = None
    probe_used = probe_digest()  # the probe this build runs, read before it runs
    if reuse_lean:
        lean = reusable_lean(cfg)
        missing = [r["name"] for r in requests_from_inventory(inv)
                   if (r["kind"] == "spec" and r["name"] not in lean["specs"])
                   or (r["kind"] == "decl" and r["name"] not in lean["defs"])
                   or (r["kind"] in ("accept", "refute", "witness") and
                       f"{r['kind']}:{r['name']}:{r.get('spec') or ''}" not in lean["proofs"])]
        if missing:
            raise RuntimeError(f"the stored probe does not cover {missing[:5]}; run the probe")
        lean_digest = lean_inputs_digest(cfg)
        log("probe: reusing the stored probe records (no Lean input changed)")
    elif not skip_lean:
        lean_digest = lean_inputs_digest(cfg)
        log(f"probe: {len(requests_from_inventory(inv))} requests in {cfg.lean_root}")
        lean = run_probe(cfg, requests_from_inventory(inv), lake=lake, build=lean_build)

    tex, papers_prov, pdfs = {}, {}, {}
    display = load_display(cfg)
    for paper in cfg.papers:
        snap = snaps[paper.id]
        prov = {"title": paper.title, "kind": snap.kind, "revision": snap.revision,
                "mode": snap.mode, "root": snap.root, "note": snap.note,
                "committed_pdf": snap.pdf,
                "committed_pdf_sha256": sha256_file(snap.dir / snap.pdf) if snap.pdf else None,
                **({"published": paper.published} if paper.published else {}),
                # A paper read from a folder: the commit of the repository that folder is in.
                **({"source_commit": git_head(cfg.root / paper.source["path"])}
                   if snap.kind == "path" and git_head(cfg.root / paper.source["path"]) else {}),
                **({"published_note": paper.published_note} if paper.published_note else {})}
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
            # The source is a PDF: its numbered statements are found by their bold headings
            # (positions approximate). The PDF counts as source evidence for the release gate
            # only when the configuration pins its hash and it matches.
            from .pdfclaims import claims_from_pdf
            anchors, size = claims_from_pdf(snap.dir / snap.pdf)
            tex[paper.id] = {"mode": "pdf", "anchors": anchors, "page_size": size, "inputs": [],
                             "pdf_sha256": prov["committed_pdf_sha256"],
                             "pdf_pinned": paper.pdf_sha256}
            prov["mode"] = "pdf"
            prov["pdf_sha256"] = prov["committed_pdf_sha256"]
            prov["pdf_origin"] = "committed"
            pdfs[paper.id] = snap.dir / snap.pdf
        if paper.id in tex:
            if t is not None:
                tex[paper.id]["regions"] = collect_source_regions(inv, paper.id, snap.dir)
                locs = [c["location"] for c in inv["claims"]
                        if c["paper"] == paper.id and line_location(c) is not None]
                tex[paper.id]["line_anchors"] = t["line_anchors"](locs)
                # Display only: the passages the reader typesets, read from this snapshot and
                # its compilation, so that a later rebuild of this release shows the same text.
                selectors = {cid: v["excerpt"] for cid, v in
                             ((display or {}).get("claims") or {}).items() if "excerpt" in v}
                tex[paper.id]["excerpts"] = collect_excerpts(
                    inv["claims"], paper.id, snap.dir, snap.root,
                    read_aux(t["cwd"], Path(snap.root).stem), snap.revision, envs,
                    tex[paper.id]["anchors"], tex[paper.id]["regions"], selectors)
            tex[paper.id]["manual_anchors"] = manual_anchors(cfg, paper.id)
        papers_prov[paper.id] = prov

    comp = cfg.comparator_log
    comp_text = comp.read_text(errors="replace") if comp and comp.exists() else None
    assessment = Assessor(cfg, inv, lean, tex, reviews, dismissals, comp_text,
                          git_head(cfg.lean_root)).run()
    body = {
        "provenance": {"tool": {"name": "prooflens", "version": tool_version(),
                                "fingerprint": FINGERPRINT_VERSION},
                       "probe_sha256": probe_used if lean else None,
                       "lean_inputs_sha256": lean_digest,
                       "lean_reused": reuse_lean,
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
    index, chunks, store = mf.build(record, rel, display)
    index.update(issues=cfg.issues, site_url=cfg.site_url)
    index["project"].update(source_info(cfg))
    site = cfg.out_dir / "site"
    write_preview(site, index, chunks, store, pdfs, web_dist,
                  rq.assurance_queue(index, chunks, store, cfg.statement_authors))
    log(f"evidence {eid[:12]}  release {rel}  site {site}")
    return {"evidence": eid, "release": rel, "site": site, "index": index}


LEAN_INPUTS = ["*.lean", "lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain"]


def lean_input_roots(cfg: Config) -> list[Path]:
    """The project and every path dependency of its lake manifest: their sources are inputs of
    the probe; remote dependencies are pinned by the manifest itself."""
    roots = [cfg.lean_root]
    lm = cfg.lean_root / "lake-manifest.json"
    if lm.exists():
        for p in read_json(lm).get("packages", []):
            if p.get("type") == "path":
                roots.append((cfg.lean_root / p["dir"]).resolve())
    return roots


def lean_inputs_digest(cfg: Config) -> str:
    """SHA-256 over the content of every Lean input of the project and its path dependencies
    (sources, lakefiles, manifest, toolchain), committed or not."""
    import hashlib
    h = hashlib.sha256()
    for root in lean_input_roots(cfg):
        files = []
        for pat in LEAN_INPUTS:
            files += [f for f in root.rglob(pat) if ".lake" not in f.parts and ".git" not in
                      f.parts and ".prooflens" not in f.parts]
        h.update(f"root {root.name}\n".encode())
        for f in sorted(set(files)):
            h.update(f"{f.relative_to(root)}\n".encode())
            h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def probe_digest() -> str:
    return sha256_text(resources.files("prooflens").joinpath("data/ProofLensProbe.lean")
                       .read_text())


def source_info(cfg: Config) -> dict:
    """The project's source repository, for the reader's Lean source links."""
    from . import audit
    return audit.source_info(cfg.lean_root, cfg.scope_roots, cfg.repository,
                             cfg.repository_private)


def reusable_lean(cfg: Config) -> dict:
    """The probe records of the latest evidence, if they still describe this checkout: the same
    content of every Lean input (here and in every path dependency) and the same probe."""
    rels = ev.releases(cfg.out_dir)
    if not rels:
        raise RuntimeError("no stored evidence to reuse")
    body = ev.load(cfg.out_dir, read_json(rels[-1])["evidence"])["body"]
    lean, prov = body.get("lean"), body["provenance"]
    if not lean or not prov.get("lean_inputs_sha256") or not prov.get("probe_sha256"):
        raise RuntimeError("the stored evidence does not record its Lean inputs; run the probe")
    if prov["lean_inputs_sha256"] != lean_inputs_digest(cfg):
        raise RuntimeError("Lean inputs changed since the stored probe (here or in a path "
                           "dependency); run the probe")
    if prov["probe_sha256"] != probe_digest():
        raise RuntimeError("the probe changed since the stored records; run the probe")
    return lean


def manual_anchors(cfg: Config, pid: str) -> dict:
    """Anchors placed by hand (`anchors.json` beside the configuration, versioned with the
    project): `{claim id: {page, y0, y1, note, by}}` for the claims of paper `pid`."""
    path = cfg.root / "anchors.json"
    if not path.exists():
        return {}
    return {cid: a for cid, a in read_json(path).items() if cid.split(":")[0] == pid}


class StaleEvidence(RuntimeError):
    """The stored evidence does not cover the project as it now is (or there is none): a build
    is needed first. The message names the command."""


NO_RELEASE = "no release: run `machinechecked build` first"


def inventory_changed(cfg: Config, body: dict) -> str | None:
    """Why the stored evidence `body` does not cover the current claim inventory, if it does
    not."""
    inv = read_json(cfg.inventory)
    validate(inv, "inventory")
    if canonical_json(inv["claims"]) != canonical_json(body["inventory"]["claims"]):
        return ("the claim inventory changed since the last build: its Lean and LaTeX results "
                "may not cover it; run `machinechecked build --reuse-lean` (or `machinechecked "
                "build` if a Lean input changed too)")
    return None


def reassess(cfg: Config, web_dist: Path | None = None, release: str | None = None,
             log=print) -> dict:
    """Assess the latest evidence again with the current rules and the current review files,
    without probing or compiling, and store the result as a new evidence record and release."""
    rels = ev.releases(cfg.out_dir)
    if not rels:
        raise StaleEvidence(NO_RELEASE)
    old = ev.load(cfg.out_dir, read_json(rels[-1])["evidence"])["body"]
    why = inventory_changed(cfg, old)
    if why:
        raise StaleEvidence(why)
    inv = read_json(cfg.inventory)
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
    rels = ev.releases(cfg.out_dir)
    if not rels:
        raise StaleEvidence(NO_RELEASE)
    rel = read_json(cfg.out_dir / "releases" / f"{release}.json") if release else \
        read_json(rels[-1])
    record = ev.load(cfg.out_dir, rel["evidence"])
    index, chunks, store = mf.build(record, rel["release"], load_display(cfg))
    index.update(issues=cfg.issues, site_url=cfg.site_url)
    index["project"].update(source_info(cfg))
    site = cfg.out_dir / "site"
    write_preview(site, index, chunks, store, pdf_paths(cfg, record["body"]), web_dist,
                  rq.assurance_queue(index, chunks, store, cfg.statement_authors))
    return {"release": rel["release"], "site": site, "index": index}


def load_display(cfg: Config) -> dict | None:
    """What changes what is shown and never what is assessed: the display overlay, and the
    symbol links (docs/SYMBOL_LINKS.md)."""
    out = read_json(cfg.display) if cfg.display and cfg.display.exists() else None
    if cfg.symbols and cfg.symbols.exists():
        out = {**(out or {}), "symbols": read_json(cfg.symbols).get("links", [])}
    return out


def write_preview(site: Path, index: dict, chunks: dict, store: dict, pdfs: dict,
                  web_dist: Path | None, queue: dict | None = None):
    if queue is not None:
        index = {**index, "review_queue": "data/review-queue.json"}
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
    if queue is not None:
        write_json(data / "review-queue.json", queue, indent=None)
    for pid, pdf in pdfs.items():
        (data / "papers").mkdir(parents=True, exist_ok=True)
        link_or_copy(pdf, data / "papers" / f"{pid}.pdf")
