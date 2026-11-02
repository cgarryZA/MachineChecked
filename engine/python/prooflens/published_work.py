"""The workspace records a published audit carries (`prooflens/published-work@1`).

An audit publishes, per claim, the records of its auditors' workspaces (`workspace.py`) that the
auditor has accepted: the requirements of the claim, the passages accepted as governing them,
the alignments with Lean, and the submitted findings (superseded ones included, with the reason)
with the evidence, compositions and counterexamples they cite (and the evidence those
compositions and counterexamples cite). Proposed and removed passages, draft findings, evidence
no submitted finding cites, questions, exposure, resume state and the review protocol's drafts
stay in the workspace.

Each record keeps its author and times, its pins and its currency against the published build,
computed over the published records alone. The paper's `publish` settings apply: a passage's
text, file and lines only when the source text is published, a Lean target's text only when the
Lean is, and the auditor's prose (notes, arguments, questions, reasons, a counterexample's
specialisation and reduction) only when reviews are; a record names the prose fields it leaves
out (`withheld`), never their words. A difference shows its paper expression when
the source text is published and its Lean expression when the Lean is. A cited fact
inside a proof keeps its basis, "established inside this proof under this context", and its
pins; its proposition and context are Lean text. Its currency, and that of a cited application
or certificate, is checked against the Lean project the export was built from, asking Lean when
the facts store has no answer; it is `unchecked` without that project or when Lean could not
look (a module not built, a failed request). A composition keeps its structure
(steps, the evidence each rests on, identifications, obligations and their state) always, the
objects and substitutions it names when the Lean is published, and its prose when reviews are.
Its basis is `checked_bridge` only when its bridge is checked against the Lean project at
export (from the facts store); otherwise it is the auditor's composition. A finding recorded as
`checked_bridge` reads the same way: as a checked bridge only while the bridge it rests on (its
composition's, or its own) is checked at export, else as `reviewed_composition` with
`recorded_basis` and the reasons.

A submitted finding also carries what it rests on (`dependencies`: each part with its content
identity, as `dependencies.py` records it at submission), a region's place only with the source
text and a Lean target's text only with the Lean. Each version map the workspace keeps (`changes
--map --save`) is published per claim (`revisions`): the map's entries for the claim, and what it
says of the claim's published findings, the evidence quoting the paper and the passages attached
to its requirements (`reopen.py`, over the published records alone, the Lean side against the
published build when the map's later release is the build's). A map's places, reasons, diffs and
macro names are manuscript text: without the source text an entry keeps its class, claims,
numbers and digests, in words that quote no place or text of the paper. Neither release's
recorded status or reviews are published with it.

The records sit in `data/work/<claim file>`, one file per claim that has any, which the claim's
passport names in `work`. The main results each workspace saves (`workspace main`) sit in the
data index, `main_results`: the claims and declarations chosen, who chose them and when, the
release and project commit they were checked against, and what the published build lacks of
them. They are readings: nothing here is an input to a status.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import requirements as rq
from . import workspace as wsp
from .util import write_json

SCHEMA = "prooflens/published-work@1"
DIR = "work"
FILE_LIMIT = 2_000_000  # bytes per claim file; the site's loader refuses a larger one

COMMON = ("id", "kind", "claim", "clause", "rev", "created_at", "created_by", "updated_at",
          "updated_by", "pins")
PROSE = ("note", "argument", "question", "would_decide", "reason", "why_rejected")
# A counterexample's mathematics, as the auditor wrote it.
CX_PROSE = ("specialisation", "reduced", "violation", "admissibility", "samples")
FIELDS = {
    "requirement": ("local_id", "form", "text", "origin", "parent", "binds", "domain",
                    "independent_of", "depends_on", "corrects"),
    "fragment": ("requirement", "role", "origin", "scope", "state", "state_by", "state_at",
                 "suggestion"),
    "alignment": ("requirements", "relation", "fragments"),
    "finding": ("coverage", "basis", "confidence", "bridge", "requirement", "state",
                "submitted_at", "supersedes", "composition", "verdict", "counterexamples"),
    "evidence": ("role",),
    "composition": ("coverage",),
    "counterexample": ("requirement", "reading", "obligation_sha256", "evidence_pins",
                       "evidence"),
}
REVIEWER = ("id", "kind", "name", "model", "identity")


class PublishError(RuntimeError):
    """Workspace records that cannot be published as they are."""


def accepted(ws: dict) -> dict[str, dict]:
    """The records of `ws` its auditor has accepted: every requirement and alignment, the
    accepted passages, the submitted findings, the compositions and counterexamples they rest
    on, and the evidence those findings, compositions and counterexamples cite."""
    recs = ws.get("records") or {}
    out = {}
    for rid, r in recs.items():
        k = r.get("kind")
        if k in ("requirement", "alignment") or \
                (k == "fragment" and r.get("state") == "accepted") or \
                (k == "finding" and r.get("state") == "submitted"):
            out[rid] = r
    for r in list(out.values()):
        c = recs.get(r.get("composition") or "")
        if r.get("kind") == "finding" and (c or {}).get("kind") == "composition":
            out[c["id"]] = c
        if r.get("kind") == "finding":
            for x in r.get("counterexamples") or []:
                if (recs.get(x["id"]) or {}).get("kind") == "counterexample":
                    out[x["id"]] = recs[x["id"]]
    for r in list(out.values()):
        if r.get("kind") in ("finding", "composition", "counterexample"):
            for e in r.get("evidence") or []:
                if (recs.get(e) or {}).get("kind") == "evidence":
                    out[e] = recs[e]
    return out


def _region(reg: dict, source_text: bool) -> dict:
    if source_text:
        return {k: reg[k] for k in (*rq.LOCATION, "sha256", "text") if reg.get(k) is not None}
    return {k: reg[k] for k in ("paper", "sha256") if reg.get(k) is not None}


def _changes(changes: list[dict], pub) -> list[dict]:
    """The changes a currency names, as `pub` allows: a changed region's place only with the
    source text, and the texts of a sub-term an alignment names (`at`) only with the Lean."""
    out = []
    for c in changes:
        c = dict(c)
        if not pub.source_text:
            c.pop("region", None)
            c.pop("lines", None)
        if not pub.lean and c.get("at") is not None:
            c.pop("was", None)
            c.pop("now", None)
            c["reason"] = (f"{c.get('decl')}: the sub-term {c['at']} is not the expression it "
                           "was recorded with")
        out.append(c)
    return out


FACT_PINS = ("decl", "module", "at", "fact_hash", "proof_hash", "kind", "name", "head")
CERT_PINS = ("theorem", "target", "certifies", "module", "file_sha256", "target_fingerprint",
             "axioms", "lean", "toolchain", "manifest_sha256", "result", "reasons")
CERT_LEAN = ("file", "type", "target_statement")
FACT_LEAN = ("type", "assumptions", "variables", "cases", "source")


def _ref(ref: dict, pub) -> dict:
    if "fact" in ref:
        # A fact inside a proof: where it is and its pins always, its basis always (it is not an
        # exported theorem), its proposition and context only when the Lean is published.
        f = ref["fact"]
        from .proof_facts import BASIS
        return {"fact": {**{k: f[k] for k in FACT_PINS if f.get(k) is not None},
                         **({k: f[k] for k in FACT_LEAN if f.get(k) is not None}
                            if pub.lean else {}),
                         "basis": BASIS}}
    if "app" in ref:
        # An application: where it is and its digest always, its arguments, premises and
        # result only when the Lean is published.
        a = ref["app"]
        keep = ("callee", "module", "id", "caller", "via", "app_hash") + \
            (("arguments", "premises", "result") if pub.lean else ())
        return {"app": {k: a[k] for k in keep if a.get(k) is not None}}
    if "decl" in ref:
        return {k: ref[k] for k in ("decl", "module", "build", "fingerprint", "digest")
                if ref.get(k) is not None}
    if "certificate" in ref:
        # A certificate: what Lean checked and its pins always; its proposition and source
        # file only when the Lean is published.
        c = ref["certificate"]
        return {"certificate": {k: c[k] for k in CERT_PINS if c.get(k) is not None}
                | ({k: c[k] for k in CERT_LEAN if c.get(k) is not None} if pub.lean else {})}
    if "source" in ref:
        return {"source": dict(ref["source"]) if pub.lean else {}}
    p = ref.get("paper") or {}
    return {"paper": {"claim": p.get("claim"),
                      **({"quote": p.get("quote") or ""} if pub.source_text else {})}}


def _difference(d: dict, pub) -> dict:
    out = {k: d[k] for k in ("feature", "outcome", "hint") if d.get(k) is not None}
    if pub.source_text:
        out["paper"] = d["paper"]
    if pub.lean and d.get("lean"):
        out["lean"] = d["lean"]
    if d.get("resolution"):
        out["resolution"] = {k: v for k, v in d["resolution"].items()
                             if k != "text" or pub.reviews}
    if pub.reviews:
        out.update({k: d[k] for k in ("conditions", "transport", "why") if d.get(k)})
    return out


def _composition(r: dict, pub, view: dict) -> dict:
    """A composition's structure always; the objects and substitutions it names when the Lean
    is published, its prose when reviews are; its computed basis, gaps and bridge check."""
    steps = []
    for st in r.get("steps") or []:
        x = {k: st[k] for k in ("id", "requirements", "uses", "after") if st.get(k)}
        if pub.lean and st.get("substitutions"):
            x["substitutions"] = st["substitutions"]
        if pub.reviews:
            x.update({k: st[k] for k in ("establishes", "inference", "note") if st.get(k)})
        steps.append(x)
    idents = []
    for it in r.get("identifications") or []:
        x = {"left": {"step": it["left"]["step"]}, "right": {"step": it["right"]["step"]},
             "relation": it["relation"], "how": it["how"]}
        if pub.lean:
            x["left"]["object"], x["right"]["object"] = it["left"]["object"], \
                it["right"]["object"]
        if it.get("evidence"):
            x["evidence"] = it["evidence"]
        if pub.reviews and it.get("note"):
            x["note"] = it["note"]
        idents.append(x)
    obls = []
    for o in r.get("obligations") or []:
        x = {k: o[k] for k in ("id", "kind", "state", "by") if o.get(k)}
        if pub.reviews:
            x.update({k: o[k] for k in ("text", "note") if o.get(k)})
        obls.append(x)
    out = {"steps": steps, "evidence": list(r.get("evidence") or []),
           "basis": view["basis"], "gaps": view["gaps"], "complete": view["complete"],
           "next_step": view["next_step"]}
    if idents:
        out["identifications"] = idents
    if obls:
        out["obligations"] = obls
    if pub.reviews and r.get("statement"):
        out["statement"] = r["statement"]
    b = r.get("bridge")
    if b:
        out["bridge"] = {k: b[k] for k in ("theorem", "target", "module", "axioms",
                                           "target_fingerprint", "source_sha256", "checked_at")
                         if b.get(k) is not None}
        if pub.lean and b.get("type"):
            out["bridge"]["type"] = b["type"]
        chk = view.get("bridge_check") or {}
        out["bridge_check"] = {"state": chk.get("state") or "unchecked",
                               "reasons": list(chk.get("reasons") or [])}
    return out


def withheld_prose(r: dict) -> list[str]:
    """The fields of the auditor's prose a record has, which an export that does not publish
    reviews leaves out: named, never quoted, so that a reader can say what is withheld."""
    fields = PROSE + (CX_PROSE if r.get("kind") == "counterexample" else ())
    return [f for f in fields if r.get(f) not in (None, "", [], {})]


def public_record(r: dict, pub, currency: dict, in_force: set[str],
                  compositions: dict | None = None,
                  records: list[dict] | None = None, bridges: dict | None = None,
                  dependencies: dict | None = None) -> dict:
    """One accepted record with what `pub` allows; `compositions` holds each composition as
    `composition.view` gives it, and `bridges` the bridge check of each finding recorded as a
    checked bridge (`composition.finding_bridge`; without it, a finding's own bridge is not
    counted). A counterexample also carries what it can show against its reading
    (`estimates.analyse`, over the published `records`). A finding carries what it rests on
    (`dependencies`, as `dependencies.of` gives them), as `public_dependencies` publishes it."""
    k = r["kind"]
    out = {f: r[f] for f in (*COMMON, *FIELDS[k]) if r.get(f) is not None}
    if pub.reviews:
        out.update({f: r[f] for f in PROSE if r.get(f) not in (None, "")})
    else:
        withheld = withheld_prose(r)
        if withheld:
            out["withheld"] = withheld
    if k == "finding" and r.get("difference"):
        out["difference"] = _difference(r["difference"], pub)
    if k == "counterexample":
        from . import estimates as est
        if pub.reviews:
            out.update({f: r[f] for f in CX_PROSE if r.get(f) not in (None, [], {})})
        ob = est.obligation(records or [], r["requirement"], r.get("reading") or ())
        a = est.analyse(r, ob)
        out["reading_text"] = (ob or {}).get("text")
        out["analysis"] = {f: a[f] for f in ("form", "decisive", "standing", "standing_text",
                                             "family", "fixed", "problems", "admissibility",
                                             "samples", "samples_note")}
        if pub.reviews:
            out["analysis"].update(shows=a["shows"], open_obligations=a["open_obligations"])
    cur = currency.get(r["id"]) or {"state": "unchecked", "changes": []}
    out["currency"] = {"state": cur["state"],
                       "changes": _changes(cur.get("changes") or [], pub)}
    if k == "fragment":
        if r.get("region"):
            out["region"] = _region(r["region"], pub.source_text)
        else:
            out["passage"] = {f: (r.get("passage") or {}).get(f) for f in ("claim", "sha256")}
    elif k == "alignment":
        out["lean"] = [{f: t[f] for f in ("decl", "module", "build", "fingerprint", "digest",
                                          *rq.SUBTARGETS, "target")
                        if t.get(f) is not None and (f != "target" or pub.lean)}
                       for t in r.get("lean") or []]
    elif k == "finding":
        out["evidence"] = list(r.get("evidence") or [])
        out["in_force"] = r["id"] in in_force
        if dependencies is not None:
            out["dependencies"] = public_dependencies(dependencies, pub)
        from . import composition as cp
        chk = bridges[r["id"]] if bridges is not None and r["id"] in bridges else \
            cp.finding_bridge(r, compositions or {}, None, None)
        if chk is not None and r.get("bridge") and not r.get("composition"):
            out["bridge_check"] = {"state": chk.get("state") or "unchecked",
                                   "reasons": list(chk.get("reasons") or [])}
        if chk is not None and chk.get("state") != "checked":
            # No bridge is checked at export (its composition's, or its own): the finding reads
            # as the auditor's composition.
            out.update(basis="reviewed_composition", recorded_basis="checked_bridge",
                       basis_reason=list(chk.get("reasons") or []))
    elif k == "evidence":
        out["ref"] = _ref(r.get("ref") or {}, pub)
    elif k == "composition":
        out.update(_composition(r, pub, (compositions or {})[r["id"]]))
    return out


# -- what a finding rests on, and what a revision of the paper reopens --------------------------

# What a published dependency keeps of an item (`dependencies.collect`): ids, roles and content
# identities; a region's place only with the source text, a Lean target's text only with the Lean.
DEP_FIELDS = ("dependency", "record", "via", "claim", "sha256", "requirement", "role", "origin",
              "requirements", "relation", "theorem", "target", "target_fingerprint",
              "source_sha256")
UNKNOWN_FIELDS = ("dependency", "record", "claim", "requirement", "why")


def _dep_ref(ref: dict, pub) -> dict:
    """An evidence reference's pins as a published dependency keeps them: a quotation only with
    the source text, a certificate's proposition and file and a source line only with the
    Lean."""
    if "paper" in ref:
        p = ref["paper"] or {}
        return {"paper": {k: p[k] for k in ("claim", "sha256", "quote")
                          if p.get(k) is not None and (k != "quote" or pub.source_text)}}
    if "source" in ref:
        return {"source": dict(ref["source"] or {}) if pub.lean else {}}
    if "certificate" in ref:
        return {"certificate": {k: v for k, v in (ref["certificate"] or {}).items()
                                if pub.lean or k not in CERT_LEAN}}
    return json.loads(json.dumps(ref))


def _dependency(it: dict, pub) -> dict:
    out = {k: it[k] for k in DEP_FIELDS if it.get(k) is not None}
    if isinstance(it.get("region"), dict):
        out["region"] = _region(it["region"], pub.source_text)
    if isinstance(it.get("passage"), dict):
        out["passage"] = {k: it["passage"].get(k) for k in ("claim", "sha256")}
    if isinstance(it.get("lean"), list):
        from .dependencies import TARGET_PINS
        out["lean"] = [{k: t[k] for k in TARGET_PINS
                        if t.get(k) is not None and (k != "target" or pub.lean)}
                       for t in it["lean"] if isinstance(t, dict)]
    if isinstance(it.get("ref"), dict):
        out["ref"] = _dep_ref(it["ref"], pub)
    if it.get("why") and "dependency" in it and not it.get("ref"):
        out["why"] = it["why"]
    return out


def public_dependencies(deps: dict, pub) -> dict:
    """What a finding rests on (`dependencies.py`) as `pub` allows: each part with its content
    identity, the parts that cannot be identified with why, the evidence kinds, and when they were
    recorded (`at`, absent for a finding submitted before findings recorded them)."""
    out = {"kinds": list(deps.get("kinds") or []),
           "items": [_dependency(it, pub) for it in deps.get("items") or []],
           "unknown": [{k: u[k] for k in UNKNOWN_FIELDS if u.get(k) is not None}
                       for u in deps.get("unknown") or []]}
    if deps.get("at"):
        out["at"] = deps["at"]
    return out


# The words of a version map's classes, for a paper whose source text is not published (the map's
# own reasons quote places and macro names).
CLASS_WORDS = {"unchanged": "the same text", "moved": "the same text at another place",
               "context-changed": "the same text; what it is read with changed",
               "changed": "its text changed",
               "removed": "no passage of the later revision has its text",
               "ambiguous": "the version map cannot tell which later claim it is",
               "unknown": "the version map cannot follow it",
               "new": "no earlier claim is matched to it", "later": "read at the later revision"}
# Why a part is not known to be current (`reopen.py`), when the words name only claims, numbers
# and declarations; the others quote the map's places and reasons.
SAFE_CAUSES = ("not in the map", "not recorded", "another text", "definitions not recorded")
SIDE = ("claim", "number", "kind", "label", "scope", "sha256", "pin_sha256", "pin")
SIDE_SOURCE = ("location", "bounds")


def _context(x: dict, pub) -> dict:
    """A change of what a passage is read with: in full with the source text; else what it is,
    how it changed and the claim it names, without its text, diff or macro name."""
    if pub.source_text:
        return dict(x)
    out = {k: x[k] for k in ("what", "change", "claim", "number", "via", "part", "names",
                             "through") if x.get(k) is not None}
    if x.get("claim_change"):
        out["claim_change"] = {"class": x["claim_change"].get("class")} \
            if isinstance(x["claim_change"], dict) else {}
    return out


def _context_words(x: dict, pub) -> str:
    from .version_map import _context_words as words
    if pub.source_text or x.get("what") != "macro":
        return words(x)
    return f"the definition of a macro it uses {x.get('change')}"


def _map_row(row: dict, pub) -> dict:
    """One entry of a kept version map as `pub` allows: its class, how the match was found and
    each side's claim, number and digests always; places, the map's reasons, diffs and context
    only with the source text. Neither release's recorded status or reviews."""
    out = {"class": row.get("class"), "by": list(row.get("by") or [])}
    for k in ("renumbered", "moved"):
        if row.get(k):
            out[k] = row[k]
    for side in ("from", "to"):
        x = row.get(side)
        out[side] = None if not isinstance(x, dict) else {
            k: x[k] for k in SIDE + (SIDE_SOURCE if pub.source_text else ())
            if x.get(k) is not None}
    if row.get("candidates"):
        out["candidates"] = [{k: c.get(k) for k in ("claim", "by") if c.get(k) is not None}
                             for c in row["candidates"] if isinstance(c, dict)]
    if row.get("resolved"):
        out["resolved"] = {k: row["resolved"][k] for k in ("by", "was")
                           if row["resolved"].get(k)}
    if row.get("context"):
        out["context"] = [_context(x, pub) for x in row["context"]]
    if pub.source_text:
        out["reason"] = row.get("reason")
        for k in ("change", "surroundings_changed", "printed_at", "proposed"):
            if row.get(k) not in (None, False, [], {}):
                out[k] = row[k]
    else:
        out["reason"] = CLASS_WORDS.get(row.get("class"), "")
        if row.get("context"):
            out["reason"] += " (" + "; ".join(dict.fromkeys(
                _context_words(x, pub) for x in row["context"])) + ")"
    return out


