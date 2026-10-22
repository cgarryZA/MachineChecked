"""Proof steps: an equation or a passage inside a printed proof, as a target of its own.

A paper unit is a `statement` (a numbered result, a definition, a remark: what the inventory has
always held), a `proof-equation` (a displayed equation inside a proof) or a `proof-passage` (a
selected stretch of a proof). A proof step names its enclosing result (`parent`) and keeps the
exact source region it was pinned at.

A proof step carries its own correspondence and its own review, apart from its parent's:

* `lean` lists the Lean declarations that establish the step as printed, with the coverage
  relation and the evidence basis of #138 (`coverage`, `basis`); a stored `composed` coverage
  reads as `full` with basis `reviewed_composition`.
* `route` lists the Lean declarations of a different formal route used instead: they reach the
  enclosing result by another argument and do not state the step.
* A review records whether the printed step holds. In a full assessment it is a `step-review`
  marker, written by `review promote` from a report of the queue's unit `step:<claim id>`, and
  assessed with the evidence (`marker_review`); in zero configuration it is such a report, kept
  in the project's `machinechecked-reviews/` folder (`review`). Either counts for the step's
  current text only when it was made at that text's hash.

None of this is an input to an assessed status. A proof step never takes its parent's coverage,
and a scope decision (`proof-step`) is a decision about formal coverage, never a reading of the
step: a step no report covers is shown as not reviewed.
"""

from __future__ import annotations

import re
from pathlib import Path

from .review_sources import marker_safe

UNITS = ("statement", "proof-equation", "proof-passage")
COVERAGE = ("full", "partial", "changed", "related", "unresolved")
BASIS = ("direct", "reviewed_composition", "checked_bridge")
CONFIDENCE = ("high", "medium", "low")
NOTE_CHARS = 2000
TEXT_CHARS = 20000

# The verdicts of a review of a printed step, by group, as on the review page
# (`web/src/lib/review.js`), and the review state each one gives the step.
VERDICTS = {
    "holds": ["holds as printed", "holds, with a gap in the argument"],
    "problem": ["false as printed"],
    "cannot": ["cannot determine"],
}
STATE = {"holds as printed": "holds", "holds, with a gap in the argument": "gap",
         "false as printed": "false", "cannot determine": "undetermined"}


def unit_of(claim: dict, region: dict | None = None) -> str:
    """The kind of paper unit a claim is: the one it records; else, for a claim recorded by line
    whose scope says it is a proof step, a proof equation when its pinned region is a display
    environment (`region`, from the source evidence) and a proof passage otherwise; else a
    statement."""
    u = claim.get("unit")
    if u in UNITS:
        return u
    loc = claim.get("location") or ""
    if claim.get("scope") == "proof-step" and re.search(r":\d+$", loc):
        return "proof-equation" if (region or {}).get("kind") == "environment" \
            else "proof-passage"
    return "statement"


def is_step(claim: dict, region: dict | None = None) -> bool:
    return unit_of(claim, region) != "statement"


def unit_id(claim_id: str) -> str:
    """The review unit of a proof step."""
    return "step:" + claim_id


def _names(x) -> list[str]:
    return [n for n in x if isinstance(n, str) and n] if isinstance(x, list) else []


def _str(x, limit: int = NOTE_CHARS) -> str:
    return x.strip()[:limit] if isinstance(x, str) else ""


def coverage_basis(entry: dict) -> tuple[str | None, str | None]:
    """The coverage relation and the evidence basis an entry records; unknown values are none."""
    cov = entry.get("coverage")
    basis = entry.get("basis") if entry.get("basis") in BASIS else None
    if cov == "composed":
        return "full", "reviewed_composition"
    return (cov if cov in COVERAGE else None), basis


def lean_names(entry: dict) -> list[str]:
    """The declarations an entry says establish the step."""
    return _names(entry.get("lean"))


def route_names(entry: dict) -> list[str]:
    """The declarations of the different formal route an entry records."""
    r = entry.get("route")
    return _names(r.get("lean")) if isinstance(r, dict) else []


def correspondence(entry: dict, source: str) -> dict | None:
    """The mapper's reading of how far the linked declarations state the step."""
    note = _str(entry.get("note"))
    cov, basis = coverage_basis(entry)
    if not (note or cov) or not lean_names(entry):
        return None
    return {"source": source, "coverage": cov, "basis": basis,
            "confidence": entry.get("confidence") if entry.get("confidence") in CONFIDENCE
            else None,
            "note": note, "by": entry["by"] if isinstance(entry.get("by"), str) else None}


