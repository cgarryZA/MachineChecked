"""Connections between objects of different Lean results (#146): a workspace's evidence
reference `{"connection": {...}}` (`workspace.py`).

A paper proves several properties of one object (a profile, a solution, a force) across several
results, and the Lean may carry that object through structures, projections, local choices and
transformations. Declaration names and a dependency closure do not show that two results concern
the same object; a connection records how one object is related to another, exactly:

- its two ends, each an object of a Lean result: a variable of a declaration's statement
  (`{decl, var}`, pinned to the binder's identity, name and type), a sub-term of it (`{decl,
  at}`, pinned to its text), a declaration as a whole (`{decl}`), the argument an application
  gives one of its callee's parameters (`{app, param}`) or a local of a fact inside a proof
  (`{fact, local}`);
- its relation, one of `RELATIONS`, with the scope that relation needs: the domain an equality
  or a restriction holds on, the filter an eventual equality holds along, the equivalence (and
  its measure) classes are equal modulo, the field a projection takes, the property a
  transformation preserves;
- the conditions under which it holds, in words;
- what supports it: theorems, applications or facts inside a proof that state it, and for a
  definitional connection the definitions that unfold.

Support is evidence of the relation. A type or a definition is refused as support, and so is a
declaration that the statements of both ends use: a shared type or a shared dependency does not
relate two objects. Two witnesses of separate existence results are separate choices: a `shared
witness` connection between them is refused without evidence that relates them (a result other
than the existence results themselves, and not one both their proofs use); naming both witnesses
`x` changes nothing, since an end is identified by its declaration and its binder's identity. A
single result `∃ x, P x ∧ Q x` gives one witness both facts are about: a connection between two
ends at that one binder needs nothing further.

Each connection is pinned to its ends and its support and goes stale alone, when one of them
changes; an end recorded at a binder or sub-term that the build now numbers otherwise is stale,
never moved to the new one. A composition identification can cite connections
(`composition.py`): an equality that holds on a domain, along a filter or between classes, used
to identify the objects outright, leaves the composition a `local to global` (or, for classes, an
`equality transport`) obligation, open until something other than such connections discharges
it. Connections are workspace records: prior interpretations, shown at the informed stage and
published with the findings and compositions that cite them. Nothing here changes a status.
"""

from __future__ import annotations

import copy

RELATIONS = ("definitional", "projection", "equal", "equal on a domain", "eventually equal",
             "equal as classes", "restriction", "coercion", "transformation", "shared witness")
# The scope each relation is stated with, required: its field and what it says.
SCOPE = {"equal on a domain": ("domain", "the domain it holds on"),
         "restriction": ("domain", "the domain one end is the restriction to"),
         "eventually equal": ("along", "the filter it holds along"),
         "equal as classes": ("modulo", "the equivalence the classes are taken modulo, with "
                                        "its measure or domain"),
         "projection": ("field", "the field or constructor argument it takes"),
         "transformation": ("preserves", "the property the transformation preserves")}
SCOPE_FIELDS = ("domain", "along", "modulo", "field", "preserves")
# The relations that need a result stating them.
NEEDS_SUPPORT = ("equal", "equal on a domain", "eventually equal", "equal as classes",
                 "restriction", "transformation")
# Relations that hold only on part of the objects, or between classes: identifying the objects
# outright through one leaves this obligation.
PARTIAL = {"equal on a domain": "local to global", "restriction": "local to global",
           "eventually equal": "local to global", "equal as classes": "equality transport"}
# The connections an identification of a composition can rest on, by its relation; a partial
# one under `same object` or `equal` leaves its obligation (`PARTIAL`).
FITS = {"same object": ("shared witness", "definitional", "projection", "equal", *PARTIAL),
        "equal": ("equal", "definitional", "projection", "shared witness", *PARTIAL),
        "restriction": ("restriction", "equal on a domain", "eventually equal"),
        "coercion": ("coercion",),
        "other": RELATIONS}
GLOBAL = ("same object", "equal")
# A declaration that can state a relation; the others are types and definitions.
THEOREM = "theorem"
KIND_WORDS = {"def": "a definition", "inductive": "a type", "opaque": "a definition",
              "axiom": "an axiom", "ctor": "a constructor", "rec": "a recursor",
              "quot": "a quotient primitive"}
