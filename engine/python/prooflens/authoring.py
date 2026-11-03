"""Validated writes of semantic links (`machinechecked link`, and the reader's Link, Unlink and
Not this buttons under `machinechecked view`).

Both paths go through `plan` and `write`: the claim is resolved against the selected build, and
the declarations, coverage, confidence and note are checked, before anything is written; both
record the same entry of `machinechecked.links.json`. A declaration is named `NAME`, or
`MODULE:NAME` when several modules declare the name; the module is then recorded with the link.
A link records a correspondence; it changes no status by itself (the next build reads it, and
Lean decides what the linked declarations establish).
"""

from __future__ import annotations

import copy
import datetime as _dt
from pathlib import Path

from . import simple, steps
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


def split_module(name: str) -> tuple[str | None, str]:
    """A declaration given as `MODULE:NAME` as `(MODULE, NAME)`, a plain name as `(None,
    NAME)`. A name quoted with «» is never split."""
    n = str(name or "").strip()
    if ":" in n and "«" not in n:
        module, _, rest = n.rpartition(":")
        return module.strip() or None, rest.strip()
    return None, n


def _known(snap: Snapshot, cid: str, entry: dict, suggested: bool) -> dict[str, dict]:
    """The declarations linked to the claim, each with the record the build shows: its links, a
    proof step's links and formal route, and the names its links-file entry holds; with
    `suggested`, its suggestions and rejections too."""
    ch = snap.chunk(cid) or {}
    st = ch.get("step") or {}
    out: dict[str, dict] = {}
    for l in ((ch.get("links") or []) + (st.get("links") or [])
              + ((st.get("route") or {}).get("links") or [])
              + ((ch.get("suggestions") or []) if suggested else [])):
        if isinstance(l, dict) and isinstance(l.get("name"), str):
            out.setdefault(l["name"], l)
    for n in (list(entry.get("lean") or []) + list((entry.get("route") or {}).get("lean") or [])
              + (list(entry.get("rejected") or []) if suggested else [])):
        if isinstance(n, str):
            out.setdefault(n, {"name": n})
    return out


def _declaration(name: str, module: str | None, snap: Snapshot, root: Path, external: bool,
                 known: dict[str, dict]) -> dict:
    """What a declaration of a request is in the build (`targets.resolve_declaration`). A name
    in `known` that does not resolve to one declaration (one Lean found outside the project, or
    one several modules declare) is kept as the build shows it, with its status: a link the
    claim has already, or a suggestion declined, which adds nothing the build has not checked.
    Any other name that does not resolve is refused, with the candidates: a name newly linked
    that several modules declare is given as MODULE:NAME."""
    try:
        return resolve_declaration(name, snap, root, module, external=external)
    except TargetError as e:
        if module is None and name in known:
            shown = known[name]
            return {"name": name, "module": shown.get("module"), "build": "as shown",
                    **({"status_code": shown["status_code"]} if shown.get("status_code")
                       else {})}
        raise LinkError(str(e) + (" as MODULE:NAME" if e.kind == "ambiguous" else ""),
                        e.candidates, e.kind) from None


def paper_steps(snap: Snapshot) -> tuple[list[dict], list[dict]]:
    """The statements of the build's paper, as `steps.proof_parent` reads them (`id`, `key`,
    `number`, `label`, the file as `location`, `line`), and the lines of its proof steps
    (`steps.step_region`, a selected passage's with `passage`)."""
    statements, taken = [], []
    for c in snap.claims:
        ch = snap.chunk(c["id"]) or {}
        st = ch.get("step")
        if st:
            p = st.get("passage")
            src = st.get("source") or {}
            r = steps.step_region({"id": c["id"], "number": c.get("number"),
                                   "unit": st.get("unit"), "location": src.get("location"),
                                   "source_region": src.get("region")})
            if isinstance(p, dict):
                r = {**(r or {}), "id": c["id"], "number": c.get("number"), "passage": True,
                     "file": p.get("file"), "start_line": p.get("start_line"),
                     "end_line": p.get("end_line")}
            if r:
                taken.append(r)
            continue
        a = ch.get("anchor") or {}
        statements.append({"id": c["id"], "key": snap.key_of(c["id"]), "number": c.get("number"),
                           "label": a.get("label"), "location": a.get("file"),
                           "line": a.get("line")})
    return statements, taken


def sources_dir(snap: Snapshot) -> tuple[str, Path]:
    """The build's paper id, and its copy of the paper's sources, which the build read."""
    pid = ((snap.index.get("papers") or [{}])[0]).get("id") or "P"
    return pid, snap.data.parent.parent / "sources" / pid


