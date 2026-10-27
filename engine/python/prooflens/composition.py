"""A claim covered by several Lean results together: the auditor's composition (a workspace's
`composition` record, `workspace.py`), and the optional Lean bridge that states it as one result.

A composition is an ordered argument. Each step says what it establishes and rests on evidence
records of the workspace (a declaration, an application of a declaration as `compare --query
uses` gives it, or a fact inside a proof) or on earlier steps; it records the substitutions it
makes (the actual arguments given to a result's variables) and any inference of the auditor's
own. Identifications say which objects of different steps are the same, and how that is known.
Obligations are what the argument still needs (compatible witness choices, a local-to-global
step, an equality transport, a constant's allowed dependence, a genericity condition), each open
or discharged by named steps or evidence. Citing a declaration discharges nothing by itself.

A composition records a coverage (the links file's words). Its basis is computed, never written:
`reviewed_composition`, the auditor's argument, which Lean has not checked; or `checked_bridge`
while a bridge is checked. A bridge is a theorem whose type is exactly a target proposition,
stated as a definition, checked through the probe's `accept` request (the same check as a
links-file bridge, `simple.bridge_evidence`), with its answer kept in the facts store. A bridge is
attached only after Lean checks it, pinned to the target as Lean has it (its definition and the
definitions it uses) and to the claim's printed passage, and it stops counting once either
changes. A composition, its bridge and its findings change no status.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

STEP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
OBLIGATION_KINDS = ("compatible witnesses", "local to global", "equality transport",
                    "constant dependence", "genericity", "side condition", "other")
OBLIGATION_STATES = ("open", "discharged")
RELATIONS = ("same object", "equal", "restriction", "coercion", "other")
HOW = ("retained witness", "evidence", "definition")
# The evidence that can support a step: a Lean result, its application, or a fact in a proof.
SUPPORT = ("decl", "app", "fact")
KIND = "bridge"  # the facts store's kind for bridge checks

OBLIGATION_WORDS = {"compatible witnesses": "compatible witness choices",
                    "local to global": "a local-to-global step",
                    "equality transport": "an equality transport",
                    "constant dependence": "a constant's allowed dependence",
                    "genericity": "a genericity condition", "side condition": "a side condition",
                    "other": "an obligation"}
BASIS_REVIEWED = "reviewed_composition"
BASIS_BRIDGE = "checked_bridge"


def _err(msg: str):
    from .workspace import WorkspaceError
    return WorkspaceError(msg)


def _text(v, what, required=False):
    from .workspace import _text as t
    return t(v, what, required)


def _choice(v, allowed, what, optional=True):
    from .workspace import _choice as c
    return c(v, allowed, what, optional)


def _ids(v, what: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise _err(f"{what} is a list of ids")
    return list(dict.fromkeys(x.strip() for x in v))


def _fields(d, allowed: tuple, what: str) -> dict:
    if not isinstance(d, dict):
        raise _err(f"{what} is an object")
    extra = set(d) - set(allowed)
    if extra:
        raise _err(f"{what} has no field {', '.join(sorted(extra))}")
    return d


def _support(ws: dict, claim: str, eid: str, what: str) -> None:
    r = ws["records"].get(eid)
    if not r or r.get("kind") != "evidence":
        raise _err(f"{what}: {eid} is not an evidence record of this workspace")
    if r["claim"] != claim:
        raise _err(f"{what}: {eid} is evidence for {r['claim']}, not {claim}")
    if r.get("role") == "rejected":
        raise _err(f"{what}: {eid} is a rejected candidate")
    if not any(k in (r.get("ref") or {}) for k in SUPPORT):
        raise _err(f"{what}: {eid} cites a passage or a source line; a step rests on a "
                   "declaration, an application of one, or a fact inside a proof")


def printed_requirements(ws: dict, claim: str) -> dict[str, dict]:
    """The claim's requirements as printed (corrections stand beside them), by local id."""
    return {r["local_id"]: r for r in ws["records"].values()
            if r.get("kind") == "requirement" and r.get("claim") == claim
            and r.get("origin") != "correction"}


