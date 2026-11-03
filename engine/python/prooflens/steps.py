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
    """The mapper's reading of how far the linked declarations state the step. A reading
    describes the linked declarations, so a step with none keeps only an unresolved one, whose
    open question may be whether any Lean states the step; with no Lean, it has no basis."""
    note = _str(entry.get("note"))
    cov, basis = coverage_basis(entry)
    linked = bool(lean_names(entry))
    if not (note or cov) or not (linked or cov == "unresolved"):
        return None
    return {"source": source, "coverage": cov, "basis": basis if linked else None,
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
            "route": [l["name"] for l in (st.get("route") or {}).get("links") or []],
            **({"passage": {k: st["passage"].get(k) for k in ("file", "start_line", "end_line",
                                                               "matches")}}
               if isinstance(st.get("passage"), dict) else {})})


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


def context_start(step: dict) -> int:
    """The line a step's context in the proof starts on: the proof's opening, or
    `CONTEXT_LINES` lines before the step when the proof opens earlier."""
    return max(step["proof_line"], step["line"] - CONTEXT_LINES)


def context_lines(lines: list[str], step: dict) -> str:
    """The proof up to the step and the sentence after it: what fixes the step's quantities and
    how it is used (at most `CONTEXT_LINES` lines before it). Shown with the step; it is not
    part of the step's pinned source."""
    start = context_start(step)
    k = step["end_line"]
    while k < len(lines) and k - step["end_line"] < 3:
        text = _uncomment(lines[k])
        if not text.strip() or PROOF.search(text) or DISPLAY.search(text):
            break
        k += 1
        if re.search(r"[.;]\s*$", text):
            break
    return "\n".join(lines[start - 1:k])


def proof_parent(statements: list[dict], file: str, proof_line: int,
                 ref: str | None) -> dict | None:
    """The statement whose proof opens on `proof_line` of `file`: the one the proof's optional
    argument names (`ref`, a label), else the last statement of the same file opening before the
    proof; None when there is neither."""
    if ref:
        named = next((c for c in statements if c.get("label") == ref), None)
        if named is not None:
            return named
    before = sorted((c for c in statements if c.get("location") == file and c.get("line")
                     and c["line"] < proof_line), key=lambda c: c["line"])
    return before[-1] if before else None


def step_claims(pid: str, statements: list[dict], snap: Path, files: list[str],
                numbers: dict[str, str]) -> list[dict]:
    """The proof equations of the source as claims (`unit: proof-equation`), each under the
    statement whose proof holds it (`proof_parent`). A step with no such statement is left
    out."""
    from .source_regions import RegionError, extract
    out = []
    for f in files:
        try:
            lines = (snap / f).read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        for st in find_proof_equations(lines, f, numbers):
            parent = proof_parent(statements, f, st["proof_line"], st["proof_ref"])
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


# -- proof passages: lines of a proof selected as a step (zero configuration) -----------------
#
# A passage is selected by its lines (`machinechecked link CLAIM --passage FILE:A-B`, or in the
# reader) and kept in the links file under a key of its own, with its parent's key and the pin
# of its lines (`tex-region-v1`: the digest of the lines' text, and of each line). The pin never
# moves by itself: when the lines no longer hold the text they were selected at, the passage
# has no current text, so no review of it counts until it is selected again.

PASSAGE_SPEC = re.compile(r"(?P<file>.+):(?P<a>\d+)(?:-(?P<b>\d+))?")
PASSAGE_KEY = re.compile(r"(?P<parent>.+)/passage-(?P<n>\d+)")


class PassageError(ValueError):
    """A selection of a proof passage refused before anything was written."""


def parse_passage(spec: str) -> tuple[str, int, int]:
    """`FILE:A-B` (or `FILE:A`, one line) as (file, first line, last line)."""
    m = PASSAGE_SPEC.fullmatch(str(spec or "").strip())
    if not m:
        raise PassageError(f"{spec!r}: give the passage as FILE:A-B, lines A to B of FILE")
    a, b = int(m["a"]), int(m["b"] or m["a"])
    if a < 1 or b < a:
        raise PassageError(f"{spec!r}: lines A to B need 1 <= A <= B")
    return m["file"], a, b


