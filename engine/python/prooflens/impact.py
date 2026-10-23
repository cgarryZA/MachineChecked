"""Which main results use a declaration, and which claims' Lean uses it: `compare --query impact
NAME`.

The trace reads the references of Lean's elaborated terms that `compare --query uses` reads
(`uses.py`): for every declaration of the project's built modules, the project's constants its
statement mentions and those its value uses (a theorem's proof, a definition's body), without the
types of its own parameters, which repeat the statement. A constant Lean generated for a
declaration (an auxiliary lemma, a matcher) is part of that declaration's value. Importing a
module is not a use.

Each selected main result is traced on its own. Its proof uses the declaration when a path of
references leads from its proof to it, and its statement uses it when one leads from its
statement; the answer gives the shortest path of each, direct or through other declarations,
and the applications of the declaration at the end of a proof's path (`uses.application`: the
actual arguments, each premise with how it is supplied, and the result). A trace is complete when
every declaration it reaches has its references recorded; otherwise it answers "not traced",
never "not used". The claims whose linked Lean uses the declaration are traced the same way: a
difference between the declaration and the paper can matter only to them.

The main results are those named (`--main`), else those an auditor saved in a workspace
(`workspace main`), else a suggestion shown as such: the declarations linked to the paper's
theorems. A saved selection says whose it is, when it was saved and against which project commit,
and names what it holds that the build does not (a claim no longer in the release, a declaration
no longer declared).

A trace is a fact about the Lean terms of this build; whether a difference matters at a use
takes a reviewer. The answer changes no status.
"""

from __future__ import annotations

from pathlib import Path

SCHEMA = "machinechecked/impact@1"
NOTE = ("A use is a reference in Lean's elaborated terms, made directly or through the "
        "declarations on the path; importing a module is not a use. Whether a difference in the "
        "declaration matters at a use takes a reviewer: compare the requirement at that "
        "application with the difference. This answer changes no status.")
SUGGESTED = "the declarations linked to the paper's theorems"
EDIT = ("choose the main results with --main NAME (a declaration, or a claim for its linked Lean); "
        "`machinechecked workspace main NAME...` saves them in your workspace")
CLAIMS_NOTE = ("the claims whose linked Lean uses the declaration, by its proof, its definition "
               "or its statement: a difference between the declaration and the paper can matter "
               "only to these")

# How a declaration's value refers to another, by the kind of declaration (`uses.VALUE_REF`).
VALUE_REF = {"proof": "proof", "definition body": "definition body", "none": "value"}
VALUE_KINDS = ("proof", "definition body", "value")
LABEL = {"proof": "proof", "definition body": "definition", "value": "value"}


