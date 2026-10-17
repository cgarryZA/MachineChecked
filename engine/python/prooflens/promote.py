"""Promotion of review reports: from a reviewer's report to the project's review markers.

A report (exported from the review queue) records what a reviewer read, compared and decided.
Promotion is the maintainer's step. It refuses a report that does not apply to the project as
it now is, or that the acceptance rules cannot count as an independent review:

* the evidence must be current (the Lean inputs unchanged since the last build);
* the unit's fingerprints (and the 32-digit legacy hash the markers record) and the manuscript
  revisions must be those the report was made at;
* the verdict must be faithful, faithful with representation choices (listed), or broader (with
  the instantiation that gives the printed claim);
* the reading must have been locked before the verdict, and the verdict recorded before the
  author's review was shown;
* the reviewer must not be an author of the statements, and a model of the same family as the
  author (or of unknown family) is refused unless the maintainer accepts it explicitly;
* the reading must have been blind: a report whose unit's Lean or author's review the reviewer
  had already seen while reviewing another unit (`reading.revealed_by`) is refused unless the
  maintainer accepts it explicitly. The page records this from the work kept in the reviewer's
  browser; it cannot see what they read elsewhere.

For each report it accepts, it archives the report (JSON and the protocol's text block) and
writes `<!-- spec-review: NAME HASH by=REVIEWER -->` (or `def-review`) after the declaration's
last marker, in the exact form the acceptance checker reads, then assesses the stored evidence
again. A promoted marker records the reviewer the report names; who they are is as the report
states it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import evidence as ev
from .config import Config
from .reviews import history, load_reviews, review_files
from .util import read_json

ACCEPTABLE = {"faithful", "faithful with representation choices", "broader"}
NEEDS_DETAIL = {"faithful with representation choices", "broader"}
HEX32 = re.compile(r"^[0-9a-f]{32}$")


class PromoteError(RuntimeError):
    pass


def latest_record(cfg: Config) -> dict:
    rels = sorted((cfg.out_dir / "releases").glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not rels:
        raise PromoteError("no release: run `prooflens build` first")
    return ev.load(cfg.out_dir, read_json(rels[-1])["evidence"])


def load_reports(paths: list[Path]) -> list[dict]:
    out = []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        out += d["reports"] if "reports" in d else [d]
    return out


def check_report(r: dict, body: dict, cfg: Config, accept_same_family: bool,
                 allow_revealed: bool = False) -> list[str]:
    """Why `r` cannot be promoted against the evidence `body` (empty if it can)."""
    why = []
    if r.get("schema") != "prooflens/review-report@1":
        return [f"not a review report (schema {r.get('schema')!r})"]
    u, pins, rev = r["unit"], r["pins"], r["reviewer"]
    lean = body.get("lean") or {}
    if u["kind"] == "spec":
        cur = lean.get("specs", {}).get(u["name"])
    elif u["kind"] == "def":
        cur = lean.get("decls", {}).get(u["name"])
    else:
        return [f"a {u['kind']} unit has no review marker in this project"]
    if cur is None:
        return [f"{u['name']} is not in the current evidence"]
    if pins.get("fingerprint") != cur.get("fingerprint"):
        why.append("the declaration changed since the review (fingerprint differs)")
    if pins.get("legacy_hash") != cur.get("legacy_hash") or not HEX32.match(
            cur.get("legacy_hash") or ""):
        why.append("the legacy hash differs from the current one")
    papers = body["provenance"]["papers"]
    for pid, revn in (pins.get("manuscripts") or {}).items():
        if pid in papers and papers[pid].get("revision") != revn:
            why.append(f"paper {pid} is at another revision than the one reviewed")
    v = r["verdict"]["value"]
    if v not in ACCEPTABLE:
        why.append(f"verdict {v!r} is not one that is recorded as a review")
    elif v in NEEDS_DETAIL and not r["verdict"].get("detail", "").strip():
        why.append(f"verdict {v!r} needs its detail (representation choices or instantiation)")
    if not r["reading"].get("text", "").strip():
        why.append("the report has no reading of the paper")
    t = [r["reading"].get("locked_at"), r["comparison"].get("decided_at"),
         r["author_review"].get("shown_at"), r.get("submitted_at")]
    if None in t or t != sorted(t):
        why.append("the steps are not recorded in order (reading, verdict, author's review)")
    rid = rev.get("id", "")
    if not rid or rid in cfg.statement_authors or rev.get("name") in cfg.statement_authors:
        why.append(f"reviewer {rid!r} is an author of the statements, or unnamed")
    if rev.get("kind") == "model" and rev.get("same_family_as_author") != "no" \
            and not accept_same_family:
        why.append("a model reviewer of the same family as the author, or of unknown family "
                   "(pass --accept-same-family to accept it)")
    seen = r["reading"].get("revealed_by") or []
    if seen and not allow_revealed:
        what = ", ".join(f"{s.get('what')} of it in {s.get('unit')}" for s in seen)
        why.append(f"the reading was not blind: the reviewer had seen the {what} "
                   "(pass --allow-revealed to accept it)")
    if not re.fullmatch(r"\S+", rid):
        why.append(f"reviewer id {rid!r} has spaces")
    return why


def marker(r: dict, cur: dict) -> str:
    return (f"<!-- {r['unit']['kind']}-review: {r['unit']['name']} {cur['legacy_hash']} "
            f"by={r['reviewer']['id']} -->")


def report_text(r: dict, cur: dict) -> str:
    """The report as the protocol's text block."""
    u, p, rv = r["unit"], r["pins"], r["reviewer"]
    ms = "; ".join(f"{k} {v}" for k, v in (p.get("manuscripts") or {}).items()) or "—"
    return "\n".join([
        f"### {', '.join(u['claims']) or u['id']}: {u['name']}",
        f"Pins: manuscript {ms}; project {p.get('project_commit')}; "
        f"hash {cur['legacy_hash']} ({p.get('fingerprint')})",
        f"Reviewer: {rv['id']} ({rv['kind']}{', ' + rv['model'] if rv.get('model') else ''}, "
        f"self-declared); {r['submitted_at']}; same model family as the author: "
        f"{rv.get('same_family_as_author')}",
        f"Phase 1 specification (locked {r['reading']['locked_at']}):", r["reading"]["text"],
        f"Comparison (verdict recorded {r['comparison']['decided_at']}):",
        r["comparison"]["text"],
        f"Witness: {r['comparison'].get('witness') or '—'}",
        f"Verdict: {r['verdict']['value']}"
        + (f" — {r['verdict']['detail']}" if r['verdict'].get('detail') else ""),
        f"Disagreements with the author's review (shown {r['author_review']['shown_at']}): "
        f"{r['author_review'].get('disagreements') or 'none'}", ""])