def _source_name(src: Path, file: str, paper: str) -> str:
    """A source file of the paper as the build names it (relative to the paper's directory):
    `file` itself, or `file` given from the project's root (`paper/main.tex`)."""
    if (src / file).is_file():
        return file
    d = Path(paper).parent.as_posix()
    if d not in ("", ".") and file.startswith(d + "/") and (src / file[len(d) + 1:]).is_file():
        return file[len(d) + 1:]
    return file


def _passages(snap: Snapshot, entries: dict, pid: str) -> dict[str, dict]:
    """The selected passages, by key: those the links file records now (`entries`, the
    paper's), each with its `id`, its lines, its parent's id, and its `number` in the build
    when the build has it."""
    built = {snap.key_of(c["id"]): c for c in snap.claims}
    out = {}
    for key, e in entries.items():
        p = steps.stored_pin(e)
        if p is None:
            continue
        out[key] = {"id": f"{pid}:{key}", "key": key, "passage": True,
                    "number": (built.get(key) or {}).get("number") or key,
                    "parent": f"{pid}:{p['parent']}" if isinstance(p.get("parent"), str)
                    else None,
                    "file": p["file"], "start_line": p["start_line"], "end_line": p["end_line"]}
    return out


def _passage(root: Path, paper: str, snap: Snapshot, claim: str, spec: str, by: str | None,
             entries: dict, at: str) -> dict:
    """What `--passage` selects (`steps.select_passage`, against the build's sources): a new
    passage of the proof of `claim` (a statement), the passage `claim` pinned again at other
    lines, or with `none`, the passage `claim` removed. A passage is named by its id or key,
    also before a build shows it; it is checked against the other proof steps of the build and
    the passages the links file records. Returns its `id`, `key`, `ref` and `pin` (None to
    remove it)."""
    if ((snap.index.get("papers") or [{}])[0]).get("mode") != "latex":
        raise LinkError("a proof passage is selected in a paper read from its LaTeX source")
    pid, src = sources_dir(snap)
    passages = _passages(snap, entries, pid)
    try:
        cid = snap.resolve_claim(claim)
    except TargetError as e:
        k = str(claim).strip()
        k = k[len(pid) + 1:] if k.startswith(pid + ":") else k
        if k not in passages:
            raise LinkError(str(e), e.candidates, e.kind) from None
        cid = passages[k]["id"]
    ch = snap.chunk(cid) or {}
    own = next((p for p in passages.values() if p["id"] == cid), None)
    if str(spec).strip().lower() == "none":
        if own is None:
            raise LinkError(f"{cid} is not a selected passage: `--passage none` removes one")
        return {"id": cid, "key": own["key"], "pin": None,
                "ref": {"id": cid, "key": own["key"], "paper": pid, "kind": "passage",
                        "number": own["number"]}}
    statements, taken = paper_steps(snap)
    taken = [t for t in taken if not t.get("passage")] + list(passages.values())
    try:
        file, a, b = steps.parse_passage(spec)
    except steps.PassageError as e:
        raise LinkError(str(e)) from None
    file = _source_name(src, file, paper)
    if own is None and ch.get("step"):
        raise LinkError(f"{cid} is a step of a proof: a passage is selected in the proof of a "
                        "statement (give the statement, or a selected passage to pin again)")
    if own is None:
        # The same lines selected again are that passage.
        own = next((p for p in passages.values()
                    if (p["file"], p["start_line"], p["end_line"]) == (file, a, b)), None)
    try:
        sel = steps.select_passage(src, file, a, b, statements,
                                   [t for t in taken if own is None or t["id"] != own["id"]])
    except steps.PassageError as e:
        raise LinkError(str(e)) from None
    parent = sel["parent"]
    if own is not None:
        if own["parent"] and own["parent"] != parent["id"]:
            raise LinkError(f"lines {a}-{b} of {file} are in the proof of {parent['number']}, "
                            f"not of the passage's {own['parent']}: select a new passage there")
        cid, key = own["id"], own["key"]
    else:
        if cid != parent["id"]:
            raise LinkError(f"lines {a}-{b} of {file} are in the proof of {parent['number']} "
                            f"({parent['id']}), not of {ch.get('number') or cid}")
        key = steps.passage_key(parent["key"], list(entries) + [snap.key_of(c["id"])
                                                                for c in snap.claims])
        cid = f"{pid}:{key}"
    ref = {"id": cid, "key": key, "paper": pid, "kind": "passage",
           "number": steps.passage_number(parent, file, a, b)}
    pin = {**sel["pin"], "parent": parent["key"]}
    old = (entries.get(key) or {}).get("passage") or {}
    if {k: v for k, v in old.items() if k not in ("by", "at")} == pin:
        pin = old
    else:
        pin.update({**({"by": by} if by else {}), "at": at})
    return {"id": cid, "key": key, "ref": ref, "pin": pin}


