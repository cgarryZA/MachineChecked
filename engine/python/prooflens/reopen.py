"""The findings of a workspace that a revision of the paper reopens, through the version map
(#120).

A finding records what it rests on (`dependencies.py`). Across two revisions of the paper the
version map (`version_map.py`) says what became of each passage, and so of each paper part a
finding rests on:

- the passage of its claim, a claim's passage it reads as the context of a requirement, a
  passage it quotes as evidence, and the passage a bridge was checked against: the map's entry
  for that claim. The same text, at the same place, moved or renumbered, leaves the part
  current, so a renumbering reopens no statement comparison. A changed or removed passage
  reopens it, and so does a change of what the passage is read with: a further passage of its
  pin, the definition of a macro it uses, the prose opening its section, a claim it refers to.
  A changed definition claim that the claim's Lean relies on reopens only a finding that cites a
  declaration whose statement uses that definition. An ambiguous or unknown match leaves the
  part `unchecked`, never current: a match the map only proposes is not taken.
- a region of the paper attached to a requirement: the map's entry for it (`passages`), found
  by its text.

A part recorded at the later revision is current as far as the map goes. Each reopened part
names the change and the dependency, with a question a new reading answers; nothing is moved
to another claim. The rest of what a finding rests on (its Lean side: declarations,
applications, facts, certificates, alignments and bridges; and the records edited or re-pinned
since it was submitted) is checked against the build of the later release as `workspace show`
checks it, and kept apart (`build`). A workspace evidence record that
quotes the paper, and each passage attached to a requirement, are judged by the map the same
way. Nothing here changes a status: a reopened finding stands as it was recorded until a new
one supersedes it.
"""

from __future__ import annotations

from copy import deepcopy

from . import dependencies as dp
from .version_map import SCHEMA as MAP_SCHEMA, region_key

SCHEMA = "prooflens/reopened@1"
STATES = ("reopened", "unchecked", "current")
STATE_WORDS = {"reopened": "due for review", "unchecked": "not known to be current",
               "current": "still current"}
# The dependencies of a finding that the paper's text decides; the map judges them.
PAPER_KINDS = (dp.PASSAGE, dp.CONTEXT, "paper")
# What a reopened finding shows of itself.
SHOWN = ("coverage", "basis", "confidence", "verdict", "difference", "requirement", "note",
         "question", "would_decide", "state", "submitted_at", "created_by", "composition",
         "supersedes", "reason")
# What a kept map keeps of the version map: the paper's side, without the later build's Lean
# references to paper numbers.
NOT_KEPT = ("references", "workspace")


class MapError(ValueError):
    pass


# -- the map ---------------------------------------------------------------------------------

class _Map:
    """A version map, indexed by the claims of each side and the passages it followed."""

    def __init__(self, doc: dict):
        self.doc = doc
        self.paper = doc["paper"]
        self.earlier = {r["from"]["claim"]: r for r in doc.get("claims") or [] if r.get("from")}
        self.later = {r["to"]["claim"]: r for r in doc.get("claims") or [] if r.get("to")}
        self.passages = {region_key(p["region"], self.paper): p
                         for p in doc.get("passages") or []}

    def of_paper(self, cid: str | None) -> bool:
        return bool(cid) and (cid in self.earlier or cid in self.later
                              or cid.split(":", 1)[0] == self.paper)


def _digest(side: dict | None) -> str | None:
    """The digest of everything a side's pin lists, as the inventory pins it."""
    return (side or {}).get("pin_sha256") or (side or {}).get("sha256")


def _place(side: dict | None) -> dict | None:
    if not side:
        return None
    return {k: side[k] for k in ("claim", "number", "location") if side.get(k)}


def _label(side: dict | None, cid: str) -> str:
    n = (side or {}).get("number")
    return f"{n} ({cid})" if n else cid