# Support that names what two ends share rather than a result relating them.
SHARED = {"type": "a shared type", "dependency": "a shared dependency",
          "shared": "something the two ends share"}
ENDS = ("from", "to")
DECL_END = ("decl", "module", "external", "build", "fingerprint", "digest", "closure",
            "closure_complete", "expansions", "var", "id", "name", "type", "op", "at", "target")
FIELDS = ("relation", "from", "to", "conditions", "support", "unfolds", *SCOPE_FIELDS)


def _err(msg: str):
    from .workspace import WorkspaceError
    return WorkspaceError(msg)


def _text(v, what, required=False):
    from .workspace import _text as t
    return t(v, what, required)


# -- the build -------------------------------------------------------------------------------

def statement_of(snap, name: str) -> dict | None:
    """The statement record the build `snap` holds for the declaration `name`, wherever a claim
    shows it (a link, a suggestion, a locked statement, a proof step's link or route); a linked
    definition's with what it says."""
    if snap is None:
        return None
    found = snap.__dict__.get("_connection_statements")
    if found is None:
        found = {}
        for meta in snap.claims:
            ch = snap.chunk(meta["id"]) or {}
            step = ch.get("step") or {}
            for l in ((ch.get("links") or []) + (ch.get("suggestions") or [])
                      + (step.get("links") or [])
                      + ((step.get("route") or {}).get("links") or [])):
                if isinstance(l, dict) and l.get("name") and isinstance(l.get("statement"), dict):
                    found.setdefault(l["name"], {**l["statement"], "definition": l["definition"]}
                                     if l.get("definition") else l["statement"])
            for cl in ch.get("clauses") or []:
                if cl.get("spec") and isinstance(cl.get("statement"), dict):
                    found.setdefault(cl["spec"], cl["statement"])
        snap.__dict__["_connection_statements"] = found
    return found.get(name)


def decl_kind(snap, name: str) -> str | None:
    """What the build says the declaration `name` is (`theorem`, `def`, `inductive`, ...), from
    its index of the project or its declaration store; None when it does not say."""
    if snap is None:
        return None
    kinds = snap.__dict__.get("_connection_kinds")
    if kinds is None:
        kinds = {d["name"]: d["kind"] for d in snap.lean_index() or []
                 if isinstance(d, dict) and d.get("name") and d.get("kind")}
        snap.__dict__["_connection_kinds"] = kinds
    if name in kinds:
        return kinds[name]
    return next((r["kind"] for r in snap.store_records(name) if r.get("kind")), None)


def _objects(st: dict, decl: str) -> dict[int, dict]:
    from .objects import objects
    return {o["var"]: o for o in objects(st, decl)}


# -- the ends ------------------------------------------------------------------------------

def _decl_end(e: dict, snap, root, what: str) -> dict:
    from .workspace import _ref
    extra = set(e) - set(DECL_END)
    if extra:
        raise _err(f"{what} has no field {', '.join(sorted(extra))}")
    subs = [k for k in ("var", "at") if e.get(k) not in (None, "")]
    if len(subs) > 1:
        raise _err(f"{what} names a variable (`var`) or a sub-term (`at`), not both")
    given = {k: e[k] for k in ("decl", "module", "external", "build", "fingerprint", "digest",
                               "closure", "closure_complete", "expansions") if k in e}
    out = dict(_ref(given, snap, root))
    decl = out["decl"]
    st = statement_of(snap, decl)
    if subs and snap is not None and st is None:
        raise _err(f"{what}: this build holds no statement of {decl}, so no object of it can be "
                   "named; link it to a claim (or a proof step), or name the declaration whole")
    if subs == ["var"]:
        v = e["var"]
        if snap is None:
            if not isinstance(v, int):
                raise _err(f"{what}: without the build a variable is named by its number")
            out["var"] = v
            out.update({k: e[k] for k in ("id", "name", "type", "op") if e.get(k) is not None})
            return out
        objs = _objects(st, decl)
        listing = ", ".join(f"{x['var']}: {x['name']} : {x['type']}" for x in objs.values())
        if e.get("id") not in (None, ""):
            # The binder it was recorded at: an end follows its identity, never its number.
            hit = [x for x in objs.values() if x["id"] == e["id"]]
            if not hit:
                raise _err(f"{what}: {decl} has no binder {e['id']!r} in this build; name the "
                           f"object again by its variable, without `id` (its objects: {listing})")
            x = hit[0]
        else:
            if isinstance(v, str) and not v.isdigit():
                named = [x for x in objs.values() if x["name"] == v]
                if len(named) != 1:
                    raise _err(f"{what}: {decl} has {len(named) or 'no'} object(s) named {v!r}; "
                               f"name it by number ({listing})")
                v = named[0]["var"]
            v = int(v) if isinstance(v, str) else v
            if not isinstance(v, int) or v not in objs:
                raise _err(f"{what}: {decl} has no object number {v!r} (its objects: {listing})")
            x = objs[v]
        out.update(var=x["var"], id=x["id"], name=x["name"], type=x["type"], op=x["op"])
        return out
    if subs == ["at"]:
        at = _text(e["at"], f"{what}'s sub-term identity", True)
        out["at"] = at
        if snap is None:
            if isinstance(e.get("target"), str):
                out["target"] = e["target"]
            return out
        from . import symbols
        txt = symbols.term_by_id(st, at, getattr(snap, "part", None))
        if txt is None:
            raise _err(f"{what}: {decl} has no sub-term with the identity {at!r}")
        if isinstance(e.get("target"), str) and e["target"] != txt:
            raise _err(f"{what}: the sub-term {at} of {decl} is now {txt!r}, not "
                       f"{e['target']!r}; name it again without `target`")
        out["target"] = txt
    return out


