"""Symbol links: a symbol of a claim's printed statement linked to an object of its Lean
statement, recorded as a named person's assertion (`machinechecked symbol add`).

A link says that a symbol of the paper (`\\nu`, `\\mathbb R^j`) is a given variable of the Lean
statement, or a given binder's type. Saying so is what a statement review checks, so a link is
kept as its author's: it names them, it is pinned to the statement's fingerprint and to the
claim's printed text, it is shown as stale when either changes, and no status reads it
(docs/SYMBOL_LINKS.md). The links are kept in the configuration's `symbols` file
(`symbols.json` by default).
"""

from __future__ import annotations

import json
import re

from . import manifest as mf
from .config import Config
from .util import read_json, sha256_text, write_json

SCHEMA = "machinechecked/symbols@1"


class SymbolError(RuntimeError):
    pass


def _in_math(tex: str, symbol: str) -> bool:
    """Whether `symbol` occurs in a math part of `tex` (between $…$, \\(…\\), \\[…\\] or in a
    display environment), as a whole command (`\\nu` is not the start of `\\nuexample`)."""
    pat = ((r"(?<![A-Za-z\\])" if re.match(r"[A-Za-z]", symbol) else "") + re.escape(symbol)
           + (r"(?![A-Za-z])" if re.search(r"[A-Za-z]$", symbol) else ""))
    spans = re.findall(r"\$\$.*?\$\$|\$.*?\$|\\\(.*?\\\)|\\\[.*?\\\]|"
                       r"\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\}",
                       tex, re.S)
    return any(re.search(pat, s) for s in spans)


def add(cfg: Config, claim: str, symbol: str, decl: str, by: str, var: str | None = None,
        type_of: str | None = None) -> dict:
    """Record a link from `symbol` in `claim`'s printed statement to the variable `var` (or the
    type of the binder `type_of`) of the Lean statement `decl`, by `by`."""
    from .pipeline import lean_inputs_digest
    from .promote import latest_record
    if not re.fullmatch(r"(human|llm):\S+", by or ""):
        raise SymbolError("name the link's author as human:NAME or llm:MODEL (--as)")
    if (var is None) == (type_of is None):
        raise SymbolError("give exactly one of --var NAME and --type-of NAME")
    record = latest_record(cfg)
    body = record["body"]
    if body["provenance"].get("lean_inputs_sha256") != lean_inputs_digest(cfg):
        raise SymbolError("the Lean project changed since the last build: run `machinechecked "
                          "build` first, so the link is pinned to the current statement")
    _, chunks, _ = mf.build(record, "symbols")
    chunk = next((c for c in chunks.values() if c["id"] == claim), None)
    if chunk is None:
        raise SymbolError(f"no claim {claim}")
    if decl not in {cl.get("spec") for cl in chunk["clauses"]}:
        raise SymbolError(f"{decl} is not a statement of {claim}")
    tex = chunk.get("statement_tex")
    if not tex or not _in_math(tex, symbol):
        raise SymbolError(f"{symbol!r} does not occur in the mathematics of {claim}'s printed "
                          "statement")
    spec = (body.get("lean") or {}).get("specs", {}).get(decl) or {}
    names = [b.get("name") for b in spec.get("binders", [])]
    want = var if var is not None else type_of
    idx = int(want) if want.isdigit() else (names.index(want) if want in names else None)
    if idx is None or not 0 <= idx < len(names):
        raise SymbolError(f"{decl} has no binder {want!r} (it has {', '.join(names)})")
    target = {"decl": decl, "var": idx} if var is not None else \
        {"decl": decl, "binder": idx, "path": "type"}
    link = {"claim": claim, "symbol": {"tex": symbol, "occurrence": "all"}, "lean": target,
            "by": by, "pins": {"statement": spec.get("fingerprint"), "source": sha256_text(tex)}}
    data = read_json(cfg.symbols) if cfg.symbols.exists() else {"schema": SCHEMA, "links": []}
    data["links"] = [ln for ln in data.get("links", [])
                     if not (ln.get("claim") == claim and (ln.get("symbol") or {}).get("tex") == symbol)]
    data["links"].append(link)
    write_json(cfg.symbols, data)
    return link


def remove(cfg: Config, claim: str, symbol: str) -> int:
    if not cfg.symbols.exists():
        return 0
    data = read_json(cfg.symbols)
    before = len(data.get("links", []))
    data["links"] = [ln for ln in data.get("links", [])
                     if not (ln.get("claim") == claim and (ln.get("symbol") or {}).get("tex") == symbol)]
    write_json(cfg.symbols, data)
    return before - len(data["links"])


def listing(cfg: Config) -> str:
    if not cfg.symbols.exists():
        return "no symbol links"
    return "\n".join(f"{ln['claim']}  {ln['symbol']['tex']} -> {json.dumps(ln['lean'])}  "
                     f"(by {ln['by']})" for ln in read_json(cfg.symbols).get("links", []))