def proofs(lines: list[str]) -> list[dict]:
    """The proof environments of a source file, outside comments: the line each opens on
    (`line`), the line it closes on (`end_line`), and the label its optional argument refers to
    (`ref`, as in `\\begin{proof}[Proof of Theorem~\\ref{thm:x}]`). A proof left open is not
    listed."""
    out, open_ = [], []
    for i, line in enumerate(lines, 1):
        text = _uncomment(line)
        for m in PROOF.finditer(text):
            if m.group(1) == "begin":
                rest = text[m.end():]
                rm = REF.search(rest)
                open_.append({"line": i, "ref": rm.group(1) if rm and rest.lstrip()
                              .startswith("[") else None})
            elif open_:
                p = open_.pop()
                out.append({"line": p["line"], "end_line": i, "ref": p["ref"]})
    return sorted(out, key=lambda p: p["line"])


def enclosing_proof(found: list[dict], a: int, b: int) -> dict | None:
    """The innermost proof of `found` (`proofs`) whose body holds lines `a` to `b`: the lines
    lie strictly between its opening and closing lines."""
    inside = [p for p in found if p["line"] < a and b < p["end_line"]]
    return max(inside, key=lambda p: p["line"]) if inside else None


def _cut_environment(lines: list[str], a: int, b: int) -> str | None:
    """Where lines `a` to `b` cut an environment, in words, or None when every environment
    they open they also close."""
    from .source_regions import RegionError, environments
    text = "\n".join(lines[a - 1:b])
    starts = [0]
    for line in lines[a - 1:b]:
        starts.append(starts[-1] + len(line) + 1)

    def at(i: int) -> int:
        return a + sum(1 for s in starts[1:] if s <= i)
    stack: list[tuple[str, int]] = []
    try:
        for op, env, i, _ in environments(text, 0):
            if op == "begin":
                stack.append((env, at(i)))
            elif stack and stack[-1][0] == env:
                stack.pop()
            else:
                return f"it ends the {env} environment at line {at(i)} without its beginning"
    except RegionError as e:
        return str(e)
    if stack:
        env, line = stack[-1]
        return f"it begins the {env} environment at line {line} without its end"
    return None


def overlaps(file: str, a: int, b: int, taken: list[dict]) -> list[dict]:
    """The steps of `taken` (each with `file`, `start_line`, `end_line`) whose lines meet lines
    `a` to `b` of `file`."""
    return [t for t in taken if t.get("file") == file
            and not (b < t["start_line"] or t["end_line"] < a)]


def source_lines(root: Path, file: str) -> list[str]:
    """The lines of a source file of the snapshot at `root`, as the steps read them."""
    from .source_regions import source_file
    return source_file(root, file).read_text(encoding="utf-8", errors="replace").split("\n")