class Graph:
    """The references between the project's declarations, from `refs` records: for each
    declaration, the declarations its statement and its value mention, each with how."""

    def __init__(self, recs: list[dict]):
        self.module: dict[str, str | None] = {}
        self.kind: dict[str, str | None] = {}
        self.ambiguous: set[str] = set()
        owner: dict[str, str] = {}
        value_kind: dict[str, str] = {}
        recs = [r for r in recs if r.get("record", "refs") == "refs" and r.get("name")]
        for r in recs:
            n = r["name"]
            o = r.get("owner") or n
            owner[n] = o
            if n == o:
                if o in self.module and self.module[o] != r.get("module"):
                    self.ambiguous.add(o)
                self.module.setdefault(o, r.get("module"))
                self.kind.setdefault(o, r.get("kind"))
                value_kind.setdefault(o, VALUE_REF.get(r.get("value_kind"), "value"))
        self.out: dict[str, dict[str, dict]] = {}
        self.users: dict[str, set[str]] = {}
        for r in recs:
            n = r["name"]
            o = owner[n]
            vk = value_kind.get(o, "value")
            for how, names in (("statement", r.get("statement") or []),
                               (vk, r.get("value") or [])):
                # A constant Lean generated for a declaration is part of its value.
                how = vk if n != o else how
                for t in names:
                    t = owner.get(t, t)
                    if t == o:
                        continue
                    e = self.out.setdefault(o, {}).setdefault(t, {"refs": [], "via": []})
                    if how not in e["refs"]:
                        e["refs"].append(how)
                    if n != o and n not in e["via"]:
                        e["via"].append(n)
                    self.users.setdefault(t, set()).add(o)
        # Declarations referred to whose own references are not recorded (or not one
        # declaration's): a trace that reaches one is incomplete.
        self.unknown = {t for t in self.users if t not in self.module} | self.ambiguous

    def known(self, name: str) -> bool:
        return name in self.module and name not in self.ambiguous

    def distances(self, target: str) -> dict[str, int]:
        """The length of the shortest path of references from each declaration to `target`."""
        dist = {target: 0}
        frontier = [target]
        while frontier:
            nxt = []
            for v in frontier:
                for u in sorted(self.users.get(v, ())):
                    if u not in dist and u not in self.ambiguous:
                        dist[u] = dist[v] + 1
                        nxt.append(u)
            frontier = nxt
        return dist

    def reaching(self, names: set[str]) -> set[str]:
        """The declarations from which a path of references leads to one of `names`."""
        seen = set(names)
        frontier = list(names)
        while frontier:
            nxt = []
            for v in frontier:
                for u in self.users.get(v, ()):
                    if u not in seen:
                        seen.add(u)
                        nxt.append(u)
            frontier = nxt
        return seen

    def unknown_from(self, start: str, limit: int = 3) -> list[str]:
        """The nearest declarations without recorded references that `start` reaches."""
        seen, frontier, out = {start}, [start], []
        while frontier and len(out) < limit:
            nxt = []
            for v in frontier:
                for t in sorted(self.out.get(v, {})):
                    if t in seen:
                        continue
                    seen.add(t)
                    (out if t in self.unknown else nxt).append(t)
            frontier = nxt
        return out[:limit]

    def step(self, a: str, b: str) -> dict:
        e = self.out[a][b]
        return {"from": a, "to": b, "refs": list(e["refs"]), **({"via": e["via"]} if e["via"]
                                                                  else {})}

    def path(self, start: str, dist: dict[str, int], target: str) -> list[dict]:
        """A shortest path of references from `start` to `target`, as steps."""
        steps, cur = [], start
        while cur != target:
            nxt = min(t for t in self.out.get(cur, {}) if dist.get(t) == dist[cur] - 1)
            steps.append(self.step(cur, nxt))
            cur = nxt
        return steps

    def trace(self, root: str, target: str, dist: dict[str, int]) -> dict[str, list[dict]]:
        """The shortest path from `root` to `target` that starts in its value, and the one that
        starts in its statement, by how it starts (`statement`, `proof`, ...)."""
        best: dict[str, tuple[int, str]] = {}
        for t, e in self.out.get(root, {}).items():
            if t not in dist:
                continue
            for how in e["refs"]:
                if how not in best or (dist[t], t) < best[how]:
                    best[how] = (dist[t], t)
        order = [*VALUE_KINDS, "statement"]
        return {how: [self.step(root, t)] + self.path(t, dist, target)
                for how, (_, t) in sorted(best.items(), key=lambda kv: order.index(kv[0]))}


# -- the main results ------------------------------------------------------------------------

def root_names(ch: dict) -> list[str]:
    """The declarations a claim's Lean starts from: its links and the theorems accepting its
    clauses, else its locked statements."""
    names = [l["name"] for l in ch.get("links") or [] if l.get("name")]
    names += [cl["accept"] for cl in ch.get("clauses") or [] if cl.get("accept")]
    if not names:
        names = [cl["spec"] for cl in ch.get("clauses") or [] if cl.get("spec")]
    return list(dict.fromkeys(names))