def route_note(entry: dict, source: str) -> dict | None:
    r = entry.get("route")
    if not isinstance(r, dict) or not route_names(entry):
        return None
    return {"source": source, "note": _str(r.get("note")),
            "by": r["by"] if isinstance(r.get("by"), str) else None}


# -- review ----------------------------------------------------------------------------------

def report_view(r: dict, source_sha256: str | None) -> dict | None:
    """A review report of a step as the reader shows it, or None for a report whose verdict is
    not a step verdict. It is current when it pinned the step's present source text."""
    verdict = r.get("verdict") or {}
    if verdict.get("value") not in STATE:
        return None
    from .review_sources import report_digests
    pins = r.get("pins") or {}
    uid = str((r.get("unit") or {}).get("id") or "")
    pinned = (report_digests(r) or {}).get(uid[len("step:"):]) if uid.startswith("step:") \
        else (pins.get("fingerprints") or {}).get("source")
    rv = r.get("reviewer") or {}
    return {"reviewer": {k: rv.get(k) for k in ("id", "kind", "name", "model", "identity",
                                                 "same_family_as_author")},
            "verdict": {"group": verdict.get("group"), "value": verdict["value"],
                        "detail": _str(verdict.get("detail"), TEXT_CHARS)},
            "state": STATE[verdict["value"]],
            "reading": _str((r.get("reading") or {}).get("text"), TEXT_CHARS),
            "comparison": _str((r.get("comparison") or {}).get("text"), TEXT_CHARS),
            "locked_at": (r.get("reading") or {}).get("locked_at"),
            "submitted_at": r.get("submitted_at"),
            "source_sha256": pinned if isinstance(pinned, str) else None,
            "release": pins.get("release"), "project_commit": pins.get("project_commit"),
            "current": bool(source_sha256) and pinned == source_sha256}


MARK = {v: k for k, v in STATE.items()}


def marker_review(marks: list, claim_id: str, source_sha256: str | None,
                  authors=frozenset()) -> dict:
    """The review of a printed step from its `step-review` markers (`reviews.Review`, in file
    order): the last marker is its record; it is the finding while it read the step's current
    passage (`review_sources.marker_state`, the rule of every review marker), and `stale`
    otherwise."""
    from .review_sources import marker_state
    views = []
    for m in marks:
        if m.verdict not in MARK:
            continue
        views.append({"reviewer": {"id": m.by, "kind": m.kind, "identity": m.provenance,
                                   "author": m.by in authors},
                      "verdict": {"value": MARK[m.verdict], "detail": ""},
                      "state": m.verdict, "text": m.text[:TEXT_CHARS], "file": m.file,
                      "line": m.line, "source_sha256": (m.source or {}).get(claim_id),
                      "current": bool(source_sha256) and
                      marker_state(m, claim_id, source_sha256) == "current"})
    if not views:
        return {"state": "unreviewed", "finding": None, "reports": []}
    last = views[-1]
    return {"state": last["state"] if last["current"] else "stale",
            "finding": last if last["current"] else None, "reports": views}


def review(reports: list[dict], source_sha256: str | None) -> dict:
    """The review of a printed step: `unreviewed` when no report covers it, the latest current
    report's finding otherwise, `stale` when every report was made on other source text."""
    views = [v for v in (report_view(r, source_sha256) for r in reports or []) if v]
    views.sort(key=lambda v: str(v.get("submitted_at") or ""))
    current = [v for v in views if v["current"]]
    if current:
        state, finding = current[-1]["state"], current[-1]
    else:
        state, finding = ("stale" if views else "unreviewed"), None
    return {"state": state, "finding": finding, "reports": views}


# -- the step block of a claim record ---------------------------------------------------------

def parent_ref(parent: dict | None) -> dict | None:
    if not parent:
        return None
    return {k: parent.get(k) for k in ("id", "number", "heading", "title", "file")}


def block(claim: dict, parent: dict | None, links: list[dict], route: list[dict],
          corr: dict | None, rnote: dict | None, reviewed: dict,
          unit: str | None = None) -> dict:
    """What a claim record says about a proof step: its kind, its parent, the Lean that
    establishes it, the formal route used instead, and its own review."""
    return {"unit": unit or unit_of(claim), "parent": parent_ref(parent),
            "source": {"location": claim.get("location"),
                       "region": claim.get("source_region"),
                       "sha256": claim.get("source_sha256")},
            "links": links, "correspondence": corr,
            "route": {"links": route, "note": (rnote or {}).get("note", ""),
                      "by": (rnote or {}).get("by"), "source": (rnote or {}).get("source")}
            if route else None,
            "review": reviewed}


