"""The public export.

The export is assembled from fields each paper's `publish` settings allow; it is never a copy of
the private preview with things removed. After assembly every output file is scanned against the
private inputs (manuscript sources, Lean sources, PDFs not approved), and any match blocks the
export.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import evidence as ev
from . import manifest as mf
from .config import Config
from .util import read_json, sha256_bytes, sha256_file, write_json

MIN_LINE = 30  # a private source line at least this long must not occur in the export


class ExportError(RuntimeError):
    pass


def _pick(d: dict | None, keys: list[str]) -> dict | None:
    if d is None:
        return None
    return {k: d[k] for k in keys if k in d}


DECL_KEYS_LEAN = ["name", "kind", "module", "range", "doc", "signature", "value", "uses",
                  "fingerprint", "legacy_hash"]
DECL_KEYS_MIN = ["name", "kind", "module", "fingerprint", "legacy_hash"]


def claim_names(chunk: dict) -> set[str]:
    """The declarations a claim depends on: the definitions its statements unfold to (`decls`)
    and the declarations its clauses name (specification, proof, refutation, witnesses)."""
    names = set(chunk.get("decls", {}))
    for cl in chunk.get("clauses", []):
        names |= {cl[k] for k in ("spec", "accept", "refute", "witness") if cl.get(k)}
        names |= set(cl.get("defs") or [])
        names |= {r["witness"] for r in cl.get("regimes", []) if r.get("witness")}
    return names


def _one_paper(index: dict, chunks: dict, store: dict, pid: str):
    """The release restricted to paper `pid`: its claims, the declaration records of their
    closure, and its own summary, gates and finding totals."""
    from collections import Counter
    kept = {name: c for name, c in chunks.items() if c["paper"] == pid}
    names = set().union(*(claim_names(c) for c in kept.values())) if kept else set()
    claim_ids = {c["id"] for c in kept.values()}
    general = [f for f in index["findings"]["general"]]
    tiers = Counter(f["tier"] for c in kept.values() for f in c.get("findings", [])
                    if not f.get("dismissed"))
    tiers.update(f["tier"] for f in general if not f.get("dismissed"))
    one = {**index,
           "papers": [p for p in index["papers"] if p["id"] == pid],
           "claims": [c for c in index["claims"] if c["id"] in claim_ids],
           "summary": {k: v for k, v in index["summary"].items() if k == pid},
           "gates": {k: v for k, v in (index.get("gates") or {}).items() if k == pid},
           "findings": {"total": dict(tiers), "general": general}}
    one["classes"] = {st: cls for st, cls in index["classes"].items()
                      if st in one["summary"].get(pid, {})}
    return one, kept, {k: d for k, d in store.items() if d.get("name") in names}


def other_papers_material(cfg: Config, pid: str, index: dict, chunks: dict,
                          store: dict) -> list[tuple[str, str, bool]]:
    """What belongs to the papers other than `pid` alone, as (text, what it is, whole word):
    their claim ids, the declarations only their claims use, their review texts and their
    statements' Lean text. A paper the configuration publishes in full (its source and Lean) may
    appear, as a dependency, and gives nothing here. Each paper's manuscript lines are private
    through `private_inputs` already, unless it publishes its source."""
    public = {p.id for p in cfg.papers if p.publish.source_text and p.publish.lean}
    mine = set().union(*(claim_names(c) for c in chunks.values() if c["paper"] == pid))
    by_name = {d.get("name"): d for d in store.values()}
    out = []
    for c in chunks.values():
        if c["paper"] == pid or c["paper"] in public:
            continue
        out.append((c["id"], f"a claim id of paper {c['paper']}", True))
        for n in sorted(claim_names(c) - mine):
            out.append((n, f"a declaration only paper {c['paper']} uses", True))
            for ln in str((by_name.get(n) or {}).get("signature") or "").splitlines():
                if len(ln.strip()) >= MIN_LINE:
                    out.append((ln.strip(), f"Lean text of {n}", False))
        for cl in c.get("clauses", []):
            for r in ((cl.get("spec_review") or {}).get("current", []) +
                      (cl.get("spec_review") or {}).get("stale", [])):
                for ln in (r.get("text") or "").splitlines():
                    if len(ln.strip()) >= MIN_LINE:
                        out.append((ln.strip(), f"a review line of paper {c['paper']}", False))
    return out


def public_claim(chunk: dict, pub) -> dict:
    """The fields of a claim passport that `pub` allows."""
    out = _pick(chunk, ["schema", "release", "id", "paper", "number", "title", "kind", "scope",
                        "scope_note", "scope_reviewed", "status", "status_code", "class", "source_matches", "source_evidence",
                        "source_sha256", "blockers"])
    out["location"] = chunk.get("location") if pub.source_text else None
    out["statement_tex"] = chunk.get("statement_tex") if pub.source_text else None
    a = chunk.get("anchor")
    # `head` (the baseline of the first line) is what the index's top is computed from, so the
    # published claim must keep it for its location to agree with the index.
    out["anchor"] = _pick(a, ["id", "env", "number", "label", "begin", "head", "end", "kind",
                              "source_sha256"] +
                          (["file", "line"] if pub.source_text else [])) if a else None
    clauses = []
    for cl in chunk["clauses"]:
        c = _pick(cl, ["name", "spec", "accept", "refute", "corrects", "witness", "defs", "state",
                       "review", "checks", "evidence"])
        c["regimes"] = [_pick(r, ["name", "description", "witness", "discharged"] +
                              (["type"] if pub.lean else [])) for r in cl.get("regimes", [])]
        if pub.lean and cl.get("statement"):
            c["statement"] = cl["statement"]
            c["proofs"] = cl.get("proofs")
            c["witness_record"] = cl.get("witness_record")
        else:
            c["statement"] = None
        if "spec_review" in cl:
            c["spec_review"] = _reviews(cl["spec_review"], pub.reviews)
        if "def_reviews" in cl:
            c["def_reviews"] = {n: _pick(r, ["state", "by", "kind"])
                                for n, r in cl["def_reviews"].items()}
        clauses.append(c)
    out["clauses"] = clauses
    # A symbol link names paper TeX and a place in the Lean statement: published with both.
    out["symbols"] = list(chunk.get("symbols", [])) if pub.source_text and pub.lean else []
    out["decls"] = dict(chunk.get("decls", {}))
    out["findings"] = [_pick(f, ["id", "tier", "code", "subject", "message", "trigger",
                                 "signal", "dismissed", "dismissal_stale"])
                       for f in chunk["findings"]]
    return out


def _reviews(r: dict | None, with_text: bool) -> dict | None:
    if r is None:
        return None
    keys = ["target", "name", "hash", "by", "kind", "provenance"] + (["text"] if with_text else [])
    return {"state": r["state"], "current": [_pick(x, keys) for x in r.get("current", [])],
            "stale": [_pick(x, keys) for x in r.get("stale", [])]}


def private_inputs(cfg: Config) -> tuple[list[Path], set[str]]:
    """Text files whose lines must not appear, and file hashes that must not appear."""
    texts, hashes = [], set()
    for paper in cfg.papers:
        src = cfg.out_dir / "sources" / paper.id
        if not paper.publish.source_text:
            texts += [p for p in src.rglob("*") if p.suffix in (".tex", ".bib", ".sty", ".cls",
                                                                  ".bbl", ".md")]
        if not paper.publish.pdf:
            hashes |= {sha256_file(p) for p in src.rglob("*.pdf")}
            built = cfg.out_dir / "site" / "data" / "papers" / f"{paper.id}.pdf"
            if built.exists():
                hashes.add(sha256_file(built))
    if not any(p.publish.lean for p in cfg.papers):
        texts += [p for p in cfg.lean_root.rglob("*.lean") if ".lake" not in p.parts]
    return texts, hashes


def scan(out: Path, texts: list[Path], hashes: set[str],
         inventory: Path | None = None,
         strings: list[tuple[str, str, bool]] = ()) -> list[str]:
    """Every leak of a private input into the export, with the JSON field that carries it.

    A line of a private Lean file that the claim inventory also contains (a docstring the
    inventory's description repeats, say) is not a leak of the Lean: the inventory is published
    with the audit. A line of a private manuscript stays private wherever else it appears."""
    published = ""
    if inventory is not None and inventory.exists():
        published = "\n".join(_strings(json.loads(inventory.read_text(encoding="utf-8"))))
    import re
    words = [(re.compile(r"(?<![\w.'])" + re.escape(t) + r"(?![\w.'])") if whole else None, t, what)
             for t, what, whole in strings]
    lines = {}
    for t in texts:
        for ln in t.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if len(s) >= MIN_LINE and not s.startswith(("%", "--", "/-", "import ")) \
                    and not (t.suffix == ".lean" and s in published):
                lines.setdefault(s, t)
    leaks = []
    for f in sorted(out.rglob("*")):
        if not f.is_file():
            continue
        b = f.read_bytes()
        if sha256_bytes(b) in hashes:
            leaks.append(f"{f.relative_to(out)}: is a private PDF")
            continue
        if f.suffix in (".json", ".html", ".js", ".css", ".txt", ".md", ".svg"):
            text = b.decode("utf-8", errors="replace")
            # JSON escapes; compare against the decoded strings as well, and name the field.
            fields = []
            if f.suffix == ".json":
                try:
                    fields = list(_strings_at(json.loads(text)))
                except json.JSONDecodeError:
                    pass
            found = None
            for s, src in lines.items():
                where = next((path for path, v in fields if s in v), None)
                if where is not None or s in text:
                    found = f"a line of {src.name}" + (f" (in {where})" if where else "")
                    break
            for rx, t, what in words if found is None else ():
                hit = (lambda v: rx.search(v)) if rx else (lambda v: t in v)
                where = next((path for path, v in fields if hit(v)), None)
                if where is not None or hit(text):
                    found = f"{what}, {t}" + (f" (in {where})" if where else "")
                    break
            if found:
                leaks.append(f"{f.relative_to(out)}: contains {found}")
    return leaks


def _strings_at(obj, path="$"):
    """Every string in a JSON value, with where it is (`$.clauses[0].regimes[0].description`)."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings_at(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings_at(v, f"{path}[{i}]")


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def export(cfg: Config, out: Path, release: str | None = None,
           web_dist: Path | None = None, paper: str | None = None) -> dict:
    """The approved public fields of a release, scanned for private material. With `paper`, only
    that paper: its claims, the declarations they depend on (their closure) and their reviews,
    scanned also against what belongs to the other papers alone."""
    if paper is not None and paper not in {p.id for p in cfg.papers}:
        raise ExportError(f"no paper {paper} in the configuration")
    rels = ev.releases(cfg.out_dir)
    if not rels:
        raise ExportError("no release: run `prooflens build` first")
    relrec = read_json(cfg.out_dir / "releases" / f"{release}.json") if release \
        else read_json(rels[-1])
    record = ev.load(cfg.out_dir, relrec["evidence"])
    # With the display layer the site is built with (descriptions, printed numbers, symbol
    # links): what is shown changes, never what is assessed.
    from .pipeline import load_display
    index, chunks, store = mf.build(record, relrec["release"], load_display(cfg))
    pubs = {p.id: p.publish for p in cfg.papers}
    full_index, full_chunks, full_store = index, chunks, store
    if paper is not None:
        index, chunks, store = _one_paper(index, chunks, store, paper)

    if out.exists():
        shutil.rmtree(out)
    if web_dist and web_dist.exists():
        shutil.copytree(web_dist, out)
    data = out / "data"
    pidx = _pick(index, ["schema", "release", "evidence", "created", "tool", "lean", "summary",
                         "classes", "gates", "search"])
    pidx["issues"], pidx["site_url"] = cfg.issues, cfg.site_url
    pidx["project"] = _pick(index["project"], ["name", "commit", "dirty", "toolchain",
                                               "repository", "repository_private",
                                               "source_prefix", "source_roots",
                                               "lake_manifest_sha256", "dependencies"])
    from .pipeline import source_info
    pidx["project"].update(source_info(cfg))
    pidx["papers"] = []
    for p in index["papers"]:
        pub = pubs[p["id"]]
        q = _pick(p, ["id", "title", "mode", "revision", "pdf_sha256", "page_size", "note",
                      "published", "published_note", "source_commit"])
        q["root"] = p.get("root") if pub.source_text else None
        q["pdf"] = p["pdf"] if pub.pdf else None
        pidx["papers"].append(q)
        if pub.pdf and p["pdf"]:
            src = cfg.out_dir / "site" / "data" / p["pdf"]
            (data / "papers").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, data / p["pdf"])
    pidx["findings"] = {"total": index["findings"]["total"],
                        "general": [_pick(f, ["id", "tier", "code", "subject", "message"])
                                    for f in index["findings"]["general"]]}
    pidx["claims"] = [_pick(c, ["id", "paper", "number", "title", "kind", "scope", "status",
                                "status_code", "class", "anchor", "counts", "file"]) for c in index["claims"]]
    write_json(data / "index.json", pidx, indent=None)
    for name, chunk in chunks.items():
        write_json(data / "claims" / name, public_claim(chunk, pubs[chunk["paper"]]),
                   indent=None)
    # Declarations are shared between papers: their Lean text and review texts are exported only
    # when every paper allows it. A redacted record is a different record, so it gets its own key.
    shown = [p for p in cfg.papers if paper is None or p.id == paper]
    lean_ok = all(p.publish.lean for p in shown)
    rev_ok = all(p.publish.reviews for p in shown)
    rekey = {}
    for key, d in store.items():
        q = _pick(d, DECL_KEYS_LEAN if lean_ok else DECL_KEYS_MIN)
        q["review"] = _reviews(d.get("review"), rev_ok)
        new = mf.record_key(q)
        rekey[key] = new
        write_json(data / "decls" / f"{new}.json", q, indent=None)
    for name in chunks:
        path = data / "claims" / name
        c = json.loads(path.read_text(encoding="utf-8"))
        c["decls"] = {n: rekey[k] for n, k in c["decls"].items()}
        write_json(path, c, indent=None)
    # The search index, with only what each paper allows.
    srch = mf.search_index(index, chunks)
    pub_search = {"claims": [], "decls": srch["decls"] if lean_ok else []}
    for c in srch["claims"]:
        pub = pubs[c["paper"]]
        pub_search["claims"].append({**c, "statement": c["statement"] if pub.source_text else "",
                                     "lean": c["lean"] if pub.lean else []})
    write_json(data / "search.json", pub_search, indent=None)
    from . import audit
    arx = [p.source["arxiv"] for p in shown if p.source.get("arxiv")]
    write_json(out / audit.NAME, audit.descriptor(
        pidx, cfg.lean_root, author=cfg.author,
        paper_url=f"https://arxiv.org/abs/{arx[0]}" if len(shown) == 1 and arx else None))
    texts, hashes = private_inputs(cfg)
    strings = (other_papers_material(cfg, paper, full_index, full_chunks, full_store)
               if paper is not None else [])
    leaks = scan(out, texts, hashes, cfg.inventory, strings)
    if leaks:
        shutil.rmtree(out)
        raise ExportError("export blocked; private material found:\n  " + "\n  ".join(leaks))
    return {"release": relrec["release"], "evidence": relrec["evidence"], "out": out}
