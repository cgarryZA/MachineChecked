"""The build: acquire the papers, run the probe, compile with anchors, assess, store the
evidence, and write the private preview site."""

from __future__ import annotations

import os
import shutil
from importlib import resources
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import content as content_mod
from . import evidence as ev
from . import manifest as mf
from . import review_queue as rq
from .assess import Assessor, line_location
from .config import Config, ConfigError
from .probe import FINGERPRINT_VERSION, MODDOCS, probe_query, requests_from_inventory, run_probe
from .reviews import load_dismissals, load_reviews
from .review_sources import carried
from .schemas import validate
from .sources import acquire
from .excerpt import collect as collect_excerpts, read_aux
from .source_regions import collect as collect_source_regions, part_texts, region_texts
from .tex import DEFAULT_ENVS, TexError, anchors_for, theorem_envs
from . import versions as paper_versions
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


def validate_inventory(inv: dict) -> None:
    """Check the claim inventory against its schema, and that a review marker can record each
    claim id (`review_sources.carried`)."""
    validate(inv, "inventory")
    bad = [c["id"] for c in inv["claims"] if not carried(c["id"])]
    if bad:
        raise ConfigError(
            "a review marker cannot record the claim id " + ", ".join(repr(b) for b in bad[:5])
            + (f" and {len(bad) - 5} more" if len(bad) > 5 else "") + ": a claim id may not "
            "hold white space or `-->`; rename the claim in the inventory")


