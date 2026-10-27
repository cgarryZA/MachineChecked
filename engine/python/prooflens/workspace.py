"""The saved record of a semantic-audit investigation (`prooflens/workspace@1`).

A workspace keeps one auditor's investigation of a paper against its Lean project, so that it
can be resumed in the reader, in a terminal or by another agent: the claims looked at, the
evidence selected for each (and the candidates rejected), the findings, the open questions,
where the auditor stopped, and the review protocol's drafts and reports. The reader (through
`machinechecked view`'s local server) and the command line (`machinechecked workspace`) call the
functions of this module, so both validate and save in the same way.

Each workspace is one JSON file in `<work dir>/review-work/`, identified by the `id` inside it,
never by the file's name. Writes replace the file atomically under a lock. Each record has a
revision: an update names the revision it was made from, so two edits of different records are
both kept, and an edit made from an older revision of the same record is refused as a conflict
that returns (and keeps) both versions. A request repeated with the same `op_id` is answered
with its first result and changes nothing.

A workspace also keeps the auditor's breakdown of a claim into requirements, the passages of
the paper that govern each one and their association with Lean (`requirements.py`), the
auditor's compositions: arguments that combine several results, with an optional Lean bridge
(`composition.py`), and, for an estimate, the differences found, candidate counterexamples and
Lean certificates (`estimates.py`).

A workspace also keeps the auditor's choice of the paper's main results (`main_results`): the
claims and declarations `compare --query impact` traces from, with who chose them and the
release and project commit they were checked against.

A workspace records evidence and readings; it changes no status. A submitted finding is never
edited: a later one supersedes it, with its reason, and both remain. It records what it rests on
when it is submitted, with the version of each part (`dependencies.py`), so that a later build
reopens exactly the findings whose parts changed. A workspace may keep version maps of the paper
(`version_maps`), which say which findings a revision of the paper reopens (`reopen.py`), so
that they travel with its export. Exposure (what the auditor had seen) is only
ever added to, so neither resuming nor importing makes an investigation blind.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as _dt
import json
import os
import re
import secrets
import tempfile
from pathlib import Path

SCHEMA = "prooflens/workspace@1"
DIR = "review-work"
MODES = ("independent", "informed")
KINDS = ("evidence", "finding", "question", "requirement", "fragment", "alignment",
         "composition", "counterexample")
ROLES = ("candidate", "supports", "context", "rejected")
QUESTION_STATES = ("open", "answered", "withdrawn")
EXPOSURES = ("Lean", "author's review", "prior interpretations", "external material")
TEXT_CHARS = 20000
OPS_KEPT = 500

# Fields the service sets; a client's value for them is ignored.
MANAGED = ("kind", "rev", "created_at", "created_by", "updated_at", "updated_by", "state",
           "submitted_at", "supersedes", "reason", "pins", "state_by", "state_at",
           "dependencies")


class WorkspaceError(RuntimeError):
    """An edit refused, with what to do instead."""


class Conflict(WorkspaceError):
    """Edits made from an older revision of a record: `conflicts` holds, for each, the saved
    record and the refused proposal."""

    def __init__(self, conflicts: list[dict]):
        super().__init__("; ".join(f"{c['id']} was changed (now revision {c['current'].get('rev')}"
                                   f", the edit was made from {c.get('base_rev')})"
                                   for c in conflicts))
        self.conflicts = conflicts


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def store(work_dir: Path) -> Path:
    return Path(work_dir) / DIR


def reviewer_slug(reviewer_id: str) -> str:
    return re.sub(r"[^\w.-]+", "_", reviewer_id)


# -- files ---------------------------------------------------------------------------------

@contextlib.contextmanager
def _locked(path: Path):
    """An exclusive lock on `path` (through `<path>.lock`) for one read-modify-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "a+") as fh:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
        except ImportError:  # Windows
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _write(path: Path, ws: dict) -> None:
    """Replace `path` by `ws` in one step: a reader sees the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ws, f, indent=1, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def new(reviewer: dict, mode: str, sources: dict | None = None,
        selection: dict | None = None, wid: str | None = None) -> dict:
    """A new, empty workspace. An informed investigation records at once that the Lean and
    earlier interpretations are open to its auditor; it has no blind reading to lock."""
    if mode not in MODES:
        raise WorkspaceError(f"mode {mode!r} is not one of: {', '.join(MODES)}")
    at = now()
    ws = {"schema": SCHEMA, "id": wid or _new_id("ws"), "created_at": at,
          "reviewer": reviewer, "mode": mode, "revision": 0,
          "selection": selection or {}, "sources": sources or {},
          "exposure": [], "records": {}, "resume": {}, "review": {"drafts": {}, "reports": []},
          "conflicts": [], "ops": {}, "provenance": []}
    if mode == "informed":
        ws["exposure"].append({"what": ["Lean", "prior interpretations"], "claims": None,
                               "at": at, "how": "informed investigation"})
    return ws


def upgrade(raw: dict) -> dict:
    """A workspace from what a file holds: a workspace as it is, or the older review work file
    (`{reviewer, drafts, reports}`), whose drafts and reports it keeps unchanged."""
    if raw.get("schema") == SCHEMA:
        return raw
    if raw.get("schema"):
        raise WorkspaceError(f"not a workspace this version can read (schema {raw['schema']!r})")
    if not isinstance(raw.get("drafts"), dict) or not isinstance(raw.get("reports"), list):
        raise WorkspaceError("not a workspace or review work file")
    ws = new(raw.get("reviewer") or {}, "independent")
    ws["review"] = {"drafts": raw["drafts"], "reports": raw["reports"]}
    ws["provenance"].append({"event": "upgraded from a review work file", "at": now()})
    return ws


def read(path: Path) -> dict:
    return upgrade(json.loads(Path(path).read_text(encoding="utf-8")))


def list_all(work_dir: Path) -> list[tuple[Path, dict]]:
    """Every workspace of the working directory, with its file."""
    out = []
    for p in sorted(store(work_dir).glob("*.json")):
        try:
            out.append((p, read(p)))
        except (OSError, ValueError, WorkspaceError):
            continue
    return out


def summary(ws: dict) -> dict:
    recs = ws.get("records", {}).values()
    count = lambda k: sum(1 for r in recs if r.get("kind") == k)
    return {"id": ws["id"], "reviewer": (ws.get("reviewer") or {}).get("id"), "mode": ws["mode"],
            "revision": ws.get("revision", 0), "release": (ws.get("sources") or {}).get("release"),
            "evidence": count("evidence"), "findings": count("finding"),
            "counterexamples": count("counterexample"),
            "requirements": count("requirement"), "compositions": count("composition"),
            "open_questions": sum(1 for r in recs if r.get("kind") == "question"
                                  and r.get("state") == "open"),
            "reports": len((ws.get("review") or {}).get("reports", [])),
            "version_maps": len(ws.get("version_maps") or []),
            "resume": ws.get("resume") or {}}


def find(work_dir: Path, wid: str) -> Path:
    for p, ws in list_all(work_dir):
        if ws["id"] == wid:
            return p
    raise WorkspaceError(f"no workspace {wid} in {store(work_dir)}")


def open_for(work_dir: Path, reviewer: dict, mode: str | None = None, wid: str | None = None,
             sources: dict | None = None, selection: dict | None = None) -> Path:
    """The workspace to continue: the one named, else this reviewer's (of the mode asked, if
    one is), else a new one. A reviewer's first workspace is the file the review protocol
    already used (`review-work/<reviewer>.json`)."""
    if wid:
        p = find(work_dir, wid)
        ws = read(p)
        if mode and ws["mode"] != mode:
            raise WorkspaceError(f"{wid} is an {ws['mode']} workspace; its mode changes only by "
                                 "an explicit mode update, which keeps what was seen")
        return p
    mine = [(p, ws) for p, ws in list_all(work_dir)
            if (ws.get("reviewer") or {}).get("id") == reviewer.get("id")
            and (mode is None or ws["mode"] == mode)]
    if len(mine) == 1:
        return mine[0][0]
    if len(mine) > 1:
        raise WorkspaceError("this reviewer has several workspaces; choose one with --id: "
                             + ", ".join(f"{ws['id']} ({ws['mode']})" for _, ws in mine))
    default = store(work_dir) / f"{reviewer_slug(reviewer.get('id') or 'reviewer')}.json"
    ws = new(reviewer, mode or "independent", sources, selection)
    path = default if not default.exists() else store(work_dir) / f"{ws['id']}.json"
    with _locked(path):
        if not path.exists():
            _write(path, ws)
    return path


# -- validation ----------------------------------------------------------------------------

def _text(v, what: str, required: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise WorkspaceError(f"{what} must be text")
    if required and not v.strip():
        raise WorkspaceError(f"{what} is empty")
    if len(v) > TEXT_CHARS:
        raise WorkspaceError(f"{what} is longer than {TEXT_CHARS} characters")
    return v


def _choice(v, allowed, what: str, optional: bool = True):
    if v is None and optional:
        return None
    if v not in allowed:
        raise WorkspaceError(f"{what} {v!r} is not one of: {', '.join(map(str, allowed))}")
    return v


def _vocab() -> tuple[tuple, tuple, tuple]:
    """The correspondence vocabulary of the links file (coverage, basis, confidence): a finding
    uses the same words, so it means what a link's reading means."""
    from . import simple
    return tuple(simple.COVERAGE), tuple(simple.BASIS), tuple(simple.CONFIDENCE)


