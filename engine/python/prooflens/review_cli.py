"""The review protocol from the command line (`machinechecked review next|read|lock|show|decide|
author|submit|status|export`), with the step locks of the reader's review page.

A reviewer takes a unit of the review queue through three steps: read the paper and lock a
reading; then see the Lean and record a verdict, with the coverage and its basis if they give
them; then see the author's review and record any disagreement. Each step refuses to run
before the one it follows, and each is timestamped, so the report is in exactly the form the
reader exports and `review promote` checks. The work is
kept in the reviewer's workspace (`workspace.py`, `<work dir>/review-work/<reviewer>.json`);
`export` writes the reports as one file.

As on the page, the order is what this program recorded: it cannot show that the reviewer did
not read the Lean elsewhere. What other units had already shown a unit's material to this
reviewer is recorded in the report (`reading.revealed_by`), and so is what the workspaces of the
working directory record the reviewer had seen: their own, and every other they have worked in,
such as an informed investigation they opened or imported (which has seen the Lean of every
claim).

`next` and `status` give the open units in the queue's order (`review_queue.prioritise`), in the
paper's, or in an order that also uses what the auditors' workspaces record as open; that last
order rests on prior interpretations, so asking for it is recorded as exposure.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import compare as cmp
from . import review_queue as rq
from .simple import reading_text
from . import workspace as wsp
from .config import Config

REPORT_SCHEMA = "prooflens/review-report@1"
REPORTS_SCHEMA = "prooflens/review-reports@1"
# How a workspace's exposure names an order that used the auditors' records.
ORDER_EXPOSURE = "interpretation-informed review order"

# The verdicts of the protocol, by group, as on the review page (`web/src/lib/review.js`).
VERDICTS = {
    "matches": ["faithful", "faithful with representation choices", "broader"],
    "problem": ["narrower", "mismatched", "vacuous", "refutation not valid"],
    "cannot": ["cannot determine"],
}
REFUTE_ONLY = {"refutation not valid"}
# A proof step is reviewed as printed: does it hold? (`steps.VERDICTS`)
from .steps import VERDICTS as STEP_VERDICTS

# The coverage a verdict can be recorded with (the links file's words, `simple.COVERAGE`), as on
# the review page: a match states every clause or part of the claim; a problem states part of
# it, states it differently or is a related result; a reviewer who cannot determine it leaves it
# unresolved, and the verdict's detail is the open question.
COVERAGE_FOR = {"matches": ("full", "partial"), "problem": ("partial", "changed", "related"),
                "cannot": ("unresolved",)}


class ReviewError(RuntimeError):
    pass


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _time(t) -> _dt.datetime | None:
    """A recorded time (UTC unless it says otherwise), or None when it is not one."""
    try:
        at = _dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=_dt.timezone.utc)


def _pinned(r: dict) -> str:
    """The Lean a report reviewed, in the form of `Session._fp`."""
    pins = r.get("pins") or {}
    return pins.get("fingerprint") or json.dumps(pins.get("fingerprints") or {}, sort_keys=True)


def _passes(work: dict, by) -> list[tuple[str, bool, bool, str | None]]:
    """For each unit of the review work `work` (a workspace's `review`) that reached step 2 or 3:
    its id, whether its Lean and its author's review had been shown at a time `by` accepts, and,
    for a report, the Lean it reviewed (`_pinned`)."""
    out = []
    for r in work.get("reports") or []:
        out.append(((r.get("unit") or {}).get("id"),
                    by((r.get("reading") or {}).get("locked_at")),
                    by((r.get("author_review") or {}).get("shown_at")), _pinned(r)))
    for i, d in (work.get("drafts") or {}).items():
        out.append((i, d.get("stage") != "read" and by(d.get("locked_at")),
                    d.get("stage") == "author" and by(d.get("author_shown_at")
                                                       or d.get("decided_at")), None))
    return out


def verdict_group(u: dict, verdict) -> str | None:
    """The group of `verdict` among the verdicts of unit `u` (a step's own, or a statement's)."""
    table = STEP_VERDICTS if u.get("kind") == "step" else VERDICTS
    return next((g for g, vs in table.items() if verdict in vs), None)


def correspondence(u: dict, verdict, given) -> tuple[dict | None, list[str]]:
    """The reviewer's coverage as a report records it beside the verdict (its `correspondence`),
    and what is wrong with `given`: the coverage (`simple.COVERAGE`, agreeing with the verdict as
    `COVERAGE_FOR` says) and, separately, its basis (`simple.BASIS`), with a reviewed
    composition's `argument`, a checked bridge's `bridge` (`{theorem, target}`, the theorem one of
    the unit's declarations) and an unresolved coverage's `would_decide`. The open question of an
    unresolved coverage is the verdict's detail. None when nothing is given; a review of a proof
    step records whether the step holds, and no coverage. The review page writes the same
    (`reportCorrespondence` in `web/src/lib/review.js`)."""
    from .simple import ARGUMENT_CHARS, BASIS, COVERAGE, NOTE_CHARS
    given = given if isinstance(given, dict) else {}
    why: list[str] = []

    def text(v, what: str) -> str:
        if v is None or isinstance(v, str):
            return (v or "").strip()
        why.append(f"{what} is not text")
        return ""

    cov, basis = text(given.get("coverage"), "the coverage"), text(given.get("basis"), "the basis")
    argument = text(given.get("argument"), "the argument")
    would = text(given.get("would_decide"), "what would decide it")
    b = given.get("bridge")
    if b is not None and not isinstance(b, dict):
        why.append("a bridge is {theorem, target}")
    b = b if isinstance(b, dict) else {}
    bridge = {k: text(b.get(k), f"the bridge's {k}") for k in ("theorem", "target")}
    if not (cov or basis or argument or would or any(bridge.values())):
        return None, why
    out = {"coverage": cov or None}
    if u.get("kind") == "step":
        why.append("a review of a proof step records whether the step holds, not a coverage")
    if cov and cov not in COVERAGE:
        why.append(f"coverage {cov!r} is not one of: {', '.join(COVERAGE)}")
    group = verdict_group(u, verdict)
    if cov in COVERAGE and group in COVERAGE_FOR and cov not in COVERAGE_FOR[group]:
        why.append(f"coverage {cov!r} does not agree with the verdict {verdict!r}: with it the "
                   f"coverage is {' or '.join(COVERAGE_FOR[group])}")
    if basis:
        out["basis"] = basis
        if basis not in BASIS:
            why.append(f"basis {basis!r} is not one of: {', '.join(BASIS)}")
        if not cov:
            why.append("a basis says how a coverage is supported: give the coverage too")
    if argument:
        out["argument"] = argument
        if basis != "reviewed_composition":
            why.append("an argument belongs to a reviewed composition (basis "
                       "reviewed_composition)")
        if len(argument) > ARGUMENT_CHARS:
            why.append(f"the argument is longer than {ARGUMENT_CHARS} characters")
    if any(bridge.values()) and basis != "checked_bridge":
        why.append("a bridge belongs to a checked bridge (basis checked_bridge)")
    if basis == "checked_bridge":
        lean = u["lean"] if isinstance(u.get("lean"), list) and u["lean"] else [u.get("name")]
        if not all(bridge.values()):
            why.append("a checked bridge names its theorem and its target")
        elif bridge["theorem"] not in lean:
            why.append(f"the bridge theorem {bridge['theorem']} is not one of the unit's "
                       f"declarations ({', '.join(map(str, lean))})")
        # The version of the target the reviewer was shown, when the build checks this bridge.
        pin = b.get("target_fingerprint")
        out["bridge"] = {**bridge, "target_fingerprint": pin if isinstance(pin, str) and pin
                         else None}
    if would:
        out["would_decide"] = would
        if cov != "unresolved":
            why.append("what would decide it belongs to an unresolved coverage")
        if len(would) > NOTE_CHARS:
            why.append(f"what would decide it is longer than {NOTE_CHARS} characters")
    return out, why


def parse_reviewer(who: str, same_family: str = "unknown") -> dict:
    """`human:NAME` or `llm:MODEL`, as the protocol writes reviewer ids."""
    m = re.fullmatch(r"(human|llm):(\S+)", who or "")
    if not m:
        raise ReviewError("give the reviewer as human:NAME or llm:MODEL (--as, or the "
                          "MACHINECHECKED_REVIEWER environment variable)")
    kind = "human" if m.group(1) == "human" else "model"
    return {"id": who, "kind": kind, "name": m.group(2).replace("-", " ") if kind == "human" else None,
            "model": m.group(2) if kind == "model" else None,
            "same_family_as_author": "no" if kind == "human" else same_family,
            "identity": "self-declared"}


class Session:
    """One reviewer's work on the queue of the last build.

    `target` is the full assessment's configuration, or the working directory of the build
    (`<project>/.machinechecked` for the zero-configuration view): the session reads that
    build's site data and keeps the work beside it."""

    def __init__(self, target: Config | Path, reviewer: dict):
        work = Path(getattr(target, "out_dir", target))
        self.work_dir = work
        self.data = work / "site" / "data"
        if not (self.data / "review-queue.json").exists():
            raise ReviewError("no review queue: run `machinechecked view` or `machinechecked "
                              "build` first")
        self.site = cmp.Site(self.data)
        self.index = self.site.index
        self.queue = json.loads((self.data / "review-queue.json").read_text(encoding="utf-8"))
        self.units = {u["id"]: u for u in self.queue["units"]}
        self.reviewer = reviewer
        self.path = wsp.store(work) / f"{wsp.reviewer_slug(reviewer['id'])}.json"
        try:
            self.workspace = wsp.read(self.path) if self.path.exists() else \
                wsp.new(reviewer, "independent")
        except (ValueError, wsp.WorkspaceError) as e:
            raise ReviewError(f"{self.path}: {e}") from None
        self.work = self.workspace["review"]

    def save(self):
        wsp.save_review(self.path, self.work, self.reviewer)

    # -- the queue -------------------------------------------------------------------------

    def unit(self, uid: str) -> dict:
        u = self.units.get(uid)
        if u is None:
            raise ReviewError(f"no unit {uid} in the queue of release {self.queue['release']}")
        return u

    @staticmethod
    def _fp(u: dict) -> str:
        return u.get("fingerprint") or json.dumps(u.get("fingerprints") or {}, sort_keys=True)

    def reported(self, u: dict) -> bool:
        return any(r["unit"]["id"] == u["id"] and _pinned(r) == self._fp(u)
                   for r in self.work["reports"])

    def open_units(self, order: str = "priority") -> list[dict]:
        """The units left to review, in the order asked (`review_queue.ORDERS`): the queue's
        (`priority`), the paper's (`document`), or the queue's with what the workspaces of this
        working directory record as open (`informed`). Those records are prior
        interpretations: an informed order records that exposure in this reviewer's workspace,
        for the claims it drew on, so that a later reading of them is not taken as blind."""
        units = [u for u in self.queue["units"] if u["state"] != "reviewed"
                 and not self.reported(u)]
        if order == "priority":
            return units
        if order == "document":
            return rq.arrange(units, {}, "document", self.index.get("claims") or [])
        if order != "informed":
            raise ReviewError(f"order {order!r} is not one of: {', '.join(rq.ORDERS)}")
        spaces = [ws for _, ws in wsp.list_all(self.work_dir)]
        signals, drawn = rq.workspace_signals(units, spaces, self.site)
        if drawn:
            self.expose(drawn, ORDER_EXPOSURE)
        return rq.arrange(units, signals)

    def expose(self, claims: list[str], how: str) -> None:
        """Record in this reviewer's workspace that they have seen prior interpretations of
        `claims`, unless it already records that."""
        for e in self.workspace.get("exposure") or []:
            if "prior interpretations" in e.get("what", []) and (
                    e.get("claims") is None or set(claims) <= set(e["claims"])):
                return
        if not self.path.exists():
            self.save()
        wsp.update(self.path, [{"op": "exposure", "what": ["prior interpretations"],
                                "claims": sorted(claims), "how": how}],
                   by=self.reviewer["id"])
        self.workspace = wsp.read(self.path)
        self.work = self.workspace["review"]

    def draft(self, u: dict, stage: str | None = None) -> dict:
        d = self.work["drafts"].get(u["id"])
        if stage is not None and (d is None or d["stage"] != stage):
            have = d["stage"] if d else "not started"
            raise ReviewError(f"{u['id']} is at step '{have}'; this needs step '{stage}' "
                              f"(read → compare → author → submitted)")
        return d

    def is_reviewer(self, who: str | None) -> bool:
        """Whether `who` names this reviewer, as the protocol keys a reviewer's work (the file
        `review-work/<reviewer>.json`)."""
        return bool(who) and wsp.reviewer_slug(who) == wsp.reviewer_slug(self.reviewer["id"])

    def other_workspaces(self) -> list[dict]:
        """The other workspaces of the working directory that this reviewer has worked in
        (`workspace.auditors`): one they opened in another mode, one they imported, one in which
        they recorded work."""
        here = self.path.resolve()
        return [ws for p, ws in wsp.list_all(self.work_dir)
                if p.resolve() != here and any(map(self.is_reviewer, wsp.auditors(ws)))]

    def revealed_by(self, u: dict, before: str | None = None) -> list[dict]:
        """What this reviewer had already seen of u's Lean or u's author review: what each
        workspace they have worked in records they had seen of u's claims (an informed
        investigation has seen the Lean and the interpretations of every claim), and the units
        whose step 2 or 3 they reached, here or in another workspace of theirs, whose material
        includes u's Lean or u's author review. With `before`, only what was recorded by that
        time; a record without its time counts."""
        def by(t) -> bool:
            if before is None or not t:
                return True
            at, limit = _time(t), _time(before)
            return at is None or limit is None or at <= limit

        out = []

        def add(unit: str, what: str) -> None:
            if {"unit": unit, "what": what} not in out:
                out.append({"unit": unit, "what": what})

        others = self.other_workspaces()
        ids = [c["id"] for c in u.get("claims") or []]
        for ws in [self.workspace, *others]:
            for e in wsp.exposed(ws, ids):
                if not by(e.get("at")):
                    continue
                for what in e["what"]:
                    what = {"prior interpretations": "author's review"}.get(what, what)
                    if what in ("Lean", "author's review"):
                        add(f"workspace {ws['id']} ({e.get('how')})", what)
        mine = [ws for ws in others if self.is_reviewer((ws.get("reviewer") or {}).get("id"))]
        for ws in [self.workspace, *mine]:
            own = ws is self.workspace
            for i, lean, author, pinned in _passes(ws.get("review") or {}, by):
                unit = i if own else f"{i} (workspace {ws['id']})"
                if i == u["id"]:
                    # Here the unit's draft is this review. Another workspace's draft of it, or
                    # its report of the same Lean, is this reviewer's earlier sight of it; a
                    # report of other Lean is an earlier review, as a reopened review is here.
                    if not own and pinned in (None, self._fp(u)):
                        for what, ok in (("Lean", lean), ("author's review", author)):
                            if ok:
                                add(unit, what)
                    continue
                r = (self.units.get(i) or {}).get("reveals") or {}
                for what, ok, key in (("Lean", lean, "lean"),
                                      ("author's review", author, "author")):
                    if ok and u["id"] in r.get(key, []):
                        add(unit, what)
        return out

    # -- what each step shows --------------------------------------------------------------

    def packet(self, u: dict, stage: str) -> dict:
        """What a step shows, as data: the unit's packet filtered to the stage (`compare.py`),
        so that nothing a later step shows is delivered before it."""
        return cmp.unit_packet(self.site, u, stage)

    def paper_text(self, u: dict) -> str:
        """Step 1: the paper's statements only, every one of the unit's claims in full."""
        return cmp.packet_text(self.packet(u, "read"))

    def lean_text(self, u: dict) -> str:
        """Step 2: the Lean of the unit, with what it uses."""
        return cmp.packet_text(self.packet(u, "compare"))

    # -- the steps -------------------------------------------------------------------------

    def read(self, uid: str, as_json: bool = False) -> str | dict:
        u = self.unit(uid)
        if self.reported(u):
            raise ReviewError(f"{uid} is already reported by {self.reviewer['id']}")
        d = self.draft(u)
        if d is None:
            self.work["drafts"][uid] = {"stage": "read", "reading": ""}
            self.save()
        elif d["stage"] != "read":
            raise ReviewError(f"{uid}: the reading is already locked")
        seen = self.revealed_by(u)
        warn = ("\n\nNOTE: you have already seen " + " and ".join(
            f"the {s['what']} of this unit (in {s['unit']})" for s in seen)
            + ". Your reading will not be blind, and the report will say so.") if seen else ""
        if as_json:
            return {**self.packet(u, "read"), "review": {"step": "read", "seen_before": seen}}
        return self.paper_text(u) + warn

    def lock(self, uid: str, reading: str) -> None:
        u = self.unit(uid)
        d = self.draft(u, "read")
        if len(reading.strip()) < 20:
            raise ReviewError("the reading is too short to record (20 characters at least)")
        # The passages read are those of this queue's release: the report pins their digests.
        d.update(reading=reading, revealed_by=self.revealed_by(u), locked_at=now(),
                 source_sha256=u.get("source_sha256"), stage="compare")
        self.save()

    def show(self, uid: str, as_json: bool = False) -> str | dict:
        u = self.unit(uid)
        d = self.draft(u)
        if d is None or d["stage"] == "read":
            raise ReviewError(f"{uid}: lock your reading first (`review lock`); the Lean is shown "
                              "only after it")
        if as_json:
            return {**self.packet(u, "compare"), "review": {"step": "compare"}}
        return self.lean_text(u)

    def decide(self, uid: str, verdict: str, comparison: str, detail: str = "",
               witness: str = "", coverage: dict | None = None) -> None:
        """Step 2's record: the verdict, the comparison and, with them, the reviewer's coverage
        (`correspondence`), all before the author's review is shown."""
        u = self.unit(uid)
        d = self.draft(u, "compare")
        table = STEP_VERDICTS if u["kind"] == "step" else VERDICTS
        group = verdict_group(u, verdict)
        if group is None:
            raise ReviewError(f"verdict {verdict!r} is not one of: "
                              + ", ".join(v for vs in table.values() for v in vs))
        if verdict in REFUTE_ONLY and not u.get("refute"):
            raise ReviewError(f"{verdict!r} applies only to a unit with a refutation")
        if verdict not in ("faithful", "holds as printed") and not detail.strip():
            raise ReviewError(f"verdict {verdict!r} needs --detail")
        if not comparison.strip():
            raise ReviewError("the comparison is empty")
        if isinstance(coverage, dict) and isinstance(coverage.get("bridge"), dict):
            coverage = {**coverage, "bridge": {**coverage["bridge"],
                                               "target_fingerprint": self.target_pin(
                                                   u, coverage["bridge"])}}
        cor, why = correspondence(u, verdict, coverage)
        if why:
            raise ReviewError("; ".join(why))
        d.update(group=group, verdict=verdict, detail=detail, comparison=comparison,
                 witness=witness, correspondence=cor, decided_at=now(), stage="author")
        self.save()

    def target_pin(self, u: dict, bridge: dict) -> str | None:
        """The version of a bridge's target in this build (`target_fingerprint`), when the links
        of one of the unit's claims record that bridge and the build checked it; it is read
        from the build's data and shown to no one."""
        for c in u.get("claims") or []:
            b = ((self.site.chunk(c["id"]) or {}).get("correspondence") or {}).get("bridge") or {}
            if (b.get("theorem"), b.get("target")) == (bridge.get("theorem"), bridge.get("target")):
                return (b.get("current") or {}).get("target_fingerprint")
        return None

    def author(self, uid: str, as_json: bool = False) -> str | dict:
        u = self.unit(uid)
        d = self.draft(u, "author")
        d.setdefault("author_shown_at", now())
        self.save()
        if as_json:
            return {**self.packet(u, "informed"),
                    "review": {"step": "author", "shown_at": d["author_shown_at"]}}
        revs = u.get("author_review") or []
        out = [f"{r.get('by')} · {r.get('file')}:{r.get('line')}\n"
               + (r.get("text") or "No text was written with this review marker.") for r in revs]
        for c in u.get("claims") or []:
            note = (self.site.chunk(c["id"]) or {}).get("correspondence") or {}
            text = reading_text(note)
            if text:
                out.append(f"Reading of the correspondence of {c['id']}"
                           + (f" by {note['by']}" if note.get("by") else "") + f"\n{text}")
        return "\n\n".join(out) or "No review by the author is recorded for this unit."

    def submit(self, uid: str, disagreements: str) -> dict:
        u = self.unit(uid)
        d = self.draft(u, "author")
        if "author_shown_at" not in d:
            raise ReviewError(f"{uid}: read the author's review first (`review author`)")
        # What reached this working directory after the lock (an investigation imported since,
        # say) but was seen before it is part of what the reading was not blind to.
        seen = list(d.get("revealed_by") or [])
        seen += [s for s in self.revealed_by(u, before=d.get("locked_at")) if s not in seen]
        d["revealed_by"] = seen
        r = report(self.index, u, d, self.reviewer, disagreements or "none")
        self.work["reports"].append(r)
        del self.work["drafts"][uid]
        self.save()
        return r

    def export(self, out: Path) -> Path:
        body = {"schema": REPORTS_SCHEMA, "project": (self.index.get("project") or {}).get("name"),
                "release": self.index["release"], "exported_at": now(),
                "reports": self.work["reports"]}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


# The kind of issue each verdict's draft is: a note explaining an accepted difference, a
# defect the reviewer found, or a question the reviewer could not decide. A faithful verdict,
# or one this table does not know, has no draft.
DRAFT_KIND = {"faithful with representation choices": "explanatory note",
              "broader": "explanatory note",
              **{v: "defect" for v in VERDICTS["problem"]},
              "cannot determine": "unresolved question"}
UNRESOLVED_BODY = ("The reviewer could not determine whether the Lean statement says what the "
                   "paper says; this is an open question.")


def issue_draft(u: dict, verdict: str, detail: str, cor: dict | None = None) -> dict | None:
    """The issue a maintainer may file for a verdict, as the reader's `issueDraft` writes it.
    An open question carries what would decide it, when the report's coverage (`cor`) says."""
    if u.get("kind") == "step":
        return step_issue_draft(u, verdict, detail)
    kind = DRAFT_KIND.get(verdict)
    if kind is None:
        return None
    claims = ", ".join(c.get("number") or c["id"] for c in u["claims"])
    suffix = f" ({claims})" if claims else ""
    detail = (detail or "").strip()
    if kind == "unresolved question":
        would = ((cor or {}).get("would_decide") or "").strip()
        return {"kind": kind, "title": f"{u['name']}: open question{suffix}",
                "body": f"Review unit `{u['id']}`, verdict **{verdict}**. {UNRESOLVED_BODY}"
                        + (f"\n\n**Open question.** {detail}" if detail else "")
                        + (f"\n\n**Would decide it.** {would}" if would else "")}
    return {"kind": kind, "title": f"{u['name']}: {verdict}{suffix}",
            "body": f"Review unit `{u['id']}`, verdict **{verdict}**.\n\n{detail}".strip()}


def step_issue_draft(u: dict, verdict: str, detail: str) -> dict | None:
    """An issue about a proof step names the step, its proof and the question it answers: a
    finding on the printed step, never on the enclosing statement."""
    if verdict == "holds as printed":
        return None
    par = (u.get("parent") or {}).get("number") or (u.get("parent") or {}).get("id") or ""
    where = f"{u['name']}" + (f" in the proof of {par}" if par else "")
    kind = {"false as printed": "finding on a proof step",
            "holds, with a gap in the argument": "explanatory note",
            "cannot determine": "unresolved question"}.get(verdict, "finding on a proof step")
    return {"kind": kind, "title": f"{where}: {verdict}",
            "body": (f"Review unit `{u['id']}` (a proof step, not the statement of {par or 'its result'}), "
                     f"verdict **{verdict}**.\n\n{detail}").strip()}


def report(index: dict, u: dict, d: dict, reviewer: dict, disagreements: str) -> dict:
    """The report, in the form the reader's review page exports (`buildReport`)."""
    revs = {p["id"]: p.get("revision") for p in index.get("papers", [])}
    return {
        "schema": REPORT_SCHEMA,
        "unit": {"id": u["id"], "kind": u["kind"], "name": u["name"],
                 "lean": u.get("lean") if u["kind"] == "step" else u.get("lean") or [u["name"]],
                 "claims": [c["id"] for c in u["claims"]], "papers": u.get("papers") or [],
                 **({"target": u.get("unit"), "parent": u.get("parent"),
                     "route": u.get("route") or []} if u["kind"] == "step" else {})},
        "pins": {"release": index["release"],
                 "project_commit": (index.get("project") or {}).get("commit"),
                 "manuscripts": {p: revs.get(p) for p in u.get("papers") or []},
                 "legacy_hash": u.get("legacy_hash"), "fingerprint": u.get("fingerprint"),
                 "fingerprints": u.get("fingerprints"),
                 "source_sha256": d.get("source_sha256")},
        "reviewer": reviewer,
        "reading": {"text": d["reading"], "locked_at": d["locked_at"],
                    "revealed_by": d.get("revealed_by") or []},
        "comparison": {"text": d["comparison"], "witness": d.get("witness") or "",
                       "checklist": {}, "decided_at": d["decided_at"]},
        "verdict": {"group": d["group"], "value": d["verdict"], "detail": d.get("detail") or ""},
        # Recorded with the verdict; None when the reviewer recorded no coverage.
        "correspondence": d.get("correspondence"),
        "author_review": {"shown_at": d["author_shown_at"], "disagreements": disagreements},
        "submitted_at": now(),
        "issue_draft": issue_draft(u, d["verdict"], d.get("detail") or "",
                                   d.get("correspondence")),
    }