def claim_names(ch: dict) -> list[str]:
    """Every declaration linked to a claim: its links, locked statements and accepting
    theorems."""
    names = [l["name"] for l in ch.get("links") or [] if l.get("name")]
    names += [n for cl in ch.get("clauses") or [] for n in (cl.get("spec"), cl.get("accept"))
              if n]
    return list(dict.fromkeys(names))


def _saved(site, saved: dict, add) -> dict:
    """The selection saved in a workspace (`workspace.main_result_selections`, with its
    `problems` against this build): a claim stands for its linked Lean; a claim no longer in the
    build is among the problems, and a declaration stays a main result, traced or not."""
    unlinked = []
    for e in saved["selected"]:
        if e.get("claim"):
            ch = site.chunk(e["claim"])
            if ch is None:
                continue
            names = root_names(ch)
            if not names:
                unlinked.append(e["claim"])
            for n in names:
                add(n, e["claim"])
        else:
            add(e["decl"], "named")
    out = {"basis": "saved", **{k: saved[k] for k in ("workspace", "reviewer", "by", "at", "pins")
                                if saved.get(k) is not None},
           "selected": saved["selected"], "problems": saved.get("problems") or [],
           "unlinked_claims": unlinked, "edit": EDIT}
    was = (saved.get("pins") or {}).get("commit")
    now = (site.snapshot().get("project") or {}).get("commit")
    if was and now and was != now:
        out["note"] = (f"saved against project commit {was[:7]}; this build is of commit "
                       f"{now[:7]}")
    return out


def selection(site, main: list[str] | None, claims_of: dict[str, list[str]],
              saved: dict | None = None) -> dict:
    """The main results to trace from: those named in `main` (a declaration, or a claim for its
    linked Lean), else those `saved` in a workspace, else the suggestion, the declarations linked
    to the paper's theorems. `saved` is `{workspace, selected: None}` when the workspace named
    saves none."""
    from .compare import CompareError
    entries: list[dict] = []

    def add(name: str, by: str) -> None:
        e = next((x for x in entries if x["name"] == name), None)
        if e is None:
            entries.append({"name": name, "claims": claims_of.get(name, []), "selected": [by]})
        elif by not in e["selected"]:
            e["selected"].append(by)

    if main:
        unlinked = []
        for m in main:
            try:
                cid = site.resolve_claim(m)
            except CompareError as e:
                if e.kind == "ambiguous":
                    raise
                add(m, "named")
                continue
            names = root_names(site.chunk(cid) or {})
            if not names:
                unlinked.append(cid)
            for n in names:
                add(n, cid)
        return {"basis": "given", "main_results": entries, "unlinked_claims": unlinked,
                "edit": EDIT}
    if saved and saved.get("selected"):
        return {**_saved(site, saved, add), "main_results": entries}
    for meta in site.claims:
        ch = site.chunk(meta["id"]) or {}
        if ch.get("kind") == "theorem" and not ch.get("step"):
            for n in root_names(ch):
                add(n, ch["id"])
    out = {"basis": "suggested", "rule": SUGGESTED, "main_results": entries, "edit": EDIT}
    if saved:
        out["note"] = f"workspace {saved['workspace']} saves no main results"
    return out


# -- the answer ------------------------------------------------------------------------------

def _how_far(steps: list[dict]) -> str:
    n = len(steps) - 1
    return "directly" if n == 0 else f"through {n} other declaration{'s' if n > 1 else ''}"


def _answer(use: str, paths: dict, main: bool, kind: str | None,
            reason: str | None = None) -> str:
    if use == "itself":
        return "this is the main result itself" if main else "linked to it"
    if use in VALUE_KINDS:
        out = f"used by its {LABEL[use]}, {_how_far(paths[use])}"
        return out + ("; also in its statement" if "statement" in paths else "")
    if use == "statement":
        value = {"theorem": "proof", "def": "definition", "opaque": "definition"}.get(kind,
                                                                                    "value")
        return f"in its statement only, {_how_far(paths['statement'])}: not used by its {value}"
    if use == "none":
        return "formalized separately: not used by this main result" if main else \
            "its Lean does not use it"
    return f"not traced: {reason}"