def attach_parents(index_claims: list[dict], chunks: dict) -> None:
    """List each proof step in its parent's record (`steps`), in the order of the paper, and
    give every index row its unit kind and parent."""
    by_id = {c["id"]: c for c in index_claims}
    for c in index_claims:
        ch = chunks[c["file"]]
        ch.setdefault("steps", [])
        c.setdefault("unit", ch.get("unit") or "statement")
        c.setdefault("parent", ch.get("parent"))
    for c in index_claims:
        ch = chunks[c["file"]]
        if c["unit"] == "statement":
            continue
        st = ch.get("step") or {}
        c["step_review"] = (st.get("review") or {}).get("state", "unreviewed")
        par = by_id.get(ch.get("parent") or "")
        if not par:
            continue
        chunks[par["file"]]["steps"].append({
            "id": c["id"], "number": c.get("number"), "unit": c["unit"], "file": c["file"],
            **{k: c[k] for k in ("status_code", "status", "class")},
            "review": (st.get("review") or {}).get("state", "unreviewed"),
            "linked": [l["name"] for l in st.get("links") or []],
            "route": [l["name"] for l in (st.get("route") or {}).get("links") or []]})


def unit_counts(index_claims: list[dict]) -> dict[str, dict[str, dict[str, int]]]:
    """Per paper and per unit kind, how many claims have each status: statements and proof
    steps are counted apart."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for c in index_claims:
        row = out.setdefault(c["paper"], {}).setdefault(c.get("unit") or "statement", {})
        row[c["status"]] = row.get(c["status"], 0) + 1
    return out


# -- finding proof steps in a LaTeX source (zero configuration) -------------------------------

DISPLAY = re.compile(r"\\begin\{(equation|align|gather|multline|eqnarray|flalign|alignat)\}")
PROOF = re.compile(r"\\(begin|end)\{proof\}")
LABEL = re.compile(r"\\label\{([^}]*)\}")
REF = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref)\{([^}]*)\}")
CONTEXT_LINES = 40


def _uncomment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def aux_numbers(aux_text: str) -> dict[str, str]:
    """The printed number of each label, from a LaTeX `.aux` file."""
    out = {}
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{([^{}]*)\}", aux_text):
        out.setdefault(m.group(1), m.group(2))
    return out


def find_proof_equations(lines: list[str], file: str, numbers: dict[str, str]) -> list[dict]:
    """The numbered, labelled displays inside the proofs of one source file: each with its
    label, printed number, opening line, the line its proof opens on, and the label the proof's
    optional argument refers to (`\\begin{proof}[Proof of Theorem~\\ref{thm:x}]`). A display
    with several labels, or whose label has no number, is left out: it has no single identity."""
    out, proof, ref = [], None, None
    i = 0
    while i < len(lines):
        text = _uncomment(lines[i])
        for m in PROOF.finditer(text):
            if m.group(1) == "begin":
                proof = i + 1
                rm = REF.search(text[m.end():])
                ref = rm.group(1) if rm and text[m.end():].lstrip().startswith("[") else None
            else:
                proof, ref = None, None
        d = DISPLAY.search(text)
        if proof is not None and d:
            end = re.compile(r"\\end\{" + d.group(1) + r"\}")
            j, labels = i, []
            while j < len(lines):
                body = _uncomment(lines[j])
                labels += LABEL.findall(body[d.end():] if j == i else body)
                if end.search(body[d.end():] if j == i else body):
                    break
                j += 1
            if len(labels) == 1 and labels[0] in numbers:
                out.append({"label": labels[0], "number": numbers[labels[0]], "file": file,
                            "line": i + 1, "end_line": j + 1, "proof_line": proof,
                            "proof_ref": ref})
            i = j + 1
            continue
        i += 1
    return out


def context_lines(lines: list[str], step: dict) -> str:
    """The proof up to the step and the sentence after it: what fixes the step's quantities and
    how it is used (at most `CONTEXT_LINES` lines before it). Shown with the step; it is not
    part of the step's pinned source."""
    start = max(step["proof_line"], step["line"] - CONTEXT_LINES)
    k = step["end_line"]
    while k < len(lines) and k - step["end_line"] < 3:
        text = _uncomment(lines[k])
        if not text.strip() or PROOF.search(text) or DISPLAY.search(text):
            break
        k += 1
        if re.search(r"[.;]\s*$", text):
            break
    return "\n".join(lines[start - 1:k])