FACT_KEPT = ("decl", "module", "at", "fact_hash", "proof_hash", "kind", "name", "head", "type",
             "basis", "assumptions", "variables", "cases", "source")


def _fact_ref(f, root) -> dict:
    """A fact inside a proof (`fact`: `{decl, at, fact_hash?, module?}`, as `compare --query
    proof-facts` gives it in each fact's `ref`). With the Lean project it is looked up (the
    answer is cached) and kept with its proposition, assumptions, cases and pins; its basis is
    always that it is established inside that proof under that context."""
    if not isinstance(f, dict) or not isinstance(f.get("decl"), str) or \
            not isinstance(f.get("at"), str):
        raise WorkspaceError("a fact reference is {decl, at} (and fact_hash), as "
                             "`compare --query proof-facts` gives it")
    from . import proof_facts as pf
    if root is None:
        if not (f.get("fact_hash") and f.get("proof_hash")):
            raise WorkspaceError("without the Lean project a fact reference carries its "
                                 "fact_hash and proof_hash")
        return {k: f[k] for k in FACT_KEPT if f.get(k) is not None} | {"basis": pf.BASIS}
    from .simple import ViewError
    try:
        doc = pf.extract(Path(root), f["decl"], f.get("module"))
    except ViewError as e:
        raise WorkspaceError(str(e)) from None
    if not doc.get("ok"):
        raise WorkspaceError(f"{f['decl']}: {doc.get('status')}"
                             + (f": {doc['reason']}" if doc.get("reason") else ""))
    found = pf.find_fact(doc, f)
    if found is None:
        raise WorkspaceError(f"no fact at {f['at']} in the proof of {f['decl']}"
                             + (" with that proposition" if f.get("fact_hash") else "")
                             + ": ask `compare --query proof-facts` again")
    return pf.citation(found)


APP_KEPT = ("callee", "module", "id", "caller", "via", "arguments", "premises", "result",
            "app_hash")


def _app_ref(a, root) -> dict:
    """An application of a declaration (`app`: `{callee, id, module?}`, as `compare --query
    uses` gives each application's `id`). With the Lean project it is looked up (the answer is
    cached) and kept with its arguments, premises, result and a digest of them."""
    if not isinstance(a, dict) or not isinstance(a.get("callee"), str) or \
            not isinstance(a.get("id"), str):
        raise WorkspaceError("an application reference is {callee, id}, as `compare --query "
                             "uses CALLEE` gives each application")
    if root is None:
        if not (a.get("caller") and a.get("app_hash")):
            raise WorkspaceError("without the Lean project an application reference carries "
                                 "its caller and app_hash")
        return {k: a[k] for k in APP_KEPT if a.get(k) is not None}
    from . import uses as us
    from .simple import ViewError
    try:
        doc, found = us.locate(Path(root), a)
    except ViewError as e:
        raise WorkspaceError(str(e)) from None
    if not doc.get("ok"):
        raise WorkspaceError(f"{a['callee']}: {doc.get('status')}"
                             + (f": {doc['reason']}" if doc.get("reason") else ""))
    if found is None:
        raise WorkspaceError(f"no application {a['id']} of {a['callee']}: ask `compare --query "
                             f"uses {a['callee']}` again")
    return us.citation(doc, found)


def _ref(ref, snap, root) -> dict:
    """An evidence reference: exactly one of a declaration (`decl`, optional `module`), an
    application of one (`app`), a fact inside a proof (`fact`), a Lean certificate
    (`certificate`: `{theorem, target, certifies}`, `estimates.certificate_ref`), a source
    location (`source`: `{file, line}`), or a passage of the paper (`paper`: `{claim, quote}`)."""
    if not isinstance(ref, dict):
        raise WorkspaceError("an evidence record needs a `ref`")
    kinds = [k for k in ("decl", "app", "fact", "certificate", "source", "paper")
             if ref.get(k)]
    if len(kinds) != 1:
        raise WorkspaceError("an evidence `ref` names exactly one of decl, app, fact, "
                             "certificate, source, paper")
    if kinds == ["fact"]:
        return {"fact": _fact_ref(ref["fact"], root)}
    if kinds == ["app"]:
        return {"app": _app_ref(ref["app"], root)}
    if kinds == ["certificate"]:
        from .estimates import certificate_ref
        return {"certificate": certificate_ref(ref["certificate"], root)}
    if kinds == ["decl"]:
        out = {"decl": _text(ref["decl"], "the declaration", True).strip()}
        if ref.get("module"):
            out["module"] = _text(ref["module"], "the module")
        if snap is not None:
            from .targets import resolve_declaration, TargetError
            try:
                r = resolve_declaration(out["decl"], snap, root, out.get("module"),
                                        external=bool(ref.get("external")))
            except TargetError as e:
                raise WorkspaceError(str(e)) from None
            out.update(module=r["module"], build=r["build"])
            out["fingerprint"] = snap.fingerprints().get(out["decl"]) or \
                snap.store_fingerprints().get(out["decl"])
            out["digest"] = snap.digests().get(out["decl"])
            # The definitions its statement uses, and the expansions it prints, as the build
            # has them: the statement means what they say.
            from .dependencies import statement_pins
            out.update(statement_pins(snap, out["decl"]))
        else:
            for k in ("build", "fingerprint", "digest"):
                if ref.get(k):
                    out[k] = ref[k]
            from .dependencies import kept_statement_pins
            out.update(kept_statement_pins(ref))
        return out
    if kinds == ["source"]:
        s = ref["source"]
        if not isinstance(s, dict) or not isinstance(s.get("file"), str):
            raise WorkspaceError("a source reference is {file, line}")
        if s.get("line") is not None and not isinstance(s["line"], int):
            raise WorkspaceError("a source line is a number")
        return {"source": {"file": s["file"], **({"line": s["line"]} if s.get("line") else {})}}
    p = ref["paper"]
    if not isinstance(p, dict):
        raise WorkspaceError("a paper reference is {claim, quote}")
    out = {"claim": _claim(p.get("claim"), snap), "quote": _text(p.get("quote"), "the quotation")}
    # The version of the claim's passage quoted: the build's pin of it.
    sha = (snap.chunk(out["claim"]) or {}).get("source_sha256") if snap is not None else \
        p.get("sha256")
    if isinstance(sha, str) and sha:
        out["sha256"] = sha
    return {"paper": out}


