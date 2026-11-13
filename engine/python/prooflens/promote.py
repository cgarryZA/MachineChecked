"""Promotion of review reports: from a reviewer's report to the project's review markers.

A report (exported from the review queue) records what a reviewer read, compared and decided.
Promotion is the maintainer's step. It refuses a report that does not apply to the project as
it now is, or that the acceptance rules cannot count as an independent review:

* the evidence must be current (the Lean inputs unchanged since the last build);
* the unit's fingerprints (and the 32-digit legacy hash the markers record), the manuscript
  revisions and the digests of the paper passages read (`review_sources.py`) must be those the
  report was made at, and the manuscript must still match the pin of each passage read;
* the verdict must be faithful, faithful with representation choices (listed), or broader (with
  the instantiation that gives the printed claim);
* the reviewer's coverage, when the report records one (`correspondence`), must be one the
  review protocol writes, and not unresolved: an open question records neither a review nor a
  defect. A report without one is promoted as before;
* the reading must have been locked before the verdict, and the verdict recorded before the
  author's review was shown;
* the reviewer must not be an author of the statements, and a model of the same family as the
  author (or of unknown family) is refused unless the maintainer accepts it explicitly;
* the reading must have been blind: a report whose unit's Lean or author's review the reviewer
  had already seen while reviewing another unit (`reading.revealed_by`) is refused unless the
  maintainer accepts it explicitly. The review page and the command line record this from the
  reviewer's work (their workspaces, or a static copy's browser); neither can see what they read
  elsewhere.

A report on a proof step (unit `step:<claim id>`) is checked the same way, against the step's
source text instead of a declaration: the step's pinned source hash must be the one the report
was made at, and match the manuscript; its verdict must be holds as printed, holds with a gap
(with the argument), or false as printed (with the failing case). Its marker is
`<!-- step-review: CLAIM SOURCE-SHA256 verdict=holds|gap|false by=REVIEWER -->`.

For each report it accepts, it archives the report as one record (`reports/<stem>.json` beside
the review files: the report as exported, which holds every pin the marker binds) and writes
a line ``Review by REVIEWER: VERDICT (report `reports/<stem>.json`).`` and
`<!-- spec-review: NAME HASH by=REVIEWER source=CLAIM@DIGEST... -->` (or `def-review`,
`step-review`; no `source` when no claim's passage is read) after the declaration's (or step's)
last marker, in the exact form the acceptance checker reads, then assesses the stored evidence
again. A promoted marker records the reviewer the report names; who they are is as the report
states it.

A report on a structure's unit is one reading and one verdict for the structure and the
constants Lean generates for it that the unit lists (`unit.lean`: its constructor and
projections). Each must still be one of those, at the fingerprint the report pinned for it. The
report is archived once, as one record, and a `def-review` marker is written for each of them,
each after its own `Review by` line linking that record, so that the acceptance checker, which
reads one marker per declaration, finds each reviewed. A separate verdict on one of them
(`verdict.members`) that is not one recorded as a review leaves that one without a marker.

The protocol's text block of an archived report is not kept: `write_texts` (`review reports`)
writes it from the record, into the output directory. A line that version 0.1.25 or earlier
wrote links the block it kept beside the record, `reports/<stem>.md`; its record is the one of
the same stem, and the block can be deleted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import evidence as ev
from . import review_sources
from .config import Config
from .reviews import history, load_reviews, review_files

ACCEPTABLE = {"faithful", "faithful with representation choices", "broader",
              "faithful to the correction"}
NEEDS_DETAIL = {"faithful with representation choices", "broader"}
# A review of a printed step records a finding; an open question is not one.
STEP_ACCEPTABLE = {"holds as printed", "holds, with a gap in the argument", "false as printed"}
STEP_NEEDS_DETAIL = {"holds, with a gap in the argument", "false as printed"}
HEX32 = re.compile(r"^[0-9a-f]{32}$")


class PromoteError(RuntimeError):
    pass


def latest_record(cfg: Config) -> dict:
    """The evidence record of the latest release (`evidence.latest`), which every command that
    reads the latest release reads."""
    last = ev.latest(cfg.out_dir)
    if last is None:
        raise PromoteError("no release: run `machinechecked build` first")
    return ev.load(cfg.out_dir, last["evidence"])


def load_reports(paths: list[Path]) -> list[dict]:
    """The reports in the given files; a directory stands for the `*.json` files directly in
    it, in name order."""
    files = []
    for p in map(Path, paths):
        if p.is_dir():
            found = sorted(f for f in p.glob("*.json") if f.is_file())
            if not found:
                raise PromoteError(f"{p} is a directory with no report files (*.json) in it")
            files += found
        elif not p.is_file():
            raise PromoteError(f"{p}: no such report file")
        else:
            files.append(p)
    out = []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise PromoteError(f"{p} is not a report file exported from the review queue "
                               f"(not JSON: {e})") from e
        out += d["reports"] if isinstance(d, dict) and "reports" in d else [d]
    return out


def check_report(r: dict, body: dict, cfg: Config, accept_same_family: bool,
                 allow_revealed: bool = False) -> list[str]:
    """Why `r` cannot be promoted against the evidence `body` (empty if it can)."""
    why = []
    if r.get("schema") != "prooflens/review-report@1":
        return [f"not a review report (schema {r.get('schema')!r})"]
    u, pins, rev = r["unit"], r["pins"], r["reviewer"]
    lean = body.get("lean") or {}
    step = u["kind"] == "step"
    if u["kind"] == "spec":
        cur = lean.get("specs", {}).get(u["name"])
    elif u["kind"] == "def":
        cur = lean.get("decls", {}).get(u["name"])
    elif step:
        cur = step_claim(body, u)
    else:
        return [f"a {u['kind']} unit has no review marker in this project"]
    if cur is None:
        return [f"{u['name']} is not in the current evidence" if not step else
                f"{u['id']} is not a proof step of the current evidence"]
    if step:
        from .source_regions import matches
        if (pins.get("fingerprints") or {}).get("source") != cur.get("source_sha256"):
            why.append("the step's source changed since the review (source hash differs)")
        if not matches(cur, (body.get("tex") or {}).get(cur["paper"], {})):
            why.append("the step's pinned source does not match the manuscript")
    else:
        if pins.get("fingerprint") != cur.get("fingerprint"):
            why.append("the declaration changed since the review (fingerprint differs)")
        if pins.get("legacy_hash") != cur.get("legacy_hash") or not HEX32.match(
                cur.get("legacy_hash") or ""):
            why.append("the legacy hash differs from the current one")
    # The passages read: one rule for every kind of unit.
    want = expected_source(body, u, cur)
    have = report_source(r)
    if have is None and want:
        why.append("the report does not record the paper text it was made against (source "
                   "digests); review the unit again from a current build")
    elif have is not None and have != want:
        why.append("the paper's text changed since the review (source digests differ)")
    if not step:
        from .assess import unpinned_passages
        inv = {"claims": (body.get("inventory") or {}).get("claims", [])}
        unpinned = sorted(set(want) & set(unpinned_passages(inv, body.get("tex"))))
        if unpinned:
            why.append("the manuscript no longer matches the pin of " + ", ".join(unpinned)
                       + ": pin the passage again (machinechecked inventory rebound --repin, at "
                       "the paper's new revision) and review it from a new build")
    papers = body["provenance"]["papers"]
    for pid, revn in (pins.get("manuscripts") or {}).items():
        if pid in papers and papers[pid].get("revision") != revn:
            why.append(f"paper {pid} is at another revision than the one reviewed")
    v = r["verdict"]["value"]
    if v == "faithful to the correction" and not corrects_a_clause(body, u):
        why.append("verdict 'faithful to the correction' applies only to the proposition of a "
                   "clause that corrects, or is a special case of, a printed clause")
    if v == "cannot determine":
        why.append("verdict 'cannot determine' is not one that is recorded as a review: it "
                   "leaves an open question, and no defect")
    elif v not in (STEP_ACCEPTABLE if step else ACCEPTABLE):
        why.append(f"verdict {v!r} is not one that is recorded as a review")
    elif v in (STEP_NEEDS_DETAIL if step else NEEDS_DETAIL) and \
            not r["verdict"].get("detail", "").strip():
        why.append(f"verdict {v!r} needs its detail ("
                   + ("the argument or the failing case" if step else
                      "representation choices or instantiation") + ")")
    why += coverage_refusals(r)
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
    why += covers(r, body)[2]
    return why


def covers(r: dict, body: dict) -> tuple[list[str], dict, list[str]]:
    """The declarations a report's markers are written for, the constants it leaves out, and why
    its list of them cannot be promoted. A report on a structure's unit reviewed the constants
    Lean generates for it with it (`unit.lean`, after the structure: its constructor and
    projections, `review_queue.structure_members`); each must be one of those in the current
    evidence, at the fingerprint the report pinned for it (`pins.fingerprints`). One the reviewer
    gave a separate verdict on (`verdict.members`) that is not one recorded as a review is left
    out, with that verdict: it gets no marker. Any other report covers its own declaration."""
    from .review_cli import member_verdicts
    from .review_queue import structure_members
    u = r.get("unit") or {}
    sep = (r.get("verdict") or {}).get("members") or {}
    names = [n for n in u.get("lean") or [] if n != u.get("name")] \
        if u.get("kind") == "def" else []
    if not names and not sep:
        return [marker_name(r)], {}, []
    decls = (body.get("lean") or {}).get("decls") or {}
    allowed = {m["name"] for m in structure_members(u.get("name"), decls)}
    pinned = (r.get("pins") or {}).get("fingerprints") or {}
    why = []
    for n in names:
        if n not in allowed:
            why.append(f"{n} is not a constructor or projection of {u.get('name')} in the "
                       "current evidence")
            continue
        if pinned.get(n) != decls[n].get("fingerprint"):
            why.append(f"{n}, reviewed with {u.get('name')}, changed since the review "
                       "(fingerprint differs)")
        if not HEX32.match(decls[n].get("legacy_hash") or ""):
            why.append(f"the legacy hash of {n} is not one a marker records")
    apart, bad = member_verdicts({"id": u.get("id"), "members": [{"name": n} for n in names]},
                                 sep)
    why += [f"the separate verdicts: {b}" for b in bad]
    out = {n: v for n, v in apart.items() if v["value"] not in ACCEPTABLE}
    return [u.get("name")] + [n for n in names if n not in out], out, why


def corrects_a_clause(body: dict, u: dict) -> bool:
    """Whether the unit's proposition is, in the evidence `body`, that of a clause that corrects
    (`corrects`) or is a special case of (`restricts`) a printed clause."""
    return u.get("kind") == "spec" and any(
        cl.get("spec") == u.get("name") and (cl.get("corrects") or cl.get("restricts"))
        for c in (body.get("inventory") or {}).get("claims", []) for cl in c.get("clauses", []))


def coverage_refusals(r: dict) -> list[str]:
    """Why the reviewer's coverage (the report's `correspondence`, recorded with the verdict)
    keeps the report from being promoted: a record the review protocol does not write
    (`review_cli.correspondence`), or an unresolved coverage, which is an open question and records
    neither a review nor a defect. A report without one is promoted as before: its coverage is
    not recorded, and the marker is the same either way."""
    from .review_cli import correspondence
    cor = r.get("correspondence")
    if cor is None:
        return []
    if not isinstance(cor, dict):
        return ["the report's coverage is not a record the review protocol writes"]
    verdict = (r.get("verdict") or {}).get("value")
    _, problems = correspondence(r.get("unit") or {}, verdict, cor)
    why = [f"the report's coverage: {p}" for p in problems]
    if cor.get("coverage") == "unresolved" and verdict != "cannot determine":
        why.append("the reviewer left the coverage unresolved: an open question records no "
                   "review, and no defect")
    return why


def coverage_text(r: dict) -> str | None:
    """The reviewer's coverage in words, for the maintainer's plan and the archived text block;
    None when the report records none."""
    from .semantic import basis_words, in_text, reading_words
    cor = r.get("correspondence")
    if not isinstance(cor, dict) or not cor.get("coverage"):
        return None
    cov, basis = cor["coverage"], cor.get("basis")
    out = in_text(reading_words(cov)) or repr(cov)
    if basis:
        out += ", " + (in_text(basis_words(basis)) or repr(basis))
    b = cor.get("bridge") if isinstance(cor.get("bridge"), dict) else {}
    if cor.get("basis") == "checked_bridge" and b:
        out += f" ({b.get('theorem')} for {b.get('target')}, as the reviewer records it)"
    return out


def step_claim(body: dict, u: dict) -> dict | None:
    """The inventory entry of the proof step a step unit reviews, if it is one."""
    from .steps import is_step
    cid = u["id"][len("step:"):] if str(u.get("id", "")).startswith("step:") else None
    c = next((c for c in body["inventory"]["claims"] if c["id"] == cid), None)
    if c is None:
        return None
    region = ((body.get("tex") or {}).get(c["paper"], {}).get("regions") or {}).get(cid)
    return c if is_step(c, region) else None


def expected_source(body: dict, unit: dict, cur: dict | None = None) -> dict[str, str]:
    """The digests of the passages a review of `unit` reads, by claim, from the inventory of
    the evidence (which promotion checks is the current one): a step's own passage, or those of
    the claims that state the proposition or name the definition."""
    if unit.get("kind") == "step":
        return {cur["id"]: cur["source_sha256"]} if cur and cur.get("source_sha256") else {}
    inv = {"claims": (body.get("inventory") or {}).get("claims", [])}
    out = review_sources.digests(inv, unit.get("kind"), unit.get("name"), body.get("tex"))
    # A structure's unit reads the passages of every constant it covers.
    if unit.get("kind") == "def":
        for n in unit.get("lean") or []:
            if n != unit.get("name"):
                out.update(review_sources.digests(inv, "def", n, body.get("tex")))
    return out


def report_source(r: dict) -> dict[str, str] | None:
    """The digests a report pinned, by claim (`review_sources.report_digests`)."""
    return review_sources.report_digests(r)


def marker_name(r: dict) -> str:
    u = r["unit"]
    return u["id"][len("step:"):] if u["kind"] == "step" else u["name"]


def marker(r: dict, cur: dict, source: dict[str, str] | None = None) -> str:
    """The marker of a promoted report; `source` is the digests of the passages it read, by
    claim."""
    attr = review_sources.attribute(source or {})
    attr = " " + attr if attr else ""
    if r["unit"]["kind"] == "step":
        from .steps import STATE
        return (f"<!-- step-review: {marker_name(r)} {cur['source_sha256']} "
                f"verdict={STATE[r['verdict']['value']]} by={r['reviewer']['id']}{attr} -->")
    return (f"<!-- {r['unit']['kind']}-review: {r['unit']['name']} {cur['legacy_hash']} "
            f"by={r['reviewer']['id']}{attr} -->")


def markers(r: dict, cur: dict) -> list[tuple[str, str]]:
    """Each declaration a promoted report records a review of, with its marker: the unit's own
    (`marker`), or for a structure's unit one per declaration it covers (`cur["covers"]`, which
    `plan` adds), each with the digests of the passages of its own claims that the report read."""
    if not cur.get("covers"):
        return [(marker_name(r), marker(r, cur, report_source(r)))]
    out = []
    for c in cur["covers"]:
        attr = review_sources.attribute(c["source"])
        attr = " " + attr if attr else ""
        out.append((c["name"], f"<!-- def-review: {c['name']} {c['legacy_hash']} "
                               f"by={r['reviewer']['id']}{attr} -->"))
    return out


def with_covers(r: dict, cur: dict | None, body: dict) -> dict | None:
    """`cur` (the current record of a report's declaration) with, for a report on a structure's
    unit, the declarations its markers are written for (`covers`: name, legacy hash and the
    digests of the passages of its claims the report read) and those it leaves out by a separate
    verdict (`left_out`)."""
    u = r.get("unit") or {}
    if cur is None or u.get("kind") != "def":
        return cur
    names, out, _ = covers(r, body)
    if names == [u.get("name")] and not out:
        return cur
    decls = (body.get("lean") or {}).get("decls") or {}
    read = report_source(r) or {}
    inv = {"claims": (body.get("inventory") or {}).get("claims", [])}
    cov = []
    for n in names:
        rec = cur if n == u.get("name") else decls.get(n) or {}
        want = review_sources.digests(inv, "def", n, body.get("tex"))
        cov.append({"name": n, "legacy_hash": rec.get("legacy_hash"),
                    "source": {c: d for c, d in read.items() if c in want}})
    return {**cur, "covers": cov, "left_out": out}


def report_text(r: dict, cur: dict | None = None) -> str:
    """The report as the protocol's text block. The hashes it prints are the current
    declaration's or step's (`cur`); without `cur`, the report's own pins, which promotion
    checked are the current ones, so the block of an archived report is the one its promotion
    would print."""
    u, p, rv = r["unit"], r["pins"], r["reviewer"]
    cur = cur or pinned(r)
    ms = "; ".join(f"{k} {v}" for k, v in (p.get("manuscripts") or {}).items()) or "—"
    return "\n".join([
        f"### {', '.join(u['claims']) or u['id']}: {u['name']}",
        f"Pins: manuscript {ms}; project {p.get('project_commit')}; "
        + (f"source {cur['source_sha256']}" if u["kind"] == "step" else
           f"hash {cur['legacy_hash']} ({p.get('fingerprint')}); source "
           f"{review_sources.attribute(p.get('source_sha256') or {}) or '—'}"),
        f"Reviewer: {rv['id']} ({rv['kind']}{', ' + rv['model'] if rv.get('model') else ''}, "
        f"self-declared); {r['submitted_at']}; same model family as the author: "
        f"{rv.get('same_family_as_author')}",
        f"Phase 1 specification (locked {r['reading']['locked_at']}):", r["reading"]["text"],
        f"Comparison (verdict recorded {r['comparison']['decided_at']}):",
        r["comparison"]["text"],
        f"Witness: {r['comparison'].get('witness') or '—'}",
        f"Verdict: {r['verdict']['value']}"
        + (f" — {r['verdict']['detail']}" if r['verdict'].get('detail') else ""),
        *_covers_lines(r),
        *_coverage_lines(r),
        f"Disagreements with the author's review (shown {r['author_review']['shown_at']}): "
        f"{r['author_review'].get('disagreements') or 'none'}", ""])


def _covers_lines(r: dict) -> list[str]:
    """The text block's lines for a report on a structure's unit, read from the report alone:
    the declarations the review covers (`unit.lean`), and each separate verdict on one of them,
    noting those that leave it without a marker; none for any other unit."""
    u = r.get("unit") or {}
    sep = (r.get("verdict") or {}).get("members") or {}
    names = list(u.get("lean") or []) if u.get("kind") == "def" else []
    if len(names) < 2 and not sep:
        return []
    out = ["Covers: " + ", ".join(n for n in names
                                  if (sep.get(n) or {}).get("value", "faithful") in ACCEPTABLE)]
    for n, v in sorted(sep.items()):
        out.append(f"Separate verdict on {n}: {v.get('value')}"
                   + (f" — {v['detail']}" if v.get("detail") else "")
                   + (" (no marker is written for it)" if v.get("value") not in ACCEPTABLE
                      else ""))
    return out


def pinned(r: dict) -> dict:
    """The hashes a report pinned, in the form of the current record they were checked against:
    a step's source hash, a declaration's legacy hash."""
    p = r["pins"]
    return {"source_sha256": (p.get("fingerprints") or {}).get("source"),
            "legacy_hash": p.get("legacy_hash")}


def _coverage_lines(r: dict) -> list[str]:
    """The text block's lines for the reviewer's coverage: none when the report records none, so
    an older report's block is as it was."""
    head = coverage_text(r)
    if head is None:
        return []
    cor = r["correspondence"]
    return [f"Coverage (recorded with the verdict): {head}",
            *([f"Argument: {cor['argument']}"] if cor.get("argument") else []),
            *([f"Would decide it: {cor['would_decide']}"] if cor.get("would_decide") else [])]


def target_file(cfg: Config, r: dict, reviews) -> tuple[Path, int | None]:
    """Where the marker goes: after the declaration's last marker, else at the end of the
    paper's review file (specs) or of the definitions' review file."""
    u = r["unit"]
    hist = history(reviews, u["kind"], marker_name(r))
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
    """Where promoted reports are archived: `reports/` in the first review directory, else
    beside the first review file."""
    first = next((p for p in cfg.reviews if p.is_dir()), cfg.reviews[0].parent if cfg.reviews
                 else cfg.root)
    return first / "reports"


def text_dir(cfg: Config) -> Path:
    """Where `review reports` writes the archived reports as text by default: in the project's
    output directory, which is generated and not kept with the reviews."""
    return cfg.out_dir / "reports"


def write_texts(cfg: Config, out: Path | None = None) -> list[Path]:
    """Write each archived report (`reports_dir`, `<stem>.json`) as the protocol's text block,
    `<stem>.md` in `out` (default `text_dir`). The text is made from the record alone, so it can
    be deleted and written again; an archived file that is not a review report is skipped."""
    out = Path(out) if out else text_dir(cfg)
    rdir, done = reports_dir(cfg), []
    for f in sorted(rdir.glob("*.json")) if rdir.is_dir() else []:
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(r, dict) or r.get("schema") != "prooflens/review-report@1":
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{f.stem}.md").write_text(report_text(r), encoding="utf-8")
        done.append(out / f"{f.stem}.md")
    return done


def plan(cfg: Config, reports: list[dict], accept_same_family: bool = False,
         allow_revealed: bool = False):
    """For each report: (report, current record, reasons it is refused)."""
    body = latest_record(cfg)["body"]
    from .pipeline import inventory_changed, lean_inputs_digest
    # Both before anything is written: promotion reassesses at the end, and stale evidence would
    # leave markers written and the assessment not updated.
    why = inventory_changed(cfg, body)
    if why:
        raise PromoteError(why)
    if body["provenance"].get("lean_inputs_sha256") != lean_inputs_digest(cfg):
        raise PromoteError("the Lean project changed since the last build: run `machinechecked "
                           "build` first, so the reports are checked against the current "
                           "declarations")
    lean = body.get("lean") or {}
    out = []
    for r in reports:
        u = r.get("unit", {})
        cur = step_claim(body, u) if u.get("kind") == "step" else \
            (lean.get("specs" if u.get("kind") == "spec" else "decls", {}) or {}).get(
                u.get("name"))
        out.append((r, with_covers(r, cur, body),
                    check_report(r, body, cfg, accept_same_family, allow_revealed)))
    return out


def already_promoted(cfg: Config, r: dict, cur: dict) -> bool:
    """Whether the markers promoting `r` are already in the project's review files, as after a
    promotion of the same report: promoting it again would write them a second time."""
    texts = [f.read_text(encoding="utf-8") for f in review_files(cfg.reviews) if f.is_file()]
    return all(any(mk in t for t in texts) for _, mk in markers(r, cur))


def apply(cfg: Config, accepted: list[tuple[dict, dict]]) -> list[dict]:
    """Archive each report once (its one record, `<stem>.json`) and write its markers (one per
    declaration it covers, `markers`), each after a line linking the record: after that
    declaration's last marker, else after the report's previous marker, else where
    `target_file` says. A report whose markers are already written (`already_promoted`) is left
    as it is, and listed with `already` set."""
    reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    rdir = reports_dir(cfg)
    rdir.mkdir(parents=True, exist_ok=True)
    done = []
    for r, cur in accepted:
        mks = markers(r, cur)
        if already_promoted(cfg, r, cur):
            done += [{"name": n, "marker": mk, "already": True} for n, mk in mks]
            continue
        stem = re.sub(r"[^\w.-]+", "_", f"{marker_name(r)}--{r['reviewer']['id']}--"
                      f"{r['submitted_at']}")
        (rdir / f"{stem}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
        prev = None
        for n, mk in mks:
            hist = history(reviews, r["unit"]["kind"], n)
            if n == marker_name(r):
                path, line = target_file(cfg, r, reviews)
            elif hist:
                path, line = (cfg.root / hist[-1].file).resolve(), hist[-1].line
            else:
                path, line = prev
            rel = Path(rdir / f"{stem}.json").resolve()
            try:
                rel = rel.relative_to(path.parent.resolve())
            except ValueError:
                pass
            with_ = "" if n == marker_name(r) else f", with {marker_name(r)}"
            insert_after(path, line, [f"Review by {r['reviewer']['id']}: {r['verdict']['value']}"
                                      f"{with_} (report `{rel.as_posix()}`).", mk])
            reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
            last = history(reviews, r["unit"]["kind"], n)[-1]
            prev = ((cfg.root / last.file).resolve(), last.line)
            done.append({"name": n, "file": str(path), "marker": mk})
    return done