def _app_end(e: dict, root, what: str) -> dict:
    from .workspace import _app_ref
    extra = set(e) - {"app", "param", "value"}
    if extra:
        raise _err(f"{what} has no field {', '.join(sorted(extra))}")
    a = _app_ref(e["app"], root)
    param = _text(e.get("param"), f"{what}'s parameter (`param`)", True).strip()
    args = [x for x in a.get("arguments") or [] if isinstance(x, dict)]
    hit = [x for x in args if x.get("binder") == param]
    if args and not hit:
        raise _err(f"{what}: {a['callee']} has no parameter {param!r} at this application (its "
                   f"parameters: {', '.join(str(x.get('binder')) for x in args)})")
    out = {"app": a, "param": param}
    value = hit[0].get("value") if hit else e.get("value")
    if isinstance(value, str):
        out["value"] = value
    return out


def _fact_end(e: dict, root, what: str) -> dict:
    from .workspace import _fact_ref
    extra = set(e) - {"fact", "local", "local_text"}
    if extra:
        raise _err(f"{what} has no field {', '.join(sorted(extra))}")
    f = _fact_ref(e["fact"], root)
    local = _text(e.get("local"), f"{what}'s local (`local`)", True).strip()
    ctx = [*(f.get("variables") or []), *(f.get("assumptions") or [])]
    hit = [x for x in ctx if isinstance(x, str) and x.split(" : ", 1)[0].strip() == local]
    if ctx and not hit:
        raise _err(f"{what}: no local {local!r} in the context of that fact (its locals: "
                   + ", ".join(x.split(" : ", 1)[0] for x in ctx if isinstance(x, str)) + ")")
    out = {"fact": f, "local": local}
    text = hit[0] if hit else e.get("local_text")
    if isinstance(text, str):
        out["local_text"] = text
    return out


def _end(e, snap, root, what: str) -> dict:
    if not isinstance(e, dict):
        raise _err(f"{what} is an object")
    kinds = [k for k in ("decl", "app", "fact") if e.get(k)]
    if len(kinds) != 1:
        raise _err(f"{what} is an object of a Lean result: a declaration's variable ({{decl, "
                   "var}}), sub-term ({{decl, at}}) or the declaration itself ({{decl}}), an "
                   "application's argument ({{app, param}}), or a local of a fact inside a proof "
                   "({{fact, local}})")
    if kinds == ["decl"]:
        return _decl_end(e, snap, root, what)
    if kinds == ["app"]:
        return _app_end(e, root, what)
    return _fact_end(e, root, what)


def end_decl(end: dict) -> str | None:
    """The declaration an end belongs to: its own, its application's callee, or the
    declaration whose proof holds its fact."""
    if end.get("decl"):
        return end["decl"]
    if end.get("app"):
        return end["app"].get("callee")
    return (end.get("fact") or {}).get("decl")