def target_file(cfg: Config, r: dict, reviews) -> tuple[Path, int | None]:
    """Where the marker goes: after the declaration's last marker, else at the end of the
    paper's review file (specs) or of the definitions' review file."""
    u = r["unit"]
    hist = history(reviews, u["kind"], u["name"])
    if hist:
        return (cfg.root / hist[-1].file).resolve(), hist[-1].line
    files = review_files(cfg.reviews)
    if not files:
        raise PromoteError("the configuration names no review file")
    want = "definitions.md" if u["kind"] == "def" else f"{(u.get('papers') or ['?'])[0]}.md"
    return next((f for f in files if f.name == want), files[-1]), None


def insert_after(path: Path, line: int | None, lines: list[str]):
    txt = path.read_text(encoding="utf-8").split("\n")
    if line is None:
        while txt and not txt[-1].strip():
            txt.pop()
        txt += [""] + lines + [""]
    else:
        indent = re.match(r"\s*", txt[line - 1]).group(0)
        txt[line:line] = [indent + l for l in lines]
    path.write_text("\n".join(txt), encoding="utf-8")


def reports_dir(cfg: Config) -> Path:
    first = next((p for p in cfg.reviews if p.is_dir()), cfg.reviews[0].parent if cfg.reviews
                 else cfg.root)
    return first / "reports"


def plan(cfg: Config, reports: list[dict], accept_same_family: bool = False,
         allow_revealed: bool = False):
    """For each report: (report, current record, reasons it is refused)."""
    body = latest_record(cfg)["body"]
    from .pipeline import lean_inputs_digest
    if body["provenance"].get("lean_inputs_sha256") != lean_inputs_digest(cfg):
        raise PromoteError("the Lean project changed since the last build: run `prooflens build` "
                           "first, so the reports are checked against the current declarations")
    lean = body.get("lean") or {}
    out = []
    for r in reports:
        u = r.get("unit", {})
        cur = (lean.get("specs" if u.get("kind") == "spec" else "decls", {}) or {}).get(
            u.get("name"))
        out.append((r, cur, check_report(r, body, cfg, accept_same_family, allow_revealed)))
    return out


def apply(cfg: Config, accepted: list[tuple[dict, dict]]) -> list[dict]:
    """Archive each report and write its marker."""
    reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    rdir = reports_dir(cfg)
    rdir.mkdir(parents=True, exist_ok=True)
    done = []
    for r, cur in accepted:
        stem = re.sub(r"[^\w.-]+", "_", f"{r['unit']['name']}--{r['reviewer']['id']}--"
                      f"{r['submitted_at']}")
        (rdir / f"{stem}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        (rdir / f"{stem}.md").write_text(report_text(r, cur), encoding="utf-8")
        path, line = target_file(cfg, r, reviews)
        rel = Path(rdir / f"{stem}.md").resolve()
        try:
            rel = rel.relative_to(path.parent.resolve())
        except ValueError:
            pass
        mk = marker(r, cur)
        insert_after(path, line, [f"Review by {r['reviewer']['id']}: {r['verdict']['value']} "
                                  f"(report `{rel.as_posix()}`).", mk])
        reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
        done.append({"name": r["unit"]["name"], "file": str(path), "marker": mk})
    return done