def _side(x: dict | None, pub) -> dict | None:
    if not isinstance(x, dict):
        return None
    return {k: x[k] for k in ("claim", "number") + (("location",) if pub.source_text else ())
            if x.get(k) is not None}


def _label(x: dict | None, cid: str | None) -> str:
    n = (x or {}).get("number")
    return f"{n} ({cid})" if n else str(cid)


def _plain_text(it: dict) -> str:
    """A part a finding rests on, in words that quote no place of the paper."""
    dep = it.get("dependency")
    if dep == "context":
        if it.get("region"):
            return f"a passage it reads as the {it.get('role')} of {it.get('requirement')}"
        return (f"the passage of {(it.get('passage') or {}).get('claim')} ({it.get('role')} of "
                f"{it.get('requirement')})")
    if dep == "paper":
        return f"the passage of {((it.get('ref') or {}).get('paper') or {}).get('claim')} it quotes"
    if dep == "bridge":
        return (f"the passage that bridge {it.get('theorem')} for {it.get('target')} was checked "
                "against")
    return f"the passage of {it.get('claim')}"


def _plain_question(fid: str, req: str | None, o: dict, it: dict) -> str:
    """The question a reopened part asks, in words that quote no place or text of the paper."""
    what = f"finding {fid}" + (f" (on {req})" if req else "")
    cls = (o.get("change") or {}).get("class")
    if it.get("dependency") == "context" and it.get("region"):
        role = f"the {it.get('role')} of {it.get('requirement')}"
        if cls == "removed":
            return (f"The passage {what} reads as {role} is not in the later revision: what "
                    f"governs {it.get('requirement')} now?")
        return f"Does {what} still hold now that the passage it reads as {role} changed?"
    side = o.get("later") or o.get("earlier") or {}
    label = _label(side, side.get("claim"))
    if cls == "removed":
        return (f"{_label(o.get('earlier'), (o.get('earlier') or {}).get('claim'))} is not in the "
                f"later revision: which claim, if any, does {what} now concern? A finding is not "
                "moved to another claim.")
    if cls == "context-changed":
        return f"Does {what} still hold for {label} now that what it is read with changed?"
    return f"Does {what} still hold for the changed text of {label}?"