def ref_text(ref: dict) -> str:
    """What a stored evidence reference names, in the reader's words: the declaration, the
    application (`callee applied in caller`), the fact inside a proof, the certificate, the
    source location or the paper passage."""
    ref = ref or {}
    if ref.get("decl"):
        return ref["decl"]
    if ref.get("app"):
        a = ref["app"]
        return f"{a.get('callee')} applied in {a.get('caller')}"
    if ref.get("fact"):
        f = ref["fact"]
        return (f"{f.get('name') or f.get('head') or 'a fact'} : {f.get('type')}, "
                f"inside the proof of {f.get('decl')}")
    if ref.get("certificate"):
        c = ref["certificate"]
        return f"{c.get('theorem')}, certificate for {c.get('target')}"
    if ref.get("source"):
        s = ref["source"]
        return f"{s.get('file')}" + (f":{s['line']}" if s.get("line") else "")
    if ref.get("paper"):
        return "paper passage"
    return "a reference of no known kind"


def _claim(q, snap) -> str:
    if not isinstance(q, str) or not q.strip():
        raise WorkspaceError("a record names its claim (`claim`)")
    if snap is None:
        return q.strip()
    from .targets import TargetError
    try:
        return snap.resolve_claim(q)
    except TargetError as e:
        raise WorkspaceError(str(e) + (": " + ", ".join(c["id"] for c in e.candidates)
                                       if e.candidates else "")) from None


def _content(kind: str, rec: dict, ws: dict, snap, root, cur: dict | None = None,
             repin: bool = False, rid: str | None = None) -> dict:
    """The fields a client may set on a record of `kind`, checked. `cur` is the record being
    replaced: a fragment's text and an alignment's fingerprints stay as they were recorded
    unless `repin` is given."""
    from . import requirements as rq
    out = {"claim": _claim(rec.get("claim"), snap)}
    if rec.get("clause") is not None:
        out["clause"] = _text(rec["clause"], "the clause")
    note = _text(rec.get("note"), "the note")
    if note:
        out["note"] = note
    refs = rec.get("evidence") or []
    if not isinstance(refs, list):
        raise WorkspaceError("`evidence` is a list of evidence record ids")
    for e in refs:
        er = ws["records"].get(e)
        if not er or er.get("kind") != "evidence":
            raise WorkspaceError(f"{e} is not an evidence record of this workspace")
        if er["claim"] != out["claim"]:
            raise WorkspaceError(f"{e} is evidence for {er['claim']}, not {out['claim']}")
    if refs:
        out["evidence"] = list(dict.fromkeys(refs))
    if kind == "composition":
        from . import composition
        return composition.content(out, rec, ws, snap, root, cur, repin)
    if kind in ("requirement", "fragment", "alignment"):
        out.pop("evidence", None)
        if kind == "requirement":
            return rq.requirement_content(out, rec, ws, rid)
        if kind == "fragment":
            return rq.fragment_content(out, rec, ws, snap, cur, repin)
        return rq.alignment_content(out, rec, ws, snap, root, cur, repin)
    if kind in ("finding", "question") and rec.get("requirement") not in (None, ""):
        out["requirement"] = rq.known_requirement(ws, out["claim"], rec["requirement"])
    if kind == "counterexample":
        from .estimates import counterexample_content
        return counterexample_content(out, rec, ws, cur, repin)
    local = [e for e in refs if "fact" in (ws["records"][e].get("ref") or {})
             and ws["records"][e].get("role") == "supports"]
    if kind == "evidence":
        out["ref"] = _ref(rec.get("ref"), snap, root)
        out["role"] = _choice(rec.get("role") or "candidate", ROLES, "the role", False)
        if rec.get("object") is not None:
            # The object of the claim's Lean the cited result derives a property of; it keeps
            # the binder it was recorded at until it is re-pinned.
            from .objects import ObjectError, object_ref
            was = (cur or {}).get("object") or {}
            o = rec["object"]
            if not repin and isinstance(o, dict) and was and o.get("decl") == was["decl"] and \
                    o.get("var") in (was["var"], was.get("name")):
                out["object"] = was
            else:
                try:
                    out["object"] = object_ref(o, None if snap is None else
                                               rq._statements(snap, out["claim"]))
                except ObjectError as e:
                    raise WorkspaceError(str(e)) from None
        out.pop("evidence", None)
        if out["role"] == "rejected" and rec.get("reason"):
            out["why_rejected"] = _text(rec["reason"], "the reason")
    elif kind == "finding":
        coverage, bases, confidence = _vocab()
        cov, basis = rec.get("coverage"), rec.get("basis")
        if cov == "composed":
            # The earlier single value for full coverage by the auditor's composition.
            if basis not in (None, "reviewed_composition"):
                raise WorkspaceError("coverage `composed` is full coverage with basis "
                                     "reviewed_composition; give one of them")
            cov, basis = "full", "reviewed_composition"
        out["coverage"] = _choice(cov, coverage, "coverage")
        basis = _choice(basis, bases, "the basis")
        if basis == "direct" and local:
            raise WorkspaceError(f"{local[0]} is a fact inside a proof, established under that "
                                 "proof's context: it is not an exported statement, so it is not "
                                 "direct coverage. Record the coverage with basis "
                                 "reviewed_composition, citing the fact")
        if basis:
            if not out["coverage"]:
                raise WorkspaceError("a basis says how a coverage is supported: give the "
                                     "coverage too")
            out["basis"] = basis
        if rec.get("composition") not in (None, ""):
            _composition_basis(out, rec["composition"], basis, ws)
        if rec.get("confidence") is not None:
            out["confidence"] = _choice(rec["confidence"], confidence, "confidence")
        if rec.get("argument") is not None:
            if basis != "reviewed_composition":
                raise WorkspaceError("an argument belongs to a reviewed composition (`basis`: "
                                     "reviewed_composition)")
            out["argument"] = _text(rec["argument"], "the argument")
        if rec.get("bridge") is not None:
            b = rec["bridge"]
            if basis != "checked_bridge":
                raise WorkspaceError("a bridge belongs to a checked bridge (`basis`: "
                                     "checked_bridge)")
            if not isinstance(b, dict) or set(b) - {"theorem", "target"}:
                raise WorkspaceError("a bridge is {theorem, target}")
            out["bridge"] = {k: _text(b.get(k), f"the bridge's {k}", True).strip()
                             for k in ("theorem", "target")}
        for k, what in (("question", "the open question"), ("would_decide",
                                                            "what would decide it")):
            if rec.get(k) not in (None, ""):
                if out["coverage"] != "unresolved":
                    raise WorkspaceError(f"{what} belongs to an unresolved finding")
                out[k] = _text(rec[k], what)
        if out["coverage"] == "unresolved" and not (out.get("question") or "").strip():
            raise WorkspaceError("an unresolved finding states its open question (`question`)")
        from .estimates import finding_fields
        finding_fields(out, rec, ws, cur, repin)
    elif kind == "question":
        out["text"] = _text(rec.get("text"), "the question", True)
        out["state"] = _choice(rec.get("state") or "open", QUESTION_STATES, "the state", False)
        if rec.get("answer") is not None:
            out["answer"] = _text(rec["answer"], "the answer")
    return out


def _composition_basis(out: dict, cid, basis, ws: dict) -> None:
    """A finding that rests on a composition of the workspace: its coverage is the
    composition's argument, so its basis is `reviewed_composition`, or `checked_bridge` when the
    composition carries a bridge Lean checked; full coverage needs a complete composition."""
    from . import composition as cp
    c = ws["records"].get(cid)
    if not c or c.get("kind") != "composition":
        raise WorkspaceError(f"{cid} is not a composition of this workspace")
    if c["claim"] != out["claim"]:
        raise WorkspaceError(f"{cid} is a composition for {c['claim']}, not {out['claim']}")
    if basis not in (cp.BASIS_REVIEWED, cp.BASIS_BRIDGE):
        raise WorkspaceError("a finding that rests on a composition has basis "
                             "reviewed_composition (or checked_bridge, once its bridge is "
                             "checked): a composition is never direct coverage")
    if basis == cp.BASIS_BRIDGE and not c.get("bridge"):
        raise WorkspaceError(f"{cid} has no bridge Lean checked: its basis is "
                             "reviewed_composition")
    if out.get("coverage") == "full":
        why = cp.full_refusal(cp.gaps(c, ws))
        if why:
            raise WorkspaceError(f"{cid}: {why}")
    out["composition"] = cid


