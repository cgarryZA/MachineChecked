"""Validated writes of semantic links (`machinechecked link`, and the reader's Link, Unlink and
Not this buttons under `machinechecked view`).

Both paths resolve the claim against the selected build before anything is written, check the
declarations, coverage, confidence and note, and record the same entry of
`machinechecked.links.json`. A link records a correspondence; it changes no status by itself
(the next build reads it, and Lean decides what the linked declarations establish).
"""

from __future__ import annotations

import copy
import datetime as _dt
from pathlib import Path

from . import simple
from .targets import Snapshot, TargetError, resolve_declaration


class LinkError(RuntimeError):
    """A link refused before anything was written."""

    def __init__(self, message: str, candidates: list | None = None, kind: str = "invalid"):
        super().__init__(message)
        self.candidates = candidates or []
        self.kind = kind

    def to_json(self) -> dict:
        return {"kind": self.kind, "message": str(self), "candidates": self.candidates}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


NOTE_FIELDS = ("note", "coverage", "confidence")


def plan(root: Path, paper: str, snap: Snapshot, claim: str, lean: list[str] | None = None,
         add: bool = False, reject: list[str] | None = None, clear: bool = False,
         note: str | None = None, coverage: str | None = None, confidence: str | None = None,
         reason: str | None = None, by: str | None = None, check_names: bool = True,
         external: bool = False, route: list[str] | None = None) -> dict:
    """The change a link request makes, without writing it: the resolved claim, each
    declaration's build state, and the links-file entry before and after.

    `lean` replaces the claim's list of linked declarations (with `add`, it is added to the
    list); `reject` records suggestions as not this claim's, with `reason`; `clear` removes the
    confirmed list, so the claim's `\\lean{}` tags and formalization.yaml apply again, and keeps
    its rejections. A note, coverage and confidence describe the declarations they were written
    with: when the list changes without a new note, the old note is kept under `earlier_notes`
    and no longer shown.

    `route` (a proof step only) replaces the step's different formal route: the declarations
    that reach its enclosing result by another argument (with `add`, they are added to it); a
    note given with it describes the route."""
    try:
        cid = snap.resolve_claim(claim)
    except TargetError as e:
        raise LinkError(str(e), e.candidates, e.kind) from None
    key = snap.key_of(cid)
    links = simple.load_links(root)
    before = copy.deepcopy(links.get("papers", {}).get(paper, {}).get(key))
    entry = copy.deepcopy(before) or {}
    shown = [l["name"] for l in (snap.chunk(cid) or {}).get("links") or []]

    if clear and (lean or reject):
        raise LinkError("--clear removes the claim's confirmed links; give it alone")
    if route is not None:
        if (snap.chunk(cid) or {}).get("unit") in (None, "statement"):
            raise LinkError(f"{cid} is not a proof step: a formal route is recorded for an "
                            "equation or passage of a proof")
        if lean is not None or reject or clear or coverage or confidence:
            raise LinkError("--route records the step's formal route; give it with a note only")
    if not (lean is not None or reject or clear or note is not None or coverage or confidence
            or route is not None):
        raise LinkError("nothing to record: give declarations, --reject, --clear or a note")
    if coverage is not None and coverage not in simple.COVERAGE:
        raise LinkError(f"coverage {coverage!r} is not one of: {', '.join(simple.COVERAGE)}")
    if confidence is not None and confidence not in simple.CONFIDENCE:
        raise LinkError(f"confidence {confidence!r} is not one of: "
                        f"{', '.join(simple.CONFIDENCE)}")
    if note is not None and len(note) > simple.NOTE_CHARS:
        raise LinkError(f"the note is longer than {simple.NOTE_CHARS} characters")

    decls = []
    names = list(dict.fromkeys(lean or [])) + list(dict.fromkeys(reject or [])) + \
        list(dict.fromkeys(route or []))
    for n in names:
        if not check_names:
            decls.append({"name": n, "module": None, "build": "unchecked"})
            continue
        try:
            decls.append(resolve_declaration(n, snap, root, external=external))
        except TargetError as e:
            raise LinkError(str(e), e.candidates, e.kind) from None

    at = _now()

    def retire_note():
        old = {k: entry.pop(k) for k in NOTE_FIELDS if k in entry}
        if old:
            entry.setdefault("earlier_notes", []).append(
                {**old, "lean": entry.get("lean"), "by": entry.get("by"), "until": at})

    if clear:
        if "lean" in entry:
            retire_note()
            for k in ("lean", "at", "by"):
                entry.pop(k, None)
    if lean is not None:
        new = list(dict.fromkeys((entry.get("lean", shown) if add else []) + list(lean)))
        bad = [n for n in new if n in (reject or [])]
        if bad:
            raise LinkError(f"{', '.join(bad)} is both linked and rejected")
        if entry.get("lean") != new:
            retire_note()
            entry["lean"] = new
            entry["at"] = at
            if by:
                entry["by"] = by
    if reject:
        linked = [n for n in reject if n in entry.get("lean", shown)]
        if linked and lean is None:
            raise LinkError(f"{', '.join(linked)} is linked to this claim; unlink it by giving "
                            "the remaining declarations (or --clear)")
        entry["rejected"] = sorted(set(entry.get("rejected", [])) | set(reject))
        if reason:
            for n in reject:
                entry.setdefault("rejected_reasons", {})[n] = {
                    "reason": reason, **({"by": by} if by else {}), "at": at}
    if route is not None:
        old = entry.get("route") or {}
        st = (snap.chunk(cid) or {}).get("step") or {}
        shown_route = [l["name"] for l in (st.get("route") or {}).get("links") or []]
        new = list(dict.fromkeys((old.get("lean", shown_route) if add else []) + list(route)))
        r = {"lean": new}
        kept = note if note is not None else (old.get("note") if old.get("lean") == new else None)
        if kept:
            r["note"] = kept
        if by or (old.get("by") and old.get("lean") == new):
            r["by"] = by or old["by"]
        r["at"] = old["at"] if {k: v for k, v in old.items() if k != "at"} == r else at
        entry["route"] = r
    elif note is not None or coverage or confidence:
        if "lean" not in entry:
            # A note is about a confirmed list: confirm what the claim shows now.
            entry["lean"] = shown
            entry["at"] = at
        for k, v in (("note", note), ("coverage", coverage), ("confidence", confidence)):
            if v is not None:
                entry[k] = v
        if by:
            entry["by"] = by
    after = entry or None
    return {"paper": paper, "claim": snap.claim_ref(cid), "declarations": decls,
            "before": before, "after": after, "changed": before != after}


