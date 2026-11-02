"""A Lean statement arranged to be read as mathematics (#70).

The probe reads every printed expression of a statement as mathematics (`math`: a tree of the
notions Lean elaborated, each node at the identity of the sub-term it renders; see
`data/ProofLensProbe.lean`). This module arranges the statement's tree (#67) into rows for the
reader, which writes the words and the typography: the objects grouped by where they stand, each
assumption and conclusion with its role and where it comes from, each tied to the Lean expression
it is. Rows refer to printed expressions of the statement record by identity (`at`, the `id` of
a binder's type, a leaf of the tree or a property an object's type carries); those identities
are the ones the exact Lean, symbol links and alignments use (#73), so a row shown as
mathematics is the expression it came from.

The rows, in reading order (a quantifier's scope runs to the end of the list it stands in):

- `objects`: objects introduced together, by one quantifier (`quantifier`: `forall` or `exists`)
  at one place: consecutive binders of the same kind and printed type (`∀ a b : ℕ` is one row),
  each `{var, name, id, binder, at}`, the shared type printed once (`at`, the first object's).
  `after` lists the objects bound before them, which they may depend on: in `∃ C, ∀ n, …` the
  row of `C` comes before that of `n`, and in `∀ n, ∃ C, …` after it.
- `structure`: an instance that supplies data on objects (`[MeasurableSpace Ω]`, a σ-algebra on
  `Ω`): supplied structure, `on` the objects it is about.
- `condition`: an assumption: a hypothesis, an instance that supplies a proposition
  (`[SigmaFinite μ]`, an assumption in addition to the measure), the premise of an implication,
  or a part of either; `about` the objects it mentions, `joint` when it relates several. A
  hypothesis with a shape has its own rows (`rows`), all inside it: a witness of an existence it
  assumes stays there. One that is a class of propositions lists what it states (`states`).
- `claim`: a part of what the statement establishes, with the objects it is `about`.
- `and`, `or`, `iff`, `not`, `implies`: a connective, with its parts (`parts`, each a list of
  rows): an existence inside a negation or one alternative keeps its whole enclosing claim.

Every row has `role`: `input` (supplied: a given object or supplied structure), `assumption`
(inside a hypothesis or a premise) or `output` (what the statement establishes, an object it
produces included); and `scope`, where the probe places a binder (`given`, `produced`,
`assumed`, `denied`, `alternative`, `equivalent`). Each property an object's type carries is
listed with its object (`properties`), with where it comes from (`origin`):

- `type`: included in the type of a given object, or of an object inside an assumption or a
  clause, where it stays;
- `established`: carried by the type of an object the statement produces: producing it
  establishes the property, which is not supplied before the statement;
- `proved`: derived for that object by a result a workspace cites (`ref`), never by a name or a
  type alone.

A condition's origin is `assumed`, a claim's `established`, supplied structure's `supplied`. Each
row lists the project's definitions applied in it (`definitions`, `{name, at, expansion}`: the
application's identity and that of its expansion at its actual arguments, #97), and the
statement lists each definition once (`definitions`), with every application. Display only:
no status, fingerprint or review reads it.
"""

from __future__ import annotations

SCHEMA = "prooflens/readable@1"


def _vars(pp) -> list[int]:
    """The statement's variables a printed expression mentions, by number."""
    return sorted({s["var"] for s in (pp or {}).get("segments") or []
                   if isinstance(s, dict) and isinstance(s.get("var"), int)})


def _text(pp) -> str:
    if not isinstance(pp, dict):
        return pp or ""
    return pp.get("text") or "".join(x.get("t", "") for x in pp.get("segments") or [])


def _id(pp):
    return pp.get("id") if isinstance(pp, dict) else None


def _definitions(pp) -> list[dict]:
    """The project's definitions applied in a printed expression, by their expansions."""
    return [{"name": x.get("name"), "at": x.get("at"), "expansion": x.get("id")}
            for x in (pp or {}).get("expansions") or [] if isinstance(x, dict)]


def _supplies(n: dict) -> str:
    return n.get("supplies") or ("proposition" if n.get("op") == "hypothesis" else "data")


