"""Symbol links: a symbol of a claim's printed statement linked to an object of its Lean
statement, recorded as a named person's assertion (`machinechecked symbol add`).

A link says that a symbol of the paper (`\\nu`, `\\mathbb R^j`) is a given variable of the Lean
statement, or a given binder's type, or one of its sub-terms, including one inside a definition
expanded at its arguments or an equation of a definition; for a claim that only defines, the
Lean side is one of its definitions. A symbol takes every occurrence in the claim, or only the
occurrences the link numbers: those are one object of the paper, which the link names, and
another object printed with the same symbol is linked apart. Saying so is what a statement review
checks, so a link is kept as its author's: it names them, it is pinned to the statement's
fingerprint and to the claim's printed text, it is shown as stale when either changes, and no
status reads it (docs/SYMBOL_LINKS.md). The links are kept in the configuration's `symbols` file
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


MATH = re.compile(r"\$\$.*?\$\$|\$.*?\$|\\\(.*?\\\)|\\\[.*?\\\]|"
                  r"\\begin\{(?:equation|align|gather)\*?\}.*?\\end\{(?:equation|align|gather)\*?\}",
                  re.S)


def token(symbol: str) -> str:
    """The pattern of `symbol` as a whole command or letter (`\\nu` is not the start of
    `\\nuexample`, `a` not the a of `\\mathbb`); the reader marks symbols by the same pattern
    (`web/src/lib/symbolmarks.js`)."""
    return ((r"(?<![A-Za-z\\])" if re.match(r"[A-Za-z]", symbol) else "") + re.escape(symbol)
            + (r"(?![A-Za-z])" if re.search(r"[A-Za-z]$", symbol) else ""))


def _in_math(tex: str, symbol: str) -> bool:
    """Whether `symbol` occurs in a math part of `tex` (between $…$, \\(…\\), \\[…\\] or in a
    display environment), as a whole command (`\\nu` is not the start of `\\nuexample`)."""
    return any(re.search(token(symbol), s) for s in MATH.findall(tex))


def math_pieces(excerpt: dict | None, tex: str | None) -> list[str]:
    """The pieces of mathematics a link's occurrences are counted in, in reading order: those
    of the typeset passage (`excerpt.blocks`, in the order the reader typesets them,
    `web/src/lib/excerpt.js`) when the link is made on it, else the math parts of the source
    text."""
    if excerpt is None:
        return MATH.findall(tex or "")
    out: list[str] = []

    def inline(nodes):
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            if isinstance(n.get("text"), str):
                continue
            if isinstance(n.get("math"), str):
                out.append(n["math"])
            elif isinstance(n.get("children"), list):
                inline(n["children"])

    def blocks(bs):
        for b in bs or []:
            if not isinstance(b, dict):
                continue
            if isinstance(b.get("p"), list):
                inline(b["p"])
            elif isinstance(b.get("math"), str):
                out.append(b["math"])
            elif isinstance(b.get("items"), list):
                for it in b["items"]:
                    blocks((it or {}).get("blocks"))
    blocks(excerpt.get("blocks"))
    return out


def occurrences(pieces: list[str], symbol: str) -> int:
    """How many times `symbol` occurs in `pieces`, as whole commands or letters: its
    occurrences are numbered from 1 in this order."""
    return sum(len(re.findall(token(symbol), p)) for p in pieces)


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


def definition_statement(rec: dict) -> dict:
    """A definition's record (the declaration store's, or a link's `definition`) as a statement
    record whose parts a link or an alignment can name: its parameters as the variables that
    open it, and what it says (`definition`). A claim that only defines has no proposition of
    its own; its definitions are what its sentences correspond to."""
    binders = [{"name": p.get("name"), "role": "forall", "type": p.get("type"),
                **({"id": p["id"]} if p.get("id") else {})}
               for p in rec.get("params") or [] if isinstance(p, dict)]
    return {"binders": binders, "definition": rec, "fingerprint": rec.get("fingerprint")}


# How many parts stored on their own (expansions, pages of equations) one look-up reads at most.
PARTS_READ = 256


def _is_ref(x) -> bool:
    return isinstance(x, dict) and "key" in x and set(x) <= {"at", "id", "name", "key"}


def _expansion_printed(x: dict):
    """What one expansion prints: its arguments, its parameters' types, its body and result,
    and each equation that applies at those arguments."""
    for a in x.get("args") or []:
        if isinstance(a, dict):
            yield a.get("value")
    for p in x.get("params") or []:
        if isinstance(p, dict):
            yield p.get("type")
    yield x.get("body")
    yield x.get("result")
    for q in x.get("equations") or []:
        if isinstance(q, dict):
            yield q.get("statement")
            yield q.get("equation")
            for p in q.get("params") or []:
                if isinstance(p, dict):
                    yield p.get("type")


def _find(pp: dict, at: str) -> str | None:
    if pp.get("id") == at and pp.get("segments"):
        return _text(pp)
    for t in pp.get("terms") or []:
        if t.get("id") == at:
            return "".join(x.get("t", "") for x in pp["segments"][t["from"]:t["to"]])
    for x in pp.get("segments") or []:
        if x.get("at") == at:
            return x.get("t", "")
    return None


def term_by_id(spec: dict, at: str, part=None) -> str | None:
    """The text of the expression whose identity is `at`, as the probe records it, wherever the
    statement record prints it: a printed expression itself (`id`), a sub-term (`terms[].id`) or
    one occurrence of a variable (`segments[].at`) of the statement's parts, of the properties
    its objects' types carry, or of what a linked definition says; and inside a definition
    expanded at the arguments of one of its applications (`expansions`, whose identities extend
    the application's: `/1/0=` and below), nested ones included, and in every equation of a
    linked definition. An expansion or a page of equations the site stores on its own is read
    with `part(key)` (`Snapshot.part`); without it, only what the record holds is searched."""
    todo = [pp for pp in (*printed(spec), *carried(spec), *defined(spec)) if isinstance(pp, dict)]
    d = spec.get("definition") or {}
    pages = list(d.get("equations_more") or []) if part is not None else []
    reads = 0
    while todo or pages:
        if not todo:
            # The further equations of a linked definition, a page at a time.
            ref = pages.pop(0)
            reads += 1
            page = part(ref.get("key")) if isinstance(ref, dict) and reads <= PARTS_READ else None
            for q in (page or {}).get("equations") or []:
                if isinstance(q, dict):
                    todo += [x for x in (q.get("statement"), q.get("equation"),
                                         *((p or {}).get("type") for p in q.get("params") or []))
                             if isinstance(x, dict)]
            continue
        pp = todo.pop(0)
        found = _find(pp, at)
        if found is not None:
            return found
        for x in pp.get("expansions") or []:
            if not isinstance(x, dict):
                continue
            # An expansion holds only identities that extend its own.
            if isinstance(x.get("id"), str) and not at.startswith(x["id"]):
                continue
            if _is_ref(x):
                reads += 1
                if part is None or reads > PARTS_READ:
                    continue
                x = part(x["key"])
                if not isinstance(x, dict):
                    continue
            todo += [p for p in _expansion_printed(x) if isinstance(p, dict)]
    return None


def _text(pp) -> str:
    if not isinstance(pp, dict):
        return pp or ""
    return pp.get("text") or "".join(x.get("t", "") for x in pp.get("segments", []))


def target_text(spec: dict, target: dict, part=None) -> str | None:
    """What a link's Lean side shows, pinned with the link so that a change in how the statement
    is printed or split (which renumbers sub-terms and parts while the statement stays the same)
    makes the link stale instead of pointing it at another object. A link by place and number in
    an earlier display (`term`) names nothing. `part` reads what the site stores on its own
    (`term_by_id`)."""
    vs = variables(spec)
    if "at" in target:
        return term_by_id(spec, target["at"], part) if isinstance(target["at"], str) else None
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


def spec_of(lean: dict, decl: str) -> dict:
    """The statement record a link's declaration is read in: the clause's proposition, or the
    definition (`definition_statement`) of a claim that only defines."""
    s = (lean.get("specs") or {}).get(decl)
    if s:
        return s
    d = (lean.get("decls") or {}).get(decl)
    return definition_statement(d) if isinstance(d, dict) else {}


def claim_decls(chunk: dict) -> tuple[set[str], set[str]]:
    """The declarations a link of a claim may point into: its clauses' propositions, and the
    definitions of a clause that has none (a claim that only defines)."""
    specs = {cl["spec"] for cl in chunk.get("clauses") or [] if cl.get("spec")}
    defs = {d for cl in chunk.get("clauses") or [] if not cl.get("spec")
            for d in cl.get("defs") or []}
    return specs, defs


def _occurrence(ln: dict) -> set[int] | None:
    """The occurrences a link names, None when it takes every one."""
    o = (ln.get("symbol") or {}).get("occurrence", "all")
    return set(o) if isinstance(o, list) else None


def _object(ln: dict) -> str | None:
    return (ln.get("symbol") or {}).get("object")


def symbol_record(symbol: str, pieces: list[str], occurrence=None,
                  paper_object: str | None = None) -> dict:
    """The paper side of a link: the symbol, the occurrences it takes (every one, or those
    numbered, from 1, in reading order, with how many there were: `of`) and the paper object
    they are (`object`, the author's name for it). Occurrences named apart are one object, so a
    link naming them names its object."""
    out: dict = {"tex": symbol, "occurrence": "all"}
    if paper_object is not None:
        name = str(paper_object).strip()
        if not name or len(name) > 120:
            raise SymbolError("name the paper object in up to 120 characters (--object)")
        out["object"] = name
    if occurrence:
        n = occurrences(pieces, symbol)
        try:
            want = sorted({int(k) for k in occurrence})
        except (TypeError, ValueError):
            raise SymbolError("an occurrence is its number, from 1 in reading order") from None
        bad = [k for k in want if not 1 <= k <= n]
        if bad:
            raise SymbolError(f"{symbol!r} occurs {n} time(s) in the mathematics; there is no "
                              f"occurrence {', '.join(map(str, bad))}")
        if "object" not in out:
            raise SymbolError("occurrences linked apart from the others are one object of the "
                              "paper: name it (--object)")
        out.update(occurrence=want, of=n)
    return out


def _clashes(links: list[dict], claim: str, new: dict) -> list[dict]:
    """The links of `claim` that take an occurrence of `new`'s symbol for another paper object;
    the link of the same object is replaced, not counted."""
    mine = _occurrence({"symbol": new})
    out = []
    for ln in links:
        if ln.get("claim") != claim or (ln.get("symbol") or {}).get("tex") != new["tex"] or \
                _object(ln) == new.get("object"):
            continue
        theirs = _occurrence(ln)
        if mine is None or theirs is None or mine & theirs:
            out.append(ln)
    return out


def add(cfg: Config, claim: str, symbol: str, decl: str, by: str, var: str | None = None,
        type_of: str | None = None, term: str | None = None, at: str | None = None,
        occurrence=None, paper_object: str | None = None) -> dict:
    """Record a link from `symbol` in `claim`'s printed statement to the variable `var` (or the
    type of the binder `type_of`, or a sub-term) of the Lean statement or definition `decl`, by
    `by`. With `occurrence` (numbers from 1) the link takes only those occurrences of the
    symbol, which are the paper object `paper_object`; another object printed with the same
    symbol is linked apart."""
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
    specs, defs = claim_decls(chunk)
    if decl not in specs | defs:
        raise SymbolError(f"{decl} is not a statement or a definition of {claim}")
    # The link is made on the passage the reader typesets, when it typesets one, and is pinned
    # to its rendering context too; otherwise on the statement's source text.
    excerpt = chunk.get("excerpt") or {}
    shown = excerpt.get("text") if excerpt.get("ready") else None
    tex = shown or chunk.get("statement_tex")
    if not tex or not _in_math(tex, symbol):
        raise SymbolError(f"{symbol!r} does not occur in the mathematics of {claim}'s printed "
                          "statement")
    sym = symbol_record(symbol, math_pieces(excerpt if shown else None, tex), occurrence,
                        paper_object)
    spec = spec_of(body.get("lean") or {}, decl)
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
    link = {"claim": claim, "symbol": sym, "lean": target,
            "by": by, "pins": {"statement": spec.get("fingerprint"), "source": sha256_text(tex),
                               "target": target_text(spec, target), "ids": IDS,
                               **({"binder_id": bid} if bid else {}),
                               **({"excerpt": excerpt["fingerprint"]} if shown else {})}}
    data = read_json(cfg.symbols) if cfg.symbols.exists() else {"schema": SCHEMA, "links": []}
    clash = _clashes(data.get("links", []), claim, sym)
    if clash:
        def what(ln):
            occ = _occurrence(ln)
            return (("every occurrence" if occ is None else
                     "occurrence " + ", ".join(map(str, sorted(occ))))
                    + (f" (object {_object(ln)!r})" if _object(ln) else "")
                    + f", by {ln.get('by')}")
        raise SymbolError(f"{symbol!r} in {claim} is linked already at "
                          + "; ".join(what(ln) for ln in clash)
                          + ": two objects of the paper never share an occurrence. Remove that "
                          "link, or name occurrences it does not take (--occurrence)")
    # A link replaces the one of the same symbol and paper object.
    data["links"] = [ln for ln in data.get("links", [])
                     if not (ln.get("claim") == claim and (ln.get("symbol") or {}).get("tex") == symbol
                             and _object(ln) == sym.get("object"))]
    data["links"].append(link)
    write_json(cfg.symbols, data)
    return link


def remove(cfg: Config, claim: str, symbol: str, paper_object: str | None = None) -> int:
    """Remove the links of `symbol` in `claim`: every one, or with `paper_object` only that
    object's."""
    if not cfg.symbols.exists():
        return 0
    data = read_json(cfg.symbols)
    before = len(data.get("links", []))
    data["links"] = [ln for ln in data.get("links", [])
                     if not (ln.get("claim") == claim and (ln.get("symbol") or {}).get("tex") == symbol
                             and (paper_object is None or _object(ln) == paper_object))]
    write_json(cfg.symbols, data)
    return before - len(data["links"])


def symbol_text(sym: dict) -> str:
    """A link's paper side in words: the symbol, its object and the occurrences it takes."""
    occ = sym.get("occurrence", "all")
    return (sym.get("tex", "")
            + (f" ({sym['object']})" if sym.get("object") else "")
            + (f" at occurrence {', '.join(map(str, occ))} of {sym.get('of')}"
               if isinstance(occ, list) else ""))


def listing(cfg: Config) -> str:
    if not cfg.symbols.exists():
        return "no symbol links"
    return "\n".join(f"{ln['claim']}  {symbol_text(ln['symbol'])} -> {json.dumps(ln['lean'])}  "
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
    occ = req.get("occurrences")
    if occ is not None and not (isinstance(occ, list) and all(type(k) is int for k in occ)):
        raise SymbolError("`occurrences` is a list of numbers, from 1 in reading order")
    if req.get("action") == "remove":
        remove(cfg, req["claim"], req["tex"], text(req.get("object")) or None)
    elif req.get("action") == "add":
        add(cfg, req["claim"], req["tex"], str(req.get("decl") or ""), req.get("by"),
            var=text(req.get("var")), type_of=text(req.get("type_of")),
            term=text(req.get("term")), at=text(req.get("at")), occurrence=occ or None,
            paper_object=text(req.get("object")) or None)
    else:
        raise SymbolError(f"unknown action {req.get('action')!r}")
    rebuild_site(cfg, web_dist, None)