def _pins(claim: str, snap) -> dict:
    if snap is None:
        return {}
    ch = snap.chunk(claim) or {}
    return {"release": snap.index.get("release"), "statement_sha256": ch.get("source_sha256")}


# -- the update service --------------------------------------------------------------------

def _record_op(ws, op, snap, root, by, at, changed):
    kind = op.get("op")
    rid = op.get("id") or (op.get("record") or {}).get("id")
    cur = ws["records"].get(rid) if rid else None
    base = op.get("base_rev")

    def stale():
        return {"id": rid, "base_rev": base, "current": copy.deepcopy(cur),
                "proposed": copy.deepcopy(op)}

    if kind == "put":
        rec = op.get("record") or {}
        if cur is None:
            if base not in (None, 0):
                raise WorkspaceError(f"{rid}: no such record to update")
            k = _choice(rec.get("kind"), KINDS, "the record kind", False)
            rid = rid or _new_id({"fragment": "p", "composition": "c"}.get(k, k[0]))
            if not re.fullmatch(r"[\w.:-]{1,80}", rid):
                raise WorkspaceError(f"{rid!r} is not a record id")
            content = _content(k, rec, ws, snap, root, rid=rid)
            new_rec = {"id": rid, "kind": k, **content, "rev": 1, "created_at": at,
                       "created_by": by, "updated_at": at, "updated_by": by,
                       "pins": _pins(content["claim"], snap)}
            if k == "finding":
                new_rec["state"] = "draft"
            if k == "fragment":
                new_rec.update(state_by=by, state_at=at)
            ws["records"][rid] = new_rec
            changed.append(rid)
            return None
        repin = bool(rec.get("repin"))
        content = _content(cur["kind"], {**rec, "kind": cur["kind"]}, ws, snap, root, cur,
                           repin, rid)
        if cur["kind"] == "requirement" and content["local_id"] != cur["local_id"]:
            from .requirements import references
            users = references(ws, cur["claim"], cur["local_id"], rid)
            if users:
                raise WorkspaceError(f"{cur['local_id']} is used by {', '.join(users)}; its "
                                     "local id stays while they refer to it")
        if content["claim"] != cur["claim"] and cur["kind"] == "requirement":
            raise WorkspaceError("a requirement stays with its claim")
        if cur["kind"] == "evidence" and not repin and content["ref"].get("decl") and \
                content["ref"]["decl"] == (cur.get("ref") or {}).get("decl"):
            # The evidence keeps the fingerprint it was recorded at, and the versions of the
            # definitions its statement uses, until it is re-pinned.
            for k in ("fingerprint", "digest"):
                content["ref"][k] = cur["ref"].get(k)
            for k in ("closure", "closure_complete", "expansions"):
                content["ref"].pop(k, None)
                if k in cur["ref"]:
                    content["ref"][k] = cur["ref"][k]
        was_paper = (cur.get("ref") or {}).get("paper") or {}
        if cur["kind"] == "evidence" and not repin and content["ref"].get("paper") and \
                (content["ref"]["paper"]["claim"], content["ref"]["paper"]["quote"]) == \
                (was_paper.get("claim"), was_paper.get("quote")):
            # A quoted passage keeps the version it was quoted from until it is re-pinned.
            content["ref"]["paper"] = dict(was_paper)
        cert = (cur.get("ref") or {}).get("certificate") or {}
        if cur["kind"] == "evidence" and not repin and content["ref"].get("certificate") and \
                all(content["ref"]["certificate"].get(k) == cert.get(k)
                    for k in ("theorem", "target", "certifies")):
            # A certificate keeps what Lean checked when it was recorded until it is re-pinned.
            content["ref"]["certificate"] = cert
        was = (cur.get("ref") or {}).get("fact") or {}
        if cur["kind"] == "evidence" and not repin and content["ref"].get("fact") and \
                (content["ref"]["fact"]["decl"], content["ref"]["fact"]["at"]) == \
                (was.get("decl"), was.get("at")):
            # A cited fact keeps the proof it was recorded from until it is re-pinned.
            content["ref"]["fact"] = was
        was_app = (cur.get("ref") or {}).get("app") or {}
        if cur["kind"] == "evidence" and not repin and content["ref"].get("app") and \
                (content["ref"]["app"]["callee"], content["ref"]["app"]["id"]) == \
                (was_app.get("callee"), was_app.get("id")):
            # A cited application keeps the elaboration it was recorded from until re-pinned.
            content["ref"]["app"] = was_app
        kept = {k: v for k, v in cur.items() if k not in MANAGED and k != "id"}
        if cur["kind"] in ("question", "fragment"):
            kept["state"] = cur.get("state")
        same = kept == content
        if base is None and same:
            return None  # the same record again: a repeated create
        if base != cur["rev"]:
            return stale()
        if cur["kind"] == "finding" and cur.get("state") == "submitted":
            raise WorkspaceError(f"{rid} is submitted; supersede it (with a reason) instead")
        if cur["kind"] == "composition" and not (same and not repin):
            cited = [r["id"] for r in ws["records"].values() if r.get("composition") == rid
                     and r.get("state") == "submitted"]
            if cited:
                raise WorkspaceError(f"{rid} is the argument of submitted finding(s) "
                                     f"{', '.join(cited)}; record a new composition and "
                                     "supersede the finding")
        if same and not repin:
            return None
        pins = _pins(content["claim"], snap) if repin else cur.get("pins", {})
        marks = {}
        if cur["kind"] == "fragment":
            marks = ({"state_by": by, "state_at": at} if content["state"] != cur.get("state")
                     else {k: cur[k] for k in ("state_by", "state_at") if k in cur})
        ws["records"][rid] = {"id": rid, "kind": cur["kind"], **content, **marks,
                              **({k: cur[k] for k in ("state", "submitted_at", "supersedes",
                                                      "reason") if k in cur}
                                 if cur["kind"] == "finding" else {}),
                              "rev": cur["rev"] + 1, "created_at": cur["created_at"],
                              "created_by": cur.get("created_by"), "updated_at": at,
                              "updated_by": by, "pins": pins}
        changed.append(rid)
        return None
    if cur is None:
        raise WorkspaceError(f"no record {rid}")
    if base != cur["rev"]:
        return stale()
    if kind == "delete":
        if cur.get("state") == "submitted":
            raise WorkspaceError(f"{rid} is submitted and is kept; supersede it instead")
        users = [r["id"] for r in ws["records"].values()
                 if (rid in (r.get("evidence") or []) or r.get("composition") == rid
                     or rid in [c["id"] for c in r.get("counterexamples") or []])
                 and r["id"] != rid]
        if users:
            raise WorkspaceError(f"{rid} is "
                                 + ("the composition" if cur["kind"] == "composition"
                                    else "evidence") + f" of {', '.join(users)}; remove it "
                                 "there first")
        if cur["kind"] == "requirement":
            from .requirements import references
            users = references(ws, cur["claim"], cur["local_id"], rid)
            if users:
                raise WorkspaceError(f"{rid} ({cur['local_id']}) is used by {', '.join(users)}; "
                                     "remove them first")
        if cur["kind"] == "fragment":
            from .requirements import fragment_users
            users = fragment_users(ws, rid)
            if users:
                raise WorkspaceError(f"{rid} is a passage of alignment(s) {', '.join(users)}; "
                                     "remove it from them first, or mark it removed (`state`: "
                                     "removed, with `why_removed`), which keeps it")
        del ws["records"][rid]
        changed.append(rid)
        return None
    if kind == "submit":
        if cur["kind"] != "finding" or cur.get("state") != "draft":
            raise WorkspaceError(f"{rid} is not a draft finding")
        if not (cur.get("coverage") or cur.get("difference") or cur.get("verdict")) or \
                not (cur.get("note") or cur.get("evidence") or cur.get("counterexamples")):
            raise WorkspaceError(f"{rid}: a submitted finding has its coverage (or a difference "
                                 "or a verdict) and a note or evidence")
        if cur.get("composition"):
            # The composition may have changed since the draft was written.
            _composition_basis(dict(cur), cur["composition"], cur.get("basis"), ws)
        from .dependencies import recorded
        # What it rests on, as it is submitted: kept with it from now on.
        cur.update(state="submitted", submitted_at=at, rev=cur["rev"] + 1, updated_at=at,
                   updated_by=by, dependencies=recorded(cur, ws["records"]))
        changed.append(rid)
        return None
    if kind == "supersede":
        if cur["kind"] != "finding" or cur.get("state") != "submitted":
            raise WorkspaceError(f"{rid}: only a submitted finding is superseded (edit a draft)")
        later = [r["id"] for r in ws["records"].values() if r.get("supersedes") == rid]
        if later:
            raise WorkspaceError(f"{rid} is already superseded by {later[0]}; supersede that")
        reason = _text(op.get("reason"), "the reason for superseding", True)
        rec = {**(op.get("record") or {}), "kind": "finding"}
        rec.setdefault("claim", cur["claim"])
        content = _content("finding", rec, ws, snap, root)
        if not (content.get("coverage") or content.get("difference")
                or content.get("verdict")) or \
                not (content.get("note") or content.get("evidence")
                     or content.get("counterexamples")):
            raise WorkspaceError("a superseding finding has its coverage (or a difference or a "
                                 "verdict) and a note or evidence")
        nid = rec.get("id") or _new_id("f")
        if nid in ws["records"]:
            raise WorkspaceError(f"{nid} exists already")
        new_rec = {"id": nid, "kind": "finding", **content, "state": "submitted",
                   "submitted_at": at, "supersedes": rid, "reason": reason, "rev": 1,
                   "created_at": at, "created_by": by, "updated_at": at,
                   "updated_by": by, "pins": _pins(content["claim"], snap)}
        from .dependencies import recorded
        new_rec["dependencies"] = recorded(new_rec, ws["records"])
        ws["records"][nid] = new_rec
        changed.append(nid)
        return None
    raise WorkspaceError(f"unknown operation {kind!r}")