def select_passage(root: Path, file: str, a: int, b: int, statements: list[dict],
                   taken: list[dict]) -> dict:
    """Lines `a` to `b` of `file` in the snapshot at `root` as a proof passage, or
    PassageError saying why not. The lines lie inside one proof, between its opening and closing
    lines; they open and close the same environments; they hold text that is not a comment;
    they meet no other proof step (`taken`, each with its `file`, `start_line`, `end_line` and
    `id`); and the proof belongs to a statement (`proof_parent`, from `statements`). Returns
    the passage's pin (`region_pin`), its parent and the line its proof opens on."""
    from .source_regions import RegionError
    try:
        lines = source_lines(root, file)
    except (OSError, RegionError):
        raise PassageError(f"{file}: no such source file of the paper") from None
    if b > len(lines):
        raise PassageError(f"{file} has {len(lines)} lines; lines {a}-{b} are outside it")
    found = proofs(lines)
    proof = enclosing_proof(found, a, b)
    if proof is None:
        raise PassageError(f"lines {a}-{b} of {file} are not inside a proof: a passage is lines "
                           "between a proof's \\begin{proof} and \\end{proof}")
    for p in found:
        if p is not proof and (a <= p["line"] <= b) != (a <= p["end_line"] <= b):
            raise PassageError(f"lines {a}-{b} of {file} cut the proof at lines "
                               f"{p['line']}-{p['end_line']}")
    cut = _cut_environment(lines, a, b)
    if cut:
        raise PassageError(f"lines {a}-{b} of {file} do not hold whole environments: {cut}")
    if not any(_uncomment(l).strip() for l in lines[a - 1:b]):
        raise PassageError(f"lines {a}-{b} of {file} hold no text of the proof")
    hit = overlaps(file, a, b, taken)
    if hit:
        raise PassageError(f"lines {a}-{b} of {file} overlap "
                           + ", ".join(f"{t.get('number') or t['id']} (lines {t['start_line']}-"
                                       f"{t['end_line']})" for t in hit)
                           + ": a line of a proof belongs to one step")
    parent = proof_parent(statements, file, proof["line"], proof["ref"])
    if parent is None:
        raise PassageError(f"the proof at line {proof['line']} of {file} follows no statement")
    try:
        pin, _ = region_pin(root, file, a, b)
    except RegionError as e:
        raise PassageError(f"lines {a}-{b} of {file}: {e}") from None
    return {"pin": pin, "parent": parent, "proof_line": proof["line"]}


def region_pin(root: Path, file: str, a: int, b: int) -> tuple[dict, str]:
    """The pin of lines `a` to `b` of `file` in the snapshot at `root`, whole lines as
    `source_regions.extract` reads an explicit span (`tex-region-v1`: the digest of their text,
    and of each line), and their text. RegionError when they cannot be read."""
    from .source_regions import SCHEME, extract
    r = extract(root, {"location": f"{file}:{a}", "source_region": {"end_line": b}})
    return {"file": file, "start_line": a, "end_line": b, "scheme": SCHEME,
            "sha256": r.sha256, "line_sha256": r.line_sha256}, r.text


def _lines(a: int, b: int) -> str:
    return f"line {a}" if a == b else f"lines {a}-{b}"


def _spec(file: str, a: int, b: int) -> str:
    return f"{file}:{a}" if a == b else f"{file}:{a}-{b}"


def passage_number(parent: dict | None, file: str, a: int, b: int) -> str:
    """How a passage is named: its proof and its pinned lines. It ends in no bare number, so
    a statement's number never resolves to it."""
    where = f"{file}:{a}" + (f"–{b}" if b > a else "")
    return f"Proof of {parent['number']}, {where}" if parent else f"Proof passage, {where}"


def passage_key(parent_key: str, keys) -> str:
    """The key of a new passage of the proof of `parent_key`: `<parent key>/passage-<n>`, with
    `n` one more than any such key in `keys`."""
    used = [int(m["n"]) for k in keys if (m := PASSAGE_KEY.fullmatch(str(k)))
            and m["parent"] == parent_key]
    return f"{parent_key}/passage-{max(used, default=0) + 1}"


def stored_pin(entry: dict) -> dict | None:
    """The pin of a links-file entry's passage, when it is a well-formed one."""
    p = entry.get("passage") if isinstance(entry, dict) else None
    if not isinstance(p, dict):
        return None
    ok = (isinstance(p.get("file"), str) and p["file"]
          and all(type(p.get(k)) is int and p[k] >= 1 for k in ("start_line", "end_line"))
          and p["start_line"] <= p["end_line"] and isinstance(p.get("sha256"), str))
    return p if ok else None


