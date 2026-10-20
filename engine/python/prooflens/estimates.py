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
transport (a common extension, a checked bridge, an argument), or no difference at all.

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


def difference_content(d) -> dict:
    """A difference as a finding records it, checked."""
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
        r = {"by": _choice(res.get("by"), RESOLVED_BY, "the resolution", False),
             "text": _text(res.get("text"), "how it resolves the difference (`text`)", True)}
        if res.get("theorem") not in (None, ""):
            r["theorem"] = _text(res["theorem"], "the theorem").strip()
        if r["by"] == "checked bridge" and not r.get("theorem"):
            raise _err("a checked bridge names its theorem (`resolution.theorem`)")
        extra = set(res) - {"by", "text", "theorem"}
        if extra:
            raise _err(f"a resolution has no field {', '.join(sorted(extra))}")
        out["resolution"] = r
    elif res is not None:
        raise _err("only a resolved difference has a resolution")
    if out["outcome"] == "no difference":
        out["why"] = _text(d.get("why"), "why there is no difference (`why`)", True)
    elif d.get("why") not in (None, ""):
        raise _err("`why` belongs to a difference whose outcome is `no difference`")
    if d.get("hint") is not None:
        h = d["hint"]
        if not isinstance(h, dict) or not isinstance(h.get("decl"), str) or \
                type(h.get("binder")) is not int:
            raise _err("a hint is {decl, binder}, as the reading lists it")
        out["hint"] = {"decl": h["decl"], "binder": h["binder"]}
    return out


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


def finding_fields(out: dict, rec: dict, ws: dict, cur: dict | None, repin: bool) -> None:
    """The fields a finding adds for an estimate: a structured difference, a verdict on a
    printed step, and the counterexamples it rests on (pinned as they were)."""
    from .steps import STATE
    if rec.get("difference") is not None:
        out["difference"] = difference_content(rec["difference"])
        if not out.get("requirement"):
            raise _err("a difference is attached to the requirement it affects (`requirement`)")
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
    from .simple import ViewError, built_modules, probe_modules, target_fingerprint
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
            raise ViewError(failed[mod])
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
    Lean; the rest is read from the facts store, or asked of Lean when `check_now` is set."""
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
        if doc.get("status") == "not checked" and not changes:
            return {"state": "unchecked", "changes": [], "reason": doc["reason"]}
        if doc.get("status") != "not checked":
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

def hints(records: list[dict], snap, claim: str) -> tuple[list[dict], list[dict]]:
    """Computed pointers, from the claim's alignments: each hypothesis of an aligned Lean
    statement that no alignment associates with a requirement (an extra Lean hypothesis to
    inspect, unless a difference finding dismissed or resolved it), and each hypothesis aligned
    with a requirement that a standing assumption governs (inherited by the claim, not an extra
    hypothesis). A hint is a pointer; it is never a finding."""
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
    settled = {}
    for f in records:
        d = (f.get("difference") or {})
        if f.get("kind") == "finding" and d.get("hint") and d.get("outcome") in (
                "no difference", "resolved", "difference"):
            settled[(d["hint"]["decl"], d["hint"]["binder"])] = f["id"]
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
                        **({"settled_by": settled[(decl, i)]} if (decl, i) in settled else {})})
    return out, inherited


# -- the block a claim's reading shows ---------------------------------------------------------

def analysis(records: list[dict], cur: dict, snap=None, claim: str | None = None) -> dict:
    """The estimates block of a claim's reading: for each requirement that has a
    counterexample or a verdict, its printed reading and each corrected reading,
    each with its obligation, counterexamples (analysed against that reading), the findings and
    certificates that are evidence for it; the differences recorded, open ones apart from
    resolved ones; and the computed hints."""
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
    diffs, settled = [], []
    for f in sorted(finds, key=lambda f: (f["created_at"], f["id"])):
        if not f.get("difference") or f["id"] not in in_force:
            continue
        item = {"finding": f["id"], "requirement": f.get("requirement"), **f["difference"],
                "state": f.get("state"), "by": f.get("created_by"),
                "currency": cur.get(f["id"], unknown)}
        (settled if f["difference"]["outcome"] in ("resolved", "no difference")
         else diffs).append(item)
    hs, inherited = hints(records, snap, claim) if claim else ([], [])
    return {"estimates": out, "differences": diffs, "resolved": settled,
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
        out.append(f"  difference on {d['requirement']} ({d['feature']}, "
                   f"{OUTCOME_WORDS[d['outcome']]}): paper {d['paper']}"
                   + (f"; Lean {d['lean']}" if d.get("lean") else "")
                   + (f"; transport inspected: {d['transport']}" if d.get("transport") else ""))
    for d in block.get("resolved") or []:
        how = (f"resolved by {d['resolution']['by']}: {d['resolution']['text']}"
               if d["outcome"] == "resolved" else f"no difference: {d['why']}")
        out.append(f"  {d['feature']} on {d['requirement']}, {how}")
    for h in block.get("hints") or []:
        out.append(f"  hint: {h['text']}")
    for h in block.get("inherited") or []:
        out.append(f"  {h['decl']} assumes {h['lean']}: inherited from {h['from']} "
                   f"({h['requirement']})")
    return out