def _part(o: dict, pub, fid: str | None = None, req: str | None = None) -> dict:
    """One part of a record across a revision (`reopen.py`) as `pub` allows. With the source
    text, as the map gives it; without it, its state, class and claims, with words that quote no
    place or text of the paper."""
    it = o.get("dependency") or {}
    if pub.source_text:
        out = {k: v for k, v in o.items() if k != "dependency"}
        if "dependency" in o:
            out["dependency"] = _dependency(it, pub)
        if isinstance(out.get("change"), dict) and out["change"].get("context"):
            out["change"] = {**out["change"],
                             "context": [_context(x, pub) for x in out["change"]["context"]]}
        return out
    out = {"state": o["state"], "earlier": _side(o.get("earlier"), pub),
           "later": _side(o.get("later"), pub)}
    if o.get("class"):
        out["class"] = o["class"]
    if "dependency" in o:
        out["dependency"] = _dependency(it, pub)
        out["text"] = _plain_text(it)
    if o.get("change"):
        ch = o["change"]
        ctx = [_context(x, pub) for x in ch.get("context") or []]
        out["change"] = {"class": ch.get("class"),
                         "reason": CLASS_WORDS.get(ch.get("class"), "it changed") + (
                             " (" + "; ".join(dict.fromkeys(_context_words(x, pub)
                                                            for x in ch.get("context") or []))
                             + ")" if ctx else ""),
                         **({"context": ctx} if ctx else {})}
    if o["state"] == "unchecked":
        cands = [c.get("claim") for c in o.get("candidates") or [] if isinstance(c, dict)]
        if cands:
            out["candidates"] = [{"claim": c} for c in cands]
        if o.get("cause") in SAFE_CAUSES or (not o.get("cause") and it.get("why")):
            # Said with claims, numbers and declarations only.
            out["why"] = o.get("why") or it.get("why")
        elif cands:
            out["why"] = (CLASS_WORDS["ambiguous"] + f" (candidates: {', '.join(cands)}); the "
                          "maintainer resolves it with --match")
        else:
            out["why"] = CLASS_WORDS["unknown"]
    if o["state"] == "reopened" and fid is not None:
        out["question"] = _plain_question(fid, req, o, it)
    return out