def moved_to(lines: list[str], pin: dict) -> dict | None:
    """Where the text a passage was pinned at is now, when its lines hold it at exactly one
    place of the file: the lines with the pinned digests, in order."""
    want = pin.get("line_sha256")
    if not isinstance(want, list) or not want:
        return None
    import hashlib
    have = [hashlib.sha256(l.rstrip("\r").encode("utf-8")).hexdigest() for l in lines]
    n = len(want)
    at = [i + 1 for i in range(len(have) - n + 1) if have[i:i + n] == want]
    return {"start_line": at[0], "end_line": at[0] + n - 1} if len(at) == 1 else None


def step_region(c: dict) -> dict | None:
    """The lines of a proof step claim (`file`, `start_line`, `end_line`), with its `id` and
    `number`, from its location and region."""
    path, _, line = str(c.get("location") or "").rpartition(":")
    if not path or not line.isdigit():
        return None
    end = (c.get("source_region") or {}).get("end_line") or int(line)
    return {"id": c.get("id"), "number": c.get("number"), "unit": c.get("unit"), "file": path,
            "start_line": int(line), "end_line": int(end)}


def passage_claims(pid: str, entries: dict, statements: list[dict], snap: Path,
                   taken=()) -> tuple[list[dict], list[str]]:
    """The selected passages of the links file (`entries`, the paper's entries by key) as
    claims (`unit: proof-passage`), each under its recorded parent, and notes on any whose
    lines no longer hold the text they were selected at, or that overlap another step
    (`taken`, the other steps' `step_region`s). A passage whose lines changed has no current
    text (`source_sha256` is None, and no text is shown), so no review of it counts; its
    `passage` says where its text is now when the file holds it at one place."""
    from .source_regions import RegionError
    out, notes = [], []
    texts: dict[str, list[str] | None] = {}
    by_key = {c.get("key"): c for c in statements}
    for key, entry in sorted(entries.items()):
        pin = stored_pin(entry)
        if pin is None:
            if isinstance(entry, dict) and "passage" in entry:
                notes.append(f"the passage {key} in the links file has no well-formed pin "
                             "(file, start_line, end_line, sha256) and is not shown")
            continue
        file, a, b = pin["file"], pin["start_line"], pin["end_line"]
        if file not in texts:
            try:
                texts[file] = source_lines(snap, file)
            except (OSError, RegionError):
                texts[file] = None
        lines = texts[file]
        parent = by_key.get(pin.get("parent"))
        try:
            now, text = region_pin(snap, file, a, b)
        except (OSError, RegionError):
            now, text = None, None
        matches = bool(now) and now["sha256"] == pin["sha256"]
        proof = enclosing_proof(proofs(lines), a, b) if matches and lines else None
        where = {"file": file, "start_line": a, "end_line": b, "sha256": pin["sha256"],
                 "scheme": pin.get("scheme") or "tex-region-v1", "matches": matches,
                 **{k: pin[k] for k in ("by", "at") if isinstance(pin.get(k), str)}}
        if not matches:
            moved = moved_to(lines, pin) if lines is not None else None
            if moved:
                where["moved_to"] = moved
            notes.append(f"the passage {key} no longer matches its pin: {_lines(a, b)} of "
                         f"{file} do not hold the text it was selected at, so no review of it "
                         "counts; "
                         + (f"that text is now at {_lines(moved['start_line'], moved['end_line'])}"
                            f"; select it there with `machinechecked link {key} --passage "
                            f"{_spec(file, moved['start_line'], moved['end_line'])}`" if moved
                            else f"select it again with `machinechecked link {key} --passage "
                            f"{file}:A-B`"))
        if pin.get("parent") and parent is None:
            notes.append(f"the passage {key} belongs to {pin['parent']}, which this paper no "
                         "longer has")
        out.append({
            "id": f"{pid}:{key}", "key": key, "paper": pid, "kind": "passage",
            "number": passage_number(parent, file, a, b), "title": "", "label": None,
            "location": f"{file}:{a}", "line": a,
            "source_sha256": pin["sha256"] if matches else None,
            "source_hash_scheme": where["scheme"], "source_region": {"end_line": b},
            "scope": "proof-step",
            "scope_note": f"a passage of the proof of {parent['number']}" if parent else
            "a passage of a proof",
            "scope_reviewed": True, "clauses": [], "tags": [],
            "unit": "proof-passage", "parent": parent["id"] if parent else None,
            "passage": where,
            "statement_tex": text if matches else None,
            "context_tex": context_lines(lines, {"proof_line": proof["line"], "line": a,
                                                 "end_line": b}) if proof else None})
    regions = [{"id": c["key"], "file": c["passage"]["file"],
                "start_line": c["passage"]["start_line"], "end_line": c["passage"]["end_line"]}
               for c in out]
    for i, r in enumerate(regions):
        for o in overlaps(r["file"], r["start_line"], r["end_line"],
                          regions[i + 1:] + list(taken)):
            notes.append(f"the passage {r['id']} overlaps {o.get('number') or o['id']}; "
                         "select the passage again")
    return out, notes