def gaps(rec: dict, ws: dict) -> dict:
    """What keeps a composition from establishing every clause: the printed requirements no step
    establishes (a step on a requirement establishes those inside it), the open obligations, and
    whether the claim has requirements recorded at all."""
    reqs = {r["local_id"]: r for r in ws["records"].values()
            if r.get("kind") == "requirement" and r.get("claim") == rec["claim"]}
    named = {lid for s in rec.get("steps") or [] for lid in s.get("requirements") or []}

    def covered(lid):
        seen = set()
        while lid and lid not in seen:
            if lid in named:
                return True
            seen.add(lid)
            lid = (reqs.get(lid) or {}).get("parent")
        return False

    printed = printed_requirements(ws, rec["claim"])
    return {"requirements": len(printed),
            "uncovered": sorted(l for l in printed if not covered(l)),
            "open": [o["id"] for o in rec.get("obligations") or [] if o.get("state") == "open"]}


def full_refusal(g: dict) -> str | None:
    """Why a composition with these gaps cannot record full coverage, or None."""
    why = []
    if not g["requirements"]:
        why.append("the claim has no requirements recorded in this workspace, so no clause can "
                   "be shown covered (record them first)")
    if g["uncovered"]:
        why.append("no step establishes " + ", ".join(g["uncovered"]))
    if g["open"]:
        why.append("obligation(s) " + ", ".join(g["open"]) + " are open")
    return "full coverage needs every clause established: " + "; ".join(why) if why else None


# -- validation ------------------------------------------------------------------------------