def write(root: Path, change: dict) -> None:
    """Record a planned change in the links file. When the claim's entry changed after the
    change was planned (another auditor, or the reader), nothing is written and the error
    holds the entry as it now is."""
    from .workspace import _locked
    if not change["changed"]:
        return
    path = simple.links_file(root)
    with _locked(path):
        data = simple.load_links(root)
        links = data.setdefault("papers", {}).setdefault(change["paper"], {})
        key = change["claim"]["key"]
        if links.get(key) != change["before"]:
            raise LinkError(f"the links of {change['claim']['id']} changed while this was "
                            "prepared; nothing was written", [links.get(key)], kind="conflict")
        if change["after"] is None:
            links.pop(key, None)
        else:
            links[key] = change["after"]
        simple.write_json(path, data)


def from_reader(root: Path, paper: str, snap: Snapshot, req: dict) -> dict:
    """A request of the reader's local server (`POST /api/link`, `{key, lean, reject}`, or
    `{key, route, note}` for a proof step's formal route),
    checked and recorded as `machinechecked link` records it. The reader picks declarations
    from the build's own lists, so their names are not checked again here."""
    if not isinstance(req.get("key"), str):
        raise LinkError("the request names no claim")
    lean, reject, route = req.get("lean"), req.get("reject"), req.get("route")
    for v in (lean, reject, route):
        if v is not None and not (isinstance(v, list) and all(isinstance(n, str) for n in v)):
            raise LinkError("declarations are a list of names")
    by = req.get("by") if isinstance(req.get("by"), str) else None
    if "route" in req:
        ch = plan(root, paper, snap, req["key"], route=route or [], check_names=False, by=by,
                  note=req["note"] if isinstance(req.get("note"), str) else None)
    else:
        ch = plan(root, paper, snap, req["key"], lean=lean, reject=reject,
                  clear=lean is None and not reject, check_names=False, by=by)
    write(root, ch)
    return ch