def same_binder(a: dict, b: dict) -> bool:
    """Whether two ends are one variable of one declaration's statement: by its binder's
    identity, or by its number when neither records one. Names never decide it."""
    if not (a.get("decl") and b.get("decl")) or a["decl"] != b["decl"] or \
            a.get("var") is None or b.get("var") is None:
        return False
    if a.get("id") or b.get("id"):
        return a.get("id") == b.get("id")
    return a["var"] == b["var"]


# -- what supports it ------------------------------------------------------------------------

def _shared_names(ends: list[dict], snap, root) -> set[str]:
    """The declarations both ends' statements use (their closures), and, for two witnesses with
    the Lean project, those both ends' declarations reach through their proofs."""
    decls = [end_decl(e) for e in ends]
    if snap is None or not all(decls) or decls[0] == decls[1]:
        return set()
    sets = []
    for d in decls:
        names, _, _ = snap.closure(d)
        sets.append(set(names or ()))
    return sets[0] & sets[1]


def _proof_shared(name: str, ends: list[dict], root) -> bool:
    """Whether the proofs (or values) of both ends' declarations use `name`, by the references
    the facts store holds (`uses.reference_records`); False when it holds none."""
    decls = [end_decl(e) for e in ends]
    if root is None or not all(decls) or decls[0] == decls[1]:
        return False
    from pathlib import Path
    from .impact import Graph
    from .uses import reference_records
    try:
        g = Graph(reference_records(Path(root))["records"])
    except Exception:  # noqa: BLE001 - an unreadable store decides nothing
        return False
    reach = g.reaching({name})
    return all(d in reach for d in decls)


def _support(s, snap, root, ends: list[dict], what: str) -> dict:
    from .workspace import _ref
    if not isinstance(s, dict):
        raise _err(f"{what} is an evidence reference")
    for k, words in SHARED.items():
        if k in s:
            raise _err(f"{what}: {words} is not evidence that two objects are related; cite a "
                       "theorem, an application or a fact inside a proof that states the "
                       "relation")
    kinds = [k for k in ("decl", "app", "fact", "certificate", "source", "paper", "connection")
             if s.get(k)]
    if len(kinds) != 1 or kinds[0] not in ("decl", "app", "fact"):
        raise _err(f"{what}: a connection rests on Lean results: a theorem ({{decl}}), an "
                   "application of one ({{app}}) or a fact inside a proof ({{fact}})")
    ref = _ref(s, snap, root)
    name = ref.get("decl") or (ref.get("app") or {}).get("callee")
    kind = decl_kind(snap, name) if name else None
    if kind and kind != THEOREM:
        raise _err(f"{what}: {name} is {KIND_WORDS.get(kind, 'not a theorem')}; a type or a "
                   "definition the two ends share is not evidence that they are related: cite "
                   "a theorem, an application of one or a fact that states the relation")
    if "decl" in ref:
        if ref["decl"] in _shared_names(ends, snap, root):
            raise _err(f"{what}: the statements of both ends use {ref['decl']}; a shared "
                       "dependency is not evidence that they are related: cite a result that "
                       "states the relation")
    return ref


def _unfolds(names, snap, root) -> list[dict]:
    from .workspace import _ref
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list) or not names:
        raise _err("a definitional connection names the definitions that unfold to make its "
                   "ends agree (`unfolds`): its reduction context")
    out = []
    for n in names:
        given = n if isinstance(n, dict) else {"decl": n}
        if not isinstance(given, dict) or not isinstance(given.get("decl"), str):
            raise _err("`unfolds` is a list of definitions' names")
        ref = _ref({k: given[k] for k in ("decl", "module", "build", "fingerprint", "digest",
                                          "closure", "closure_complete", "expansions")
                    if k in given}, snap, root)
        kind = decl_kind(snap, ref["decl"])
        if kind == THEOREM:
            raise _err(f"{ref['decl']} is a theorem: a definitional connection unfolds "
                       "definitions; cite the theorem as support of an equality instead")
        out.append(ref)
    return out


