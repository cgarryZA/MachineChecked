"""Where a Lean declaration is used, and how: `compare --query uses` and `inspect --used-by`.

Lean is asked, in every library of the project, which declarations mention the declaration in
their statement and which use it in their value (a theorem's proof, a definition's body), and,
inside each user's value, for every application of it: the actual argument supplied for each of
its binders (implicit and instance arguments included), the premise each proof argument
instantiates, where that proof comes from, and the conclusion the application obtains. The
arguments are read from the elaborated terms; names and source text decide nothing.

Where a premise comes from is what the term shows: one of the caller's own hypotheses (the
caller assumes it), a hypothesis or fact introduced inside the proof, a theorem applied there,
a constructor, a projection of a structure, an instance, or a term built in place (in each of
those the caller proves it). That is a fact about Lean terms; whether the premise matches a
condition of the paper takes a reviewer.

The answer names the scope it searched. Modules that are not built or could not be loaded are
listed, and while there are any the answer is incomplete: "no use found" then holds only for the
modules searched. A name declared by two modules is ambiguous until its module is given.

Answers are kept in the facts store (`facts.py`) and reused while no module of the project
changes; a repeat query starts no Lean session. The reverse references of every declaration
(`refs`, for the further callers) are stored per module with the index a build extracts, and
shared by every query.
"""

from __future__ import annotations

from pathlib import Path

from .config import work_dir_name
from .facts import graphs
from .probe import lib_names
from .simple import ViewError, built_modules, loading_error, probe_modules

SCHEMA = "machinechecked/uses@1"
NOTE = ("Uses are read from Lean's elaborated terms. Where a premise comes from is what the term "
        "shows; whether it matches a condition of the paper takes a reviewer.")
VALUE_REF = {"proof": "proof", "definition body": "definition body", "none": "value"}

# How far further callers are followed, and how many are listed.
FURTHER_DEPTH, FURTHER_MAX = 6, 300

# How a premise is supplied, in words.
DISCHARGE = {"assumed": "assumed by the caller", "proved": "proved in the caller",
             "local": "from a hypothesis introduced in the proof",
             "helper": "a parameter of a constant Lean generated",
             "unknown": "not determined from the term"}

# Where a premise's proof comes from: the caller assumes it, or proves it.
ASSUMED = {"caller hypothesis", "caller instance", "caller parameter"}
LOCAL = {"local hypothesis", "local variable"}


def _tool_version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("machinechecked")
    except PackageNotFoundError:
        return "unknown"


# -- the reverse references of every declaration ----------------------------------------------

def refs_index(recs: list[dict]) -> dict:
    """The reverse references of a probe's `refs` records, per session: for each declaration
    (by its owner, the declaration a generated constant belongs to) the declarations that
    mention it, each with how (`statement`, and `proof` or `definition body`). Self-references
    and a generated constant's references to its own declaration are left out."""
    owner: dict[tuple[str, str], str] = {}
    module: dict[tuple[str, str], str] = {}
    for r in recs:
        if r.get("record") == "refs":
            g = r.get("probe_group", "")
            owner[(g, r["name"])] = r.get("owner") or r["name"]
            module[(g, r.get("owner") or r["name"])] = module.get(
                (g, r.get("owner") or r["name"]), r.get("module"))
    users: dict[tuple[str, str], dict[str, dict]] = {}
    for r in recs:
        if r.get("record") != "refs":
            continue
        g = r.get("probe_group", "")
        u = owner[(g, r["name"])]
        for how, names in (("statement", r.get("statement") or []),
                           (VALUE_REF.get(r.get("value_kind"), "value"), r.get("value") or [])):
            for n in names:
                t = owner.get((g, n), n)
                if t == u:
                    continue
                e = users.setdefault((g, t), {}).setdefault(
                    u, {"name": u, "module": module.get((g, u)), "refs": [], "via": []})
                if how not in e["refs"]:
                    e["refs"].append(how)
                if r["name"] != u and r["name"] not in e["via"]:
                    e["via"].append(r["name"])
    return {"users": users, "module": module}