def _build_part(b: dict, pub, fid: str, req: str | None) -> dict:
    """The Lean side of a finding across a revision, against the published build, as `pub`
    allows: a declaration's statement in both releases only with the Lean."""
    from .dependencies import change_text
    what = f"finding {fid}" + (f" (on {req})" if req else "")
    changes = []
    for c in b.get("changes") or []:
        (ch,) = _changes([{k: v for k, v in c.items()
                           if k not in ("words", "question", "statement")}], pub)
        ch["words"] = change_text(ch)
        ch["question"] = f"Does {what} still hold now that {ch['words']}?"
        if pub.lean and c.get("statement"):
            ch["statement"] = c["statement"]
        changes.append(ch)
    out = {"state": b.get("state"), "changes": changes}
    if b.get("unknown"):
        out["unknown"] = [{k: u[k] for k in UNKNOWN_FIELDS if u.get(k) is not None}
                          for u in b["unknown"]]
    return out


def _reopened(f: dict, pub) -> dict:
    out = {"id": f["id"], "claim": f["claim"], "state": f["state"], "kinds": f.get("kinds") or [],
           "class": f.get("class"), "earlier": _side(f.get("earlier"), pub),
           "later": _side(f.get("later"), pub),
           "paper": [_part(o, pub, f["id"], (f.get("finding") or {}).get("requirement"))
                     for o in f.get("paper") or []]}
    if f.get("build") is not None:
        out["build"] = _build_part(f["build"], pub, f["id"],
                                   (f.get("finding") or {}).get("requirement"))
    return out


