"""Canonical paper pages with project-specific audit records and PDF editions.

The original PDF remains the default. Published evidence retains its author, release,
source revision and complete claim records. Each audit's PDF coordinates belong to its
verified PDF bytes; selecting a formalisation changes the evidence, independently of the PDF.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import formalization as fz
from . import manifest as mf
from .util import content_id, write_json
from .status import fields, source_evidence, STATUSES
from .published import load_published_audit  # public import API for site builders

SCHEMA = mf.SCHEMA
NOT_CHECKED = "linked: Lean not checked here (no audit published)"
NOT_IN_AUDIT = "linked: Lean not checked here (the published audit does not list it)"
NOT_LINKED = "not linked"
NAME = re.compile(r"[\w.'«»]+")


def paper_claims(anchors: list[dict], title: str,
                 alignments: list[tuple[dict, dict | None]]) -> list[dict]:
    """The statements found in the paper (anchors from `pdfclaims.claims_from_pdf`), each with
    the links the projects' `formalization.yaml` files declare for it. `alignments` pairs each
    project (`repository`, `commit`) with its parsed `formalization.yaml`, or None when it has
    none or it could not be read."""
    out = []
    for a in anchors:
        number = f"{a['env'].capitalize()} {a['number']}"
        links = []
        for f, fy in alignments:
            for row in fz.links_for(fy, a["env"], number, title) if fy else []:
                links += [{"name": n, "repository": f["repository"], "commit": f["commit"],
                           "source": "formalization.yaml"}
                          for n in row["lean"] if NAME.fullmatch(n)]
        out.append({"key": f"{a['env']}-{a['number']}", "number": number, "kind": a["env"],
                    "title": a.get("title"),
                    "anchor": {k: a[k] for k in ("begin", "end", "head") if a.get(k)},
                    "links": links})
    return out


def apply_audits(claims: list[dict], audits: dict[str, dict], pdf_sha256: str | None = None) -> list[dict]:
    """Join unique printed numbers within a validated project/paper snapshot.

    Additional and ambiguously numbered audit entries retain their own identifiers.
    Complete records stay under their project; exact coordinates transfer to the original
    paper only when the PDF hashes match. ``load_published_audit`` supplies full snapshots.
    """
    original = list(claims)
    used = {r: set() for r in audits}
    for c in original:
        c["audit"] = {}
        for repo, au in audits.items():
            same = [x for x in au.get("claims", []) if x.get("number") == c["number"]]
            if len(same) != 1 or sum(x["number"] == c["number"] for x in original) != 1:
                if same:
                    c["audit"][repo] = {**fields("unknown"), "detail": "Several records share this printed number; choose an audit entry from the contents."}
                continue
            x = same[0]
            c["audit"][repo] = _audit_record(x, au, pdf_sha256)
            used[repo].add(x["id"])
            if not any(l["repository"] == repo for l in c["links"]):
                c["links"] = c["links"] + [
                    {"name": n, "repository": repo, "commit": au.get("commit"),
                     "source": "audit"} for n in x.get("lean", []) if NAME.fullmatch(n)]
    # Audit entries include equations, prose and scope decisions that heading extraction misses.
    for repo, au in audits.items():
        for x in au.get("claims", []):
            if x["id"] in used[repo] or not x.get("record"):
                continue
            claims.append({"key": "audit-" + content_id([repo, x["id"]])[:20],
                           "number": x.get("number"), "kind": x.get("kind"),
                           "title": x.get("title"), "links": [], "anchor": None,
                           "projects": [repo], "audit": {repo: _audit_record(x, au, pdf_sha256)}})
    return claims


def _audit_record(x: dict, au: dict, pdf_sha256: str | None) -> dict:
    code = x.get("status_code")
    out = {**fields(code if code in STATUSES else "unknown"), "claim": x["id"],
           "link": x.get("link"), "author": au.get("author"), "audit": au.get("url")}
    if x.get("record"):
        ap = au["paper"]
        out.update(record=x["record"], paper=ap, context=au["context"],
                   edition=ap.get("edition"), audit_anchor=x.get("anchor"),
                   same_pdf=bool(pdf_sha256 and pdf_sha256 == ap.get("pdf_sha256")))
    return out


def _state(links: list[dict], audit: dict | None = None, audited: bool = False) -> dict:
    """Copy the audit's code; a link alone establishes no proof or review."""
    if audit:
        return fields(audit["status_code"])
    if not links:
        return fields("link.none")
    return fields("link.not-in-audit" if audited else "link.no-audit")


