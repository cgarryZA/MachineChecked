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

What a recorded difference affects at one use is a finding of a workspace with an `impact`
(`impact_content`): the difference finding it concerns (pinned to the version read), the use (an
evidence record citing an application of the differing declaration), the requirement at that use
(the finding's own `requirement`, of the claim whose Lean makes the application), the outcome
(`OUTCOMES`) and the reviewer's explanation, with the evidence the finding cites. Each use has
its own: an outcome recorded for one application says nothing of another. The finding goes stale
when the application changes (a change to the caller's proof alone does it, while the
difference, a comparison of statements, stays current), when the difference finding changes, is
superseded or goes stale, or when the requirement changes. The impact answer lists the impacts
recorded at the target's applications (`recorded`). An impact is the reviewer's attributed
reading; it changes no status and erases no difference.
"""

from __future__ import annotations

import hashlib
import json
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


def _trace_use(g: Graph, name: str, target: str, dist: dict[str, int], blocked: set[str],
               missing) -> tuple[str, dict, str | None]:
    """How `name` uses `target` by the references of `g` (`dist`: `g.distances(target)`;
    `blocked`: the declarations that reach one whose references are not recorded): `(use,
    paths, reason)`. `use` is `itself`, a value kind (`proof`, ...), `statement`, `none`, or `not
    traced` with the `reason` (`missing(n)` says why `n` has no recorded references)."""
    if name == target:
        return "itself", {}, None
    if target in g.ambiguous:
        return "not traced", {}, f"several modules declare {target}"
    if not g.known(name):
        return "not traced", {}, missing(name)
    paths = g.trace(name, target, dist)
    use = next((k for k in [*VALUE_KINDS, "statement"] if k in paths), None)
    if use is None and name in blocked:
        return "not traced", paths, "; ".join(f"it reaches {n}, and {missing(n)}"
                                              for n in g.unknown_from(name))
    return use or "none", paths, None


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


def _recorded_for(site, name: str, root: Path) -> list[dict]:
    """The impacts the workspaces of the build's working directory record at uses of `name`
    (`recorded`); none when the build cannot be read as a workspace's build."""
    from .targets import Snapshot, TargetError
    try:
        snap = Snapshot(site.data)
    except TargetError:
        return []
    return recorded(site.data.parent.parent, snap, name, root)


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
        use, paths, reason = _trace_use(g, name, tname, dist, blocked, missing)
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
    found = _recorded_for(site, tname, root)
    for m in mains:
        here = [r for r in found if r["use"]["id"] in (m.get("applications") or [])]
        if here:
            m["impacts"] = [{"finding": r["finding"], "workspace": r["workspace"],
                             "application": r["use"]["id"], "outcome": r["outcome"]}
                            for r in here]
    return {
        **head, "ok": True,
        "declaration": decl, "linked_to": claims_of.get(tname, []),
        "selection": {k: v for k, v in sel.items() if k != "main_results"},
        "main_results": mains,
        "claims": claims, "claims_note": CLAIMS_NOTE,
        "applications": [apps[i] for i in cited],
        "applications_complete": doc.get("applications_complete"),
        "imports_without_use": doc.get("imports_without_use") or [],
        "recorded": found, "applications_all": [a["id"] for a in doc.get("applications") or []],
        "locations": {n: where(n) for n in sorted(used_names) if g.module.get(n)},
        "scope": {"libraries": sc.get("libraries") or [], "modules": len(refs["built"]),
                  "unbuilt": refs["unbuilt"], "failed": failed,
                  "without_references": refs["missing"], "declarations": len(g.module)},
        "complete": not any(d["use"] == "not traced" for d in traced),
        "cache": doc.get("cache"),
    }


# -- each link, by the main results -----------------------------------------------------------

LINK_USE_SCHEMA = "machinechecked/link-use@1"
LINK_USE_NOTE = ("How each main result's Lean uses each link, by the references of Lean's "
                 "elaborated terms the build stored: a use is a path of references, direct or "
                 "through other declarations; importing a module is not a use; a trace that "
                 "reaches a declaration whose references are not recorded reads not traced, "
                 "never unused. It changes no status.")
FULL_UNAVAILABLE = ("not available in a full assessment: its build records no reverse "
                    "references (#480); `compare --query impact NAME` traces one declaration on "
                    "request")
MAIN_USE_FILE = "main-use.json"


def unavailable(reason: str) -> dict:
    return {"schema": LINK_USE_SCHEMA, "available": False, "reason": reason}


class ViewClaims:
    """The claims of a zero-configuration view (`simple.build_view`) as `selection` and
    `link_uses` read a site's: each with its links, its kind and whether it is a proof step, for
    `check`, which writes no site."""

    def __init__(self, body: dict):
        from .steps import is_step
        self._commit = body.get("commit")
        self.claims = [{"id": c["id"]} for c in body["claims"]]
        self._chunks = {c["id"]: {"id": c["id"], "number": c.get("number"), "kind": c.get("kind"),
                                  "links": [{"name": l["name"]} for l in c.get("links") or []],
                                  "clauses": [], **({"step": True} if is_step(c) else {})}
                        for c in body["claims"]}

    def chunk(self, cid: str) -> dict | None:
        return self._chunks.get(cid)

    def snapshot(self) -> dict:
        return {"project": {"commit": self._commit} if self._commit else {}}


def link_uses(site, root: Path, saved: dict | None = None) -> dict:
    """How each main result uses each link of each claim of `site` (a `compare.Site`, or
    `ViewClaims`): `claims`, by claim and link, one entry per main result with its `use`
    (`itself`, `proof`, `definition body`, `value`, `statement`, `none` or `not traced`), its
    `answer` in words and, for a use, how many declarations the shortest path goes `through` and
    the `path` itself. The main results are those `saved` in a workspace, with their problems,
    else the suggestion (`selection`), whose basis the answer states. Every link is traced on one
    graph of the references the facts store holds (`uses.reference_records`, read without
    starting Lean)."""
    from . import compare as cmp
    from . import uses as us
    sel = selection(site, None, cmp.linked_claims(site), saved)
    refs = us.reference_records(root)
    g = Graph(refs["records"])
    blocked = g.reaching(g.unknown)
    why: dict[str, str] = {}
    dists: dict[str, dict[str, int]] = {}

    def missing(n: str) -> str:
        if n not in why:
            why[n] = _not_traced(root, g, n, refs, {})
        return why[n]

    def one(main: str, link: str) -> dict:
        if link not in dists:
            dists[link] = {} if link in g.ambiguous else g.distances(link)
        if main != link and link not in g.ambiguous and not g.known(link):
            # Without the link's own record, its name may not be a declaration of the project's
            # traced modules at all: a use of it is not looked for.
            use, paths, reason = "not traced", {}, f"for {link}, {missing(link)}"
        else:
            use, paths, reason = _trace_use(g, main, link, dists[link], blocked, missing)
        out = {"main": main, "use": use,
               "answer": _answer(use, paths, True, g.kind.get(main), reason)}
        p = paths.get(use)
        if p:
            out["through"] = len(p) - 1
            out["path"] = [p[0]["from"], *(s["to"] for s in p)]
        return out

    mains = [e["name"] for e in sel["main_results"]]
    claims: dict[str, dict[str, list[dict]]] = {}
    for meta in site.claims:
        ch = site.chunk(meta["id"]) or {}
        names = list(dict.fromkeys(l["name"] for l in ch.get("links") or [] if l.get("name")))
        if names:
            claims[ch.get("id") or meta["id"]] = {n: [one(m, n) for m in mains] for n in names}
    traced = [x for per in claims.values() for xs in per.values() for x in xs]
    return {"schema": LINK_USE_SCHEMA, "available": True,
            "selection": {**{k: v for k, v in sel.items() if k not in ("main_results", "edit")},
                          "main_results": [{k: e[k] for k in ("name", "claims", "selected")}
                                           for e in sel["main_results"]]},
            "claims": claims,
            "scope": {"modules": len(refs["built"]), "unbuilt": refs["unbuilt"],
                      "without_references": refs["missing"], "declarations": len(g.module)},
            "complete": not any(x["use"] == "not traced" for x in traced),
            "note": LINK_USE_NOTE}


def _saved_or_reason(work_dir: Path | None, data: Path | None, root: Path | None):
    """The main results the workspaces of `work_dir` save, as `selection` takes them (with what
    the build whose site data is `data` lacks of them; `data` None when there is no such site),
    or None when none saves any; a string, the reason, when several do: selections are never
    merged."""
    if work_dir is None or not Path(work_dir).exists():
        return None
    from . import workspace as wsp
    found = wsp.main_result_selections(Path(work_dir))
    if len(found) > 1:
        return ("several workspaces save main results ("
                + ", ".join(f"{s['workspace']} by {s.get('by')}" for s in found)
                + "): they are never merged; keep one with `machinechecked workspace main`, "
                  "clearing the others with `--clear`")
    if not found:
        return None
    (s,) = found
    if data is None:
        return s
    from .targets import Snapshot
    return {**s, "problems": wsp.main_results_problems(s, Snapshot(data), root)}


def site_link_uses(data: Path, root: Path | None, work_dir: Path | None = None) -> dict:
    """`link_uses` for the site data at `data`, traced from the main results the one workspace
    of `work_dir` that saves any saves, else the suggestion. Not available in a full assessment,
    without the Lean project, or when several workspaces save main results."""
    from . import compare as cmp
    site = cmp.Site(data)
    if (site.index.get("mode") or "full") != "simple":
        return unavailable(FULL_UNAVAILABLE)
    if root is None:
        return unavailable("no Lean project to read the stored references of")
    saved = _saved_or_reason(work_dir, data, root)
    if isinstance(saved, str):
        return unavailable(saved)
    return link_uses(site, root, saved)


def view_link_uses(view: dict, root: Path, work_dir: Path | None = None) -> dict:
    """`link_uses` for a zero-configuration view that `check` computed without writing its
    site: from its claims (`ViewClaims`), or, when a workspace saves main results, from its site
    written to a temporary directory, against which their problems are checked."""
    saved = _saved_or_reason(work_dir, None, root)
    if isinstance(saved, str):
        return unavailable(saved)
    if saved is None:
        return link_uses(ViewClaims(view["body"]), root)
    import tempfile
    from .simple import write_view_site
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        write_view_site({**view, "pdf": None}, site, None, root)
        return site_link_uses(site / "data", root, work_dir)


def write_link_uses(data: Path, root: Path | None, work_dir: Path | None = None) -> dict:
    """Write `site_link_uses` beside the site data at `data` (`data/main-use.json`, which the
    reader's link panel reads)."""
    from .util import write_json
    doc = site_link_uses(data, root, work_dir)
    write_json(data / MAIN_USE_FILE, doc, indent=None)
    return doc


# -- text ------------------------------------------------------------------------------------

def path_text(steps: list[dict]) -> str:
    """A path for the terminal: `A -proof-> B -statement-> C`."""
    out = steps[0]["from"] if steps else ""
    for s in steps:
        out += f" -{'/'.join(s['refs'])}-> {s['to']}"
    return out


def _application_body(a: dict) -> list[str]:
    """What an application of the target supplies and gives, as `_application_lines` prints
    it below its heading."""
    from .uses import DISCHARGE
    if not a.get("available"):
        return [f"        not described: {'; '.join(a.get('errors') or [])}"]
    out = [f"        premise {p['binder']} : {p.get('statement')}  "
           f"({DISCHARGE.get(p['discharge'], p['discharge'])}: {p['supplied']})"
           for p in a.get("premises") or []]
    res = a.get("result")
    return out + [f"        gives {res.get('text') if isinstance(res, dict) else res}"]


def _ids_text(ids: list[str]) -> str:
    """Application ids for the terminal: `app:X:0 to app:X:7` for a run of consecutive ids of
    one declaration, else each of them."""
    heads = {i.rpartition(":")[0] for i in ids}
    tails = [i.rpartition(":")[2] for i in ids]
    if len(ids) > 2 and len(heads) == 1 and all(t.isdigit() for t in tails):
        nums = [int(t) for t in tails]
        if nums == list(range(nums[0], nums[0] + len(nums))):
            return f"{ids[0]} to {ids[-1]}"
    return ", ".join(ids)


def _application_lines(apps: list[dict]) -> list[str]:
    """The applications of the target at the end of a main result's path, each named by the id
    `uses` gives and workspace evidence cites. Applications in one declaration with the same
    premises and result are shown once, with their number and their ids (`uses` gives each
    one's arguments)."""
    groups: dict[tuple, list[dict]] = {}
    for a in apps:
        groups.setdefault((a["caller"], a.get("via"), tuple(_application_body(a))), []).append(a)
    out = []
    for (caller, via, body), same in groups.items():
        where = f"in {caller}" + (f" (in {via})" if via else "")
        if len(same) == 1:
            out.append(f"      application {same[0]['id']} {where}")
        else:
            what = ("description" if not same[0].get("available") else
                    "premises and result" if same[0].get("premises") else "result")
            out.append(f"      {len(same)} applications {where}, with the same {what}: "
                       + _ids_text([a["id"] for a in same]))
        out += list(body)
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
        lines += _application_lines([apps[i] for i in m.get("applications") or []])
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
    lines += recorded_lines(doc)
    sc = doc["scope"]
    if sc["unbuilt"] or sc["failed"] or sc["without_references"]:
        lines.append("Not searched: " + "; ".join(x for x in (
            f"not built: {', '.join(sc['unbuilt'][:5])}" if sc["unbuilt"] else "",
            f"could not be loaded: {', '.join(list(sc['failed'])[:5])}" if sc["failed"] else "",
            f"references not recorded: {', '.join(sc['without_references'][:5])}"
            if sc["without_references"] else "") if x))
    lines.append(doc["note"])
    return "\n".join(lines)


# -- what a recorded difference affects at a use ------------------------------------------------

OUTCOMES = ("sufficient for this use", "not sufficient", "a separate scope question",
            "unresolved")
IMPACT_KEYS = ("difference", "use", "outcome", "why")
# What an impact keeps of the difference finding it concerns, as it was read.
PIN_KEYS = ("finding", "claim", "requirement", "sha256", "feature", "paper", "lean", "outcome")
DIFFERENCE = "difference"  # the dependency kind of the difference an impact concerns


def _err(msg: str):
    from .workspace import WorkspaceError
    return WorkspaceError(msg)


def difference_digest(d: dict) -> str:
    """A digest of what a difference finding says: its claim, its requirement and its
    difference."""
    body = {k: d.get(k) for k in ("claim", "requirement", "difference")}
    return "difference-v1:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def superseded_by(records: dict, fid: str) -> str | None:
    """The finding that supersedes `fid`, or None."""
    return next((r["id"] for r in records.values() if r.get("supersedes") == fid), None)


def _pin(d: dict) -> dict:
    diff = d.get("difference") or {}
    return {"finding": d["id"], "claim": d.get("claim"), "requirement": d.get("requirement"),
            "sha256": difference_digest(d),
            **{k: diff[k] for k in ("feature", "paper", "lean", "outcome") if diff.get(k)}}


def linked_names(snap, claim: str) -> list[str]:
    """The declarations the build links to `claim`: its links, locked statements and accepting
    theorems."""
    ch = snap.chunk(claim) if snap is not None else None
    return claim_names(ch) if ch else []


def impact_content(out: dict, imp, rec: dict, ws: dict, snap, cur: dict | None,
                   repin: bool) -> None:
    """The `impact` of a finding, checked: the difference finding it concerns (`difference`, an
    id; kept with the version read until re-pinned), the use (`use`, an evidence record of the
    finding's claim citing an application of a declaration the difference's claim is linked
    to), the outcome at that use and the reviewer's explanation (`why`). The requirement at the
    use is the finding's own `requirement`; the use joins the finding's evidence."""
    from .workspace import _choice, _text
    if not isinstance(imp, dict):
        raise _err("an impact is {difference, use, outcome, why}")
    extra = set(imp) - set(IMPACT_KEYS)
    if extra:
        raise _err(f"an impact has no field {', '.join(sorted(extra))}")
    for k, what in (("coverage", "a coverage"), ("difference", "a difference"),
                    ("verdict", "a verdict"), ("composition", "a composition")):
        if rec.get(k) not in (None, ""):
            raise _err(f"an impact is a finding of its own: it records what a difference "
                       f"affects at one use, not {what}")
    if not out.get("requirement"):
        raise _err("an impact names the requirement at the use (`requirement`: a requirement "
                   f"of {out['claim']}, the claim whose Lean makes the application)")
    d = imp.get("difference")
    fid = d.get("finding") if isinstance(d, dict) else d
    if not isinstance(fid, str) or not fid.strip():
        raise _err("an impact names the difference finding it concerns (`difference`)")
    fid = fid.strip()
    df = ws["records"].get(fid)
    if not df or df.get("kind") != "finding" or not df.get("difference"):
        raise _err(f"{fid} is not a finding of this workspace that records a difference")
    if df.get("impact"):
        raise _err(f"{fid} records an impact; name the finding that records the difference")
    later = superseded_by(ws["records"], fid)
    if later:
        raise _err(f"{fid} is superseded by {later}; name the finding in force")
    use = imp.get("use")
    if not isinstance(use, str) or not use.strip():
        raise _err("an impact names its use (`use`: an evidence record citing an application, "
                   "as `compare --query uses` or `impact` gives it)")
    use = use.strip()
    u = ws["records"].get(use)
    if not u or u.get("kind") != "evidence" or not (u.get("ref") or {}).get("app"):
        raise _err(f"{use} is not an evidence record citing an application: a use is one "
                   "application of the declaration (`ref`: {app: {callee, id}})")
    if u["claim"] != out["claim"]:
        raise _err(f"{use} is evidence for {u['claim']}, not {out['claim']}")
    if u.get("role") == "rejected":
        raise _err(f"{use} is a rejected candidate")
    callee = u["ref"]["app"].get("callee")
    names = linked_names(snap, df["claim"])
    if names and callee not in names:
        raise _err(f"{use} applies {callee}, but the difference {fid} is about the Lean of "
                   f"{df['claim']} ({', '.join(names)}): an impact is recorded at a use of that "
                   "Lean")
    old = (cur or {}).get("impact") or {}
    pin = dict(old["difference"]) if not repin and (old.get("difference") or {}).get(
        "finding") == fid else _pin(df)
    out["impact"] = {"difference": pin, "use": use,
                     "outcome": _choice(imp.get("outcome"), OUTCOMES, "the outcome at this use",
                                        False),
                     "why": _text(imp.get("why"), "the reviewer's explanation (`why`)",
                                  True).strip()}
    out["evidence"] = list(dict.fromkeys([*(out.get("evidence") or []), use]))


def difference_item(f: dict) -> dict:
    """The dependency of an impact finding on the difference it concerns, as it pinned it."""
    pin = (f.get("impact") or {}).get("difference") or {}
    return {"dependency": DIFFERENCE, "record": pin.get("finding"), "claim": pin.get("claim"),
            "requirement": pin.get("requirement"), "sha256": pin.get("sha256")}


def difference_currency(it: dict, records: dict, snap, root=None, cur: dict | None = None,
                        check_facts: bool = False) -> dict:
    """Whether the difference an impact concerns is the one it read and still current: stale
    when it is gone, superseded or changed, or when what it rests on changed; unchecked when its
    own currency is not known."""
    fid = it.get("record")
    d = records.get(fid or "")
    if not d or d.get("kind") != "finding" or not d.get("difference"):
        return {"state": "stale", "changes": [{"finding": fid, "reason": (
            f"the difference {fid} the impact concerns is no longer in this workspace")}]}
    later = superseded_by(records, fid)
    if later:
        return {"state": "stale", "changes": [{"finding": fid, "now": later, "reason": (
            f"the difference {fid} the impact concerns is superseded by {later}")}]}
    if difference_digest(d) != it.get("sha256"):
        return {"state": "stale", "changes": [{"finding": fid, "reason": (
            f"the difference {fid} changed since the impact was recorded")}]}
    res = (cur or {}).get(fid)
    if res is None:
        from .dependencies import check
        res = check(d, records, snap, root, cur, check_facts)
    if res.get("state") == "stale":
        return {"state": "stale", "changes": [{"finding": fid, "reason": (
            f"what the difference {fid} rests on changed")}] + list(res.get("changes") or [])}
    if res.get("state") == "unchecked":
        why = "; ".join(dict.fromkeys(u.get("why") for u in res.get("unknown") or []
                                      if u.get("why"))) or res.get("reason")
        return {"state": "unchecked", "changes": [],
                "reason": f"the difference {fid} is not known to be current"
                          + (f": {why}" if why else "")}
    return {"state": "current", "changes": []}


def impact_words(imp: dict) -> str:
    """An impact's heading: its outcome at the use."""
    return f"At a use: {imp.get('outcome')}"


def difference_words(pin: dict) -> str:
    """The difference an impact concerns, as it pinned it."""
    out = f"the {pin.get('feature') or 'recorded'} difference {pin.get('finding')}"
    where = " ".join(x for x in (pin.get("claim"), pin.get("requirement")) if x)
    sides = "; ".join(x for x in ((f"paper {pin['paper']}" if pin.get("paper") else ""),
                                  (f"Lean {pin['lean']}" if pin.get("lean") else "")) if x)
    return out + (f" on {where}" if where else "") + (f" ({sides})" if sides else "")


def recorded(work_dir: Path, snap, name: str, root: Path | None = None) -> list[dict]:
    """The impacts the workspaces of `work_dir` record at uses of the declaration `name`, each
    with its workspace and auditor, the use's application, the requirement at the use, the
    outcome, the explanation, the difference it concerns and its currency."""
    from . import workspace as wsp
    out = []
    for _, ws in wsp.list_all(work_dir):
        if not any((r.get("impact") or {}).get("use") for r in ws["records"].values()):
            continue
        v = wsp.view(ws, snap, None, root)
        for cid, c in v["claims"].items():
            evidence = {e["id"]: e for e in c.get("evidence") or []}
            reqs = {r.get("local_id"): r for r in (c.get("reading") or {}).get("requirements")
                    or []}
            for f in c.get("findings") or []:
                imp = f.get("impact")
                app = ((evidence.get((imp or {}).get("use")) or {}).get("ref") or {}).get("app")
                if not imp or not app or app.get("callee") != name:
                    continue
                out.append({"finding": f["id"], "claim": cid, "workspace": ws["id"],
                            "reviewer": v["reviewer"], "mode": v["mode"],
                            "state": f.get("state"), "in_force": f.get("in_force"),
                            "requirement": f.get("requirement"),
                            "requirement_text": (reqs.get(f.get("requirement")) or {}).get(
                                "text"),
                            "outcome": imp["outcome"], "why": imp.get("why"),
                            "use": {"evidence": imp["use"], "id": app.get("id"),
                                    "caller": app.get("caller"), "callee": app.get("callee")},
                            "difference": imp.get("difference"),
                            "currency": (f.get("currency") or {}).get("state")})
    return out


def recorded_lines(doc: dict) -> list[str]:
    """The impacts recorded at the target's uses, and its applications with none, for the
    terminal."""
    recs = doc.get("recorded") or []
    if not recs and not doc.get("applications_all"):
        return []
    out = ["Recorded impacts at its uses (each is one reviewer's reading of one application):"]
    for r in recs:
        tag = r["currency"] + ("" if r.get("in_force", True) else ", superseded")
        out.append(f"  {r['use']['id']} in {r['use']['caller']}: {r['outcome']}, for "
                   f"{r['requirement']} of {r['claim']}"
                   + (f" ({r['requirement_text']})" if r.get("requirement_text") else "")
                   + f"  [{r['finding']}, {r['reviewer']}, {tag}]")
        out.append(f"    {difference_words(r.get('difference') or {})}")
        if r.get("why"):
            out.append(f"    why: {r['why']}")
    seen = {r["use"]["id"] for r in recs if r.get("in_force", True)}
    none = [a for a in doc.get("applications_all") or [] if a not in seen]
    if not recs:
        out.append("  none")
    if none:
        out.append("  no impact recorded at: " + _ids_text(none))
    return out
