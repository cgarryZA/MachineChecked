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


# Where an author's proposed verdict on a step is kept apart from the claim records, so that no
# client receives it before the reviewer's own verdict (`split_proposals`, #678).
PROPOSALS = "proposals"
PROPOSAL_SCHEMA = "machinechecked/step-proposal@1"


def proposal(entry: dict, source: str) -> dict | None:
    """The verdict an author proposes for a printed step (`proposed` of its entry in the
    inventory or the links file): one of the step verdicts (`VERDICTS`), with a note and,
    optionally, the Lean theorem the author says it rests on, proving the step or refuting it,
    which is the author's and not checked by Lean here. None when the entry proposes none, or
    not one of the step verdicts. It is shown only after the reviewer's own verdict, and it
    neither completes a review nor changes a status."""
    p = entry.get("proposed")
    if not isinstance(p, dict) or p.get("verdict") not in [v for vs in VERDICTS.values()
                                                          for v in vs]:
        return None
    th = p.get("theorem")
    return {"verdict": p["verdict"], "note": _str(p.get("note")),
            "theorem": th.strip() if isinstance(th, str) and th.strip() else None,
            "by": p["by"] if isinstance(p.get("by"), str) else None, "source": source}


def split_proposals(chunks: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """The claim records `chunks` (by file name) without their steps' proposals, and each
    proposal as a file of its own (`data/proposals/<file>`, `PROPOSAL_SCHEMA`), which the review
    page fetches only at its step 3 and the claim page on its own."""
    out, files = {}, {}
    for name, ch in chunks.items():
        st = ch.get("step")
        if isinstance(st, dict) and st.get("proposed"):
            files[name] = {"schema": PROPOSAL_SCHEMA, "claim": ch.get("id"),
                           "unit": "step:" + str(ch.get("id")), "proposed": st["proposed"]}
            ch = {**ch, "step": {k: v for k, v in st.items() if k != "proposed"}}
        out[name] = ch
    return out, files


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
                                   "author": m.by in authors,
                                   # A model reviewer accepted over the same-family rule.
                                   **({"accepted_family": m.accepted_family}
                                      if getattr(m, "accepted_family", None) else {})},
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
          unit: str | None = None, proposed: dict | None = None, candidates=()) -> dict:
    """What a claim record says about a proof step: its kind, its parent (or, when it is not
    certain which statement its proof proves, the `candidates`), the Lean that establishes it,
    the formal route used instead, and its own review; and the verdict its author proposes
    (`proposal`), which the site writes apart (`split_proposals`)."""
    return {"unit": unit or unit_of(claim), "parent": parent_ref(parent),
            **({"parent_candidates": [parent_ref(c) for c in candidates if c]}
               if candidates else {}),
            "source": {"location": claim.get("location"),
                       "region": claim.get("source_region"),
                       "sha256": claim.get("source_sha256")},
            "links": links, "correspondence": corr,
            "route": {"links": route, "note": (rnote or {}).get("note", ""),
                      "by": (rnote or {}).get("by"), "source": (rnote or {}).get("source")}
            if route else None,
            "review": reviewed, **({"proposed": proposed} if proposed else {})}


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

DISPLAY_ENVS = ("equation", "align", "gather", "multline", "eqnarray", "flalign", "alignat")
DISPLAY = re.compile(r"\\begin\{(" + "|".join(DISPLAY_ENVS) + r")\}")
# Environments that number each row: a display of several labelled rows is a step per row.
ROW_ENVS = {"align", "gather", "eqnarray", "flalign", "alignat"}
# A macro defined as the opening or closing of a display (`\def\beq{\begin{equation}}`).
DISPLAY_MACRO = re.compile(
    r"\\(?:def|(?:re|provide)?newcommand\*?)\s*\{?\\([A-Za-z@]+)\}?\s*\{\s*\\(begin|end)\{("
    + "|".join(DISPLAY_ENVS) + r")\}\s*\}")
PROOF = re.compile(r"\\(begin|end)\{proof\}")
LABEL = re.compile(r"\\label\{([^}]*)\}")
REF = re.compile(r"\\(?:ref|eqref|cref|Cref|autoref)\{([^}]*)\}")
CONTEXT_LINES = 40
# A proof's title naming a statement by its printed number ("Proof of Theorem 2.1").
PROOF_OF = re.compile(r"\bproof\s+of\s+([A-Za-z]+)\s*~?\s*"
                      r"([A-Z]?\d+(?:\.\d+)*[a-z]?|[A-Z](?:\.\d+)+)", re.I)
