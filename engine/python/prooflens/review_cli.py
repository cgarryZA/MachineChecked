"""The review protocol from the command line (`machinechecked review next|read|lock|show|decide|
author|submit|status|export`), with the step locks of the reader's review page.

A reviewer takes a unit of the review queue through three steps: read the paper and lock a
reading; then see the Lean and record a verdict; then see the author's review and record any
disagreement. Each step refuses to run before the one it follows, and each is timestamped, so
the report is in exactly the form the reader exports and `review promote` checks. The work is
kept in the reviewer's workspace (`workspace.py`, `<work dir>/review-work/<reviewer>.json`);
`export` writes the reports as one file.

As on the page, the order is what this program recorded: it cannot show that the reviewer did
not read the Lean elsewhere. What other units had already shown a unit's material to this
reviewer is recorded in the report (`reading.revealed_by`), and so is what the workspace
records the reviewer had seen (an informed investigation has seen the Lean of every claim).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import compare as cmp
from .simple import reading_text
from . import workspace as wsp
from .config import Config

REPORT_SCHEMA = "prooflens/review-report@1"
REPORTS_SCHEMA = "prooflens/review-reports@1"

# The verdicts of the protocol, by group, as on the review page (`web/src/lib/review.js`).
VERDICTS = {
    "matches": ["faithful", "faithful with representation choices", "broader"],
    "problem": ["narrower", "mismatched", "vacuous", "refutation not valid"],
    "cannot": ["cannot determine"],
}
REFUTE_ONLY = {"refutation not valid"}
# A proof step is reviewed as printed: does it hold? (`steps.VERDICTS`)
from .steps import VERDICTS as STEP_VERDICTS


class ReviewError(RuntimeError):
    pass


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        return any(r["unit"]["id"] == u["id"] and (r["pins"].get("fingerprint") or json.dumps(
            r["pins"].get("fingerprints") or {}, sort_keys=True)) == self._fp(u)
            for r in self.work["reports"])

    def open_units(self) -> list[dict]:
        return [u for u in self.queue["units"] if u["state"] != "reviewed" and not self.reported(u)]

    def draft(self, u: dict, stage: str | None = None) -> dict:
        d = self.work["drafts"].get(u["id"])
        if stage is not None and (d is None or d["stage"] != stage):
            have = d["stage"] if d else "not started"
            raise ReviewError(f"{u['id']} is at step '{have}'; this needs step '{stage}' "
                              f"(read → compare → author → submitted)")
        return d

    def revealed_by(self, u: dict) -> list[dict]:
        """The units this reviewer has reached step 2 or 3 of here whose material includes u's
        Lean or u's author review."""
        passed = [(r["unit"]["id"], True, True) for r in self.work["reports"]]
        passed += [(i, d["stage"] != "read", d["stage"] == "author")
                   for i, d in self.work["drafts"].items()]
        out = []
        for e in wsp.exposed(self.workspace, [c["id"] for c in u.get("claims") or []]):
            for what in e["what"]:
                what = {"prior interpretations": "author's review"}.get(what, what)
                item = {"unit": f"workspace {self.workspace['id']} ({e.get('how')})",
                        "what": what}
                if what in ("Lean", "author's review") and item not in out:
                    out.append(item)
        for i, lean, author in passed:
            r = (self.units.get(i) or {}).get("reveals") or {}
            if i == u["id"]:
                continue
            for what, ok, key in (("Lean", lean, "lean"), ("author's review", author, "author")):
                if ok and u["id"] in r.get(key, []) and {"unit": i, "what": what} not in out:
                    out.append({"unit": i, "what": what})
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
               witness: str = "") -> None:
        u = self.unit(uid)
        d = self.draft(u, "compare")
        table = STEP_VERDICTS if u["kind"] == "step" else VERDICTS
        group = next((g for g, vs in table.items() if verdict in vs), None)
        if group is None:
            raise ReviewError(f"verdict {verdict!r} is not one of: "
                              + ", ".join(v for vs in table.values() for v in vs))
        if verdict in REFUTE_ONLY and not u.get("refute"):
            raise ReviewError(f"{verdict!r} applies only to a unit with a refutation")
        if verdict not in ("faithful", "holds as printed") and not detail.strip():
            raise ReviewError(f"verdict {verdict!r} needs --detail")
        if not comparison.strip():
            raise ReviewError("the comparison is empty")
        d.update(group=group, verdict=verdict, detail=detail, comparison=comparison,
                 witness=witness, decided_at=now(), stage="author")
        self.save()

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
        r = report(self.index, u, d, self.reviewer, disagreements or "none")
        self.work["reports"].append(r)
        del self.work["drafts"][uid]
        self.save()
        return r

    def export(self, out: Path) -> Path:
        body = {"schema": REPORTS_SCHEMA, "project": (self.index.get("project") or {}).get("name"),
                "release": self.index["release"], "exported_at": now(),
                "reports": self.work["reports"]}
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
                   "paper says. This is an open question, not a difference that was found.")


def issue_draft(u: dict, verdict: str, detail: str) -> dict | None:
    """The issue a maintainer may file for a verdict, as the reader's `issueDraft` writes it."""
    if u.get("kind") == "step":
        return step_issue_draft(u, verdict, detail)
    kind = DRAFT_KIND.get(verdict)
    if kind is None:
        return None
    claims = ", ".join(c.get("number") or c["id"] for c in u["claims"])
    suffix = f" ({claims})" if claims else ""
    detail = (detail or "").strip()
    if kind == "unresolved question":
        return {"kind": kind, "title": f"{u['name']}: open question{suffix}",
                "body": f"Review unit `{u['id']}`, verdict **{verdict}**. {UNRESOLVED_BODY}"
                        + (f"\n\n**Open question.** {detail}" if detail else "")}
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
        "author_review": {"shown_at": d["author_shown_at"], "disagreements": disagreements},
        "submitted_at": now(),
        "issue_draft": issue_draft(u, d["verdict"], d.get("detail") or ""),
    }
