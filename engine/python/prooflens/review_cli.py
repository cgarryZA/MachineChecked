"""The review protocol from the command line (`machinechecked review next|read|lock|show|decide|
author|submit|status|export`), with the step locks of the reader's review page.

A reviewer takes a unit of the review queue through three steps: read the paper and lock a
reading; then see the Lean and record a verdict; then see the author's review and record any
disagreement. Each step refuses to run before the one it follows, and each is timestamped, so
the report is in exactly the form the reader exports and `review promote` checks. The work is
kept in `<work dir>/review-work/<reviewer>.json`; `export` writes the reports as one file.

As on the page, the order is what this program recorded: it cannot show that the reviewer did
not read the Lean elsewhere. What other units had already shown a unit's material to this
reviewer is recorded in the report (`reading.revealed_by`).
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from .config import Config
from .review_queue import _text

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
    """One reviewer's work on the current release's queue."""

    def __init__(self, cfg: Config, reviewer: dict):
        self.data = cfg.out_dir / "site" / "data"
        if not (self.data / "review-queue.json").exists():
            raise ReviewError("no review queue: run `machinechecked build` first")
        self.index = json.loads((self.data / "index.json").read_text(encoding="utf-8"))
        self.queue = json.loads((self.data / "review-queue.json").read_text(encoding="utf-8"))
        self.units = {u["id"]: u for u in self.queue["units"]}
        self.reviewer = reviewer
        slug = re.sub(r"[^\w.-]+", "_", reviewer["id"])
        self.path = cfg.out_dir / "review-work" / f"{slug}.json"
        self.work = (json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists()
                     else {"reviewer": reviewer, "drafts": {}, "reports": []})

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.work, indent=1, ensure_ascii=False), encoding="utf-8")

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
        for i, lean, author in passed:
            r = (self.units.get(i) or {}).get("reveals") or {}
            if i == u["id"]:
                continue
            for what, ok, key in (("Lean", lean, "lean"), ("author's review", author, "author")):
                if ok and u["id"] in r.get(key, []) and {"unit": i, "what": what} not in out:
                    out.append({"unit": i, "what": what})
        return out

    # -- what each step shows --------------------------------------------------------------

    def claim(self, cid: str) -> dict | None:
        meta = next((c for c in self.index["claims"] if c["id"] == cid), None)
        p = meta and self.data / "claims" / meta["file"]
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None

    def decl(self, key: str | None) -> dict | None:
        p = key and self.data / "decls" / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None

    def paper_text(self, u: dict) -> str:
        """Step 1: the paper's statements only."""
        out = []
        for c in u["claims"][:6]:
            ch = self.claim(c["id"])
            if not ch:
                continue
            head = ch.get("number") or ch["id"]
            if ch.get("heading"):
                head += f" ({ch['heading']})"
            out.append(f"{head}  [{ch['id']}]\n{ch.get('statement_tex') or '(the printed text is not part of this site)'}")
        if u["kind"] == "def":
            out.insert(0, f"A definition used by {len(u['claims'])} claim(s): "
                          + ", ".join(c["id"] for c in u["claims"][:12]))
        if u["kind"] == "step":
            ch = self.claim(u["claims"][0]["id"]) or {}
            par = (ch.get("step") or {}).get("parent") or {}
            out.insert(0, f"A step of the proof of {par.get('number') or par.get('id') or 'a result'}"
                          f" ({par.get('id') or 'no parent recorded'}). Is it valid as printed?")
            if ch.get("context_tex"):
                out.append("Its context in the proof:\n" + ch["context_tex"])
        return "\n\n".join(out)

    def lean_text(self, u: dict) -> str:
        """Step 2: the Lean of the unit, with what it uses."""
        if u["kind"] == "def":
            return self._decl_text(u["name"], self.decl(u.get("key")))
        if u["kind"] == "step":
            return self._step_text(u)
        lines = []
        for c in u["claims"]:
            ch = self.claim(c["id"])
            cl = next((x for x in (ch or {}).get("clauses", []) if x.get("spec") == u["name"]), None)
            if not cl:
                continue
            st = cl["statement"]
            lines.append(u["name"])
            for b in st.get("binders") or []:
                role = {"forall": "for all", "exists": "there is", "hypothesis": "assume",
                        "instance": "instance"}.get(b["role"], b["role"])
                lines.append(f"  {role:9} {b['name']} : {_text(b['type'])}")
            lines.append(f"  {'then' if st.get('binders') else '':9} {_text(st.get('conclusion'))}")
            if u.get("witness"):
                lines.append(f"\nWitness: {u['witness']}")
            for n in st.get("closure") or []:
                lines.append("\n" + self._decl_text(n, self.decl((ch.get("decls") or {}).get(n))))
            break
        return "\n".join(lines) or "(the statement is not in this release)"

    def _step_text(self, u: dict) -> str:
        """Step 2 of a proof step: the Lean linked as establishing it and the formal route
        used instead, if any."""
        st = (self.claim(u["claims"][0]["id"]) or {}).get("step") or {}
        out = []
        for title, links in (("Lean linked as establishing this step", st.get("links") or []),
                             ("The different formal route used instead",
                              (st.get("route") or {}).get("links") or [])):
            if not links:
                continue
            out.append(title + ":")
            for l in links:
                stmt = l.get("statement") or {}
                out.append(f"  {l['name']}  ({l.get('status')})")
                for b in stmt.get("binders") or []:
                    out.append(f"    {b['role']:10} {b['name']} : {_text(b['type'])}")
                if stmt.get("conclusion") is not None:
                    out.append(f"    {'then':10} {_text(stmt.get('conclusion'))}")
            if (st.get("route") or {}).get("note") and links is (st.get("route") or {}).get("links"):
                out.append("  Note: " + st["route"]["note"])
        return "\n".join(out) or "No Lean is linked to this step: assess the printed step itself."

    @staticmethod
    def _decl_text(name: str, d: dict | None) -> str:
        if d is None:
            return f"{name}: (not in this release)"
        out = [f"{name}  ({d.get('kind')})", f"  type : {_text(d.get('signature'))}"]
        if d.get("value"):
            out.append(f"  value: {_text(d.get('value'))}")
        return "\n".join(out)

    # -- the steps -------------------------------------------------------------------------

    def read(self, uid: str) -> str:
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
        return self.paper_text(u) + warn

    def lock(self, uid: str, reading: str) -> None:
        u = self.unit(uid)
        d = self.draft(u, "read")
        if len(reading.strip()) < 20:
            raise ReviewError("the reading is too short to record (20 characters at least)")
        d.update(reading=reading, revealed_by=self.revealed_by(u), locked_at=now(), stage="compare")
        self.save()

    def show(self, uid: str) -> str:
        u = self.unit(uid)
        d = self.draft(u)
        if d is None or d["stage"] == "read":
            raise ReviewError(f"{uid}: lock your reading first (`review lock`); the Lean is shown "
                              "only after it")
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

    def author(self, uid: str) -> str:
        u = self.unit(uid)
        d = self.draft(u, "author")
        d.setdefault("author_shown_at", now())
        self.save()
        revs = u.get("author_review") or []
        if not revs:
            return "No review by the author is recorded for this unit."
        return "\n\n".join(f"{r.get('by')} · {r.get('file')}:{r.get('line')}\n"
                           + (r.get("text") or "No text was written with this review marker.")
                           for r in revs)

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


def issue_draft(u: dict, verdict: str, detail: str) -> dict | None:
    if u.get("kind") == "step":
        return step_issue_draft(u, verdict, detail)
    if verdict == "faithful":
        return None
    note = verdict in ("faithful with representation choices", "broader")
    claims = ", ".join(c.get("number") or c["id"] for c in u["claims"])
    return {"kind": "explanatory note" if note else "defect",
            "title": f"{u['name']}: {verdict}" + (f" ({claims})" if claims else ""),
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
                 "fingerprints": u.get("fingerprints")},
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
