"""A claim's requirements as an auditor reads them, the passages of the paper that govern each
one, and their association with Lean (records of a workspace, `workspace.py`).

A requirement is one thing the claim demands, in the auditor's words, with a local id under the
claim (`r1`, `r1.2`) and its place in the claim's logical structure (`parent`, `form`): "for
every ε > 0", "there is C, independent of ε", "the estimate (4.25)". Its sources are fragments:
exact regions of the paper's source in the build's snapshot of the paper (or another claim's
whole passage), each with the role it plays in the reading (the statement itself, the domain of
a quantifier, the allowed dependence of a constant, a standing assumption, a definition, a
later use) and whether the paper prints it for this claim, the auditor infers the attachment,
or it is a proposed correction. A fragment can be suggested by the engine from the passage's
neighbourhood; it is a proposal until the auditor accepts it, and removing it keeps who removed
it and why. An alignment associates one or more requirements with one or more Lean targets (a
declaration, or a variable, binder or sub-term of its statement), many to many, with the
relation recorded.

These records are readings. They are pinned to the source text and the declarations they were
made against and go stale when either changes; they change no status, and a later use of a
result never rewrites the requirement it uses (it is shown as a use, apart from the reading).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

FORMS = ("statement", "object", "assumption", "conclusion", "condition", "for every",
         "there is", "and", "or", "not", "implies", "constant dependence", "definition",
         "other")
BINDING_FORMS = ("for every", "there is", "constant dependence")
ORIGINS = ("printed", "correction")
FRAGMENT_ROLES = ("statement", "quantifier domain", "constant dependence",
                  "standing assumption", "definition", "earlier choice", "cited result",
                  "context", "later use", "proposed correction")
FRAGMENT_ORIGINS = ("printed", "inferred", "correction")
FRAGMENT_STATES = ("proposed", "accepted", "removed")
RELATIONS = ("corresponds", "additional assumption", "changed", "alternative representation")
LOCAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
FRAGMENT_LINES = 60

# The words a reading of a fragment's role or a witness's scope shows.
ROLE_WORDS = {"statement": "the statement", "quantifier domain": "domain of a quantifier",
              "constant dependence": "allowed dependence of a constant",
              "standing assumption": "standing assumption", "definition": "definition used",
              "earlier choice": "choice made earlier", "cited result": "result cited",
              "context": "context", "later use": "later use",
              "proposed correction": "proposed correction"}
SCOPE_WORDS = {"produced": "the claim produces it", "assumed": "assumed by the claim",
               "denied": "the claim says there is none",
               "alternative": "inside one alternative"}


class RequirementError(ValueError):
    """A requirement record refused, with what to do instead."""


def _err(msg: str):
    from .workspace import WorkspaceError
    return WorkspaceError(msg)


def _text(v, what, required=False):
    from .workspace import _text as t
    return t(v, what, required)


def _choice(v, allowed, what, optional=True):
    from .workspace import _choice as c
    return c(v, allowed, what, optional)


def sources_dir(snap, paper: str) -> Path | None:
    """The build's snapshot of a paper's source (`<work dir>/sources/<paper>/`, or under the
    snapshot's `sources_base`), which the claims' anchors and the fragments' regions are
    relative to."""
    if snap is None or not paper:
        return None
    base = getattr(snap, "sources_base", None) or Path(snap.data).parent.parent / "sources"
    d = Path(base) / paper
    return d if d.is_dir() else None


def _requirements(ws: dict, claim: str) -> dict[str, dict]:
    return {r["local_id"]: r for r in ws["records"].values()
            if r.get("kind") == "requirement" and r.get("claim") == claim}


def known_requirement(ws: dict, claim: str, local_id, what: str = "the requirement") -> str:
    lid = _text(local_id, what, True).strip()
    if lid not in _requirements(ws, claim):
        raise _err(f"{claim} has no requirement {lid!r} in this workspace (add it first)")
    return lid


# -- validation ------------------------------------------------------------------------------

def requirement_content(out: dict, rec: dict, ws: dict, rid: str | None) -> dict:
    lid = _text(rec.get("local_id"), "the requirement's local id (`local_id`)", True).strip()
    if not LOCAL_ID.fullmatch(lid):
        raise _err(f"{lid!r} is not a local id (letters, digits, `.`, `_`, `-`; up to 40)")
    others = _requirements(ws, out["claim"])
    if lid in others and others[lid]["id"] != rid:
        raise _err(f"{out['claim']} already has a requirement {lid} ({others[lid]['id']})")
    out["local_id"] = lid
    out["form"] = _choice(rec.get("form") or "condition", FORMS, "the form", False)
    out["text"] = _text(rec.get("text"), "the requirement (`text`)", True)
    out["origin"] = _choice(rec.get("origin") or "printed", ORIGINS, "the origin", False)
    if rec.get("parent") not in (None, ""):
        parent = known_requirement(ws, out["claim"], rec["parent"], "the parent")
        seen, at = {lid}, parent
        while at:
            if at in seen:
                raise _err(f"{lid} cannot be inside {parent}: {parent} is inside {lid}")
            seen.add(at)
            at = (others.get(at) or {}).get("parent")
        out["parent"] = parent
    binds = rec.get("binds")
    if binds not in (None, []):
        if out["form"] not in BINDING_FORMS:
            raise _err(f"only a requirement of form {', '.join(BINDING_FORMS)} binds variables")
        if not isinstance(binds, list) or not all(isinstance(b, str) and b.strip()
                                                  for b in binds):
            raise _err("`binds` is a list of the variables' names")
        out["binds"] = [b.strip() for b in binds]
    if rec.get("independent_of") not in (None, []):
        ind = rec["independent_of"]
        if out["form"] not in ("there is", "constant dependence"):
            raise _err("`independent_of` belongs to a constant or witness (`there is` or "
                       "`constant dependence`)")
        if not isinstance(ind, list) or not all(isinstance(b, str) and b.strip() for b in ind):
            raise _err("`independent_of` is a list of the variables' names")
        out["independent_of"] = [b.strip() for b in ind]
    if out["origin"] == "correction":
        if rec.get("corrects") in (None, ""):
            raise _err("a requirement added by a correction names the printed requirement it "
                       "corrects (`corrects`), which stays as printed")
    if rec.get("corrects") not in (None, ""):
        if out["origin"] != "correction":
            raise _err("`corrects` belongs to a requirement with origin `correction`")
        out["corrects"] = known_requirement(ws, out["claim"], rec["corrects"], "`corrects`")
        if out["corrects"] == lid:
            raise _err("a correction is a requirement of its own, beside the printed one")
    return out


def _region(spec, snap, paper: str) -> dict:
    """A region of the paper's source, checked against the build's snapshot of it."""
    from .source_regions import RegionError, extract
    if not isinstance(spec, dict) or not isinstance(spec.get("file"), str):
        raise _err("a region is {file, start_line, end_line[, start_column, end_column]}")
    extra = set(spec) - {"paper", "file", "start_line", "end_line", "start_column", "end_column",
                         "sha256", "line_sha256", "text"}
    if extra:
        raise _err(f"a region has no field {', '.join(sorted(extra))}")
    pid = spec.get("paper") or paper
    out = {"paper": pid, "file": spec["file"]}
    for k in ("start_line", "end_line", "start_column", "end_column"):
        v = spec.get(k)
        if v is not None:
            if type(v) is not int or v < 1:
                raise _err(f"{k} is a positive number")
            out[k] = v
    if "start_line" not in out:
        raise _err("a region names its first line (`start_line`)")
    out.setdefault("end_line", out["start_line"])
    if out["end_line"] < out["start_line"]:
        raise _err("a region ends before it starts")
    if out["end_line"] - out["start_line"] >= FRAGMENT_LINES:
        raise _err(f"a fragment is at most {FRAGMENT_LINES} lines; attach a longer passage "
                   "as several fragments")
    if snap is None:
        # Without a build the region cannot be read: it is kept unpinned (`unchecked`).
        return out
    src = sources_dir(snap, pid)
    if src is None:
        raise _err(f"this build holds no source of paper {pid} to locate the region in")
    try:
        reg = extract(src, region_claim(out))
    except (RegionError, OSError, UnicodeError) as e:
        raise _err(f"{out['file']}:{out['start_line']}: {e}") from None
    out.update(sha256=reg.sha256, line_sha256=reg.line_sha256, text=reg.text)
    return out


def region_claim(region: dict) -> dict:
    """The region as `source_regions.extract` locates one."""
    span = {"end_line": region.get("end_line", region["start_line"])}
    for k in ("start_column", "end_column"):
        if region.get(k):
            span[k] = region[k]
    return {"location": f"{region['file']}:{region['start_line']}", "source_region": span}


LOCATION = ("paper", "file", "start_line", "end_line", "start_column", "end_column")


def fragment_content(out: dict, rec: dict, ws: dict, snap, cur: dict | None,
                     repin: bool) -> dict:
    from .workspace import _claim
    out["requirement"] = known_requirement(ws, out["claim"], rec.get("requirement"))
    out["role"] = _choice(rec.get("role"), FRAGMENT_ROLES, "the role", False)
    origin = rec.get("origin") or ("correction" if out["role"] == "proposed correction"
                                   else "printed")
    out["origin"] = _choice(origin, FRAGMENT_ORIGINS, "the origin", False)
    if out["role"] == "proposed correction" and out["origin"] != "correction":
        raise _err("a proposed correction has origin `correction`")
    out["state"] = _choice(rec.get("state") or "accepted", FRAGMENT_STATES, "the state", False)
    if out["state"] == "removed":
        out["why_removed"] = _text(rec.get("why_removed"), "why it was removed (`why_removed`)",
                                   True)
    if rec.get("scope") not in (None, ""):
        out["scope"] = _text(rec["scope"], "the scope")
    if rec.get("suggestion") is not None:
        s = rec["suggestion"]
        if not isinstance(s, dict) or not isinstance(s.get("rule"), str):
            raise _err("a suggestion is {rule, by}")
        out["suggestion"] = {"rule": s["rule"], "by": str(s.get("by") or "machinechecked")}
    has_region, has_passage = rec.get("region") is not None, rec.get("passage") is not None
    if has_region == has_passage:
        raise _err("a fragment is one region of the source (`region`) or one claim's passage "
                   "(`passage`: {claim})")
    paper = (snap.chunk(out["claim"]) or {}).get("paper") if snap is not None else None
    paper = paper or (out["claim"].split(":", 1)[0] if ":" in out["claim"] else None)
    if has_region:
        old = (cur or {}).get("region") or {}
        loc = {k: (rec["region"] or {}).get(k) for k in LOCATION} \
            if isinstance(rec["region"], dict) else None
        if loc is not None:
            loc["paper"] = loc.get("paper") or paper
            if loc.get("end_line") is None:
                loc["end_line"] = loc.get("start_line")
        if cur is not None and not repin and loc == {k: old.get(k) for k in LOCATION}:
            # The fragment keeps the text it was attached with until it is re-pinned.
            out["region"] = dict(old)
        else:
            out["region"] = _region(rec["region"], snap, paper)
    else:
        p = rec["passage"]
        if not isinstance(p, dict):
            raise _err("a passage is {claim}")
        cid = _claim(p.get("claim"), snap)
        old = (cur or {}).get("passage") or {}
        if cur is not None and not repin and old.get("claim") == cid:
            out["passage"] = dict(old)
        else:
            ch = snap.chunk(cid) if snap is not None else None
            out["passage"] = {"claim": cid, "sha256": (ch or {}).get("source_sha256")}
    return out


def _statements(snap, claim: str) -> dict[str, dict]:
    """The statements of the claim's declarations the build holds, by name."""
    ch = (snap.chunk(claim) or {}) if snap is not None else {}
    out = {}
    for l in (ch.get("links") or []) + (ch.get("suggestions") or []):
        if l.get("name") and l.get("statement"):
            out.setdefault(l["name"], l["statement"])
    for cl in ch.get("clauses") or []:
        if cl.get("spec") and cl.get("statement"):
            out.setdefault(cl["spec"], cl["statement"])
    return out


SUBTARGETS = ("var", "binder", "at", "conclusion")


def _target(t, snap, root, claim: str, olds: list[dict], repin: bool) -> dict:
    from . import symbols
    if not isinstance(t, dict) or not isinstance(t.get("decl"), str) or not t["decl"].strip():
        raise _err("a Lean target names its declaration (`decl`)")
    extra = set(t) - {"decl", "module", "external", "build", "fingerprint", "digest", "target",
                      *SUBTARGETS}
    if extra:
        raise _err(f"a Lean target has no field {', '.join(sorted(extra))}")
    out = {"decl": t["decl"].strip()}
    subs = [k for k in SUBTARGETS if t.get(k) not in (None, False)]
    if len(subs) > 1:
        raise _err("a Lean target names at most one of var, binder, at, conclusion")
    statements = _statements(snap, claim)
    st = statements.get(out["decl"])
    if subs:
        k = subs[0]
        if snap is not None and st is None:
            raise _err(f"this build holds no statement of {out['decl']} for {claim}: a part "
                       "of it can be named once it is linked to the claim")
        if k == "conclusion":
            out["conclusion"] = True
            if st is not None:
                out["target"] = symbols._text(st.get("conclusion"))
        elif k == "at":
            out["at"] = _text(t["at"], "the sub-term's identity", True)
            if st is not None:
                txt = symbols.term_by_id(st, out["at"])
                if txt is None:
                    raise _err(f"{out['decl']} has no sub-term with the identity {out['at']!r}")
                out["target"] = txt
        else:
            v = t[k]
            if st is not None:
                names = [b.get("name") for b in symbols.variables(st)]
                if isinstance(v, str) and not v.isdigit():
                    if v not in names:
                        raise _err(f"{out['decl']} has no variable {v!r} (it has "
                                   f"{', '.join(str(n) for n in names if n)})")
                    v = names.index(v)
                v = int(v)
                txt = symbols.target_text(st, {k: v})
                if txt is None:
                    raise _err(f"{out['decl']} has no variable number {v}")
                out["target"] = txt
            elif not isinstance(v, int):
                raise _err(f"`{k}` is a variable's number")
            out[k] = v
    old = next((o for o in olds if all(o.get(k) == out.get(k) for k in ("decl", *SUBTARGETS))),
               None)
    if old is not None and not repin:
        # The target keeps the fingerprint it was recorded at until it is re-pinned.
        return dict(old)
    if snap is None:
        for k in ("module", "build", "fingerprint", "digest", "target"):
            if t.get(k) is not None:
                out.setdefault(k, t[k])
        return out
    fps = {**snap.store_fingerprints(), **snap.fingerprints()}
    if st is not None or out["decl"] in fps:
        out["build"] = "built"
        if st is not None and st.get("fingerprint"):
            fps.setdefault(out["decl"], st["fingerprint"])
    else:
        from .targets import TargetError, resolve_declaration
        try:
            r = resolve_declaration(out["decl"], snap, root, t.get("module"),
                                    external=bool(t.get("external")))
        except TargetError as e:
            raise _err(str(e)) from None
        out.update(module=r["module"], build=r["build"])
    out["fingerprint"] = fps.get(out["decl"])
    out["digest"] = snap.digests().get(out["decl"])
    return out


def alignment_content(out: dict, rec: dict, ws: dict, snap, root, cur: dict | None,
                      repin: bool) -> dict:
    reqs = rec.get("requirements")
    if isinstance(reqs, str):
        reqs = [reqs]
    if reqs is None:
        reqs = []
    if not isinstance(reqs, list):
        raise _err("`requirements` is a list of the requirements' local ids")
    out["relation"] = _choice(rec.get("relation") or "corresponds", RELATIONS, "the relation",
                              False)
    if not reqs and out["relation"] != "additional assumption":
        raise _err("an alignment names the requirements it concerns; only an additional "
                   "assumption of the Lean has none")
    out["requirements"] = list(dict.fromkeys(known_requirement(ws, out["claim"], r)
                                             for r in reqs))
    lean = rec.get("lean")
    if isinstance(lean, dict):
        lean = [lean]
    if not isinstance(lean, list) or not lean:
        raise _err("an alignment names one or more Lean targets (`lean`)")
    olds = list((cur or {}).get("lean") or [])
    targets = []
    for t in lean:
        tgt = _target(t, snap, root, out["claim"], olds, repin)
        if tgt not in targets:
            targets.append(tgt)
    out["lean"] = targets
    return out


def references(ws: dict, claim: str, lid: str, but: str | None = None) -> list[str]:
    """The records that refer to the requirement `lid` of `claim`."""
    users = []
    for r in ws["records"].values():
        if r.get("claim") != claim or r["id"] == but:
            continue
        if r.get("kind") == "requirement" and lid in (r.get("parent"), r.get("corrects")):
            users.append(r["id"])
        elif r.get("kind") == "fragment" and r.get("requirement") == lid:
            users.append(r["id"])
        elif r.get("kind") == "alignment" and lid in (r.get("requirements") or []):
            users.append(r["id"])
        elif r.get("kind") in ("finding", "question") and r.get("requirement") == lid:
            users.append(r["id"])
    return users


# -- currency --------------------------------------------------------------------------------

def fragment_currency(r: dict, snap) -> dict:
    from .source_regions import RegionError, extract
    if snap is None:
        return {"state": "unchecked", "changes": []}
    if r.get("passage"):
        p = r["passage"]
        ch = snap.chunk(p["claim"])
        now = (ch or {}).get("source_sha256")
        if not p.get("sha256") or (ch is not None and not now):
            return {"state": "unchecked", "changes": []}
        if now != p["sha256"]:
            return {"state": "stale", "changes": [{"passage": p["claim"], "was": p["sha256"],
                                                   "now": now}]}
        return {"state": "current", "changes": []}
    reg = r.get("region") or {}
    src = sources_dir(snap, reg.get("paper"))
    if src is None or not reg.get("sha256"):
        return {"state": "unchecked", "changes": []}
    where = f"{reg['file']}:{reg['start_line']}" + (
        f"-{reg['end_line']}" if reg.get("end_line", reg["start_line"]) != reg["start_line"]
        else "")
    try:
        now = extract(src, region_claim(reg))
    except (RegionError, OSError, UnicodeError):
        return {"state": "stale", "changes": [{"region": where, "was": reg["sha256"],
                                               "now": None}]}
    if now.sha256 != reg["sha256"]:
        lines = [reg["start_line"] + i for i, (a, b) in
                 enumerate(zip(reg.get("line_sha256") or [], now.line_sha256)) if a != b]
        return {"state": "stale", "changes": [{"region": where, "was": reg["sha256"],
                                               "now": now.sha256, "lines": lines}]}
    return {"state": "current", "changes": []}


def alignment_currency(r: dict, snap) -> dict:
    if snap is None:
        return {"state": "unchecked", "changes": []}
    digests = snap.digests()
    changes, unchecked = [], False
    for t in r.get("lean") or []:
        was, now = t.get("digest") or t.get("fingerprint"), digests.get(t["decl"])
        if not was or now is None:
            unchecked = True
        elif was != now:
            changes.append({"decl": t["decl"], "was": was, "now": now})
    if changes:
        return {"state": "stale", "changes": changes}
    return {"state": "unchecked" if unchecked else "current", "changes": []}


def currency(ws: dict, snap) -> dict[str, dict]:
    """The currency of every fragment, alignment and requirement: a requirement is stale when
    one of its fragments (not removed) or alignments is."""
    out = {}
    for r in ws["records"].values():
        if r.get("kind") == "fragment":
            out[r["id"]] = (fragment_currency(r, snap) if r.get("state") != "removed"
                            else {"state": "removed", "changes": []})
        elif r.get("kind") == "alignment":
            out[r["id"]] = alignment_currency(r, snap)
    for r in ws["records"].values():
        if r.get("kind") != "requirement":
            continue
        changes = []
        for u in ws["records"].values():
            if u.get("claim") != r["claim"]:
                continue
            if (u.get("kind") == "fragment" and u.get("requirement") == r["local_id"]) or \
                    (u.get("kind") == "alignment" and r["local_id"] in (u.get("requirements")
                                                                        or [])):
                changes += out.get(u["id"], {}).get("changes", [])
        out[r["id"]] = {"state": "stale" if changes else "current", "changes": changes}
    return out


def requirement_changes(ws: dict, claim: str, lid: str, cur: dict) -> list[dict]:
    r = _requirements(ws, claim).get(lid)
    return list(cur.get(r["id"], {}).get("changes", [])) if r else []


# -- the reading -----------------------------------------------------------------------------

def _pin(fr: dict) -> str | None:
    return (fr.get("region") or {}).get("sha256") or (fr.get("passage") or {}).get("sha256")


def reading_digest(req: dict, fragments: list[dict]) -> str:
    """A digest of what the requirement reads: its form, words and variables, and the pins of
    the fragments that govern it (not later uses, proposals or removed ones)."""
    body = {k: req.get(k) for k in ("form", "text", "binds", "independent_of", "origin",
                                    "parent", "corrects")}
    body["fragments"] = sorted([fr["role"], fr["origin"], _pin(fr)] for fr in fragments
                               if fr.get("state") == "accepted" and fr["role"] != "later use")
    return "reading-v1:" + hashlib.sha256(json.dumps(body, sort_keys=True,
                                                     ensure_ascii=False).encode()).hexdigest()


def witnesses(reqs: list[dict]) -> list[dict]:
    """Each `there is` requirement as a witness obligation: the variables it introduces, whether
    the claim produces it, assumes it, denies it or has it inside one alternative, the
    variables of enclosing `for every` requirements it may depend on (`after`), those it is
    chosen before (`before`), the variables it is stated independent of, and the
    requirements it must meet (its children)."""
    by = {r["local_id"]: r for r in reqs}
    kids: dict[str, list[str]] = {}
    for r in reqs:
        if r.get("parent") in by:
            kids.setdefault(r["parent"], []).append(r["local_id"])

    def below(lid):
        out = []
        for k in kids.get(lid, []):
            out.append(k)
            out += below(k)
        return out

    out = []
    for r in reqs:
        if r.get("form") != "there is":
            continue
        chain, at = [], r.get("parent")
        while at in by:
            chain.append(by[at])
            at = by[at].get("parent")
        forms = [a.get("form") for a in chain]
        # The nearest enclosing negation, premise or alternative decides the scope.
        scope = "produced"
        for a in chain:
            if a.get("form") == "not":
                scope = "denied"
                break
            if a.get("form") == "assumption":
                scope = "assumed"
                break
            if a.get("form") == "or":
                scope = "alternative"
                break
        after = [b for a in reversed(chain) if a.get("form") == "for every"
                 for b in a.get("binds") or []]
        before = [b for k in below(r["local_id"]) if by[k].get("form") == "for every"
                  for b in by[k].get("binds") or []]
        out.append({"requirement": r["local_id"], "binds": r.get("binds") or [],
                    "scope": scope, "after": after, "before": before,
                    "independent_of": r.get("independent_of") or [],
                    "conditions": kids.get(r["local_id"], []),
                    "inside": [a["local_id"] for a in chain if a.get("form") in
                               ("not", "or", "implies", "assumption")],
                    "forms": forms})
    return out


def _order(reqs: list[dict]) -> list[tuple[dict, int]]:
    """The requirements in reading order: each followed by those inside it."""
    by = {r["local_id"]: r for r in reqs}
    kids: dict[str | None, list[dict]] = {}
    for r in reqs:
        kids.setdefault(r.get("parent") if r.get("parent") in by else None, []).append(r)
    out = []

    def walk(lid, depth):
        for r in sorted(kids.get(lid, []), key=lambda r: _natural(r["local_id"])):
            out.append((r, depth))
            walk(r["local_id"], depth + 1)
    walk(None, 0)
    return out


def _natural(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def reading(records: list[dict], cur: dict) -> dict:
    """The claim's requirements as the reader, `workspace show` and `compare` present them:
    in reading order, each with its fragments (governing, later uses, proposals, removed) and
    alignments, its currency and the questions it leaves; the witness obligations; and the
    alignments with what they associate."""
    reqs = [r for r in records if r.get("kind") == "requirement"]
    frags = [r for r in records if r.get("kind") == "fragment"]
    aligns = [r for r in records if r.get("kind") == "alignment"]
    items, problems = [], []
    for r, depth in _order(reqs):
        lid = r["local_id"]
        mine = [f for f in frags if f.get("requirement") == lid]
        group = {"governing": [], "later_uses": [], "proposed": [], "removed": []}
        for f in sorted(mine, key=lambda f: (f["created_at"], f["id"])):
            item = {**f, "currency": cur.get(f["id"], {"state": "unchecked", "changes": []})}
            if f.get("state") == "removed":
                group["removed"].append(item)
            elif f.get("state") == "proposed":
                group["proposed"].append(item)
            elif f["role"] == "later use":
                group["later_uses"].append(item)
            else:
                group["governing"].append(item)
        mine_al = [a["id"] for a in aligns if lid in (a.get("requirements") or [])]
        qs = []
        if not group["governing"]:
            qs.append("no passage of the paper is attached as its source"
                      + (" (only later uses are)" if group["later_uses"] else ""))
        if group["proposed"]:
            qs.append(f"{len(group['proposed'])} suggested passage(s) not yet accepted or "
                      "removed")
        if r.get("origin") == "correction" and not any(
                f["role"] == "proposed correction" or f["origin"] == "correction"
                for f in group["governing"]):
            qs.append("a correction with no passage proposing it")
        for q in qs:
            problems.append({"requirement": lid, "question": q})
        items.append({**r, "depth": depth, "fragments": group, "alignments": mine_al,
                      "children": [x["local_id"] for x in reqs if x.get("parent") == lid],
                      "reading_sha256": reading_digest(r, mine),
                      "currency": cur.get(r["id"], {"state": "unchecked", "changes": []}),
                      "questions": qs})
    al_items = [{**a, "currency": cur.get(a["id"], {"state": "unchecked", "changes": []})}
                for a in sorted(aligns, key=lambda a: (a["created_at"], a["id"]))]
    return {"requirements": items, "witnesses": witnesses(reqs), "alignments": al_items,
            "questions": problems}


# -- suggestions -----------------------------------------------------------------------------

QUANTIFIER = re.compile(r"\b(for (every|all|each|any)|there (is|are|exists?)|exists?)\b", re.I)
DEPENDENCE = re.compile(r"\b(independent(ly)? of|depend(s|ing)? only on|not depending on|"
                        r"uniform(ly)? in|does not depend)\b", re.I)
SECTION = re.compile(r"^\s*\\(part|chapter|section|subsection)\*?\s*(\[[^\]]*\])?\s*\{(.*)\}")
REF = re.compile(r"\\(?:eq|c|C|auto|name)?ref\{([^{}]+)\}")


def _where(ch: dict) -> tuple[str, int, int] | None:
    """The file and lines of a claim's passage in the paper's source."""
    ex = ch.get("excerpt") or {}
    if ex.get("file") and ex.get("start_line"):
        return ex["file"], ex["start_line"], ex.get("end_line") or ex["start_line"]
    reg = ch.get("source_region") or {}
    if isinstance(reg, dict) and reg.get("file") and reg.get("start_line"):
        return reg["file"], reg["start_line"], reg.get("end_line") or reg["start_line"]
    a = ch.get("anchor") or {}
    if a.get("file") and a.get("line"):
        return a["file"], a["line"], a.get("end_line") or a["line"]
    return None


def _prose(line: str) -> bool:
    s = line.strip()
    return bool(s) and not s.startswith("%") and not re.match(
        r"\\(begin|end|section|subsection|label|maketitle|documentclass|usepackage)\b", s)


def suggest(snap, claim: str) -> list[dict]:
    """Passages near a claim that may govern its reading, each as a proposed fragment: the
    sentence just before its passage and the one just after (when they read as a quantifier
    or a constraint on a constant), lines inside it that set a quantifier's domain or a
    constant's dependence, the prose that opens its section (a standing assumption), and the
    claims it cites. A proposal is a guess from position and wording; the auditor accepts,
    edits or removes it."""
    ch = snap.chunk(claim) if snap is not None else None
    if ch is None:
        raise _err(f"no claim {claim} in this build")
    where = _where(ch)
    src = sources_dir(snap, ch.get("paper"))
    if where is None or src is None:
        return []
    from .source_regions import RegionError, source_file
    file, first, last = where
    try:
        lines = source_file(src, file).read_text(encoding="utf-8").splitlines()
    except (RegionError, OSError, UnicodeError):
        return []
    out = []

    def add(rule, role, a, b, origin, scope=None):
        if any(o["region"]["start_line"] <= a <= o["region"]["end_line"] for o in out
               if o.get("region")):
            return
        out.append({"role": role, "origin": origin, "state": "proposed",
                    "region": {"paper": ch.get("paper"), "file": file, "start_line": a,
                               "end_line": b},
                    "suggestion": {"rule": rule, "by": "machinechecked"},
                    **({"scope": scope} if scope else {})})

    # Inside the passage.
    for i in range(first, min(last, len(lines)) + 1):
        t = lines[i - 1]
        if not _prose(t):
            continue
        if DEPENDENCE.search(t):
            add("dependence inside the passage", "constant dependence", i, i, "printed")
        elif QUANTIFIER.search(t):
            add("quantifier inside the passage", "quantifier domain", i, i, "printed")
    # The sentence just before and just after.
    i = first - 1
    if i >= 1 and _prose(lines[i - 1]):
        a = i
        while a > 1 and _prose(lines[a - 2]) and i - a < 3:
            a -= 1
        text = " ".join(lines[a - 1:i])
        if QUANTIFIER.search(text) or DEPENDENCE.search(text) or text.rstrip().endswith(
                (",", ":")):
            role = "constant dependence" if DEPENDENCE.search(text) else "quantifier domain"
            add("sentence before the passage", role, a, i, "inferred")
    j = last + 1
    if j <= len(lines) and _prose(lines[j - 1]):
        b = j
        while b < len(lines) and _prose(lines[b]) and b - j < 2 and \
                not re.search(r"[.]\s*$", lines[b - 1]):
            b += 1
        text = " ".join(lines[j - 1:b])
        if DEPENDENCE.search(text) or re.match(r"\s*(with|where|for)\b", text):
            role = "constant dependence" if DEPENDENCE.search(text) else "context"
            add("sentence after the passage", role, j, b, "inferred")
    # The prose that opens the enclosing section.
    sec = next((k for k in range(first - 1, 0, -1) if SECTION.match(lines[k - 1])), None)
    if sec is not None:
        title = SECTION.match(lines[sec - 1]).group(3).strip()
        a = sec + 1
        while a < first and not lines[a - 1].strip() or (a < first and
                                                         lines[a - 1].lstrip().startswith("%")):
            a += 1
        # Only prose before the section's first environment opens it.
        if a < first and _prose(lines[a - 1]):
            b = a
            while b + 1 < first and not re.match(r"\s*\\(begin|section|subsection)\b",
                                                 lines[b]):
                b += 1
            while b > a and not _prose(lines[b - 1]):
                b -= 1
            add("opening of the section", "standing assumption", a, b, "inferred",
                f"the section “{title}”")
    # The claims the passage cites.
    labels = {}
    for c in snap.claims:
        k = snap.key_of(c["id"])
        labels[k] = c
        cc = snap.chunk(c["id"]) or {}
        if (cc.get("anchor") or {}).get("label"):
            labels[cc["anchor"]["label"]] = c
    text = "\n".join(lines[first - 1:last])
    for lab in dict.fromkeys(m.group(1) for m in REF.finditer(text)):
        c = labels.get(lab)
        if c and c["id"] != claim:
            out.append({"role": "definition" if c.get("kind") == "definition"
                        else "cited result", "origin": "printed", "state": "proposed",
                        "passage": {"claim": c["id"]},
                        "suggestion": {"rule": f"reference \\ref{{{lab}}}",
                                       "by": "machinechecked"}})
    return out


def suggestion_ops(ws: dict, snap, claim: str, requirement: str) -> list[dict]:
    """The `put` operations that attach `suggest`'s proposals to a requirement, leaving out
    those the requirement already has (in any state, a removed one included)."""
    requirement = known_requirement(ws, claim, requirement)
    have = []
    for r in ws["records"].values():
        if r.get("kind") == "fragment" and r.get("claim") == claim and \
                r.get("requirement") == requirement:
            loc = r.get("region") or {}
            have.append(("r", loc.get("file"), loc.get("start_line"), loc.get("end_line"))
                        if r.get("region") else ("p", (r.get("passage") or {}).get("claim")))
    ops = []
    for s in suggest(snap, claim):
        loc = s.get("region") or {}
        key = ("r", loc.get("file"), loc.get("start_line"), loc.get("end_line")) \
            if s.get("region") else ("p", s["passage"]["claim"])
        if key in have:
            continue
        ops.append({"op": "put", "record": {"kind": "fragment", "claim": claim,
                                            "requirement": requirement, **s}})
    return ops


# -- text ------------------------------------------------------------------------------------

def where_text(fr: dict) -> str:
    if fr.get("passage"):
        return f"the passage of {fr['passage']['claim']}"
    r = fr.get("region") or {}
    end = r.get("end_line", r.get("start_line"))
    return f"{r.get('file')}:{r.get('start_line')}" + (f"-{end}" if end != r.get("start_line")
                                                       else "")


def target_text(t: dict) -> str:
    if t.get("conclusion"):
        part = "the conclusion"
    elif "var" in t:
        part = f"variable {t['var']}"
    elif "binder" in t:
        part = f"the type of variable {t['binder']}"
    elif "at" in t:
        part = f"sub-term {t['at']}"
    else:
        return t["decl"]
    return f"{t['decl']} ({part}" + (f": {t['target']})" if t.get("target") else ")")


def lines(rd: dict) -> list[str]:
    """A claim's reading for the terminal."""
    out = []
    for r in rd["requirements"]:
        pad = "  " * (r["depth"] + 1)
        head = f"{pad}{r['local_id']}  {r['form']}"
        if r.get("binds"):
            head += " " + ", ".join(r["binds"])
        head += f": {r['text']}"
        if r.get("origin") == "correction":
            head += f"  (added by a correction of {r.get('corrects')})"
        if r["currency"]["state"] == "stale":
            head += "  [stale]"
        out.append(head)
        for f in r["fragments"]["governing"]:
            out.append(f"{pad}  from {where_text(f)} ({ROLE_WORDS[f['role']]}, {f['origin']}"
                       + (f", applies to {f['scope']}" if f.get("scope") else "")
                       + f", by {f.get('created_by')})"
                       + ("  [changed since]" if f["currency"]["state"] == "stale" else ""))
        for f in r["fragments"]["later_uses"]:
            out.append(f"{pad}  used later at {where_text(f)} (a use; the reading is unchanged)")
        for f in r["fragments"]["proposed"]:
            out.append(f"{pad}  suggested: {where_text(f)} ({ROLE_WORDS[f['role']]}; "
                       f"{(f.get('suggestion') or {}).get('rule', 'by ' + str(f.get('created_by')))})"
                       f"  [{f['id']}]")
        for f in r["fragments"]["removed"]:
            out.append(f"{pad}  removed: {where_text(f)} by {f.get('state_by')}: "
                       f"{f.get('why_removed')}")
        for q in r["questions"]:
            out.append(f"{pad}  question: {q}")
    for w in rd["witnesses"]:
        out.append(f"  witness {', '.join(w['binds']) or w['requirement']}: "
                   f"{SCOPE_WORDS[w['scope']]}"
                   + (f"; chosen after {', '.join(w['after'])}" if w["after"] else "")
                   + (f"; chosen before {', '.join(w['before'])}" if w["before"] else "")
                   + (f"; independent of {', '.join(w['independent_of'])}"
                      if w["independent_of"] else ""))
    for a in rd["alignments"]:
        out.append(f"  {', '.join(a['requirements']) or '(no requirement)'} -> "
                   + "; ".join(target_text(t) for t in a["lean"])
                   + f"  ({a['relation']}, recorded by {a.get('created_by')})"
                   + ("  [stale]" if a["currency"]["state"] == "stale" else ""))
    return out
