"""The objects of a Lean statement and what the statement says about each, by where the object
stands (#98).

An object is a variable a statement binds to data: one that opens it ("for all", an instance
that supplies data such as `[Inhabited E]`), a witness of a "there is", or a variable bound inside
the conclusion or inside an assumption. What the statement says about it is listed with the
reason each part holds of it (its `basis`):

- `type`: a property its type carries, from the probe: the predicate of a subtype, a proof field
  of a structure or a class, inherited ones once, as it applies to the object;
- `premise`: an explicit premise that mentions it (a hypothesis of the statement, the premise of
  an implication, or a part of the assumption it stands in), with what the premise states when
  it is a structure of propositions (`[IsProbability Ω]`);
- `conclusion`: a part of the conclusion (or of the clause the object stands in) that mentions it;
- `definition`: a definition applied to it in one of those, as Lean expands it at its arguments
  (#97; the expansion is referred to by its identity and key);
- `theorem`: a derivation cited for it, a theorem, an application or a fact inside a proof, as
  workspace evidence cites one. A derivation names its object by declaration, variable number
  and binder identity, never by printed name or type, so two objects of the same name or type
  never share one.

The data fields of its type are listed apart (`data`), and the instances that supply structure on
it (`instances`: `[MeasureData Ω]` for `Ω`), which are objects of their own.

Where the object stands decides how these read (`position`): supplied (`given`), introduced by
the conclusion (`produced`), inside an assumption (`assumed`), inside the premise of an
implication (`premise`), inside a negation (`denied`), one alternative (`alternative`) or one
side of an equivalence (`equivalent`). Inside a negation or an alternative, the object and its
properties stay local to that clause. Display only: no status reads it, and names of custom
fields add no meaning to it.
"""

from __future__ import annotations

from . import symbols

BASES = ("definition", "type", "premise", "theorem", "conclusion")

# How each position reads: what it says of the object, then of the properties its type carries
# (when it has some), for an object bound by a "there is" (`exists`) and by a "for every".
READING = {
    "given": ("Supplied to the statement.",
              "Supplied to the statement: the properties its type carries are part of that "
              "input."),
    "produced": ("Introduced by the conclusion: producing it establishes what the conclusion "
                 "states of it.",
                 "Introduced by the conclusion: producing it establishes the properties its "
                 "type carries and what the conclusion states of it."),
    "assumed": {"exists": ("A witness inside an assumption: it stays inside that assumption.",
                           "A witness inside an assumption: it and its properties stay inside "
                           "that assumption."),
                "forall": ("Bound inside an assumption: it stays inside that assumption.",
                           "Bound inside an assumption: it and its properties stay inside that "
                           "assumption.")},
    "premise": ("Inside the premise of an implication: it belongs to that premise.",
                "Inside the premise of an implication: it and its properties belong to that "
                "premise."),
    "denied": {"exists": ("Inside a negation: the statement says there is no such object.",
                          "Inside a negation: the statement says there is no such object; its "
                          "properties belong to the negated claim."),
               "forall": ("Inside a negation: it belongs to the negated claim.",
                          "Inside a negation: it and its properties belong to the negated "
                          "claim.")},
    "alternative": ("Inside one alternative: it belongs to that alternative.",
                    "Inside one alternative: it and its properties belong to that "
                    "alternative."),
    "equivalent": ("On one side of an equivalence: it belongs to that side.",
                   "On one side of an equivalence: it and its properties belong to that side."),
}

# A property's basis in words, by the object's position where that changes how it reads.
BASIS_WORDS = {"type": "in its type", "premise": "assumed", "conclusion": "concluded",
               "definition": "by definition", "theorem": "by a cited result"}
PRODUCED_WORDS = {"type": "established with it", "conclusion": "established"}


def position(n: dict) -> str:
    """Where a binder node stands, from the probe's `scope` and `within`."""
    s = n.get("scope")
    if s == "assumed":
        return "assumed" if (n.get("within") or [None])[0] == "assume" else "premise"
    if s:
        return s
    return "produced" if n.get("op") == "exists" else "given"