# Kinds of statement often printed without a proof of their own, between a result and its proof:
# an unnamed proof after one is not attached by its place alone (`resolve_parent`). They can
# have proofs of their own too.
ASIDE_KINDS = {"remark", "example", "note", "notes", "observation", "exercise", "convention"}


def _uncomment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def _proof_title(rest: str) -> str | None:
    """The optional argument of a `\\begin{proof}` whose text after the command is `rest`
    (`[Proof of Theorem~\\ref{thm:x}]`), or None."""
    rest = rest.lstrip()
    if not rest.startswith("["):
        return None
    depth = 0
    for i, ch in enumerate(rest):
        depth += {"{": 1, "}": -1}.get(ch, 0)
        if ch == "]" and depth == 0:
            return rest[1:i]
    return None


def aux_numbers(aux_text: str) -> dict[str, str]:
    """The printed number of each label, from a LaTeX `.aux` file."""
    out = {}
    for m in re.finditer(r"\\newlabel\{([^}]*)\}\{\{([^{}]*)\}", aux_text):
        out.setdefault(m.group(1), m.group(2))
    return out


def display_macros(texts) -> dict[str, tuple[str, str]]:
    """The macros the source `texts` define as the opening or the closing of a display
    environment, by name: `(begin|end, environment)`."""
    out = {}
    for t in texts:
        for m in DISPLAY_MACRO.finditer(_uncomment_all(t)):
            out.setdefault(m.group(1), (m.group(2), m.group(3)))
    return out


def _uncomment_all(text: str) -> str:
    return "\n".join(_uncomment(l) for l in text.split("\n"))


def _opening(text: str, macros: dict[str, tuple[str, str]]):
    """The first display opened in `text`, as `(environment, start, end, by_macro)`, or None."""
    found = []
    d = DISPLAY.search(text)
    if d:
        found.append((d.start(), d.group(1), d.end(), False))
    for name, (op, env) in macros.items():
        if op == "begin":
            m = re.search(r"\\" + re.escape(name) + r"(?![A-Za-z@])", text)
            if m:
                found.append((m.start(), env, m.end(), True))
    if not found:
        return None
    start, env, end, by_macro = min(found)
    return env, start, end, by_macro


def _closing(env: str, macros: dict[str, tuple[str, str]]) -> re.Pattern:
    names = [re.escape(n) for n, (op, e) in macros.items() if op == "end" and e == env]
    return re.compile(r"\\end\{" + env + r"\}"
                      + "".join(r"|\\" + n + r"(?![A-Za-z@])" for n in names))