def _role(scope: str | None, base: str) -> str:
    """The role of a binder standing at `scope`, in a part whose role is `base`."""
    if scope == "given":
        return "input"
    if scope == "produced":
        return "output"
    if scope == "assumed":
        return "assumption"
    return base


def _properties(n: dict, var, origin_of_type: str) -> tuple[list[dict], list[dict]]:
    """The propositions and the data an object's type carries, each tied to its statement."""
    props, data = [], []
    for p in n.get("properties") or []:
        if not isinstance(p, dict):
            continue
        pp = p.get("type") or {}
        common = {"object": var, "field": p.get("field"), "at": _id(pp),
                  **{k: p[k] for k in ("structure", "declared_in", "inherited", "via",
                                       "projection", "module", "range", "depends")
                     if p.get(k) is not None}}
        if p.get("kind") == "proposition":
            basis = p.get("basis") or "type"
            props.append({**common, "basis": basis,
                          "origin": origin_of_type if basis == "type" else
                          "assumed" if basis == "premise" else basis,
                          "definitions": _definitions(pp)})
        else:
            data.append({**common, "term": p.get("term")})
    return props, data


class _Builder:
    def __init__(self, decl, derivations):
        self.decl = decl
        self.derivations = list(derivations or ())
        self.defs: dict[str, dict] = {}

    def note(self, row: dict, pp, role: str) -> None:
        """Record the definitions applied in `pp` on `row` and in the statement's list."""
        ds = _definitions(pp)
        if not ds:
            return
        row["definitions"] = ds
        for d in ds:
            entry = self.defs.setdefault(d["name"], {"name": d["name"], "applications": []})
            entry["applications"].append({"at": d["at"], "expansion": d["expansion"],
                                          "role": role})

    def derived(self, n: dict) -> list[dict]:
        """The results a workspace cites for the object of node `n`, by declaration, number and
        binder identity."""
        out = []
        for d in self.derivations:
            o = d.get("object") or {}
            if o.get("decl") == self.decl and o.get("var") == n.get("var") and \
                    o.get("id") in (None, n.get("id")):
                out.append({"object": n.get("var"), "origin": "proved", "basis": "theorem",
                            "ref": d.get("ref"), "statement": d.get("statement"),
                            **{k: d[k] for k in ("evidence", "by", "note", "currency")
                               if d.get(k)}})
        return out

    # -- rows ---------------------------------------------------------------------------------

    def binder(self, n: dict, base: str) -> dict:
        """The row of one binder node: an object, supplied structure or an assumption."""
        op, ty = n.get("op"), n.get("type") or {}
        scope = n.get("scope") or ("produced" if op == "exists" else "given")
        if _supplies(n) == "proposition":
            row = {"k": "condition", "role": "assumption", "origin": "assumed",
                   "var": n.get("var"), "name": n.get("name"), "id": n.get("id"),
                   "binder": n.get("binder"), "at": _id(ty), "about": _vars(ty)}
            row["joint"] = len(row["about"]) > 1
            self.note(row, ty, "assumption")
            states, _ = _properties(n, n.get("var"), "assumed")
            if states:
                row["states"] = [{**s, "origin": "assumed"} for s in states]
            if isinstance(n.get("logic"), dict):
                row["rows"] = self.rows(n["logic"], "assumption")
            for k in ("logic_error", "properties_error"):
                if n.get(k):
                    row[k] = n[k]
            return row
        role = _role(scope, base)
        if op == "instance":
            props, data = _properties(n, n.get("var"), "type")
            row = {"k": "structure", "role": role, "origin": "supplied", "var": n.get("var"),
                   "name": n.get("name"), "id": n.get("id"), "binder": n.get("binder"),
                   "at": _id(ty), "on": _vars(ty), "properties": props, "data": data}
            self.note(row, ty, role)
            return row
        origin = "established" if scope == "produced" else "type"
        props, data = _properties(n, n.get("var"), origin)
        props += self.derived(n)
        row = {"k": "objects", "quantifier": "exists" if op == "exists" else "forall",
               "role": role, "scope": scope, "within": list(n.get("within") or []),
               "after": list(n.get("after") or []),
               "objects": [{"var": n.get("var"), "name": n.get("name"), "id": n.get("id"),
                            "binder": n.get("binder"), "at": _id(ty)}],
               "at": _id(ty), "properties": props, "data": data,
               # What `group` compares, removed once the rows are grouped.
               "type_text": _text(ty), "type_vars": _vars(ty)}
        for k in ("properties_omitted", "properties_error"):
            if n.get(k):
                row[k] = n[k]
        self.note(row, ty, role)
        return row

    def leaf(self, pp: dict, base: str) -> dict:
        about = _vars(pp)
        if base == "assumption":
            row = {"k": "condition", "role": "assumption", "origin": "assumed", "at": _id(pp),
                   "about": about, "joint": len(about) > 1}
        else:
            row = {"k": "claim", "role": base, "origin": "established", "at": _id(pp),
                   "about": about}
        self.note(row, pp, base)
        return row

    def rows(self, n, base: str) -> list[dict]:
        """The rows of the part `n` of the tree, in a part whose role is `base`."""
        out: list[dict] = []
        while isinstance(n, dict):
            if "leaf" in n:
                out.append(self.leaf(n.get("leaf") or {}, base))
                break
            op, args = n.get("op"), n.get("args") or []
            if op in ("forall", "exists", "hypothesis", "instance"):
                out.append(self.binder(n, base))
                n = args[0] if args else None
                continue
            if op == "implies" and len(args) == 2:
                out.append({"k": "implies", "id": n.get("id"), "role": base,
                            "parts": [self.rows(args[0], "assumption"),
                                      self.rows(args[1], base)]})
            elif op in ("and", "or"):
                parts = []

                def flat(m):
                    if isinstance(m, dict) and m.get("op") == op and "leaf" not in m:
                        for a in m.get("args") or []:
                            flat(a)
                    else:
                        parts.append(self.rows(m, base))
                flat(n)
                out.append({"k": op, "id": n.get("id"), "role": base, "parts": parts})
            elif op in ("iff", "not"):
                out.append({"k": op, "id": n.get("id"), "role": base,
                            "parts": [self.rows(a, base) for a in args]})
            break
        return group(out)