def _not_traced(root: Path, g: Graph, name: str, refs: dict, failed: dict) -> str:
    """Why a declaration has no recorded references: the module whose source declares it is
    not built, could not be loaded, or has no recorded references."""
    from .simple import declaring_modules
    if name in g.ambiguous:
        return "several modules declare it"
    gaps = [(refs["unbuilt"], "its module is not built", ""),
            (sorted(failed), "its module could not be loaded", ""),
            (refs["missing"], "the references of its module are not recorded",
             "; `machinechecked view` or `build` records them")]
    for mods, what, then in gaps:
        found = declaring_modules(root, mods, name) if mods else []
        if found:
            return f"{what} ({', '.join(found)}){then}"
    return "no declaration of this name has recorded references in the project's built modules"


def _resolution(doc: dict) -> str:
    mods = ", ".join(doc.get("modules") or [])
    st = doc.get("status")
    if st == "ambiguous":
        return f"several modules declare it ({mods}); name one as MODULE:NAME"
    if st == "not built":
        return f"its module is not built ({mods})"
    if st == "not found":
        return "no declaration of this name in the project's libraries"
    if st == "not checked":
        return f"some built modules could not be loaded ({mods})"
    return doc.get("reason") or st or "its uses are not known"


def impact(site, root: Path, target: str, main: list[str] | None = None, log=None,
           saved: dict | None = None) -> dict:
    """The impact document of `target` (a declaration name, or `Module:Name`) in the Lean project
    at `root`, against the claims and links of `site` (a `compare.Site`), from the main results
    `main` names, else those `saved` in a workspace (`selection`). Lean is asked only for the
    uses of `target` (`uses.uses`, cached); the rest is read from the facts store."""
    from . import compare as cmp
    from . import uses as us
    module, _, name = target.rpartition(":") if ":" in target else ("", "", target)
    head = {"schema": SCHEMA, "id": f"impact:{name}", "name": name, "note": NOTE}
    doc = us.uses(root, name, module or None, log=log)
    if not doc.get("ok"):
        return {**head, "ok": False, "status": doc.get("status"),
                "modules": doc.get("modules") or [],
                "reason": f"not available: {_resolution(doc)}"}
    decl = doc["declaration"]
    tname = decl["name"]
    claims_of = cmp.linked_claims(site)
    refs = us.reference_records(root)
    g = Graph(refs["records"])
    failed = (doc.get("scope") or {}).get("failed") or {}
    dist = {} if tname in g.ambiguous else g.distances(tname)
    blocked = g.reaching(g.unknown)
    apps = {a["id"]: a for a in doc.get("applications") or []}
    ret = site.retrieval()
    used_names: set[str] = set()
    cited: list[str] = []
    why: dict[str, str] = {}

    def missing(n: str) -> str:
        if n not in why:
            why[n] = _not_traced(root, g, n, refs, failed)
        return why[n]

    def answer(name: str, main_result: bool) -> dict:
        out = {"name": name}
        if name == tname:
            use, paths, reason = "itself", {}, None
        elif tname in g.ambiguous:
            use, paths, reason = "not traced", {}, f"several modules declare {tname}"
        elif not g.known(name):
            use, paths, reason = "not traced", {}, missing(name)
        else:
            paths = g.trace(name, tname, dist)
            use = next((k for k in [*VALUE_KINDS, "statement"] if k in paths), None)
            reason = None
            if use is None and name in blocked:
                use = "not traced"
                reason = "; ".join(f"it reaches {n}, and {missing(n)}"
                                   for n in g.unknown_from(name))
            elif use is None:
                use = "none"
        out.update(use=use, answer=_answer(use, paths, main_result, g.kind.get(name), reason))
        if paths:
            main_path = paths.get(use) or next(iter(paths.values()))
            out["direct"] = len(main_path) == 1
            out["paths"] = {k: {"length": len(p), "steps": p} for k, p in paths.items()}
            for p in paths.values():
                for s in p:
                    used_names.update((s["from"], s["to"]))
        if main_result and use in VALUE_KINDS:
            last = paths[use][-1]
            if any(h in VALUE_KINDS for h in last["refs"]):
                ids = [i for i, a in apps.items() if a["caller"] == last["from"]]
                out["applications"] = ids
                cited.extend(i for i in ids if i not in cited)
                if not ids:
                    out["applications_note"] = (
                        f"the applications in {last['from']} are not described"
                        + (f": {doc['applications_note']}" if doc.get("applications_note")
                           else ""))
        return out

    sel = selection(site, main, claims_of, saved)
    mains = []
    for e in sel["main_results"]:
        mains.append({**{k: e[k] for k in ("name", "claims", "selected")},
                      **answer(e["name"], True)})
        used_names.add(e["name"])
    claims = []
    for meta in site.claims:
        ch = site.chunk(meta["id"]) or {}
        names = claim_names(ch)
        if not names:
            continue
        ds = [answer(n, False) for n in names]
        uses_ = {d["use"] for d in ds}
        relation = ("linked" if "itself" in uses_ else
                    "uses" if uses_ & {*VALUE_KINDS, "statement"} else
                    "not traced" if "not traced" in uses_ else "none")
        claims.append({"claim": ch.get("id") or meta["id"], "number": ch.get("number"),
                       "kind": ch.get("kind"), "relation": relation, "declarations": ds})

    def where(n: str) -> dict:
        w = {"module": g.module.get(n), "kind": g.kind.get(n)}
        i = ret.by_name.get(n) if ret is not None else None
        if i is not None and ret.docs[i].get("line"):
            w["line"] = ret.docs[i]["line"]
        return {k: v for k, v in w.items() if v is not None}

    traced = mains + [d for c in claims for d in c["declarations"]]
    sc = doc.get("scope") or {}
    return {
        **head, "ok": True,
        "declaration": decl, "linked_to": claims_of.get(tname, []),
        "selection": {k: v for k, v in sel.items() if k != "main_results"},
        "main_results": mains,
        "claims": claims, "claims_note": CLAIMS_NOTE,
        "applications": [apps[i] for i in cited],
        "applications_complete": doc.get("applications_complete"),
        "imports_without_use": doc.get("imports_without_use") or [],
        "locations": {n: where(n) for n in sorted(used_names) if g.module.get(n)},
        "scope": {"libraries": sc.get("libraries") or [], "modules": len(refs["built"]),
                  "unbuilt": refs["unbuilt"], "failed": failed,
                  "without_references": refs["missing"], "declarations": len(g.module)},
        "complete": not any(d["use"] == "not traced" for d in traced),
        "cache": doc.get("cache"),
    }