def proof_view(lines_of, statements: list[dict], taken: list[dict], claim_id: str) -> dict:
    """The proofs of the statement `claim_id`, as the reader's selection of a passage shows
    them: each proof's file, its opening and closing lines and its lines' text, and the proof
    steps already in them (`taken`). `lines_of(file)` gives a file's lines, or None."""
    me = next((c for c in statements if c.get("id") == claim_id), None)
    if me is None:
        raise PassageError(f"{claim_id} is not a statement of the paper")
    out = []
    for file in sorted({c.get("location") for c in statements if c.get("location")}):
        lines = lines_of(file)
        if lines is None:
            continue
        for p in proofs(lines):
            par = proof_parent(statements, file, p["line"], p["ref"])
            if par is not None and par.get("id") == claim_id:
                out.append({"file": file, "start_line": p["line"], "end_line": p["end_line"],
                            "lines": lines[p["line"] - 1:p["end_line"]],
                            "steps": [{k: t.get(k) for k in ("id", "number", "unit",
                                                            "start_line", "end_line")}
                                      for t in overlaps(file, p["line"], p["end_line"], taken)]})
    return {"claim": claim_id, "proofs": out}


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


def cut_text(text: str, file: str, first_line: int) -> tuple[str, dict | None]:
    """`text`, which starts on line `first_line` of `file`, kept to its first `TEXT_CHARS`
    characters; and, when that shortens it, where it was cut: the line holding the first
    character left out (`line`), the last line of the whole text (`end_line`), and how many of
    its characters were kept (`kept` of `chars`)."""
    if len(text) <= TEXT_CHARS:
        return text, None
    kept = text[:TEXT_CHARS]
    return kept, {"file": file, "line": first_line + kept.count("\n"),
                  "end_line": first_line + text.count("\n"), "kept": len(kept),
                  "chars": len(text)}


def context_cut(rec: dict) -> dict | None:
    """Where the context of a `step_texts` record was cut, or None when it is whole. Evidence
    written before cuts were recorded holds a context cut at the limit with no record of
    where: such a context is taken as cut, at a place it does not record."""
    if rec.get("context_cut"):
        return rec["context_cut"]
    context = rec.get("context") or ""
    return {"kept": len(context)} if len(context) >= TEXT_CHARS else None


def step_texts(inv: dict, paper: str, root: Path, regions: dict) -> dict[str, dict]:
    """For each proof step of `paper` in the inventory: the text of its pinned region, whole,
    and its context in the proof (`context_lines`: from the proof's opening, at most
    `CONTEXT_LINES` lines before it, to the sentence after it), kept to `TEXT_CHARS`
    characters, with where it was cut when it was (`context_cut`, from `cut_text`). Read from
    the snapshot the source evidence was computed on."""
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
        where = {"proof_line": proof, "line": start, "end_line": end}
        context, cut = cut_text(context_lines(lines, where), reg["file"], context_start(where))
        out[c["id"]] = {"text": text, "context": context, **({"context_cut": cut} if cut else {})}
    return out


def _fields(code: str) -> dict:
    from .status import fields
    return fields(code)