def revisions(ws: dict, kept: dict, snap, pub_for, root: Path | None = None,
              work_dir: Path | None = None) -> dict[str, list[dict]]:
    """Per claim, what each version map the workspace `ws` keeps says of the claim and of its
    accepted records (`kept`) across that revision of the paper (`reopen.reopen`, over the
    published records alone, the Lean side checked against the published build `snap` when the
    map's later release is the build's), as the claim's paper's `pub_for` allows: the map's
    entries for the claim (`claims`), its findings in force with each part they rest on
    (`findings`), the evidence quoting the paper and the passages attached to its requirements
    (`evidence`, `passages`). A finding is named by its id: its own record is published beside
    it. A map of a paper this export does not publish is left out."""
    from . import reopen as ro
    published, paper_of = {}, {}
    for c in snap.claims:
        published.setdefault(c.get("paper"), c["id"])
        paper_of[c["id"]] = c.get("paper")
    out: dict[str, list[dict]] = {}
    for m in ws.get("version_maps") or []:
        paper = (m or {}).get("paper")
        if paper not in published:
            continue
        pub = pub_for(published[paper])
        texts = ro.lean_texts(work_dir, m) if pub.lean and work_dir is not None else None
        doc = ro.reopen(m, {"id": ws.get("id"), "records": kept}, snap, root, texts,
                        root is not None)
        cids = {r.get("claim") for r in kept.values()}
        for cid in sorted(c for c in cids if c and paper_of.get(c) == paper):
            rows = [_map_row(r, pub) for r in m.get("claims") or []
                    if cid in ((r.get("from") or {}).get("claim"), (r.get("to") or {}).get("claim"))]
            fs = [_reopened(f, pub) for f in doc["findings"] if f["claim"] == cid]
            ev = [{**{k: r[k] for k in ("id", "claim", "role") if r.get(k) is not None},
                   **_part(r, pub)} for r in doc["evidence"] if r.get("claim") == cid]
            ps = [{**{k: r[k] for k in ("id", "claim", "requirement", "role", "state")
                      if r.get(k) is not None}, **_part(r, pub)}
                  for r in doc["passages"] if r.get("claim") == cid]
            if not (rows or fs or ev or ps):
                continue
            out.setdefault(cid, []).append({
                "map": ro.identity(m), "build_checked": doc["build_checked"],
                "claims": rows, "findings": fs, "evidence": ev, "passages": ps})
    return out