# -- text ------------------------------------------------------------------------------------

def path_text(steps: list[dict]) -> str:
    """A path for the terminal: `A -proof-> B -statement-> C`."""
    out = steps[0]["from"] if steps else ""
    for s in steps:
        out += f" -{'/'.join(s['refs'])}-> {s['to']}"
    return out


def _application_lines(a: dict) -> list[str]:
    from .uses import DISCHARGE
    out = [f"      application in {a['caller']}" + (f" (in {a['via']})" if a.get("via") else "")]
    if not a.get("available"):
        return out + [f"        not described: {'; '.join(a.get('errors') or [])}"]
    for p in a.get("premises") or []:
        out.append(f"        premise {p['binder']} : {p.get('statement')}  "
                   f"({DISCHARGE.get(p['discharge'], p['discharge'])}: {p['supplied']})")
    res = a.get("result")
    out.append(f"        gives {res.get('text') if isinstance(res, dict) else res}")
    return out


def _source_text(sel: dict) -> str:
    """Where the main results come from, for the heading of their list."""
    if sel["basis"] == "suggested":
        return f" (suggested: {sel['rule']})"
    if sel["basis"] == "saved":
        commit = (sel.get("pins") or {}).get("commit")
        return (f" (saved in workspace {sel['workspace']} by {sel.get('by')} at {sel.get('at')}"
                + (f", against project commit {commit[:7]}" if commit else "") + ")")
    return " (named with --main)"