def group(rows: list[dict]) -> list[dict]:
    """`rows` with consecutive objects introduced alike merged into one row: the same quantifier,
    role, place and printed type, the later not depending on the earlier (`∀ a b : ℕ`)."""
    out: list[dict] = []
    for r in rows:
        last = out[-1] if out else None
        if last is not None and r.get("k") == "objects" == last.get("k") and \
                all(r.get(k) == last.get(k) for k in ("quantifier", "role", "scope", "within")) \
                and r.get("type_text") == last.get("type_text") and r.get("type_text") and \
                not set(r.get("type_vars") or []) & {o["var"] for o in last["objects"]}:
            last["objects"] += r["objects"]
            last["properties"] += r["properties"]
            last["data"] += r["data"]
            for d in r.get("definitions") or []:
                last.setdefault("definitions", []).append(d)
            continue
        out.append(r)
    for r in out:
        r.pop("type_text", None)
        r.pop("type_vars", None)
    return out


def readable(spec: dict | None, decl: str | None = None, derivations=()) -> dict | None:
    """The statement record `spec` (of the declaration `decl`) as rows to read as mathematics
    (see the module's description); `derivations` are results a workspace cites for objects,
    as `objects.objects` takes them. None for a record without a statement."""
    if not isinstance(spec, dict) or not (spec.get("tree") or spec.get("binders")
                                          or spec.get("conclusion")):
        return None
    b = _Builder(decl, derivations)
    # The binders that open the statement are read from the tree like those inside it: a given
    # object is an input, a hypothesis an assumption, and the conclusion is the output.
    from .symbols import tree
    rows = b.rows(tree(spec), "output")
    return {"schema": SCHEMA, "rows": rows, "definitions": list(b.defs.values()),
            "exact": _id(spec.get("exact"))}