def _workspace_op(ws, op, snap, by, at, changed):
    kind = op.get("op")
    if kind == "resume":
        st = op.get("state") or {}
        if not isinstance(st, dict):
            raise WorkspaceError("resume state is an object")
        out = {}
        if st.get("claim"):
            out["claim"] = _claim(st["claim"], snap)
        if st.get("clause"):
            out["clause"] = _text(st["clause"], "the clause")
        if st.get("question"):
            q = ws["records"].get(st["question"])
            if not q or q.get("kind") != "question":
                raise WorkspaceError(f"{st['question']} is not a question of this workspace")
            out["question"] = st["question"]
        pinned = st.get("pinned") or []
        if not isinstance(pinned, list) or not all(isinstance(x, (str, dict)) for x in pinned):
            raise WorkspaceError("`pinned` is a list of references")
        if pinned:
            out["pinned"] = pinned
        ws["resume"] = {**out, "at": at, "by": by}
        changed.append("resume")
    elif kind == "mode":
        mode = _choice(op.get("mode"), MODES, "mode", False)
        if mode != ws["mode"]:
            if mode == "informed":
                ws["exposure"].append({"what": ["Lean", "prior interpretations"], "claims": None,
                                       "at": at, "how": "informed investigation"})
            ws["provenance"].append({"event": f"mode {ws['mode']} -> {mode}", "at": at, "by": by})
            ws["mode"] = mode
            changed.append("mode")
    elif kind == "version-map":
        # A version map the workspace keeps (`reopen.py`), replacing one of the same paper and
        # revisions: the reader, `workspace show` and the export judge the findings with it.
        from . import reopen as ro
        try:
            doc = ro.check_map(op.get("map"))
        except ro.MapError as e:
            raise WorkspaceError(str(e)) from None
        doc.update(kept_at=at, kept_by=by)
        maps = [m for m in ws.get("version_maps") or [] if ro.map_key(m) != ro.map_key(doc)]
        ws["version_maps"] = maps + [doc]
        changed.append("version_maps")
    elif kind == "exposure":
        what = op.get("what")
        what = [what] if isinstance(what, str) else what
        if not what or not all(w in EXPOSURES for w in what):
            raise WorkspaceError(f"exposure is one or more of: {', '.join(EXPOSURES)}")
        claims = op.get("claims")
        if claims is not None:
            claims = [_claim(c, snap) for c in claims]
        ws["exposure"].append({"what": what, "claims": claims, "at": at,
                               "how": _text(op.get("how"), "how") or "self-declared"})
        changed.append("exposure")
    else:
        raise WorkspaceError(f"unknown operation {kind!r}")


# -- the main results ------------------------------------------------------------------------

MAIN_OP = "main-results"


def _main_claim(q: str, snap) -> str | None:
    """The claim `q` names, or None when it names none; a name several claims share is
    refused."""
    from .targets import TargetError
    try:
        return snap.resolve_claim(q)
    except TargetError as e:
        if e.kind == "ambiguous":
            raise WorkspaceError(str(e) + ": " + ", ".join(c["id"] for c in e.candidates)) \
                from None
        return None


def _main_decl(name: str, module: str | None, snap, root) -> dict:
    """The project declaration `name` (in `module`, when given), as the build has it."""
    from .targets import TargetError, resolve_declaration
    try:
        r = resolve_declaration(name, snap, root, module)
    except TargetError as e:
        if e.kind == "ambiguous":
            mods = ", ".join(c["module"] for c in e.candidates)
            raise WorkspaceError(f"{name} is declared in several modules ({mods}); name one as "
                                 "MODULE:NAME") from None
        if e.kind == "no-build" or any(c.get("module") for c in e.candidates):
            # The build has no index to look in, or the name is declared in other modules
            # than the one given: the reason says which.
            raise WorkspaceError(str(e)) from None
        near = list(dict.fromkeys(c["name"] for c in e.candidates if c.get("name")))
        raise WorkspaceError(
            f"{name if not module else f'{module}:{name}'} is neither a claim of release "
            f"{snap.index.get('release')} nor a declaration of the project"
            + (f" (did you mean: {', '.join(near)})" if near else "")) from None
    return {"decl": r["name"], "module": r["module"], "build": r["build"]}


def main_result_entries(names, snap, root: Path | None = None) -> list[dict]:
    """The main results `names` names, checked against the build `snap`: each a claim (by id,
    key or number), standing for its linked Lean, as `{claim}`, or a declaration of the project
    (`NAME`, or `MODULE:NAME` when several modules declare it; or `{decl, module}`), as `{decl,
    module, build}`. A name is read as a claim first."""
    if snap is None:
        raise WorkspaceError("main results are checked against a build: run `machinechecked view` "
                             "or `build` first")
    if not isinstance(names, list):
        raise WorkspaceError("`main` is a list of claims and declarations")
    out: list[dict] = []
    for n in names:
        if isinstance(n, dict) and isinstance(n.get("claim"), str) and not n.get("decl"):
            cid = _main_claim(n["claim"], snap)
            if cid is None:
                raise WorkspaceError(f"no claim {n['claim']!r} in release "
                                     f"{snap.index.get('release')}")
            e = {"claim": cid}
        elif isinstance(n, dict) and isinstance(n.get("decl"), str) and not n.get("claim"):
            e = _main_decl(n["decl"].strip(), _text(n.get("module"), "the module") or None,
                           snap, root)
        elif isinstance(n, str) and n.strip():
            q = n.strip()
            cid = _main_claim(q, snap)
            if cid is not None:
                e = {"claim": cid}
            else:
                module, _, name = q.rpartition(":") if ":" in q else ("", "", q)
                e = _main_decl(name, module or None, snap, root)
        else:
            raise WorkspaceError("a main result is a claim or a declaration: its name, or "
                                 "{claim} or {decl, module}")
        if e not in out:
            out.append(e)
    return out