def _witness_support(ends: list[dict], support: list[dict], root, what: str) -> None:
    """A shared witness between separate choices needs evidence relating them: a result other
    than the ends' own results and not one both their proofs use."""
    for i, e in enumerate(ends):
        if e.get("decl") and e.get("var") is None:
            raise _err(f"{what}: a shared witness relates two witnesses; name each by its "
                       "variable ({decl, var}), an application's argument or a fact's local")
        if e.get("op") not in (None, "exists"):
            raise _err(f"{what}: {e.get('name')} of {e['decl']} is not the witness of a "
                       "\"there is\"; relate it as equal, definitional or a projection")
    if same_binder(*ends):
        return  # one result's witness: its facts are about one object
    own = {end_decl(e) for e in ends}
    own_facts = {((e.get("fact") or {}).get("decl"), (e.get("fact") or {}).get("at"))
                 for e in ends if e.get("fact")}
    useful = []
    for s in support:
        name = s.get("decl") or (s.get("app") or {}).get("callee")
        if name and (name in own or _proof_shared(name, ends, root)):
            continue
        if s.get("fact") and (s["fact"].get("decl"), s["fact"].get("at")) in own_facts:
            continue
        useful.append(s)
    if not useful:
        names = " and ".join(end_text(e) for e in ends)
        raise _err(f"{what}: {names} are witnesses of separate choices; each existence result "
                   "chooses its own, so they are one witness only with evidence that relates "
                   "them (a theorem, an application or a fact other than the existence results "
                   "themselves, and not one both their proofs use). Until there is such "
                   "evidence, a composition that combines them keeps its `compatible "
                   "witnesses` obligation open")


def ref(c, snap, root) -> dict:
    """A connection reference, checked against the build `snap` (and the Lean project at `root`
    for applications and facts) and pinned: its ends, relation and scope, conditions, support
    and, for a definitional one, the definitions that unfold."""
    if not isinstance(c, dict):
        raise _err("a connection is {from, to, relation, ...}")
    extra = set(c) - set(FIELDS)
    if extra:
        raise _err(f"a connection has no field {', '.join(sorted(extra))}")
    from .workspace import _choice
    rel = _choice(c.get("relation"), RELATIONS, "the connection's relation", False)
    out = {"relation": rel}
    ends = [_end(c.get(side), snap, root, f"the connection's `{side}` end") for side in ENDS]
    out["from"], out["to"] = ends
    need = SCOPE.get(rel)
    for f in SCOPE_FIELDS:
        if c.get(f) in (None, ""):
            continue
        if not need or need[0] != f:
            takes = [r for r, (g, _) in SCOPE.items() if g == f]
            raise _err(f"`{f}` belongs to a connection that is {' or '.join(takes)}")
        out[f] = _text(c[f], f"the connection's {f}", True).strip()
    if need and need[0] not in out:
        raise _err(f"a connection that is {rel} states {need[1]} (`{need[0]}`)")
    conds = c.get("conditions") or []
    if isinstance(conds, str):
        conds = [conds]
    if not isinstance(conds, list):
        raise _err("`conditions` is a list of the conditions under which the relation holds")
    conds = [_text(x, "a condition", True).strip() for x in conds]
    if conds:
        out["conditions"] = list(dict.fromkeys(conds))
    raw = c.get("support") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise _err("`support` is a list of evidence references")
    support = [_support(s, snap, root, ends, f"support {i + 1}") for i, s in enumerate(raw)]
    if rel in NEEDS_SUPPORT and not support:
        raise _err(f"a connection that is {rel} rests on a result that states it (`support`: a "
                   "theorem, an application or a fact inside a proof)")
    if rel == "shared witness":
        _witness_support(ends, support, root, "the connection")
    if rel == "definitional":
        out["unfolds"] = _unfolds(c.get("unfolds"), snap, root)
    elif c.get("unfolds"):
        raise _err("`unfolds` belongs to a definitional connection")
    if support:
        out["support"] = support
    return {**{k: out[k] for k in ("relation", "from", "to")},
            **{k: v for k, v in out.items() if k not in ("relation", "from", "to")}}


def _end_identity(e: dict) -> tuple:
    if e.get("decl"):
        return ("decl", e["decl"], e.get("var"), e.get("id"), e.get("at"))
    if e.get("app"):
        return ("app", e["app"].get("callee"), e["app"].get("id"), e.get("param"))
    f = e.get("fact") or {}
    return ("fact", f.get("decl"), f.get("at"), e.get("local"))


def _ref_identity(r: dict) -> tuple:
    if r.get("decl"):
        return ("decl", r["decl"])
    if r.get("app"):
        return ("app", r["app"].get("callee"), r["app"].get("id"))
    f = r.get("fact") or {}
    return ("fact", f.get("decl"), f.get("at"))


