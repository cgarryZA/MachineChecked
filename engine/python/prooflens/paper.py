"""A paper's page: the paper's PDF, the statements found in it, and for each Lean project that
states it formalises the paper, the declarations its `formalization.yaml` maps them to.

It is written in the reader's standard data format (`data/index.json`, `data/claims/`), so a
paper page is read by the same code as a view or an audit. Nothing here runs Lean, so a mapped
statement reads "linked: Lean not checked here (no audit published)": the link says which
declaration the project names, not what Lean establishes. Each project's links and statuses are
kept apart (`by_project`); the reader shows one project at a time and never combines them.

No statement's text is written: only its number, heading title and place on the page.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import formalization as fz
from . import manifest as mf
from .util import content_id

SCHEMA = "prooflens/manifest@0"
NOT_CHECKED = "linked: Lean not checked here (no audit published)"
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


def _state(links: list[dict]) -> tuple[str, str]:
    return (NOT_CHECKED, "declared") if links else (NOT_LINKED, "unspecified")


def write_paper_site(site: Path, paper: dict, claims: list[dict],
                     page_size: list | tuple | None, pdf_url: str | None,
                     web_dist: Path | None = None) -> dict:
    """Write the paper page's data under `site/data/` (and the reader, given its built
    directory). `paper` is the paper's registry entry (its identifier, title, authors, links and
    formalisations), which the reader's panel beside the paper shows; `claims` are from
    `paper_claims`. Replaces whatever is at `site`."""
    from .pipeline import write_preview
    projects = [f["repository"] for f in paper.get("formalisations", [])]
    index_claims, chunks = [], {}
    for c in claims:
        cid = f"P:{c['key']}"
        fname = mf.claim_file(cid)
        anchor = {**c["anchor"], "kind": "approximate"} if c.get("anchor") else None
        by_project = {}
        for r in projects:
            status, cls = _state([l for l in c["links"] if l["repository"] == r])
            by_project[r] = {"status": status, "class": cls}
        status, cls = _state([l for l in c["links"]
                              if not projects or l["repository"] == projects[0]])
        common = {"id": cid, "paper": "P", "number": c["number"], "title": c.get("title"),
                  "heading": c.get("title") or None, "kind": c["kind"], "scope": "formal",
                  "status": status, "class": cls, "by_project": by_project}
        index_claims.append({**common, "anchor": mf.index_anchor(anchor, "approximate"),
                             "counts": {}, "file": fname, "linked": len(c["links"]),
                             "suggested": 0})
        chunks[fname] = {
            **common, "schema": SCHEMA, "mode": "simple", "release": "paper", "key": c["key"],
            "scope_note": "", "scope_reviewed": True, "anchor": anchor,
            "source_matches": None, "statement_tex": None, "blockers": [],
            "links": [{**l, "status": NOT_CHECKED, "class": "declared", "why": None,
                       "statement": None, "path": None} for l in c["links"]],
            "suggestions": [], "clauses": [], "decls": {}, "findings": []}
    summary = {}
    for c in index_claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    # The page has no Lean evidence; its identifier is that of what it shows.
    eid = content_id({"paper": paper, "claims": claims, "pdf": pdf_url})
    index = {"schema": SCHEMA, "mode": "paper", "release": "paper", "evidence": eid,
             "tool": {"name": "machinechecked"}, "project": {}, "projects": projects,
             "paper": paper, "notes": [],
             "papers": [{"id": "P", "title": paper.get("title", ""), "mode": "pdf", "pdf": None,
                         "pdf_url": pdf_url, "page_size": list(page_size) if page_size else None,
                         "note": ""}],
             "summary": {"P": summary},
             "classes": {c["status"]: c["class"] for c in index_claims},
             "findings": {"total": {}, "general": []}, "gates": {}, "claims": index_claims,
             "search": "data/search.json"}
    write_preview(site, index, chunks, {}, {}, web_dist)
    return index