def _rows(text: str, first_line: int) -> list[dict]:
    """The rows of a display's body `text` (which starts on line `first_line`): the parts
    between the row breaks (`\\\\`) outside braces and inner environments, each with the lines
    it spans (`line`, `end_line`, from its first to its last character that is not a space)
    and its labels."""
    rows, depth, inner, start, k = [], 0, 0, 0, 0
    while k < len(text):
        ch = text[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        elif text.startswith("\\begin{", k):
            inner += 1
        elif text.startswith("\\end{", k):
            inner -= 1
        if text.startswith("\\\\", k) and depth == 0 and inner == 0:
            rows.append((start, k + 2))
            start = k = k + 2
            continue
        k += 2 if ch == "\\" else 1
    rows.append((start, len(text)))
    out = []
    for a, b in rows:
        part = text[a:b]
        if not part.strip():
            continue
        lead = a + len(part) - len(part.lstrip())
        tail = a + len(part.rstrip())
        out.append({"line": first_line + text.count("\n", 0, lead),
                    "end_line": first_line + text.count("\n", 0, max(lead, tail - 1)),
                    "labels": LABEL.findall(part)})
    return out


def find_proof_equations(lines: list[str], file: str, numbers: dict[str, str],
                         macros: dict[str, tuple[str, str]] | None = None,
                         left: list[dict] | None = None) -> list[dict]:
    """The numbered, labelled displays inside the proofs of one source file: each with its
    label, printed number, opening line, the line its proof opens on, and the label the proof's
    optional argument refers to (`\\begin{proof}[Proof of Theorem~\\ref{thm:x}]`). A display is
    opened by its environment or by a macro defined as its opening (`macros`,
    `display_macros`). A display with one label is one step. A display of several labelled
    rows (`ROW_ENVS`) is a step per labelled, numbered row, with the row's lines (`rows`). Each
    numbered display, or row, left out (several labels, a label with no number, a row on the
    line of another) is added to `left`, with its label, its line and why."""
    macros = macros or {}
    out, proof, ref, title = [], None, None, None

    def skip(labels, line, reason):
        if left is not None and labels:
            left.append({"label": ", ".join(labels), "file": file, "line": line,
                         "reason": reason})

    i = 0
    while i < len(lines):
        text = _uncomment(lines[i])
        for m in PROOF.finditer(text):
            if m.group(1) == "begin":
                proof = i + 1
                rm = REF.search(text[m.end():])
                ref = rm.group(1) if rm and text[m.end():].lstrip().startswith("[") else None
                title = _proof_title(text[m.end():])
            else:
                proof, ref, title = None, None, None
        d = _opening(text, macros)
        if proof is not None and d:
            env, _, opened, by_macro = d
            end = _closing(env, macros)
            j, labels, body_text, closed_at = i, [], [], None
            while j < len(lines):
                body = _uncomment(lines[j])
                part = body[opened:] if j == i else body
                e = end.search(part)
                body_text.append(part[:e.start()] if e else part)
                labels += LABEL.findall(part[:e.start()] if e else part)
                if e:
                    closed_at = j
                    break
                j += 1
            where = {"file": file, "proof_line": proof, "proof_ref": ref, "proof_title": title}
            if closed_at is None:
                i = j + 1
                continue
            if len(labels) == 1 and labels[0] in numbers:
                out.append({"label": labels[0], "number": numbers[labels[0]], "line": i + 1,
                            "end_line": j + 1, **where,
                            **({"env": env, "explicit": True} if by_macro else {})})
            elif len(labels) > 1 and env in ROW_ENVS:
                rows = _rows("\n".join(body_text), i + 1)
                for r in rows:
                    shared = [x for x in rows if x is not r and x["labels"]
                              and not (x["end_line"] < r["line"] or r["end_line"] < x["line"])]
                    if len(r["labels"]) > 1:
                        skip(r["labels"], r["line"], "the row has several labels")
                    elif r["labels"] and r["labels"][0] not in numbers:
                        skip(r["labels"], r["line"], "its label has no printed number")
                    elif r["labels"] and shared:
                        skip(r["labels"], r["line"], "its row shares a line with another "
                                                     "labelled row, so it has no lines of its own")
                    elif r["labels"]:
                        out.append({"label": r["labels"][0], "number": numbers[r["labels"][0]],
                                    "line": r["line"], "end_line": r["end_line"], **where,
                                    "env": env, "explicit": True, "row": True})
            elif len(labels) > 1:
                skip(labels, i + 1, f"it is one {env} display, with one number, and it has "
                                    "several labels")
            else:
                skip(labels, i + 1, "its label has no printed number")
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


def _kind(c: dict) -> str:
    """A statement's kind: its own, else the first word of its printed number."""
    return (c.get("kind") or (c.get("number") or "").split(" ")[0]).lower()


def resolve_parent(statements: list[dict], file: str, proof_line: int, ref: str | None,
                   title: str | None = None, proof_lines=()) -> tuple[dict | None, list[dict]]:
    """The statement whose proof opens on `proof_line` of `file`, and the candidates when that
    is not certain. A proof whose optional argument names a statement, by its label (`ref`) or
    by its printed number (`title`: "Proof of Theorem 2.1"), proves that one. Otherwise it
    proves the last statement of the same file opening before it, unless that statement is an
    aside (`ASIDE_KINDS`: a remark, an example) and the last statement before the asides is not
    proved yet (no proof of `proof_lines` opens between it and this one): either may then be
    the one proved, and the parent is None, with that statement and the asides as candidates.
    `(None, [])` when no statement precedes the proof."""
    if ref:
        named = next((c for c in statements if c.get("label") == ref), None)
        if named is not None:
            return named, []
    m = PROOF_OF.search(title or "")
    if m:
        number = f"{m.group(1)} {m.group(2)}".lower()
        named = [c for c in statements if (c.get("number") or "").lower() == number]
        if len(named) == 1:
            return named[0], []
    before = sorted((c for c in statements if c.get("location") == file and c.get("line")
                     and c["line"] < proof_line), key=lambda c: c["line"])
    if not before:
        return None, []
    asides = []
    while before and _kind(before[-1]) in ASIDE_KINDS:
        asides.insert(0, before.pop())
    if not asides or not before:
        return (asides or before)[-1], []
    result = before[-1]
    if any(result["line"] < p < proof_line for p in proof_lines):
        # The result has its proof already: this one is the aside's own.
        return asides[-1], []
    return None, [result, *asides]


def proof_parent(statements: list[dict], file: str, proof_line: int, ref: str | None,
                 title: str | None = None, proof_lines=()) -> dict | None:
    """The statement whose proof opens on `proof_line` of `file` (`resolve_parent`); None when
    none precedes it or it is not certain which one it proves."""
    return resolve_parent(statements, file, proof_line, ref, title, proof_lines)[0]


def step_claims(pid: str, statements: list[dict], snap: Path, files: list[str],
                numbers: dict[str, str], notes: list[str] | None = None) -> list[dict]:
    """The proof equations of the source as claims (`unit: proof-equation`), each under the
    statement whose proof holds it (`resolve_parent`). A step with no such statement is left
    out. A step that is a row of a display, or a display opened by a macro, is pinned by its
    own lines. Each numbered display of a proof left out (`find_proof_equations`) is said in
    `notes`, with its label, its place and why."""
    from .source_regions import RegionError, extract, tex_sources
    out = []
    macros = display_macros(tex_sources(snap).values())
    for f in files:
        try:
            lines = (snap / f).read_text(encoding="utf-8", errors="replace").split("\n")
        except OSError:
            continue
        opened = [p["line"] for p in proofs(lines)]
        left: list[dict] = []
        for st in find_proof_equations(lines, f, numbers, macros, left):
            parent, candidates = resolve_parent(statements, f, st["proof_line"], st["proof_ref"],
                                                st.get("proof_title"), opened)
            if parent is None and not candidates:
                continue
            claim = {"location": f"{f}:{st['line']}"}
            if st.get("explicit"):
                claim["source_region"] = {"end_line": st["end_line"]}
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
                "scope": "proof-step",
                "scope_note": f"a step of the proof of {parent['number']}" if parent else
                "a step of a proof whose statement is not certain: "
                + " or ".join(c["number"] for c in candidates),
                "scope_reviewed": True, "clauses": [], "tags": [],
                "unit": "proof-equation", "parent": parent["id"] if parent else None,
                **({"parent_candidates": [c["id"] for c in candidates]} if candidates else {}),
                "statement_tex": _display_tex(lines, st, macros),
                "context_tex": context_lines(lines, st)})
        if notes is not None:
            notes += [f"{x['file']}:{x['line']}: the numbered display {x['label']} in a proof is "
                      f"not listed as a step: {x['reason']}" for x in left]
    return out