def _lean_names(items: list[dict]) -> dict:
    """The declarations a finding cites (as evidence or alignments) and the definitions their
    statements use, each with the declarations that use it (`by`); `unknown` names the cited
    declarations whose statements' definitions were not recorded."""
    by, unknown = {}, []
    for it in items:
        refs = []
        if it["dependency"] == "declaration":
            refs = [it.get("ref") or {}]
        elif it["dependency"] == dp.OBJECT:
            refs = list(it.get("lean") or [])
        for r in refs:
            if not r.get("decl"):
                continue
            for n in [r["decl"]] + sorted(r.get("closure") or {}):
                by.setdefault(n, [])
                if r["decl"] not in by[n]:
                    by[n].append(r["decl"])
            if not isinstance(r.get("closure"), dict):
                unknown.append(r["decl"])
    return {"by": by, "unknown": list(dict.fromkeys(unknown))}


def _through(x: dict, lean: dict | None) -> list[dict]:
    """The cited declarations through which a part relies on a claim the claim's Lean relies
    on: each with the definitions of that claim its statement uses (or that it is)."""
    out: dict[str, list[str]] = {}
    for n in x.get("names") or []:
        for d in ((lean or {}).get("by") or {}).get(n, []):
            out.setdefault(d, []).append(n)
    return [{"decl": d, "uses": u} for d, u in out.items()]


def _relies(x: dict, lean: dict | None) -> str:
    """Whether a part that reads a passage relies on one change of its context: `yes`, `no`, or
    `unknown`. A claim relied on only through the claim's Lean concerns a part that cites a
    declaration whose statement uses one of that claim's definitions."""
    if x.get("what") not in ("definition", "reference") or x.get("via") != ["lean"]:
        return "yes"
    if lean is None:
        return "no"
    if _through(x, lean):
        return "yes"
    return "unknown" if lean["unknown"] else "no"


def _context_words(x: dict) -> str:
    from .version_map import _context_words as words
    out = words(x)
    through = x.get("through") or []
    if through:
        out += " (through " + "; ".join(
            f"{t['decl']}" + ("" if t["uses"] == [t["decl"]] else
                              f", whose statement uses {', '.join(t['uses'])}")
            for t in through) + ")"
    return out


def _with_change(m: _Map, x: dict, lean: dict | None = None) -> dict:
    """A context change, with the change of the claim it names when the map has it, and the
    cited declarations through which a part relies on it (`through`)."""
    out = dict(x)
    if x.get("via") == ["lean"] and _through(x, lean):
        out["through"] = _through(x, lean)
    row = m.earlier.get(x.get("claim") or "")
    if row and row.get("change"):
        out["claim_change"] = row["change"]
    return out


