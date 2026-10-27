"""The full assessment's content index and paper-number check (#179).

A full assessment probes only what its inventory names. Content search (`retrieval.py`) and the
check of the Lean's references to the paper's numbers (`numbering.py`) read every declaration of
the project's built modules, as zero configuration does: they are read from the Lean facts store
(`simple.LeanFacts`), which a zero-configuration build of the same project shares, so a module
whose index is stored current starts no Lean session. With several papers, each reference is
attributed to the paper that its declaration's claims, namespace or module belong to, or that
it names, and checked against that paper's numbering.

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


def paper_inventory(pid: str, tex: dict, inv_claims: list[dict], auxes: dict) \
        -> tuple[list[dict], dict]:
    """A paper's numbered statements (`numbering_claims`) and its numbering
    (`numbering.inventory`), complete when the paper's LaTeX compiled."""
    from . import numbering as nb
    t = tex.get(pid) or {}
    claims = numbering_claims(pid, inv_claims, t.get("anchors") or [])
    if t.get("mode") == "latex" and claims:
        complete, reason = True, ""
    elif t.get("mode") == "pdf" and claims:
        complete, reason = False, ("the paper is a PDF whose statements were found by "
                                   "their headings, so its numbering may be incomplete")
    else:
        complete, reason = False, "the paper's statements could not be read in this build"
    aux = auxes.get(pid)
    return claims, nb.inventory(claims, complete, reason,
                                nb.sections_from_aux(aux) if aux is not None else None)


def claim_declarations(c: dict, defs: bool = True) -> set[str]:
    """The declarations an inventory claim names: its clauses' statements, acceptance and
    refutation theorems and witnesses, its links, and (with `defs`) its definitions."""
    names = {l["name"] for l in c.get("links") or [] if isinstance(l, dict) and l.get("name")}
    for cl in c.get("clauses") or []:
        names |= {n for n in (cl.get("spec"), cl.get("accept"), cl.get("refute"),
                              cl.get("witness"), *(cl.get("defs") or [] if defs else ()))
                  if n}
    return names


def several(papers, tex: dict, inv_claims: list[dict], auxes: dict, full: list[dict],
            blocks: list[dict], fy, retrieval, notes: list[str]) -> dict:
    """The Lean's references to the numbers of a configuration's several papers: each is
    attributed to one paper (`numbering.attribute`) and checked against that paper's numbering;
    one that cannot be attributed stays unchecked, with the reason."""
    from . import formalization as fz
    from . import numbering as nb
    from .simple import claim_text
    refs = nb.find_references(full, blocks)
    def named(pid, defs):
        return set().union(set(), *(claim_declarations(c, defs) for c in inv_claims
                                    if c.get("paper") == pid))
    aligned = {p.id: fz.paper_names(fy, p.title) for p in papers}
    own = nb.owners({p.id: named(p.id, True) | aligned[p.id] for p in papers}, full,
                    {p.id: named(p.id, False) | aligned[p.id] for p in papers})
    ids = [(p.id, p.title) for p in papers]
    mine: dict[str, list[dict]] = {p.id: [] for p in papers}
    loose = 0
    for o in refs:
        pid, why = nb.attribute(o, own, ids)
        if pid:
            if o.get("status") == "other-source":
                # A reference that names one of the configuration's papers cites that paper.
                del o["status"], o["detail"]
            o["attributed"] = pid
            mine[pid].append(o)
        elif o.get("status") != "other-source":
            o["status"] = "unchecked"
            o["detail"] = ("the configuration has several papers and nothing says which one it "
                           f"cites: {why}")
            o["message"] = nb.message(o)
            loose += 1
    per, invs = {}, {}
    for p in papers:
        claims, invs[p.id] = paper_inventory(p.id, tex, inv_claims, auxes)
        per[p.id] = nb.analyse(full, claims, invs[p.id], retrieval=retrieval,
                               claim_text=claim_text, refs=mine[p.id])
        note = nb.drift_note(per[p.id]["pattern"], per[p.id]["references"], suggestions=False)
        if note:
            notes.append(f"paper {p.id}: {note}")
    for o in refs:
        o.setdefault("message", nb.message(o))
    if loose:
        notes.append(f"{loose} of the Lean's references to paper numbers are not checked: "
                     "nothing attributes them to one of the configuration's papers")
    return nb.combine(per, invs, refs)


def build(cfg, tex: dict, inv_claims: list[dict], auxes: dict, lake: str = "lake", log=print,
          reuse_only: bool = False) -> dict | None:
    """The content index of every declaration of the project's built modules and the Lean's
    references to the paper's numbers, attributed to one paper each when the configuration
    has several (`several`). None when the project has no Lean library or nothing is built;
    with `reuse_only`, None (and a log line) when the facts store does not hold the index."""
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
    modules = {d.get("module") for d in full if d.get("module")}
    blocks = nb.module_doc_blocks(root, modules) + nb.comment_blocks(root, modules, full)
    fy = fz.load(root)
    if len(cfg.papers) == 1:
        paper = cfg.papers[0]
        claims, inv = paper_inventory(paper.id, tex, inv_claims, auxes)
        foreign = fz.foreign_roots(fy, paper.title) if fy and "error" not in fy else set()
        numbering = nb.analyse(full, claims, inv, blocks, foreign, retrieval, claim_text)
        note = nb.drift_note(numbering["pattern"], numbering["references"],
                            suggestions=False)
        if note:
            notes.append(note)
    else:
        numbering = several(cfg.papers, tex, inv_claims, auxes, full, blocks, fy, retrieval,
                            notes)
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