def keep_pins(new: dict, old: dict) -> dict:
    """A connection written again without re-pinning keeps the versions its ends, its support
    and its unfolded definitions were recorded at, where it names the same ones."""
    out = copy.deepcopy(new)
    for side in ENDS:
        if old.get(side) and _end_identity(old[side]) == _end_identity(new[side]):
            out[side] = copy.deepcopy(old[side])
    for k in ("support", "unfolds"):
        was = {_ref_identity(r): r for r in old.get(k) or []}
        if out.get(k):
            out[k] = [copy.deepcopy(was.get(_ref_identity(r), r)) for r in out[k]]
    return out


# -- currency --------------------------------------------------------------------------------

def _identity_changes(e: dict, snap) -> list[dict]:
    """An end at a binder or a sub-term that the build no longer has there: the change names
    what it was recorded at and what is there now, and the end is never moved to it."""
    if snap is None or not e.get("decl") or (e.get("var") is None and not e.get("at")):
        return []
    st = statement_of(snap, e["decl"])
    if st is None:
        return []
    if e.get("at"):
        if not isinstance(e.get("target"), str):
            return []
        from . import symbols
        now = symbols.term_by_id(st, e["at"], getattr(snap, "part", None))
        if now == e["target"]:
            return []
        return [{"decl": e["decl"], "at": e["at"], "was": e["target"], "now": now,
                 "reason": f"{e['decl']}: the sub-term {e['at']} " +
                 (f"is now {now!r}, not {e['target']!r}" if now is not None else
                  f"({e['target']!r}) is not in this build")}]
    objs = _objects(st, e["decl"])
    was = {k: e.get(k) for k in ("id", "name", "type") if e.get(k) is not None}
    by_id = [x for x in objs.values() if was.get("id") and x["id"] == was["id"]]
    x = by_id[0] if by_id else objs.get(e["var"])
    now = {k: x[k] for k in ("id", "name", "type")} if x else None
    if now is not None and all(now.get(k) == v for k, v in was.items()) and \
            x["var"] == e["var"]:
        return []
    def show(d):
        return f"{d.get('name')} : {d.get('type')}" + (f" (binder {d['id']})" if d.get("id")
                                                       else "")
    if by_id:
        why = f"the object {show(was)} the connection was recorded at is now variable {x['var']}"
    elif now is None:
        why = f"variable {e['var']}, {show(was)} when the connection was recorded, is not there"
    else:
        why = (f"variable {e['var']} is now {show(now)}, not {show(was)}, the object the "
               "connection was recorded at")
    return [{"decl": e["decl"], "var": e["var"], "was": was, "now": now,
             "reason": f"{e['decl']}: {why}"}]


def _named(res: dict, what: str) -> dict:
    """A currency whose changes each say which part of the connection changed."""
    out = dict(res)
    out["changes"] = [c if c.get("reason") else {**c, "reason": f"{what} changed"}
                      for c in res.get("changes") or []]
    return out


def currency(c: dict, snap, root, check_facts: bool = False) -> dict:
    """Whether a connection is still what the build (and the Lean project at `root`) shows:
    `stale` when one of its ends, its support or a definition it unfolds changed, or an end's
    binder or sub-term is not the one it was recorded at; `unchecked` when a part cannot be
    checked here (with the reasons); else `current`. Each connection is checked on its own
    pins."""
    from . import dependencies as dp
    from pathlib import Path
    root = Path(root) if root else None
    parts = []
    for side in ENDS:
        e = c.get(side) or {}
        label = f"{end_text(e)}, the `{side}` end,"
        if e.get("decl"):
            res = dp.decl_currency(e, snap, root)
            res = {**res, "changes": list(res.get("changes") or [])
                   + _identity_changes(e, snap)}
            if res["changes"]:
                res["state"] = "stale"
        elif e.get("app"):
            from .uses import app_currency
            res = app_currency(root, e["app"], check_facts)
        else:
            from .proof_facts import currency as fact_currency
            res = fact_currency(root, e.get("fact") or {}, check_facts)
        parts.append(_named(res, label))
    for s in c.get("support") or []:
        parts.append(_named(dp.evidence_currency(s, snap, root, check_facts),
                            f"{ref_words(s)}, its support,"))
    for u in c.get("unfolds") or []:
        parts.append(_named(dp.decl_currency(u, snap, root),
                            f"{u.get('decl')}, a definition it unfolds,"))
    changes = [ch for p in parts for ch in p.get("changes") or []]
    if changes:
        return {"state": "stale", "changes": changes}
    reasons = [p.get("reason") for p in parts if p.get("state") == "unchecked"]
    if any(p.get("state") == "unchecked" for p in parts):
        return {"state": "unchecked", "changes": [],
                **({"reason": "; ".join(dict.fromkeys(r for r in reasons if r))}
                   if any(reasons) else {})}
    return {"state": "current", "changes": []}