def build(cfg: Config, release: str | None = None, skip_lean: bool = False,
          skip_tex: bool = False, lake: str = "lake", web_dist: Path | None = None,
          lean_build: bool = True, reuse_lean: bool = False, log=print) -> dict:
    prepare_work_dir(cfg.out_dir)
    inv = read_json(cfg.inventory)
    validate_inventory(inv)
    reviews, review_hashes = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    dismissals = load_dismissals(cfg.dismissals)

    # Every paper's source is acquired and checked (one LaTeX root, the PDF present) before Lean
    # runs: a problem there should not wait for a probe that can take hours.
    snaps = {paper.id: acquire(cfg, paper, cfg.out_dir / "sources" / paper.id)
             for paper in cfg.papers}
    # The version of each paper the audit pins, refused when the inventory pins another one.
    versions = {}
    for paper in cfg.papers:
        rec, is_declared = paper_versions.declared(paper, snaps[paper.id], cfg.root)
        versions[paper.id] = paper_versions.check(paper, rec, is_declared, inv)

    lean = None
    lean_digest = None
    probe_used = probe_digest()  # the probe this build runs, read before it runs
    settings_used = probe_settings_digest(cfg)
    engine_used = records_engine()
    if reuse_lean:
        reused, lean = reusable_lean(cfg, requests_from_inventory(inv))
        lean_digest = lean_inputs_digest(cfg)
        log(f"probe: reusing the probe records of release {reused} (the same Lean inputs, "
            "probe, probe settings and version of MachineChecked)")
    elif not skip_lean:
        # Without `lake build` the probe reads the build files as they are, which may be older
        # than the sources: its records are not known to describe these Lean inputs, so none
        # are recorded, and reuse, promotion and symbol links do not take them as current.
        lean_digest = lean_inputs_digest(cfg) if lean_build else None
        log(f"probe: {len(requests_from_inventory(inv))} requests in {cfg.lean_root}")
        if not lean_build:
            log("probe: the Lean project is not built first (`--no-lean-build`), so this build "
                "records no digest of its Lean inputs and `--reuse-lean` will not reuse it")
        from .review_citations import citations, names_request
        cited = names_request(citations(cfg.reviews, cfg.root,
                                        getattr(cfg, "review_citations_ignore", None)))
        lean = run_probe(cfg, requests_from_inventory(inv) + [MODDOCS]
                         + ([cited] if cited else []), lake=lake, build=lean_build)

    tex, papers_prov, pdfs, auxes = {}, {}, {}, {}
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
                **({"published_note": paper.published_note} if paper.published_note else {}),
                **({"paper_version": versions[paper.id]} if versions[paper.id] else {})}
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
            auxes[paper.id] = Path(t["cwd"]) / (Path(snap.root).stem + ".aux")
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
                tex[paper.id]["regions"] = collect_source_regions(
                    inv, paper.id, snap.dir, getattr(paper, "notation_macros", ()))
                # The passages of pins that list several, in order (display only).
                parts = part_texts(inv, paper.id, snap.dir)
                if parts:
                    tex[paper.id]["part_text"] = parts
                # The text of each proof step and its context in the proof, for the reader and
                # the review packet (published only with the source text).
                from .steps import step_texts
                tex[paper.id]["step_text"] = step_texts(inv, paper.id, snap.dir,
                                                        tex[paper.id]["regions"])
                # The passage of each claim located by line, read from the file that holds it:
                # its printed statement, as an environment's body is an anchor's (display only;
                # published only with the source text).
                texts = region_texts(inv, paper.id, snap.dir, tex[paper.id]["regions"])
                if texts:
                    tex[paper.id]["region_text"] = texts
                locs =[c["location"] for c in inv["claims"]
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

    # Content search and the paper-number check read every declaration of the built modules,
    # from the Lean facts store; they are display, kept beside the evidence (`content.py`).
    found = None
    if lean is not None:
        found = content_mod.build(cfg, tex, inv["claims"], auxes, lake, log, reuse_only=reuse_lean)

    comp = cfg.comparator_log
    comp_text = comp.read_text(errors="replace") if comp and comp.exists() else None
    assessment = Assessor(cfg, inv, lean, tex, reviews, dismissals, comp_text,
                          git_head(cfg.lean_root)).run()
    body = {
        "provenance": {"tool": {"name": "prooflens", "version": tool_version(),
                                "fingerprint": FINGERPRINT_VERSION},
                       "probe_sha256": probe_used if lean else None,
                       "probe_settings_sha256": settings_used if lean else None,
                       "lean_records_engine": engine_used if lean else None,
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
    content_mod.save(cfg.out_dir, eid, found)
    rel = release or f"r-{eid[:12]}"
    ev.record_release(cfg.out_dir, rel, eid)
    record = ev.load(cfg.out_dir, eid)
    index, chunks, store = mf.build(record, rel, display)
    index.update(issues=cfg.issues, site_url=cfg.site_url, author=cfg.author)
    index["project"].update(source_info(cfg))
    site = cfg.out_dir / "site"
    found = content_mod.load(cfg.out_dir, eid, record["body"])
    changes = release_changes(cfg, rel)
    write_preview(site, index, chunks, store, pdfs, web_dist,
                  rq.prioritise(rq.assurance_queue(index, chunks, store, cfg.statement_authors),
                                changes, claims=index["claims"]),
                  changes=changes, content=found)
    for n in (found or {}).get("notes", []):
        log(f"note: {n}")
    log(f"evidence {eid[:12]}  release {rel}  site {site}")
    return {"evidence": eid, "release": rel, "site": site, "index": index, "content": found}


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


def probe_settings_digest(cfg: Config) -> str:
    """SHA-256 over what the probe's records depend on besides the Lean, the probe and the
    requests: the modules it loads, and the scope roots, layer prefixes and allowed axioms it is
    given (`probe.probe_query`)."""
    return sha256_text(canonical_json({"modules": cfg.modules,
                                       "query": probe_query(cfg, [])}))


def records_engine() -> dict:
    """The engine that read the probe's output into Lean records (`probe.parse_records`,
    `merge_records`, `attach_sources` and the fingerprints): its version and fingerprint
    version. A record keeps it when reassessed, since its Lean records are carried unchanged,
    and stored records are reused only by the same engine, as the facts store's are."""
    return {"version": tool_version(), "fingerprint": FINGERPRINT_VERSION}


def source_info(cfg: Config) -> dict:
    """The project's source repository, for the reader's Lean source links."""
    from . import audit
    return audit.source_info(cfg.lean_root, cfg.scope_roots, cfg.repository,
                             cfg.repository_private)


def reusable_lean(cfg: Config, requests: list[dict]) -> tuple[str, dict]:
    """The newest stored release whose probe records describe this checkout, and those records:
    made from the same content of every Lean input (here and in every path dependency), by the
    same probe, with the same probe settings, read by the same engine (`records_engine`), and
    answering every one of `requests`. It need not be the latest release: a build that
    reproduces an earlier evidence record names no new release. When no release qualifies, the
    refusal says how far the closest came."""
    want = (lean_inputs_digest(cfg), probe_digest(), probe_settings_digest(cfg),
            records_engine())
    closest, why, seen = -1, "no stored Lean results to reuse", set()
    for rel in reversed(ev.releases(cfg.out_dir)):
        try:
            named = read_json(rel)
            name, eid = named["release"], named["evidence"]
            if eid in seen:
                continue
            seen.add(eid)
            path = cfg.out_dir / "evidence" / f"{eid}.json"
            rec = read_json(path)
            body = rec["body"]
            lean, prov = body.get("lean"), body["provenance"]
        except (OSError, ValueError, KeyError, TypeError):
            continue  # a record that cannot be read cannot be reused
        if not lean:
            continue
        stage, reason = _reuse_stage(lean, prov, want, requests)
        if reason is None:
            # The id is checked only for the record reused: each is a large file.
            return name, ev.checked(rec, eid, path)["body"]["lean"]
        if stage > closest:
            closest, why = stage, reason
    raise StaleEvidence(why + "; " + RUN_PROBE)


def _reuse_stage(lean: dict, prov: dict, want: tuple[str, str, str, dict],
                 requests: list[dict]) -> tuple[int, str | None]:
    """How far stored probe records `lean`, with provenance `prov`, match the checkout's Lean
    inputs, probe and probe settings and this engine, `want`, and cover `requests`: the number
    of conditions met in turn, and why the next one fails (None when every one holds)."""
    inputs, probe, settings, engine = (prov.get("lean_inputs_sha256"), prov.get("probe_sha256"),
                                       prov.get("probe_settings_sha256"),
                                       prov.get("lean_records_engine"))
    if not inputs or not probe:
        return 0, ("the stored Lean results do not record their Lean inputs (a build with "
                   "`--no-lean-build` records none: its build files may be older than the "
                   "sources)")
    if inputs != want[0]:
        return 1, ("Lean inputs changed since the stored Lean results (here or in a path "
                   "dependency)")
    if probe != want[1]:
        return 2, "the Lean probe changed since the stored Lean results"
    if not settings:
        return 3, ("the stored Lean results do not record the probe's settings (an earlier "
                   "version of MachineChecked stored them)")
    if settings != want[2]:
        return 4, ("the probe's settings (`modules`, `scope_roots`, `spec_prefix`, "
                   "`accept_prefix` or `allowed_axioms` in the configuration) changed since the "
                   "stored Lean results")
    if not isinstance(engine, dict) or not engine:
        return 5, ("the stored Lean results do not record the version of MachineChecked that "
                   "read them (an earlier version stored them)")
    if engine != want[3]:
        name = lambda e: f"{e.get('version')}, fingerprints {e.get('fingerprint')}"
        return 6, ("the stored Lean results were read by another version of MachineChecked "
                   f"({name(engine)}; this is {name(want[3])})")
    missing = [r["name"] for r in requests
               if (r["kind"] == "spec" and r["name"] not in lean.get("specs", {}))
               or (r["kind"] == "decl" and r["name"] not in lean.get("defs", {}))
               or (r["kind"] == "link" and r["name"] not in lean.get("links", {}))
               or (r["kind"] in ("accept", "refute", "witness") and
                   f"{r['kind']}:{r['name']}:{r.get('spec') or ''}" not in lean.get("proofs", {}))]
    if missing:
        return 7, (f"the stored Lean results do not cover {', '.join(missing[:5])}"
                   + (", …" if len(missing) > 5 else ""))
    return 8, None


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
RUN_PROBE = "run `machinechecked build` without `--reuse-lean`"


def inventory_changed(cfg: Config, body: dict) -> str | None:
    """Why the stored evidence `body` does not cover the current claim inventory, if it does
    not."""
    inv = read_json(cfg.inventory)
    validate_inventory(inv)
    if canonical_json(inv["claims"]) != canonical_json(body["inventory"]["claims"]):
        return ("the claim inventory changed since the last build: its Lean and LaTeX results "
                "may not cover it; run `machinechecked build --reuse-lean` (or `machinechecked "
                "build` if a Lean input changed too)")
    return None


def reassess(cfg: Config, web_dist: Path | None = None, release: str | None = None,
             log=print) -> dict:
    """Assess the latest release's evidence (`evidence.latest`) again with the current rules and
    the current review files, without probing or compiling, and store the result as a new
    evidence record and release. When nothing changed (the record would differ from the one
    read only in naming it in `reassessed_from`), the reassessment reproduces the release it
    read, as a repeated build does."""
    last = ev.latest(cfg.out_dir)
    if last is None:
        raise StaleEvidence(NO_RELEASE)
    old = ev.load(cfg.out_dir, last["evidence"])["body"]
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
                           "reassessed_from": last["evidence"]}}
    body.pop("schema", None)
    if _apart_from_origin(body) == _apart_from_origin(old):
        eid, rel = last["evidence"], release or last["release"]
        ev.record_release(cfg.out_dir, rel, eid)
        log(f"evidence {eid[:12]}  release {rel} (reassessed: nothing changed)")
        return rebuild_site(cfg, web_dist, rel)
    eid = ev.store(cfg.out_dir, body)
    rel = release or f"r-{eid[:12]}"
    ev.record_release(cfg.out_dir, rel, eid)
    log(f"evidence {eid[:12]}  release {rel} (reassessed)")
    return rebuild_site(cfg, web_dist, rel)


def _apart_from_origin(body: dict) -> str:
    """An evidence body's canonical JSON without its schema and without the record it was
    reassessed from: what a reassessment shares with the record it read when nothing
    changed."""
    prov = {k: v for k, v in body["provenance"].items() if k != "reassessed_from"}
    return canonical_json({**{k: v for k, v in body.items() if k != "schema"},
                           "provenance": prov})


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
    """The preview site again from a stored release (by default the latest, `evidence.latest`),
    without probing or compiling. A PDF is included only if the one on disk is the one the
    evidence records."""
    last = ev.latest(cfg.out_dir)
    if last is None:
        raise StaleEvidence(NO_RELEASE)
    rel = read_json(cfg.out_dir / "releases" / f"{release}.json") if release else last
    record = ev.load(cfg.out_dir, rel["evidence"])
    index, chunks, store = mf.build(record, rel["release"], load_display(cfg))
    index.update(issues=cfg.issues, site_url=cfg.site_url, author=cfg.author)
    index["project"].update(source_info(cfg))
    site = cfg.out_dir / "site"
    found = content_mod.load(cfg.out_dir, rel["evidence"], record["body"])
    changes = release_changes(cfg, rel["release"])
    write_preview(site, index, chunks, store, pdf_paths(cfg, record["body"]), web_dist,
                  rq.prioritise(rq.assurance_queue(index, chunks, store, cfg.statement_authors),
                                changes, claims=index["claims"]),
                  changes=changes, content=found)
    return {"release": rel["release"], "site": site, "index": index, "content": found}


def release_changes(cfg: Config, release: str) -> dict | None:
    """What changed from the release before `release` to it (`changes.py`), for the reader;
    None for a first release, or when the earlier evidence is of a form the comparison cannot
    read. It changes nothing that is assessed."""
    from . import changes
    try:
        if changes.previous_release(cfg.out_dir, release) is None:
            return None
        return changes.between(cfg.out_dir, None, release)
    except (changes.ChangesError, ev.EvidenceError, KeyError, TypeError, ValueError):
        return None


def load_display(cfg: Config) -> dict | None:
    """What changes what is shown and never what is assessed: the display overlay, and the
    symbol links (docs/SYMBOL_LINKS.md)."""
    out = read_json(cfg.display) if cfg.display and cfg.display.exists() else None
    if cfg.symbols and cfg.symbols.exists():
        out = {**(out or {}), "symbols": read_json(cfg.symbols).get("links", [])}
    return out


def write_preview(site: Path, index: dict, chunks: dict, store: dict, pdfs: dict,
                  web_dist: Path | None, queue: dict | None = None,
                  expansions: dict | None = None, changes: dict | None = None,
                  content: dict | None = None):
    """Write the reader and its data to `site`. Definitions expanded at their applications, and
    a declaration's equations after its first 64, are written on their own
    (`data/expansions/<key>.json`, `mf.split_expansions`), together with `expansions` already
    split off (those of published audits). `changes`, the comparison with
    the release before, is written as `data/changes.json`; `content`, the content index and
    the paper-number check (`content.py`), as `data/retrieval.json` and `data/numbering.json`.
    An audit's index (not a paper page's) gets its semantic summary (`semantic.py`), computed from
    these records."""
    if index.get("mode") != "paper":
        from . import semantic
        semantic.apply(index, chunks, author=index.get("author"))
    index, chunks = content_mod.apply(index, chunks, content)
    expansions = dict(expansions or {})
    pins = mf.fingerprints(store)
    # A declaration record without its expansions is a different record: it gets its own key.
    rekey, split_store = {}, {}
    for k, r in store.items():
        q = mf.split_expansions(r, expansions, pins)
        rekey[k] = mf.record_key(q) if q != r else k
        split_store[rekey[k]] = q
    store = split_store
    chunks = {n: {**mf.split_expansions(c, expansions, pins),
                  **({"decls": {d: rekey.get(k, k) for d, k in c["decls"].items()}}
                     if isinstance(c.get("decls"), dict) else {})}
              for n, c in chunks.items()}
    if queue is not None:
        index = {**index, "review_queue": "data/review-queue.json"}
    if changes is not None:
        index = {**index, "changes": "data/changes.json"}
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
    for key, record in expansions.items():
        write_json(data / "expansions" / f"{key}.json", record, indent=None)
    write_json(data / "search.json", mf.search_index(index, chunks), indent=None)
    if queue is not None:
        write_json(data / "review-queue.json", queue, indent=None)
    if changes is not None:
        write_json(data / "changes.json", changes, indent=None)
    content_mod.write(data, content)
    for pid, pdf in pdfs.items():
        (data / "papers").mkdir(parents=True, exist_ok=True)
        link_or_copy(pdf, data / "papers" / f"{pid}.pdf")
