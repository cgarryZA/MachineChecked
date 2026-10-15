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


SEG_KEYS = ["text", "segments"]
DECL_KEYS_LEAN = ["name", "kind", "module", "doc", "signature", "value", "uses", "fingerprint",
                  "legacy_hash"]
DECL_KEYS_MIN = ["name", "kind", "module", "fingerprint", "legacy_hash"]


def public_claim(chunk: dict, pub) -> dict:
    """The fields of a claim passport that `pub` allows."""
    out = _pick(chunk, ["schema", "release", "id", "paper", "number", "title", "kind", "scope",
                        "scope_note", "scope_reviewed", "status", "class", "source_matches",
                        "source_sha256"])
    out["location"] = chunk.get("location") if pub.source_text else None
    out["statement_tex"] = chunk.get("statement_tex") if pub.source_text else None
    a = chunk.get("anchor")
    out["anchor"] = _pick(a, ["id", "env", "number", "label", "begin", "end", "source_sha256"] +
                          (["file", "line"] if pub.source_text else [])) if a else None
    clauses = []
    for cl in chunk["clauses"]:
        c = _pick(cl, ["name", "spec", "accept", "refute", "corrects", "witness", "defs", "state",
                       "review", "checks", "ladder"])
        c["regimes"] = [_pick(r, ["name", "description", "witness", "discharged"] +
                              (["type"] if pub.lean else [])) for r in cl.get("regimes", [])]
        if pub.lean and cl.get("statement"):
            c["statement"] = cl["statement"]
            c["proofs"] = cl.get("proofs")
            c["witness_record"] = cl.get("witness_record")
        else:
            c["statement"] = None
        for key in ("spec_review", "def_reviews"):
            if key in cl:
                c[key] = _reviews(cl[key], pub.reviews) if key == "spec_review" else \
                    {n: _reviews(r, pub.reviews) for n, r in cl[key].items()}
        if not pub.source_text:
            for rung in c["ladder"]:
                if rung["rung"] == "source" and rung["state"] == "pass":
                    rung["detail"] = "located in the compiled paper"
        clauses.append(c)
    out["clauses"] = clauses
    keys = DECL_KEYS_LEAN if pub.lean else DECL_KEYS_MIN
    out["decls"] = {n: _pick(d, keys) for n, d in chunk.get("decls", {}).items()}
    out["findings"] = [_pick(f, ["id", "tier", "code", "subject", "message", "trigger",
                                 "dismissed", "dismissal_stale"]) for f in chunk["findings"]]
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


def scan(out: Path, texts: list[Path], hashes: set[str]) -> list[str]:
    """Every leak of a private input into the export."""
    lines = {}
    for t in texts:
        for ln in t.read_text(encoding="utf-8", errors="replace").splitlines():
            s = ln.strip()
            if len(s) >= MIN_LINE and not s.startswith(("%", "--", "/-", "import ")):
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
            # JSON escapes; compare against the decoded strings as well.
            hay = text
            if f.suffix == ".json":
                try:
                    hay = text + "\n" + "\n".join(_strings(json.loads(text)))
                except json.JSONDecodeError:
                    pass
            for s, src in lines.items():
                if s in hay:
                    leaks.append(f"{f.relative_to(out)}: contains a line of {src.name}")
                    break
    return leaks


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
           web_dist: Path | None = None) -> dict:
    rels = sorted((cfg.out_dir / "releases").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not rels:
        raise ExportError("no release: run `prooflens build` first")
    relrec = read_json(cfg.out_dir / "releases" / f"{release}.json") if release \
        else read_json(rels[-1])
    record = ev.load(cfg.out_dir, relrec["evidence"])
    index, chunks = mf.build(record, relrec["release"])
    pubs = {p.id: p.publish for p in cfg.papers}

    if out.exists():
        shutil.rmtree(out)
    if web_dist and web_dist.exists():
        shutil.copytree(web_dist, out)
    data = out / "data"
    pidx = _pick(index, ["schema", "release", "evidence", "created", "tool", "lean", "summary",
                         "classes", "gates"])
    pidx["project"] = _pick(index["project"], ["name", "commit", "dirty", "toolchain",
                                               "lake_manifest_sha256", "dependencies"])
    pidx["papers"] = []
    for p in index["papers"]:
        pub = pubs[p["id"]]
        q = _pick(p, ["id", "title", "mode", "revision", "pdf_sha256", "page_size", "note"])
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
                                "class", "anchor", "counts", "file"]) for c in index["claims"]]
    write_json(data / "index.json", pidx, indent=None)
    for name, chunk in chunks.items():
        write_json(data / "claims" / name, public_claim(chunk, pubs[chunk["paper"]]),
                   indent=None)
    texts, hashes = private_inputs(cfg)
    leaks = scan(out, texts, hashes)
    if leaks:
        shutil.rmtree(out)
        raise ExportError("export blocked; private material found:\n  " + "\n  ".join(leaks))
    return {"release": relrec["release"], "evidence": relrec["evidence"], "out": out}
