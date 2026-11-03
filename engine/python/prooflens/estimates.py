"""Estimates read with their quantifiers and constants, the differences an auditor records
between the paper and the Lean, and candidate counterexamples with their Lean certificates.

The reading of an estimate is computed from a claim's requirements (`requirements.py`): the
requirements around it give the order in which its variables are chosen, their domains, and each
constant's allowed dependence. A constant stated independent of a variable is chosen before it,
so "for every ε > 0, … with C independent of ε" reads as "there is C; for every ε > 0". A
correction of one of these requirements gives a separate reading; the printed one stays.

A difference is a finding on the affected requirement: the feature compared (a domain, the order
of quantifiers, a constant's dependence, a derivative order, …), the exact paper and Lean
expressions, and what the auditor concluded: still open, a difference, resolved by a stated
transport (a common extension, a checked bridge, an argument), or no difference at all. A
resolution that names some of the difference's conditions resolves those only; the others stay
open. A checked bridge is a theorem whose type is exactly a target proposition: Lean checks it
(`check`) when it is recorded, and it is refused otherwise; it is pinned to the target and the
claim's passage as they were then. It reads as resolving the difference only while Lean checks it
now (`resolution_check`); otherwise as recorded as resolved, with what Lean does not check.

A counterexample is an auditor's record against one reading of a requirement: its
specialisation (values for the variables, channels set to zero, dimensions, limits), the
reduced obligation and its violation, and the admissibility obligations it still has to meet.
Its values may be symbolic: `ε = C + 1` for every `C` is a family over the constants the reading
lets the auditor not choose. Only a family (or, when the reading has no constant, an instance)
can show that every constant fails; numeric samples are kept as samples and never do. A
certificate is a Lean declaration whose type is exactly a target proposition or its negation,
checked through the probe as a checked bridge is; it certifies that proposition, not the
reading it is attached to.

All of this is a reading. Nothing here is an input to a status: a refuted printed step is a
finding on the step, and its enclosing result keeps its own evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path

FEATURES = ("domain", "quantifier order", "constant dependence", "derivative order", "norm",
            "power", "weight", "index offset", "additional assumption", "lost case",
            "stronger conclusion", "representation", "other")
OUTCOMES = ("open", "difference", "resolved", "no difference")
RESOLVED_BY = ("common extension", "checked bridge", "argument", "inherited assumption",
               "renaming")
# An apparent difference of these features may be carried away by a transport (an extension, a
# bridge, the full theorem): a difference of them states what transport was inspected.
TRANSPORT_FEATURES = ("domain", "representation", "additional assumption")
ADMISSIBILITY = ("verified", "open", "fails")
CERTIFIES = ("refutes", "proves")
SAMPLES_KEPT = 1000

OUTCOME_WORDS = {"open": "not yet decided", "difference": "a difference",
                 "resolved": "resolved", "no difference": "no difference"}
STANDING_WORDS = {
    "admissible counterexample": "an admissible counterexample to this reading",
    "candidate": "a candidate counterexample: not yet shown admissible",
    "not admissible": "not admissible: it violates an assumption of the reading",
    "illustration": "numeric samples only: they show that the values tried fail, not that every "
                    "constant fails",
    "incomplete": "incomplete: it does not give each variable a value the reading allows"}
SAMPLES_NOTE = ("Numeric samples show only the values tried. They never show that every "
                "constant fails; a symbolic family does.")


def _err(msg: str):
    from .workspace import WorkspaceError
    return WorkspaceError(msg)


def _text(v, what, required=False):
    from .workspace import _text as t
    return t(v, what, required)


def _choice(v, allowed, what, optional=True):
    from .workspace import _choice as c
    return c(v, allowed, what, optional)


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False)
                          .encode()).hexdigest()


def _texts(v, what) -> list[str]:
    if v in (None, []):
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
        raise _err(f"{what} is a list of texts")
    return [_text(x, what).strip() for x in v]


# -- differences ---------------------------------------------------------------------------

DIFF_KEYS = ("feature", "paper", "lean", "outcome", "conditions", "transport", "resolution",
             "why", "hint")
RESOLUTION_KEYS = ("by", "text", "theorem", "target", "module", "conditions")
# What a checked bridge keeps of Lean's check when it is recorded.
BRIDGE_PINS = ("module", "file", "file_sha256", "type", "axioms", "target_fingerprint",
               "source_sha256", "checked_at")
BRIDGE = "checked bridge"


def difference_content(d, cur: dict | None = None, repin: bool = False, snap=None,
                       root: Path | None = None, claim: str | None = None) -> dict:
    """A difference as a finding records it, checked. A resolution by a checked bridge is
    checked by Lean now against the claim's passage in `snap` (`_bridge_pins`), unless `cur`, the
    difference being replaced, holds the same bridge and it is not re-pinned."""
    if not isinstance(d, dict):
        raise _err("a difference is {feature, paper, lean, outcome, …}")
    extra = set(d) - set(DIFF_KEYS)
    if extra:
        raise _err(f"a difference has no field {', '.join(sorted(extra))}")
    out = {"feature": _choice(d.get("feature"), FEATURES, "the feature compared", False),
           "paper": _text(d.get("paper"), "the paper's expression (`paper`)", True),
           "outcome": _choice(d.get("outcome") or "open", OUTCOMES, "the outcome", False)}
    if d.get("lean") not in (None, ""):
        out["lean"] = _text(d["lean"], "the Lean expression (`lean`)")
    conds = _texts(d.get("conditions"), "`conditions`")
    if conds:
        out["conditions"] = conds
    if d.get("transport") not in (None, ""):
        out["transport"] = _text(d["transport"], "the transport inspected (`transport`)")
    if out["outcome"] == "difference" and out["feature"] in TRANSPORT_FEATURES and \
            not out.get("transport"):
        raise _err(f"a {out['feature']} difference says what transport was inspected first "
                   "(`transport`: a common extension, a bridge, the full theorem), so that a "
                   "change of representation is not recorded as a defect")
    res = d.get("resolution")
    if out["outcome"] == "resolved":
        if not isinstance(res, dict):
            raise _err("a resolved difference names its resolution (`resolution`: {by, text})")
        extra = set(res) - set(RESOLUTION_KEYS) - set(BRIDGE_PINS)
        if extra:
            raise _err(f"a resolution has no field {', '.join(sorted(extra))}")
        r = {"by": _choice(res.get("by"), RESOLVED_BY, "the resolution", False),
             "text": _text(res.get("text"), "how it resolves the difference (`text`)", True)}
        for k in ("theorem", "target", "module"):
            if res.get(k) not in (None, ""):
                r[k] = _text(res[k], f"the bridge's {k}").strip()
        named = list(dict.fromkeys(_texts(res.get("conditions"), "`resolution.conditions`")))
        for c in named:
            if c not in conds:
                raise _err(f"“{c}” is not one of the difference's conditions: a resolution "
                           "names the conditions it resolves (`resolution.conditions`)")
        if named:
            r["conditions"] = named
        if r["by"] == BRIDGE:
            if not (r.get("theorem") and r.get("target")):
                raise _err("a checked bridge names its theorem and the target proposition its "
                           "type states exactly (`resolution.theorem`, `resolution.target`)")
            if conds and not named:
                raise _err("a checked bridge resolves only the conditions it names: name them "
                           "(`resolution.conditions`); the difference's others stay open")
            old = ((cur or {}).get("resolution") or {}) \
                if (cur or {}).get("outcome") == "resolved" else {}
            r.update(_bridge_pins(r, old, repin, snap, root, claim))
        elif any(k in r for k in ("target", "module")) or set(res) & set(BRIDGE_PINS):
            raise _err("only a checked bridge has a target and what Lean checked")
        out["resolution"] = r
    elif res is not None:
        raise _err("only a resolved difference has a resolution")
    if out["outcome"] == "no difference":
        out["why"] = _text(d.get("why"), "why there is no difference (`why`)", True)
    elif d.get("why") not in (None, ""):
        raise _err("`why` belongs to a difference whose outcome is `no difference`")
    if d.get("hint") is not None:
        out["hint"] = hint_ref(d["hint"])
    return out


def _bridge_pins(r: dict, old: dict, repin: bool, snap, root, claim: str | None) -> dict:
    """What a checked bridge keeps of Lean's check: Lean checks now that the type of its theorem
    is exactly its target, a proposition stated as a definition, with no `sorry` and only the
    standard axioms (`check`), and the bridge is pinned to the target as Lean has it and to the
    claim's passage. A bridge Lean does not check is refused. One already recorded keeps the
    versions it was checked at until it is re-pinned."""
    if not repin and old.get("by") == BRIDGE and old.get("checked_at") and \
            (old.get("theorem"), old.get("target")) == (r["theorem"], r["target"]) and \
            r.get("module") in (None, old.get("module")):
        return {k: old[k] for k in BRIDGE_PINS if k in old}
    lroot = lean_root(root)
    if lroot is None or snap is None or not claim:
        raise _err("a checked bridge is checked by Lean when it is recorded, against the claim's "
                   "passage: it needs the Lean project and its build")
    from .simple import ViewError
    thm, target = r["theorem"], r["target"]
    try:
        doc = check(lroot, thm, target, "proves", r.get("module"))
    except ViewError as e:
        raise _err(f"the bridge {thm} for {target} was not checked: {e}") from None
    if not doc.get("ok") or doc.get("status") != "checked":
        why = doc.get("reasons") or [doc.get("reason") or doc.get("status")]
        raise _err(f"the bridge {thm} for {target} is refused: " + "; ".join(map(str, why)))
    import datetime as _dt
    pins = {"module": doc.get("module"), "file": doc.get("file"),
            "file_sha256": doc.get("file_sha256"), "type": doc.get("type"),
            "axioms": doc.get("axioms") or [], "target_fingerprint": doc.get("target_fingerprint"),
            "source_sha256": (snap.chunk(claim) or {}).get("source_sha256"),
            "checked_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return {k: v for k, v in pins.items() if v is not None}


def is_bridge(d: dict | None) -> bool:
    """Whether a difference is recorded as resolved by a checked bridge."""
    return (d or {}).get("outcome") == "resolved" and \
        ((d or {}).get("resolution") or {}).get("by") == BRIDGE


def resolution_check(d: dict | None, claim: str, snap, root, check_now: bool = False) \
        -> dict | None:
    """Whether Lean checks now the checked bridge a difference is resolved by, or None for a
    difference not resolved by one: `checked` (the type of its theorem is exactly its target, a
    proposition stated as a definition, with no `sorry` and only the standard axioms, and the
    target and the claim's passage are the versions it was recorded with), `stale` (Lean checks
    it, but the target or the passage changed since), or `unchecked`, each with `reasons`. The
    answer is read from the facts store, or asked of Lean when `check_now` is set; without `snap`
    the passage is not compared."""
    if not is_bridge(d):
        return None
    res = d["resolution"]
    out = {"theorem": res.get("theorem"), "target": res.get("target"), "state": "unchecked",
           "reasons": []}
    if not (res.get("theorem") and res.get("target")):
        out["reasons"].append("no theorem and target proposition are recorded for it")
        return out
    if not (res.get("checked_at") and res.get("target_fingerprint")):
        out["reasons"].append("Lean did not check it when it was recorded")
        return out
    lroot = lean_root(root)
    if lroot is None:
        out["reasons"].append("no Lean project to check the bridge against")
        return out
    from .deps import NOT_CHECKED, not_checked_reason
    from .simple import ViewError
    try:
        doc = check(lroot, res["theorem"], res["target"], "proves", res.get("module"),
                    cached_only=not check_now)
    except ViewError as e:
        out["reasons"].append(str(e))
        return out
    if not doc.get("ok") or doc.get("status") != "checked":
        if doc.get("status") in NOT_CHECKED:
            out["reasons"].append(not_checked_reason(res["theorem"], doc))
        else:
            out["reasons"] += [str(x) for x in doc.get("reasons") or []] or \
                [doc.get("reason") or str(doc.get("status"))]
        return out
    why = out["reasons"]
    if doc.get("target_fingerprint") != res.get("target_fingerprint"):
        why.append("the target is not the version the auditor read")
    if snap is not None:
        from .dependencies import unprinted
        ch = snap.chunk(claim)
        passage = None if ch is None or unprinted(ch, claim) else ch.get("source_sha256")
        if passage != res.get("source_sha256"):
            why.append("the paper's passage is not the version the auditor read")
    out["state"] = "stale" if why else "checked"
    return out


def open_conditions(d: dict | None) -> list[str]:
    """The conditions of a resolved difference that its resolution does not name: they stay
    open. A resolution that names none resolves the difference as a whole."""
    d = d or {}
    named = (d.get("resolution") or {}).get("conditions") or []
    if d.get("outcome") != "resolved" or not named:
        return []
    return [c for c in d.get("conditions") or [] if c not in named]


def difference_view(d: dict, chk: dict | None) -> dict:
    """A recorded difference as it is shown: for a resolution by a checked bridge, whether Lean
    checks the bridge now (`bridge_check`, from `resolution_check`; a check not given reads as
    unchecked), and the conditions its resolution leaves open (`open_conditions`, and `partial`).
    """
    out = dict(d)
    if is_bridge(d):
        c = chk or {"state": "unchecked", "reasons": ["Lean's check of the bridge is not known"]}
        out["bridge_check"] = {"state": c.get("state") or "unchecked",
                               "reasons": list(c.get("reasons") or [])}
    left = open_conditions(d)
    if left:
        out.update(open_conditions=left, partial=True)
    return out


def settled(dv: dict) -> bool:
    """Whether a difference as shown (`difference_view`) is settled now: found to be none, or
    resolved as a whole by a resolution that holds now (a checked bridge only while Lean checks
    it)."""
    if dv.get("outcome") == "no difference":
        return True
    return dv.get("outcome") == "resolved" and not dv.get("partial") and \
        (dv.get("bridge_check") or {"state": "checked"})["state"] == "checked"


def _conditions_words(cs: list[str]) -> str:
    return ("the condition " if len(cs) == 1 else "the conditions ") + ", ".join(cs)


def outcome_text(dv: dict) -> str:
    """A difference's outcome as shown (`difference_view`), in words: a resolution by a checked
    bridge Lean does not check now is recorded, not holding, and one that leaves conditions open
    resolves the difference in part."""
    if dv.get("outcome") == "resolved":
        if (dv.get("bridge_check") or {"state": "checked"})["state"] != "checked":
            return "recorded as resolved; Lean does not check its bridge now"
        if dv.get("partial"):
            return "resolved in part"
    return OUTCOME_WORDS.get(dv.get("outcome"), str(dv.get("outcome")))


def resolution_text(dv: dict) -> str | None:
    """How a difference as shown (`difference_view`) is resolved, in words; None without a
    resolution. A checked bridge Lean does not check now reads as recorded, with why."""
    r = dv.get("resolution")
    if not r:
        return None
    named = r.get("conditions") or []
    where = f" for {_conditions_words(named)}" if named else ""
    left = dv.get("open_conditions") or []
    still = (f"; still open: {_conditions_words(left)}" if left else
             "; some of its conditions are still open" if dv.get("partial") else "")
    b = dv.get("bridge_check")
    if b and b.get("state") != "checked":
        why = "; ".join(b.get("reasons") or []) or "it is not checked"
        return (f"recorded as resolved by a checked bridge{where}; Lean does not check it now: "
                f"{why}{still}")
    return f"resolved by {r.get('by')}{where}" + (f": {r['text']}" if r.get("text") else "") + \
        still


def hint_ref(h) -> dict:
    """The computed hint a difference settles (`hint`): `{decl, binder}`, a hypothesis no
    requirement is aligned with, or `{alignment, kind}`, a hint an alignment's paper expression
    gives (`EXPRESSION_HINTS`) or the order of its variables (`ORDER_HINTS`), as the reading
    lists them."""
    if isinstance(h, dict) and "alignment" in h:
        if set(h) - {"alignment", "kind"} or not isinstance(h["alignment"], str) or \
                h.get("kind") not in ALIGNMENT_HINTS:
            raise _err("a hint of an alignment is {alignment, kind}, `kind` one of "
                       + ", ".join(ALIGNMENT_HINTS) + ", as the reading lists it")
        return {"alignment": h["alignment"], "kind": h["kind"]}
    if not isinstance(h, dict) or not isinstance(h.get("decl"), str) or \
            type(h.get("binder")) is not int:
        raise _err("a hint is {decl, binder} or {alignment, kind}, as the reading lists it")
    return {"decl": h["decl"], "binder": h["binder"]}


# -- counterexamples -----------------------------------------------------------------------

SPEC_KEYS = ("assign", "zero", "dimensions", "limits", "other")


def _specialisation(s) -> dict:
    if not isinstance(s, dict) or not s:
        raise _err("a specialisation is {assign, zero, dimensions, limits, other}")
    extra = set(s) - set(SPEC_KEYS)
    if extra:
        raise _err(f"a specialisation has no field {', '.join(sorted(extra))}")
    out = {}
    for k in ("assign", "dimensions"):
        v = s.get(k)
        if v in (None, {}):
            continue
        if not isinstance(v, dict) or not all(isinstance(n, str) and n.strip() for n in v) or \
                not all(isinstance(x, (str, int, float)) and not isinstance(x, bool)
                        and str(x).strip() for x in v.values()):
            raise _err(f"`{k}` maps each variable to its value (a number or an expression)")
        out[k] = {n.strip(): (x.strip() if isinstance(x, str) else x) for n, x in v.items()}
    for k in ("zero", "limits", "other"):
        t = _texts(s.get(k), f"`{k}`")
        if t:
            out[k] = t
    if not out:
        raise _err("a specialisation gives at least one value, channel, dimension or limit")
    return out


def _samples(v) -> list[dict]:
    if v in (None, []):
        return []
    if not isinstance(v, list) or len(v) > SAMPLES_KEPT or not all(
            isinstance(x, dict) and x and all(isinstance(n, str) for n in x) and
            all(isinstance(y, (int, float)) and not isinstance(y, bool) for y in x.values())
            for x in v):
        raise _err(f"`samples` is a list of at most {SAMPLES_KEPT} numeric assignments")
    return [dict(x) for x in v]


def _admissibility(v) -> list[dict]:
    if v in (None, []):
        return []
    if not isinstance(v, list):
        raise _err("`admissibility` is a list of {obligation, state, method}")
    out = []
    for a in v:
        if not isinstance(a, dict) or set(a) - {"obligation", "state", "method"}:
            raise _err("an admissibility obligation is {obligation, state, method}")
        item = {"obligation": _text(a.get("obligation"), "the obligation", True),
                "state": _choice(a.get("state") or "open", ADMISSIBILITY, "its state", False)}
        if a.get("method") not in (None, ""):
            item["method"] = _text(a["method"], "how it was verified (`method`)")
        if item["state"] != "open" and not item.get("method"):
            raise _err(f"“{item['obligation']}” is {item['state']}: say how (`method`)")
        out.append(item)
    return out


def corrections_of(ws_records, claim: str, ids) -> list[str]:
    """The correction requirements a reading applies, checked."""
    from .requirements import _requirements
    if ids in (None, []):
        return []
    if not isinstance(ids, list):
        raise _err("`reading` lists the corrections it applies, by local id")
    reqs = _requirements({"records": ws_records}, claim)
    out = []
    for lid in ids:
        r = reqs.get(lid) if isinstance(lid, str) else None
        if r is None or r.get("origin") != "correction":
            raise _err(f"{lid!r} is not a correction of {claim} in this workspace")
        out.append(lid)
    return list(dict.fromkeys(out))


def counterexample_content(out: dict, rec: dict, ws: dict, cur: dict | None,
                           repin: bool) -> dict:
    from .requirements import known_requirement
    out["requirement"] = known_requirement(ws, out["claim"], rec.get("requirement"))
    reading = corrections_of(ws["records"], out["claim"], rec.get("reading"))
    if reading:
        out["reading"] = reading
    out["specialisation"] = _specialisation(rec.get("specialisation"))
    out["reduced"] = _text(rec.get("reduced"), "the reduced obligation (`reduced`)", True)
    out["violation"] = _text(rec.get("violation"), "the violation (`violation`)", True)
    adm = _admissibility(rec.get("admissibility"))
    if adm:
        out["admissibility"] = adm
    samples = _samples(rec.get("samples"))
    if samples:
        out["samples"] = samples
    recs = [r for r in ws["records"].values() if r.get("claim") == out["claim"]]
    ob = obligation(recs, out["requirement"], reading)
    keep = cur is not None and not repin and cur.get("requirement") == out["requirement"] and \
        (cur.get("reading") or []) == reading
    # The record keeps the reading it was made against until it is re-pinned: a changed reading
    # makes it stale, never silently rebinds it.
    out["obligation_sha256"] = cur.get("obligation_sha256") if keep else ob["sha256"]
    ev = {e: evidence_pin(ws["records"].get(e) or {}) for e in out.get("evidence") or []}
    if keep and not repin:
        ev = {e: (cur.get("evidence_pins") or {}).get(e, p) for e, p in ev.items()}
    if ev:
        out["evidence_pins"] = ev
    return out


def evidence_pin(e: dict) -> str:
    return digest(e.get("ref") or {})


def counterexample_pin(c: dict) -> str:
    """A digest of what a counterexample says: its reading, specialisation, reduction,
    violation, admissibility and the evidence it cites."""
    return digest({k: c.get(k) for k in ("requirement", "reading", "specialisation", "reduced",
                                          "violation", "admissibility", "samples", "evidence",
                                          "obligation_sha256", "evidence_pins")})


def finding_fields(out: dict, rec: dict, ws: dict, cur: dict | None, repin: bool, snap=None,
                   root: Path | None = None) -> None:
    """The fields a finding adds for an estimate: a structured difference (a checked bridge it is
    resolved by checked by Lean in the project at `root`, against the build `snap`), a verdict on
    a printed step, and the counterexamples it rests on (pinned as they were)."""
    from .steps import STATE
    if rec.get("difference") is not None:
        out["difference"] = difference_content(rec["difference"], (cur or {}).get("difference"),
                                               repin, snap, root, out["claim"])
        if not out.get("requirement"):
            raise _err("a difference is attached to the requirement it affects (`requirement`)")
        _hint_alignment(out, ws)
    if rec.get("verdict") not in (None, ""):
        out["verdict"] = _choice(rec["verdict"], tuple(STATE), "the verdict", False)
    cxs = rec.get("counterexamples")
    if cxs not in (None, []):
        if not isinstance(cxs, list):
            raise _err("`counterexamples` lists counterexample record ids")
        pins = {}
        old = {p["id"]: p["sha256"] for p in (cur or {}).get("counterexamples") or []}
        for c in dict.fromkeys(cxs):
            r = ws["records"].get(c) if isinstance(c, str) else None
            if not r or r.get("kind") != "counterexample" or r.get("claim") != out["claim"]:
                raise _err(f"{c} is not a counterexample of {out['claim']} in this workspace")
            pins[c] = old[c] if c in old and not repin else counterexample_pin(r)
        out["counterexamples"] = [{"id": c, "sha256": s} for c, s in pins.items()]


def _hint_alignment(out: dict, ws: dict) -> None:
    """A difference that settles an alignment's hint names an alignment of its claim."""
    aid = (out["difference"].get("hint") or {}).get("alignment")
    if aid is None:
        return
    a = ws["records"].get(aid)
    if not a or a.get("kind") != "alignment" or a.get("claim") != out["claim"]:
        raise _err(f"{aid} is not an alignment of {out['claim']} in this workspace")