def reading(n: dict) -> str:
    """How an object reads where it stands (`READING`)."""
    r = READING.get(position(n), ("", ""))
    if isinstance(r, dict):
        r = r["exists" if n.get("op") == "exists" else "forall"]
    carries = any(p.get("kind") == "proposition" for p in n.get("properties") or [])
    return r[1] if carries else r[0]


def _supplies(n: dict) -> str:
    """Whether a binder node binds an object (`data`) or a proof (`proposition`); a record
    written before the probe said so is read from its role."""
    return n.get("supplies") or ("proposition" if n.get("op") == "hypothesis" else "data")


def _vars(pp) -> set:
    return {s["var"] for s in (pp or {}).get("segments") or []
            if isinstance(s, dict) and isinstance(s.get("var"), int)}


def _range_vars(pp: dict, at: str) -> set | None:
    """The variables the sub-term `at` of `pp` mentions; None when `pp` has no such sub-term."""
    segs = pp.get("segments") or []
    if pp.get("id") == at:
        return _vars(pp)
    for t in pp.get("terms") or []:
        if t.get("id") == at:
            return {s["var"] for s in segs[t["from"]:t["to"]]
                    if isinstance(s, dict) and isinstance(s.get("var"), int)}
    return None


def _range_text(pp: dict, at: str) -> str | None:
    if pp.get("id") == at:
        return symbols._text(pp)
    for t in pp.get("terms") or []:
        if t.get("id") == at:
            return "".join(s.get("t", "") for s in (pp.get("segments") or [])[t["from"]:t["to"]])
    return None


def _walk(spec: dict):
    """Each binder node and each leaf of the statement's tree (the hypotheses' own trees
    included), with the path to it: the binders (`("bind", node)`) and connectives
    (`("conn", word)`, the probe's words: `and`, `or`, `iff`, `not`, `if`, `then`, `assume`)
    around it, outermost first."""
    out = []

    def walk(n, path):
        if not isinstance(n, dict):
            return
        if "leaf" in n:
            out.append(("leaf", n, path))
            return
        op = n.get("op")
        args = n.get("args") or []
        if op in ("forall", "exists", "hypothesis", "instance"):
            out.append(("binder", n, path))
            inner = path + [("bind", n)]
            if isinstance(n.get("logic"), dict):
                walk(n["logic"], inner + [("conn", "assume")])
            for a in args:
                walk(a, inner)
        elif op == "implies" and len(args) == 2:
            walk(args[0], path + [("conn", "if")])
            walk(args[1], path + [("conn", "then")])
        else:
            for a in args:
                walk(a, path + [("conn", op)])

    walk(symbols.tree(spec), [])
    return out


def _carried(n: dict, how: str | None = None) -> list[dict]:
    """The propositions a node's type carries, each as a property of the object."""
    out = []
    for p in n.get("properties") or []:
        if p.get("kind") != "proposition":
            continue
        pp = p.get("type") or {}
        out.append({"basis": how or p.get("basis") or "type", "field": p.get("field"),
                    "statement": symbols._text(pp), "id": pp.get("id"),
                    **{k: p[k] for k in ("structure", "declared_in", "inherited", "via",
                                         "projection", "module", "range", "depends")
                       if p.get(k) is not None}})
    return out


def _data(n: dict) -> list[dict]:
    return [{"field": p.get("field"), "term": p.get("term"),
             "type": symbols._text(p.get("type")), "id": (p.get("type") or {}).get("id"),
             **{k: p[k] for k in ("declared_in", "inherited", "via") if p.get(k) is not None}}
            for p in n.get("properties") or [] if p.get("kind") == "data"]


def _definitions(pp: dict, var: int, source: str) -> list[dict]:
    """The definitions applied to the variable `var` in the printed term `pp`, as expanded at
    their arguments (`expansions`): each `{basis: definition, definition, application, at,
    expansion, key}`, `source` the identity of the part it occurs in."""
    out = []
    for x in (pp or {}).get("expansions") or []:
        at = x.get("at")
        vs = _range_vars(pp, at) if at else None
        if not vs or var not in vs:
            continue
        out.append({"basis": "definition", "definition": x.get("name"),
                    "application": _range_text(pp, at), "at": at, "expansion": x.get("id"),
                    **({"key": x["key"]} if x.get("key") else {}), "in": source})
    return out