def content(out: dict, rec: dict, ws: dict, snap, root, cur: dict | None, repin: bool) -> dict:
    """The fields of a composition record, checked; `out` holds the common ones."""
    from . import requirements as rq
    from . import simple
    claim = out["claim"]
    out.pop("evidence", None)
    if rec.get("statement") not in (None, ""):
        out["statement"] = _text(rec["statement"], "the combined statement")
    raw = rec.get("steps")
    if not isinstance(raw, list) or not raw:
        raise _err("a composition lists its steps (`steps`), in order")
    steps, seen = [], []
    for i, s in enumerate(raw):
        _fields(s, ("id", "establishes", "requirements", "uses", "after", "substitutions",
                    "inference", "note"), f"step {i + 1}")
        sid = _text(s.get("id") or f"s{i + 1}", "a step's id", True).strip()
        if not STEP_ID.fullmatch(sid):
            raise _err(f"{sid!r} is not a step id (letters, digits, `.`, `_`, `-`; up to 40)")
        if sid in seen:
            raise _err(f"two steps are called {sid}")
        what = f"step {sid}"
        step = {"id": sid, "establishes": _text(s.get("establishes"),
                                                f"what {what} establishes (`establishes`)", True)}
        lids = _ids(s.get("requirements"), f"{what}'s `requirements`")
        if lids:
            step["requirements"] = [rq.known_requirement(ws, claim, l) for l in lids]
        uses = _ids(s.get("uses"), f"{what}'s `uses`")
        for e in uses:
            _support(ws, claim, e, what)
        after = _ids(s.get("after"), f"{what}'s `after`")
        for a in after:
            if a not in seen:
                raise _err(f"{what} rests on {a}, which is not an earlier step")
        if not uses and not after:
            raise _err(f"{what} rests on nothing: name the evidence it uses (`uses`: a "
                       "declaration, an application or a fact inside a proof) or the earlier "
                       "steps it follows from (`after`)")
        if uses:
            step["uses"] = uses
        if after:
            step["after"] = after
        subs = s.get("substitutions") or []
        if not isinstance(subs, list):
            raise _err(f"{what}'s `substitutions` is a list of {{variable, value}}")
        kept = []
        for sub in subs:
            _fields(sub, ("variable", "value", "in"), f"a substitution of {what}")
            x = {"variable": _text(sub.get("variable"), "a substituted variable", True).strip(),
                 "value": _text(sub.get("value"), "a substituted value", True).strip()}
            if sub.get("in") not in (None, ""):
                if sub["in"] not in uses:
                    raise _err(f"a substitution of {what} is in {sub['in']}, which the step "
                               "does not use")
                x["in"] = sub["in"]
            kept.append(x)
        if kept:
            step["substitutions"] = kept
        for k, w in (("inference", "the auditor's inference"), ("note", "the note")):
            if s.get(k) not in (None, ""):
                step[k] = _text(s[k], f"{what}'s {w}")
        steps.append(step)
        seen.append(sid)
    out["steps"] = steps
    order = {s["id"]: i for i, s in enumerate(steps)}
    after_of = {s["id"]: set(s.get("after") or []) for s in steps}

    def follows(right, left):
        stack, done = list(after_of[right]), set()
        while stack:
            x = stack.pop()
            if x == left:
                return True
            if x not in done:
                done.add(x)
                stack.extend(after_of.get(x, ()))
        return False

    idents = []
    for k, it in enumerate(rec.get("identifications") or []):
        what = f"identification {k + 1}"
        _fields(it, ("left", "right", "relation", "how", "evidence", "note"), what)
        ends = []
        for side in ("left", "right"):
            e = _fields(it.get(side), ("step", "object"), f"the {side} of {what}")
            if e.get("step") not in order:
                raise _err(f"the {side} of {what} names no step of this composition")
            ends.append({"step": e["step"], "object": _text(e.get("object"),
                                                            f"the {side} object of {what}",
                                                            True).strip()})
        x = {"left": ends[0], "right": ends[1],
             "relation": _choice(it.get("relation") or "same object", RELATIONS,
                                 "the relation", False),
             "how": _choice(it.get("how"), HOW, f"how {what} is known (`how`)", False)}
        ev = _ids(it.get("evidence"), f"{what}'s `evidence`")
        for e in ev:
            _support(ws, claim, e, what)
        if x["how"] == "evidence" and not ev:
            raise _err(f"{what} is known by evidence: name it (`evidence`)")
        if x["how"] == "retained witness" and not follows(ends[1]["step"], ends[0]["step"]):
            raise _err(f"{what}: a retained witness is the object an earlier step produced, "
                       f"used by a later step that follows from it; {ends[1]['step']} does not "
                       f"follow from {ends[0]['step']} (`after`)")
        if ev:
            x["evidence"] = ev
        if it.get("note") not in (None, ""):
            x["note"] = _text(it["note"], f"{what}'s note")
        idents.append(x)
    if idents:
        out["identifications"] = idents
    obls, oids = [], set()
    for k, o in enumerate(rec.get("obligations") or []):
        _fields(o, ("id", "kind", "text", "state", "by", "note"), f"obligation {k + 1}")
        oid = _text(o.get("id") or f"o{k + 1}", "an obligation's id", True).strip()
        if not STEP_ID.fullmatch(oid) or oid in oids:
            raise _err(f"{oid!r} is not a new obligation id")
        oids.add(oid)
        x = {"id": oid, "kind": _choice(o.get("kind") or "other", OBLIGATION_KINDS, "the kind",
                                        False),
             "text": _text(o.get("text"), f"obligation {oid} (`text`)", True),
             "state": _choice(o.get("state") or "open", OBLIGATION_STATES, "the state", False)}
        by = o.get("by")
        if by is not None:
            _fields(by, ("steps", "evidence"), f"what discharges {oid}")
            st = _ids(by.get("steps"), f"{oid}'s `by.steps`")
            for s in st:
                if s not in order:
                    raise _err(f"{oid} is discharged by {s}, which is not a step")
            ev = _ids(by.get("evidence"), f"{oid}'s `by.evidence`")
            for e in ev:
                _support(ws, claim, e, f"obligation {oid}")
            by = {**({"steps": st} if st else {}), **({"evidence": ev} if ev else {})}
        if x["state"] == "discharged" and not by:
            raise _err(f"obligation {oid} is discharged: name the steps or evidence that "
                       "discharge it (`by`)")
        if by:
            x["by"] = by
        if o.get("note") not in (None, ""):
            x["note"] = _text(o["note"], f"{oid}'s note")
        obls.append(x)
    if obls:
        out["obligations"] = obls
    out["evidence"] = list(dict.fromkeys(
        [e for s in steps for e in s.get("uses") or []]
        + [e for x in idents for e in x.get("evidence") or []]
        + [e for x in obls for e in (x.get("by") or {}).get("evidence") or []]))
    if rec.get("basis") is not None:
        raise _err("a composition's basis is not written: it is the auditor's composition, or a "
                   "checked bridge once Lean checks one (`bridge`)")
    cov = _choice(rec.get("coverage"), simple.COVERAGE, "coverage")
    if cov:
        out["coverage"] = cov
        if cov == "full":
            why = full_refusal(gaps(out, ws))
            if why:
                raise _err(why)
    if rec.get("bridge") is not None:
        out["bridge"] = _bridge(rec["bridge"], claim, snap, root, cur, repin)
    return out