# -- certificates ----------------------------------------------------------------------------

CERT_KEPT = ("theorem", "target", "certifies", "module", "file", "file_sha256", "type",
             "target_statement", "target_fingerprint", "axioms", "lean", "toolchain",
             "manifest_sha256", "result", "reasons")
CERT_KIND = "certificate"  # the facts store's kind for these answers
CERT_ERRORS = {"missing": "Lean finds no such theorem", "not-a-theorem": "it is not a theorem",
               "type-not-spec": "its type is not exactly the target",
               "type-not-negated-spec": "its type is not exactly the negation of the target"}


def lean_root(root: Path | None) -> Path | None:
    """The Lean project of a workspace's project: `root` itself when it has a lakefile, else the
    `lean_root` of its MachineChecked configuration."""
    if root is None:
        return None
    root = Path(root)
    if any((root / f).exists() for f in ("lakefile.toml", "lakefile.lean")):
        return root
    from . import config as cfgmod
    for name in cfgmod.CONFIG_NAMES:
        if (root / name).exists():
            try:
                return cfgmod.load(root / name).lean_root
            except Exception:  # an unreadable configuration has no Lean project to offer
                return None
    return None


def _file_digest(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def check(root: Path, theorem: str, target: str, certifies: str, module: str | None = None,
          lake: str = "lake", refresh: bool = False, cached_only: bool = False) -> dict:
    """Whether Lean checks the certificate `theorem` for `target`: its type is exactly `target`
    (`proves`) or its negation (`refutes`), with no `sorry` and only the standard axioms, and the
    target is a proposition stated as a definition. The answer carries the checked type, the
    target's statement and fingerprint (over the project definitions it uses) and the Lean
    version, and is kept in the facts store until the modules it was read from change."""
    from .deps import _resolve, _short, store
    from .facts import graphs
    from .probe import lib_names
    from .simple import (ViewError, built_modules, module_failed_detail, probe_modules,
                         target_fingerprint)
    from .config import work_dir_name
    libs = lib_names(root)
    if not libs:
        raise ViewError("no Lean library found in the lakefile")
    built, unbuilt = built_modules(root, libs)
    mod, answer = _resolve(root, theorem, module, built, unbuilt)
    if answer is not None:
        return {"ok": False, **answer}
    if mod is None:
        return {"ok": False, "status": "not found",
                "reason": f"no module of the project declares {theorem}; give its module"}
    st = store(root, libs)
    key = f"{theorem}\0{target}\0{certifies}\0{mod}"
    if not refresh:
        entry, _ = st.get(CERT_KIND, key)
        if entry is not None:
            return {**entry["body"], "cache": {"hit": True, "key": _short(key)}}
    if cached_only:
        return {"ok": False, "status": "not checked",
                "reason": "the certificate has not been checked since the Lean last changed"}
    with st.lock(None):
        entry, _ = (None, None) if refresh else st.get(CERT_KIND, key)
        if entry is not None:
            return {**entry["body"], "cache": {"hit": True, "key": _short(key)}}
        request = [{"kind": "refute" if certifies == "refutes" else "accept", "name": theorem,
                    "spec": target}, {"kind": "link", "name": target},
                   {"kind": "modules", "name": ""}]
        recs, failed = probe_modules(root, [mod], libs, request, lake, log=lambda m: None,
                                     work=root / work_dir_name(root) / "build")
        if failed:
            raise ViewError(module_failed_detail(mod, failed[mod], root=root))
        env = st.environment([mod], next(iter(graphs(recs).values()), {}))
        pr = next((r for r in recs if r.get("record") in ("refute", "accept")
                   and r.get("name") == theorem), None)
        link = next((r for r in recs if r.get("record") == "link" and r.get("name") == target),
                    None)
        errors = list((pr or {}).get("errors") or []) + list((link or {}).get("errors") or [])
        if any(str(e).startswith("probe-error") for e in errors):
            return {"ok": False, "status": "probe error", "reason": str(errors[0])}
        reasons = []
        for e in (pr or {"errors": ["missing"]}).get("errors") or []:
            reasons.append(CERT_ERRORS.get(e) or ("its axioms are not all allowed"
                                                  if str(e).startswith("axioms=") else str(e)))
        if (pr or {}).get("sorry"):
            reasons.append("its proof uses sorry")
        if link is None or "missing" in (link.get("errors") or []):
            reasons.append("Lean finds no such target")
        elif link.get("kind") != "def" or \
                ((link.get("decl") or {}).get("signature") or {}).get("text") != "Prop":
            reasons.append("the target is not a proposition stated as a definition")
        decls = {r["name"]: r for r in recs if r.get("record") == "decl" and r.get("name")}
        env_rec = next((r for r in recs if r.get("record") == "env"), {})
        file = mod.replace(".", "/") + ".lean"
        body = {"ok": True, "status": "checked" if not reasons else "failed",
                "theorem": theorem, "target": target, "certifies": certifies, "module": mod,
                "file": file, "file_sha256": _file_digest(root / file),
                "type": ((pr or {}).get("type") or {}).get("text"),
                "range": (pr or {}).get("range"), "axioms": (pr or {}).get("axioms") or [],
                "target_statement": (((link or {}).get("decl") or {}).get("value") or {})
                .get("text"),
                "target_fingerprint": target_fingerprint(link, decls),
                "lean": {"version": env_rec.get("lean"), "githash": env_rec.get("githash")},
                "toolchain": _read(root / "lean-toolchain"),
                "manifest_sha256": _file_digest(root / "lake-manifest.json"),
                "result": "checked" if not reasons else "failed", "reasons": reasons}
        st.put(CERT_KIND, key, env, body=body)
    return {**body, "cache": {"hit": False, "key": _short(key)}}


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def certificate_ref(c, root) -> dict:
    """A certificate as an evidence record cites it (`certificate`: `{theorem, target,
    certifies, module?}`). With the Lean project it is checked now, and kept with what Lean
    checked; without one it carries those pins itself and stays unchecked until checked."""
    if not isinstance(c, dict) or not all(isinstance(c.get(k), str) and c[k].strip()
                                          for k in ("theorem", "target")):
        raise _err("a certificate is {theorem, target, certifies} (`certifies`: refutes when "
                   "its type is the negation of the target, proves when it is the target)")
    certifies = _choice(c.get("certifies"), CERTIFIES, "what it certifies (`certifies`)", False)
    base = {"theorem": c["theorem"].strip(), "target": c["target"].strip(),
            "certifies": certifies}
    if c.get("module"):
        base["module"] = _text(c["module"], "the module").strip()
    lroot = lean_root(root)
    if lroot is None:
        kept = {k: c[k] for k in CERT_KEPT if c.get(k) is not None}
        if not (kept.get("type") and kept.get("target_fingerprint")):
            raise _err("without the Lean project a certificate carries what Lean checked "
                       "(its type and target_fingerprint)")
        return {**kept, **base}
    from .simple import ViewError
    try:
        doc = check(lroot, base["theorem"], base["target"], certifies, base.get("module"))
    except ViewError as e:
        raise _err(str(e)) from None
    if not doc.get("ok"):
        raise _err(f"{base['theorem']}: {doc.get('status')}"
                   + (f": {doc['reason']}" if doc.get("reason") else ""))
    return {k: doc[k] for k in CERT_KEPT if doc.get(k) is not None}


def certificate_scope(ref: dict) -> str:
    """What a certificate establishes, in words."""
    what = "the negation of" if ref.get("certifies") == "refutes" else "exactly"
    stmt = f" ({ref['target_statement']})" if ref.get("target_statement") else ""
    if ref.get("result") == "failed":
        return (f"Lean does not check {ref.get('theorem')} as a certificate for "
                f"{ref.get('target')}: {'; '.join(ref.get('reasons') or [])}")
    return (f"Lean checks that the type of {ref.get('theorem')} is {what} {ref.get('target')}"
            f"{stmt}. It certifies that proposition only, not the reading it is attached to.")


def certificate_currency(root: Path | None, ref: dict, check_now: bool = False) -> dict:
    """Whether a certificate is still what was recorded: its source file, its checked type, its
    target's statement and fingerprint and the result. A changed source file is seen without
    Lean; the rest is read from the facts store, or asked of Lean when `check_now` is set. An
    answer that says Lean did not look (its module is not built, the request failed) leaves the
    rest unchecked."""
    from .deps import NOT_CHECKED, not_checked_reason
    lroot = lean_root(root)
    if lroot is None:
        return {"state": "unchecked", "changes": [], "reason": "no Lean project to check against"}
    changes = []
    if ref.get("file"):
        now = _file_digest(lroot / ref["file"])
        if now != ref.get("file_sha256"):
            changes.append({"certificate": ref.get("theorem"), "file": ref["file"],
                            "was": ref.get("file_sha256"), "now": now,
                            "reason": "the certificate's source changed"})
    from .simple import ViewError
    try:
        doc = check(lroot, ref["theorem"], ref["target"], ref.get("certifies", "proves"),
                    ref.get("module"), cached_only=not check_now)
    except ViewError as e:
        return {"state": "stale" if changes else "unchecked", "changes": changes,
                "reason": str(e)}
    if not doc.get("ok"):
        if doc.get("status") in NOT_CHECKED:
            return {"state": "stale" if changes else "unchecked", "changes": changes,
                    "reason": not_checked_reason(ref.get("theorem"), doc)}
        changes.append({"certificate": ref.get("theorem"), "reason": doc.get("status")})
    else:
        for k, why in (("type", "the checked proposition changed"),
                       ("target_fingerprint", "the target or a definition it uses changed"),
                       ("result", "Lean's result changed")):
            if doc.get(k) != ref.get(k):
                changes.append({"certificate": ref.get("theorem"), "was": ref.get(k),
                                "now": doc.get(k), "reason": why})
    return {"state": "stale" if changes else "current", "changes": changes}


# -- the reading of an estimate -------------------------------------------------------------

BINDING = ("for every", "there is", "constant dependence")
PREMISES = ("assumption", "condition", "implies")


def _fragments(records: list[dict], lid: str) -> list[dict]:
    return [f for f in records if f.get("kind") == "fragment" and f.get("requirement") == lid]


def obligation(records: list[dict], lid: str, corrections=()) -> dict | None:
    """The reading of requirement `lid` of a claim (`records`: the claim's workspace records)
    as an obligation: its variables in the order they are chosen, each with its domain, the
    constants' allowed and excluded dependences, the premises around it, and a digest of the
    reading (the requirements involved and the passages that govern them). `corrections` are
    correction requirements to read in place of the printed ones they correct (a correction of
    another form adds a condition to the one it corrects)."""
    from .requirements import reading_digest
    reqs = {r["local_id"]: r for r in records if r.get("kind") == "requirement"}
    est = reqs.get(lid)
    if est is None:
        return None
    replace, added = {}, {}
    for c in corrections or ():
        r = reqs.get(c)
        if not r or r.get("origin") != "correction" or r.get("corrects") not in reqs:
            continue
        if r.get("form") in BINDING or r.get("form") == reqs[r["corrects"]].get("form"):
            replace[r["corrects"]] = r
        else:
            added.setdefault(r["corrects"], []).append(r)
    sub = lambda r: replace.get(r["local_id"], r)  # noqa: E731
    chain, at = [], est.get("parent")
    while at in reqs and len(chain) < len(reqs):
        chain.insert(0, reqs[at])
        at = reqs[at].get("parent")
    involved = []
    entries, premises = [], []

    def enter(r0):
        r = sub(r0)
        involved.append(r)
        involved.extend(added.get(r0["local_id"], []))
        conds = [a["text"] for a in added.get(r0["local_id"], [])]
        if r.get("form") in BINDING:
            for v in r.get("binds") or []:
                q = "for every" if r["form"] == "for every" else "there is"
                same = next((e for e in entries if e["var"] == v), None)
                if same is not None and q == "there is" and same["quantifier"] == "there is":
                    same["independent_of"] = list(dict.fromkeys(
                        same["independent_of"] + list(r.get("independent_of") or [])))
                    same["depends_on"] = list(dict.fromkeys(
                        same["depends_on"] + list(r.get("depends_on") or [])))
                    same["requirements"].append(r["local_id"])
                    same["conditions"] += conds
                    same["domain"] = same["domain"] or r.get("domain")
                    continue
                entries.append({"var": v, "quantifier": q, "domain": r.get("domain"),
                                "requirements": [r["local_id"]],
                                "independent_of": list(r.get("independent_of") or []),
                                "depends_on": list(r.get("depends_on") or []),
                                "conditions": conds,
                                **({"correction": r["local_id"]} if r is not r0 else {})})
        elif r.get("form") in PREMISES:
            premises.append({"requirement": r["local_id"], "text": r["text"]})
            premises.extend({"requirement": a["local_id"], "text": a["text"]}
                            for a in added.get(r0["local_id"], []))

    for a in chain:
        enter(a)
    ids = {a["local_id"] for a in chain} | {lid}
    for r in sorted(reqs.values(), key=lambda r: _natural(r["local_id"])):
        if r in chain or r is est or r.get("origin") == "correction" or \
                r.get("form") != "constant dependence":
            continue
        if r.get("parent") in ids or not r.get("parent"):
            enter(r)
    goal = sub(est)
    involved.append(goal)
    if goal.get("form") in BINDING:
        enter(est)
    conds = [a["text"] for a in added.get(lid, [])]
    involved.extend(added.get(lid, []))
    # A constant stated independent of a variable is chosen before it; one allowed to depend
    # on a variable is chosen after it.
    for _ in range(len(entries) ** 2 + 1):
        moved = False
        for i, e in enumerate(entries):
            if e["quantifier"] != "there is":
                continue
            js = [j for j, f in enumerate(entries[:i]) if f["var"] in e["independent_of"]]
            ks = [j for j, f in enumerate(entries) if j > i and f["var"] in e["depends_on"]]
            if js:
                entries.insert(min(js), entries.pop(i))
            elif ks:
                entries.insert(max(ks), entries.pop(i))
            else:
                continue
            moved = True
            break
        if not moved:
            break
    for i, e in enumerate(entries):
        before = [f["var"] for f in entries[:i]]
        e["chosen_after"] = before
        e["chosen_before"] = [f["var"] for f in entries[i + 1:]]
        if e["quantifier"] == "there is":
            e["may_depend_on"] = [v for v in before if v not in e["independent_of"]]
    pinned = {"order": [{k: e[k] for k in ("var", "quantifier", "domain", "requirements",
                                           "independent_of", "depends_on", "conditions")}
                        for e in entries],
              "premises": premises, "goal": {"form": goal.get("form"), "text": goal.get("text"),
                                              "conditions": conds},
              "readings": sorted({r["local_id"]: reading_digest(
                  r, _fragments(records, r["local_id"])) for r in involved}.items())}
    return {"requirement": lid, "corrections": list(corrections or ()),
            "involved": [r for r, _ in pinned["readings"]],
            "order": entries, "premises": premises,
            "goal": {"requirement": goal["local_id"], "form": goal.get("form"),
                     "text": goal.get("text"), "conditions": conds},
            "text": prefix_text(entries, goal.get("text"), conds),
            "sha256": "obligation-v1:" + digest(pinned)}


def _natural(s: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def prefix_text(entries: list[dict], goal: str | None, conds=()) -> str:
    parts = []
    for e in entries:
        dom = f" ({e['domain']})" if e.get("domain") else ""
        extra = "".join(f", {c}" for c in e.get("conditions") or [])
        ind = f", independent of {', '.join(e['independent_of'])}" \
            if e["quantifier"] == "there is" and e.get("independent_of") else ""
        parts.append(f"{e['quantifier']} {e['var']}{dom}{extra}{ind}")
    tail = (goal or "") + "".join(f", {c}" for c in conds)
    return "; ".join(parts) + (": " if parts else "") + tail


IDENT = re.compile(r"[^\W\d][\w']*")


def _vars_in(expr, names) -> list[str]:
    return [t for t in dict.fromkeys(IDENT.findall(str(expr))) if t in names]


def analyse(cx: dict, ob: dict | None) -> dict:
    """What a counterexample can show against its reading: a symbolic family over the
    constants left free, a single instance (when the reading chooses no constant), a choice of
    fixed constants, or only samples; whether its admissibility is verified; and the problems
    that keep it from refuting the reading as read."""
    assign = (cx.get("specialisation") or {}).get("assign") or {}
    problems, fixed, family, values = [], [], [], []
    order = ob["order"] if ob else []
    names = [e["var"] for e in order]
    for i, e in enumerate(order):
        v = e["var"]
        if e["quantifier"] == "for every":
            if v not in assign:
                problems.append(f"no value is given for {v}")
                continue
            used = _vars_in(assign[v], set(names))
            late = [u for u in used if names.index(u) >= i]
            if late:
                problems.append(f"{v} = {assign[v]} uses {', '.join(late)}, chosen after {v} in "
                                "this reading")
            values.append({"var": v, "value": assign[v], "symbolic": bool(used),
                           "uses": used})
        elif v in assign:
            fixed.append(v)
        else:
            family.append(e)
    if problems:
        form = "incomplete"
    elif fixed:
        form = "fixed constants"
    elif family:
        form = "family"
    else:
        form = "instance"
    adm = cx.get("admissibility") or []
    states = {a["state"] for a in adm}
    adm_state = "fails" if "fails" in states else "verified" if adm and states == {"verified"} \
        else "open"
    decisive = form in ("family", "instance")
    if adm_state == "fails":
        standing = "not admissible"
    elif not decisive and cx.get("samples"):
        standing = "illustration"
    elif form == "incomplete":
        standing = "incomplete"
    elif decisive and adm_state == "verified":
        standing = "admissible counterexample"
    else:
        standing = "candidate"
    quant = "; ".join(f"for every {e['var']}" + (f" ({e['domain']})" if e.get("domain") else "")
                      for e in family)
    vals = ", ".join(f"{x['var']} = {x['value']}" for x in values)
    if form == "family":
        shows = (f"{quant}: {vals} reduces the reading to {cx.get('reduced')}, which fails "
                 f"({cx.get('violation')}). No choice of {', '.join(e['var'] for e in family)} "
                 "satisfies this reading.")
    elif form == "instance":
        shows = (f"{vals} reduces the reading to {cx.get('reduced')}, which fails "
                 f"({cx.get('violation')}).")
    elif form == "fixed constants":
        shows = (f"It fixes {', '.join(f'{v} = {assign[v]}' for v in fixed)}: it shows only "
                 "that this choice fails, not that every choice does.")
    else:
        shows = "It does not yet give each variable a value this reading allows."
    open_ = [a["obligation"] for a in adm if a["state"] == "open"]
    return {"form": form, "decisive": decisive, "standing": standing,
            "standing_text": STANDING_WORDS[standing], "family": [e["var"] for e in family],
            "fixed": fixed, "values": values, "problems": problems,
            "admissibility": adm_state, "open_obligations": open_,
            "samples": len(cx.get("samples") or []),
            "samples_note": SAMPLES_NOTE if cx.get("samples") else None, "shows": shows}


COMPARISON = re.compile(r"(<=|>=|<|>|≤|≥)")
FLIP = {"<": ">", ">": "<", "≤": "≥", "≥": "≤", "<=": "≥", ">=": "≤"}


def bounds(var: str, domain: str) -> list[tuple[str, str, bool]]:
    """The bounds a domain such as `0 < ε ≤ 1` or `k ≥ 0` puts on `var`: (side, value, strict),
    side `lower` or `upper`. A domain of another shape gives none."""
    parts = [p.strip() for p in COMPARISON.split(domain)]
    out = []
    for i in range(1, len(parts) - 1, 2):
        left, op, right = parts[i - 1], parts[i], parts[i + 1]
        if right == var and left != var:
            left, op, right = right, FLIP[op], left
        if left != var or not right:
            continue
        op = {"<=": "≤", ">=": "≥"}.get(op, op)
        out.append(("lower" if op in (">", "≥") else "upper", right, op in ("<", ">")))
    return out


def specialisations(ob: dict) -> list[dict]:
    """Specialisations to try for a reading, from the domains of its variables: each endpoint
    or limit of a variable, with the constants chosen before it kept fixed. These are
    suggestions from the wording of the domains; the auditor decides."""
    out = []
    consts = {e["var"] for e in ob["order"] if e["quantifier"] == "there is"}
    for e in ob["order"]:
        if e["quantifier"] != "for every" or not e.get("domain"):
            continue
        fixed = [v for v in e["chosen_after"] if v in consts]
        keep = f", with {', '.join(fixed)} fixed" if fixed else ""
        bs = bounds(e["var"], e["domain"])
        tries = []
        for side, value, strict in bs:
            if strict:
                tries.append(f"{e['var']} → {value}" + ("⁺" if side == "lower" else "⁻"))
            else:
                tries.append(f"{e['var']} = {value}")
        if bs and not any(side == "upper" for side, _, _ in bs):
            tries.append(f"{e['var']} → ∞")
        for t in dict.fromkeys(tries):
            out.append({"var": e["var"], "try": t + keep, "by": "machinechecked",
                        "rule": f"the domain {e['domain']}"})
    return out


# -- hints -----------------------------------------------------------------------------------

# The hints an alignment's paper expression gives (`expression_hints`), which a difference
# settles by naming `{alignment, kind}`.
EXPRESSION_HINTS = ("offset", "coefficient", "power", "terms", "not compared")
# The hints the order of the claim's aligned variables gives (`order_hints`).
ORDER_HINTS = ("quantifier order", "quantifier")
ALIGNMENT_HINTS = (*EXPRESSION_HINTS, *ORDER_HINTS)


def _settling(records: list[dict]) -> dict[tuple, dict]:
    """The findings in force whose difference settles a hint (an outcome other than `open`), by
    the hint they name: `(decl, binder)` or `(alignment, kind)`."""
    later = {r.get("supersedes") for r in records if r.get("supersedes")}
    out = {}
    for f in records:
        d = f.get("difference") or {}
        h = d.get("hint") or {}
        if f.get("kind") != "finding" or f["id"] in later or not h or \
                d.get("outcome") not in ("no difference", "resolved", "difference"):
            continue
        out[(h["alignment"], h["kind"]) if "alignment" in h else (h["decl"], h["binder"])] = f
    return out


def _settled(f: dict | None) -> dict:
    """What a hint settled by the finding `f` carries: the finding (`settled_by`) and, in
    `settled`, its outcome, who recorded it and why."""
    if f is None:
        return {}
    d = f["difference"]
    why = d.get("why") or (d.get("resolution") or {}).get("text") or f.get("note") or \
        OUTCOME_WORDS[d["outcome"]]
    return {"settled_by": f["id"], "settled": {"finding": f["id"], "outcome": d["outcome"],
                                               "why": why, "by": f.get("created_by")}}


def hints(records: list[dict], snap, claim: str) -> tuple[list[dict], list[dict]]:
    """Computed pointers, from the claim's alignments: each hypothesis of an aligned Lean
    statement that no alignment associates with a requirement (an extra Lean hypothesis to
    inspect), each aligned paper expression that differs in quantity from its Lean expression,
    or that could not be compared (`expression_hints`); and each hypothesis aligned with a
    requirement that a standing assumption governs (inherited by the claim, not an extra
    hypothesis). A hint a difference finding in force dismissed or resolved carries that finding
    and its reason (`settled_by`, `settled`). A hint is a pointer; it is never a finding, and it
    changes no status."""
    from . import requirements as rq
    from . import symbols
    if snap is None:
        return [], []
    aligns = [r for r in records if r.get("kind") == "alignment"]
    statements = rq._statements(snap, claim)
    decls = list(dict.fromkeys(t["decl"] for a in aligns if a.get("requirements")
                               for t in a.get("lean") or []))
    seen: dict[tuple[str, int], list[str]] = {}
    for a in aligns:
        for t in a.get("lean") or []:
            i = t.get("binder", t.get("var"))
            if isinstance(i, int):
                seen.setdefault((t["decl"], i), []).extend(a.get("requirements") or [])
    settled = _settling(records)
    out, inherited = [], []
    for decl in decls:
        st = statements.get(decl)
        if not st:
            continue
        for i, b in enumerate(st.get("binders") or []):
            if b.get("role") != "hypothesis":
                continue
            lean = f"{b.get('name')} : {symbols._text(b.get('type'))}"
            lids = seen.get((decl, i))
            if lids:
                for lid in dict.fromkeys(lids):
                    fr = [f for f in _fragments(records, lid) if f.get("state") == "accepted"
                          and f.get("role") == "standing assumption"]
                    if fr:
                        inherited.append({"decl": decl, "binder": i, "lean": lean,
                                          "requirement": lid,
                                          "from": fr[0].get("scope") or rq.where_text(fr[0])})
                continue
            if (decl, i) in seen:
                continue  # aligned as an additional assumption of the Lean, by the auditor
            out.append({"kind": "unmatched hypothesis", "decl": decl, "binder": i,
                        "lean": lean, "basis": "computed hint",
                        "text": f"{decl} assumes {lean}; no requirement of this reading is "
                                "aligned with it",
                        **_settled(settled.get((decl, i)))})
    for h in [*expression_hints(records, snap, claim, statements),
              *order_hints(records, snap, claim, statements)]:
        out.append({**h, **_settled(settled.get((h["alignment"], h["kind"])))})
    return out, inherited


def variable_pairs(records: list[dict], snap, claim: str,
                   statements: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """Per declaration, the paper's variables matched with its variables: a requirement's
    variable (`binds`) aligned with a Lean variable (`var`), and the claim's symbol links to a
    variable that hold and take every occurrence of their symbol. An alignment of several
    variables with several Lean variables matches those of the same name only. A paper variable
    matched with two variables of one declaration is matched with neither (`ambiguous`).
    `{decl: {name key: {lean, name, paper, via, alignment} | {ambiguous: [names]}}}`, with
    `alignment` the alignment that matched them (null for a symbol link)."""
    from . import expressions as ex
    from . import symbols
    reqs = {r["local_id"]: r for r in records if r.get("kind") == "requirement"}
    found: dict[str, dict[str, list[dict]]] = {}

    def names_of(decl):
        st = statements.get(decl)
        return [(v or {}).get("name") for v in symbols.variables(st)] if st else []

    def add(decl, paper, i, via, aid=None):
        names = names_of(decl)
        found.setdefault(decl, {}).setdefault(ex.name_key(paper), []).append(
            {"lean": f"v:{i}", "name": (names[i] if i < len(names) else None) or f"#{i}",
             "paper": ex.name_key(paper), "via": via, "alignment": aid})

    for a in sorted((r for r in records if r.get("kind") == "alignment"),
                    key=lambda r: (r.get("created_at") or "", r["id"])):
        binds = list(dict.fromkeys(b for lid in a.get("requirements") or []
                                   for b in (reqs.get(lid) or {}).get("binds") or []))
        by_decl: dict[str, list[int]] = {}
        for t in a.get("lean") or []:
            if type(t.get("var")) is int:
                by_decl.setdefault(t["decl"], []).append(t["var"])
        for decl, idx in by_decl.items():
            idx = list(dict.fromkeys(idx))
            if len(binds) == 1 and len(idx) == 1:
                add(decl, binds[0], idx[0], f"alignment {a['id']}", a["id"])
                continue
            names = names_of(decl)
            for b in binds:
                same = [i for i in idx if i < len(names) and
                        ex.name_key(names[i] or "") == ex.name_key(b)]
                if len(same) == 1:
                    add(decl, b, same[0], f"alignment {a['id']}", a["id"])
    for ln in (snap.chunk(claim) or {}).get("symbols") or []:
        t, sym = ln.get("lean") or {}, ln.get("symbol") or {}
        if ln.get("stale") or type(t.get("var")) is not int or not sym.get("tex") or \
                sym.get("occurrence", "all") != "all":
            continue
        add(t.get("decl"), sym["tex"], t["var"], f"symbol link by {ln.get('by')}")
    out: dict[str, dict[str, dict]] = {}
    for decl, by_name in found.items():
        for k, cands in by_name.items():
            if len({c["lean"] for c in cands}) == 1:
                out.setdefault(decl, {})[k] = cands[0]
            else:
                out.setdefault(decl, {})[k] = {"ambiguous": list(dict.fromkeys(
                    c["name"] for c in cands))}
    return out


def _lean_expression(st: dict, t: dict, part) -> tuple[dict | None, str | None, dict | None]:
    """The mathematics, text and place (`symbols.math_context`) of the expression a Lean
    target names: the conclusion, a variable's type (a hypothesis), or a sub-term (`at`)."""
    from . import symbols
    if t.get("conclusion"):
        pp = st.get("conclusion") or {}
        return pp.get("math"), symbols._text(pp), {"path": [], "printed": pp, "expansion": None}
    if type(t.get("binder")) is int:
        vs = symbols.variables(st)
        pp = (vs[t["binder"]] or {}).get("type") if t["binder"] < len(vs) else None
        if not isinstance(pp, dict):
            return None, None, None
        return pp.get("math"), symbols._text(pp), {"path": [], "printed": pp, "expansion": None}
    if isinstance(t.get("at"), str):
        c = symbols.math_context(st, t["at"], part)
        return (c or {}).get("math"), symbols.term_by_id(st, t["at"], part), c
    return None, None, None


def _expanded(x: dict) -> str | None:
    from . import symbols
    if isinstance(x.get("body"), dict):
        return symbols._text(x["body"])
    q = next((q for q in x.get("equations") or [] if isinstance(q, dict)), None)
    return symbols._text(q.get("equation") or q.get("statement")) if q else None


def _definition(ctx: dict, app: dict | None, arg: dict | None, part) -> dict | None:
    """The definition the compared Lean expression stands in: the one whose expansion it is
    printed in, or the application `app` of a definition it is the argument `arg` of, with that
    definition's parameter and its expansion at these arguments when the build holds it."""
    from . import symbols
    x = ctx.get("expansion")
    if x is not None and app is None:
        return {"name": x.get("name"), "expansion": x.get("id"),
                **({"expanded": _expanded(x)} if _expanded(x) else {})}
    if app is None:
        return None
    out = {"name": app.get("name")}
    ref = next((e for e in (ctx.get("printed") or {}).get("expansions") or []
                if isinstance(e, dict) and e.get("at") == app.get("id")), None)
    if ref is not None and symbols._is_ref(ref):
        ref = part(ref["key"]) if part is not None else None
    if isinstance(ref, dict):
        out["expansion"] = ref.get("id")
        for p in ref.get("args") or []:
            if isinstance(p, dict) and (p.get("value") or {}).get("id") == (arg or {}).get("id"):
                out["parameter"] = p.get("name")
        if _expanded(ref):
            out["expanded"] = _expanded(ref)
    return out


def _unwrapped(text: str | None) -> str | None:
    """`text` without one pair of brackets around all of it, as Lean prints an argument."""
    if not text or not (text.startswith("(") and text.endswith(")")):
        return text
    depth = 0
    for i, ch in enumerate(text):
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0 and i < len(text) - 1:
            return text
    return text[1:-1]


def _identifiers(node) -> list[str]:
    if not isinstance(node, dict):
        return []
    if node.get("k") == "local":
        return [node["name"]]
    return [n for a in node.get("args") or [] for n in _identifiers(a)]


def _compare_target(expr: str, st: dict, t: dict, pairs: dict, part) -> dict:
    """The comparison of the paper's `expr` with the Lean expression the target `t` names, with
    the definition it stands in. An application of a definition, or a relation, is compared
    through the one argument that has the paper's variables."""
    from . import expressions as ex
    from . import symbols
    node, text, ctx = _lean_expression(st, t, part)
    keys = {k: v["lean"] for k, v in pairs.items() if "lean" in v}
    known = {v["lean"]: v["name"] for v in pairs.values() if "lean" in v}
    out = {"lean_text": t.get("target") if text is None else text}
    try:
        used = _identifiers(ex.read_tex(expr))
    except ex.Unsupported:
        used = []
    twice = [k for k in used if "ambiguous" in (pairs.get(k) or {})]
    if twice:
        return {**out, "outcome": "not compared",
                "reason": f"the paper's {twice[0]} is aligned with more than one variable of "
                          f"{t['decl']} ({', '.join(pairs[twice[0]]['ambiguous'])})"}
    if node is None:
        return {**out, "outcome": "not compared",
                "reason": f"this build holds no reading of that part of {t['decl']} as "
                          "mathematics"}
    app = arg = None
    path = [*((ctx or {}).get("path") or []), node]
    if node.get("k") in ("apply", "rel"):
        want = ex.paper_atoms(expr, keys)
        if want is not None:
            cands = [a for a in node.get("args") or [] if ex.lean_atoms(a, known) == want]
            what = node.get("name") if node.get("k") == "apply" else "the relation"
            if len(cands) != 1:
                return {**out, "outcome": "not compared",
                        "reason": ("no" if not cands else "more than one") + f" argument of {what} "
                        "has exactly the paper expression's variables"}
            node = cands[0]
            path.append(node)
            out["lean_text"] = symbols.term_by_id(st, node.get("id"), part) or out["lean_text"]
            out["lean_at"] = node.get("id")
    if ctx is not None and ctx.get("expansion") is None:
        # The nearest application of a definition around the expression, with the argument it
        # stands in.
        for i in range(len(path) - 2, -1, -1):
            if path[i].get("k") == "apply":
                app, arg = path[i], path[i + 1]
                break
    res = ex.compare(expr, node, keys, known)
    d = _definition(ctx or {}, app, arg, part)
    return {**out, **res, **({"definition": d} if d else {})}


def expression_hints(records: list[dict], snap, claim: str,
                     statements: dict[str, dict]) -> list[dict]:
    """A hint for each Lean target of an alignment that names its paper `expression` and an
    expression of the Lean (the conclusion, a hypothesis or a sub-term), when the two differ in
    quantity (`expressions.compare`: an `offset`, a `coefficient`, a `power`, other `terms`), or
    when they could not be compared (`not compared`, with the reason: an identifier aligned with
    no Lean variable, something the TeX reader does not read, a Lean operation that is not this
    arithmetic, an alignment out of date). A rename through an alignment or a symbol link, and
    an algebraically equal form, give none."""
    from . import requirements as rq
    aligns = sorted((a for a in records if a.get("kind") == "alignment" and a.get("expression")),
                    key=lambda a: (a.get("created_at") or "", a["id"]))
    if not aligns:
        return []
    pairs = variable_pairs(records, snap, claim, statements)
    part = getattr(snap, "part", None)
    out = []
    for a in aligns:
        cur = rq.alignment_currency(a, snap)
        cur = rq.with_expression(cur, a, records, snap)
        for t in a.get("lean") or []:
            if not (t.get("conclusion") or type(t.get("binder")) is int
                    or isinstance(t.get("at"), str)):
                continue
            st = statements.get(t["decl"])
            if cur["state"] == "stale":
                res = {"outcome": "not compared", "lean_text": t.get("target"),
                       "reason": "the alignment is out of date: read it again and re-pin it"}
            elif st is None:
                res = {"outcome": "not compared", "lean_text": t.get("target"),
                       "reason": f"this build holds no statement of {t['decl']} for {claim}"}
            else:
                res = _compare_target(a["expression"], st, t, pairs.get(t["decl"]) or {}, part)
            if res["outcome"] == "same":
                continue
            out.append(_hint(a, t, res, pairs.get(t["decl"]) or {}))
    return out


CHOOSES = {"for every": "takes {v} as given (for every {v})",
           "there is": "produces {v} (there is {v})"}
LEAN_CHOOSES = {"given": "takes {v} as given (for every {v})",
                "produced": "produces {v} (there is {v})"}
SCOPE_WORDS = {"assumed": "inside a hypothesis or a premise", "denied": "inside a negation",
               "alternative": "inside one alternative", "equivalent": "inside an equivalence"}


def order_hints(records: list[dict], snap, claim: str,
                statements: dict[str, dict]) -> list[dict]:
    """Hints from the order in which the claim's aligned variables are chosen. The paper's order
    is each reading's (`obligation`, for every requirement with nothing inside it): a constant or
    witness (`there is`) may depend on the variables chosen before it, unless it is stated
    independent of them. The Lean's is the scope in its statement's tree (`symbols.scopes`): a
    "there is" may depend on every variable bound around it, whatever its type mentions. For each
    paper variable matched with a Lean variable (`variable_pairs`): a `quantifier` hint when one
    side produces it and the other takes it as given; for each "there is" and "for every" both
    matched, a `quantifier order` hint when the paper lets the one depend on the other and the
    Lean does not, or the other way round (`∃ C ∀ n` against `∀ n ∃ C`; a domain chosen once
    before every stage against one chosen per stage). A variable the Lean binds inside a
    hypothesis, a negation, an alternative or an equivalence, and a variable of such a pair that
    is matched with none, give `not compared`. Agreeing orders give none."""
    from . import expressions as ex
    from . import symbols
    reqs = [r for r in records if r.get("kind") == "requirement"]
    pairs = variable_pairs(records, snap, claim, statements)
    if not reqs or not pairs:
        return []
    inner = {r.get("parent") for r in reqs}
    orders = [o["order"] for o in (obligation(records, r["local_id"]) for r in
                                   sorted(reqs, key=lambda r: _natural(r["local_id"]))
                                   if r["local_id"] not in inner and r.get("origin") != "correction")
              if o and o["order"]]
    out, seen = [], set()
    for decl in sorted(pairs):
        st = statements.get(decl)
        if not st:
            continue
        sc, m = symbols.scopes(st), pairs[decl]

        def lean(e):
            p = m.get(ex.name_key(e["var"]))
            return p if p and "lean" in p else None

        def said(x):
            """A Lean variable as the Lean binds it."""
            p = lean(x)
            s = sc.get(int(p["lean"][2:])) if p else None
            if not s:
                return "(aligned with none)" if p is None else p["name"]
            return ("there is " if s["scope"] == "produced" else "for every " if
                    s["scope"] == "given" else "") + p["name"]

        def hint(kind, xs, text, lean_text, **more):
            """A hint about the paper variables `xs` (in the paper's order) of one reading."""
            key = (kind, decl, *(x["var"] for x in xs))
            if key in seen:
                return
            seen.add(key)
            ps = [lean(x) for x in xs]
            on = next(p for p in ps if p)
            aid = next((p["alignment"] for p in ps if p and p.get("alignment")), None)
            out.append({"kind": kind, "basis": "computed hint", "alignment": aid,
                        "requirements": list(dict.fromkeys(r for x in xs
                                                           for r in x["requirements"])),
                        "decl": decl, "target": {"decl": decl, "var": int(on["lean"][2:])},
                        "paper": {"text": "; ".join(f"{x['quantifier']} {x['var']}" for x in xs),
                                  "order": [x["var"] for x in xs]},
                        "lean": {"text": lean_text},
                        "variables": [{"paper": p["paper"], "lean": p["name"], "via": p["via"]}
                                      for p in ps if p],
                        **more, "text": text})

        def comparable(e):
            """The number of the Lean variable of the paper's `e` when the order can be compared:
            matched, and bound by a "for every" or a "there is" with the paper's quantifier that
            stands outside every hypothesis, negation, alternative and equivalence."""
            p = lean(e)
            s = sc.get(int(p["lean"][2:])) if p else None
            if s is None:
                return None
            if s["scope"] not in ("given", "produced"):
                where = f"{decl} binds {p['name']} {SCOPE_WORDS.get(s['scope'], s['scope'])}"
                hint("not compared", [e], f"The paper's {e['var']} and Lean's {p['name']} are "
                     f"not compared: {where}.", p["name"], reason=where)
                return None
            if (e["quantifier"] == "there is") != (s["scope"] == "produced"):
                hint("quantifier", [e],
                     f"The paper {CHOOSES[e['quantifier']].format(v=e['var'])}; {decl} "
                     f"{LEAN_CHOOSES[s['scope']].format(v=p['name'])}.", said(e),
                     feature="quantifier order")
                return None
            return int(p["lean"][2:])

        for order in orders:
            for i, a in enumerate(order):
                comparable(a)
                for b in order[i + 1:]:
                    if a["quantifier"] == b["quantifier"]:
                        continue
                    e, u = (a, b) if a["quantifier"] == "there is" else (b, a)
                    unmatched = [x for x in (e, u) if lean(x) is None]
                    if len(unmatched) == 1:
                        x = unmatched[0]
                        why = (f"the paper's {x['var']} is aligned with "
                               + ("more than one variable" if m.get(ex.name_key(x["var"]))
                                  else "no variable") + f" of {decl}")
                        hint("not compared", [a, b], f"The order of the paper's {a['var']} and "
                             f"{b['var']} is not compared with {decl}: {why}.",
                             "; ".join(said(x) for x in (a, b)), reason=why)
                        continue
                    if unmatched:
                        continue
                    ie, iu = comparable(e), comparable(u)
                    if ie is None or iu is None:
                        continue
                    paper_dep = u["var"] in (e.get("may_depend_on") or [])
                    lean_dep = iu in sc[ie]["after"]
                    if paper_dep == lean_dep:
                        continue
                    ne, nu = lean(e)["name"], lean(u)["name"]
                    stated = u["var"] in (e.get("independent_of") or [])
                    if paper_dep:
                        text = (f"The paper chooses {e['var']} after {u['var']}, so {e['var']} "
                                f"may depend on {u['var']}; in {decl}, {ne} is chosen before "
                                f"{nu} and may not depend on it: Lean's {ne} is one for every "
                                f"{nu}.")
                    else:
                        text = (f"The paper chooses {e['var']} before {u['var']}, so "
                                f"{e['var']} may not depend on {u['var']}"
                                + (" (stated independent of it)" if stated else "")
                                + f"; in {decl}, {ne} is chosen after {nu} and may depend on "
                                "it, whatever its type mentions.")
                    hint("quantifier order", [u, e] if paper_dep else [e, u], text,
                         f"for every {nu}; there is {ne}" if lean_dep
                         else f"there is {ne}; for every {nu}",
                         feature="constant dependence" if stated else "quantifier order",
                         dependence={"paper": paper_dep, "lean": lean_dep})
    return out


def _aligned(spaces) -> list:
    return [(p, ws) for p, ws in spaces
            if any(isinstance(r, dict) and r.get("kind") == "alignment"
                   for r in (ws.get("records") or {}).values())]


def has_alignments(work_dir: Path | None) -> bool:
    """Whether a workspace in `work_dir` records an alignment, which can give a hint."""
    from . import workspace as wsp
    return work_dir is not None and bool(_aligned(wsp.list_all(work_dir)))


def workspace_hints(work_dir: Path | None, data: Path,
                    sources: Path | None = None) -> dict[str, dict]:
    """Per claim of the build whose site data is `data`, the computed hints the workspaces in
    `work_dir` give (`hints`), each with the workspace, its auditor and its mode: those in
    force (`hints`) and those a difference settles (`dismissed`). `sources` is the build's copy
    of the papers' sources, which the passages are read in. Hints are pointers for the auditor;
    nothing counts or publishes them."""
    from . import workspace as wsp
    from .targets import Snapshot, TargetError
    spaces = _aligned(wsp.list_all(work_dir)) if work_dir is not None else []
    if not spaces:
        return {}
    try:
        snap = Snapshot(data)
    except TargetError:
        return {}
    if sources is not None:
        snap.sources_base = Path(sources)
    claims = {c["id"] for c in snap.claims}
    out: dict[str, dict] = {}
    for _, ws in spaces:
        recs = [r for r in ws["records"].values() if isinstance(r, dict)]
        who = {"workspace": ws.get("id"), "by": (ws.get("reviewer") or {}).get("id"),
               "mode": ws.get("mode")}
        for cid in sorted({r.get("claim") for r in recs if r.get("kind") == "alignment"}
                          & claims):
            hs, _ = hints([r for r in recs if r.get("claim") == cid], snap, cid)
            for h in hs:
                out.setdefault(cid, {"hints": [], "dismissed": []})[
                    "dismissed" if h.get("settled_by") else "hints"].append({**h, **who})
    return out


def _hint(a: dict, t: dict, res: dict, pairs: dict) -> dict:
    from . import requirements as rq
    kind = res.get("kind") or "not compared"
    by_key = {v["lean"]: v for v in pairs.values() if "lean" in v}
    variables = [{"paper": by_key[k]["paper"], "lean": by_key[k]["name"],
                  "via": by_key[k]["via"]} for k in res.get("used") or [] if k in by_key]
    paper, lean = a["expression"], _unwrapped(res.get("lean_text")) or rq.target_text(t)
    d = res.get("definition") or {}
    where = [t["decl"]]
    if d.get("parameter"):
        where.append(f"the argument {d['parameter']} of {d['name']}")
    elif d.get("name"):
        where.append(f"inside {d['name']}")
    if d.get("expanded"):
        where.append(f"which expands to {d['expanded']}")
    renamed = [f"{v['paper']} as {v['lean']}" for v in variables if v["paper"] != v["lean"]]
    context = f" ({'; '.join(renamed)}; " if renamed else " ("
    context += "in " + ", ".join(where) + ")"
    if kind == "offset":
        diff = Fraction(res["difference"])
        lead = (f"The paper's {paper} and Lean's {lean} differ by {abs(diff)}: Lean's is "
                + ("larger" if diff > 0 else "smaller"))
    elif kind == "coefficient":
        lead = f"Lean's {lean} is {res['factor']} times the paper's {paper}"
    elif kind == "power":
        lead = (f"The paper's {paper} and Lean's {lean} have different powers: "
                f"{res['paper_normal']} and {res['lean_normal']}")
    elif kind == "terms":
        lead = (f"The paper's {paper} and Lean's {lean} differ: {res['paper_normal']} and "
                f"{res['lean_normal']}")
    else:
        lead = f"The paper's {paper} and Lean's {lean} are not compared: {res['reason']}"
    target = {k: t[k] for k in ("decl", *rq.SUBTARGETS) if k in t}
    return {"kind": kind, "basis": "computed hint", "alignment": a["id"],
            "requirements": list(a.get("requirements") or []), "decl": t["decl"],
            "target": target,
            **({"feature": res["feature"]} if res.get("feature") else {}),
            "paper": {"text": paper, **({"normal": res["paper_normal"]}
                                        if res.get("paper_normal") else {})},
            "lean": {"text": lean, **({"normal": res["lean_normal"]}
                                      if res.get("lean_normal") else {}),
                     **({"at": res["lean_at"]} if res.get("lean_at") else {})},
            **({"difference": res["difference"]} if "difference" in res else {}),
            **({"factor": res["factor"]} if "factor" in res else {}),
            **({"conditions": res["conditions"]} if res.get("conditions") else {}),
            **({"reason": res["reason"]} if kind == "not compared" else {}),
            "variables": variables,
            **({"definition": d} if d else {}),
            "text": lead + context + "."}


# -- the block a claim's reading shows ---------------------------------------------------------

def analysis(records: list[dict], cur: dict, snap=None, claim: str | None = None) -> dict:
    """The estimates block of a claim's reading: for each requirement that has a
    counterexample or a verdict, its printed reading and each corrected reading,
    each with its obligation, counterexamples (analysed against that reading), the findings and
    certificates that are evidence for it; the differences recorded, open ones apart from
    settled ones (a resolution by a checked bridge Lean does not check now, as `cur` gives it,
    or one that leaves conditions open, is not settled); and the computed hints."""
    from .workspace import current_findings
    reqs = {r["local_id"]: r for r in records if r.get("kind") == "requirement"}
    cxs = [r for r in records if r.get("kind") == "counterexample"]
    evid = {r["id"]: r for r in records if r.get("kind") == "evidence"}
    in_force = {f["id"] for f in current_findings({"records": {r["id"]: r for r in records}})}
    finds = [r for r in records if r.get("kind") == "finding"]
    unknown = {"state": "unchecked", "changes": []}

    def corrected(lid):
        """The printed requirement a correction corrects, followed to the printed one."""
        seen = set()
        while lid in reqs and reqs[lid].get("origin") == "correction" and lid not in seen:
            seen.add(lid)
            lid = reqs[lid].get("corrects")
        return lid

    targets = []
    for r in cxs:
        targets.append(r["requirement"])
    for f in finds:
        if f.get("requirement") and (f.get("verdict") or f.get("counterexamples")):
            targets.append(corrected(f["requirement"]))
    out = []
    for lid in dict.fromkeys(t for t in targets if t in reqs):
        ob0 = obligation(records, lid)
        involved = {e for e in ob0["order"] for e in e["requirements"]} | {lid} | \
            {p["requirement"] for p in ob0["premises"]}
        readings = [()]
        for r in reqs.values():
            if r.get("origin") == "correction" and r.get("corrects") in involved:
                readings.append((r["local_id"],))
        for c in cxs:
            if c["requirement"] == lid and c.get("reading"):
                readings.append(tuple(c["reading"]))
        rd_out = []
        for corr in dict.fromkeys(readings):
            ob = obligation(records, lid, corr)
            mine = [c for c in cxs if c["requirement"] == lid and
                    tuple(c.get("reading") or ()) == corr]
            on = {lid} if not corr else set(corr)
            fs = [f for f in finds if f.get("requirement") in on and f["id"] in in_force
                  and (f.get("verdict") or f.get("counterexamples") or f.get("evidence")
                       or f.get("difference"))]
            certs = []
            for f in fs:
                for e in f.get("evidence") or []:
                    ref = (evid.get(e) or {}).get("ref") or {}
                    if "certificate" in ref:
                        certs.append({"evidence": e, "finding": f["id"],
                                      "scope": certificate_scope(ref["certificate"]),
                                      **{k: ref["certificate"].get(k) for k in
                                         ("theorem", "target", "certifies", "result")},
                                      "currency": cur.get(e, unknown)})
            cx_items = []
            for c in sorted(mine, key=lambda c: (c["created_at"], c["id"])):
                cited = []
                for e in c.get("evidence") or []:
                    ref = (evid.get(e) or {}).get("ref") or {}
                    if "certificate" in ref:
                        cited.append({"evidence": e, "scope": certificate_scope(
                            ref["certificate"]), **{k: ref["certificate"].get(k) for k in
                                                    ("theorem", "target", "certifies",
                                                     "result")},
                            "currency": cur.get(e, unknown)})
                cx_items.append({**c, "analysis": analyse(c, ob), "certificates": cited,
                                 "currency": cur.get(c["id"], unknown)})
            rd_out.append({"corrections": list(corr), "printed": not corr,
                           "obligation": ob, "specialisations": specialisations(ob),
                           "counterexamples": cx_items,
                           "findings": [{"id": f["id"], "verdict": f.get("verdict"),
                                         "state": f.get("state"),
                                         "coverage": f.get("coverage"),
                                         "currency": cur.get(f["id"], unknown)} for f in fs],
                           "certificates": certs})
        out.append({"requirement": lid, "readings": rd_out})
    diffs, done = [], []
    for f in sorted(finds, key=lambda f: (f["created_at"], f["id"])):
        if not f.get("difference") or f["id"] not in in_force:
            continue
        # A resolution holds only as `difference_view` reads it now: a checked bridge Lean does
        # not check, or conditions left open, keep the difference with the open ones.
        dv = difference_view(f["difference"], (cur.get(f["id"]) or {}).get("resolution"))
        item = {"finding": f["id"], "requirement": f.get("requirement"), **dv,
                "state": f.get("state"), "by": f.get("created_by"),
                "currency": cur.get(f["id"], unknown)}
        (done if settled(dv) else diffs).append(item)
    hs, inherited = hints(records, snap, claim) if claim else ([], [])
    return {"estimates": out, "differences": diffs, "resolved": done,
            "hints": [h for h in hs if not h.get("settled_by")],
            "settled_hints": [h for h in hs if h.get("settled_by")], "inherited": inherited}


def empty(block: dict | None) -> bool:
    return not block or not any(block.get(k) for k in ("estimates", "differences", "resolved",
                                                       "hints", "inherited"))


# -- currency --------------------------------------------------------------------------------

def counterexample_currency(c: dict, records: list[dict], out: dict) -> dict:
    """A counterexample is stale when the reading it was made against changed (a quantifier, a
    domain, a constant's dependence, a passage that governs them), or when evidence it cites
    changed or is no longer what it cited."""
    changes = []
    ob = obligation(records, c["requirement"], c.get("reading") or ())
    if ob is None or ob["sha256"] != c.get("obligation_sha256"):
        changes.append({"counterexample": c["id"], "reading": c["requirement"],
                        "was": c.get("obligation_sha256"), "now": (ob or {}).get("sha256"),
                        "reason": "the reading it was made against changed"})
    # A passage that governs the reading changed in the paper since it was attached.
    for f in records:
        if f.get("kind") == "fragment" and f.get("requirement") in (ob or {}).get("involved", ()) \
                and f.get("state") == "accepted" and f.get("role") != "later use":
            changes += out.get(f["id"], {}).get("changes", [])
    by = {r["id"]: r for r in records}
    for e, pin in (c.get("evidence_pins") or {}).items():
        if e not in by or evidence_pin(by[e]) != pin:
            changes.append({"counterexample": c["id"], "evidence": e,
                            "reason": "the evidence it cites is not the one it was made with"})
    for e in c.get("evidence") or []:
        changes += out.get(e, {}).get("changes", [])
    return {"state": "stale" if changes else "current", "changes": changes}


def finding_changes(f: dict, records: dict, out: dict) -> list[dict]:
    changes = []
    for p in f.get("counterexamples") or []:
        c = records.get(p["id"])
        if c is None or counterexample_pin(c) != p["sha256"]:
            changes.append({"counterexample": p["id"],
                            "reason": "the counterexample changed since the finding cited it"})
        else:
            changes += out.get(p["id"], {}).get("changes", [])
    return changes


# -- text ------------------------------------------------------------------------------------

def lines(block: dict) -> list[str]:
    """The estimates block for the terminal."""
    out = []
    for est in block.get("estimates") or []:
        for rd in est["readings"]:
            ob = rd["obligation"]
            head = "printed reading" if rd["printed"] else \
                f"reading with the correction {', '.join(rd['corrections'])}"
            out.append(f"  estimate {est['requirement']}, {head}: {ob['text']}")
            for e in ob["order"]:
                if e["quantifier"] == "there is":
                    out.append(f"    {e['var']} may depend on "
                               f"{', '.join(e['may_depend_on']) or 'nothing chosen before it'}"
                               + (f"; independent of {', '.join(e['independent_of'])}"
                                  if e["independent_of"] else ""))
            for c in rd["counterexamples"]:
                a = c["analysis"]
                out.append(f"    counterexample {c['id']}: {a['standing_text']}"
                           + ("  [stale]" if c["currency"]["state"] == "stale" else ""))
                out.append(f"      {a['shows']}")
                for p in a["problems"]:
                    out.append(f"      problem: {p}")
                for o in a["open_obligations"]:
                    out.append(f"      open: {o}")
                if a["samples_note"]:
                    out.append(f"      {a['samples']} sample(s). {a['samples_note']}")
                for cert in c["certificates"]:
                    out.append(f"      certificate: {cert['scope']}"
                               + ("  [stale]" if cert["currency"]["state"] == "stale" else ""))
            for f in rd["findings"]:
                out.append(f"    finding {f['id']}" + (f": {f['verdict']}" if f.get("verdict")
                                                       else "")
                           + f" ({f['state']})"
                           + ("  [stale]" if f["currency"]["state"] == "stale" else ""))
            for cert in rd["certificates"]:
                out.append(f"    certificate: {cert['scope']}")
            for s in rd["specialisations"]:
                out.append(f"    to try: {s['try']} (from {s['rule']})")
    for d in block.get("differences") or []:
        how = resolution_text(d)
        out.append(f"  difference on {d['requirement']} ({d['feature']}, "
                   f"{outcome_text(d)}): paper {d['paper']}"
                   + (f"; Lean {d['lean']}" if d.get("lean") else "")
                   + (f"; transport inspected: {d['transport']}" if d.get("transport") else "")
                   + (f"; {how}" if how else ""))
    for d in block.get("resolved") or []:
        how = resolution_text(d) if d["outcome"] == "resolved" else f"no difference: {d['why']}"
        out.append(f"  {d['feature']} on {d['requirement']}, {how}")
    for h in block.get("hints") or []:
        out.append(f"  hint: {h['text']}")
    shown = {d.get("finding"): d for d in (block.get("differences") or [])
             + (block.get("resolved") or [])}
    for h in block.get("settled_hints") or []:
        s = h.get("settled") or {}
        # The outcome of the difference that dismissed it, as the reading shows it now.
        out.append(f"  hint dismissed by {h['settled_by']} "
                   f"({outcome_text(shown.get(h['settled_by']) or s)}"
                   f", {s.get('by')}): {h['text']} Why: {s.get('why')}")
    for h in block.get("inherited") or []:
        out.append(f"  {h['decl']} assumes {h['lean']}: inherited from {h['from']} "
                   f"({h['requirement']})")
    return out