def objects(spec: dict, decl: str | None = None, derivations=()) -> list[dict]:
    """The objects of the statement record `spec` (of the declaration `decl`), by number (those
    that open the statement, then those of its conclusion, then those inside its hypotheses),
    each `{var, name, id, op, binder, type, type_id, position, within, after, reading,
    properties, data, instances}` (see the module's description). `derivations` are
    results cited for objects: `{object: {decl, var, id?}, ref, statement?, evidence?, by?}`; one
    is listed only with the object it names, by declaration, number and binder identity."""
    if not isinstance(spec, dict) or not (spec.get("tree") or spec.get("binders")):
        return []
    items = _walk(spec)
    binders = [(n, path) for kind, n, path in items if kind == "binder"]
    leaves = [(n, path) for kind, n, path in items if kind == "leaf"]
    spine = len(spec.get("binders") or [])
    out = []
    for n, path in binders:
        var = n.get("var")
        if not isinstance(var, int) or _supplies(n) != "data":
            continue
        props = _carried(n)
        instances = []
        # The opening hypotheses and instances that mention it: premises, and structure
        # supplied on it.
        for m, _ in binders:
            mv = m.get("var")
            if not isinstance(mv, int) or mv >= spine or mv <= var or var >= spine:
                continue
            if var not in _vars(m.get("type")):
                continue
            ty = m.get("type") or {}
            if _supplies(m) == "data":
                if m.get("op") == "instance":
                    instances.append({"var": mv, "name": m.get("name"),
                                      "type": symbols._text(ty), "id": m.get("id")})
                continue
            states = _carried(m, "premise")
            props.append({"basis": "premise", "hypothesis": m.get("name"),
                          "binder_id": m.get("id"), "statement": symbols._text(ty),
                          "id": ty.get("id"), **({"states": states} if states else {})})
            props += _definitions(ty, var, ty.get("id"))
        # A proposition bound inside the tree (`∀ h : P, …` whose body uses `h`) is a premise
        # of the part under it.
        for m, mpath in binders:
            if _supplies(m) != "proposition" or not isinstance(m.get("var"), int) or \
                    m["var"] < spine or var not in _vars(m.get("type")):
                continue
            ty = m.get("type") or {}
            props.append({"basis": "premise", "statement": symbols._text(ty), "id": ty.get("id"),
                          "binder_id": m.get("id"),
                          "within": [w for k, w in mpath if k == "conn"]})
        # The parts of the tree that mention it: what a premise or an assumption states of it,
        # and what the conclusion (or the clause it stands in) states of it. An opening object
        # is stated of by an opening hypothesis as a whole (above), not by its parts.
        for leaf, lpath in leaves:
            pp = leaf.get("leaf") or {}
            if var not in _vars(pp):
                continue
            conns = [w for k, w in lpath if k == "conn"]
            if var < spine and "assume" in conns:
                continue
            basis = "premise" if ("if" in conns or "assume" in conns) else "conclusion"
            mine = next((i for i, (k, x) in enumerate(lpath) if k == "bind" and x is n), None)
            local = [w for k, w in lpath[mine + 1:] if k == "conn"] if mine is not None else conns
            props.append({"basis": basis, "statement": symbols._text(pp), "id": pp.get("id"),
                          **({"within": local} if local else {})})
            props += _definitions(pp, var, pp.get("id"))
        for d in derivations or ():
            o = d.get("object") or {}
            if o.get("decl") == decl and o.get("var") == var and \
                    o.get("id") in (None, n.get("id")):
                props.append({"basis": "theorem", "ref": d.get("ref"),
                              "statement": d.get("statement"),
                              **{k: d[k] for k in ("evidence", "by", "note", "currency")
                                 if d.get(k)}})
        ty = n.get("type") or {}
        obj = {"var": var, "name": n.get("name"), "id": n.get("id"), "op": n.get("op"),
               "binder": n.get("binder"), "type": symbols._text(ty), "type_id": ty.get("id"),
               "position": position(n), "within": list(n.get("within") or []),
               "after": list(n.get("after") or []), "reading": reading(n),
               "properties": props, "data": _data(n), "instances": instances}
        for k in ("properties_omitted", "properties_error"):
            if n.get(k):
                obj[k] = n[k]
        out.append(obj)
    return sorted(out, key=lambda o: o["var"])