def _passage(m: _Map, cid: str | None, sha: str | None, lean: dict | None = None) -> dict | None:
    """What the map says of a part that read the passage of claim `cid` at digest `sha`, or None
    when the claim is not of the map's paper."""
    if not m.of_paper(cid):
        return None
    row = m.earlier.get(cid)
    if row is None:
        later = m.later.get(cid)
        if later is not None and sha and sha == _digest(later["to"]):
            return {"state": "current", "note": f"it read {_label(later['to'], cid)} as the "
                                                "later revision prints it",
                    "later": _place(later["to"])}
        return {"state": "unchecked",
                "why": f"the version map has no claim {cid} in the earlier revision"}
    here = {"earlier": _place(row["from"]), "later": _place(row.get("to")),
            "class": row["class"]}
    label = _label(row["from"], cid)
    if not sha:
        return {**here, "state": "unchecked", "why": f"the version of the passage of {label} it "
                                                      "read was not recorded"}
    if sha != _digest(row["from"]):
        if row.get("to") and sha == _digest(row["to"]):
            return {**here, "state": "current", "note": f"it read {label} as the later revision "
                                                         "prints it"}
        return {**here, "state": "unchecked",
                "why": f"it read another text of {label} than the earlier revision prints"
                       + (" (the earlier inventory pins other text)"
                          if row["from"].get("pin") == "differs" else "")}
    cls = row["class"]
    if cls in ("unchanged", "moved"):
        note = row.get("reason") or "the same text"
        if row.get("surroundings_changed"):
            note += "; the lines beside it changed"
        return {**here, "state": "current", "note": note}
    if cls == "context-changed":
        ctx = row.get("context") or []
        relied = [_with_change(m, x, lean) for x in ctx if _relies(x, lean) == "yes"]
        if relied:
            return {**here, "state": "reopened",
                    "change": {"class": cls, "reason": "; ".join(dict.fromkeys(
                        _context_words(x) for x in relied)), "context": relied}}
        doubt = [x for x in ctx if _relies(x, lean) == "unknown"]
        if doubt:
            return {**here, "state": "unchecked", "why": (
                f"{'; '.join(_context_words(x) for x in doubt)}; the definitions the statement "
                f"of {', '.join(lean['unknown'])} uses were not recorded, so whether it relies "
                "on that definition is not known")}
        return {**here, "state": "current",
                "note": "the same text; what changed of its context it does not rest on ("
                        + "; ".join(dict.fromkeys(_context_words(x) for x in ctx)) + ")"}
    if cls == "changed":
        ctx = [_with_change(m, x, lean) for x in row.get("context") or []
               if _relies(x, lean) == "yes"]
        return {**here, "state": "reopened",
                "change": {"class": cls, "reason": row.get("reason"),
                           **{k: v for k, v in (row.get("change") or {}).items()},
                           **({"context": ctx} if ctx else {})}}
    if cls == "removed":
        return {**here, "state": "reopened", "change": {"class": cls, "reason": row.get("reason")}}
    if cls == "ambiguous":
        cands = ", ".join(x["claim"] for x in row.get("candidates") or [])
        return {**here, "state": "unchecked", "candidates": row.get("candidates") or [],
                "why": f"the version map cannot tell which later claim {label} is: "
                       f"{row.get('reason')}" + (f" (candidates: {cands})" if cands else "")
                       + "; the maintainer resolves it with --match"}
    return {**here, "state": "unchecked", "why": row.get("reason") or "the version map cannot "
                                                                     "follow it"}


def _region(m: _Map, reg: dict | None) -> dict | None:
    """What the map says of a region of the paper attached to a requirement, or None when the
    region is of another paper."""
    reg = reg or {}
    if (reg.get("paper") or m.paper) != m.paper:
        return None
    p = m.passages.get(region_key(reg, m.paper))
    where = f"{reg.get('file')}:{reg.get('start_line')}"
    if p is None:
        return {"state": "unchecked", "why": f"the version map was made without the passage at "
                                             f"{where}: make it again with the workspace "
                                             "(`changes --map --workspace ID`)"}
    here = {"earlier": {"location": where}, "later": p.get("to"), "class": p["class"]}
    if p["class"] in ("unchanged", "moved", "later"):
        return {**here, "state": "current", "note": p.get("reason")}
    if p["class"] in ("changed", "context-changed", "removed"):
        return {**here, "state": "reopened",
                "change": {"class": p["class"], "reason": p.get("reason"),
                           **{k: p[k] for k in ("context",) if p.get(k)},
                           **(p.get("change") or {})}}
    return {**here, "state": "unchecked", "why": p.get("reason") or "the version map cannot "
                                                                   "follow it"}


# -- what each record rests on ---------------------------------------------------------------

def _outcome(m: _Map, f: dict, it: dict, lean: dict) -> dict | None:
    dep = it["dependency"]
    if dep == dp.PASSAGE:
        return _passage(m, it.get("claim"), it.get("sha256"), lean)
    if dep == dp.CONTEXT:
        if it.get("region"):
            return _region(m, it["region"])
        p = it.get("passage") or {}
        return _passage(m, p.get("claim"), p.get("sha256"))
    if dep == "paper":
        p = (it.get("ref") or {}).get("paper") or {}
        return _passage(m, p.get("claim"), p.get("sha256"))
    if dep == dp.BRIDGE and it.get("source_sha256"):
        return _passage(m, f["claim"], it["source_sha256"], lean)
    return None


