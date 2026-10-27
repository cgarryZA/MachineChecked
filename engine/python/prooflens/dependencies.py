"""What a finding of a workspace rests on (`workspace.py`), with the content identity of each
part, so that a later build can tell which findings a change affects.

A finding rests on:

- the claim's printed passage (`passage`);
- the auditor's reading of the requirements it concerns (the one it names or its
  counterexamples concern, with those it sits inside; those a step of its composition
  establishes, with those inside them): each requirement (`reading`, the digest of its form,
  words and governing passages), the passages of the paper that govern them (`context`) and
  their alignments with Lean (`object`: the scoped expression of each target, its declaration's
  digest and those of the definitions its statement uses). A finding on the whole claim rests on
  a requirement only through its own evidence: a change of context reopens it only then;
- the evidence it cites, and that its composition and its counterexamples cite: a declaration
  (`declaration`: its fingerprint and digest, the definitions its statement uses, each with its
  digest, and the expansions of definitions it prints, by their keys), an application of one
  (`application`), a fact inside a proof (`fact`), a certificate (`certificate`), a passage of
  the paper (`paper`) or a source line (`source`, which records no version of its text);
- its composition (`composition`: a digest of its steps, with their substitutions, of its
  identifications and of its obligations) and, for a finding recorded as a checked bridge, the
  bridge (`bridge`: the target's fingerprint and the passage Lean checked it against);
- the counterexamples it cites (`counterexample`).

The evidence kinds of the finding (`kinds`) say which of these it uses: a statement comparison
(a declaration's statement, or a certificate), an object correspondence (alignments, or a
composition's identifications), a composition, a proof route (applications or facts inside a
proof) and a checked bridge.

A submitted finding records its dependencies when it is submitted and keeps them; a draft's are
read from the records it cites whenever it is shown, so a draft follows its records as they are
edited and re-pinned. Against a build each part is checked as its record would be. A finding is
`stale` when a part changed, or, for a submitted finding, when a record it rests on was edited,
re-pinned or removed since; it is `unchecked` when a part cannot be identified or checked (it was
recorded without its version, the build does not show it, Lean has not looked), never `current`.
Nothing here changes a status.
"""

from __future__ import annotations

import hashlib
import json
import re

PASSAGE, READING, CONTEXT, OBJECT = "passage", "reading", "context", "object"
COMPOSITION, BRIDGE, COUNTEREXAMPLE = "composition", "bridge", "counterexample"
# The evidence kinds of a reference, by its key.
EVIDENCE = {"decl": "declaration", "app": "application", "fact": "fact",
            "certificate": "certificate", "paper": "paper", "source": "source"}
KINDS = ("statement comparison", "object correspondence", "composition", "proof route",
         "checked bridge")

# What an item keeps of an evidence reference: what identifies it and its version.
REF_PINS = {
    "decl": ("decl", "module", "build", "fingerprint", "digest", "closure", "closure_complete",
             "expansions"),
    "app": ("callee", "module", "id", "caller", "via", "app_hash"),
    "fact": ("decl", "module", "at", "fact_hash", "proof_hash"),
    "certificate": ("theorem", "target", "certifies", "module", "file", "file_sha256", "type",
                    "target_fingerprint", "result"),
    "paper": ("claim", "quote", "sha256"),
    "source": ("file", "line"),
}
REGION_PINS = ("paper", "file", "start_line", "end_line", "start_column", "end_column",
               "sha256", "line_sha256")
TARGET_PINS = ("decl", "module", "var", "binder", "at", "conclusion", "target", "build",
               "fingerprint", "digest", "closure", "closure_complete")
COMPOSITION_FIELDS = ("statement", "steps", "identifications", "obligations", "coverage")

WORDS = {PASSAGE: "the passage", READING: "the requirement", CONTEXT: "the passage",
         OBJECT: "the alignment", COMPOSITION: "the composition",
         BRIDGE: "the composition's bridge", COUNTEREXAMPLE: "the counterexample",
         **{v: "the evidence" for v in EVIDENCE.values()}}