# -- in words ------------------------------------------------------------------------------

def end_text(e: dict) -> str:
    """An end of a connection in the reader's words."""
    e = e or {}
    if e.get("decl"):
        if e.get("var") is not None:
            return f"{e.get('name') or 'variable ' + str(e['var'])} of {e['decl']}"
        if e.get("at"):
            return (f"`{e['target']}` in {e['decl']}" if e.get("target") else
                    f"the sub-term {e['at']} of {e['decl']}")
        return e["decl"]
    if e.get("app"):
        a = e["app"]
        return f"{e.get('param')} of {a.get('callee')} applied in {a.get('caller')}"
    f = e.get("fact") or {}
    return f"{e.get('local')} in the proof of {f.get('decl')}"


def ref_words(r: dict) -> str:
    if r.get("decl"):
        return r["decl"]
    if r.get("app"):
        return f"{r['app'].get('callee')} applied in {r['app'].get('caller')}"
    f = r.get("fact") or {}
    return f"{f.get('name') or f.get('head') or 'a fact'} inside the proof of {f.get('decl')}"


def relation_text(c: dict) -> str:
    """The relation of a connection between its ends, in words."""
    a, b = end_text(c.get("from")), end_text(c.get("to"))
    rel = c.get("relation")
    words = {
        "definitional": f"{a} and {b} are definitionally equal",
        "projection": f"{b} is the field {c.get('field') or 'taken'} of {a}",
        "equal": f"{a} and {b} are equal",
        "equal on a domain": f"{a} and {b} are equal on {c.get('domain') or 'a domain'}",
        "eventually equal": f"{a} and {b} are eventually equal along "
                            f"{c.get('along') or 'a filter'}",
        "equal as classes": f"{a} and {b} are equal as classes, modulo "
                            f"{c.get('modulo') or 'an equivalence'}",
        "restriction": f"{b} is the restriction of {a} to {c.get('domain') or 'a domain'}",
        "coercion": f"{b} is {a} coerced",
        "transformation": f"{b} is a transformation of {a} preserving "
                          f"{c.get('preserves') or 'a property'}",
        "shared witness": f"{a} and {b} are one witness",
    }
    return words.get(rel, f"{a} and {b}: {rel}")


def text(c: dict) -> str:
    """A connection in the reader's words: its ends, relation and scope, conditions and
    support."""
    out = relation_text(c)
    if c.get("conditions"):
        out += f", when {'; '.join(c['conditions'])}"
    if c.get("unfolds"):
        out += ", unfolding " + ", ".join(u.get("decl") for u in c["unfolds"])
    if c.get("support"):
        out += ", by " + "; ".join(ref_words(s) for s in c["support"])
    return out


# -- reading them back -------------------------------------------------------------------------

def records(evidence: list[dict] | None) -> list[dict]:
    """The connections among a claim's evidence records, as `workspace.view` gives them (with
    their currency): the records the reader shows and the comparison carries."""
    return [e for e in evidence or [] if "connection" in (e.get("ref") or {})]


def query(work_dir, snap, claim: str, root=None, workspace: str | None = None,
          check_now: bool = False) -> list[dict]:
    """The connections recorded for `claim` in the workspaces of `work_dir` (or the one named),
    each as `workspace.view` gives it, with its workspace and auditor."""
    from . import workspace as wsp
    rows = wsp.list_all(work_dir)
    if workspace and not any(ws["id"] == workspace for _, ws in rows):
        raise wsp.WorkspaceError(f"no workspace {workspace} in {wsp.store(work_dir)}")
    out = []
    for _, ws in rows:
        if workspace and ws["id"] != workspace:
            continue
        v = wsp.view(ws, snap, claim, root, check_facts=check_now)
        for e in records((v["claims"].get(claim) or {}).get("evidence")):
            out.append({**e, "workspace": ws["id"], "reviewer": v["reviewer"],
                        "mode": v["mode"]})
    return out


