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

# How a link names a Lean expression: by its position in the proposition (Lean's
# `SubExpr.Pos`), with a prefix for a property carried by an object's type (`<object>#<field>:`)
# and for an equation of a definition (`<theorem>:`). A link records it; a link made under
# another scheme, or by place and number in an earlier display (`term`), names nothing now.
IDS = "subexpr-pos@1"


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


def tree(spec: dict) -> dict:
    """The statement as one tree (`tree`, from the probe): each binder that opens it a node (its
    role as `op`, its place in `binders` as `var`) whose one part is the rest of the statement. A
    record of an earlier probe, without one, is rebuilt from its binders and its conclusion's
    `logic` in the same form."""
    t = spec.get("tree")
    if isinstance(t, dict):
        return t
    concl = spec.get("conclusion") or {}
    node = concl.get("logic") or ({"leaf": concl} if concl else {})
    for i, b in reversed(list(enumerate(spec.get("binders") or []))):
        node = {**b, "op": b.get("role"), "var": i, "args": [node]}
    return node


def nodes(spec: dict):
    """Every node of the statement's tree, in reading order, hypotheses' own trees included."""
    stack = [tree(spec)]
    while stack:
        n = stack.pop()
        if not isinstance(n, dict):
            continue
        yield n
        stack.extend(reversed([n.get("logic"), *(n.get("args") or [])]))


def conclusion_tree(spec: dict) -> dict:
    """The part of the tree under the binders that open the statement."""
    n = tree(spec)
    for _ in spec.get("binders") or []:
        n = (n.get("args") or [{}])[0]
    return n


def variables(spec: dict) -> list[dict]:
    """The statement's variables by number: the binders that open it, then each variable bound
    inside its conclusion or inside a hypothesis, at the number the probe gave it."""
    out: list[dict] = list(spec.get("binders", []))
    opening = len(out)
    for n in nodes(spec):
        v = n.get("var")
        if n.get("op") in ("exists", "forall") and isinstance(v, int) and v >= opening:
            out.extend({} for _ in range(v + 1 - len(out)))
            out[v] = {"role": n["op"], "name": n.get("name"), "type": n.get("type"),
                      "id": n.get("id")}
    return out


def _term_pp(spec: dict, where: str) -> dict | None:
    """The pretty-printed term a sub-term's place names: `b:<i>` a binder's type, `x:<i>` the
    type of the i-th variable (one bound inside the conclusion included), `c` the conclusion,
    `l:<n>` the n-th part of the conclusion's tree."""
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
        shape = conclusion_tree(spec)
        if "leaf" not in shape:
            walk(shape)
        n = int(where[2:])
        return leaves[n] if n < len(leaves) else None
    return None


def printed(spec: dict):
    """Every printed expression of a statement record: the binders' types, the conclusion, the
    leaves and types of its tree (the hypotheses' own trees included), and the exact
    proposition."""
    for b in spec.get("binders", []):
        yield b.get("type")
    yield spec.get("conclusion") or {}
    for n in nodes(spec):
        yield n.get("leaf")
        yield n.get("type")
    yield spec.get("exact")


def _objects(spec: dict):
    """The objects of a statement record whose types can carry properties: every node of its
    tree, the hypotheses' own trees included, and the objects inside a hypothesis as a record
    written before the tree lists them (`objects`)."""
    for n in nodes(spec):
        yield n
        yield from n.get("objects") or []


def carried(spec: dict):
    """The printed statement of every field an object's type carries, as it applies to that
    object; its identities are prefixed by the object's and the field's (`<id>#<field>:`)."""
    for o in _objects(spec):
        for p in o.get("properties") or []:
            yield p.get("type")


def defined(spec: dict):
    """What a linked definition says (`definition`, beside a link's statement), printed: its
    parameters' types, body and result, and each equation's statement, parameters and equation,
    whose identities are prefixed by the equation theorem's name."""
    d = spec.get("definition") or {}
    for x in d.get("params") or []:
        yield x.get("type")
    yield d.get("body")
    yield d.get("result")
    for q in d.get("equations") or []:
        yield q.get("statement")
        yield q.get("equation")
        for x in q.get("params") or []:
            yield x.get("type")


def term_by_id(spec: dict, at: str) -> str | None:
    """The text of the expression whose identity is `at`, as the probe records it, wherever the
    statement record prints it: a printed expression itself (`id`), a sub-term (`terms[].id`) or
    one occurrence of a variable (`segments[].at`) of the statement's parts, of the properties
    its objects' types carry, or of what a linked definition says."""
    for pp in (*printed(spec), *carried(spec), *defined(spec)):
        if not isinstance(pp, dict):
            continue
        if pp.get("id") == at and pp.get("segments"):
            return _text(pp)
        for t in pp.get("terms") or []:
            if t.get("id") == at:
                return "".join(x.get("t", "") for x in pp["segments"][t["from"]:t["to"]])
        for x in pp.get("segments") or []:
            if x.get("at") == at:
                return x.get("t", "")
    return None


def _text(pp) -> str:
    if not isinstance(pp, dict):
        return pp or ""
    return pp.get("text") or "".join(x.get("t", "") for x in pp.get("segments", []))