def _dependency_text(it: dict, f: dict) -> str:
    if it["dependency"] == dp.BRIDGE:
        return (f"the passage of {f['claim']} that bridge {it.get('theorem')} for "
                f"{it.get('target')} was checked against")
    if it["dependency"] == "paper":
        p = (it.get("ref") or {}).get("paper") or {}
        return f"the passage of {p.get('claim')} it quotes"
    return dp.item_text(it)


def _what(f: dict) -> str:
    return f"finding {f['id']}" + (f" (on {f['requirement']})" if f.get("requirement") else "")


def _question(f: dict, o: dict, it: dict) -> str:
    """The question a new reading of the finding answers about one reopened part."""
    what = _what(f)
    ch = o.get("change") or {}
    cls = ch.get("class")
    if it["dependency"] == dp.CONTEXT and it.get("region"):
        loc = (o.get("earlier") or {}).get("location")
        role = f"the {it.get('role')} of {it.get('requirement')}"
        if cls == "removed":
            return (f"The passage {what} reads as {role} ({loc}) is not in the later revision: "
                    f"what governs {it.get('requirement')} now?")
        if cls == "context-changed":
            words = "; ".join(_context_words(x) for x in ch.get("context") or [])
            return (f"Does {what} still hold now that {words}, in the passage it reads as {role} "
                    f"({loc})?")
        return f"Does {what} still hold now that the passage it reads as {role} ({loc}) changed?"
    side = o.get("later") or o.get("earlier") or {}
    cid = side.get("claim") or (o.get("earlier") or {}).get("claim") or f["claim"]
    label = _label(side, cid)
    if cls == "removed":
        return (f"{_label(o.get('earlier'), cid)} is not in the later revision: which claim, if "
                f"any, does {what} now concern? A finding is not moved to another claim.")
    if cls == "context-changed":
        return f"Does {what} still hold for {label} now that {ch.get('reason')}?"
    return f"Does {what} still hold for the changed text of {label}?"


def _build(f: dict, records: dict, snap, root, cur: dict, check_facts: bool, texts) -> dict:
    """The rest of what a finding rests on, against the later build: its Lean side, and the
    records edited or re-pinned since it was submitted; what changed (with each changed
    declaration's statement in both builds, when `texts` gives them), and what is not known."""
    res = dp.check(f, records, snap, root, cur, check_facts, skip=PAPER_KINDS)
    changes = []
    for ch in res.get("changes") or []:
        ch = dict(ch)
        ch["words"] = dp.change_text(ch)
        if texts is not None and ch.get("decl"):
            t = texts(ch["decl"])
            if t:
                ch["statement"] = t
        changes.append(ch)
    out = {"state": res["state"], "changes": changes}
    if res.get("unknown"):
        out["unknown"] = res["unknown"]
    return out


def _summary(f: dict, shown: dict | None) -> dict:
    out = {k: f[k] for k in SHOWN if f.get(k) not in (None, "", [])}
    if shown:
        # As `workspace show` gives it: a checked bridge Lean does not check now reads as the
        # auditor's composition.
        for k in ("basis", "recorded_basis", "basis_reason"):
            if shown.get(k) is not None:
                out[k] = shown[k]
    elif out.get("basis") == "checked_bridge":
        out.update(basis="reviewed_composition", recorded_basis="checked_bridge",
                   basis_reason=["no build of the later release to check the bridge against"])
    return out


def _state(paper: list[dict], build: dict | None) -> str:
    states = {o["state"] for o in paper}
    if "reopened" in states or (build or {}).get("state") == "stale":
        return "reopened"
    if "unchecked" in states or (build or {}).get("state") == "unchecked":
        return "unchecked"
    return "current"