def _display_tex(lines: list[str], st: dict, macros: dict[str, tuple[str, str]]) -> str:
    """The text of a step's display, as the reader typesets it: a row inside its environment,
    and a display's macros written out (display only; the pin holds the source's lines)."""
    text = "\n".join(lines[st["line"] - 1:st["end_line"]])
    if st.get("row"):
        return f"\\begin{{{st['env']}}}\n{text}\n\\end{{{st['env']}}}"
    for name, (op, env) in macros.items():
        text = re.sub(r"\\" + re.escape(name) + r"(?![A-Za-z@])",
                      lambda _: f"\\{op}{{{env}}}", text)
    return text


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
                              .startswith("[") else None, "title": _proof_title(rest)})
            elif open_:
                p = open_.pop()
                out.append({"line": p["line"], "end_line": i, "ref": p["ref"],
                            "title": p["title"]})
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
    parent, candidates = resolve_parent(statements, file, proof["line"], proof["ref"],
                                        proof.get("title"), [p["line"] for p in found])
    if candidates:
        raise PassageError(f"the proof at line {proof['line']} of {file} may prove "
                           + " or ".join(c.get("number") or c["id"] for c in candidates)
                           + ": it names no statement and follows an aside, so the statement "
                           "its passages belong to is not certain")
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
                 reviewed or {"state": "unreviewed", "finding": None, "reports": []}, unit,
                 proposal(claim, "inventory")), names


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