def site_index(recs: list[dict]) -> dict:
    """The reverse references the reader shows (`data/uses.json`): for each declaration, by
    name, one entry per module declaring it, with its users."""
    idx = refs_index(recs)
    # One library's session holds the libraries it imports: a declaration's users are the union
    # of what every session that holds it reports.
    merged: dict[tuple[str, str | None], dict[str, dict]] = {}
    for (g, name), us in idx["users"].items():
        into = merged.setdefault((name, idx["module"].get((g, name))), {})
        for u in us.values():
            e = into.setdefault(u["name"], {**u, "refs": [], "via": []})
            e["refs"] += [x for x in u["refs"] if x not in e["refs"]]
            e["via"] += [x for x in u["via"] if x not in e["via"]]
    out: dict[str, list[dict]] = {}
    for (name, mod), us in sorted(merged.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        out.setdefault(name, []).append({
            "module": mod,
            "users": [{k: v for k, v in u.items() if v} for u in
                      sorted(us.values(), key=lambda u: u["name"])]})
    return {"schema": "machinechecked/uses-index@1", "by_name": out}


# -- one declaration ---------------------------------------------------------------------------

def _resolve(root: Path, name: str, module: str | None, built: list[str], unbuilt: list[str]):
    from .deps import _resolve as resolve
    return resolve(root, name, module, built, unbuilt)


def _origin_root(o: dict | None) -> dict | None:
    """The origin a projection or a local fact comes from in the end."""
    seen = 0
    while o and seen < 6:
        nxt = o.get("of") if o.get("kind") == "projection" else None
        if not nxt:
            return o
        o, seen = nxt, seen + 1
    return o


def discharge(o: dict | None) -> str:
    """How a premise is supplied at an application: `assumed` (the caller's own hypothesis, or
    a part of one), `local` (a hypothesis introduced inside the proof), `proved` (proved in the
    caller), `helper` (a parameter of a constant Lean generated), or `unknown`."""
    r = _origin_root(o) or {}
    k = r.get("kind")
    if k in ASSUMED:
        return "assumed"
    if k in LOCAL:
        return "local"
    if k == "helper parameter":
        return "helper"
    if k in (None, "other", "unassigned"):
        return "unknown"
    return "proved"


def describe(o: dict | None) -> str:
    """An origin in words."""
    if not o:
        return "not shown"
    k = o.get("kind")
    n = o.get("name")
    through = f" (through {', '.join(o['through'])})" if o.get("through") else ""
    applied = " applied to arguments" if o.get("applied") else ""
    if k == "caller hypothesis":
        s = f"the caller's hypothesis {n}{applied}"
    elif k == "caller parameter":
        s = f"the caller's parameter {n}{applied}"
    elif k == "caller instance":
        s = f"an instance the caller assumes ({n})"
    elif k == "helper parameter":
        s = f"a parameter {n} of a constant Lean generated"
    elif k == "local hypothesis":
        s = f"the hypothesis {n} introduced in the proof{applied}"
    elif k == "local variable":
        s = f"the variable {n} introduced in the proof"
    elif k in ("local fact", "local definition"):
        s = f"the local {'fact' if k == 'local fact' else 'definition'} {n}" + \
            (f", from {describe(o['by'])}" if o.get("by") else "")
    elif k == "theorem application":
        s = f"by {n}"
    elif k == "application":
        s = f"by {n}, applied in the caller"
    elif k == "construction":
        parts = [describe(p) for p in o.get("parts") or [] if p]
        s = f"constructed with {n}" + (f" from {'; '.join(parts)}" if parts else "")
    elif k == "projection":
        s = f"the field {o.get('field')} of {describe(o.get('of')) if o.get('of') else 'a term'}"
    elif k == "instance":
        s = f"the instance {n}"
    elif k == "built in place":
        s = "a term built in place"
    elif k == "term" and o.get("head") == "OfNat.ofNat":
        s = "a numeral"
    elif k == "term":
        s = "a term built in the caller"
    elif k == "literal":
        s = "a literal"
    else:
        s = "not determined from the term"
    return s + through


def _text(pp) -> str | None:
    return pp.get("text") if isinstance(pp, dict) else None


def application(r: dict, caller_owner: str, ranges: dict) -> dict:
    """An application record as the CLI and the reader show it: the raw record (exact
    printed expressions with their variable references) and, for each premise, how it is
    supplied."""
    caller = r["caller"]
    loc = {"declaration": caller_owner, "path": r.get("path"),
           "range": ranges.get(caller), "precision": "declaration",
           "note": "the position is the application's path in the elaborated term; the source "
                   "line is the enclosing declaration's"}
    out = {"id": f"app:{caller}:{r.get('index', 0)}", "callee": r["name"], "caller": caller_owner,
           "location": loc}
    if caller != caller_owner:
        out["via"] = caller
    if r.get("errors"):
        return {**out, "available": False, "errors": r["errors"]}
    params = []
    for p in r.get("params") or []:
        q = dict(p)
        q["supplied"] = describe(p.get("origin"))
        if p.get("role") == "premise":
            q["discharge"] = discharge(p.get("origin"))
        params.append(q)
    return {**out, "available": True, "params": params,
            "premises": [{"binder": p["binder"], "statement": _text(p.get("type")),
                          "discharge": p["discharge"], "supplied": p["supplied"]}
                         for p in params if p.get("role") == "premise"],
            "unsupplied": r.get("open") or [], "extra_args": r.get("extra_args", 0),
            "result": r.get("result"), "locals": r.get("locals") or []}


def _further(idx: dict, group: str, name: str) -> list[dict]:
    """Declarations that reach `name` through other declarations, nearest first."""
    users = idx["users"]
    out, seen = [], {name}
    frontier = [(u, u) for u in sorted(users.get((group, name), {}))]
    seen |= {u for u, _ in frontier}
    depth = 1
    while frontier and depth < FURTHER_DEPTH and len(out) < FURTHER_MAX:
        depth += 1
        nxt = []
        for n, first in frontier:
            for u in sorted(users.get((group, n), {})):
                if u in seen:
                    continue
                seen.add(u)
                e = users[(group, n)][u]
                out.append({"name": u, "module": e.get("module"), "depth": depth, "through": n,
                            "refs": e["refs"]})
                nxt.append((u, first))
        frontier = nxt
    return out[:FURTHER_MAX]


def _assemble(name: str, recs: list[dict], groups: list[str], built: list[str],
              unbuilt: list[str], failed: dict[str, str], idx: dict,
              root: Path | None = None) -> dict:
    """The answer from the records of the sessions in `groups` (those whose environment holds
    the declaration). Each module that could not be loaded is given with what its session
    reported, as `check` gives it (`simple.loading_error`, paths from `root`)."""
    head = next(r for r in recs if r.get("record") == "uses" and r.get("probe_group") in groups
                and not r.get("errors"))
    users: dict[tuple[str, str], dict] = {}
    for r in recs:
        if r.get("record") != "user" or r.get("probe_group") not in groups:
            continue
        key = (r["owner"], r["module"])
        u = users.setdefault(key, {"id": f"decl:{r['owner']}", "name": r["owner"],
                                   "module": r["module"], "kind": r.get("kind"), "refs": [],
                                   "via": []})
        how = []
        if r.get("statement"):
            how.append("statement")
        if r.get("value"):
            how.append(VALUE_REF.get(r.get("value_kind"), "value"))
        for h in how:
            if h not in u["refs"]:
                u["refs"].append(h)
        if r["user"] != r["owner"] and r["user"] not in u["via"]:
            u["via"].append(r["user"])
        if not r.get("user_facing") and r["owner"] == r["user"]:
            # A constant Lean generated that belongs to no declaration (a shared auxiliary
            # lemma, say): its own users are found among the further callers.
            u["generated"] = True
    # A generated constant's own references to its declaration are not uses.
    users = {k: v for k, v in users.items() if v["name"] != name}
    ranges, scans, apps = {}, {}, []
    for r in recs:
        if r.get("probe_group") not in groups:
            continue
        if r.get("record") == "appscan":
            ranges[r["caller"]] = r.get("range")
            scans[r["caller"]] = r
    owner_of = {r["user"]: r["owner"] for r in recs if r.get("record") == "user"}
    seen_apps = set()
    for r in recs:
        if r.get("record") == "app" and r.get("probe_group") in groups:
            key = (r["caller"], r.get("path"))
            if key in seen_apps:
                continue
            seen_apps.add(key)
            ow = owner_of.get(r["caller"], r["caller"])
            if ow == name:
                continue
            apps.append(application(r, ow, ranges))
    apps.sort(key=lambda a: (a["caller"], a.get("via") or "", a["id"]))
    cut = [c for c, s in scans.items() if s.get("cut")]
    not_described = max((r.get("not_described", 0) for r in recs if r.get("record") == "uses"
                         and r.get("probe_group") in groups), default=0)
    module = head.get("module")
    # Modules that import the declaration's module but use nothing of it are not uses.
    graph = {}
    for r in recs:
        if r.get("record") == "module" and r.get("probe_group") in groups:
            graph.setdefault(r["name"], set()).update(r.get("imports") or [])
    using = {u["module"] for u in users.values()}
    importers = sorted(m for m, imps in graph.items() if module in imps and m not in using
                       and m in built)
    complete = not unbuilt and not failed
    if users:
        answer = "used"
    elif complete:
        answer = "no use found in this scope"
    else:
        answer = "not traced: some modules of the project were not searched"
    linked_users = sorted(users.values(), key=lambda u: (u.get("generated", False), u["name"]))
    for u in linked_users:
        if not u["via"]:
            del u["via"]
    return {
        "ok": True, "status": "found",
        "declaration": {"id": f"decl:{name}", "name": name, "module": module,
                        "kind": head.get("kind")},
        "scope": {"libraries": sorted({r.get("probe_group") for r in recs
                                       if r.get("record") == "uses"}),
                  "modules": len(built), "unbuilt": sorted(unbuilt),
                  "failed": {m: loading_error(failed[m], root) for m in sorted(failed)},
                  "declarations_searched": head.get("searched")},
        "complete": complete, "answer": answer,
        "users": linked_users,
        "further": _further(idx, "", name) if idx else [],
        "further_note": "declarations that reach this one through its users, by their "
                        "statements and values" if idx else "not extracted",
        "imports_without_use": importers,
        "applications": apps,
        "applications_complete": not cut and not not_described,
        "applications_note": (
            (f"applications are described in {head.get('described')} user(s); "
             f"{not_described} more user(s) are not described. " if not_described else "")
            + (f"Some applications in {', '.join(sorted(cut)[:5])} are not described (the "
               f"term is too large, or there are more than the per-user limit). " if cut else "")
            ).strip() or None,
    }


def uses(root: Path, name: str, module: str | None = None, lake: str = "lake", log=None,
         refresh: bool = False, cached_only: bool = False) -> dict:
    """Where `name` is used in the Lean project at `root`, and its applications there, as one
    JSON-ready document. `cached_only` answers from the facts store or with `status: "not
    extracted"`."""
    libs = lib_names(root)
    if not libs:
        raise ViewError("no Lean library found in the lakefile")
    built, unbuilt = built_modules(root, libs)
    if not built:
        raise ViewError("the Lean project is not built (run `lake build`)")
    head = {"schema": SCHEMA, "name": name, "tool": _tool_version(), "note": NOTE}
    target, answer = _resolve(root, name, module, built, unbuilt)
    if answer is not None:
        return {**head, "ok": False, **answer}
    from .deps import store
    # An answer is reused while every module of the project it searched, and the probe, are
    # unchanged (#130's facts store): a user can be anywhere, so an edit to any project module
    # reopens it, and an edit outside Lean does not.
    st = store(root, libs)
    key = f"{name}\0{module or target or '*'}"
    if cached_only:
        entry, _ = st.get("uses", key)
        if entry is not None:
            return {**head, **entry["body"], "cache": {"hit": True}}
        return {**head, "ok": False, "status": "not extracted",
                "reason": "its uses have not been read since the Lean last changed"}
    with st.lock(log):
        entry, _ = (None, None) if refresh else st.get("uses", key)
        if entry is not None:
            return {**head, **entry["body"], "cache": {"hit": True}}
        refs = None if refresh else _stored_refs(st, built)
        requests = [{"kind": "apps", "name": name}, {"kind": "modules", "name": ""}]
        if refs is None:
            requests.append({"kind": "refs", "name": ""})
        work = root / work_dir_name(root) / "build"
        quiet = log or (lambda m: None)
        recs, failed = probe_modules(root, built, libs, requests, lake, log=quiet, work=work)
        errs = [r for r in recs if r.get("record") == "apps" and r.get("errors")]
        if errs and not any(r.get("record") == "uses" for r in recs):
            raise ViewError(errs[0]["errors"][0])
        graph: dict[str, list[str]] = {}
        for g in graphs(recs).values():
            graph.update(g)
        found = [r for r in recs if r.get("record") == "uses" and not r.get("errors")]
        if module or target:
            want = module or target
            found = [r for r in found if r.get("module") == want]
        groups = sorted({r["probe_group"] for r in found})
        if refs is None:
            fresh = [r for r in recs if r.get("record") == "refs"]
            if not failed:
                st.put("refs", "", st.environment(built, graph),
                       records=[{k: v for k, v in r.items() if k != "probe_group"}
                                for r in fresh])
            # The sessions that hold the declaration, as one environment.
            refs = [r for r in fresh if r.get("probe_group") in groups]
        mods = sorted({r.get("module") for r in found})
        if len(mods) > 1:
            body = {"ok": False, "status": "ambiguous", "modules": mods}
        elif not found:
            body = {"ok": False, "status": "not checked" if failed else "not found",
                    "modules": sorted(failed) if failed else ([target] if target else []),
                    **({"reason": "some built modules could not be loaded"} if failed else {})}
        else:
            idx = refs_index([{**r, "probe_group": ""} for r in refs])
            body = _assemble(name, recs, groups, built, unbuilt, failed, idx, root)
        if not failed:
            st.put("uses", key, st.environment(built, graph), body=body)
    return {**head, **body, "cache": {"hit": False}}


def app_hash(app: dict) -> str:
    """A digest of an application as Lean elaborated it: its arguments, premises and result."""
    import hashlib
    import json
    body = {k: app.get(k) for k in ("callee", "caller", "via", "params", "result", "unsupplied")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()[:16]


def citation(doc: dict, app: dict) -> dict:
    """What a workspace keeps of a cited application (`compare --query uses`): where it is, the
    actual argument of each variable, each premise with how it is supplied, the conclusion it
    obtains, and a digest that says when it no longer describes the caller's proof."""
    return {"callee": app["callee"], "module": (doc.get("declaration") or {}).get("module"),
            "id": app["id"], "caller": app["caller"],
            **({"via": app["via"]} if app.get("via") else {}),
            "arguments": [{"binder": p.get("binder"), "role": p.get("role"),
                           "value": _text(p.get("argument"))}
                          for p in app.get("params") or [] if p.get("role") != "premise"],
            "premises": [{"binder": q["binder"], "statement": q.get("statement"),
                          "discharge": q.get("discharge"), "supplied": q.get("supplied")}
                         for q in app.get("premises") or []],
            "result": _text(app.get("result")), "app_hash": app_hash(app)}


def find_application(doc: dict, ref: dict) -> dict | None:
    for a in doc.get("applications") or []:
        if a["id"] == ref.get("id") and a.get("available", True):
            return a
    return None


def app_currency(root: Path | None, ref: dict, check_now: bool = False) -> dict:
    """Whether a cited application still describes the caller's proof: `current` while it is
    elaborated the same way, `stale` when it changed or is gone, `unchecked` while its uses have
    not been read since the Lean last changed (`check_now` reads them), or when Lean could not
    read them all (a module not built or not loaded, applications not described), so that one
    not found may only be out of sight."""
    from .deps import NOT_CHECKED, not_checked_reason
    if root is None:
        return {"state": "unchecked", "changes": [], "reason": "no Lean project to check against"}
    try:
        doc = uses(root, ref["callee"], ref.get("module"), cached_only=not check_now)
    except ViewError as e:
        return {"state": "unchecked", "changes": [], "reason": str(e)}
    if doc.get("status") == "not extracted":
        return {"state": "unchecked", "changes": [],
                "reason": f"{doc['reason']}; `machinechecked compare --query uses "
                          f"{ref['callee']}` reads them again"}
    if not doc.get("ok") and doc.get("status") in NOT_CHECKED:
        return {"state": "unchecked", "changes": [],
                "reason": not_checked_reason(ref["callee"], doc)}
    found = find_application(doc, ref) if doc.get("ok") else None
    if found is None and doc.get("ok"):
        callers = {u.get("name") for u in doc.get("users") or []}
        if any(a.get("id") == ref.get("id") for a in doc.get("applications") or []) or \
                not doc.get("applications_complete"):
            return {"state": "unchecked", "changes": [],
                    "reason": "Lean did not describe every application of "
                              f"{ref['callee']}"}
        if ref.get("caller") not in callers and not doc.get("complete"):
            return {"state": "unchecked", "changes": [],
                    "reason": f"{ref.get('caller')} is not among the declarations Lean "
                              "searched: some modules of the project are not built or could "
                              "not be loaded"}
    if found is None:
        return {"state": "stale", "changes": [{"app": ref["id"], "was": ref.get("app_hash"),
                                               "now": None,
                                               "reason": "the application is no longer there"}]}
    now = app_hash(found)
    if now == ref.get("app_hash"):
        return {"state": "current", "changes": []}
    return {"state": "stale", "changes": [{"app": ref["id"], "was": ref.get("app_hash"),
                                           "now": now, "reason": "the application changed"}]}


def reference_records(root: Path) -> dict:
    """The `refs` records of the project's built modules that the facts store holds current,
    read without starting Lean (`compare --query impact` reads them after `uses`):
    `{records, built, unbuilt, missing}`, where `missing` lists the built modules whose records it
    does not hold (changed since they were read, or not loaded)."""
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    from .deps import store
    st = store(root, libs)
    out, missing = [], []
    for m in built:
        e, _ = st.get("index", m)
        if e is None or "refs" not in e:
            missing.append(m)
        else:
            out += e["refs"]
    if missing:
        e, _ = st.get("refs", "")
        if e is not None:
            out, missing = list(e["records"]), []
    return {"records": out, "built": built, "unbuilt": unbuilt, "missing": missing}


def _stored_refs(st, built: list[str]) -> list[dict] | None:
    """The reverse references of the built modules, as the facts store holds them current: from
    the index a build stored per module, else from an earlier query; None when it holds neither
    for every module."""
    out = []
    for m in built:
        e, _ = st.get("index", m)
        if e is None or "refs" not in e:
            break
        out += e["refs"]
    else:
        return out
    e, _ = st.get("refs", "")
    return e["records"] if e is not None else None


# -- the reader ------------------------------------------------------------------------------

def route(root: Path, data_dir: Path, lake: str = "lake"):
    """`GET /api/uses?name=&module=` of `machinechecked view`'s local server: the document
    `compare --query uses` gives, so that the reader and the command line show the same
    records."""
    def get(q: dict) -> dict:
        from . import compare as cmp
        name = (q.get("name") or [""])[0]
        if not name:
            raise ViewError("name a declaration")
        doc = uses(root, name, (q.get("module") or [None])[0] or None, lake)
        try:
            claims = cmp.linked_claims(cmp.Site(data_dir))
        except cmp.CompareError:
            claims = {}
        return cmp.mark_claims(doc, claims)
    return get


# -- text --------------------------------------------------------------------------------------

def cite_text(ref: dict) -> str:
    """An evidence reference as a workspace record takes it (`"ref"`), for the terminal."""
    import json
    return json.dumps(ref, ensure_ascii=False)


def text(out: dict, claims: dict[str, list[str]] | None = None,
         module: str | None = None) -> str:
    """A uses document for the terminal. Each application is named by its id, which workspace
    evidence cites (`{"app": {callee, id}}`, with the `module` the declaration was asked for in,
    when one was)."""
    if not out.get("ok"):
        where = ", ".join(out.get("modules") or [])
        return (f"{out['name']}: {out['status']}" + (f" ({where})" if where else "")
                + (f": {out['reason']}" if out.get("reason") else "")
                + ("\n  name the module that declares it with --module"
                   if out.get("status") == "ambiguous" else ""))
    d = out["declaration"]
    sc = out["scope"]
    lines = [f"{d['name']}  ({d['kind']}, {d['module']})",
             f"  searched {sc['modules']} built module(s) of {', '.join(sc['libraries'])}"
             + (f"; not built: {', '.join(sc['unbuilt'][:5])}" if sc["unbuilt"] else "")
             + (f"; could not be loaded: {', '.join(list(sc['failed'])[:5])}"
                if sc["failed"] else ""),
             f"  {out['answer']}"]
    claims = claims or {}
    for u in out["users"]:
        tag = f"  [linked to {', '.join(claims[u['name']])}]" if u["name"] in claims else ""
        via = f"  (through {', '.join(u['via'])})" if u.get("via") else ""
        lines.append(f"  used by {u['name']}  ({', '.join(u['refs'])}; {u['module']}){via}{tag}")
    if out.get("further"):
        lines.append(f"  further: {len(out['further'])} declaration(s) reach it through these, "
                     "nearest first:")
        for f in out["further"][:10]:
            tag = f"  [linked to {', '.join(claims[f['name']])}]" if f["name"] in claims else ""
            lines.append(f"    {f['depth']}  {f['name']}  (through {f['through']}){tag}")
    if out.get("imports_without_use"):
        lines.append("  imported without use by: " + ", ".join(out["imports_without_use"]))
    for a in out["applications"]:
        where = a["location"]
        lines.append(f"\n  application {a['id']} in {a['caller']}"
                     + (f" (in {a['via']})" if a.get("via") else "")
                     + f", at {where['path']}")
        if not a.get("available"):
            lines.append(f"    not described: {'; '.join(a.get('errors') or [])}")
            continue
        for p in a["params"]:
            arg = _text(p.get("argument"))
            ty = _text(p.get("type"))
            if p["role"] == "premise":
                lines.append(f"    premise   {p['binder']} : {ty}\n"
                             f"              {DISCHARGE[p['discharge']]}: {p['supplied']}")
            else:
                lines.append(f"    {p['role']:10}{p['binder']} : {ty} := {arg}"
                             + (f"  ({p['supplied']})" if p.get("supplied") else ""))
        for o in a.get("unsupplied") or []:
            lines.append(f"    left open: {o['binder']} ({o['role']})")
        lines.append(f"    gives     {_text(a.get('result'))}")
    cited = [a for a in out["applications"] if a.get("available")]
    if cited:
        ref = {"callee": d["name"], **({"module": module} if module else {}), "id": cited[0]["id"]}
        lines.append("\n  cite as evidence: " + cite_text({"app": ref})
                     + (" (or another application's id)" if len(cited) > 1 else ""))
    if out.get("applications_note"):
        lines.append("  " + out["applications_note"])
    lines.append(f"  {out['note']}")
    if out.get("cache", {}).get("hit"):
        lines.append("  (from the cache: no Lean input changed)")
    return "\n".join(lines)