def _finding(m: _Map, f: dict, records: dict, snap, root, cur, check_facts, texts,
             shown) -> dict | None:
    deps = dp.of(f, records)
    items = deps.get("items") or []
    lean = _lean_names(items)
    paper = []
    for it in items:
        o = _outcome(m, f, it, lean)
        if o is None:
            continue
        o = {**o, "dependency": it, "text": _dependency_text(it, f)}
        if o["state"] == "reopened":
            o["question"] = _question(f, o, it)
        paper.append(o)
    for u in deps.get("unknown") or []:
        if u.get("dependency") == dp.PASSAGE and m.of_paper(f["claim"]):
            paper.append({"state": "unchecked", "dependency": u,
                          "text": f"the passage of {f['claim']}", "why": u.get("why")})
    if not paper:
        return None
    row = m.earlier.get(f["claim"]) or m.later.get(f["claim"])
    out = {"id": f["id"], "claim": f["claim"], "kinds": deps.get("kinds") or [],
           "finding": _summary(f, shown.get(f["id"]) if shown else None),
           "earlier": _place((row or {}).get("from")) if row else None,
           "later": _place((row or {}).get("to")) if row else None,
           "class": (row or {}).get("class"), "paper": paper}
    if snap is not None:
        out["build"] = _build(f, records, snap, root, cur, check_facts, texts)
        for ch in out["build"]["changes"]:
            ch["question"] = f"Does {_what(f)} still hold now that {ch['words']}?"
    out["state"] = _state(paper, out.get("build"))
    return out


def _record(m: _Map, r: dict, o: dict | None, **extra) -> dict | None:
    if o is None:
        return None
    return {"id": r["id"], "claim": r.get("claim"), **extra, **o}


def regions_of(ws: dict, paper: str) -> list[dict]:
    """The regions of the paper the workspace attaches to requirements (its fragments, not
    removed) and those its findings rest on as they were submitted, for the map to follow."""
    out, seen = [], set()

    def add(reg):
        if isinstance(reg, dict) and (reg.get("paper") or paper) == paper:
            k = region_key(reg, paper)
            if k not in seen:
                seen.add(k)
                out.append(reg)

    from .workspace import current_findings
    recs = ws.get("records") or {}
    for r in recs.values():
        if r.get("kind") == "fragment" and r.get("state") != "removed":
            add(r.get("region"))
    for f in current_findings(ws):
        for it in (dp.of(f, recs).get("items") or []):
            if it["dependency"] == dp.CONTEXT:
                add(it.get("region"))
    return out


def reopen(doc: dict, ws: dict, snap=None, root=None, texts=None, check_facts: bool = False,
           view: dict | None = None) -> dict:
    """The findings in force of the workspace `ws`, the evidence quoting the paper and the
    passages attached to requirements, each judged across the version map `doc`: `reopened`
    (with each part that changed: `change`, the `dependency` it is, and the `question`),
    `unchecked` (with `why`) or `current` (with a `note` when it moved). With `snap`, the build
    of the later release, the rest of what a finding rests on too (`build`: its Lean side, and
    the records edited since it was submitted), with `texts` giving a changed declaration's
    statement in both builds. `view`, the workspace as `workspace.view` shows it
    against that build, gives each finding's basis as shown. A record of another paper is left
    out."""
    if doc.get("schema") != MAP_SCHEMA:
        raise MapError(f"not a version map (schema {doc.get('schema')!r})")
    m = _Map(doc)
    records = ws.get("records") or {}
    if snap is not None and snap.index.get("release") != (doc.get("to") or {}).get("release"):
        snap = None  # the Lean side is checked only against the later release's own build
    cur = {}
    if snap is not None:
        from .workspace import currency
        cur = currency(ws, snap, root, check_facts)
    shown = {}
    for c in ((view or {}).get("claims") or {}).values():
        for f in c.get("findings") or []:
            shown[f["id"]] = f
    from .workspace import current_findings
    findings = []
    for f in sorted(current_findings(ws), key=lambda r: (r.get("claim") or "", r["id"])):
        row = _finding(m, f, records, snap, root, cur, check_facts, texts, shown)
        if row is not None:
            findings.append(row)
    evidence, passages = [], []
    for r in sorted(records.values(), key=lambda r: r["id"]):
        if r.get("kind") == "evidence" and "paper" in (r.get("ref") or {}) and \
                r.get("role") != "rejected":
            p = r["ref"]["paper"]
            row = _record(m, r, _passage(m, p.get("claim"), p.get("sha256")),
                          role=r.get("role"), quote=p.get("quote"))
            if row:
                evidence.append(row)
        elif r.get("kind") == "fragment" and r.get("state") != "removed":
            o = _region(m, r["region"]) if r.get("region") else _passage(
                m, (r.get("passage") or {}).get("claim"), (r.get("passage") or {}).get("sha256"))
            row = _record(m, r, o, requirement=r.get("requirement"), role=r.get("role"),
                          state=r.get("state"))
            if row:
                passages.append(row)
    counts = {s: n for s in STATES if (n := sum(f["state"] == s for f in findings))}
    return {"schema": SCHEMA, "workspace": ws.get("id"), "paper": m.paper,
            "from": doc.get("from"), "to": doc.get("to"),
            "build_checked": snap is not None,
            "counts": counts, "findings": findings, "evidence": evidence, "passages": passages,
            "note": ("A reopened finding stands as it was recorded until a new finding supersedes "
                     "it. A part the map leaves ambiguous or cannot follow is not known to be "
                     "current. Nothing here changes a status.")}