def _main_results_op(ws, op, snap, root, by, at, changed) -> None:
    """Save the main results `op['main']` names, replacing those saved (kept in `provenance`);
    an empty list removes them."""
    entries = main_result_entries(op.get("main"), snap, root)
    prev = ws.get("main_results")
    if entries == ((prev or {}).get("selected") or []):
        return
    if prev:
        ws.setdefault("provenance", []).append({"event": "main results replaced", "at": at,
                                                "by": by, "was": prev})
    if entries:
        src = snap.sources()
        ws["main_results"] = {"selected": entries, "by": by, "at": at,
                              "pins": {"release": src.get("release"),
                                       **{k: v for k, v in (src.get("project") or {}).items()
                                          if k in ("commit", "repository")}}}
    else:
        ws.pop("main_results", None)
    changed.append("main_results")


def main_results_problems(sel: dict | None, snap, root: Path | None = None) -> list[dict]:
    """The entries of a saved main-result selection that the build `snap` does not have: a claim
    not in its release, a declaration it does not declare (in the module recorded) or that
    several of its modules declare. A declaration the build cannot look up (it keeps no index of
    the project's declarations and no record of this one) is not counted as missing."""
    from .targets import TargetError, resolve_declaration
    out = []
    index = snap.lean_index()
    for e in (sel or {}).get("selected") or []:
        if e.get("claim"):
            if snap.chunk(e["claim"]) is None:
                out.append({"claim": e["claim"], "problem": f"no claim {e['claim']} in release "
                                                            f"{snap.index.get('release')}"})
            continue
        name, module = e.get("decl"), e.get("module")
        if index is None and not snap.store_records(name):
            continue
        try:
            resolve_declaration(name, snap, root, module)
        except TargetError as err:
            if err.kind == "no-build":
                continue
            now = sorted({c["module"] for c in err.candidates if c.get("module")})
            out.append({"decl": name, **({"module": module} if module else {}), "problem": (
                f"{name} is declared in several modules of this build" if err.kind == "ambiguous"
                else f"{name} is not declared in {module} in this build"
                + (f"; it is declared in {', '.join(now)}" if now else "") if module
                else f"{name} is not a declaration of this build")})
    return out


def main_results_view(ws: dict, snap, root: Path | None = None) -> dict | None:
    """The workspace's saved main results, with what the build `snap` lacks of them
    (`problems`), or None when it saves none."""
    sel = ws.get("main_results")
    if not sel:
        return None
    return {**sel, "problems": main_results_problems(sel, snap, root) if snap is not None
            else []}


def main_result_selections(work_dir: Path, wid: str | None = None) -> list[dict]:
    """The main-result selections saved in the workspaces of `work_dir` (only in `wid`, when one
    is named), each with its workspace's id, reviewer and mode."""
    rows = list_all(work_dir)
    if wid and not any(ws["id"] == wid for _, ws in rows):
        raise WorkspaceError(f"no workspace {wid} in {store(work_dir)}")
    return [{"workspace": ws["id"], "reviewer": (ws.get("reviewer") or {}).get("id"),
             "mode": ws.get("mode"), **ws["main_results"]}
            for _, ws in rows if (not wid or ws["id"] == wid) and ws.get("main_results")]


def apply(ws: dict, ops: list[dict], snap=None, root: Path | None = None, by: str | None = None,
          op_id: str | None = None) -> dict:
    """Apply `ops` to `ws` in memory, all or none. Returns the acknowledgement; raises
    WorkspaceError for an invalid edit and Conflict for edits of changed records (whose
    proposals are kept in `ws['conflicts']`, the one change made then)."""
    if op_id is not None and op_id in ws.get("ops", {}):
        return {**ws["ops"][op_id], "repeated": True}
    if not isinstance(ops, list) or not ops:
        raise WorkspaceError("an update is a non-empty list of operations")
    work = copy.deepcopy(ws)
    at, changed, conflicts = now(), [], []
    by = by or (ws.get("reviewer") or {}).get("id")
    for op in ops:
        if not isinstance(op, dict):
            raise WorkspaceError("each operation is an object")
        if op.get("op") in ("resume", "mode", "exposure", "version-map"):
            _workspace_op(work, op, snap, by, at, changed)
        elif op.get("op") == MAIN_OP:
            _main_results_op(work, op, snap, root, by, at, changed)
        else:
            c = _record_op(work, op, snap, root, by, at, changed)
            if c:
                conflicts.append(c)
    if conflicts:
        for c in conflicts:
            ws.setdefault("conflicts", []).append({**c, "at": at, "by": by})
        raise Conflict(conflicts)
    ack = {"ok": True, "workspace": ws["id"], "changed": list(dict.fromkeys(changed)),
           "revisions": {r: work["records"][r]["rev"] for r in changed if r in work["records"]}}
    if changed:
        work["revision"] = ws.get("revision", 0) + 1
    ack["revision"] = work["revision"]
    if op_id is not None:
        work.setdefault("ops", {})[op_id] = ack
        while len(work["ops"]) > OPS_KEPT:
            work["ops"].pop(next(iter(work["ops"])))
    ws.clear()
    ws.update(work)
    return ack


def update(path: Path, ops: list[dict], snap=None, root: Path | None = None,
           by: str | None = None, op_id: str | None = None, dry_run: bool = False) -> dict:
    """Apply `ops` to the workspace saved at `path` and save it. With `dry_run`, return the
    acknowledgement and the changed records without saving."""
    with _locked(path):
        ws = read(path)
        try:
            ack = apply(ws, ops, snap, root, by, op_id)
        except Conflict:
            if not dry_run:
                _write(path, ws)
            raise
        if dry_run:
            return {**ack, "dry_run": True,
                    "records": {r: ws["records"].get(r) for r in ack["changed"]}}
        if ack["changed"] or op_id is not None:
            _write(path, ws)
        return ack


def save_review(path: Path, review: dict, reviewer: dict | None = None) -> None:
    """Save the review protocol's drafts and reports (`review_cli.Session`) into the workspace,
    leaving its other records as they are on disk."""
    with _locked(path):
        ws = read(path) if path.exists() else new(reviewer or {}, "independent")
        if reviewer and not ws.get("reviewer"):
            ws["reviewer"] = reviewer
        ws["review"] = review
        ws["revision"] = ws.get("revision", 0) + 1
        _write(path, ws)


# -- reading it back -----------------------------------------------------------------------

def current_findings(ws: dict) -> list[dict]:
    """The findings in force: submitted findings no later finding supersedes, and drafts."""
    later = {r.get("supersedes") for r in ws["records"].values() if r.get("supersedes")}
    return [r for r in ws["records"].values()
            if r.get("kind") == "finding" and r["id"] not in later]