def readings(work_dir: Path, snap, pub_for, claims: set[str],
             root: Path | None = None) -> dict[str, list[dict]]:
    """Per claim of `claims`, one reading per workspace that has accepted records for it: the
    workspace, its auditor and mode, its records in the form `public_record` gives (a finding
    with what it rests on), and what each version map the workspace keeps says of them
    (`revisions`).
    `pub_for(claim)` is the publication settings of the claim's paper. Cited facts, applications
    and certificates are checked against the Lean project at `root`, asking Lean when the facts
    store has no answer (without it they are `unchecked`); a composition's bridge is checked
    against it from the facts store (without it, or when it is not stored current, the bridge is
    not counted)."""
    from . import composition as cp
    from .dependencies import of as dependencies_of
    out: dict[str, list[dict]] = {}
    for _, ws in wsp.list_all(work_dir):
        kept = accepted(ws)
        kept = {rid: r for rid, r in kept.items() if r.get("claim") in claims}
        if not kept:
            continue
        across = revisions(ws, kept, snap, pub_for, root, work_dir)
        cur = wsp.currency({"records": kept}, snap, root, check_facts=root is not None)
        in_force = {r["id"] for r in wsp.current_findings({"records": kept})}
        comps = {r["id"]: cp.view(r, {"records": kept}, cur, cp.bridge_currency(
                     r["bridge"], r["claim"], snap, root) if r.get("bridge") else None)
                 for r in kept.values() if r["kind"] == "composition"}
        bridges = {r["id"]: cp.finding_bridge(r, comps, snap, root)
                   for r in kept.values() if r["kind"] == "finding"}
        who = ws.get("reviewer") or {}
        by_claim: dict[str, list[dict]] = {}
        for r in kept.values():
            by_claim.setdefault(r["claim"], []).append(r)
        for cid, recs in sorted(by_claim.items()):
            pub = pub_for(cid)
            order = {r["id"]: (i, d) for i, (r, d) in enumerate(rq._order(
                [r for r in recs if r["kind"] == "requirement"]))}
            group: dict[str, list[dict]] = {"requirements": [], "fragments": [],
                                            "alignments": [], "findings": [], "evidence": [],
                                            "compositions": [], "counterexamples": []}
            for r in sorted(recs, key=lambda r: (order.get(r["id"], (0, 0))[0],
                                                 r.get("created_at") or "", r["id"])):
                item = public_record(r, pub, cur, in_force, comps, recs, bridges,
                                     dependencies_of(r, kept) if r["kind"] == "finding"
                                     else None)
                if r["kind"] == "requirement":
                    item["depth"] = order[r["id"]][1]
                group[{"requirement": "requirements", "fragment": "fragments",
                       "alignment": "alignments", "finding": "findings",
                       "evidence": "evidence",
                       "composition": "compositions",
                       "counterexample": "counterexamples"}[r["kind"]]].append(item)
            out.setdefault(cid, []).append({
                "workspace": ws["id"], "mode": ws.get("mode"),
                "reviewer": {k: who[k] for k in REVIEWER if who.get(k) is not None},
                **group, **({"revisions": across[cid]} if across.get(cid) else {})})
    return out