def _bridge(b, claim: str, snap, root, cur: dict | None, repin: bool) -> dict:
    """A bridge as recorded: checked now by Lean, and pinned to the target and the claim's
    passage as they are now. A bridge Lean does not check is refused."""
    _fields(b, ("theorem", "target", "target_fingerprint", "source_sha256", "module", "type",
                "axioms", "checked_at"), "a bridge")
    thm = _text(b.get("theorem"), "the bridge's theorem", True).strip()
    target = _text(b.get("target"), "the bridge's target", True).strip()
    old = (cur or {}).get("bridge") or {}
    if not repin and (old.get("theorem"), old.get("target")) == (thm, target):
        # The bridge keeps the versions it was checked at until it is re-pinned.
        return dict(old)
    if root is None or snap is None:
        raise _err("a bridge is checked by Lean against the claim's passage: it needs the Lean "
                   "project and its build")
    from .simple import ViewError
    try:
        body = check(Path(root), thm, target)
    except ViewError as e:
        raise _err(f"the bridge was not checked: {e}") from None
    passage = (snap.chunk(claim) or {}).get("source_sha256")
    ev = evaluate({"theorem": thm, "target": target}, body, passage)
    if ev["reasons"] and ev["state"] == "unchecked":
        raise _err(f"the bridge {thm} for {target} is refused: " + "; ".join(ev["reasons"]))
    acc = body.get("accept") or {}
    return {"theorem": thm, "target": target, "module": acc.get("module"),
            "type": (acc.get("type") or {}).get("text") if isinstance(acc.get("type"), dict)
            else acc.get("type"),
            "axioms": acc.get("axioms") or [],
            "target_fingerprint": ev["current"]["target_fingerprint"],
            "source_sha256": passage,
            "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


# -- the bridge check ------------------------------------------------------------------------

def check(root: Path, theorem: str, target: str, lake: str = "lake", log=None,
          cached_only: bool = False) -> dict:
    """Lean's answer about a bridge: the probe's `accept` record for `theorem` against `target`,
    the target's record and the fingerprints of the definitions its statement uses. Kept in the
    facts store with the environment of the theorem's module (which imports the target's when
    its type is the target) and reused until a module of it changes. `cached_only` answers from
    the store or with `status: "not checked"`."""
    from .config import work_dir_name
    from .deps import _resolve, store
    from .facts import graphs
    from .probe import lib_names
    from .simple import ViewError, _clean, built_modules, probe_modules
    libs = lib_names(root)
    if not libs:
        raise ViewError("no Lean library found in the lakefile")
    built, unbuilt = built_modules(root, libs)
    if not built:
        raise ViewError("the Lean project is not built (run `lake build`)")
    module, answer = _resolve(root, theorem, None, built, unbuilt)
    if answer is not None:
        return {"status": answer["status"], "accept": {"errors": ["missing"]}
                if answer["status"] == "not found" else None, "target": None, "decls": {},
                "reason": f"{theorem}: {answer['status']}"}
    st = store(root, libs)
    key = f"{theorem}\0{target}\0{module or '*'}"
    entry, _ = st.get(KIND, key)
    if entry is not None:
        return {**entry["body"], "cache": {"hit": True}}
    if cached_only:
        return {"status": "not checked", "accept": None, "target": None, "decls": {},
                "reason": "Lean has not checked the bridge since the Lean last changed; "
                          "`machinechecked workspace show` checks it"}
    with st.lock(log):
        entry, _ = st.get(KIND, key)
        if entry is not None:
            return {**entry["body"], "cache": {"hit": True}}
        mods = [module] if module else built
        requests = [{"kind": "accept", "name": theorem, "spec": target},
                    {"kind": "link", "name": target}, {"kind": "modules", "name": ""}]
        recs, failed = probe_modules(root, mods, libs, requests, lake, log=log or (lambda m: None),
                                     work=root / work_dir_name(root) / "build")
        accepts = [r for r in recs if r.get("record") == "accept" and r.get("name") == theorem]
        found = [r for r in accepts if "missing" not in (r.get("errors") or [])]
        groups = {r.get("probe_group") for r in found}
        if len(groups) > 1:
            return {"status": "ambiguous", "accept": None, "target": None, "decls": {},
                    "reason": f"several libraries declare {theorem}"}
        if not found and failed:
            return {"status": "not checked", "accept": None, "target": None, "decls": {},
                    "reason": "some built modules could not be loaded: "
                              + ", ".join(sorted(failed)[:3])}
        if any(str(e).startswith("probe-error") for r in recs for e in r.get("errors") or []):
            return {"status": "not checked", "accept": None, "target": None, "decls": {},
                    "reason": "the probe failed on this request; ask again"}
        group = next(iter(groups)) if groups else None
        mine = [r for r in recs if group is None or r.get("probe_group") == group]
        acc = (found or accepts or [None])[0]
        tgt = next((r for r in mine if r.get("record") == "link" and r.get("name") == target),
                   None)
        decls = {r["name"]: {"fingerprint": r.get("fingerprint")
                             or (r.get("decl") or {}).get("fingerprint")}
                 for r in mine if r.get("record") == "decl"}
        body = {"status": "checked", "accept": _clean(acc) if acc else {"errors": ["missing"]},
                "target": _clean(tgt) if tgt else None, "decls": decls}
        graph: dict[str, list[str]] = {}
        for g, gr in graphs(recs).items():
            if group is None or g == group:
                graph.update(gr)
        mods_env = [acc["module"]] if acc and acc.get("module") else mods
        st.put(KIND, key, st.environment(mods_env, graph), body=body)
    return {**body, "cache": {"hit": False}}


def evaluate(bridge: dict, body: dict, passage: str | None) -> dict:
    """Whether Lean's answer `body` (`check`) establishes the bridge as recorded: `state` is
    `checked` (the theorem's type is exactly the target, a proposition stated as a definition,
    with no `sorry` and only allowed axioms, and the target and the claim's passage are the
    versions recorded), `stale` (checked, but the target or the passage changed since), or
    `unchecked`, with `reasons` (`simple.bridge_evidence`)."""
    from .simple import bridge_evidence
    if body.get("status") not in ("checked", None) and not body.get("accept"):
        return {"theorem": bridge.get("theorem"), "target": bridge.get("target"),
                "state": "unchecked", "reasons": [body.get("reason") or body.get("status")],
                "pinned": {k: bridge.get(k) for k in ("target_fingerprint", "source_sha256")},
                "current": {"target_fingerprint": None, "source_sha256": passage}}
    entry = {"basis": "checked_bridge", "lean": [bridge["theorem"]],
             "bridge": {k: bridge.get(k) for k in ("theorem", "target", "target_fingerprint",
                                                   "source_sha256")}}
    return bridge_evidence({"source_sha256": passage}, entry, body.get("accept"),
                           body.get("target"), body.get("decls") or {})


def bridge_currency(b: dict, claim: str, snap, root, check_now: bool = False) -> dict:
    """The bridge of a composition against the current Lean and paper (`evaluate`); `unchecked`
    without the Lean project, or while Lean has not checked it since the Lean last changed
    (`check_now` asks Lean)."""
    passage = (snap.chunk(claim) or {}).get("source_sha256") if snap is not None else None
    if root is None:
        return {"theorem": b.get("theorem"), "target": b.get("target"), "state": "unchecked",
                "reasons": ["no Lean project to check the bridge against"],
                "pinned": {k: b.get(k) for k in ("target_fingerprint", "source_sha256")},
                "current": {"target_fingerprint": None, "source_sha256": passage}}
    from .simple import ViewError
    try:
        body = check(Path(root), b["theorem"], b["target"], cached_only=not check_now)
    except ViewError as e:
        body = {"status": "not checked", "reason": str(e)}
    if snap is None:
        passage = b.get("source_sha256")
    return evaluate(b, body, passage)


def finding_bridge(f: dict, compositions: dict, snap, root, check_now: bool = False) \
        -> dict | None:
    """The bridge check a finding recorded with basis `checked_bridge` rests on, or None for a
    finding with another basis: its composition's (`compositions` holds each as `view` gives
    it), else its own `bridge` against the current Lean and paper (`bridge_currency`), else an
    unchecked one, since nothing names a bridge. The finding counts as a checked bridge only
    while the state is `checked`."""
    if f.get("basis") != BASIS_BRIDGE:
        return None
    cid = f.get("composition")
    if cid:
        c = compositions.get(cid)
        if c is None:
            reason = f"its composition {cid} is not among these records"
        elif c.get("bridge_check"):
            return c["bridge_check"]
        else:
            reason = f"its composition {cid} has no bridge"
        return {"theorem": None, "target": None, "state": "unchecked", "reasons": [reason]}
    b = f.get("bridge")
    if isinstance(b, dict) and all(isinstance(b.get(k), str) and b[k]
                                   for k in ("theorem", "target")):
        return bridge_currency(b, f["claim"], snap, root, check_now)
    return {"theorem": None, "target": None, "state": "unchecked",
            "reasons": ["no bridge is recorded"]}


# -- reading it back -------------------------------------------------------------------------

def currency(rec: dict, ws: dict, cur: dict, snap) -> dict:
    """A composition's currency: stale when evidence it uses changed, when a requirement a step
    establishes changed, or when its claim's printed text changed. Its bridge is checked apart
    (`bridge_currency`)."""
    from . import requirements as rq
    changes = [ch for e in rec.get("evidence") or [] for ch in cur.get(e, {}).get("changes", [])]
    for lid in dict.fromkeys(l for s in rec.get("steps") or [] for l in s.get("requirements")
                             or []):
        changes += rq.requirement_changes(ws, rec["claim"], lid, cur)
    pin = (rec.get("pins") or {}).get("statement_sha256")
    if snap is not None:
        ch = snap.chunk(rec["claim"])
        if ch is None:
            changes.append({"claim": rec["claim"], "was": pin, "now": None})
        elif pin and ch.get("source_sha256") != pin:
            changes.append({"claim": rec["claim"], "was": pin, "now": ch.get("source_sha256")})
    return {"state": "stale" if changes else "current", "changes": changes}


def view(rec: dict, ws: dict, cur: dict, bridge: dict | None) -> dict:
    """A composition as the reader, `workspace show` and `compare --query composition` present
    it: its record, its currency, its basis (a checked bridge only while `bridge` says Lean
    checks it), what it leaves uncovered or open, and the next step for a reviewed
    composition."""
    from .simple import COMPOSITION_NEXT_STEP
    g = gaps(rec, ws)
    basis = BASIS_BRIDGE if bridge and bridge.get("state") == "checked" else BASIS_REVIEWED
    out = {**rec, "currency": cur.get(rec["id"], {"state": "unchecked", "changes": []}),
           "basis": basis, "gaps": g,
           "complete": bool(g["requirements"]) and not g["uncovered"] and not g["open"],
           "next_step": COMPOSITION_NEXT_STEP if basis == BASIS_REVIEWED else None}
    if rec.get("bridge"):
        out["bridge_check"] = bridge
    return out


def lines(c: dict) -> list[str]:
    """A composition for the terminal."""
    from .semantic import basis_words, in_text, reading_words
    # Its basis is a checked bridge only while Lean checks the bridge (`view`).
    head = in_text(reading_words(c.get("coverage"))) or "no coverage recorded"
    out = [f"  composition {c['id']}: {head}, {in_text(basis_words(c['basis']))}"
           + ("  [stale]" if c["currency"]["state"] == "stale" else "")]
    if c.get("statement"):
        out.append(f"    combined statement: {c['statement']}")
    for s in c["steps"]:
        rests = ", ".join((s.get("uses") or []) + [f"step {a}" for a in s.get("after") or []])
        out.append(f"    {s['id']}: {s['establishes']}  (from {rests}"
                   + (f"; establishes {', '.join(s['requirements'])}" if s.get("requirements")
                      else "") + ")")
        for x in s.get("substitutions") or []:
            out.append(f"        {x['variable']} := {x['value']}"
                       + (f" in {x['in']}" if x.get("in") else ""))
        if s.get("inference"):
            out.append(f"        the auditor's inference: {s['inference']}")
    for x in c.get("identifications") or []:
        out.append(f"    {x['left']['object']} of {x['left']['step']} is {x['relation']} as "
                   f"{x['right']['object']} of {x['right']['step']} ({x['how']}"
                   + (f": {', '.join(x['evidence'])}" if x.get("evidence") else "") + ")")
    for o in c.get("obligations") or []:
        by = o.get("by") or {}
        out.append(f"    obligation {o['id']} ({OBLIGATION_WORDS[o['kind']]}), {o['state']}: "
                   f"{o['text']}" + (" — discharged by " + ", ".join(
                       (by.get("steps") or []) + (by.get("evidence") or [])) if by else ""))
    g = c["gaps"]
    if g["uncovered"]:
        out.append(f"    no step establishes: {', '.join(g['uncovered'])}")
    b = c.get("bridge_check")
    if b:
        out.append(f"    bridge {b.get('theorem')} for {b.get('target')}: "
                   + ("Lean checks it" if b["state"] == "checked" else
                      ("out of date: " if b["state"] == "stale" else "not checked: ")
                      + "; ".join(b.get("reasons") or [])))
    if c.get("next_step"):
        out.append("    Lean has not checked this combination. Next step: " + c["next_step"])
    return out


def query(work_dir: Path, snap, claim: str, root: Path | None = None,
          workspace: str | None = None, check_now: bool = False) -> list[dict]:
    """The compositions recorded for `claim` in the workspaces of `work_dir` (or the one named),
    as `view` gives them, each with its workspace and auditor."""
    from . import workspace as wsp
    out = []
    for _, ws in wsp.list_all(work_dir):
        if workspace and ws["id"] != workspace:
            continue
        v = wsp.view(ws, snap, claim, root, check_facts=check_now)
        for c in (v["claims"].get(claim) or {}).get("compositions") or []:
            out.append({**c, "workspace": ws["id"], "reviewer": v["reviewer"],
                        "mode": v["mode"]})
    if workspace and not any(ws["id"] == workspace for _, ws in wsp.list_all(work_dir)):
        raise wsp.WorkspaceError(f"no workspace {workspace} in {wsp.store(work_dir)}")
    return out