def currency(ws: dict, snap, root: Path | None = None, check_facts: bool = False) \
        -> dict[str, dict]:
    """Whether each record's evidence is still what the current build shows. A declaration
    whose fingerprint changed, or one of the definitions its statement uses, makes its evidence
    `stale`, and so every question that cites it. A fact inside a proof is stale when that proof
    changed: it is read from the cache of `compare --query proof-facts`, or asked of Lean when
    `check_facts` is set. A finding's currency is that of what it rests on
    (`dependencies.check`): stale when a part changed, unchecked when one is not known. A record
    the build cannot check is `unchecked`; nothing here changes a status."""
    from . import dependencies as dp
    from . import requirements as rq
    out = rq.currency(ws, snap, root)
    for r in ws["records"].values():
        if r.get("kind") == "evidence":
            out[r["id"]] = dp.evidence_currency(r.get("ref") or {}, snap, root, check_facts)
    from . import composition as cp
    for r in ws["records"].values():
        if r.get("kind") == "composition":
            out[r["id"]] = cp.currency(r, ws, out, snap)
    from . import estimates as est
    for r in ws["records"].values():
        if r.get("kind") == "counterexample":
            out[r["id"]] = est.counterexample_currency(
                r, [x for x in ws["records"].values() if x.get("claim") == r["claim"]], out)
    for r in ws["records"].values():
        if r.get("kind") == "finding":
            # Through what it rests on (`dependencies.py`): a submitted finding through the
            # versions it was submitted with.
            out[r["id"]] = dp.check(r, ws["records"], snap, root, out, check_facts)
            continue
        if r.get("kind") != "question":
            continue
        changes = [ch for e in r.get("evidence") or [] for ch in out.get(e, {}).get("changes", [])]
        changes += est.finding_changes(r, ws["records"], out)
        if r.get("composition"):
            changes += out.get(r["composition"], {}).get("changes", [])
        if r.get("requirement"):
            changes += rq.requirement_changes(ws, r["claim"], r["requirement"], out)
        pin = (r.get("pins") or {}).get("statement_sha256")
        if snap is not None:
            ch = snap.chunk(r["claim"])
            if ch is None:
                changes.append({"claim": r["claim"], "was": pin, "now": None})
            elif pin and ch.get("source_sha256") != pin:
                changes.append({"claim": r["claim"], "was": pin, "now": ch.get("source_sha256")})
            elif pin and dp.unprinted(ch, r["claim"]):
                changes.append({"claim": r["claim"], "was": pin, "now": ch.get("source_sha256"),
                                "reason": dp.unprinted(ch, r["claim"])})
        out[r["id"]] = {"state": "stale" if changes else "current", "changes": changes}
    return out


def view(ws: dict, snap=None, claim: str | None = None, root: Path | None = None,
         check_facts: bool = False) -> dict:
    """The workspace as the reader and `workspace show` present it: its summary and, per
    claim, the evidence, findings (current and superseded) and questions, each with its
    currency against the current build (and, for cited facts inside proofs, the Lean project
    at `root`)."""
    from . import composition as cp
    from . import requirements as rq
    cur = currency(ws, snap, root, check_facts)
    in_force = {r["id"] for r in current_findings(ws)}
    comps = {}
    for r in ws["records"].values():
        if r.get("kind") == "composition" and (not claim or r["claim"] == claim):
            b = cp.bridge_currency(r["bridge"], r["claim"], snap, root, check_facts) \
                if r.get("bridge") else None
            comps[r["id"]] = cp.view(r, ws, cur, b)
    claims: dict[str, dict] = {}
    for r in sorted(ws["records"].values(), key=lambda r: (r["created_at"], r["id"])):
        if claim and r["claim"] != claim:
            continue
        c = claims.setdefault(r["claim"], {"evidence": [], "findings": [], "questions": [],
                                           "compositions": [], "counterexamples": []})
        if r["kind"] in ("requirement", "fragment", "alignment"):
            continue
        if r["kind"] == "composition":
            c["compositions"].append(comps[r["id"]])
            continue
        item = {**r, "currency": cur.get(r["id"], {"state": "unchecked", "changes": []})}
        if r["kind"] == "finding":
            item["in_force"] = r["id"] in in_force
            # What it rests on: as submitted, or, for a draft, as its records give it now.
            from .dependencies import of as dependencies_of
            item["dependencies"] = dependencies_of(r, ws["records"])
            chk = cp.finding_bridge(r, comps, snap, root, check_facts)
            if chk is not None and r.get("bridge") and not r.get("composition"):
                item["bridge_check"] = chk
            if chk is not None and chk.get("state") != "checked":
                # No bridge Lean checks now (its composition's, or its own): the finding reads
                # as the auditor's composition until there is one.
                item.update(basis=cp.BASIS_REVIEWED, recorded_basis=cp.BASIS_BRIDGE,
                            basis_reason=list(chk.get("reasons") or []))
        c[{"evidence": "evidence", "finding": "findings", "question": "questions",
           "counterexample": "counterexamples"}[r["kind"]]].append(item)
    for cid, c in claims.items():
        c["reading"] = rq.reading([r for r in ws["records"].values() if r["claim"] == cid], cur,
                                  snap, cid)
    from .reopen import identity
    return {"schema": "prooflens/workspace-view@1", **summary(ws),
            "selection": ws.get("selection") or {}, "sources": ws.get("sources") or {},
            "main_results": main_results_view(ws, snap, root),
            "kept_maps": [identity(m) for m in ws.get("version_maps") or []],
            "current_sources": snap.sources() if snap is not None else None,
            "exposure": ws.get("exposure") or [], "conflicts": ws.get("conflicts") or [],
            "claims": claims}


def exposed(ws: dict, claim_ids: list[str]) -> list[dict]:
    """The exposure entries of the workspace that cover any of `claim_ids`."""
    return [e for e in ws.get("exposure") or []
            if e.get("claims") is None or set(e["claims"]) & set(claim_ids)]


def auditors(ws: dict) -> set[str]:
    """Everyone the workspace records as having worked in it: its reviewer, the authors of its
    records and of its edits (refused ones too), whoever set where to resume or chose its main
    results, and whoever changed its mode or imported it. What the workspace records as seen,
    each of them had seen."""
    out = {(ws.get("reviewer") or {}).get("id"), (ws.get("resume") or {}).get("by"),
           (ws.get("main_results") or {}).get("by")}
    for r in (ws.get("records") or {}).values():
        if isinstance(r, dict):
            out |= {r.get(k) for k in ("created_by", "updated_by", "state_by")}
    for k in ("conflicts", "provenance"):
        out |= {e.get("by") for e in ws.get(k) or [] if isinstance(e, dict)}
    out |= {m.get("kept_by") for m in ws.get("version_maps") or [] if isinstance(m, dict)}
    return {x for x in out if isinstance(x, str) and x}


# -- moving it between machines -------------------------------------------------------------

def export(path: Path) -> dict:
    """The workspace as a file to hand on: everything it holds, with its mode, exposure, pins
    and authors, less the record of acknowledged requests."""
    ws = read(path)
    out = {k: v for k, v in ws.items() if k != "ops"}
    out["exported_at"] = now()
    return out


