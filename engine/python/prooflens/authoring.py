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


# The fields of a reading: they describe the declarations they were written with
# (`simple.READING_KEYS`).
NOTE_FIELDS = simple.READING_KEYS


def _reading_fields(entry: dict, coverage, basis, refs, argument, bridge, question,
                    would_decide) -> dict:
    """The reading fields a request sets, checked against the entry they go into: a stored or
    given `composed` becomes `full` with basis `reviewed_composition`; a basis needs a
    coverage; an argument belongs to a reviewed composition, a bridge to a checked bridge, and
    a question and what would decide it to an unresolved reading."""
    if coverage == "composed":
        if basis not in (None, "reviewed_composition"):
            raise LinkError("coverage `composed` is full coverage with basis "
                            "reviewed_composition; give one of them")
        coverage, basis = "full", "reviewed_composition"
    if coverage is not None and coverage not in simple.COVERAGE:
        raise LinkError(f"coverage {coverage!r} is not one of: {', '.join(simple.COVERAGE)}")
    if basis is not None and basis not in simple.BASIS:
        raise LinkError(f"basis {basis!r} is not one of: {', '.join(simple.BASIS)}")
    legacy = entry.get("coverage") == "composed"
    stored_cov = "full" if legacy else entry.get("coverage")
    stored_basis = "reviewed_composition" if legacy else entry.get("basis")
    cov = coverage or stored_cov
    # A basis given stays; a stored one stays while the coverage is unchanged.
    if basis is not None:
        bas = basis
    elif coverage is None or coverage == stored_cov:
        bas = stored_basis
    else:
        bas = None
    if bas and not cov:
        raise LinkError("a basis says how a coverage is supported: give --coverage too")
    out = {"basis": bas}
    if coverage is not None:
        out["coverage"] = coverage
    for v, what, limit in ((argument, "the argument", simple.ARGUMENT_CHARS),
                           (question, "the open question", simple.NOTE_CHARS),
                           (would_decide, "what would decide it", simple.NOTE_CHARS)):
        if v is not None and len(v) > limit:
            raise LinkError(f"{what} is longer than {limit} characters")
    if argument is not None:
        if bas != "reviewed_composition":
            raise LinkError("an argument belongs to a reviewed composition "
                            "(--basis reviewed_composition)")
        out["argument"] = argument
    if bridge is not None:
        if bas != "checked_bridge":
            raise LinkError("a bridge belongs to a checked bridge (--basis checked_bridge)")
        if not (isinstance(bridge, dict) and all(isinstance(bridge.get(k), str) and bridge[k]
                                                 for k in ("theorem", "target"))):
            raise LinkError("a bridge names its theorem and its target")
        extra = set(bridge) - {"theorem", "target", "target_fingerprint", "source_sha256"}
        if extra or not all(isinstance(bridge.get(k), (str, type(None)))
                            for k in ("target_fingerprint", "source_sha256")):
            raise LinkError("a bridge has theorem, target, target_fingerprint and "
                            "source_sha256 (text)")
        out["bridge"] = {k: v for k, v in bridge.items() if v}
    if question is not None or would_decide is not None:
        if cov != "unresolved":
            raise LinkError("an open question belongs to an unresolved reading "
                            "(--coverage unresolved)")
        if question is not None:
            out["question"] = question
        if would_decide is not None:
            out["would_decide"] = would_decide
    if refs is not None:
        if not bas:
            raise LinkError("references say what a basis rests on: give --basis too")
        out["refs"] = list(dict.fromkeys(refs))
    return out


