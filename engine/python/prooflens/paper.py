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
COMMIT = re.compile(r"[0-9a-f]{40}")


def page_versions(entries: list[dict], current: str) -> list[dict]:
    """The versions of a paper its page offers (one page per version, each with its own PDF,
    claim numbering and audits), as the reader's version drop-down receives them. Each entry
    gives `id` and `kind` as an audit's `paper_version` does (a manuscript also its `revision`),
    `href` (the address of that version's page, on the same site), and optionally `pdf` and
    `audits` (`url`, `author`, `repository`, `commit`). The label is MachineChecked's for that version,
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
        audits = [{**{k: a.get(k) for k in ("url", "author", "repository") if a.get(k)},
                   **({"commit": a["commit"]} if COMMIT.fullmatch(str(a.get("commit", ""))) else {})}
                  for a in e.get("audits") or [] if HTTPS.fullmatch(str(a.get("url", "")))]
        out.append({"id": rec["id"], "kind": rec["kind"], "label": rec["label"],
                    **({"revision": rec["revision"]} if rec.get("revision") else {}),
                    "href": href, "pdf": pdf, "audits": audits})
    ids = [v["id"] for v in out]
    if len(set(ids)) != len(ids) or ids.count(current) != 1:
        raise ValueError(f"the versions must be distinct and include this page's ({current})")
    return out


CHANGES = ("same", "renumbered", "changed", "split", "removed", "new")
KEY = re.compile(r"[\w.:-]+")
LABEL = re.compile(r"\\label\s*\{[^{}]*\}")


def _unlabelled(m: re.Match) -> str:
    """What a `\\label` command leaves in a statement text: nothing, or a space when it stands
    between a control word and a letter (`\\item\\label{a}Each`), which it keeps apart."""
    s, i = m.string, m.start()
    k = i
    while k > 0 and s[k - 1].isascii() and s[k - 1].isalpha():
        k -= 1
    after = s[m.end():m.end() + 1]
    return " " if 0 < k < i and s[k - 1] == "\\" and after.isascii() and after.isalpha() \
        else ""


def statement_key(text) -> str:
    """A statement text as `claim_map` compares it: without its `\\label` commands, which are
    not printed, and then with its white space collapsed, so that a statement that only gains,
    loses or renames a label is the same text."""
    return " ".join(LABEL.sub(_unlabelled, str(text or "")).split())


def claim_map(earlier: str, earlier_claims: list[dict], later: str,
              later_claims: list[dict]) -> dict:
    """The map of the claims of one version of a paper (`earlier`, a version id) to those of
    another (`later`), computed from the two versions' claim inventories. Each claim gives `key`
    and `number`, and may give `label` (its source pin, such as the LaTeX label) and `statement`
    (its text). Statement texts are compared without their `\\label` commands and with white
    space collapsed (`statement_key`).

    A claim's counterpart is, in this order: the claim of the other version with its label, when
    each version has one claim with it; else the claim of the other version with its statement
    text, when each version has one such claim not matched by a label; else the claim of the
    other version under its number, when each version has one claim there not matched before
    and neither claim has a label that the other version gives a claim. A claim and its
    counterpart are `same`, `renumbered` (same statement, another number) or `changed` (another
    statement); when either has no statement text, nothing says whether it changed, and the pair
    is left out.

    A claim with a statement and no counterpart is `removed` (from the earlier version) or `new`
    (in the later) only when the other version certainly has none: the claim has a label, no
    claim of the other version has that label, and none there under its number is unmatched or
    lacks a statement text. Any other claim without a counterpart is left out, as is a claim
    without a statement. A split is never inferred: a listing states it."""
    def ref(c):
        return {"key": c["key"], "number": c["number"]}
    sides = (list(earlier_claims), list(later_claims))
    text = [[statement_key(c.get("statement")) for c in cs] for cs in sides]
    labels = [{} for _ in sides]          # label -> indices of the claims with it, per side
    for s, cs in enumerate(sides):
        for i, c in enumerate(cs):
            if c.get("label"):
                labels[s].setdefault(c["label"], []).append(i)
    match: dict[int, int] = {}            # earlier index -> later index

    def unmatched(s):
        taken = set(match) if s == 0 else set(match.values())
        return [i for i in range(len(sides[s])) if i not in taken]

    # By label: certain when each version has one claim with it.
    for lab, ii in labels[0].items():
        jj = labels[1].get(lab, [])
        if len(ii) == 1 and len(jj) == 1:
            match[ii[0]] = jj[0]
    # By statement text, among the claims a label did not match.
    by_text = [{}, {}]
    for s in (0, 1):
        for i in unmatched(s):
            if text[s][i]:
                by_text[s].setdefault(text[s][i], []).append(i)
    for t, ii in by_text[0].items():
        jj = by_text[1].get(t, [])
        if len(ii) == 1 and len(jj) == 1:
            match[ii[0]] = jj[0]
    # By number, among the claims still unmatched, when neither has a label the other version
    # gives a claim (that claim may be its counterpart).
    by_number = [{}, {}]
    for s in (0, 1):
        for i in unmatched(s):
            by_number[s].setdefault(sides[s][i]["number"], []).append(i)
    for n, ii in by_number[0].items():
        jj = by_number[1].get(n, [])
        if len(ii) == 1 and len(jj) == 1 and \
                (sides[0][ii[0]].get("label") or None) not in labels[1] and \
                (sides[1][jj[0]].get("label") or None) not in labels[0]:
            match[ii[0]] = jj[0]

    # The numbers under which a claim's counterpart may be, per side: those of a claim left
    # unmatched or without a statement text.
    left = [set(unmatched(0)), set(unmatched(1))]
    unsure = [{c["number"] for i, c in enumerate(cs) if i in left[s] or not text[s][i]}
              for s, cs in enumerate(sides)]

    def certain(s, i):
        lab = sides[s][i].get("label")
        return bool(lab) and lab not in labels[1 - s] and sides[s][i]["number"] not in unsure[1 - s]

    out = []
    for i, c in enumerate(sides[0]):
        j = match.get(i)
        if j is not None:
            d = sides[1][j]
            if text[0][i] and text[1][j]:
                change = ("changed" if text[0][i] != text[1][j] else
                          "renumbered" if d["number"] != c["number"] else "same")
                out.append({"from": [ref(c)], "to": [ref(d)], "change": change})
        elif text[0][i] and certain(0, i):
            out.append({"from": [ref(c)], "to": [], "change": "removed"})
    out += [{"from": [], "to": [ref(d)], "change": "new"} for j, d in enumerate(sides[1])
            if j in left[1] and text[1][j] and certain(1, j)]
    return check_claim_map({"from": earlier, "to": later, "claims": out})


def check_claim_map(m: dict) -> dict:
    """A claim map (`claim_map`, or a listing's), checked: `from` and `to` are the ids of the
    earlier and the later version, and each of `claims` names the claims (`key`, `number`) it
    relates on each side and its `change`: `same`, `renumbered` or `changed` (one claim to one),
    `split` (one to several), `removed` (one to none) or `new` (none to one)."""
    if not isinstance(m, dict) or not all(isinstance(m.get(k), str) and m[k] for k in ("from", "to")) \
            or m["from"] == m["to"] or not isinstance(m.get("claims"), list):
        raise ValueError("a claim map gives `from` and `to` (two version ids) and `claims`")
    shape = {"same": (1, 1), "renumbered": (1, 1), "changed": (1, 1), "split": (1, 2),
             "removed": (1, 0), "new": (0, 1)}
    out = []
    for e in m["claims"]:
        sides = {}
        for side in ("from", "to"):
            refs = e.get(side) if isinstance(e, dict) else None
            if not isinstance(refs, list) or not all(
                    isinstance(r, dict) and isinstance(r.get("key"), str) and KEY.fullmatch(r["key"])
                    and isinstance(r.get("number"), str) and r["number"] for r in refs):
                raise ValueError(f"claim map {m['from']} -> {m['to']}: each side is a list of "
                                 f"claims with `key` and `number` ({e!r})")
            sides[side] = [{"key": r["key"], "number": r["number"]} for r in refs]
        change = e.get("change")
        lo = shape.get(change)
        n = (len(sides["from"]), len(sides["to"]))
        if lo is None or not (n == lo or change == "split" and n[0] == 1 and n[1] >= 2):
            raise ValueError(f"claim map {m['from']} -> {m['to']}: {change!r} does not fit "
                             f"{n[0]} claim(s) to {n[1]}")
        out.append({**sides, "change": change})
    return {"from": m["from"], "to": m["to"], "claims": out}


def counterparts(maps: list[dict], version: str, offered: list[str]) -> dict[str, list[dict]]:
    """For each claim key of the page of `version`, its counterparts in the other versions the
    page offers, from the claim maps that relate them: the other version, the `change`, whether
    the other version is the `later` one, and its claims there (`id`, `number`)."""
    out: dict[str, list[dict]] = {}
    for m in maps:
        m = check_claim_map(m)
        for here, there in (("from", "to"), ("to", "from")):
            if m[here] != version or m[there] not in offered:
                continue
            for e in m["claims"]:
                for r in e[here]:
                    out.setdefault(r["key"], []).append({
                        "version": m[there], "later": there == "to", "change": e["change"],
                        "claims": [{"id": f"P:{x['key']}", "number": x["number"]}
                                   for x in e[there]]})
    return out


def audit_order(projects: list[str], audits: dict, stars: dict | None) -> tuple[list[str], str]:
    """The loaded audits of a page, in the order the reader draws on them, and what orders them:
    `"stars"` (the repositories' GitHub star counts, most first, ties in listing order) when the
    site gives a count for every one, else `"listing"` (the registry's order). The first is the
    page's default audit; only audits that pin the same version of the paper as it are listed,
    since claim numbers can differ between versions."""
    loaded = [r for r in projects if (audits.get(r) or {}).get("state") == "loaded"]
    counts = {r: (stars or {}).get(r) for r in loaded}
    by = "stars" if loaded and all(type(n) is int and n >= 0 for n in counts.values()) else "listing"
    if by == "stars":
        loaded.sort(key=lambda r: -counts[r])
    if not loaded:
        return [], by
    from .published import same_version

    def pin(r):
        return ((audits[r].get("paper_version") or {}).get("id"))
    first = pin(loaded[0])
    return [r for r in loaded if (pin(r) is None and first is None) or
            (pin(r) and first and same_version(pin(r), first))], by


def write_paper_site(site: Path, paper: dict, claims: list[dict],
                     page_size: list | tuple | None, pdf_url: str | None,
                     web_dist: Path | None = None, audits: dict | None = None,
                     versions: list[dict] | None = None, version: str | None = None,
                     stars: dict[str, int] | None = None,
                     claim_maps: list[dict] | None = None) -> dict:
    """Write the paper page's data under `site/data/` (and the reader, given its built
    directory). `paper` is the paper's registry entry (its identifier, title, authors, links and
    formalisations), which the reader's panel beside the paper shows; `claims` are from
    `paper_claims`. A paper with several versions has a page per version: `version` is the id of
    this page's, `versions` every version's entry (`page_versions`), and every audit loaded for
    this page must pin this version. `stars` gives each audited repository's GitHub star count,
    which orders the audits the reader draws on (`audit_order`). `claim_maps` relate this
    version's claims to another version's (`claim_map`, `check_claim_map`): each claim they name
    carries its `counterparts`, which the reader shows with a link; they never change a status.
    Replaces whatever is at `site`."""
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
    order, order_by = audit_order(projects, audits_loaded, stars)
    audited = {r for r, a in audits_loaded.items() if a.get("state") == "loaded"} if audits is not None else {f["repository"] for f in paper.get("formalisations", []) if f.get("audits")}
    if claim_maps and not offered:
        raise ValueError("claim maps relate versions: give `versions` and `version`")
    related = counterparts(claim_maps or [], version, [v["id"] for v in offered or []])
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
        first = order[0] if order else projects[0] if projects else None
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
                             "suggested": 0,
                             **({"counterparts": related[c["key"]]} if c["key"] in related else {})})
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
             "audit_order": order, "audit_order_by": order_by,
             **({"stars": {r: stars[r] for r in order if order_by == "stars"}} if stars else {}),
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