def import_(work_dir: Path, data: dict, snap=None, by: str | None = None,
            source: str | None = None) -> dict:
    """Bring an exported workspace into this working directory. It keeps its id, authors,
    pins, mode and exposure. A workspace already here with the same id gains the records it
    lacks, and the main results when it saves none; a record (or main-result selection) both
    hold in different versions is kept as here and reported as a conflict. References the
    current build cannot resolve, main results included, are reported as `problems`; the
    records stay as they were written and are not counted as resolved."""
    ws_in = upgrade(dict(data))
    ws_in.pop("exported_at", None)
    ws_in.setdefault("ops", {})
    for k in ("exposure", "records", "conflicts", "provenance"):
        ws_in.setdefault(k, [] if k != "records" else {})
    ws_in.setdefault("review", {"drafts": {}, "reports": []})
    if ws_in.get("mode") not in MODES:
        raise WorkspaceError(f"mode {ws_in.get('mode')!r} is not one of: {', '.join(MODES)}")
    problems = []
    for r in ws_in["records"].values():
        if snap is not None:
            if snap.chunk(r.get("claim") or "") is None:
                problems.append({"record": r.get("id"),
                                 "problem": f"claim {r.get('claim')} is not in release "
                                            f"{snap.index.get('release')}"})
            ref = r.get("ref") or {}
            if ref.get("decl") and ref["decl"] not in snap.digests() and \
                    ref.get("build") not in ("unbuilt", "external"):
                names = {d.get("name") for d in snap.lean_index() or []}
                if ref["decl"] not in names:
                    problems.append({"record": r.get("id"),
                                     "problem": f"{ref['decl']} is not in this build"})
        for e in r.get("evidence") or []:
            if e not in ws_in["records"]:
                problems.append({"record": r.get("id"), "problem": f"evidence {e} is missing"})
    if snap is not None:
        problems += [{"record": "main_results", "problem": p["problem"]}
                     for p in main_results_problems(ws_in.get("main_results"), snap)]
    if "version_maps" in ws_in:
        from .reopen import MapError, check_map
        maps = []
        for m in ws_in["version_maps"] if isinstance(ws_in["version_maps"], list) else [None]:
            try:
                maps.append(check_map(m))
            except MapError as e:
                problems.append({"record": "version_maps", "problem": f"{e}; it is left out"})
        ws_in["version_maps"] = maps
    at = now()
    event = {"event": "imported", "at": at, "by": by, "from": source}
    try:
        path = find(work_dir, ws_in["id"])
    except WorkspaceError:
        path = store(work_dir) / f"{ws_in['id']}.json"
        ws_in["provenance"].append(event)
        with _locked(path):
            _write(path, ws_in)
        from .reopen import identity
        return {"workspace": ws_in["id"], "path": str(path),
                "added": sorted(ws_in["records"]) + [
                    "version map " + json.dumps(identity(m), ensure_ascii=False)
                    for m in ws_in.get("version_maps") or []],
                "conflicts": [], "problems": problems}
    added, conflicts = [], []
    with _locked(path):
        ws = read(path)
        for rid, r in ws_in["records"].items():
            mine = ws["records"].get(rid)
            if mine is None:
                ws["records"][rid] = r
                added.append(rid)
            elif mine != r:
                c = {"id": rid, "base_rev": r.get("rev"), "current": mine, "proposed": r,
                     "at": at, "by": by, "how": "import"}
                ws.setdefault("conflicts", []).append(c)
                conflicts.append(c)
        from .reopen import identity, map_key
        kept = {map_key(m): m for m in ws.get("version_maps") or []}
        for m in ws_in.get("version_maps") or []:
            mine = kept.get(map_key(m))
            if mine is None:
                ws.setdefault("version_maps", []).append(m)
                kept[map_key(m)] = m
                added.append("version map " + json.dumps(identity(m), ensure_ascii=False))
            elif mine != m:
                c = {"id": "version_map", "current": identity(mine), "proposed": m, "at": at,
                     "by": by, "how": "import"}
                ws.setdefault("conflicts", []).append(c)
                conflicts.append(c)
        theirs, mine = ws_in.get("main_results"), ws.get("main_results")
        if theirs and not mine:
            ws["main_results"] = theirs
            added.append("main_results")
        elif theirs and theirs != mine:
            c = {"id": "main_results", "current": mine, "proposed": theirs, "at": at, "by": by,
                 "how": "import"}
            ws.setdefault("conflicts", []).append(c)
            conflicts.append(c)
        for e in ws_in["exposure"]:
            if e not in ws["exposure"]:
                ws["exposure"].append(e)
        if ws_in["mode"] == "informed" and ws["mode"] != "informed":
            ws["provenance"].append({"event": "imported informed work; exposure added",
                                     "at": at, "by": by})
        known = {json.dumps(r, sort_keys=True) for r in ws["review"]["reports"]}
        for r in ws_in["review"].get("reports", []):
            if json.dumps(r, sort_keys=True) not in known:
                ws["review"]["reports"].append(r)
        ws["provenance"].append(event)
        ws["revision"] = ws.get("revision", 0) + 1
        _write(path, ws)
    return {"workspace": ws["id"], "path": str(path), "added": added, "conflicts": conflicts,
            "problems": problems}


# -- the local reader's interface ------------------------------------------------------------

def api(work_dir: Path, data_dir: Path, root: Path | None = None) -> tuple[dict, dict]:
    """The routes `machinechecked view`'s local server answers for the reader: GET
    `/api/workspaces` (the list), `/api/workspace?id=&claim=` (one, as `view` gives it) and
    `/api/workspace/export?id=`, `/api/workspace/revision?id=` (the findings the version maps
    it keeps reopen, `reopen.for_site`), and `/api/proof-facts?name=&match=` (the facts inside one
    proof, as `compare --query proof-facts` gives them); POST `/api/workspace` with `action`
    `open` (`reviewer`, `mode`, `id`), `update` (`id`, `ops`, `op_id`, `base` ignored), `import`
    (`data`) or `suggest` (`id`, `claim`, `requirement`: attach the passages
    `requirements.suggest` proposes, as proposals); and GET `/api/review-order?order=informed`,
    the review queue in the order that uses the workspaces' records (`review_cli.order_route`).
    They call the functions the command line calls."""
    from .review_cli import ReviewError, order_route, parse_reviewer
    from .targets import Snapshot, TargetError

    def snap():
        try:
            return Snapshot(data_dir)
        except TargetError:
            return None

    def one(q):
        p = find(work_dir, (q.get("id") or [""])[0])
        return view(read(p), snap(), (q.get("claim") or [None])[0], root)

    def post(req):
        action = req.get("action")
        if action == "open":
            s = snap()
            if req.get("id"):
                p = find(work_dir, req["id"])
                ws = read(p)
                if req.get("mode") and ws["mode"] != req["mode"]:
                    raise WorkspaceError(f"{ws['id']} is an {ws['mode']} workspace")
                return view(ws, s)
            try:
                who = parse_reviewer(req.get("reviewer") or "", req.get("same_family") or "unknown")
            except ReviewError as e:
                raise WorkspaceError(str(e)) from None
            p = open_for(work_dir, who, req.get("mode"), req.get("id"),
                         s.sources() if s else None)
            return view(read(p), s)
        if action == "update":
            p = find(work_dir, req.get("id") or "")
            ws = read(p)
            return update(p, req.get("ops"), snap(), root, req.get("by")
                          or (ws.get("reviewer") or {}).get("id"), req.get("op_id"))
        if action == "import":
            return import_(work_dir, req.get("data") or {}, snap(), req.get("by"), "reader")
        if action == "suggest":
            from .requirements import suggestion_ops
            p = find(work_dir, req.get("id") or "")
            ws, s = read(p), snap()
            cid = _claim(req.get("claim"), s)
            ops = suggestion_ops(ws, s, cid, req.get("requirement"))
            if not ops:
                return {"ok": True, "workspace": ws["id"], "changed": [], "suggested": 0}
            ack = update(p, ops, s, root, req.get("by") or (ws.get("reviewer") or {}).get("id"),
                         req.get("op_id"))
            return {**ack, "suggested": len(ops)}
        raise WorkspaceError(f"unknown action {action!r}")

    def facts(q):
        # The facts inside one proof, on request (`compare --query proof-facts`); cached.
        if root is None:
            raise WorkspaceError("no Lean project to read the proof from")
        from .compare import CompareError, Site, query
        try:
            return query(Site(data_dir), "proof-facts", (q.get("name") or [""])[0], root=root,
                         match=(q.get("match") or [None])[0] or None)
        except CompareError as e:
            raise WorkspaceError(str(e)) from None

    def revision(q):
        # The findings each version map the workspace keeps reopens, for the maps to this
        # site's release (`reopen.for_site`).
        from .reopen import for_site
        ws, s = read(find(work_dir, (q.get("id") or [""])[0])), snap()
        return for_site(ws, s, root, work_dir, view=view(ws, s, None, root))

    get = {"/api/workspaces": lambda q: {"workspaces": [summary(ws) for _, ws in
                                                        list_all(work_dir)]},
           "/api/proof-facts": facts,
           "/api/workspace": one,
           "/api/workspace/revision": revision,
           "/api/workspace/export": lambda q: export(find(work_dir, (q.get("id") or [""])[0])),
           "/api/review-order": order_route(work_dir, data_dir)}
    return get, {"/api/workspace": post}