HREF = re.compile(r"(?!//)(?![a-z][\w+.-]*:)[\w./~%-]*", re.I)
HTTPS = re.compile(r"https://[^\s\"'<>]+")


def page_versions(entries: list[dict], current: str) -> list[dict]:
    """The versions of a paper its page offers (one page per version, each with its own PDF,
    claim numbering and audits), as the reader's version drop-down receives them. Each entry
    gives `id` and `kind` as an audit's `paper_version` does (a manuscript also its `revision`),
    `href` (the address of that version's page, on the same site), and optionally `pdf` and
    `audits` (`url`, `author`, `repository`). The label is MachineChecked's for that version,
    never one the entry supplies; `current` is the id of the version this page shows."""
    from .published import AuditError, paper_version
    out = []
    for e in entries:
        try:
            rec = paper_version({k: e.get(k) for k in ("kind", "id", "revision")})
        except AuditError as err:
            raise ValueError(f"paper version {e.get('id')!r}: {err}") from None
        href = e.get("href")
        if not isinstance(href, str) or not href or not HREF.fullmatch(href):
            raise ValueError(f"paper version {rec['id']}: href must be an address on this site")
        pdf = e.get("pdf")
        if pdf is not None and not (isinstance(pdf, str) and (HTTPS.fullmatch(pdf) or
                                                               HREF.fullmatch(pdf))):
            raise ValueError(f"paper version {rec['id']}: pdf must be https or on this site")
        audits = [{k: a.get(k) for k in ("url", "author", "repository") if a.get(k)}
                  for a in e.get("audits") or [] if HTTPS.fullmatch(str(a.get("url", "")))]
        out.append({"id": rec["id"], "kind": rec["kind"], "label": rec["label"],
                    **({"revision": rec["revision"]} if rec.get("revision") else {}),
                    "href": href, "pdf": pdf, "audits": audits})
    ids = [v["id"] for v in out]
    if len(set(ids)) != len(ids) or ids.count(current) != 1:
        raise ValueError(f"the versions must be distinct and include this page's ({current})")
    return out