LEFT_OUT = ("main results this published data cannot name: claims of papers it does not "
            "publish, or declarations it holds no record of")


def main_results(work_dir: Path, snap, root: Path | None = None) -> list[dict]:
    """The main results each workspace of `work_dir` saves, attributed to its workspace and
    auditor, with who saved them, when, the release and project commit they were checked
    against (`pins`), and what the published data `snap` lacks of them (`problems`). An entry
    the data cannot name is counted in `left_out`, never named: a claim of a paper it does not
    publish, or a declaration it neither records nor can look up (it keeps no index of the
    project), which may belong to a paper it does not publish."""
    papers = {p.get("id") for p in snap.index.get("papers") or []}
    index = snap.lean_index()
    out = []
    for _, ws in wsp.list_all(work_dir):
        sel = ws.get("main_results")
        if not sel:
            continue
        kept, left = [], 0
        for e in sel.get("selected") or []:
            if e.get("claim"):
                ok = snap.chunk(e["claim"]) is not None or e["claim"].split(":", 1)[0] in papers
            else:
                ok = index is not None or bool(snap.store_records(e.get("decl")))
            if ok:
                kept.append(e)
            else:
                left += 1
        who = ws.get("reviewer") or {}
        out.append({"workspace": ws["id"], "mode": ws.get("mode"),
                    "reviewer": {k: who[k] for k in REVIEWER if who.get(k) is not None},
                    "selected": kept, "by": sel.get("by"), "at": sel.get("at"),
                    "pins": sel.get("pins") or {},
                    "problems": wsp.main_results_problems({"selected": kept}, snap, root),
                    **({"left_out": {"count": left, "why": LEFT_OUT}} if left else {})})
    return out