def text(doc: dict) -> str:
    """An impact document for the terminal."""
    if not doc.get("ok"):
        return f"{doc['name']}: {doc['reason']}"
    d = doc["declaration"]
    lines = [f"{d['name']}  ({d.get('kind')}, {d.get('module')})"
             + (f"  [linked to {', '.join(doc['linked_to'])}]" if doc["linked_to"] else "")]
    sel = doc["selection"]
    lines.append("Main results" + _source_text(sel) + ":")
    if sel.get("note"):
        lines.append(f"  ({sel['note']})")
    if not doc["main_results"]:
        lines.append("  none")
    apps = {a["id"]: a for a in doc["applications"]}
    for m in doc["main_results"]:
        lines.append(f"  {m['name']}" + (f"  [{', '.join(m['claims'])}]" if m["claims"] else ""))
        lines.append(f"    {m['answer']}")
        for how, p in (m.get("paths") or {}).items():
            lines.append(f"    {how}: {path_text(p['steps'])}")
        for i in m.get("applications") or []:
            lines += _application_lines(apps[i])
        if m.get("applications_note"):
            lines.append(f"      {m['applications_note']}")
    for c in sel.get("unlinked_claims") or []:
        lines.append(f"  {c}: no Lean is linked to this claim")
    for p in sel.get("problems") or []:
        lines.append(f"  {p.get('claim') or p.get('decl')}: saved as a main result, but "
                     f"{p['problem']}")
    lines.append(f"  ({sel['edit']})")
    groups = {"linked": [], "uses": [], "not traced": [], "none": []}
    for c in doc["claims"]:
        groups[c["relation"]].append(c)
    lines.append("Claims whose Lean uses it (a difference in it can matter only to these):")
    for c in groups["linked"] + groups["uses"]:
        for x in c["declarations"]:
            if x["use"] not in ("none", "not traced"):
                who = "" if x["use"] == "itself" else f"{x['name']}: "
                lines.append(f"  {c['number'] or c['claim']}  [{c['claim']}]  {who}{x['answer']}")
    if not groups["linked"] + groups["uses"]:
        lines.append("  none")
    for c in groups["not traced"]:
        why = "; ".join(f"{x['name']}: {x['answer']}" for x in c["declarations"]
                        if x["use"] == "not traced")
        lines.append(f"  {c['number'] or c['claim']}  [{c['claim']}]  {why}")
    if groups["none"]:
        lines.append("Claims whose Lean does not use it: "
                     + ", ".join(c["number"] or c["claim"] for c in groups["none"]))
    if doc["imports_without_use"]:
        lines.append("Imported without use by: " + ", ".join(doc["imports_without_use"]))
    sc = doc["scope"]
    if sc["unbuilt"] or sc["failed"] or sc["without_references"]:
        lines.append("Not searched: " + "; ".join(x for x in (
            f"not built: {', '.join(sc['unbuilt'][:5])}" if sc["unbuilt"] else "",
            f"could not be loaded: {', '.join(list(sc['failed'])[:5])}" if sc["failed"] else "",
            f"references not recorded: {', '.join(sc['without_references'][:5])}"
            if sc["without_references"] else "") if x))
    lines.append(doc["note"])
    return "\n".join(lines)