def object_lines(objs: list[dict]) -> list[str]:
    """The objects of a statement for the terminal: each with its position, then what the
    statement says about it, by basis."""
    lines = []
    for o in objs:
        if not (o["properties"] or o["data"] or o["instances"]):
            continue
        head = (f"  object [{o['type']}]" if o["op"] == "instance" else
                f"  object {o['name']} : {o['type']}") + f"  ({o['position']})"
        lines += [head, f"    {o['reading']}"]
        words = {**BASIS_WORDS, **(PRODUCED_WORDS if o["position"] == "produced" else {})}
        for p in o["properties"]:
            what = words.get(p["basis"], p["basis"])
            if p["basis"] == "type":
                src = f"field {p.get('field')} of {p.get('structure')}" + (
                    f", from {p['declared_in']}" if p.get("inherited") else "")
                lines.append(f"    {what:20} {p['statement']}   [{src}]")
            elif p["basis"] == "premise":
                by = f"   [{p['hypothesis']}]" if p.get("hypothesis") else ""
                lines.append(f"    {what:20} {p['statement']}{by}")
                for s in p.get("states") or []:
                    lines.append(f"    {'  which states':20} {s['statement']}   "
                                 f"[field {s.get('field')} of {s.get('structure')}]")
            elif p["basis"] == "definition":
                which = p.get("key") or p.get("expansion")
                lines.append(f"    {what:20} {p.get('application') or p.get('definition')}"
                             f" unfolds by {p.get('definition')}   [expansion {which}]")
            elif p["basis"] == "theorem":
                from .workspace import ref_text
                lines.append(f"    {what:20} {p.get('statement') or ref_text(p.get('ref'))}"
                             f"   [{ref_text(p.get('ref'))}]")
            else:
                within = f"   (within {' › '.join(p['within'])})" if p.get("within") else ""
                lines.append(f"    {what:20} {p['statement']}{within}")
        if o["data"]:
            lines.append(f"    {'data':20} " + "; ".join(f"{d['term']} : {d['type']}"
                                                         for d in o["data"]))
        for i in o["instances"]:
            lines.append(f"    {'structure on it':20} [{i['type']}]")
        if o.get("properties_omitted"):
            lines.append(f"    ({o['properties_omitted']} further field(s) of its type are not "
                         "listed)")
        if o.get("properties_error"):
            lines.append(f"    (the fields of its type could not be read: "
                         f"{o['properties_error']})")
    return lines


def structure_view(rec: dict) -> dict | None:
    """What a structure is made of, from its declaration record (`structure`, from the probe),
    with its fields grouped by where they come from: those it declares (`declares`), and those
    it inherits from each parent (`inherits`, by the parent projection they come through). For
    a structure that extends another, `declares` is exactly what it adds."""
    st = rec.get("structure")
    if not isinstance(st, dict):
        return None
    name = rec.get("name")
    parents = {p.get("projection"): p.get("structure") for p in st.get("parents") or []}
    declares, inherits = [], {}
    for f in st.get("fields") or []:
        if f.get("declared_in") == name or not f.get("inherited"):
            declares.append(f.get("field"))
        else:
            via = f.get("via") or []
            parent = parents.get(via[0]) if via else f.get("declared_in")
            inherits.setdefault(parent or f.get("declared_in"), []).append(f.get("field"))
    return {**st, "declares": declares,
            "inherits": [{"parent": p, "fields": fs} for p, fs in inherits.items()]}