def step_claims(pid: str, statements: list[dict], snap: Path, files: list[str],
                numbers: dict[str, str]) -> list[dict]:
    """The proof equations of the source as claims (`unit: proof-equation`), each under the
    statement whose proof holds it: the one the proof names, else the last statement of the same
    file opening before the proof. A step with no such statement is left out."""
    from .source_regions import RegionError, extract
    out = []
    for f in files:
        try:
            lines = (snap / f).read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        mine = sorted((c for c in statements if c.get("location") == f and c.get("line")),
                      key=lambda c: c["line"])
        for st in find_proof_equations(lines, f, numbers):
            parent = next((c for c in statements if st["proof_ref"]
                           and c.get("label") == st["proof_ref"]), None)
            if parent is None:
                before = [c for c in mine if c["line"] < st["proof_line"]]
                parent = before[-1] if before else None
            if parent is None:
                continue
            claim = {"location": f"{f}:{st['line']}"}
            try:
                region = extract(snap, claim).record()
            except (RegionError, OSError, UnicodeError):
                continue
            key = marker_safe(st["label"])
            out.append({
                "id": f"{pid}:{key}", "key": key, "paper": pid, "kind": "equation",
                "number": f"Equation ({st['number']})", "title": "", "label": st["label"],
                "location": claim["location"], "line": st["line"],
                "source_sha256": region["sha256"], "source_hash_scheme": region["scheme"],
                "source_region": {"end_line": region["end_line"]},
                "scope": "proof-step", "scope_note": f"a step of the proof of {parent['number']}",
                "scope_reviewed": True, "clauses": [], "tags": [],
                "unit": "proof-equation", "parent": parent["id"],
                "statement_tex": "\n".join(lines[st["line"] - 1:st["end_line"]]),
                "context_tex": context_lines(lines, st)})
    return out


# -- the full assessment ----------------------------------------------------------------------

def full_block(claim: dict, parent: dict | None, lean: dict, reviewed: dict | None,
               unit: str) -> tuple[dict, set[str]]:
    """The step block of an inventory claim, from the probe's link records, and the names of
    the declarations its links' statements use (for the claim's declaration map)."""
    from .simple import _link_view, link_state
    recs = (lean or {}).get("links") or {}
    names: set[str] = set()

    def view(n: str) -> dict:
        if not lean:
            return _link_view({"name": n, **_fields("link.unbuilt"), "source": "inventory"})
        rec = recs.get(n)
        if rec is not None and "missing" in rec.get("errors", []):
            rec = None
        names.update((rec or {}).get("closure", []))
        state = link_state(rec) if n in recs else _fields("link.missing")
        return _link_view({"name": n, **state, "source": "inventory", "record": rec})

    links = [view(n) for n in lean_names(claim)]
    route = [view(n) for n in route_names(claim)]
    return block(claim, parent, links, route, correspondence(claim, "inventory"),
                 route_note(claim, "inventory"),
                 reviewed or {"state": "unreviewed", "finding": None, "reports": []}, unit), names


def step_texts(inv: dict, paper: str, root: Path, regions: dict) -> dict[str, dict]:
    """For each proof step of `paper` in the inventory: the text of its pinned region, and its
    context in the proof (`context_lines`: from the proof's opening, at most `CONTEXT_LINES`
    lines before it, to the sentence after it). Read from the snapshot the source evidence was
    computed on."""
    from .source_regions import RegionError, extract
    out = {}
    for c in inv["claims"]:
        reg = regions.get(c["id"]) or {}
        if c["paper"] != paper or not is_step(c, reg) or reg.get("error"):
            continue
        try:
            text = extract(root, c).text
            lines = (root / reg["file"]).read_text(encoding="utf-8").split("\n")
        except (RegionError, OSError, UnicodeError, KeyError):
            continue
        start, end = reg["start_line"], reg["end_line"]
        proof = next((i + 1 for i in range(start - 1, -1, -1)
                      if PROOF.search(_uncomment(lines[i]))
                      and "begin" in PROOF.search(_uncomment(lines[i])).group(1)), start)
        out[c["id"]] = {"text": text[:TEXT_CHARS], "context": context_lines(
            lines, {"proof_line": proof, "line": start, "end_line": end})[:TEXT_CHARS]}
    return out


def _fields(code: str) -> dict:
    from .status import fields
    return fields(code)
