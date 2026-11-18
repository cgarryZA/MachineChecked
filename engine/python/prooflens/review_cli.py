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
paper's, or in an order that also uses what the auditors' workspaces record as open (findings a
change reopened first, with their questions) and the main results they save; that last order
rests on prior interpretations, so asking for it is recorded as exposure. The reader's review
page asks the local server for that order (`order_route`) and records the exposure.

Under `machinechecked view`, the reader's review page works through this session too (`api`):
its drafts, reports and exposure are those of the reviewer's workspace, so a unit begun in the
browser is continued in a terminal and the other way round, with the same steps and checks. A
static copy of the site keeps the page's work in the browser instead.

A session is independent or informed, as its workspace is. Independent review keeps the locks
above. An informed session has already seen the Lean and the prior interpretations of every
claim (its workspace records that when it is opened): any step may be shown at any time, a
reading is recorded only when the reviewer gives one, and the report lists what was seen, so
`review promote` treats it as not blind.

A reviewer who did not build the project reviews its author's review snapshot
(`review_snapshot.py`, `--snapshot`): the session reads the snapshot's site data, keeps the work
in a working directory of the reviewer's own, and each report records what it was reviewed
against (`evidence`).
"""

from __future__ import annotations

import copy
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
    "matches": ["faithful", "faithful with representation choices", "broader",
                "faithful to the correction"],
    "problem": ["narrower", "mismatched", "vacuous", "refutation not valid"],
    "cannot": ["cannot determine"],
}
# Whether a proposition is refuted is shown only after the verdict, so this verdict is offered
# for every locked proposition: a refutation of it would not refute the printed claim.
REFUTE_ONLY = {"refutation not valid"}
# A correction (or special case) of a printed clause states the printed claim with the
# correction: reviewed against the printed passage, its honest verdict is this one (#639).
CORRECTION_ONLY = {"faithful to the correction"}
# A proof step is reviewed as printed: does it hold? (`steps.VERDICTS`)
from .steps import VERDICTS as STEP_VERDICTS

# What the detail of a verdict says, as the review page asks for it (`needsDetail` in
# `web/src/lib/review.js`; tests/fixtures/review/verdict-details.json holds both to it). A verdict
# not listed needs no detail. The comparison says how the Lean compares with the paper; the
# detail is what the verdict itself needs said.
DETAIL = {
    "faithful with representation choices":
        "List the representation choices, and say why each is harmless.",
    "broader": "State the instantiation that gives the printed claim.",
    "narrower": "Say exactly how: which hypothesis is added, which case is lost.",
    "mismatched": "Say what it states instead.",
    "vacuous": "Say why the hypotheses cannot be met, or why the witness does not meet them.",
    "refutation not valid": "Say how the proposition is stronger than the printed claim, so that "
                            "a refutation of it would not refute the printed claim.",
    "cannot determine": "State the open question, and what would decide it.",
}
STEP_DETAIL = {
    "holds, with a gap in the argument": "Give the argument the printed proof leaves out.",
    "false as printed":
        "Give the counterexample or the failing case, and what would repair the step.",
    "cannot determine": "Say what would decide it.",
}


def detail_asked(u: dict, verdict) -> str | None:
    """What the detail of `verdict` says for unit `u` (a proof step's verdicts are its own), or
    None when that verdict needs no detail."""
    return (STEP_DETAIL if u.get("kind") == "step" else DETAIL).get(verdict)


# The coverage a verdict can be recorded with (the links file's words, `simple.COVERAGE`), as on
# the review page: a match states every clause or part of the claim; a problem states part of
# it, states it differently or is a related result; a reviewer who cannot determine it leaves it
# unresolved, and the verdict's detail is the open question.
COVERAGE_FOR = {"matches": ("full", "partial"), "problem": ("partial", "changed", "related"),
                "cannot": ("unresolved",)}


class ReviewError(RuntimeError):
    """A step refused, with what to do instead. `kind` says why: `no-build`, `snapshot` (a
    review snapshot that is incomplete, inconsistent or of another format), `paper-source` (the
    source of a paper whose text the snapshot leaves out, not obtained or not the one it was
    made from), `unknown-unit`, `order` (a step before the one it follows), `reported`,
    `invalid`, `stale` (the build changed since the material was shown), `conflict` (the draft
    changed meanwhile; `conflicts` holds it as saved) or `workspace`."""

    def __init__(self, message: str, kind: str = "refused", conflicts: list | None = None):
        super().__init__(message)
        self.kind = kind
        self.conflicts = conflicts

    def to_json(self) -> dict:
        return {"kind": self.kind, "message": str(self),
                **({"conflicts": self.conflicts} if self.conflicts is not None else {})}


# The fields of a draft the reviewer may still change at each step (`Session.edit`): the reading
# until it is locked, the comparison and verdict until the verdict is recorded, and the response
# to the author's review until the report is submitted.
EDITABLE = {"read": ("reading",),
            "compare": ("comparison", "witness", "checklist", "group", "verdict", "detail",
                        "coverage", "basis", "argument", "bridge", "would_decide"),
            "author": ("disagreements", "changed")}
MARKS = ("matches", "differs", "unsure")

# Why there is nothing to review here, and the two ways to have something: a review of a
# project the reviewer did not build reads its author's snapshot, which needs no Lean.
NO_BUILD = ("no review queue here. To review a project you did not build, get its author's "
            "review snapshot (`machinechecked review pack`) and pass it with --snapshot FILE: "
            "that needs no Lean. To review your own project, run `machinechecked view` or "
            "`machinechecked build` first")


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


def member_verdicts(u: dict, given) -> tuple[dict, list[str]]:
    """The separate verdicts a review of a structure's unit records on some of the constants it
    covers (its constructor or a projection), as the report records them under the verdict
    (`verdict.members`, `{name: {group, value, detail}}`), and what is wrong with `given`
    (`{name: {verdict, detail}}`): each name one the unit covers other than the structure, each
    verdict one of the protocol's, with its detail unless it is "faithful". The unit's own
    verdict holds for every constant without one. Empty when nothing is given."""
    if not given:
        return {}, []
    if not isinstance(given, dict):
        return {}, ["the separate verdicts are {name: {verdict, detail}}"]
    covered = [m["name"] for m in u.get("members") or []]
    out, why = {}, []
    for name, v in given.items():
        v = v if isinstance(v, dict) else {"verdict": v}
        value = v.get("verdict", v.get("value"))
        detail = v.get("detail") or ""
        if name not in covered:
            why.append(f"{name} is not a constructor or projection that {u.get('id')} covers"
                       + (f" ({', '.join(covered)})" if covered else ""))
            continue
        group = next((g for g, vs in VERDICTS.items() if value in vs), None)
        # A constructor or projection has no refutation and corrects no clause.
        if group is None or value in REFUTE_ONLY | CORRECTION_ONLY:
            why.append(f"the verdict on {name}, {value!r}, is not one of: "
                       + ", ".join(x for vs in VERDICTS.values() for x in vs
                                   if x not in REFUTE_ONLY | CORRECTION_ONLY))
            continue
        if not isinstance(detail, str):
            why.append(f"the detail of the verdict on {name} is not text")
            continue
        if value != "faithful" and not detail.strip():
            why.append(f"the verdict {value!r} on {name} needs its detail")
            continue
        out[name] = {"group": group, "value": value, "detail": detail.strip()}
    return out, why


def changed_judgement(u: dict, blind: str | None, given) -> tuple[dict | None, list[str]]:
    """A judgement the reviewer changed after the author's review was shown, as the report keeps
    it beside the blind verdict (`changed_judgement`: `reason` and the revised `verdict`,
    `{group, value, detail}`, or None when they name none), and what is wrong with `given`
    (`{reason, verdict, detail}`). The reason is required; a revised verdict is one of the
    unit's, other than the blind one (`blind`), with the detail it needs (`detail_asked`). None
    when nothing is given. The review page applies the same rule (`changedJudgement` in
    `web/src/lib/review.js`; tests/fixtures/review/changed-judgement.json holds both to it)."""
    given = given if isinstance(given, dict) else {}
    why: list[str] = []

    def text(k: str, what: str) -> str:
        v = given.get(k)
        if v is None or isinstance(v, str):
            return (v or "").strip()
        why.append(f"{what} is not text")
        return ""

    reason, verdict = text("reason", "the reason"), text("verdict", "the revised verdict")
    detail = text("detail", "the revised verdict's detail")
    if not (reason or verdict or detail or why):
        return None, []
    if not reason:
        why.append("a changed judgement says why it changed: give the reason")
    out = {"reason": reason, "verdict": None}
    if detail and not verdict:
        why.append("a detail belongs to a revised verdict: name the verdict too")
    if verdict:
        group = verdict_group(u, verdict)
        table = STEP_VERDICTS if u.get("kind") == "step" else VERDICTS
        if group is None:
            why.append(f"the revised verdict {verdict!r} is not one of: "
                       + ", ".join(v for vs in table.values() for v in vs))
        elif verdict in REFUTE_ONLY and not u.get("refute"):
            why.append(f"{verdict!r} applies only to a unit with a refutation")
        elif verdict in CORRECTION_ONLY and not u.get("correction"):
            why.append(f"{verdict!r} applies only to a correction or a special case of a "
                       "printed clause")
        elif verdict == blind:
            why.append(f"{verdict!r} is the verdict recorded before the author's review: a "
                       "changed judgement names another verdict, or only its reason")
        elif detail_asked(u, verdict) and not detail:
            asked = detail_asked(u, verdict)
            why.append(f"the revised verdict {verdict!r} needs its detail: "
                       f"{asked[0].lower()}{asked[1:]}")
        out["verdict"] = {"group": group, "value": verdict, "detail": detail}
    return out, why


# A model reviewer's declaration of its family relative to the statements' author, as a report
# records it (`same_family_as_author`), in the words the reader uses too (`data/semantic.json`):
# three answers, kept apart. A value that is none of them reads as unknown, never as either
# known answer.
FAMILY = {k: v["label"] for k, v in json.loads(
    (Path(__file__).parent / "data" / "semantic.json").read_text(encoding="utf-8"))
    ["family"].items()}


def family_of(reviewer: dict | None) -> str | None:
    """A model reviewer's declared family (`yes`, `no` or `unknown`); None for a person."""
    rv = reviewer or {}
    if rv.get("kind") != "model":
        return None
    return rv.get("same_family_as_author") if rv.get("same_family_as_author") in FAMILY \
        else "unknown"


def same_family_rule(reviewer: dict | None) -> bool:
    """Whether promotion's same-family rule applies to a reviewer's reports
    (`promote.check_report`): a model reviewer not declared of a different family from the
    statements' author. Such a report is promoted only when the maintainer accepts it
    explicitly (`--accept-same-family`)."""
    return family_of(reviewer) in ("yes", "unknown")


def family_note(reviewer: dict | None) -> str | None:
    """What `review next` and `review status` say once of a model reviewer's declaration and of
    the promotion rule it meets; None for a person."""
    fam = family_of(reviewer)
    if fam is None:
        return None
    who = f"You review as {reviewer['id']}, {FAMILY[fam]} (self-declared"
    if fam == "no":
        return who + "): promotion's same-family rule does not apply to your reports."
    return (who + "; --same-family yes|no|unknown declares it). `review promote` refuses the "
            "report of a model reviewer of the statements' author's family, or of unknown "
            "family, unless the maintainer accepts it explicitly; each report records your "
            "declaration, and one accepted so says that it was.")


def parse_reviewer(who: str, same_family: str = "unknown") -> dict:
    """`human:NAME` or `llm:MODEL`, as the protocol writes reviewer ids."""
    m = re.fullmatch(r"(human|llm):(\S+)", who or "")
    if not m:
        raise ReviewError("give the reviewer as human:NAME or llm:MODEL (--as, or the "
                          "MACHINECHECKED_REVIEWER environment variable)", "invalid")
    kind = "human" if m.group(1) == "human" else "model"
    return {"id": who, "kind": kind, "name": m.group(2).replace("-", " ") if kind == "human" else None,
            "model": m.group(2) if kind == "model" else None,
            "same_family_as_author": "no" if kind == "human" else same_family,
            "identity": "self-declared"}


class Session:
    """One reviewer's work on the queue of the last build.

    `target` is the full assessment's configuration, or the working directory of the build
    (`<project>/.machinechecked` for the zero-configuration view): the session reads that
    build's site data (in `data_dir`, when the site is elsewhere) and keeps the work beside it.

    The work is kept in a workspace of the working directory: the one `workspace` names (the
    reviewer's own), else the reviewer's workspace of the `mode` given (opened if there is
    none), else the reviewer's first workspace (`review-work/<reviewer>.json`). The session's
    mode is its workspace's; it is chosen when the workspace is opened, and only a `mode`
    operation of the workspace changes it, keeping what was seen.

    `evidence` says what the site data is when it is not a build of this working directory:
    the provenance of a review snapshot (`review_snapshot.provenance`), which each report
    records."""

    def __init__(self, target: Config | Path, reviewer: dict, workspace: str | None = None,
                 mode: str | None = None, data_dir: Path | None = None,
                 root: Path | None = None, evidence: dict | None = None):
        work = Path(getattr(target, "out_dir", target))
        self.work_dir = work
        # The Lean project: what Lean read of it before tells whether a workspace's records are
        # current, for the informed order (no Lean runs).
        self.root = Path(root) if root else None
        self.order_record: dict | None = None
        self.evidence = evidence
        self.data = Path(data_dir) if data_dir else work / "site" / "data"
        if not (self.data / "review-queue.json").exists():
            raise ReviewError(NO_BUILD, "no-build")
        self.site = cmp.Site(self.data)
        self.index = self.site.index
        self.queue = json.loads((self.data / "review-queue.json").read_text(encoding="utf-8"))
        self.units = {u["id"]: u for u in self.queue["units"]}
        # The constants a structure's unit covers (its constructor and projections), by the id
        # a unit of their own would have: they are reviewed in the structure's unit.
        self.member_of = {"def:" + m["name"]: u["id"] for u in self.queue["units"]
                          for m in u.get("members") or []}
        self.reviewer = reviewer
        if mode is not None and mode not in wsp.MODES:
            raise ReviewError(f"mode {mode!r} is not one of: {', '.join(wsp.MODES)}", "invalid")
        self.path = self._workspace_path(workspace, mode)
        try:
            self.workspace = wsp.read(self.path) if self.path.exists() else \
                wsp.new(reviewer, mode or "independent")
        except (ValueError, wsp.WorkspaceError) as e:
            raise ReviewError(f"{self.path}: {e}", "workspace") from None
        self.workspace.setdefault("review", {"drafts": {}, "reports": []})
        self.work = self.workspace["review"]
        # The drafts as this session read them: a step saves its unit's draft only while the
        # saved one is still this (`_save`).
        self._read = copy.deepcopy(self.work.get("drafts") or {})

    def _workspace_path(self, wid: str | None, mode: str | None) -> Path:
        try:
            if wid:
                p = wsp.find(self.work_dir, wid)
                ws = wsp.read(p)
                owner = (ws.get("reviewer") or {}).get("id")
                if owner and not self.is_reviewer(owner):
                    raise ReviewError(f"{wid} is the workspace of {owner}: review in a workspace "
                                      "of your own", "workspace")
                if mode and ws["mode"] != mode:
                    raise ReviewError(f"{wid} is an {ws['mode']} workspace. A workspace's mode is "
                                      "chosen when it is opened; a `mode` operation of `workspace "
                                      "update` changes it and keeps what it records you had seen",
                                      "workspace")
                return p
            if mode:
                return wsp.open_for(self.work_dir, self.reviewer, mode, flag="--workspace")
        except wsp.WorkspaceError as e:
            raise ReviewError(str(e), "workspace") from None
        return wsp.store(self.work_dir) / f"{wsp.reviewer_slug(self.reviewer['id'])}.json"

    @property
    def mode(self) -> str:
        return self.workspace.get("mode") or "independent"

    @property
    def informed(self) -> bool:
        return self.mode == "informed"

    def save(self):
        wsp.save_review(self.path, self.work, self.reviewer)
        self._read = copy.deepcopy(self.work["drafts"])

    def _save(self, uid: str, add: dict | None = None, remove: dict | None = None) -> None:
        """Save unit `uid`'s draft as this session now holds it (with a report submitted, or
        one taken back), leaving the rest of the workspace as it is on disk. Refused when the
        saved draft changed since this session read it: another window or terminal is working
        on the unit."""
        try:
            wsp.save_review_unit(self.path, uid, self._read.get(uid),
                                 self.work["drafts"].get(uid), self.reviewer, add, remove)
        except wsp.DraftChanged as e:
            raise ReviewError(
                f"{uid} was changed meanwhile, in another window or terminal: nothing was saved. "
                "Look at it again (`review status`, or reload the review page) and repeat the "
                "step", "conflict",
                [{"id": uid, "current": e.current, "proposed": self.work["drafts"].get(uid)}]) \
                from None
        self._read[uid] = copy.deepcopy(self.work["drafts"].get(uid))

    # -- the queue -------------------------------------------------------------------------

    def unit(self, uid: str) -> dict:
        u = self.units.get(uid)
        if u is None and uid in self.member_of:
            raise ReviewError(f"{uid} is reviewed with its structure, in unit "
                              f"{self.member_of[uid]}: one reading and one verdict cover the "
                              "structure, its constructor and its projections", "unknown-unit")
        if u is None:
            kept =" (your draft of it is kept)" if uid in (self.work.get("drafts") or {}) else ""
            raise ReviewError(f"no unit {uid} in the queue of release {self.queue['release']}"
                              f"{kept}: `review status` lists the units", "unknown-unit")
        return u

    @staticmethod
    def _fp(u: dict) -> str:
        return u.get("fingerprint") or json.dumps(u.get("fingerprints") or {}, sort_keys=True)

    def reported(self, u: dict) -> bool:
        return self.report_of(u) is not None

    def report_of(self, u: dict) -> dict | None:
        """This reviewer's report of `u`'s current Lean, if they have submitted one."""
        return next((r for r in reversed(self.work["reports"])
                     if r["unit"]["id"] == u["id"] and _pinned(r) == self._fp(u)), None)

    def would_reveal(self, u: dict) -> list[str]:
        """The other units whose Lean step 2 of `u` shows and whose reading this reviewer has
        not locked yet: if they review those units afterwards, those readings will not be blind."""
        out = []
        for i in ((u.get("reveals") or {}).get("lean") or []):
            other = self.units.get(i)
            if i == u["id"] or other is None or other.get("state") == "reviewed" \
                    or self.reported(other):
                continue
            d = self.work["drafts"].get(i)
            if d is None or d.get("stage") == "read":
                out.append(i)
        return out

    def progress(self) -> list[dict]:
        """Each draft's step and when each step was taken, for resuming after an interruption:
        whether the Lean was shown (`shown`, with its time when it was recorded) tells whether a
        reading may still be locked blind."""
        return [{"unit": uid, "step": d.get("stage"), "locked_at": d.get("locked_at"),
                 "shown": bool(d.get("shown_fingerprint") or d.get("shown_at")),
                 "shown_at": d.get("shown_at"), "decided_at": d.get("decided_at"),
                 "author_shown_at": d.get("author_shown_at")}
                for uid, d in self.work["drafts"].items()]

    def open_units(self, order: str = "priority") -> list[dict]:
        """The units left to review, in the order asked (`review_queue.ORDERS`): the queue's
        (`priority`), the paper's (`document`), or the queue's with what the workspaces of this
        working directory record as open and their saved main results (`informed`; the records
        it read are then in `order_record`). Those records are prior interpretations: an
        informed order records that exposure in this reviewer's workspace, for the claims it drew
        on, so that a later reading of them is not taken as blind."""
        units = [u for u in self.queue["units"] if u["state"] != "reviewed"
                 and not self.reported(u)]
        if order == "priority":
            return units
        if order == "document":
            return rq.arrange(units, {}, "document", self.index.get("claims") or [])
        if order != "informed":
            raise ReviewError(f"order {order!r} is not one of: {', '.join(rq.ORDERS)}")
        units, drawn, self.order_record = informed_order(units, self.work_dir, self.data,
                                                         self.root, self.queue)
        if drawn:
            self.expose(drawn, ORDER_EXPOSURE)
        return units

    def expose(self, claims: list[str], how: str,
               what: tuple[str, ...] = ("prior interpretations",)) -> None:
        """Record in this reviewer's workspace that they have seen `what` (prior interpretations,
        or the Lean) of `claims`, unless it already records that."""
        if not claims:
            return
        known = {c.get("id") for c in self.site.claims}
        unknown = sorted(c for c in claims if c not in known)
        if unknown:
            raise ReviewError(f"no claim {', '.join(map(str, unknown))} in release "
                              f"{self.queue['release']}", "invalid")
        for e in self.workspace.get("exposure") or []:
            if set(what) <= set(e.get("what", [])) and (
                    e.get("claims") is None or set(claims) <= set(e["claims"])):
                return
        if not self.path.exists():
            self.save()
        try:
            wsp.update(self.path, [{"op": "exposure", "what": list(what),
                                    "claims": sorted(claims), "how": how}],
                       by=self.reviewer["id"])
        except wsp.WorkspaceError as e:
            raise ReviewError(str(e), "invalid") from None
        self.workspace = wsp.read(self.path)
        self.work = self.workspace["review"]
        self._read = copy.deepcopy(self.work["drafts"])

    def draft(self, u: dict, stage: str | None = None) -> dict:
        d = self.work["drafts"].get(u["id"])
        if stage is not None and (d is None or d["stage"] != stage):
            have = d["stage"] if d else "not started"
            raise ReviewError(f"{u['id']} is at step '{have}'; this needs step '{stage}' "
                              f"(read → compare → author → submitted)", "order")
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
        includes u's Lean or u's author review; for a structure's unit, those of its constructor
        and projections reviewed as units of their own count as its own. With `before`, only
        what was recorded by that time; a record without its time counts."""
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
        # A structure's constructor and projections are the structure's unit: work on one of
        # them as a unit of its own (in a queue before they were reviewed together) showed its
        # Lean, as an earlier draft of this unit would have.
        members = {"def:" + m["name"]: m.get("fingerprint") for m in u.get("members") or []}
        for ws in [self.workspace, *mine]:
            own = ws is self.workspace
            work = ws.get("review") or {}
            for i, lean, author, pinned in _passes(
                    self._without_locked_with(u, work) if own else work, by):
                unit = i if own else f"{i} (workspace {ws['id']})"
                if i in members:
                    if pinned in (None, members[i]):
                        for what, ok in (("Lean", lean), ("author's review", author)):
                            if ok:
                                add(unit, what)
                    continue
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

    def begin(self, uid: str) -> tuple[dict, list[dict]]:
        """Step 1 started: the unit's draft (begun now if there is none) and what this reviewer
        had already seen of the unit's Lean or author's review (`revealed_by`). In an informed
        session a unit can be read again at any step."""
        u = self.unit(uid)
        d = self._may_begin(u)
        if d is None:
            self.work["drafts"][uid] = d = {"stage": "read", "reading": ""}
            self._save(uid)
        return d, self.revealed_by(u)

    def _may_begin(self, u: dict) -> dict | None:
        """The draft of `u` that step 1 continues (None: it begins one), refused when `u` is
        reported or, in independent review, its reading is locked."""
        if self.reported(u):
            raise ReviewError(f"{u['id']} is already reported by {self.reviewer['id']}",
                              "reported")
        d = self.draft(u)
        if d is not None and d["stage"] != "read" and not self.informed:
            raise ReviewError(f"{u['id']}: the reading is already locked", "order")
        return d

    def read(self, uid: str, as_json: bool = False, context: bool = False) -> str | dict:
        """Step 1: the unit's passages; with `context`, each with the paper around it
        (`with_context`)."""
        u = self.unit(uid)
        _, seen = self.begin(uid)
        warn = ("\n\nNOTE: you have already seen " + " and ".join(
            f"the {s['what']} of this unit (in {s['unit']})" for s in seen)
            + ". Your reading will not be blind, and the report will say so.") if seen else ""
        reveals = self.would_reveal(u)
        if reveals:
            warn += "\n\n" + reveals_note(reveals, "Step 2 of this unit (`review show`) will show")
        pk = self.packet(u, "read")
        if context:
            self.with_context(pk)
        if as_json:
            return {**pk, "review": {"step": "read", "mode": self.mode, "seen_before": seen,
                                     "reveals": reveals}}
        lean = step_lean_text(pk.get("unit") or {})
        return cmp.packet_text(pk) + (f"\n\n{lean}" if lean else "") + warn

    def with_context(self, pk: dict) -> dict:
        """The read step's packet `pk` with, on each passage, the paper around it
        (`surroundings`, `passage_context.py`), read from the build's copy of the paper's
        source. A review snapshot holds the passages only, so a review of one has none."""
        from .passage_context import surroundings
        chunks = [ch for ch in (self.site.chunk(p["claim"]) for p in pk["paper"]["passages"])
                  if ch is not None]
        got = surroundings(self.site, chunks, self.work_dir / "sources", self.work_dir / "build",
                           "a review snapshot holds the passages the steps show, not the rest "
                           "of the paper's source: read their context in the paper"
                           if self.evidence else None)
        for p in pk["paper"]["passages"]:
            if p["claim"] in got:
                p["surroundings"] = got[p["claim"]]
        pk["paper"]["context"] = "requested"
        return pk

    def _started(self, u: dict) -> dict:
        """An informed session's draft of `u`, begun now if there is none: its steps need no
        earlier one."""
        d = self.draft(u)
        if d is None:
            if self.reported(u):
                raise ReviewError(f"{u['id']} is already reported by {self.reviewer['id']}",
                                  "reported")
            self.work["drafts"][u["id"]] = d = {"stage": "read", "reading": ""}
        return d

    def lock(self, uid: str, reading: str) -> list[dict]:
        """Step 1's record: the reviewer's reading of the paper, with the digests of the
        passages read and what they had already seen. Independent review locks it before the
        Lean is shown. An informed session records it when the reviewer gives it, until the
        verdict; it is not blind, and the report says so. Returns what the reviewer had already
        seen of the unit (`revealed_by`), so that they are told at once."""
        u = self.unit(uid)
        d = self._lockable(u)
        _check_reading(reading)
        return self._record_lock(u, d, reading, now(), self.revealed_by(u))

    def _lockable(self, u: dict) -> dict:
        """The draft whose reading step 1 locks: in independent review, one at step 1, of a
        unit not reported; in an informed session, any draft before its verdict."""
        uid = u["id"]
        if self.informed:
            d = self._started(u)
            if d["stage"] == "author":
                raise ReviewError(f"{uid}: the verdict is recorded; the reading it was made with "
                                  "is kept", "order")
            return d
        r = self.report_of(u) if self.draft(u) is None else None
        if r is not None:
            raise ReviewError(f"{uid} is already reported by {self.reviewer['id']} (submitted "
                              f"{r.get('submitted_at')}): its reading is the one in that "
                              "report, and a new one would not be blind", "reported")
        return self.draft(u, "read")

    def _record_lock(self, u: dict, d: dict, reading: str, at: str, seen: list[dict],
                     locked_with: list[str] | None = None) -> list[dict]:
        """Record the reading on `u`'s draft `d`, locked at `at`, with what the reviewer had
        already seen of `u` (`seen`, returned) and the units locked with it (`lock_together`)."""
        # The passages read are those of this queue's release: the report pins their digests.
        d.update(reading=reading, revealed_by=seen, locked_at=at,
                 source_sha256=u.get("source_sha256"), stage="compare")
        if locked_with:
            d["locked_with"] = list(locked_with)
        else:
            d.pop("locked_with", None)
        self._save(u["id"])
        return seen

    # -- one reading for several definitions of one passage (#616) ---------------------------

    def shared_reading(self, uids: list[str]) -> list[dict]:
        """The units `uids`, when one reading can be locked for them all: definitions whose
        reading material is the same, every passage of the same claims, complete and with the
        same pins. Refused otherwise, naming the unit that differs. The group is these steps'
        alone: each unit keeps its own draft, verdict and report."""
        if len(uids) < 2 or len(set(uids)) != len(uids):
            raise ReviewError("name two or more different units to read together", "invalid")
        units = [self.unit(i) for i in uids]
        other = [u["id"] for u in units if u["kind"] != "def"]
        if other:
            raise ReviewError(f"{', '.join(other)}: only definitions are read together, from "
                              "the passages they share; review the others one at a time",
                              "invalid")

        def material(u: dict) -> tuple[dict, list[str]]:
            p = self.packet(u, "read")["paper"]
            return p, sorted(json.dumps(x, sort_keys=True) for x in p["passages"])

        first, same = material(units[0])
        if not (first["complete"] and first["passages"] and all(
                x.get("available") and x.get("complete") for x in first["passages"])):
            raise ReviewError(f"{units[0]['id']}: this build does not hold the whole of its "
                              "passages, so a reading shared with other units cannot be checked "
                              "against them: review each definition on its own", "invalid")
        for u in units[1:]:
            p, mine = material(u)
            if mine != same or not p["complete"]:
                raise ReviewError(f"{u['id']} is not read from exactly the passages of "
                                  f"{units[0]['id']}: review it on its own", "invalid")
        return units

    def read_together(self, uids: list[str], as_json: bool = False,
                      context: bool = False) -> str | dict:
        """Step 1 for several definitions read from the same passages (`shared_reading`): the
        passages once, and a draft begun for each unit, with what the reviewer had already seen
        of each. Every unit's refusals are checked before any draft is begun."""
        units = self.shared_reading(uids)
        for u in units:
            self._may_begin(u)
        seen = {u["id"]: self.begin(u["id"])[1] for u in units}
        # Step 2 of one shows the Lean of another only after both readings are locked.
        reveals = sorted({i for u in units for i in self.would_reveal(u) if i not in uids})
        pk = self.packet(units[0], "read")
        pk["request"] = {"units": list(uids), "stage": "read"}
        pk.pop("unit", None)
        pk["units"] = [self.packet(u, "read")["unit"] for u in units]
        if context:
            self.with_context(pk)
        if as_json:
            return {**pk, "review": {"step": "read", "mode": self.mode, "units": list(uids),
                                     "seen_before": seen, "reveals": reveals}}
        lock = f"review lock {uids[0]} READING " + " ".join(f"--with {i}" for i in uids[1:])
        head = (f"The passages below are the whole of the reading material of {and_list(uids)}. "
                f"Read them once: `{lock}` locks one reading for them all. Each is then shown "
                "with its own Lean and takes its own verdict.")
        warn = "".join(
            f"\n\nNOTE: you have already seen " + " and ".join(
                f"the {s['what']} of {uid} (in {s['unit']})" for s in got)
            + f". Your reading of {uid} will not be blind, and its report will say so."
            for uid, got in seen.items() if got)
        if reveals:
            warn += "\n\n" + reveals_note(reveals, "Step 2 of these units (`review show`) will "
                                                   "show")
        return head + "\n\n" + cmp.packet_text(pk) + warn

    def lock_together(self, uids: list[str], reading: str) -> dict[str, list[dict]]:
        """Step 1's record for several definitions read from the same passages: one reading,
        locked at one time on each unit's draft, after every unit's material (`shared_reading`)
        and order (`_lockable`) are checked; nothing is recorded when one is refused. Returns
        what the reviewer had already seen of each unit."""
        units = self.shared_reading(uids)
        drafts = [self._lockable(u) for u in units]
        _check_reading(reading)
        # What had been seen of each, before any of the readings is locked.
        seen = [self.revealed_by(u) for u in units]
        at = now()
        return {u["id"]: self._record_lock(u, d, reading, at, got,
                                           [i for i in uids if i != u["id"]])
                for u, d, got in zip(units, drafts, seen)}

    def locked_with(self, uid: str) -> list[str]:
        """The other units whose reading was locked with `uid`'s (`lock_together`), as its
        draft records them."""
        return sorted((self.work["drafts"].get(uid) or {}).get("locked_with") or [])

    def _without_locked_with(self, u: dict, work: dict) -> dict:
        """The review work `work` of this workspace without the passes of the units whose
        reading was locked with `u`'s at the same time (`locked_with`): in independent review
        each of them was at step 1 when the readings were locked together, so whatever their
        steps showed came after `u`'s lock, at a time a record to the second cannot tell
        apart from it."""
        d = self.work["drafts"].get(u["id"]) or {}
        group, at = set(d.get("locked_with") or []), d.get("locked_at")
        if not group or not at or self.informed:
            return work
        return {"reports": [r for r in work.get("reports") or []
                            if not ((r.get("unit") or {}).get("id") in group
                                    and (r.get("reading") or {}).get("locked_at") == at)],
                "drafts": {i: x for i, x in (work.get("drafts") or {}).items()
                           if not (i in group and x.get("locked_at") == at)}}

    def show(self, uid: str, as_json: bool = False, definitions: bool = False) -> str | dict:
        """Step 2: the unit's Lean, after the lock in independent review. The draft records the
        version shown, so that a verdict is recorded against the Lean that was shown. A unit
        this reviewer has reported is shown as it was reviewed: its Lean was seen already. With
        `definitions`, only the definitions it uses, as a compact listing
        (`compare.definitions_text`)."""
        u = self.unit(uid)
        d = self._started(u) if self.informed else self.draft(u)
        if d is None and not self.informed:
            r = self.report_of(u)
            if r is not None:
                note = (f"{uid} is reported (submitted {r.get('submitted_at')}, verdict "
                        f"{(r.get('verdict') or {}).get('value')}); this is the Lean you reviewed. "
                        "`review export` writes your reports.")
                if as_json:
                    return {**self.packet(u, "compare"),
                            "review": {"step": "reported", "mode": self.mode,
                                       "submitted_at": r.get("submitted_at")}}
                return note + "\n\n" + self._lean_or_definitions(u, definitions)
        if d is None or (d["stage"] == "read" and not self.informed):
            raise ReviewError(f"{uid}: lock your reading first (`review lock`); the Lean is shown "
                              "only after it", "order")
        reveals = self.would_reveal(u)
        shown = {"stage": "compare" if d["stage"] == "read" else d["stage"],
                 "shown_fingerprint": self._fp(u)}
        if any(d.get(k) != v for k, v in shown.items()) or "shown_at" not in d:
            d.update(shown)
            d.setdefault("shown_at", now())
            self._save(uid)
        together = self.locked_with(uid)
        if as_json:
            return {**self.packet(u, "compare"), "review": {
                "step": "compare", "mode": self.mode, "reveals": reveals,
                **({"locked_with": together} if together else {})}}
        text = self._lean_or_definitions(u, definitions)
        if together:
            text = (f"Your reading of {uid} was locked with that of {and_list(together)}, from the "
                    f"same passages. This is the Lean of {uid} alone: compare it with your "
                    "reading and give it a verdict of its own.\n\n") + text
        return (reveals_note(reveals, "This shows") + text) if reveals else text

    def _lean_or_definitions(self, u: dict, definitions: bool) -> str:
        """Step 2's text: the unit's Lean, or only the definitions it uses (`definitions`)."""
        return cmp.definitions_text(self.packet(u, "compare")) if definitions \
            else self.lean_text(u)

    def decide(self, uid: str, verdict: str, comparison: str, detail: str = "",
               witness: str = "", coverage: dict | None = None, checklist: dict | None = None,
               shown: str | dict | None = None, members: dict | None = None) -> None:
        """Step 2's record: the verdict, the comparison and, with them, the reviewer's coverage
        (`correspondence`) and checklist, all before the author's review is shown (in an
        informed session, until the report is submitted). The Lean the verdict is about is the
        version shown (`shown`, the unit's fingerprint as the reviewer's page drew it, or as
        `show` recorded it): refused as stale when the build has changed it since. For a
        structure's unit, `members` records a separate verdict on one of the constants it covers
        (`{name: {verdict, detail}}`, `member_verdicts`): the unit's verdict holds for the rest."""
        u = self.unit(uid)
        if self.informed:
            d = self._started(u)
        else:
            d = self.draft(u, "compare")
        table = STEP_VERDICTS if u["kind"] == "step" else VERDICTS
        group = verdict_group(u, verdict)
        if group is None:
            raise ReviewError(f"verdict {verdict!r} is not one of: "
                              + ", ".join(v for vs in table.values() for v in vs), "invalid")
        if verdict in REFUTE_ONLY and u.get("kind") != "spec":
            # Not "only to a refuted one": that would say, before the verdict, whether it is.
            raise ReviewError(f"{verdict!r} applies only to a locked proposition (a spec unit)",
                              "invalid")
        if verdict in CORRECTION_ONLY and not u.get("correction"):
            raise ReviewError(f"{verdict!r} applies only to a correction or a special case of a "
                              "printed clause", "invalid")
        asked = detail_asked(u, verdict)
        if asked and not (detail or "").strip():
            raise ReviewError(f"verdict {verdict!r} needs --detail: {asked[0].lower()}{asked[1:]}",
                              "invalid")
        if not (comparison or "").strip():
            raise ReviewError("the comparison is empty", "invalid")
        was = self._fp(shown) if isinstance(shown, dict) else shown or d.get("shown_fingerprint")
        if was is not None and was != self._fp(u):
            raise ReviewError(f"the Lean of {uid} changed since it was shown to you (the build is "
                              f"now release {self.queue['release']}): look at it again (`review "
                              f"show {uid}`, or reload the review page), then record the verdict",
                              "stale")
        checklist = check_checklist(checklist)
        if isinstance(coverage, dict) and isinstance(coverage.get("bridge"), dict):
            coverage = {**coverage, "bridge": {**coverage["bridge"],
                                               "target_fingerprint": self.target_pin(
                                                   u, coverage["bridge"])}}
        cor, why = correspondence(u, verdict, coverage)
        if why:
            raise ReviewError("; ".join(why), "invalid")
        apart, why = member_verdicts(u, members)
        if why:
            raise ReviewError("; ".join(why), "invalid")
        if apart:
            d["members"] = apart
        else:
            d.pop("members", None)
        d.update(group=group, verdict=verdict, detail=detail or "", comparison=comparison,
                 witness=witness or "", checklist=checklist, correspondence=cor,
                 decided_at=now(), stage="author",
                 # The Lean the verdict is about: the report pins this version.
                 lean={k: u.get(k) for k in ("fingerprint", "fingerprints", "legacy_hash")})
        self._save(uid)

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
        """Step 3: the author's review and what else was recorded about the correspondence,
        with the author's account of each clause a locked proposition states (the outcome the
        earlier steps withhold), after the verdict in independent review."""
        u = self.unit(uid)
        d = self._started(u) if self.informed else self.draft(u, "author")
        if "author_shown_at" not in d:
            d["author_shown_at"] = now()
            self._save(uid)
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
        out = out or ["No review by the author is recorded for this unit."]
        out += self._account(u) + self._refutation_scope(u)
        # What the verdict just recorded means for the claim (#685).
        out += [r.get("line") or rq.refutation_line(r) for r in u.get("refuted_by") or []]
        if u.get("kind") == "step":
            out += [proposal_text(p) for p in [self.site.proposal(c["id"])
                                               for c in u.get("claims") or []] if p]
        return "\n\n".join(out)

    def _account(self, u: dict) -> list[str]:
        """The author's account of each clause a locked proposition states, for step 3: the
        clause's place and name, its state, the printed clause a correction corrects, and the
        theorems that prove, refute or witness it (`compare.unit_account`)."""
        chunks = [ch for ch in (self.site.chunk(c["id"]) for c in u.get("claims") or []) if ch]
        return [f"The author's account of this proposition, for {a['claim']}\n"
                + "\n".join(a["lines"]) for a in cmp.unit_account(u, chunks)]

    def _refutation_scope(self, u: dict) -> list[str]:
        """The author's account of the scope of a proposition's refutation, for step 3: the
        readings its counterexample is declared to cover and not to cover, and what the class
        lemmas show of each standing assumption, with the statement of each theorem named
        (`review_queue.refutation_scope_text`). Authored, so shown only after the verdict."""
        return [f"Scope of the refutation of {s['claim']}, as its author records it\n"
                + "\n".join(s["lines"]) for s in u.get("refutation_scope") or []]

    def submit(self, uid: str, disagreements: str, changed: dict | None = None) -> dict:
        """The report, from the draft. Independent review submits after the author's review was
        shown; an informed session once a verdict is recorded. The report lists what the
        reviewer had seen before the reading was recorded, or, with no reading, before now.
        `changed` is a judgement the reviewer changed after the author's review
        (`changed_judgement`), kept beside the blind verdict, which stays as it was recorded;
        an informed session records its verdict again instead, until it submits."""
        u = self.unit(uid)
        if self.informed:
            d = self.draft(u)
            if d is None or "decided_at" not in d:
                raise ReviewError(f"{uid}: record a verdict first (`review decide`)", "order")
        else:
            d = self.draft(u, "author")
            if "author_shown_at" not in d:
                raise ReviewError(f"{uid}: read the author's review first (`review author`)",
                                  "order")
        # A changed judgement the draft keeps (typed on the review page, or given back by Undo)
        # stands unless another is given: dropping it would let the blind verdict pass silently.
        prev = d.get("changed") if isinstance(d.get("changed"), dict) else {}
        given = changed if changed is not None else \
            {k: prev.get(k) for k in ("reason", "verdict", "detail")}
        cj, why = changed_judgement(u, d.get("verdict"), given)
        if cj and self.informed:
            why = ["an informed review has no blind verdict to keep: record the verdict again "
                   "(`review decide`) until the report is submitted"]
        if why:
            raise ReviewError("; ".join(why), "invalid")
        # What reached this working directory after the lock (an investigation imported since,
        # say) but was seen before it is part of what the reading was not blind to.
        seen = list(d.get("revealed_by") or [])
        seen += [s for s in self.revealed_by(u, before=d.get("locked_at")) if s not in seen]
        d["revealed_by"] = seen
        if cj:
            same = {k: (prev.get(k) or "").strip() for k in ("reason", "verdict", "detail")} == {
                "reason": cj["reason"], "verdict": (cj["verdict"] or {}).get("value") or "",
                "detail": (cj["verdict"] or {}).get("detail") or ""}
            d["changed"] = {"reason": cj["reason"],
                            "verdict": (cj["verdict"] or {}).get("value"),
                            "detail": (cj["verdict"] or {}).get("detail") or "",
                            "recorded_at": prev.get("recorded_at") if same and
                            prev.get("recorded_at") else now()}
        else:
            d.pop("changed", None)
        r = report(self.index, u, d, self.reviewer, disagreements or "none", self.mode,
                   self.evidence)
        self.work["reports"].append(r)
        del self.work["drafts"][uid]
        self._save(uid, add=r)
        return r

    def edit(self, uid: str, stage: str, fields: dict) -> dict:
        """Save what the reviewer has typed so far at the step `stage` (the review page saves as
        it is typed): only the fields the step may still change (`EDITABLE`). Refused when the
        unit is at another step, as when a terminal moved it on meanwhile."""
        u = self.unit(uid)
        d = self.draft(u, stage)
        if not isinstance(fields, dict):
            raise ReviewError("the fields are an object", "invalid")
        bad = sorted(set(fields) - set(EDITABLE.get(stage, ())))
        if bad:
            raise ReviewError(f"{', '.join(bad)}: not changed at step '{stage}'", "order")
        fields = dict(fields)
        for k, v in fields.items():
            if k == "checklist":
                fields[k] = check_checklist(v)
            elif k == "bridge":
                if v is not None and not (isinstance(v, dict) and all(
                        x is None or isinstance(x, str) for x in v.values())):
                    raise ReviewError("a bridge is {theorem, target}", "invalid")
            elif k == "changed":
                if v is not None and not (isinstance(v, dict) and set(v) <= {
                        "reason", "verdict", "detail", "recorded_at"} and all(
                        x is None or isinstance(x, str) for x in v.values())):
                    raise ReviewError("a changed judgement is {reason, verdict, detail}",
                                      "invalid")
                if v is not None:
                    # Its time is the engine's: kept while it is the judgement Undo gave back.
                    v = {x: v.get(x) for x in ("reason", "verdict", "detail")}
                    old = d.get("changed") if isinstance(d.get("changed"), dict) else {}
                    if old.get("recorded_at") and all((old.get(x) or "") == (v.get(x) or "")
                                                      for x in v):
                        v["recorded_at"] = old["recorded_at"]
                    fields[k] = v
            elif v is not None and not isinstance(v, str):
                raise ReviewError(f"{k} is text", "invalid")
            elif isinstance(v, str) and len(v) > wsp.TEXT_CHARS:
                raise ReviewError(f"{k} is longer than {wsp.TEXT_CHARS} characters", "invalid")
        changed = {k: v for k, v in fields.items() if d.get(k) != v}
        if changed:
            d.update(changed)
            self._save(uid)
        return d

    def undo(self) -> dict:
        """Take back this reviewer's last report, as the review page's Undo does: its unit
        returns to step 3 with its reading, verdict and coverage as recorded, and the report
        is removed until it is submitted again."""
        if not self.work["reports"]:
            raise ReviewError("there is no report to take back", "order")
        r = self.work["reports"][-1]
        uid = (r.get("unit") or {}).get("id")
        if uid in self.work["drafts"]:
            raise ReviewError(f"{uid} has a draft in progress; finish or keep it first", "order")
        rd, cmp_, v, a = (r.get(k) or {} for k in ("reading", "comparison", "verdict",
                                                   "author_review"))
        pins = r.get("pins") or {}
        self.work["drafts"][uid] = {
            "stage": "author", "reading": rd.get("text") or "", "locked_at": rd.get("locked_at"),
            "revealed_by": rd.get("revealed_by") or [], "source_sha256": pins.get("source_sha256"),
            **({"locked_with": rd["locked_with"]} if rd.get("locked_with") else {}),
            "comparison": cmp_.get("text") or "", "witness": cmp_.get("witness") or "",
            "checklist": cmp_.get("checklist") or {}, "decided_at": cmp_.get("decided_at"),
            "group": v.get("group"), "verdict": v.get("value"), "detail": v.get("detail") or "",
            **({"members": v["members"]} if v.get("members") else {}),
            "correspondence": r.get("correspondence"),
            "lean": {k: pins.get(k) for k in ("fingerprint", "fingerprints", "legacy_hash")},
            "author_shown_at": a.get("shown_at"), "disagreements": a.get("disagreements") or "",
            **({"changed": changed_draft(r["changed_judgement"])}
               if isinstance(r.get("changed_judgement"), dict) else {})}
        self.work["reports"].pop()
        self._save(uid, remove=r)
        return self.work["drafts"][uid]

    def state(self) -> dict:
        """This reviewer's work as the review page shows it: the workspace (its id and mode),
        the drafts, the reports and the exposure it records, as saved now."""
        ws = wsp.read(self.path) if self.path.exists() else self.workspace
        rv = ws.get("review") or {}
        return {"schema": "machinechecked/review-work@1", "release": self.queue.get("release"),
                "workspace": {"id": ws["id"], "mode": ws.get("mode"),
                              "reviewer": (ws.get("reviewer") or {}).get("id")},
                "reviewer": self.reviewer["id"], "drafts": rv.get("drafts") or {},
                "reports": rv.get("reports") or [], "exposure": ws.get("exposure") or [],
                "editable": EDITABLE}

    def export(self, out: Path) -> Path:
        body = {"schema": REPORTS_SCHEMA, "project": (self.index.get("project") or {}).get("name"),
                "release": self.index["release"], "exported_at": now(),
                "workspace": {"id": self.workspace["id"], "mode": self.mode},
                **({"evidence": self.evidence} if self.evidence else {}),
                "reports": self.work["reports"]}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
        return out


def proposal_text(p: dict) -> str:
    """A proof step's author's proposed verdict (`steps.proposal`), for step 3: the verdict, the
    note and the theorem it names, which is the author's and not checked by Lean here. It
    completes no review and changes no status (#678)."""
    return (f"The author's proposed verdict on this step" + (f", by {p['by']}" if p.get("by")
                                                            else "")
            + f": {p.get('verdict')}" + (f". {p['note']}" if p.get("note") else "")
            + (f"\nIt names {p['theorem']} (the author's; Lean does not check it here)."
               if p.get("theorem") else "")
            + "\nA proposal completes no review: your verdict is the review, and a different "
              "conclusion goes in your response to the author or a finding.")


def _check_reading(reading: str) -> None:
    if len(reading.strip()) < 20:
        raise ReviewError("the reading is too short to record (20 characters at least)",
                          "invalid")


def step_lean_text(unit: dict) -> str | None:
    """What step 1 says of a proof step's Lean (`compare.step_lean`), naming none; None for
    any other unit."""
    if unit.get("kind") != "step" or "lean_linked" not in unit:
        return None
    if unit["lean_linked"]:
        return ("Lean is linked as establishing this step: step 2 (`review show`) shows it once "
                "your reading is locked.")
    if unit.get("route_linked"):
        return ("No Lean is linked as establishing this step. A different formal route used "
                "instead is recorded, which step 2 shows and which does not state the step: "
                "judge the printed step on the mathematics.")
    return ("No Lean is linked to this step: judge the printed step on the mathematics alone. "
            "Step 2 has no Lean to show; once your reading is locked, record the verdict "
            "(`review decide`) with the argument you checked as the comparison.")


def and_list(items: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def reveals_note(units: list[str], lead: str) -> str:
    """The warning that a step shows the Lean of other units still to be read blind."""
    return (f"NOTE: {lead} the Lean of {', '.join(units)} as well, whose reading you have not "
            "locked. Lock those readings first if you will review them: a reading locked after "
            "seeing their Lean is not blind, and promotion refuses it unless the maintainer "
            "accepts it.\n\n")


def check_checklist(given) -> dict:
    """The comparison's checklist as a report keeps it: each item marked matches, differs or
    unsure (an unmarked item is left out)."""
    if given is None:
        return {}
    if not isinstance(given, dict) or not all(
            isinstance(k, str) and (v is None or v in MARKS) for k, v in given.items()):
        raise ReviewError(f"a checklist marks items {', '.join(MARKS)}", "invalid")
    return {k: v for k, v in given.items() if v is not None}


def informed_order(units: list[dict], work_dir: Path, data_dir: Path, root: Path | None = None,
                   queue: dict | None = None) -> tuple[list[dict], list[str], dict]:
    """`units` (open units, in the queue's order) in the informed order: the queue's, with what
    every workspace of `work_dir` records as open, checked against the build whose site data is
    `data_dir` and what Lean read of the project at `root` before (no Lean runs;
    `review_queue.workspace_signals`), and what their saved main results say of each unit
    (`review_queue.main_result_signals`); the claims whose records it drew on; and which records
    it read (`informed_record`). Reading them is seeing prior interpretations of those claims;
    the caller records that. `queue` is the build's queue, whose record says whether the
    reverse references were traced in full."""
    from .targets import Snapshot
    snap = Snapshot(data_dir)
    spaces = [ws for _, ws in wsp.list_all(work_dir)]
    signals, drawn = rq.workspace_signals(units, spaces, snap, root)
    selections = [ws["main_results"] for ws in spaces if ws.get("main_results")]
    path = Path(data_dir) / "uses.json"
    uses = json.loads(path.read_text(encoding="utf-8")) \
        if snap.index.get("uses") and path.is_file() else None
    mains, more = rq.main_result_signals(units, selections, uses, snap.chunk)
    for k, v in mains.items():
        signals.setdefault(k, []).extend(v)
    drawn += [c for c in more if c not in drawn]
    trace = (((queue or {}).get("order") or {}).get("signals") or {}).get(rq.RELEVANCE)
    return (rq.arrange(units, signals), drawn,
            informed_record(snap, spaces, selections, uses, trace))


def informed_record(snap, spaces: list[dict], selections: list[dict], uses: dict | None,
                    trace: dict | None = None) -> dict:
    """Which records the informed order read, each `read`, `incomplete` or `not available` with
    why: the workspaces, and the trace from their saved main results through the build's
    reverse references (`trace`: the queue's record of them). Without the trace a saved main
    result itself is still marked."""
    out = {"workspaces": {"state": "read", "count": len(spaces)} if spaces else
           {"state": "not available", "why": "no workspace in the working directory"}}
    if not selections:
        out[rq.MAIN] = {"state": "not available",
                        "why": "no workspace saves the paper's main results (`workspace main`)"}
    elif uses is None:
        out[rq.MAIN] = {"state": "not available", "why": (
            "this build extracted no reverse references" if snap.index.get("mode") == "simple"
            else "the full assessment extracts no reverse references")
            + ": a saved main result itself is marked, not what it uses"}
    elif (trace or {}).get("state") == "incomplete":
        out[rq.MAIN] = dict(trace)
    else:
        out[rq.MAIN] = {"state": "read"}
    return out


def order_route(work_dir: Path, data_dir: Path, root: Path | None = None):
    """`GET /api/review-order?order=informed` of `machinechecked view`'s local server: the open
    units of the last build's queue in the informed order, each with its reason and priority
    record, the claims it drew on (`drawn`) and the records it read (`signals`), for the reader's
    review page; `root` is the Lean project, for what Lean read of it before. The page records,
    before it shows the order, that the reviewer has seen prior interpretations of those claims;
    this route writes nothing. The priority and document orders are in the queue the build
    wrote."""
    def get(q: dict) -> dict:
        order = (q.get("order") or ["informed"])[0]
        if order != "informed":
            raise ReviewError(f"order {order!r}: this route gives the informed order; the "
                              "priority and document orders are in data/review-queue.json")
        path = data_dir / "review-queue.json"
        if not path.exists():
            raise ReviewError(NO_BUILD, "no-build")
        queue = json.loads(path.read_text(encoding="utf-8"))
        units, drawn, record = informed_order(
            [u for u in queue["units"] if u["state"] != "reviewed"], work_dir, data_dir, root,
            queue)
        return {"schema": "machinechecked/review-order@1", "release": queue.get("release"),
                "order": "informed", "drawn": drawn,
                "exposure": {"what": ["prior interpretations"], "how": ORDER_EXPOSURE},
                "signals": record,
                "units": [{k: u.get(k) for k in ("id", "reason", "priority")} for u in units]}
    return get


def api(work_dir: Path, data_dir: Path) -> tuple[dict, dict]:
    """The review routes of `machinechecked view`'s local server, for the reader's review page:
    the same session, steps and checks as `machinechecked review`, on the reviewer's workspace.

    GET `/api/review?reviewer=&same_family=&workspace=` gives the reviewer's work (`state`).
    POST `/api/review` with `reviewer` (`same_family`, `workspace`) and `action`: `begin`
    (`unit`: step 1 started, with `seen_before`), `edit` (`unit`, `stage`, `fields`: what was
    typed so far), `lock` (`unit`, `reading`), `decide` (`unit`, `verdict`, `comparison`,
    `detail`, `witness`, `checklist`, `coverage`, and `shown`: the unit's `fingerprint` and
    `fingerprints` as the page drew it; with `show_author`, step 3 is shown at once), `author`
    (`unit`), `submit` (`unit`, `disagreements`: the `report`), `undo`, or `expose` (`claims`,
    `what`, `how`: material the reviewer saw outside the steps). Each answers with the work as
    saved after it. A refused step answers 400 with its message and `kind`; a draft changed
    meanwhile answers 409 with `conflicts`."""
    def session(q: dict) -> Session:
        who = parse_reviewer(q.get("reviewer") or "", q.get("same_family") or "unknown")
        return Session(work_dir, who, q.get("workspace") or None, data_dir=data_dir)

    def get(q: dict) -> dict:
        return session({k: (v or [None])[0] for k, v in q.items()}).state()

    def post(req: dict) -> dict:
        s = session(req)
        action, uid = req.get("action"), req.get("unit") or ""
        out: dict = {}
        if action == "begin":
            _, out["seen_before"] = s.begin(uid)
        elif action == "edit":
            s.edit(uid, req.get("stage") or "", req.get("fields") or {})
        elif action == "lock":
            out["seen_before"] = s.lock(uid, req.get("reading") or "")
        elif action == "decide":
            s.decide(uid, req.get("verdict") or "", req.get("comparison") or "",
                     req.get("detail") or "", req.get("witness") or "", req.get("coverage"),
                     req.get("checklist"), req.get("shown"), req.get("members"))
            if req.get("show_author"):
                s.author(uid)
        elif action == "author":
            s.author(uid)
        elif action == "submit":
            out["report"] = s.submit(uid, req.get("disagreements") or "", req.get("changed"))
        elif action == "undo":
            s.undo()
        elif action == "expose":
            what = req.get("what") or ["prior interpretations"]
            if not isinstance(what, list) or not set(what) <= {"Lean", "prior interpretations"}:
                raise ReviewError("`what` is a list of: Lean, prior interpretations", "invalid")
            claims = req.get("claims")
            if not isinstance(claims, list) or not all(isinstance(c, str) for c in claims):
                raise ReviewError("`claims` is a list of claim ids", "invalid")
            how = req.get("how")
            if not isinstance(how, str) or not how.strip():
                raise ReviewError("`how` says where the material was seen", "invalid")
            s.expose(claims, how.strip(), tuple(what))
        else:
            raise ReviewError(f"unknown action {action!r}", "invalid")
        return {**s.state(), **out}

    return {"/api/review": get}, {"/api/review": post}


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


def report(index: dict, u: dict, d: dict, reviewer: dict, disagreements: str,
           mode: str = "independent", evidence: dict | None = None) -> dict:
    """The report, in the form the reader's review page exports (`buildReport`). It pins the Lean
    the verdict was recorded against (the draft's `lean`), and its `mode` is the session's: an
    informed report keeps the reading only when the reviewer recorded one, with its time, and
    never a lock it did not have. A report made against a review snapshot records it
    (`evidence`: its manifest's digest and pins); one made from a build of the working directory
    has none."""
    revs = {p["id"]: p.get("revision") for p in index.get("papers", [])}
    lean = d.get("lean") or {k: u.get(k) for k in ("fingerprint", "fingerprints", "legacy_hash")}
    return {
        "schema": REPORT_SCHEMA,
        "mode": mode,
        "unit": {"id": u["id"], "kind": u["kind"], "name": u["name"],
                 "lean": u.get("lean") if u["kind"] == "step" else u.get("lean") or [u["name"]],
                 "claims": [c["id"] for c in u["claims"]], "papers": u.get("papers") or [],
                 **({"target": u.get("unit"), "parent": u.get("parent"),
                     "route": u.get("route") or []} if u["kind"] == "step" else {})},
        "pins": {"release": index["release"],
                 "project_commit": (index.get("project") or {}).get("commit"),
                 "manuscripts": {p: revs.get(p) for p in u.get("papers") or []},
                 "legacy_hash": lean.get("legacy_hash"), "fingerprint": lean.get("fingerprint"),
                 "fingerprints": lean.get("fingerprints"),
                 "source_sha256": d.get("source_sha256")},
        "reviewer": reviewer,
        "reading": {"text": d.get("reading") or "", "locked_at": d.get("locked_at"),
                    "revealed_by": d.get("revealed_by") or [],
                    # The units whose reading was locked with this one (`lock_together`).
                    **({"locked_with": d["locked_with"]} if d.get("locked_with") else {})},
        "comparison": {"text": d["comparison"], "witness": d.get("witness") or "",
                       "checklist": d.get("checklist") or {}, "decided_at": d["decided_at"]},
        "verdict": {"group": d["group"], "value": d["verdict"], "detail": d.get("detail") or "",
                    # A structure's unit: the separate verdicts on constants it covers.
                    **({"members": d["members"]} if d.get("members") else {})},
        # Recorded with the verdict; None when the reviewer recorded no coverage.
        "correspondence": d.get("correspondence"),
        "author_review": {"shown_at": d.get("author_shown_at"), "disagreements": disagreements},
        # What the verdict means for the claim, as the build records it: a theorem named as
        # refuting the proposition (#685).
        **({"refuted_by": u["refuted_by"]} if u.get("refuted_by") else {}),
        # A judgement changed after the author's review: beside the blind verdict, never in it.
        **({"changed_judgement": changed_record(u, d["changed"])}
           if isinstance(d.get("changed"), dict) and d["changed"].get("reason") else {}),
        "submitted_at": now(),
        "issue_draft": issue_draft(u, d["verdict"], d.get("detail") or "",
                                   d.get("correspondence")),
        **({"evidence": evidence} if evidence else {}),
    }


def changed_record(u: dict, c: dict) -> dict:
    """A report's `changed_judgement`, from the draft's `changed` that `Session.submit` checked:
    the reason, the revised verdict (`{group, value, detail}`, or None) and when it was
    recorded."""
    v = c.get("verdict")
    return {"reason": c.get("reason") or "",
            "verdict": {"group": verdict_group(u, v), "value": v, "detail": c.get("detail") or ""}
            if v else None,
            "recorded_at": c.get("recorded_at")}


def changed_draft(cj: dict) -> dict:
    """The draft's `changed` that gives a report's `changed_judgement` again (Undo)."""
    v = cj.get("verdict") or {}
    return {"reason": cj.get("reason") or "", "verdict": v.get("value"),
            "detail": v.get("detail") or "", "recorded_at": cj.get("recorded_at")}