def structure_lines(rec: dict) -> list[str]:
    """A structure's fields for the terminal: those it inherits, by parent, then those it adds,
    each with its statement at an object `self`, and the properties a construction's value
    carries."""
    out = []
    view = structure_view(rec)
    if view:
        fields = {f.get("field"): f for f in view.get("fields") or []}

        def show(f):
            x = fields.get(f) or {}
            kind = "" if x.get("kind") == "proposition" else " (data)"
            return f"{f} : {symbols._text(x.get('type'))}{kind}"
        for g in view["inherits"]:
            out.append(f"  inherits from {g['parent']}: " + "; ".join(show(f) for f in g["fields"]))
        if view["declares"]:
            out.append(("  adds: " if view["inherits"] else "  fields: ")
                       + "; ".join(show(f) for f in view["declares"]))
        if view.get("fields_omitted"):
            out.append(f"  ({view['fields_omitted']} further field(s) are not listed)")
    if rec.get("structure_error"):
        out.append(f"  its fields could not be read from Lean: {rec['structure_error']}")
    props = [p for p in rec.get("result_properties") or [] if p.get("kind") == "proposition"]
    if props:
        out.append("  its value carries, established by this definition: "
                   + "; ".join(f"{p.get('field')} : {symbols._text(p.get('type'))}"
                               for p in props))
    if rec.get("result_properties_error"):
        out.append(f"  what its value carries could not be read from Lean: "
                   f"{rec['result_properties_error']}")
    return out


class ObjectError(ValueError):
    """An object reference that names no object of the claim's Lean."""


def object_ref(o, statements: dict | None) -> dict:
    """An object of a claim's Lean as a derivation names it: `{decl, var}`, `var` its number (or
    its name, when one variable of the statement has it). With the claim's statements by
    declaration (`requirements._statements`), it is checked and pinned to the binder's identity
    (`id`), name and type, so that a rebuild that numbers the variables otherwise attaches it to
    no other object."""
    if not isinstance(o, dict) or not isinstance(o.get("decl"), str) or not o["decl"].strip():
        raise ObjectError("an object is {decl, var}: the declaration and the variable's number")
    out = {"decl": o["decl"].strip()}
    v = o.get("var")
    if statements is None:
        if not isinstance(v, int):
            raise ObjectError("without the build an object names its variable by number")
        return {**out, "var": v, **{k: o[k] for k in ("id", "name", "type") if o.get(k)}}
    st = statements.get(out["decl"])
    if st is None:
        raise ObjectError(f"this build holds no statement of {out['decl']} for the claim: an "
                          "object of it can be named once it is linked to the claim")
    objs = {x["var"]: x for x in objects(st, out["decl"])}
    if isinstance(v, str) and not v.isdigit():
        named = [x for x in objs.values() if x["name"] == v]
        if len(named) != 1:
            raise ObjectError(f"{out['decl']} has {len(named) or 'no'} object(s) named {v!r}; "
                              "name it by number (" + ", ".join(
                                  f"{x['var']}: {x['name']} : {x['type']}"
                                  for x in objs.values()) + ")")
        v = named[0]["var"]
    if isinstance(v, str):
        v = int(v)
    if not isinstance(v, int) or v not in objs:
        raise ObjectError(f"{out['decl']} has no object number {v!r} (its objects: "
                          + ", ".join(f"{x['var']}: {x['name']} : {x['type']}"
                                      for x in objs.values()) + ")")
    x = objs[v]
    return {**out, "var": v, "id": x["id"], "name": x["name"], "type": x["type"]}


def derivations(evidence: list[dict]) -> list[dict]:
    """The results cited for objects among a claim's workspace evidence: each evidence record
    that names an `object` and supports it, as `objects` takes it."""
    from .workspace import ref_text
    out = []
    for e in evidence or []:
        if not e.get("object") or e.get("role") != "supports":
            continue
        ref = e.get("ref") or {}
        stmt = ((ref.get("fact") or {}).get("type") or (ref.get("app") or {}).get("result"))
        out.append({"object": e["object"], "ref": ref,
                    "statement": symbols._text(stmt) if isinstance(stmt, dict) else
                    stmt or ref_text(ref),
                    "evidence": e.get("id"), "by": e.get("created_by"), "note": e.get("note"),
                    **({"currency": e["currency"]} if e.get("currency") else {})})
    return out
