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


def variables(spec: dict) -> list[dict]:
    """The statement's variables by number: the prefix's binders, then each "there is" inside
    the conclusion at the number the probe gave it."""
    out: list[dict] = list(spec.get("binders", []))

    def walk(n):
        if n.get("op") == "exists" and isinstance(n.get("var"), int):
            out.extend({} for _ in range(n["var"] + 1 - len(out)))
            out[n["var"]] = {"role": "exists", "name": n.get("name"), "type": n.get("type")}
        for a in n.get("args", []):
            walk(a)
    walk((spec.get("conclusion") or {}).get("logic") or {})
    return out


def _term_pp(spec: dict, where: str) -> dict | None:
    """The pretty-printed term a sub-term's place names: `b:<i>` a binder's type, `x:<i>` the
    type of the i-th variable (a "there is" inside the conclusion included), `c` the
    conclusion, `l:<n>` the n-th part of a conclusion split by its logic."""
    concl = spec.get("conclusion") or {}
    if where == "c":
        return concl
    for tag, items in (("b:", spec.get("binders", [])), ("x:", None)):
        if where.startswith(tag) and where[2:].isdigit():
            items = items if items is not None else variables(spec)
            i = int(where[2:])
            return (items[i] or {}).get("type") if i < len(items) else None
    if where.startswith("l:") and where[2:].isdigit():
        leaves = []

        def walk(n):
            if "leaf" in n:
                leaves.append(n["leaf"])
            for a in n.get("args", []):
                walk(a)
        if concl.get("logic"):
            walk(concl["logic"])
        n = int(where[2:])
        return leaves[n] if n < len(leaves) else None
    return None


def _text(pp) -> str:
    if not isinstance(pp, dict):
        return pp or ""
    return pp.get("text") or "".join(x.get("t", "") for x in pp.get("segments", []))


def target_text(spec: dict, target: dict) -> str | None:
    """What a link's Lean side shows, pinned with the link so that a change in how the statement
    is printed or split (which renumbers sub-terms and parts while the statement stays the same)
    makes the link stale instead of pointing it at another object."""
    vs = variables(spec)
    if "term" in target:
        pp = _term_pp(spec, target.get("in", ""))
        terms = (pp or {}).get("terms") or []
        k = target["term"]
        if not isinstance(k, int) or k >= len(terms):
            return None
        return "".join(x.get("t", "") for x in pp["segments"][terms[k]["from"]:terms[k]["to"]])
    i = target.get("var", target.get("binder"))
    if not isinstance(i, int) or i >= len(vs) or not vs[i]:
        return None
    return f"{vs[i].get('name')} : {_text(vs[i].get('type'))}" if "binder" in target \
        else str(vs[i].get("name"))


def add(cfg: Config, claim: str, symbol: str, decl: str, by: str, var: str | None = None,
        type_of: str | None = None, term: str | None = None) -> dict:
    """Record a link from `symbol` in `claim`'s printed statement to the variable `var` (or the
    type of the binder `type_of`) of the Lean statement `decl`, by `by`."""
    from .pipeline import lean_inputs_digest
    from .promote import latest_record
    if not re.fullmatch(r"(human|llm):\S+", by or ""):
        raise SymbolError("name the link's author as human:NAME or llm:MODEL (--as)")
    if sum(x is not None for x in (var, type_of, term)) != 1:
        raise SymbolError("give exactly one of --var NAME, --type-of NAME and --term WHERE#K")
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
    if term is not None:
        where, _, k = term.partition("#")
        pp = _term_pp(spec, where)
        if pp is None or not k.isdigit() or int(k) >= len(pp.get("terms") or []):
            raise SymbolError(f"{decl} has no sub-term {term!r} (WHERE#K: b:<binder>, x:<variable>, "
                              "c or l:<part>, then the sub-term's number)")
        target = {"decl": decl, "term": int(k), "in": where}
    else:
        names = [b.get("name") for b in variables(spec)]
        want = var if var is not None else type_of
        idx = int(want) if want.isdigit() else (names.index(want) if want in names else None)
        if idx is None or not 0 <= idx < len(names):
            raise SymbolError(f"{decl} has no binder {want!r} (it has "
                              f"{', '.join(str(n) for n in names if n)})")
        target = {"decl": decl, "var": idx} if var is not None else \
            {"decl": decl, "binder": idx, "path": "type"}
    link = {"claim": claim, "symbol": {"tex": symbol, "occurrence": "all"}, "lean": target,
            "by": by, "pins": {"statement": spec.get("fingerprint"), "source": sha256_text(tex),
                               "target": target_text(spec, target)}}
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


def from_reader(cfg: Config, req: dict, web_dist=None) -> None:
    """A symbol link made or removed in the local reader (`POST /api/symbol`), with the checks
    of `symbol add`; the site is then rewritten from the stored evidence (links are display
    only, so nothing is probed or assessed again)."""
    from .pipeline import rebuild_site

    def text(v):
        return None if v is None else str(v)
    if not isinstance(req.get("claim"), str) or not isinstance(req.get("tex"), str):
        raise SymbolError("a symbol request names a claim and a symbol")
    if req.get("action") == "remove":
        remove(cfg, req["claim"], req["tex"])
    elif req.get("action") == "add":
        add(cfg, req["claim"], req["tex"], str(req.get("decl") or ""), req.get("by"),
            var=text(req.get("var")), type_of=text(req.get("type_of")),
            term=text(req.get("term")))
    else:
        raise SymbolError(f"unknown action {req.get('action')!r}")
    rebuild_site(cfg, web_dist, None)