def plan(root: Path, paper: str, snap: Snapshot, claim: str, lean: list[str] | None = None,
         add: bool = False, reject: list[str] | None = None, clear: bool = False,
         note: str | None = None, coverage: str | None = None, confidence: str | None = None,
         reason: str | None = None, by: str | None = None,
         external: bool = False, basis: str | None = None, refs: list[str] | None = None,
         argument: str | None = None, bridge: dict | None = None, question: str | None = None,
         would_decide: str | None = None, route: list[str] | None = None,
         passage: str | None = None) -> dict:
    """The change a link request makes, without writing it: the resolved claim, each
    declaration's build state, and the links-file entry before and after.

    `lean` replaces the claim's list of linked declarations (with `add`, it is added to the
    list); `reject` records suggestions as not this claim's, with `reason`; `clear` removes the
    confirmed list, so the claim's `\\lean{}` tags and formalization.yaml apply again, and keeps
    its rejections. A reading (note, coverage, confidence, basis and the fields of its basis, see
    `simple.correspondence`) describes the declarations it was written with: when the list
    changes without a new reading, the old one is kept under `earlier_notes` and no longer
    shown.

    `route` (a proof step only) replaces the step's different formal route: the declarations
    that reach its enclosing result by another argument (with `add`, they are added to it); a
    note given with it describes the route.

    Each declaration is `NAME` or `MODULE:NAME` (`split_module`). A module given for a linked or
    route declaration is recorded in the entry's `modules`, which the next build reads as
    formalization.yaml's `module`; a rejection is by name.

    `passage` (`FILE:A-B`) selects lines of a proof as a proof passage (`_passage`): with a
    statement as `claim`, a new passage of its proof, whose key the change names; with a
    selected passage, that passage pinned again at those lines; `none` removes the passage
    `claim`. The other arguments then apply to the passage."""
    links = simple.load_links(root)
    at = _now()
    sel = None
    if passage is not None:
        sel = _passage(root, paper, snap, claim, passage, by,
                       links.get("papers", {}).get(paper, {}), at)
        cid, key = sel["id"], sel["key"]
        if sel["pin"] is None and any(v not in (None, False, []) for v in (
                lean, reject, clear, note, coverage, confidence, basis, refs, argument, bridge,
                question, would_decide, route)):
            raise LinkError("--passage none removes the passage; give it alone")
    else:
        try:
            cid = snap.resolve_claim(claim)
        except TargetError as e:
            raise LinkError(str(e), e.candidates, e.kind) from None
        key = snap.key_of(cid)
    before = copy.deepcopy(links.get("papers", {}).get(paper, {}).get(key))
    entry = copy.deepcopy(before) or {}
    if sel is not None and sel["pin"] is None:
        return {"paper": paper, "claim": sel["ref"], "declarations": [], "before": before,
                "after": None, "changed": before is not None}
    if sel is not None:
        entry["passage"] = sel["pin"]
    shown = [l["name"] for l in (snap.chunk(cid) or {}).get("links") or []]
    known = {"lean": _known(snap, cid, entry, False), "route": _known(snap, cid, entry, False),
             "reject": _known(snap, cid, entry, True)}
    given = {"lean": None if lean is None else [split_module(n) for n in lean],
             "reject": None if reject is None else [split_module(n) for n in reject],
             "route": None if route is None else [split_module(n) for n in route]}
    for pairs in given.values():
        for m, n in pairs or []:
            if m and not n:
                raise LinkError(f"{m}: no declaration name after the module")
    lean, reject, route = ([n for _, n in pairs] if pairs is not None else None
                           for pairs in given.values())
    chosen: dict[str, str] = {}
    for m, n in (given["lean"] or []) + (given["route"] or []):
        if m and chosen.setdefault(n, m) != m:
            raise LinkError(f"{n} is given in two modules ({chosen[n]}, {m}); link one of them")

    if clear and (lean or reject):
        raise LinkError("--clear removes the claim's confirmed links; give it alone")
    reading_given = any(v is not None for v in (note, coverage, confidence, basis, refs,
                                                argument, bridge, question, would_decide))
    if route is not None:
        if sel is None and (snap.chunk(cid) or {}).get("unit") in (None, "statement"):
            raise LinkError(f"{cid} is not a proof step: a formal route is recorded for an "
                            "equation or passage of a proof")
        if lean is not None or reject or clear or (reading_given and not (
                note is not None and not any(v is not None for v in (
                    coverage, confidence, basis, refs, argument, bridge, question,
                    would_decide)))):
            raise LinkError("--route records the step's formal route; give it with a note only")
    if not (lean is not None or reject or clear or reading_given or route is not None
            or sel is not None):
        raise LinkError("nothing to record: give declarations, --reject, --clear or a note")
    if confidence is not None and confidence not in simple.CONFIDENCE:
        raise LinkError(f"confidence {confidence!r} is not one of: "
                        f"{', '.join(simple.CONFIDENCE)}")
    if note is not None and len(note) > simple.NOTE_CHARS:
        raise LinkError(f"the note is longer than {simple.NOTE_CHARS} characters")

    decls = []
    for k in ("lean", "reject", "route"):
        for m, n in dict.fromkeys(given[k] or []):
            decls.append(_declaration(n, m, snap, root, external, known[k]))

    recorded = dict(entry["modules"]) if isinstance(entry.get("modules"), dict) else {}

    def retire_note():
        old = {k: entry.pop(k) for k in NOTE_FIELDS if k in entry}
        if old:
            mods = {n: recorded[n] for n in entry.get("lean") or [] if recorded.get(n)}
            entry.setdefault("earlier_notes", []).append(
                {**old, "lean": entry.get("lean"), **({"modules": mods} if mods else {}),
                 "by": entry.get("by"), "until": at})

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
        # A module named now for a declaration already linked changes which declaration it is.
        if entry.get("lean") != new or any(chosen.get(n) and chosen[n] != recorded.get(n)
                                           for n in new):
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
    elif reading_given:
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
    # The modules of the linked and route declarations: named now, else as recorded.
    names = list(entry.get("lean") or []) + list((entry.get("route") or {}).get("lean") or [])
    mods = {n: chosen.get(n) or recorded[n] for n in names if chosen.get(n) or recorded.get(n)}
    if mods:
        entry["modules"] = mods
    else:
        entry.pop("modules", None)
    after = entry or None
    return {"paper": paper, "claim": sel["ref"] if sel else snap.claim_ref(cid),
            "declarations": decls,
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
    `{key, route, note}` for a proof step's formal route, or `{key, passage}` to select lines
    of a statement's proof as a passage, pin a passage again or, with `none`, remove it),
    checked and recorded by `plan` and `write`, as `machinechecked link` records it: the same
    claim resolution, the same declaration checks, the same entry."""
    if not isinstance(req.get("key"), str):
        raise LinkError("the request names no claim")
    lean, reject, route = req.get("lean"), req.get("reject"), req.get("route")
    for v in (lean, reject, route):
        if v is not None and not (isinstance(v, list) and all(isinstance(n, str) for n in v)):
            raise LinkError("declarations are a list of names")
    passage = req.get("passage")
    if passage is not None and not isinstance(passage, str):
        raise LinkError("a passage is given as FILE:A-B, or none")
    by = req.get("by") if isinstance(req.get("by"), str) else None
    if "route" in req:
        ch = plan(root, paper, snap, req["key"], route=route or [], by=by,
                  note=req["note"] if isinstance(req.get("note"), str) else None,
                  passage=passage)
    elif passage is not None:
        ch = plan(root, paper, snap, req["key"], lean=lean, by=by, passage=passage)
    else:
        ch = plan(root, paper, snap, req["key"], lean=lean, reject=reject,
                  clear=lean is None and not reject, by=by)
    write(root, ch)
    return ch


def proof_route(data_dir: Path):
    """`GET /api/proof?claim=ID` of `machinechecked view`'s local server: the proofs of the
    statement ID with their lines and the proof steps already in them (`steps.proof_view`),
    read from the build's copy of the paper, for the reader's selection of a passage."""
    def get(q: dict) -> dict:
        cid = (q.get("claim") or [""])[0]
        snap = Snapshot(data_dir)
        _, src = sources_dir(snap)
        statements, taken = paper_steps(snap)

        def lines_of(file: str) -> list[str] | None:
            try:
                return steps.source_lines(src, file)
            except (OSError, ValueError):
                return None
        try:
            return steps.proof_view(lines_of, statements, taken, cid)
        except steps.PassageError as e:
            raise LinkError(str(e)) from None
    return get