def _tidy_reading(entry: dict) -> None:
    """Drop the fields the entry's coverage and basis no longer have: a stored `composed`
    becomes `full` with basis `reviewed_composition`."""
    if entry.get("coverage") == "composed":
        entry["coverage"] = "full"
        entry.setdefault("basis", "reviewed_composition")
        if not entry.get("argument") and entry.get("note"):
            entry["argument"] = entry.pop("note")
    if not entry.get("coverage"):
        for k in ("basis", "refs"):
            entry.pop(k, None)
    if not entry.get("basis"):
        entry.pop("refs", None)
    if entry.get("basis") != "reviewed_composition":
        entry.pop("argument", None)
    if entry.get("basis") != "checked_bridge":
        entry.pop("bridge", None)
    if entry.get("coverage") != "unresolved":
        for k in ("question", "would_decide"):
            entry.pop(k, None)
    for k in [k for k in NOTE_FIELDS if entry.get(k) is None]:
        entry.pop(k, None)


def plan(root: Path, paper: str, snap: Snapshot, claim: str, lean: list[str] | None = None,
         add: bool = False, reject: list[str] | None = None, clear: bool = False,
         note: str | None = None, coverage: str | None = None, confidence: str | None = None,
         reason: str | None = None, by: str | None = None, check_names: bool = True,
         external: bool = False, basis: str | None = None, refs: list[str] | None = None,
         argument: str | None = None, bridge: dict | None = None, question: str | None = None,
         would_decide: str | None = None) -> dict:
    """The change a link request makes, without writing it: the resolved claim, each
    declaration's build state, and the links-file entry before and after.

    `lean` replaces the claim's list of linked declarations (with `add`, it is added to the
    list); `reject` records suggestions as not this claim's, with `reason`; `clear` removes the
    confirmed list, so the claim's `\\lean{}` tags and formalization.yaml apply again, and keeps
    its rejections. A reading (note, coverage, confidence, basis and the fields of its basis, see
    `simple.correspondence`) describes the declarations it was written with: when the list
    changes without a new reading, the old one is kept under `earlier_notes` and no longer
    shown."""
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
    reading_given = any(v is not None for v in (note, coverage, confidence, basis, refs,
                                                argument, bridge, question, would_decide))
    if not (lean is not None or reject or clear or reading_given):
        raise LinkError("nothing to record: give declarations, --reject, --clear or a note")
    if confidence is not None and confidence not in simple.CONFIDENCE:
        raise LinkError(f"confidence {confidence!r} is not one of: "
                        f"{', '.join(simple.CONFIDENCE)}")
    if note is not None and len(note) > simple.NOTE_CHARS:
        raise LinkError(f"the note is longer than {simple.NOTE_CHARS} characters")

    decls = []
    names = list(dict.fromkeys(lean or [])) + list(dict.fromkeys(reject or []))
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
    if reading_given:
        fields = _reading_fields(entry, coverage, basis, refs, argument, bridge, question,
                                 would_decide)
        if "lean" not in entry:
            # A note is about a confirmed list: confirm what the claim shows now.
            entry["lean"] = shown
            entry["at"] = at
        linked = entry["lean"]
        stray = [n for n in fields.get("refs", []) if n not in linked]
        if stray:
            raise LinkError(f"{', '.join(stray)} is not linked to this claim: references are "
                            "among its linked declarations")
        if "bridge" in fields and fields["bridge"]["theorem"] not in linked:
            raise LinkError(f"the bridge theorem {fields['bridge']['theorem']} is not linked to "
                            "this claim")
        for k, v in (("note", note), ("confidence", confidence)):
            if v is not None:
                entry[k] = v
        entry.update(fields)
        _tidy_reading(entry)
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
    """A request of the reader's local server (`POST /api/link`, `{key, lean, reject}`),
    checked and recorded as `machinechecked link` records it. The reader picks declarations
    from the build's own lists, so their names are not checked again here."""
    if not isinstance(req.get("key"), str):
        raise LinkError("the request names no claim")
    lean, reject = req.get("lean"), req.get("reject")
    for v in (lean, reject):
        if v is not None and not (isinstance(v, list) and all(isinstance(n, str) for n in v)):
            raise LinkError("declarations are a list of names")
    ch = plan(root, paper, snap, req["key"], lean=lean, reject=reject,
              clear=lean is None and not reject, check_names=False,
              by=req.get("by") if isinstance(req.get("by"), str) else None)
    write(root, ch)
    return ch
