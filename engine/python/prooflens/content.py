"""The full assessment's content index and paper-number check (#179).

A full assessment probes only what its inventory names. Content search (`retrieval.py`) and the
check of the Lean's references to the paper's numbers (`numbering.py`) read every declaration of
the project's built modules, as zero configuration does: they are read from the Lean facts store
(`simple.LeanFacts`), which a zero-configuration build of the same project shares, so a module
whose index is stored current starts no Lean session.

What this module computes is display: it is kept beside the evidence record it was built with
(`<work>/content/<evidence id>.json`), never inside it, and it changes no status. A record
reassessed from another (`reassessed_from`) shows its content, since the Lean is the same.
"""

from __future__ import annotations

from pathlib import Path

from .util import read_json, write_json

SCHEMA = "prooflens/content@1"


def numbering_claims(pid: str, inv_claims: list[dict], anchors: list[dict]) -> list[dict]:
    """The paper's numbered statements as `numbering.analyse` reads them: one per statement
    environment of the compiled paper (or per heading of a PDF), with the inventory's claim id
    when the inventory maps it, so a reference is attached to that claim."""
    from .assess import match_anchor
    from .simple import anchor_key
    mine = [c for c in inv_claims if c.get("paper") == pid]
    owner = {}
    for c in mine:
        a = match_anchor(c, anchors)
        if a is not None:
            owner.setdefault(id(a), c["id"])
    out = []
    for a in anchors:
        env, num = a.get("env") or "", a.get("number")
        out.append({"id": owner.get(id(a)) or f"{pid}:{anchor_key(a)}", "paper": pid,
                    "kind": env, "number": f"{env.capitalize()} {num}" if num else
                    env.capitalize(), "title": a.get("title") or "",
                    "statement": a.get("statement") or ""})
    return out


def build(cfg, tex: dict, inv_claims: list[dict], auxes: dict, lake: str = "lake", log=print,
          reuse_only: bool = False) -> dict | None:
    """The content index of every declaration of the project's built modules and, for a
    configuration with one paper, the Lean's references to that paper's numbers. None when the
    project has no Lean library or nothing is built; with `reuse_only`, None (and a log line)
    when the facts store does not hold the index."""
    from . import formalization as fz
    from . import numbering as nb
    from .probe import lib_names
    from .retrieval import Retrieval
    from .simple import LeanFacts, StaleLean, built_modules, claim_text
    root = cfg.lean_root
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    if not built:
        return None
    lean = LeanFacts(root, libs, built, unbuilt, cfg.out_dir / "build", lake, log, reuse_only)
    try:
        with lean.store.lock(log):
            full, failed = lean.index(set())
    except StaleLean as e:
        log(f"content index: not written ({e})")
        return None
    notes = []
    if failed:
        notes.append(f"{len(failed)} built module(s) could not be loaded and are not in the "
                     "content index")
    if unbuilt:
        notes.append(f"{len(unbuilt)} module(s) of the project are not built and are not in "
                     "the content index")
    retrieval = Retrieval.build(full)
    numbering = None
    if len(cfg.papers) == 1:
        paper = cfg.papers[0]
        t = tex.get(paper.id) or {}
        claims = numbering_claims(paper.id, inv_claims, t.get("anchors") or [])
        if t.get("mode") == "latex" and claims:
            complete, reason = True, ""
        elif t.get("mode") == "pdf" and claims:
            complete, reason = False, ("the paper is a PDF whose statements were found by "
                                       "their headings, so its numbering may be incomplete")
        else:
            complete, reason = False, "the paper's statements could not be read in this build"
        aux = auxes.get(paper.id)
        inv = nb.inventory(claims, complete, reason,
                           nb.sections_from_aux(aux) if aux is not None else None)
        blocks = nb.module_doc_blocks(root, {d.get("module") for d in full if d.get("module")})
        fy = fz.load(root)
        foreign = fz.foreign_roots(fy, paper.title) if fy and "error" not in fy else set()
        numbering = nb.analyse(full, claims, inv, blocks, foreign, retrieval, claim_text)
        note = nb.drift_note(numbering["pattern"], numbering["references"],
                            suggestions=False)
        if note:
            notes.append(note)
    else:
        notes.append("the Lean's references to the paper's numbers are checked only in a "
                     "configuration with one paper")
    return {"schema": SCHEMA, "retrieval": retrieval.export(), "numbering": numbering,
            "notes": notes, "modules": {"indexed": len(built) - len(failed),
                                        "failed": len(failed), "unbuilt": len(unbuilt)}}


def path(out_dir: Path, eid: str) -> Path:
    return out_dir / "content" / f"{eid}.json"


def save(out_dir: Path, eid: str, content: dict | None) -> None:
    if content is not None:
        write_json(path(out_dir, eid), content, indent=None)


def load(out_dir: Path, eid: str, body: dict | None = None) -> dict | None:
    """The content kept with evidence `eid`, or with the record it was reassessed from."""
    from . import evidence as ev
    seen = set()
    while eid and eid not in seen:
        seen.add(eid)
        p = path(out_dir, eid)
        if p.exists():
            try:
                doc = read_json(p)
            except (OSError, ValueError):
                return None
            return doc if doc.get("schema") == SCHEMA else None
        try:
            body = body if body is not None else ev.load(out_dir, eid)["body"]
        except (OSError, ValueError, KeyError, ev.EvidenceError):
            return None
        eid, body = body.get("provenance", {}).get("reassessed_from"), None
    return None


def claim_references(chunk: dict, numbering: dict | None) -> list[dict]:
    """The references that concern a claim of the full assessment: those citing its number,
    and those in the docstrings and names of the declarations its clauses and links name (not
    of every definition in their closure, which other claims share)."""
    if not numbering:
        return []
    names = {l["name"] for l in chunk.get("links") or [] if l.get("name")}
    for cl in chunk.get("clauses") or []:
        names |= {n for n in (cl.get("spec"), cl.get("accept"), cl.get("refute"),
                              *(cl.get("defs") or [])) if n}
    return [o for o in numbering["references"]
            if chunk["id"] in (o.get("paper") or {}).get("claims", [])
            or o["source"].get("declaration") in names]


def apply(index: dict, chunks: dict, content: dict | None) -> tuple[dict, dict]:
    """The site's index and claims with the content's references to each claim, and the index
    naming the content files (`data/retrieval.json`, `data/numbering.json`)."""
    if not content:
        return index, chunks
    num = content.get("numbering")
    index = {**index, "retrieval": "data/retrieval.json",
             **({"numbering": num["pattern"]} if num else {})}
    if num:
        chunks = {n: {**c, "references": claim_references(c, num)} for n, c in chunks.items()}
    return index, chunks


def write(data: Path, content: dict | None) -> None:
    if not content:
        return
    write_json(data / "retrieval.json", content["retrieval"], indent=None)
    if content.get("numbering"):
        write_json(data / "numbering.json", content["numbering"], indent=None)
