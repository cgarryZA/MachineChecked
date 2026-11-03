"""Typed facts inside a selected proof: `machinechecked compare --query proof-facts NAME`.

An exported theorem can prove more than it states: its proof may establish a sharper bound and
then weaken it, or a bound under a case hypothesis. The probe's other records erase proofs, so
that fingerprints and reviews see statements only. This asks Lean, for one declaration and on
request, for the propositions its elaborated proof term holds along the way:

* each `have` (or `let` of a proposition) and each goal a `show` states, with its type;
* each application of a theorem of the project, or of any theorem to a local fact, with the
  theorem's hypotheses at the application and the local that supplies each one;

each with the local context it holds in (the statement's binders, binders of the cases it lies
in, earlier facts), the locals it needs, the cases of the proof it lies in and its position in the
term. The source line of a named fact is found by its name in the declaration's source lines and
is marked as found that way; a `have` or `show` of the source with no typed counterpart is listed
apart, as source text only.

Lean reads one page of facts at a time: the facts after a given one (`after`, a fact's id), at or
under a position in the term (`within`, a fact's `at`, such as an application's), at most
`limits["facts"]` of them (200 by default). A fact's id is its place among all the facts of the
proof, so no page renumbers it, and each page reports a fact exactly as the whole list would.

A fact inside a proof is established inside this proof, under its context. It is never an
exported theorem, and nothing here says that one proposition implies another: a search ranks
candidates, it does not compare bounds.

The answer is kept in the facts store (`facts.py`) and reused until the modules it was read
from change, so asking again over unchanged input runs no Lean.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import work_dir_name
from .deps import NOT_CHECKED, _resolve, _short, _tool_version, not_checked_reason, store
from .facts import graphs
from .probe import lib_names
from .simple import ViewError, built_modules, module_failed_detail, probe_modules

SCHEMA = "machinechecked/proof-facts@1"
BASIS = "established inside this proof under this context"
EXPORTED = "exported theorem"
SOURCE_ONLY = "source text, with no typed fact"
NOTE = ("A fact inside a proof holds in its context only, under the assumptions listed with it. It "
        "is not an exported theorem, and a search ranks candidates without deciding whether one "
        "bound implies another.")
INSPECTED = ["the declaration's elaborated proof term, from its compiled module",
             "the declaration's source lines, to place named facts"]
NOT_INSPECTED = ["tactic states between steps (Lean keeps them only while it elaborates a file)",
                 "lemmas Lean generated for parts of the proof (listed under `auxiliary`; each "
                 "can be asked about by its own name)"]
KIND_WORDS = {"have": "stated in the proof", "show": "goal restated in the proof",
              "application": "theorem applied in the proof"}


KIND = "proof-facts"  # the facts store's kind for these answers


# -- the source ----------------------------------------------------------------------------

BINDING = re.compile(r"\b(have|haveI|let|obtain|rcases|rintro|intro|intros|cases|by_cases|"
                     r"suffices|set|fun|match|with|calc)\b|[|⟨λ]")
SOURCE_STEP = re.compile(r"^\s*(?:·\s*)?(have|haveI|suffices|show)\b\s*([^\s:=]*)")


def _source(root: Path, module: str, rng: dict | None) -> tuple[str, list[tuple[int, str]]]:
    from .layout import module_file
    file = module_file(root, module)
    if not rng:
        return file, []
    try:
        lines = (root / file).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return file, []
    first, last = rng.get("line") or 1, rng.get("end_line") or rng.get("line") or 1
    return file, [(i, lines[i - 1]) for i in range(first, min(last, len(lines)) + 1)]


def _code(line: str) -> str:
    return line.split("--", 1)[0]


def _place(facts: list[dict], file: str, lines: list[tuple[int, str]], rng: dict | None,
           complete: bool = True):
    """The source line of each named fact, found by its name, in order; the `have` and `show`
    lines of the source that no typed fact accounts for (or, when the walk was cut short, that
    no fact it reached accounts for)."""
    cursor = 0
    shows = [i for i, f in enumerate(facts) if f["kind"] == "show"]
    for f in facts:
        word = None
        if f["kind"] == "have" and f.get("name") and not f.get("generated_name") \
                and f["name"] != "this":
            word = f["name"]
        elif f["kind"] == "application" and f.get("head"):
            word = f["head"].rsplit(".", 1)[-1]
        found = None
        if word:
            pat = re.compile(r"(?<![\w.'])" + re.escape(word) + r"(?![\w'])")
            for k in range(cursor, len(lines)):
                code = _code(lines[k][1])
                if pat.search(code) and (f["kind"] == "application" or BINDING.search(code)):
                    found = k
                    break
        if found is not None:
            if f["kind"] == "have":
                cursor = found
            f["source"] = {"file": file, "line": lines[found][0],
                           "located": "by its name in the source"}
        else:
            f["source"] = {"file": file, "line": (rng or {}).get("line"),
                           "located": "the declaration only"}
    # `show` steps in source order, matched to the typed `show` facts in term order.
    show_lines = [n for n, t in lines if (_step(t) or ("",))[0] == "show"]
    for i, n in zip(shows, show_lines):
        facts[i]["source"] = {"file": file, "line": n, "located": "by its order in the source"}
    typed = {f.get("name") for f in facts if f["kind"] == "have"}
    anonymous = sum(1 for f in facts if f["kind"] == "have"
                    and (f.get("name") in (None, "this") or f.get("generated_name")))
    only, k_show, k_anon = [], 0, 0
    for n, t in lines:
        step = _step(t)
        if step is None:
            continue
        word, name = step
        if word == "show":
            k_show += 1
            kept = k_show <= len(shows)
        elif not name or name == "this":
            k_anon += 1
            kept = k_anon <= anonymous
        else:
            kept = name in typed
        if not kept:
            only.append({"kind": "source line", "basis": SOURCE_ONLY,
                         "source": {"file": file, "line": n}, "text": t.strip()[:300],
                         "note": "the source states this here; the compiled proof keeps no "
                                 "typed fact for it" if complete else
                                 "the source states this here; the walk stopped before any "
                                 "typed fact for it"})
    return only


def _step(line: str) -> tuple[str, str] | None:
    """A `have`, `haveI`, `suffices` or `show` step of a source line: the keyword and the name
    it gives (empty when none)."""
    m = SOURCE_STEP.match(_code(line))
    if not m:
        return None
    name = m.group(2)
    return m.group(1), "" if name.startswith(("(", "⟨", ":")) else name


# -- assembling the answer -----------------------------------------------------------------

def _text(pp) -> str:
    return (pp or {}).get("text", "") if isinstance(pp, dict) else str(pp or "")


def _index(f: dict) -> int:
    return int(f["id"][1:])


def _assemble(rec: dict, root: Path) -> dict:
    locals_ = {l["id"]: l for l in rec.get("locals") or []}
    scopes = {s["id"]: dict(s) for s in rec.get("scopes") or []}
    for s in scopes.values():
        s["binds"] = [l["id"] for l in locals_.values()
                      if l.get("origin") == "bound" and (l.get("scope") or [None])[-1] == s["id"]]
        s["text"] = _scope_text(s, locals_)
    facts = [dict(f) for f in rec.get("facts") or []]
    for f in facts:
        f["basis"] = BASIS
        f["what"] = KIND_WORDS.get(f["kind"], f["kind"])
        f["assumptions"] = [_local_ref(locals_.get(i), i) for i in f.get("needs") or []]
        f["cases"] = [scopes[s]["text"] for s in f.get("scope") or [] if s in scopes]
        f["uses_facts"] = list(f.get("uses_facts") or [])
        f["used_by"] = list(f.get("used_by") or [])
        f["ref"] = {"decl": rec["name"], "module": rec.get("module"), "at": f["at"],
                    "fact_hash": f["fact_hash"], "proof_hash": rec.get("proof_hash")}
    cut = list(rec.get("cut") or [])
    file, lines = _source(root, rec.get("module") or "", rec.get("range"))
    # The source lines are matched against every `have` and `show` of the proof (the record's
    # outline), the page's own facts among them, so a fact is placed as the whole list places it.
    mine = {f["id"]: f for f in facts}
    walk = {o["id"]: dict(o) for o in rec.get("outline") or []} | mine
    only = _place(sorted(walk.values(), key=_index), file, lines, rec.get("range"), not cut)
    page = rec.get("page") or {}
    return {
        "declaration": {"name": rec["name"], "kind": rec.get("kind"), "module": rec.get("module"),
                        "file": file, "range": rec.get("range"),
                        "statement": rec.get("statement"),
                        "basis": EXPORTED if rec.get("kind") == "theorem" else
                        f"exported {rec.get('kind') or 'declaration'}",
                        "axioms": rec.get("axioms") or [], "sorry": bool(rec.get("sorry"))},
        "proof": {"hash": rec.get("proof_hash"), "visited": rec.get("visited"),
                  "complete": not cut, "cut": [{"nodes": "the walk reached its node limit"}
                                               .get(c, c) for c in cut],
                  "limits": rec.get("limits"), "auxiliary": rec.get("auxiliary") or [],
                  "inspected": INSPECTED, "not_inspected": NOT_INSPECTED},
        "page": {"after": page.get("after"), "within": page.get("within"),
                 "size": (rec.get("limits") or {}).get("facts"),
                 "before": page.get("before") or 0, "count": page.get("kept", len(facts)),
                 "total": page.get("selected", len(facts)), "more": bool(page.get("more")),
                 "next": page.get("last") if page.get("more") else None},
        "facts": facts, "locals": list(locals_.values()), "scopes": list(scopes.values()),
        "source_only": only,
    }


def _local_ref(l: dict | None, i: str) -> dict:
    if l is None:
        return {"id": i}
    return {"id": i, "name": l.get("name"), "role": l.get("role"), "origin": l.get("origin"),
            "type": _text(l.get("type"))}


def _scope_text(s: dict, locals_: dict) -> str:
    binds = [locals_[i] for i in s.get("binds") or []]
    shown = ", ".join(f"{l['name']} : {_text(l.get('type'))}" for l in binds)
    return (f"in the case {shown}" if shown else "in a case") + \
        f" (argument {s['arg']} of {s['head']})"


# -- matching ------------------------------------------------------------------------------

TOKEN = re.compile(r"[\w.'₀-₉]+|[^\s\w()]")


def _tokens(s: str) -> list[str]:
    return [t for t in TOKEN.findall(s or "")]


def rank(facts: list[dict], query: str) -> list[dict]:
    """The facts that share a token with `query`, most shared first, each with what matched.
    A ranking only: a match says the texts share symbols, not that one bound gives another."""
    want = set(_tokens(query))
    out = []
    for f in facts:
        have = _tokens(_text(f.get("type"))) + [f.get("name") or "", f.get("head") or ""]
        hits = sorted(want & set(have))
        if hits:
            out.append({**f, "match": {"shared": hits, "score": len(hits) / max(len(want), 1)}})
    return sorted(out, key=lambda f: (-f["match"]["score"], f["id"]))


# -- the request ---------------------------------------------------------------------------

FACT_ID = re.compile(r"f(\d+)")
POSITION = re.compile(r"/(?:[0-3](?:/[0-3])*)?")


def page_request(after: str | None, within: str | None) -> dict:
    """The probe's fields for a page: the facts after the fact `after` (its id, `f12`), at or
    under the term position `within` (a fact's `at`, `/1/0/1`). Raises ValueError on anything
    else."""
    out = {}
    if after is not None:
        m = FACT_ID.fullmatch(after)
        if not m:
            raise ValueError(f"{after!r} is not a fact of a proof (f0, f1, …, as a page gives "
                             "them)")
        out["facts_after"] = int(m.group(1))
    if within is not None:
        if not POSITION.fullmatch(within):
            raise ValueError(f"{within!r} is not a position in a proof term (a fact's at, "
                             "such as /1/0/1)")
        out["facts_within"] = within
    return out


def extract(root: Path, name: str, module: str | None = None, lake: str = "lake", log=None,
            refresh: bool = False, limits: dict | None = None, cached_only: bool = False,
            after: str | None = None, within: str | None = None) -> dict:
    """The facts inside the proof of `name` in the Lean project at `root`, as one JSON-ready
    document. `limits` (`nodes`, `facts`, and `heartbeats` in thousands) bound the walk, `facts`
    the facts of one page; `after` (a fact's id) and `within` (a term position) say which page
    (`page_request`), and `page` in the answer says which it is and whether more remain;
    `cached_only` answers from the facts store or not at all (`status: "not extracted"`).

    The answer is kept in the facts store shared with `view`, `build`, `check` and `inspect`
    and reused while the modules of the environment it was read from (the declaration's module
    and what it imports, sources and compiled files) and the probe are unchanged; an edit to
    another module keeps it."""
    try:
        page = page_request(after, within)
    except ValueError as e:
        raise ViewError(str(e)) from None
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
    st = store(root, libs)
    asked = {**(limits or {}), **({"after": after} if after else {}),
             **({"within": within} if within else {})}
    key = f"{name}\0{target or '*'}\0{json.dumps(asked, sort_keys=True)}"
    if cached_only or not refresh:
        entry, _ = st.get(KIND, key)
        if entry is not None:
            return {**head, **entry["body"], "cache": {"hit": True, "key": _short(key)}}
    if cached_only:
        return {**head, "ok": False, "status": "not extracted",
                "reason": "the facts of this proof have not been read since the Lean last "
                          "changed"}
    with st.lock(log):
        entry, _ = (None, None) if refresh else st.get(KIND, key)
        if entry is not None:  # another process read it meanwhile
            return {**head, **entry["body"], "cache": {"hit": True, "key": _short(key)}}
        work = root / work_dir_name(root) / "build"
        request = [{"kind": "proof-facts", "name": name, **page},
                   {"kind": "modules", "name": ""}]
        extra = {"facts_nodes": (limits or {}).get("nodes"),
                 "facts_items": (limits or {}).get("facts"),
                 "max_heartbeats": (limits or {}).get("heartbeats")}
        extra = {k: v for k, v in extra.items() if v}
        quiet = log or (lambda m: None)
        if target is not None:
            recs, failed = probe_modules(root, [target], libs, request, lake, log=quiet,
                                         work=work, extra=extra)
            if failed:
                raise ViewError(module_failed_detail(target, failed[target], root=root))
            env = st.environment([target], next(iter(graphs(recs).values()), {}))
        else:
            # The source does not show the name: ask every library, each in its own session.
            recs, failed = probe_modules(root, built, libs, request, lake, log=quiet, work=work,
                                         extra=extra)
            hits = [r for r in recs if r.get("record") == "proof-facts" and r.get("name") == name
                    and not r.get("errors")]
            if len({h.get("module") for h in hits}) > 1:
                return {**head, "ok": False, "status": "ambiguous",
                        "modules": sorted(h.get("module") for h in hits)}
            if not hits and failed:
                return {**head, "ok": False, "status": "not checked", "modules": sorted(failed),
                        "reason": "some built modules could not be loaded"}
            recs = hits or recs
            graph: dict[str, list[str]] = {}
            for g in graphs(recs).values():
                graph.update(g)
            env = st.environment(built, graph)
        rec = next((r for r in recs if r.get("record") == "proof-facts"
                    and r.get("name") == name), None)
        errors = (rec or {}).get("errors") or []
        if rec is None or "missing" in errors:
            body = {"ok": False, "status": "not found", "modules": [target] if target else []}
        elif "no-value" in errors:
            body = {"ok": False, "status": "no proof",
                    "reason": f"{name} is a {rec.get('kind')}: it has no proof or body to look "
                              "into"}
        elif any(e.startswith("probe-error") for e in errors):
            # The request failed (it ran out of heartbeats, say); nothing is stored, so asking
            # again retries it.
            return {**head, "ok": False, "status": "probe error", "reason": errors[0],
                    "cache": {"hit": False, "key": _short(key)}}
        else:
            body = {"ok": True, "status": "found", **_assemble(rec, root)}
        st.put(KIND, key, env, body=body)
    return {**head, **body, "cache": {"hit": False, "key": _short(key)}}


def locate(root: Path, ref: dict, limits: dict | None = None) -> tuple[dict, dict | None]:
    """The answer that holds the fact `ref` names (`{decl, at, fact_hash?, module?}`), and the
    fact, None when the proof no longer has it: the first page of the proof, else the pages of
    the facts at or under its position."""
    doc = extract(root, ref["decl"], ref.get("module"), limits=limits)
    found = find_fact(doc, ref) if doc.get("ok") else None
    after = None
    while found is None and doc.get("ok") and (doc.get("page") or {}).get("more"):
        doc = extract(root, ref["decl"], ref.get("module"), limits=limits, after=after,
                      within=ref["at"])
        found = find_fact(doc, ref) if doc.get("ok") else None
        after = (doc.get("page") or {}).get("next")
    return doc, found


def find_fact(doc: dict, ref: dict) -> dict | None:
    """The fact of `doc` a reference names: by its position in the term and its proposition."""
    for f in doc.get("facts") or []:
        if f["at"] == ref.get("at") and (not ref.get("fact_hash")
                                         or f["fact_hash"] == ref["fact_hash"]):
            return f
    return None


def citation(f: dict) -> dict:
    """What a workspace keeps of a cited fact: enough to read it without Lean, and the pins
    that say when it no longer describes the proof."""
    r = f["ref"]
    return {"decl": r["decl"], "module": r.get("module"), "at": r["at"],
            "fact_hash": r["fact_hash"], "proof_hash": r.get("proof_hash"),
            "kind": f["kind"], "name": f.get("name"), "head": f.get("head"),
            "type": _text(f.get("type")), "basis": BASIS,
            "assumptions": [f"{a.get('name')} : {a.get('type')}" for a in f.get("assumptions")
                            or [] if a.get("role") == "hypothesis"],
            "variables": [f"{a.get('name')} : {a.get('type')}" for a in f.get("assumptions")
                          or [] if a.get("role") != "hypothesis"],
            "cases": f.get("cases") or [], "source": f.get("source")}


def currency(root: Path | None, ref: dict, extract_now: bool = False) -> dict:
    """Whether a cited fact still describes the proof: `current` while the declaration's proof
    is unchanged, `stale` when it changed (saying whether a fact with the same proposition is
    still there), `unchecked` when the proof has not been read since the Lean last changed or
    Lean could not read it (its module is not built, a module could not be loaded, the request
    failed)."""
    if root is None:
        return {"state": "unchecked", "changes": [], "reason": "no Lean project to check against"}
    try:
        doc = extract(root, ref["decl"], ref.get("module"), cached_only=not extract_now)
    except ViewError as e:
        return {"state": "unchecked", "changes": [], "reason": str(e)}
    if doc.get("status") == "not extracted":
        return {"state": "unchecked", "changes": [],
                "reason": f"{doc['reason']}; `machinechecked compare --query proof-facts "
                          f"{ref['decl']}` reads it again"}
    if not doc.get("ok") and doc.get("status") in NOT_CHECKED:
        return {"state": "unchecked", "changes": [],
                "reason": not_checked_reason(ref["decl"], doc)}
    if not doc.get("ok"):
        return {"state": "stale", "changes": [{"decl": ref["decl"], "was": ref.get("proof_hash"),
                                               "now": None, "reason": doc.get("status")}]}
    now = doc["proof"]["hash"]
    if now == ref.get("proof_hash"):
        return {"state": "current", "changes": []}
    same = [f for f in doc["facts"] if f["fact_hash"] == ref.get("fact_hash")]
    return {"state": "stale", "changes": [{
        "decl": ref["decl"], "proof_was": ref.get("proof_hash"), "proof_now": now,
        "same_fact_at": [f["at"] for f in same],
        "reason": "the proof changed" + ("; a fact with the same proposition and assumptions is "
                                         "still in it" if same else "")}]}