def lines(e: dict) -> list[str]:
    """A connection evidence record for the terminal."""
    c = (e.get("ref") or {}).get("connection") or {}
    out = [f"  connection {e['id']} ({e.get('role')}): {text(c)}  [{e['currency']['state']}]"]
    for ch in e["currency"].get("changes") or []:
        out.append(f"    changed: {ch.get('reason') or ch}")
    if e["currency"].get("state") == "unchecked" and e["currency"].get("reason"):
        out.append(f"    not known to be current: {e['currency']['reason']}")
    return out


# -- in a composition ------------------------------------------------------------------------

def identification(x: dict, cited: dict[str, dict], what: str) -> list[tuple[str, str, str]]:
    """The obligations an identification of a composition leaves through the connections it
    cites (`cited`: evidence id to its record): `(kind, connection id, text)` for each partial
    relation it uses to identify the objects outright. A connection whose relation does not fit
    the identification's is refused."""
    out = []
    for eid, r in cited.items():
        c = (r.get("ref") or {}).get("connection")
        if c is None:
            continue
        rel = c.get("relation")
        if rel not in FITS.get(x["relation"], ()):
            fit = [k for k, v in FITS.items() if rel in v]
            raise _err(f"{what} says the objects are {x['relation']}, but {eid} records that "
                       f"{relation_text(c)}: identify them as {' or '.join(fit)}")
        if x["relation"] in GLOBAL and rel in PARTIAL:
            scope = c.get(SCOPE[rel][0])
            words = (f"holds between classes modulo {scope}, not between their representatives"
                     if PARTIAL[rel] == "equality transport" else
                     f"holds only {'along' if rel == 'eventually equal' else 'on'} {scope}")
            out.append((PARTIAL[rel], eid,
                        f"{x['left']['object']} of {x['left']['step']} and "
                        f"{x['right']['object']} of {x['right']['step']} are identified as "
                        f"{x['relation']}, but {eid} {words}: "
                        + ("extend it to where the objects are used"
                           if PARTIAL[rel] == "local to global" else
                           "show that the representatives agree where they are used")))
    return out


def partial_only(ids: list[str], records: dict) -> bool:
    """Whether the evidence `ids` are all connections whose relation holds only on part of the
    objects (or between classes): they cannot discharge the obligation they leave."""
    rels = [((records.get(e) or {}).get("ref") or {}).get("connection", {}).get("relation")
            for e in ids]
    return bool(rels) and all(r in PARTIAL for r in rels)


# -- published -------------------------------------------------------------------------------

def _public_end(e: dict, pub) -> dict:
    if e.get("decl"):
        keep = ("decl", "module", "build", "fingerprint", "digest", "var", "id", "op", "at") + \
            (("name", "type", "target") if pub.lean else ())
        return {k: e[k] for k in keep if e.get(k) is not None}
    if e.get("app"):
        a = e["app"]
        out = {"app": {k: a[k] for k in ("callee", "module", "id", "caller", "via", "app_hash")
                       if a.get(k) is not None}, "param": e.get("param")}
        if pub.lean and e.get("value") is not None:
            out["value"] = e["value"]
        return out
    f = e.get("fact") or {}
    out = {"fact": {k: f[k] for k in ("decl", "module", "at", "fact_hash", "proof_hash")
                    if f.get(k) is not None}, "local": e.get("local")}
    if pub.lean and e.get("local_text") is not None:
        out["local_text"] = e["local_text"]
    return out


def public(c: dict, pub, ref_of) -> dict:
    """A connection as a published audit carries it: its relation, its ends' identities and pins
    and its support's always; the Lean text of its ends, its scope and its conditions only when
    the Lean is published. `ref_of` publishes a support reference."""
    out = {"relation": c.get("relation"),
           "from": _public_end(c.get("from") or {}, pub),
           "to": _public_end(c.get("to") or {}, pub)}
    if pub.lean:
        out.update({k: c[k] for k in (*SCOPE_FIELDS, "conditions") if c.get(k)})
    if c.get("support"):
        out["support"] = [ref_of(s, pub) for s in c["support"]]
    if c.get("unfolds"):
        out["unfolds"] = [{k: u[k] for k in ("decl", "module", "build", "fingerprint", "digest")
                           if u.get(k) is not None} for u in c["unfolds"]]
    return out