def write_paper_site(site: Path, paper: dict, claims: list[dict],
                     page_size: list | tuple | None, pdf_url: str | None,
                     web_dist: Path | None = None, audits: dict | None = None,
                     versions: list[dict] | None = None, version: str | None = None) -> dict:
    """Write the paper page's data under `site/data/` (and the reader, given its built
    directory). `paper` is the paper's registry entry (its identifier, title, authors, links and
    formalisations), which the reader's panel beside the paper shows; `claims` are from
    `paper_claims`. A paper with several versions has a page per version: `version` is the id of
    this page's, `versions` every version's entry (`page_versions`), and every audit loaded for
    this page must pin this version. Replaces whatever is at `site`."""
    from .pipeline import write_preview
    from .published import same_version
    audits_loaded = audits or {}
    offered = page_versions(versions, version) if versions else None
    if offered:
        for r, a in audits_loaded.items():
            pv = a.get("paper_version") if a.get("state") == "loaded" else None
            if a.get("state") == "loaded" and not (pv and same_version(pv["id"], version)):
                raise ValueError(f"the audit of {r} does not pin {version}: load it with the "
                                 "listing's version (load_published_audit)")
    projects = [f["repository"] for f in paper.get("formalisations", [])]
    audited = {r for r, a in audits_loaded.items() if a.get("state") == "loaded"} if audits is not None else {f["repository"] for f in paper.get("formalisations", []) if f.get("audits")}
    index_claims, chunks = [], {}
    for c in claims:
        cid = f"P:{c['key']}"
        fname = mf.claim_file(cid)
        anchor = {**c["anchor"], "kind": "approximate"} if c.get("anchor") else None
        by_project = {}
        audits = c.get("audit") or {}
        for r in projects:
            state = _state([l for l in c["links"] if l["repository"] == r], audits.get(r),
                                 r in audited)
            failure = audits_loaded.get(r, {})
            if not audits.get(r) and failure.get("state") in ("unavailable", "incompatible"):
                state = fields("audit." + failure["state"])
            by_project[r] = {**state,
                             **({"audit": audits[r]} if r in audits else {})}
        first = projects[0] if projects else None
        state = {k: by_project[first][k] for k in ("status_code", "status", "class")} if first else fields("link.none")
        common = {**({"projects": c["projects"]} if c.get("projects") else {}), "id": cid, "paper": "P", "number": c["number"], "title": c.get("title"),
                  "heading": c.get("title") or None, "kind": c["kind"], "scope": "formal",
                  **state, "by_project": by_project}
        index_by_project = {}
        chunk_by_project = {}
        for r, variant in by_project.items():
            au = variant.get("audit", {})
            meta = {k: v for k, v in au.items() if k != "record"}
            index_by_project[r] = {**variant, **({"audit": meta} if au else {})}
            chunk_by_project[r] = {**variant, **({"audit": meta, "record": au["record"]} if au.get("record") else {})}
            if au.get("record"):
                rec = au["record"]
                index_by_project[r]["evidence_summary"] = [
                    {k: cl["evidence"][k] for k in ("formal", "review") if k in cl.get("evidence", {})}
                    for cl in rec.get("clauses", [])]
                index_by_project[r].update({k: rec.get(k) for k in ("scope", "kind", "title", "heading")})
                index_by_project[r]["anchor"] = au.get("audit_anchor") if au.get("same_pdf") else mf.index_anchor(anchor, "approximate")
        index_claims.append({**common, "by_project": index_by_project, "anchor": mf.index_anchor(anchor, "approximate"),
                             "counts": {}, "file": fname, "linked": len(c["links"]),
                             "suggested": 0})
        chunks[fname] = {
            **common, "by_project": chunk_by_project, "schema": SCHEMA, "mode": "simple", "release": "paper", "key": c["key"],
            "scope_note": "", "scope_reviewed": True, "anchor": anchor,
            "source_matches": None, "source_evidence": source_evidence(anchor, "pdf"),
            "statement_tex": None, "blockers": [],
            "links": [{**l, **fields("link.claim-audit" if l["repository"] in audits else
                                               "link.not-in-audit" if l["repository"] in audited else "link.no-audit"),
                       "why": None, "statement": None, "path": None} for l in c["links"]],
            "suggestions": [], "clauses": [], "decls": {}, "findings": []}
    summary = {}
    for c in index_claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    # Identify the assembled paper and its project-specific evidence.
    eid = content_id({"paper": paper, "claims": claims, "pdf": pdf_url})
    editions = {a["paper"]["edition"]: {**a["paper"], "author": a.get("author"), "repository": r}
                for r, a in audits_loaded.items() if a.get("paper", {}).get("edition")}
    index = {"schema": SCHEMA, "editions": list(editions.values()),
             "audits": {r: {k: a[k] for k in ("state", "detail", "commit", "release", "author", "url", "gates",
                                                    "paper_version") if k in a}
                        for r, a in audits_loaded.items()}, "mode": "paper", "release": "paper", "evidence": eid,
             "tool": {"name": "machinechecked"}, "project": {}, "projects": projects,
             "paper": paper, "notes": [],
             **({"version": version, "versions": offered} if offered else {}),
             "papers": [{"id": "P", "title": paper.get("title", ""), "mode": "pdf", "pdf": None,
                         "pdf_url": pdf_url, "page_size": list(page_size) if page_size else None,
                         "note": ""}],
             "summary": {"P": summary},
             "classes": {c["status"]: c["class"] for c in index_claims},
             "findings": {"total": {}, "general": []}, "gates": {}, "claims": index_claims,
             "search": "data/search.json"}
    store = {k: v for a in audits_loaded.values() for k, v in a.get("store", {}).items()}
    expansions = {k: v for a in audits_loaded.values() for k, v in a.get("expansions", {}).items()}
    write_preview(site, index, chunks, store, {}, web_dist, expansions=expansions)
    search = mf.search_index(index, chunks)
    search["by_project"] = {}
    for repo in projects:
        selected = {}
        for name, chunk in chunks.items():
            if chunk.get("projects") and repo not in chunk["projects"]:
                continue
            variant = chunk["by_project"][repo]
            selected[name] = {**chunk,
                              "links": [l for l in chunk.get("links", []) if l.get("repository") == repo],
                              **variant.get("record", {}), "id": chunk["id"], "paper": "P"}
        rows = [{**c, **c["by_project"][repo]} for c in index["claims"] if c["file"] in selected]
        search["by_project"][repo] = mf.search_index({**index, "claims": rows}, selected)
    write_json(site / "data" / "search.json", search, indent=None)
    for a in audits_loaded.values():
        for key, raw in a.get("pdfs", {}).items():
            path = site / "data" / "papers" / f"{key}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    return index