# -- kept with the workspace -----------------------------------------------------------------

def kept(doc: dict) -> dict:
    """The version map as a workspace keeps it: the paper's side (its claims and the passages it
    followed), without the later build's Lean references to paper numbers."""
    return {k: deepcopy(v) for k, v in doc.items() if k not in NOT_KEPT}


def map_key(doc: dict) -> tuple:
    a, b = doc.get("from") or {}, doc.get("to") or {}
    return (doc.get("paper"), a.get("release"), a.get("evidence"), a.get("revision"),
            b.get("release"), b.get("evidence"), b.get("revision"))


def check_map(doc) -> dict:
    """A version map given to keep, checked for form."""
    if not isinstance(doc, dict) or doc.get("schema") != MAP_SCHEMA:
        raise MapError(f"a version map has the schema {MAP_SCHEMA}")
    if not isinstance(doc.get("paper"), str) or not isinstance(doc.get("claims"), list) or \
            not isinstance(doc.get("from"), dict) or not isinstance(doc.get("to"), dict):
        raise MapError("a version map names its paper, both revisions and its claims")
    for r in doc["claims"]:
        if not isinstance(r, dict) or not isinstance(r.get("class"), str):
            raise MapError("each entry of a version map has its class")
    if not isinstance(doc.get("passages") or [], list):
        raise MapError("a version map's passages are a list")
    return kept(doc)


def identity(doc: dict) -> dict:
    """What names a kept map: its paper and both revisions, and who kept it when."""
    side = lambda s: {k: s.get(k) for k in ("release", "evidence", "revision") if s.get(k)}
    return {"paper": doc.get("paper"), "from": side(doc.get("from") or {}),
            "to": side(doc.get("to") or {}),
            **{k: doc[k] for k in ("kept_at", "kept_by") if doc.get(k)}}


def lean_texts(out_dir, doc: dict):
    """A function giving a declaration's statement in the two releases of the map (`{from,
    to}`, as `changes` shows them), or None when the releases cannot be read here."""
    from . import changes as chg
    try:
        _, a, _, b = chg.records(out_dir, (doc.get("from") or {}).get("release"),
                                 (doc.get("to") or {}).get("release"))
        old, new = chg.Version(a, "from"), chg.Version(b, "to")
    except (chg.ChangesError, OSError, KeyError, TypeError, ValueError):
        return None

    def texts(name: str) -> dict | None:
        x, y = old.decl(name), new.decl(name)
        out = {k: v.get("text") for k, v in (("from", x), ("to", y)) if v and v.get("text")}
        return out or None
    return texts