def _natural(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", str(s))]


# -- the pins a record keeps of a declaration's statement -------------------------------------

def statement_pins(snap, name: str) -> dict:
    """What a record citing the declaration `name` keeps of its statement, from the build
    `snap`: the definitions its statement uses (`closure`, each with its digest, or None when
    the build shows no version of it), `closure_complete: False` when the build's records of
    them are incomplete, and the expansions it prints (`expansions`, `{at, name, key}`). Empty
    when the build shows nothing of what the statement uses: the record then reads as unchecked
    until it is re-pinned against a build that does."""
    if snap is None:
        return {}
    names, complete, _ = snap.closure(name)
    if names is None:
        return {}
    digests = snap.digests()
    out = {"closure": {m: digests.get(m) for m in names}}
    if not complete:
        out["closure_complete"] = False
    exp = (snap.statement_records().get(name) or {}).get("expansions")
    if exp:
        out["expansions"] = exp
    return out


def kept_statement_pins(ref: dict) -> dict:
    """The statement pins `ref` carries (when a record is written without a build), checked."""
    out = {}
    c = ref.get("closure")
    if c is not None:
        if not isinstance(c, dict) or not all(isinstance(k, str) and
                                              (v is None or isinstance(v, str))
                                              for k, v in c.items()):
            from .workspace import WorkspaceError
            raise WorkspaceError("`closure` maps each definition to its digest")
        out["closure"] = dict(c)
    if ref.get("closure_complete") is False:
        out["closure_complete"] = False
    if isinstance(ref.get("expansions"), list):
        out["expansions"] = [{k: x.get(k) for k in ("at", "name", "key")}
                             for x in ref["expansions"] if isinstance(x, dict)]
    return out


def closure_currency(pins: dict, snap, owner: str) -> dict:
    """Whether the definitions the statement of `owner` uses are those `pins` recorded: `stale`
    naming each that changed, `unchecked` when they were not recorded or the build shows no
    version of one."""
    closure = pins.get("closure")
    if not isinstance(closure, dict):
        return {"state": "unchecked", "changes": [],
                "reason": f"the definitions the statement of {owner} uses were not recorded with "
                          "it: re-pin it to record them"}
    digests = snap.digests() if snap is not None else {}
    changes, unknown = [], []
    for m, was in sorted(closure.items()):
        now = digests.get(m)
        if not was or now is None:
            unknown.append(m)
        elif now != was:
            changes.append({"decl": m, "was": was, "now": now, "used_by": owner,
                            "reason": f"{m}, which the statement of {owner} uses, changed"})
    if changes:
        return {"state": "stale", "changes": changes}
    if unknown:
        return {"state": "unchecked", "changes": [],
                "reason": f"no version of {', '.join(unknown[:3])}"
                          + (f" and {len(unknown) - 3} more" if len(unknown) > 3 else "")
                          + f", which the statement of {owner} uses, is known here"}
    if pins.get("closure_complete") is False:
        return {"state": "unchecked", "changes": [],
                "reason": f"the build's records of what the statement of {owner} uses were "
                          "incomplete when it was recorded"}
    return {"state": "current", "changes": []}


# -- the currency of an evidence reference ----------------------------------------------------

def decl_currency(ref: dict, snap, root=None) -> dict:
    """A declaration cited as evidence: `stale` when its digest (its fingerprint with those of
    the constants Lean generated for it) or the digest of a definition its statement uses
    changed, `unchecked` when the build shows no version of it or of one of them, or none was
    recorded with it, with the reason and what would let a build check it (`absent_reason`,
    which looks at the Lean project at `root` when it is given)."""
    digests = snap.digests() if snap is not None else {}
    was, now = ref.get("digest") or ref.get("fingerprint"), digests.get(ref["decl"])
    if now is None:
        return {"state": "unchecked", "changes": [], "reason": absent_reason(ref, snap, root)}
    if not was:
        return {"state": "unchecked", "changes": [], "reason": unrecorded_reason(ref)}
    if now != was:
        return {"state": "stale", "changes": [{"decl": ref["decl"], "was": was, "now": now}]}
    return closure_currency(ref, snap, ref["decl"])


def unrecorded_reason(ref: dict) -> str:
    """Why a reference to a declaration the build now shows records no version of it: it was
    cited while the build could not read it, or without a build."""
    name, module, build = ref["decl"], ref.get("module"), ref.get("build")
    where = f"its module {module}" if module else "its module"
    when = {"unbuilt": f"while {where} was not built",
            "not loaded": f"while {where} could not be loaded",
            "external": "as a declaration outside the project"}.get(build, "without a build that "
                                                                   "showed it")
    return (f"{name} was cited {when}, so no version of it was recorded: re-pin the evidence "
            "(`\"repin\": true`) to record the version this build shows")


def absent_reason(ref: dict, snap, root=None) -> str:
    """Why the build `snap` shows no version of the declaration `ref` names, with the step that
    would let a build show one: no build; a build that ran no Lean (a full assessment built
    without Lean, or a view with no Lean index); a declaration outside the project; a module that
    is not built or could not be loaded; a declaration the project no longer declares; and, in
    a full assessment, one its inventory's clauses do not use (the build records only those),
    naming its module when the configuration does not list it in `modules`. With the Lean
    project at `root` the modules are read from it; without it, only from the build."""
    from pathlib import Path
    name, module = ref["decl"], ref.get("module")
    if snap is None:
        return "no build to check it against: run `machinechecked view` or `build`"
    full = snap.index.get("mode") != "simple"
    index = snap.lean_index() or []
    if full and not snap.index.get("lean"):
        return (f"this build ran no Lean, so it records no version of {name}: build again with "
                "Lean")
    if not full and not index:
        return (f"this build has no Lean index, so it records no version of {name}: run `lake "
                "build`, then `machinechecked view`")
    if ref.get("build") == "external":
        return (f"{name} is not a declaration of the project, and a build records versions only "
                "of the project's declarations")
    root = Path(root) if root else None
    declares = []
    if root is not None:
        from .simple import declaring_modules
        from .targets import _project_modules
        # The project's modules, read once for this build however many references ask.
        cache = snap.__dict__.setdefault("_project_modules", {})
        if str(root) not in cache:
            cache[str(root)] = _project_modules(snap, root)
        built, unbuilt, failed = cache[str(root)]
        for m in declaring_modules(root, unbuilt, name):
            return f"its module {m} is not built: run `lake build {m}`, then build again"
        for m in declaring_modules(root, list(failed), name):
            why = (str(failed.get(m) or "").strip().splitlines() or [""])[0][:200]
            return (f"its module {m} could not be loaded" + (f" ({why})" if why else "")
                    + f": fix it, run `lake build {m}`, then build again")
        declares = declaring_modules(root, built, name)
    indexed = sorted({d.get("module") for d in index if d.get("name") == name} - {None})
    if not declares and not indexed and not (snap.store_records(name) if full else []):
        if root is None:
            return f"this build shows no version of {name}"
        from .targets import _near
        near = _near(index, name)
        return (f"the project does not declare {name} in this build"
                + (f" (did you mean {', '.join(near)}?)" if near else "")
                + ": if it was renamed, cite the new name")
    if full:
        out = (f"this build records no version of {name}: a full assessment records the "
               "declarations its inventory's clauses name and those their statements use, and "
               f"{name} is not among them")
        listed = _listed_modules(snap)
        unlisted = [m for m in declares or ([module] if module else [])
                    if listed is not None and m not in listed]
        if unlisted:
            out += (f"; its module {unlisted[0]} is not listed in `modules` of the "
                    "configuration either")
        return out
    if indexed:
        return (f"{name} is in this build's index, but the build records a version only of the "
                "declarations its claims link and those their statements use")
    return (f"this build's Lean index does not hold {name}, which {declares[0]} declares: run "
            "`lake build`, then `machinechecked view`")


def _listed_modules(snap) -> list[str] | None:
    """The modules the full assessment's configuration lists (`modules`), when the
    configuration is the one beside the working directory of the build `snap`; None when it is
    not found there."""
    from . import config as cfgmod
    work = snap.data.parent.parent
    for name in cfgmod.CONFIG_NAMES:
        p = work.parent / name
        if p.is_file():
            try:
                cfg = cfgmod.load(p)
            except (cfgmod.ConfigError, OSError, ValueError):
                return None
            return list(cfg.modules) if cfg.out_dir.resolve() == work.resolve() else None
    return None


def unprinted(ch: dict | None, cid: str | None) -> str | None:
    """Why the build's pin of a claim's passage is not the text the paper now prints, or None.
    A build of the full assessment pins a passage by the inventory's digest of it and checks
    that digest against the manuscript (`source_matches`): when the text changed and the
    inventory was not pinned again, the pin stays the same and the check fails, so a record that
    read the pinned text is not current although the pin did not change."""
    if ch is not None and ch.get("source_matches") is False:
        return (f"the paper now prints other text than the pin of {cid}: its passage changed, "
                "and the inventory has not pinned it again")
    return None


def paper_currency(p: dict, snap) -> dict:
    """A passage of the paper cited as evidence: `stale` once the claim's printed passage is not
    the one it was recorded against (its pin changed, or the paper no longer prints the pinned
    text: `unprinted`), `unchecked` when it was recorded without it."""
    if snap is None or not p.get("sha256"):
        return {"state": "unchecked", "changes": [],
                "reason": "no version of the passage was recorded with it"
                if snap is not None else "no build to check the passage against"}
    ch = snap.chunk(p.get("claim") or "")
    now = (ch or {}).get("source_sha256")
    if ch is None or now != p["sha256"]:
        return {"state": "stale", "changes": [{"passage": p.get("claim"), "was": p["sha256"],
                                               "now": now if ch is not None else None}]}
    why = unprinted(ch, p.get("claim"))
    if why:
        return {"state": "stale", "changes": [{"passage": p.get("claim"), "was": p["sha256"],
                                               "now": now, "reason": why}]}
    return {"state": "current", "changes": []}


def evidence_currency(ref: dict, snap, root, check_facts: bool = False) -> dict:
    """Whether an evidence reference is still what the build and the Lean project show."""
    from pathlib import Path
    root = Path(root) if root else None
    if "certificate" in ref:
        from .estimates import certificate_currency
        return certificate_currency(root, ref["certificate"], check_facts)
    if "fact" in ref:
        from .proof_facts import currency as fact_currency
        return fact_currency(root, ref["fact"], check_facts)
    if "app" in ref:
        from .uses import app_currency
        return app_currency(root, ref["app"], check_facts)
    if "decl" in ref:
        return decl_currency(ref, snap, root)
    if "paper" in ref:
        return paper_currency(ref["paper"], snap)
    return {"state": "unchecked", "changes": [],
            "reason": "a source line records no version of its text"}


# -- what a finding rests on ------------------------------------------------------------------

def ref_pins(ref: dict) -> dict:
    """What identifies an evidence reference and its version."""
    ref = ref or {}
    if "decl" in ref:
        return {k: ref[k] for k in REF_PINS["decl"] if ref.get(k) is not None}
    for k in ("app", "fact", "certificate", "paper", "source"):
        if k in ref:
            v = ref[k] or {}
            return {k: {f: v[f] for f in REF_PINS[k] if v.get(f) is not None}}
    return {}


def _kind(ref: dict) -> str:
    return next((v for k, v in EVIDENCE.items() if k in (ref or {})), "evidence")


def composition_digest(c: dict) -> str:
    """A digest of what a composition argues: its combined statement, its steps (what each
    establishes, from what, with which substitutions and inferences), its identifications, its
    obligations, its coverage and its bridge's pins."""
    body = {k: c.get(k) for k in COMPOSITION_FIELDS}
    b = c.get("bridge")
    if isinstance(b, dict):
        body["bridge"] = {k: b.get(k) for k in ("theorem", "target", "target_fingerprint",
                                                "source_sha256")}
    return "composition-v1:" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _requirements(f: dict, records: dict, named: set[str], established: set[str]) \
        -> tuple[list[dict], list[dict]]:
    """The requirements a finding's reading rests on: those it names (itself, or through its
    counterexamples), each with the requirements it sits inside (its scope), and those a step of
    its composition establishes, with those inside them too (a step on a requirement establishes
    them); and the names the workspace does not have. A finding on the whole claim names none:
    it rests on a requirement only through its own evidence."""
    reqs = {r["local_id"]: r for r in records.values()
            if r.get("kind") == "requirement" and r.get("claim") == f["claim"]}
    used, missing = set(), []
    inside: dict[str, list[str]] = {}
    for r in reqs.values():
        inside.setdefault(r.get("parent"), []).append(r["local_id"])
    for lid in sorted(named | established, key=_natural):
        if lid not in reqs:
            missing.append({"dependency": READING, "requirement": lid,
                            "why": f"{f['claim']} has no requirement {lid} in this workspace"})
            continue
        at, seen = lid, set()
        while at in reqs and at not in seen:
            seen.add(at)
            used.add(at)
            at = reqs[at].get("parent")
        if lid in established:
            todo = list(inside.get(lid, []))
            while todo:
                x = todo.pop()
                if x not in used:
                    used.add(x)
                    todo += inside.get(x, [])
    return [reqs[l] for l in sorted(used, key=_natural)], missing


def collect(f: dict, records: dict) -> dict:
    """The dependencies of the finding `f` among the workspace's `records`: `kinds` (the evidence
    kinds it uses), `items` (each part it rests on with its content identity: `dependency`, the
    `record` it comes from when it is one, `via` the composition or counterexample it is cited
    through) and `unknown` (parts that cannot be identified, each with `why`)."""
    from . import requirements as rq
    items, unknown = [], []
    sha = (f.get("pins") or {}).get("statement_sha256")
    if sha:
        items.append({"dependency": PASSAGE, "claim": f["claim"], "sha256": sha})
    else:
        unknown.append({"dependency": PASSAGE, "claim": f["claim"],
                        "why": "it was recorded without a build, so the version of the passage "
                               "it was read against is not known"})
    comp = records.get(f.get("composition") or "") if f.get("composition") else None
    if f.get("composition") and (comp or {}).get("kind") != COMPOSITION:
        unknown.append({"dependency": COMPOSITION, "record": f["composition"],
                        "why": f"its composition {f['composition']} is not in this workspace"})
        comp = None
    named, established, cxs = {f["requirement"]} if f.get("requirement") else set(), set(), []
    for s in (comp or {}).get("steps") or []:
        established |= set(s.get("requirements") or [])
    for p in f.get("counterexamples") or []:
        cx = records.get(p.get("id"))
        cxs.append((p, cx if (cx or {}).get("kind") == COUNTEREXAMPLE else None))
        if cxs[-1][1] is not None:
            named.add(cx.get("requirement"))
            named |= set(cx.get("reading") or [])
    named.discard(None)
    reqs, missing = _requirements(f, records, named, established)
    unknown += missing
    lids = {r["local_id"] for r in reqs}
    claim_recs = [r for r in records.values() if r.get("claim") == f["claim"]]
    for r in reqs:
        frags = [x for x in claim_recs if x.get("kind") == "fragment"
                 and x.get("requirement") == r["local_id"]]
        items.append({"dependency": READING, "record": r["id"], "requirement": r["local_id"],
                      "sha256": rq.reading_digest(r, frags)})
        for x in sorted(frags, key=lambda x: (x.get("created_at") or "", x["id"])):
            if x.get("state") != "accepted" or x.get("role") == "later use":
                continue
            it = {"dependency": CONTEXT, "record": x["id"], "requirement": r["local_id"],
                  "role": x.get("role"), "origin": x.get("origin")}
            if x.get("region"):
                it["region"] = {k: x["region"][k] for k in REGION_PINS
                                if x["region"].get(k) is not None}
            else:
                it["passage"] = {k: (x.get("passage") or {}).get(k) for k in ("claim", "sha256")}
            items.append(it)
    for a in sorted((x for x in claim_recs if x.get("kind") == "alignment"),
                    key=lambda x: (x.get("created_at") or "", x["id"])):
        if set(a.get("requirements") or []) & lids:
            items.append({"dependency": OBJECT, "record": a["id"],
                          "requirements": list(a.get("requirements") or []),
                          "relation": a.get("relation"),
                          "lean": [{k: t[k] for k in TARGET_PINS if t.get(k) is not None}
                                   for t in a.get("lean") or []]})
    cited: dict[str, list[str]] = {}
    for e in f.get("evidence") or []:
        cited.setdefault(e, [])
    if comp is not None:
        for e in comp.get("evidence") or []:
            cited.setdefault(e, []).append(comp["id"])
    for p, cx in cxs:
        for e in (cx or {}).get("evidence") or []:
            cited.setdefault(e, []).append(cx["id"])
    for e, via in cited.items():
        r = records.get(e)
        if not r or r.get("kind") != "evidence":
            unknown.append({"dependency": "evidence", "record": e,
                            "why": f"the evidence {e} is not in this workspace"})
            continue
        it = {"dependency": _kind(r.get("ref")), "record": e, "role": r.get("role"),
              "ref": ref_pins(r.get("ref"))}
        if via:
            it["via"] = via
        items.append(it)
    if comp is not None:
        items.append({"dependency": COMPOSITION, "record": comp["id"],
                      "sha256": composition_digest(comp)})
    if f.get("basis") == "checked_bridge":
        b = (comp or {}).get("bridge")
        if comp is not None and isinstance(b, dict):
            items.append({"dependency": BRIDGE, "record": comp["id"],
                          **{k: b.get(k) for k in ("theorem", "target", "target_fingerprint",
                                                   "source_sha256")}})
        elif comp is None and isinstance(f.get("bridge"), dict):
            items.append({"dependency": BRIDGE, **{k: f["bridge"].get(k)
                                                   for k in ("theorem", "target")}})
            unknown.append({"dependency": BRIDGE, "why": "a finding's own bridge records no "
                            "version of its target or of the passage the auditor read"})
        else:
            unknown.append({"dependency": BRIDGE, "why": "no bridge is recorded"
                            if comp is None else f"its composition {comp['id']} has no bridge"})
    for p, cx in cxs:
        if cx is None:
            unknown.append({"dependency": COUNTEREXAMPLE, "record": p.get("id"),
                            "why": f"the counterexample {p.get('id')} is not in this workspace"})
        items.append({"dependency": COUNTEREXAMPLE, "record": p.get("id"),
                      "sha256": p.get("sha256")})
    return {"kinds": kinds(items, comp), "items": items, "unknown": unknown}


def kinds(items: list[dict], comp: dict | None = None) -> list[str]:
    """The evidence kinds a finding with these dependencies uses."""
    deps = {it["dependency"] for it in items}
    out = []
    if deps & {"declaration", "certificate"}:
        out.append("statement comparison")
    if OBJECT in deps or (comp or {}).get("identifications"):
        out.append("object correspondence")
    if COMPOSITION in deps:
        out.append("composition")
    if deps & {"application", "fact"}:
        out.append("proof route")
    if BRIDGE in deps:
        out.append("checked bridge")
    return out


def recorded(f: dict, records: dict) -> dict:
    """The dependencies a finding records when it is submitted: `collect`'s, with the time."""
    from .workspace import now
    return {**collect(f, records), "at": now()}


def of(f: dict, records: dict) -> dict:
    """The dependencies a finding rests on: those a submitted finding recorded, else (a draft,
    or a finding submitted before they were recorded) those its records give now."""
    if f.get("state") == "submitted" and isinstance(f.get("dependencies"), dict):
        return f["dependencies"]
    return collect(f, records)


# -- checking them ---------------------------------------------------------------------------

def _strip(it: dict) -> dict:
    return {k: v for k, v in it.items() if k != "via"}


def _key(it: dict) -> tuple:
    return it["dependency"], it.get("record"), it.get("claim")


def drift(stored: dict, now: dict) -> list[dict]:
    """The records a submitted finding rests on that are not what it was submitted with: edited,
    re-pinned, or no longer standing as its dependency (a passage removed, a record deleted)."""
    current = {_key(it): _strip(it) for it in now.get("items") or []}
    out = []
    for it in stored.get("items") or []:
        rid = it.get("record")
        if not rid or it["dependency"] == COUNTEREXAMPLE:
            # A counterexample is pinned by the finding itself; it is checked below.
            continue
        word = WORDS.get(it["dependency"], "the record")
        k = _key(it)
        if k not in current:
            out.append({"record": rid, "dependency": it["dependency"],
                        "reason": f"{word} {rid}, which it was submitted with, no longer stands "
                                  "as it did (removed or no longer attached)"})
        elif current[k] != _strip(it):
            out.append({"record": rid, "dependency": it["dependency"],
                        "reason": f"{word} {rid} was edited or re-pinned after the finding was "
                                  "submitted"})
    return out


def _as_unknown(it: dict, cur: dict) -> dict:
    out = {"dependency": it["dependency"]}
    for k in ("record", "claim"):
        if it.get(k):
            out[k] = it[k]
    out["why"] = cur.get("reason") or "this build cannot check it"
    return out


def check(f: dict, records: dict, snap, root=None, cur: dict | None = None,
          check_facts: bool = False, skip=()) -> dict:
    """The currency of the finding `f` against the build `snap` (and the Lean project at
    `root`), through what it rests on (`of`): `stale` with the `changes` (each part that
    changed; for a submitted finding, each record it rests on that was edited or re-pinned
    since), else `unchecked` with what is not known (`unknown`, each with `why`), else
    `current`. `cur` holds the currency of the workspace's records (`workspace.currency`), for
    the counterexamples it cites. The dependencies of the kinds in `skip` are left out (the
    paper's, when a version map judges them: `reopen.py`); a bridge is then checked against the
    Lean alone when `skip` holds the passage."""
    from . import composition as cp
    from . import requirements as rq
    from .estimates import counterexample_pin
    cur = cur or {}
    deps = of(f, records)
    changes = []
    unknown = [u for u in deps.get("unknown") or [] if u.get("dependency") not in skip]
    if f.get("state") == "submitted":
        if isinstance(f.get("dependencies"), dict):
            changes += drift(f["dependencies"], collect(f, records))
        else:
            unknown.append({"dependency": "dependencies",
                            "why": "it was submitted before findings recorded their "
                                   "dependencies, so records edited or re-pinned since cannot "
                                   "be told apart: supersede it to record them"})
    for it in deps.get("items") or []:
        dep = it["dependency"]
        if dep in (READING, COMPOSITION) or dep in skip:
            continue  # what the auditor wrote: an edit is a drift, above
        if dep == PASSAGE:
            if snap is None:
                unknown.append(_as_unknown(it, {"reason": "no build to check the passage "
                                                          "against"}))
                continue
            ch = snap.chunk(it["claim"])
            now = (ch or {}).get("source_sha256")
            if ch is None or now != it.get("sha256"):
                changes.append({"claim": it["claim"], "was": it.get("sha256"),
                                "now": now if ch is not None else None})
            elif unprinted(ch, it["claim"]):
                changes.append({"claim": it["claim"], "was": it.get("sha256"), "now": now,
                                "reason": unprinted(ch, it["claim"])})
            continue
        if dep == CONTEXT:
            res = rq.fragment_currency(it, snap)
        elif dep == OBJECT:
            res = rq.alignment_currency(it, snap, root)
        elif dep == BRIDGE:
            if not it.get("target_fingerprint") and not it.get("source_sha256"):
                continue  # a finding's own bridge: unknown when recorded
            b = cp.bridge_currency(it, f["claim"], None if PASSAGE in skip else snap, root,
                                   check_facts)
            res = {"state": {"checked": "current"}.get(b.get("state"), b.get("state")),
                   "changes": [{"bridge": it.get("theorem"), "target": it.get("target"),
                                "reason": f"the bridge {it.get('theorem')} for "
                                          f"{it.get('target')} is out of date: "
                                          + "; ".join(b.get("reasons") or [])}]
                   if b.get("state") == "stale" else [],
                   "reason": "; ".join(b.get("reasons") or []) or None}
        elif dep == COUNTEREXAMPLE:
            cx = records.get(it.get("record") or "")
            if cx is None:
                continue  # unknown when collected
            if counterexample_pin(cx) != it.get("sha256"):
                res = {"state": "stale", "changes": [{
                    "counterexample": it["record"],
                    "reason": "the counterexample changed since the finding cited it"}]}
            else:
                res = cur.get(it["record"]) or {"state": "unchecked", "changes": []}
        elif dep in EVIDENCE.values():
            res = evidence_currency(it.get("ref") or {}, snap, root, check_facts)
        else:
            continue
        changes += res.get("changes") or []
        if res.get("state") == "unchecked":
            unknown.append(_as_unknown(it, res))
    seen, kept = set(), []
    for ch in changes:
        k = json.dumps(ch, sort_keys=True, ensure_ascii=False)
        if k not in seen:
            seen.add(k)
            kept.append(ch)
    out = {"state": "stale" if kept else "unchecked" if unknown else "current", "changes": kept}
    if unknown:
        out["unknown"] = unknown
    return out


# -- text -------------------------------------------------------------------------------------

def item_text(it: dict) -> str:
    """One dependency, in the reader's words."""
    dep = it["dependency"]
    if dep == PASSAGE:
        return f"the passage of {it['claim']}"
    if dep == READING:
        return f"requirement {it.get('requirement')}"
    if dep == CONTEXT:
        if it.get("region"):
            r = it["region"]
            end = r.get("end_line", r.get("start_line"))
            where = f"{r.get('file')}:{r.get('start_line')}" + (
                f"-{end}" if end != r.get("start_line") else "")
        else:
            where = f"the passage of {(it.get('passage') or {}).get('claim')}"
        return f"{where} ({it.get('role')} of {it.get('requirement')})"
    if dep == OBJECT:
        from .requirements import target_text
        return "; ".join(target_text(t) for t in it.get("lean") or []) + \
            f" ({it.get('relation')})"
    if dep == COMPOSITION:
        return f"composition {it.get('record')}"
    if dep == BRIDGE:
        return f"bridge {it.get('theorem')} for {it.get('target')}"
    if dep == COUNTEREXAMPLE:
        return f"counterexample {it.get('record')}"
    from .workspace import ref_text
    text = ref_text(it.get("ref") or {})
    n = len((it.get("ref") or {}).get("closure") or {})
    return text + (f" (and {n} definition{'s' if n != 1 else ''} its statement uses)"
                   if dep == "declaration" and n else "")


def change_text(ch: dict) -> str:
    """One change a finding's currency names, in words."""
    if ch.get("reason"):
        return ch["reason"]
    if ch.get("decl"):
        return f"{ch['decl']} changed" if ch.get("now") else f"{ch['decl']} is not in the build"
    if ch.get("region"):
        return f"the paper's text at {ch['region']} changed" if ch.get("now") else \
            f"the paper has no text at {ch['region']}"
    what = ch.get("passage") or ch.get("claim")
    if what:
        return f"the passage of {what} changed" if ch.get("now") else \
            f"{what} is not in the build"
    return "changed since it was recorded"


def lines(deps: dict, currency: dict | None = None, pad: str = "           ") -> list[str]:
    """A finding's dependencies and what of them changed or is not known, for the terminal."""
    items = deps.get("items") or []
    out = [pad + "rests on: " + ("; ".join(item_text(it) for it in items) or "nothing recorded")
           + (f"  [{', '.join(deps['kinds'])}]" if deps.get("kinds") else "")]
    for ch in (currency or {}).get("changes") or []:
        out.append(pad + "changed: " + change_text(ch))
    for u in (currency or {}).get("unknown") or []:
        out.append(pad + "not known to be current: " + u.get("why", ""))
    return out
