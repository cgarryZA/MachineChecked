"""The workspace records a published audit carries (`prooflens/published-work@1`).

An audit publishes, per claim, the records of its auditors' workspaces (`workspace.py`) that the
auditor has accepted: the requirements of the claim, the passages accepted as governing them,
the alignments with Lean, and the submitted findings (superseded ones included, with the reason)
with the evidence they cite. Proposed and removed passages, draft findings, evidence no
submitted finding cites, questions, exposure, resume state and the review protocol's drafts stay
in the workspace.

Each record keeps its author and times, its pins and its currency against the published build,
computed over the published records alone. The paper's `publish` settings apply: a passage's
text, file and lines only when the source text is published, a Lean target's text only when the
Lean is, and the auditor's prose (notes, arguments, questions, reasons) only when reviews are.

The records sit in `data/work/<claim file>`, one file per claim that has any, which the claim's
passport names in `work`. They are readings: nothing here is an input to a status.
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
FIELDS = {
    "requirement": ("local_id", "form", "text", "origin", "parent", "binds", "independent_of",
                    "corrects"),
    "fragment": ("requirement", "role", "origin", "scope", "state", "state_by", "state_at",
                 "suggestion"),
    "alignment": ("requirements", "relation"),
    "finding": ("coverage", "basis", "confidence", "bridge", "requirement", "state",
                "submitted_at", "supersedes"),
    "evidence": ("role",),
}
REVIEWER = ("id", "kind", "name", "model", "identity")


class PublishError(RuntimeError):
    """Workspace records that cannot be published as they are."""


def accepted(ws: dict) -> dict[str, dict]:
    """The records of `ws` its auditor has accepted: every requirement and alignment, the
    accepted passages, the submitted findings and the evidence those findings cite."""
    recs = ws.get("records") or {}
    out = {}
    for rid, r in recs.items():
        k = r.get("kind")
        if k in ("requirement", "alignment") or \
                (k == "fragment" and r.get("state") == "accepted") or \
                (k == "finding" and r.get("state") == "submitted"):
            out[rid] = r
    for r in list(out.values()):
        if r.get("kind") == "finding":
            for e in r.get("evidence") or []:
                if (recs.get(e) or {}).get("kind") == "evidence":
                    out[e] = recs[e]
    return out


def _region(reg: dict, source_text: bool) -> dict:
    if source_text:
        return {k: reg[k] for k in (*rq.LOCATION, "sha256", "text") if reg.get(k) is not None}
    return {k: reg[k] for k in ("paper", "sha256") if reg.get(k) is not None}


def _changes(changes: list[dict], source_text: bool) -> list[dict]:
    if source_text:
        return changes
    return [{k: v for k, v in c.items() if k not in ("region", "lines")} for c in changes]


def _ref(ref: dict, pub) -> dict:
    if "decl" in ref:
        return {k: ref[k] for k in ("decl", "module", "build", "fingerprint", "digest")
                if ref.get(k) is not None}
    if "source" in ref:
        return {"source": dict(ref["source"]) if pub.lean else {}}
    p = ref.get("paper") or {}
    return {"paper": {"claim": p.get("claim"),
                      **({"quote": p.get("quote") or ""} if pub.source_text else {})}}


def public_record(r: dict, pub, currency: dict, in_force: set[str]) -> dict:
    """One accepted record with what `pub` allows."""
    k = r["kind"]
    out = {f: r[f] for f in (*COMMON, *FIELDS[k]) if r.get(f) is not None}
    if pub.reviews:
        out.update({f: r[f] for f in PROSE if r.get(f) not in (None, "")})
    cur = currency.get(r["id"]) or {"state": "unchecked", "changes": []}
    out["currency"] = {"state": cur["state"],
                       "changes": _changes(cur.get("changes") or [], pub.source_text)}
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
    elif k == "evidence":
        out["ref"] = _ref(r.get("ref") or {}, pub)
    return out


def readings(work_dir: Path, snap, pub_for, claims: set[str]) -> dict[str, list[dict]]:
    """Per claim of `claims`, one reading per workspace that has accepted records for it: the
    workspace, its auditor and mode, and its records in the form `public_record` gives.
    `pub_for(claim)` is the publication settings of the claim's paper."""
    out: dict[str, list[dict]] = {}
    for _, ws in wsp.list_all(work_dir):
        kept = accepted(ws)
        kept = {rid: r for rid, r in kept.items() if r.get("claim") in claims}
        if not kept:
            continue
        cur = wsp.currency({"records": kept}, snap)
        in_force = {r["id"] for r in wsp.current_findings({"records": kept})}
        who = ws.get("reviewer") or {}
        by_claim: dict[str, list[dict]] = {}
        for r in kept.values():
            by_claim.setdefault(r["claim"], []).append(r)
        for cid, recs in sorted(by_claim.items()):
            pub = pub_for(cid)
            order = {r["id"]: (i, d) for i, (r, d) in enumerate(rq._order(
                [r for r in recs if r["kind"] == "requirement"]))}
            group: dict[str, list[dict]] = {"requirements": [], "fragments": [],
                                            "alignments": [], "findings": [], "evidence": []}
            for r in sorted(recs, key=lambda r: (order.get(r["id"], (0, 0))[0],
                                                 r.get("created_at") or "", r["id"])):
                item = public_record(r, pub, cur, in_force)
                if r["kind"] == "requirement":
                    item["depth"] = order[r["id"]][1]
                group[{"requirement": "requirements", "fragment": "fragments",
                       "alignment": "alignments", "finding": "findings",
                       "evidence": "evidence"}[r["kind"]]].append(item)
            out.setdefault(cid, []).append({
                "workspace": ws["id"], "mode": ws.get("mode"),
                "reviewer": {k: who[k] for k in REVIEWER if who.get(k) is not None},
                **group})
    return out


def write(data: Path, work_dir: Path, pub_for, sources: Path | None = None) -> dict[str, str]:
    """Write the accepted workspace records of `work_dir` into the published data at `data`
    (its `index.json` and claim passports already written): `data/work/<claim file>` for each
    claim that has any, named by the passport's `work`. Currency is computed against `data`
    itself, with the paper sources under `sources` (default: the sources of the build the data
    was written from). Returns the files written, by claim id."""
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
    found = readings(work_dir, snap, pub_for, set(files))
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
    return written