def for_site(ws: dict, snap, root=None, out_dir=None, check_facts: bool = False,
             view: dict | None = None) -> dict:
    """The findings each version map the workspace keeps reopens, for the maps to the release of
    the build `snap` (each map's Lean side checked against it); the other maps it keeps are
    named (`other`)."""
    release = snap.index.get("release") if snap is not None else None
    maps, other = [], []
    for doc in ws.get("version_maps") or []:
        if release is not None and (doc.get("to") or {}).get("release") == release:
            texts = lean_texts(out_dir, doc) if out_dir is not None else None
            maps.append({**reopen(doc, ws, snap, root, texts, check_facts, view),
                         "map": identity(doc)})
        else:
            other.append(identity(doc))
    return {"schema": "prooflens/reopened-list@1", "workspace": ws.get("id"), "release": release,
            "maps": maps, "other": other}


# -- text ------------------------------------------------------------------------------------

def _side_words(s: dict | None) -> str:
    s = s or {}
    if s.get("release"):
        return f"release {s['release']}"
    return f"revision {s.get('revision') or 'not recorded'}"


def _diff_lines(ch: dict, pad: str) -> list[str]:
    out = [pad + ln for ln in ch.get("diff") or []]
    for x in ch.get("context") or []:
        out += [pad + ln for ln in x.get("diff") or []]
        out += [pad + ln for ln in (x.get("claim_change") or {}).get("diff") or []]
    return out


def lines(doc: dict) -> list[str]:
    """The findings a version map reopens, for the terminal."""
    counts = doc.get("counts") or {}
    head = (f"workspace {doc.get('workspace')} across paper {doc.get('paper')} from "
            f"{_side_words(doc.get('from'))} to {_side_words(doc.get('to'))}: "
            + (", ".join(f"{n} finding(s) {STATE_WORDS[s]}" for s, n in counts.items())
               or "no finding rests on this paper"))
    out = [head]
    if not doc.get("build_checked"):
        out.append("  the Lean is not checked here: no site of the later release (run "
                   "`machinechecked site --release "
                   f"{(doc.get('to') or {}).get('release')}`)")
    for f in doc.get("findings") or []:
        e, l = f.get("earlier") or {}, f.get("later") or {}
        where = f"{e.get('number') or f['claim']}" + (
            f" -> {l.get('number') or l.get('claim')}" if l and (l.get("number"), l.get("claim"))
            != (e.get("number"), e.get("claim")) else "")
        out.append(f"  finding {f['id']} ({f['claim']}, {where}): {STATE_WORDS[f['state']]}")
        for o in f["paper"]:
            if o["state"] == "reopened":
                word = "removed" if o["change"].get("class") == "removed" else "changed"
                out.append(f"    {word}: {o['text']}: {o['change'].get('reason')}")
                out += _diff_lines(o["change"], "      ")
                out.append(f"    question: {o['question']}")
            elif o["state"] == "unchecked":
                out.append(f"    not known: {o['text']}: {o.get('why')}")
            elif o.get("note"):
                out.append(f"    current: {o['text']}: {o['note']}")
        build = f.get("build") or {}
        for ch in build.get("changes") or []:
            out.append(f"    changed in the later build: {ch['words']}")
            for side, word in (("from", "was"), ("to", "now")):
                t = (ch.get("statement") or {}).get(side)
                if t:
                    out.append(f"      {word}: " + t.replace("\n", "\n           "))
        for u in build.get("unknown") or []:
            out.append(f"    not known in the later build: {u.get('why')}")
    for r in doc.get("evidence") or []:
        if r["state"] != "current":
            quoted = (r.get("earlier") or {}).get("claim")
            out.append(f"  evidence {r['id']} ({r['claim']}"
                       + (f", quoting {quoted}" if quoted and quoted != r["claim"] else "")
                       + f"): {STATE_WORDS[r['state']]}: "
                       + ((r.get("change") or {}).get("reason") or r.get("why") or ""))
    for r in doc.get("passages") or []:
        if r["state"] != "current":
            out.append(f"  passage {r['id']} ({r.get('role')} of {r.get('requirement')}, "
                       f"{(r.get('earlier') or {}).get('location') or r['claim']}): "
                       f"{STATE_WORDS[r['state']]}: "
                       + ((r.get("change") or {}).get("reason") or r.get("why") or ""))
    out.append("  " + doc["note"])
    return out