def write(data: Path, work_dir: Path, pub_for, sources: Path | None = None,
          root: Path | None = None) -> dict[str, str]:
    """Write the accepted workspace records of `work_dir` into the published data at `data`
    (its `index.json` and claim passports already written): `data/work/<claim file>` for each
    claim that has any, named by the passport's `work`, and the saved main results in the
    index's `main_results`. Currency is computed against `data` itself, with the paper sources
    under `sources` (default: the sources of the build the data was written from), and cited
    facts, applications, certificates and bridges against the Lean project at `root`. Returns
    the files written, by claim id."""
    from .targets import Snapshot, TargetError
    if not wsp.store(work_dir).is_dir():
        return {}
    try:
        snap = Snapshot(data)
    except TargetError:
        return {}
    if sources is not None:
        snap.sources_base = Path(sources)
    files = {c["id"]: c["file"] for c in snap.claims if c.get("file")}
    found = readings(work_dir, snap, pub_for, set(files), root)
    written = {}
    for cid, rs in sorted(found.items()):
        body = {"schema": SCHEMA, "release": snap.index.get("release"), "claim": cid,
                "readings": rs}
        size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
        if size > FILE_LIMIT:
            raise PublishError(f"the workspace records of {cid} take {size} bytes, more than "
                               f"the {FILE_LIMIT} a published claim may carry")
        rel = f"{DIR}/{files[cid]}"
        write_json(data / rel, body, indent=None)
        chunk_path = data / "claims" / files[cid]
        chunk = json.loads(chunk_path.read_text(encoding="utf-8"))
        chunk["work"] = rel
        write_json(chunk_path, chunk, indent=None)
        written[cid] = rel
    mains = main_results(work_dir, snap, root)
    if mains:
        index_path = data / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["main_results"] = mains
        write_json(index_path, index, indent=None)
    return written