def target_text(spec: dict, target: dict) -> str | None:
    """What a link's Lean side shows, pinned with the link so that a change in how the statement
    is printed or split (which renumbers sub-terms and parts while the statement stays the same)
    makes the link stale instead of pointing it at another object. A link by place and number in
    an earlier display (`term`) names nothing."""
    vs = variables(spec)
    if "at" in target:
        return term_by_id(spec, target["at"]) if isinstance(target["at"], str) else None
    if "term" in target:
        return None
    i = target.get("var", target.get("binder"))
    if not isinstance(i, int) or i >= len(vs) or not vs[i]:
        return None
    return f"{vs[i].get('name')} : {_text(vs[i].get('type'))}" if "binder" in target \
        else str(vs[i].get("name"))


def target_id(spec: dict, target: dict) -> str | None:
    """The identity of the binder a link to a variable or a binder's type names (its position in
    the proposition), pinned with the link: a variable is named by its number, which a change in
    how the statement is split can give to another variable of the same name."""
    i = target.get("var", target.get("binder"))
    if "at" in target or "term" in target or not isinstance(i, int):
        return None
    vs = variables(spec)
    return (vs[i] or {}).get("id") if i < len(vs) else None


# Why a link is stale, for the reader: what changed, and what to do.
STALE = {
    "statement": "the Lean statement changed since the link was made",
    "source": "the paper's text changed since the link was made",
    "excerpt": "the typeset passage changed since the link was made",
    "missing": "the Lean statement no longer has the object it names",
    "target": "the Lean object at its place is a different one now",
    "unpinned": "it was made without the text of its Lean object, so a change cannot be detected",
    "positional": "it names its Lean object by place and number in an earlier display",
    "ids": "it was made with an earlier scheme of identities",
}


def stale_reasons(spec: dict, target: dict, pins: dict, moved: str | None) -> list[str]:
    """Why a link no longer holds, as codes of `STALE`, none when it holds. `moved` is `source` or
    `excerpt` when the paper side changed."""
    out = []
    if pins.get("statement") != spec.get("fingerprint"):
        out.append("statement")
    if moved:
        out.append(moved)
    if "term" in target:
        out.append("positional")
    elif target_text(spec, target) is None:
        out.append("missing")
    elif ("target" in pins and pins["target"] != target_text(spec, target)) or \
            ("binder_id" in pins and pins["binder_id"] != target_id(spec, target)):
        out.append("target")
    elif "at" in target and "target" not in pins:
        out.append("unpinned")
    if pins.get("ids", IDS) != IDS:
        out.append("ids")
    return out


def add(cfg: Config, claim: str, symbol: str, decl: str, by: str, var: str | None = None,
        type_of: str | None = None, term: str | None = None, at: str | None = None) -> dict:
    """Record a link from `symbol` in `claim`'s printed statement to the variable `var` (or the
    type of the binder `type_of`) of the Lean statement `decl`, by `by`."""
    from .pipeline import lean_inputs_digest
    from .promote import latest_record
    if not re.fullmatch(r"(human|llm):\S+", by or ""):
        raise SymbolError("name the link's author as human:NAME or llm:MODEL (--as)")
    if sum(x is not None for x in (var, type_of, term, at)) != 1:
        raise SymbolError("give exactly one of --var NAME, --type-of NAME, --term WHERE#K and "
                          "--at ID")
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
    # The link is made on the passage the reader typesets, when it typesets one, and is pinned
    # to its rendering context too; otherwise on the statement's source text.
    excerpt = chunk.get("excerpt") or {}
    shown = excerpt.get("text") if excerpt.get("ready") else None
    tex = shown or chunk.get("statement_tex")
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
        # A sub-term is recorded by its identity in the proposition, which no change in how the
        # statement is printed or split can move.
        tid = pp["terms"][int(k)].get("id")
        if not tid:
            raise SymbolError(f"the last build gives {decl}'s sub-term {term!r} no identity: run "
                              "`machinechecked build` with this version first")
        target = {"decl": decl, "at": tid}
    elif at is not None:
        if term_by_id(spec, at) is None:
            raise SymbolError(f"{decl} has no sub-term with the identity {at!r}")
        target = {"decl": decl, "at": at}
    else:
        names = [b.get("name") for b in variables(spec)]
        want = var if var is not None else type_of
        idx = int(want) if want.isdigit() else (names.index(want) if want in names else None)
        if idx is None or not 0 <= idx < len(names):
            raise SymbolError(f"{decl} has no binder {want!r} (it has "
                              f"{', '.join(str(n) for n in names if n)})")
        target = {"decl": decl, "var": idx} if var is not None else \
            {"decl": decl, "binder": idx, "path": "type"}
    bid = target_id(spec, target)
    link = {"claim": claim, "symbol": {"tex": symbol, "occurrence": "all"}, "lean": target,
            "by": by, "pins": {"statement": spec.get("fingerprint"), "source": sha256_text(tex),
                               "target": target_text(spec, target), "ids": IDS,
                               **({"binder_id": bid} if bid else {}),
                               **({"excerpt": excerpt["fingerprint"]} if shown else {})}}
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
            term=text(req.get("term")), at=text(req.get("at")))
    else:
        raise SymbolError(f"unknown action {req.get('action')!r}")
    rebuild_site(cfg, web_dist, None)
