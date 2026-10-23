"""References to the paper's numbered statements in the Lean, checked against the paper (#127).

A formalisation written against an earlier version of a paper keeps that version's numbers in
its docstrings and names: `/-- Theorem 2.1: … -/`, `theorem lemma_3_4`. This module finds each
such reference (with its exact text, its declaration or module, file and line) and compares it
with the numbering of the paper at the revision the audit reads:

- `exact`: the paper has a statement of that kind and number;
- `other-kind`: the number exists, under another kind (the docstring says Lemma 2.3, the
  paper's 2.3 is a Proposition);
- `absent`: the paper, whose numbering is completely known, has no statement with that number;
- `unchecked`: the paper's numbering is not completely known in this build (a PDF read by its
  headings, a paper that did not compile), so the reference is neither confirmed nor refuted;
- `other-source`: the reference is to another work (`Theorem 3 of [AB]`) or sits in a namespace
  the project maps to another paper; it says nothing about this paper.

An exact reference whose declaration's statement reads much closer to another statement of the
paper (`retrieval.py`) keeps its status and is marked as a possibly stale lead, with the closer
statement named. When several references disagree with the paper, in number and in proportion,
the project-level pattern says the Lean appears to follow another version of the paper; one
stray reference is reported alone and never read as a version change. An explicit map between
two versions of the paper resolves a renumbered reference when it names one current statement,
and keeps every candidate when it names several.

This changes what suggestions say and how much a cited number counts; it never creates a link
or changes a status.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

KINDS = {"theorem": "theorem", "thm": "theorem", "lemma": "lemma", "lem": "lemma",
         "proposition": "proposition", "prop": "proposition", "corollary": "corollary",
         "cor": "corollary", "definition": "definition", "defn": "definition",
         "def": "definition", "remark": "remark", "rem": "remark", "example": "example",
         "assumption": "assumption", "ass": "assumption", "hypothesis": "assumption",
         "hyp": "assumption", "conjecture": "conjecture", "conj": "conjecture",
         "claim": "claim", "section": "section", "sec": "section", "subsection": "section",
         "§": "section"}
WORD = {"theorem": "Theorem", "lemma": "Lemma", "proposition": "Proposition",
        "corollary": "Corollary", "definition": "Definition", "remark": "Remark",
        "example": "Example", "assumption": "Assumption", "conjecture": "Conjecture",
        "claim": "Claim", "section": "Section"}

REF = re.compile(r"(?<![\w.])(Theorem|Thm|Lemma|Lem|Proposition|Prop|Corollary|Cor|Definition|"
                 r"Defn|Def|Remark|Rem|Example|Assumption|Hypothesis|Conjecture|Claim|"
                 r"Subsection|Section|Sec|§)\.?[ \t~]*(\d+(?:\.\d+)*)(?![\w]|\.\d)", re.I)
NAME_REF = re.compile(r"(?:^|_)(theorem|thm|lemma|lem|proposition|prop|corollary|cor|"
                      r"definition|defn|def|section|sec)_?(\d+(?:_\d+)*)(?=_|$)")
_ELSEWHERE_AFTER = re.compile(
    r"\s*(?:,\s*)?(?:of|in|from)\s+(?!(?:the|this|our)\s+(?:paper|article|manuscript|note|text|"
    r"preprint)\b)(?:\[|\\cite|[A-Z]|the\s+[A-Z]|arXiv|ref)|\s*\[")
_ELSEWHERE_BEFORE = re.compile(r"\[[^\]]*$|\bet al\.?\s*,?\s*$")

DRIFT_MIN = 3           # disagreeing references needed before a pattern is reported
DRIFT_SHARE = 0.3       # ... and their share of the references checked
CLOSER_MIN = 0.4        # an exact reference reads elsewhere when another statement is at
CLOSER_MARGIN = 0.15    # least this similar to the declaration, and this much more than the cited


def canonical(kind_word: str) -> str:
    k = kind_word.lower().rstrip(".")
    return KINDS.get(k, k)


def printed(kind: str, number: str) -> str:
    return f"{WORD.get(kind, kind.capitalize())} {number}"


def claim_ref(claim: dict) -> tuple[str, str] | None:
    """A claim's (kind, number), from its printed number (`Theorem 2.1`)."""
    parts = (claim.get("number") or "").rsplit(" ", 1)
    if len(parts) != 2 or not re.fullmatch(r"\d+(?:\.\d+)*", parts[1]):
        return None
    return canonical(claim.get("kind") or parts[0]), parts[1]


def sections_from_aux(aux: Path) -> set[str] | None:
    """The section numbers a LaTeX compilation wrote to its table of contents, or None when
    there is no such file."""
    if not aux.is_file():
        return None
    text = aux.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"\\contentsline\s*\{(?:sub)*section\}\{\\numberline\s*\{([\d.]+)\}",
                          text))


def module_doc_blocks(root: Path | None, modules) -> list[dict]:
    """The module docstrings (`/-! … -/`) of the project's modules, with their file and the
    line each begins on."""
    out = []
    if root is None:
        return out
    for m in sorted(set(modules)):
        rel = m.replace(".", "/") + ".lean"
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for mt in re.finditer(r"/-!(.*?)-/", text, re.S):
            out.append({"module": m, "file": rel, "line": text.count("\n", 0, mt.start(1)) + 1,
                        "text": mt.group(1)})
    return out


def _elsewhere(text: str, start: int, end: int) -> str | None:
    if _ELSEWHERE_AFTER.match(text[end:end + 60]) or _ELSEWHERE_BEFORE.search(
            text[max(0, start - 60):start]):
        return "it refers to another work"
    return None


def _context(text: str, start: int, end: int) -> str:
    a, b = max(0, start - 60), min(len(text), end + 60)
    return (("…" if a else "") + re.sub(r"\s+", " ", text[a:b]).strip()
            + ("…" if b < len(text) else ""))


def find_references(index: list[dict], blocks: list[dict], foreign=frozenset()) -> list[dict]:
    """Every reference to a numbered statement or section in the project's declaration
    docstrings, declaration names and module docstrings, with its source."""
    out = []
    foreign = set(foreign)

    def obs(kind_word, number, exact, context, source, scope_note):
        kind = canonical(kind_word)
        key = "\n".join([source.get("declaration") or "", source.get("file") or "",
                         str(source.get("line")), source["where"], exact])
        o = {"id": "ref:" + hashlib.sha256(key.encode()).hexdigest()[:12],
             "reference": printed(kind, number), "kind": kind, "number": number,
             "text": exact, "context": context, "source": source}
        if scope_note:
            o["status"], o["detail"] = "other-source", scope_note
        out.append(o)

    for d in sorted(index, key=lambda d: (d.get("module") or "", d["name"])):
        roots = {d["name"].split(".")[0], str(d.get("module") or "").split(".")[0]}
        mapped = ("its namespace is one the project maps to another paper"
                  if foreign & roots else None)
        file = (d.get("module") or "").replace(".", "/") + ".lean" if d.get("module") else None
        line = (d.get("range") or {}).get("line")
        doc = d.get("doc") or ""
        for m in REF.finditer(doc):
            obs(m.group(1), m.group(2), m.group(0), _context(doc, m.start(), m.end()),
                {"declaration": d["name"], "module": d.get("module"), "file": file,
                 "line": line, "where": "docstring"},
                mapped or _elsewhere(doc, m.start(), m.end()))
        for comp in d["name"].split("."):
            for m in NAME_REF.finditer(comp.lower()):
                obs(m.group(1), m.group(2).replace("_", "."), comp, d["name"],
                    {"declaration": d["name"], "module": d.get("module"), "file": file,
                     "line": line, "where": "name"}, mapped)
    for b in blocks:
        mapped = ("its module is in a namespace the project maps to another paper"
                  if b["module"].split(".")[0] in foreign else None)
        for m in REF.finditer(b["text"]):
            obs(m.group(1), m.group(2), m.group(0), _context(b["text"], m.start(), m.end()),
                {"declaration": None, "module": b["module"], "file": b["file"],
                 "line": b["line"] + b["text"].count("\n", 0, m.start()),
                 "where": "module docstring"},
                mapped or _elsewhere(b["text"], m.start(), m.end()))
    return out


def inventory(claims: list[dict], complete: bool, reason: str = "",
              sections: set[str] | None = None) -> dict:
    """The paper's numbering: each numbered statement's (kind, number) with its claim, whether
    the list is complete, and the section numbers when the compilation recorded them."""
    st: dict[tuple[str, str], list[str]] = {}
    for c in claims:
        r = claim_ref(c)
        if r:
            st.setdefault(r, []).append(c["id"])
    return {"statements": st, "complete": bool(complete and claims), "reason":
            reason if not (complete and claims) else "",
            "sections": sorted(sections) if sections is not None else None}


def _norm_ref(s: str) -> str | None:
    m = REF.fullmatch(s.strip())
    return printed(canonical(m.group(1)), m.group(2)) if m else None


def analyse(index: list[dict], claims: list[dict], inv: dict, blocks: list[dict] = (),
            foreign=frozenset(), retrieval=None, claim_text=None,
            version_map: dict | None = None) -> dict:
    """The references of the project to the paper, each with its status, and the project-level
    pattern. `retrieval` (a `retrieval.Retrieval` of `index`) and `claim_text` (a claim's
    printed statement) let an exact reference be compared with the content it cites.
    `version_map` (`{"source": …, "entries": [{"old": "Theorem 2.1", "new": ["Theorem 3.1"]}]}`)
    maps references of an earlier version of the paper to this one."""
    refs = find_references(index, list(blocks), foreign)
    st = inv["statements"]
    by_number: dict[str, list[tuple[str, str]]] = {}
    for (k, n) in st:
        by_number.setdefault(n, []).append((k, n))
    claim_by_id = {c["id"]: c for c in claims}
    for o in refs:
        if o.get("status"):
            continue
        k, n = o["kind"], o["number"]
        if k == "section":
            secs = inv.get("sections")
            if secs is None:
                o["status"], o["detail"] = "unchecked", ("the paper's section numbers are not "
                                                         "known in this build")
            elif n in secs:
                o["status"], o["detail"] = "exact", f"the paper has Section {n}"
            elif inv["complete"]:
                o["status"], o["detail"] = "absent", f"this version of the paper has no Section {n}"
            else:
                o["status"], o["detail"] = "unchecked", inv["reason"]
            continue
        if (k, n) in st:
            ids = st[(k, n)]
            o["status"] = "exact"
            o["paper"] = {"claims": ids, "reference": printed(k, n)}
            o["detail"] = f"the paper has {printed(k, n)}"
        elif n in by_number:
            others = [printed(kk, nn) for kk, nn in by_number[n]]
            o["status"] = "other-kind"
            o["paper"] = {"claims": [i for r in by_number[n] for i in st[r]],
                          "reference": ", ".join(others)}
            o["detail"] = (f"the paper's {n} is {' and '.join(others)}, not "
                           f"{'an' if k[0] in 'aeiou' else 'a'} {k}")
        elif not inv["complete"]:
            o["status"], o["detail"] = "unchecked", inv["reason"]
        else:
            o["status"] = "absent"
            o["detail"] = f"this version of the paper has no statement numbered {n}"
    if retrieval is not None and claim_text is not None:
        _content_check(refs, claims, claim_by_id, retrieval, claim_text)
    if version_map:
        _apply_map(refs, version_map, st)
    for o in refs:
        o["message"] = message(o)
    return {"references": refs, "pattern": pattern(refs, inv)}


def _content_check(refs, claims, claim_by_id, retrieval, claim_text):
    queries = {}
    for o in refs:
        if o["status"] != "exact" or not o["source"].get("declaration") or "paper" not in o:
            continue
        i = retrieval.by_name.get(o["source"]["declaration"])
        if i is None:
            continue
        cited = [claim_by_id[c] for c in o["paper"]["claims"] if c in claim_by_id]
        if not cited:
            continue
        sort = cited[0].get("scope")
        scores = []
        for c in claims:
            if c.get("scope") != sort or not claim_ref(c):
                continue
            if c["id"] not in queries:
                queries[c["id"]] = retrieval.query_counts(claim_text(c))
            scores.append((retrieval.similarity(queries[c["id"]], i), c))
        own = max((s for s, c in scores if c["id"] in o["paper"]["claims"]), default=0.0)
        best = max(((s, c) for s, c in scores if c["id"] not in o["paper"]["claims"]),
                   key=lambda x: (x[0], x[1]["id"]), default=None)
        o["content"] = {"cited": own}
        if best and best[0] >= CLOSER_MIN and best[0] >= own + CLOSER_MARGIN:
            o["content"].update(closer={"claim": best[1]["id"], "number": best[1].get("number"),
                                        "score": best[0]})
            o["stale_lead"] = True
            o["detail"] += (f", but the declaration's statement reads closer to "
                            f"{best[1].get('number')}")


def _apply_map(refs, version_map, st):
    targets: dict[str, list[str]] = {}
    for e in version_map.get("entries") or []:
        old = _norm_ref(str(e.get("old") or ""))
        new = e.get("new")
        new = [new] if isinstance(new, str) else list(new or [])
        if old:
            for n in new:
                nn = _norm_ref(str(n))
                if nn and nn not in targets.setdefault(old, []):
                    targets[old].append(nn)
    src = version_map.get("source")
    for o in refs:
        if o["status"] not in ("absent", "other-kind") and not o.get("stale_lead"):
            continue
        new = targets.get(o["reference"])
        if not new:
            continue
        if len(new) == 1:
            k, n = new[0].rsplit(" ", 1)
            ids = st.get((canonical(k), n), [])
            o["current"] = {"reference": new[0], "claims": ids, "source": src}
        else:
            o["current"] = {"ambiguous": new, "source": src}


def suspect(o: dict) -> bool:
    return o.get("status") in ("absent", "other-kind") or bool(o.get("stale_lead"))


def pattern(refs: list[dict], inv: dict) -> dict:
    """Counts of the references by status, and whether they show a pattern of numbering drift:
    at least `DRIFT_MIN` references that disagree with the paper, making at least `DRIFT_SHARE`
    of those checked."""
    count = lambda f: sum(1 for o in refs if f(o))
    checked = [o for o in refs if o["status"] in ("exact", "other-kind", "absent")]
    bad = [o for o in refs if suspect(o)]
    drift = len(bad) >= DRIFT_MIN and len(bad) >= DRIFT_SHARE * max(1, len(checked))
    return {"references": len(refs), "checked": len(checked),
            "exact": count(lambda o: o["status"] == "exact" and not o.get("stale_lead")),
            "reads_elsewhere": count(lambda o: o.get("stale_lead")),
            "other_kind": count(lambda o: o["status"] == "other-kind"),
            "absent": count(lambda o: o["status"] == "absent"),
            "unchecked": count(lambda o: o["status"] == "unchecked"),
            "other_source": count(lambda o: o["status"] == "other-source"),
            "drift": drift, "examples": [o["id"] for o in bad[:5]],
            "inventory": {"complete": inv["complete"], "reason": inv["reason"],
                          "statements": len(inv["statements"]),
                          "sections": len(inv["sections"]) if inv.get("sections") is not None
                          else None}}


def where(o: dict) -> str:
    s = o["source"]
    loc = f"{s['file']}:{s['line']}" if s.get("file") and s.get("line") else (s.get("file") or "")
    what = {"docstring": f"the docstring of {s.get('declaration')}",
            "name": f"the name {s.get('declaration')}",
            "module docstring": f"the docstring of module {s.get('module')}"}[s["where"]]
    return f"{what} ({loc})" if loc else what


def message(o: dict) -> str:
    """One line for the terminal."""
    out = f"{where(o)} cites {o['reference']}: {o['detail']}"
    cur = o.get("current")
    if cur:
        out += (f"; the version map gives {cur['reference']}" if cur.get("reference")
                else f"; the version map gives several: {', '.join(cur['ambiguous'])}")
    return out


def drift_note(p: dict, refs: list[dict], suggestions: bool = True) -> str | None:
    """The project-level note when the references show a pattern; `suggestions` when the build
    makes suggestions, whose ranking the note then explains."""
    if not p["drift"]:
        return None
    parts = [f"{p['absent']} cite numbers this version does not have" if p["absent"] else "",
             f"{p['other_kind']} name another kind of statement" if p["other_kind"] else "",
             f"{p['reads_elsewhere']} read closer to another statement" if p["reads_elsewhere"]
             else ""]
    bad = [o for o in refs if o["id"] in p["examples"]]
    ex = "; ".join(f"{o['reference']} in {where(o)}" for o in bad[:3])
    return (f"the Lean's references to the paper appear to follow another version of it: "
            f"{p['absent'] + p['other_kind'] + p['reads_elsewhere']} of the {p['checked']} "
            f"references checked disagree with this version ({', '.join(x for x in parts if x)})"
            f", for example {ex}."
            + (" Suggestions rank statement content above these numbers." if suggestions else ""))


def reliability(numbering: dict | None, decl: str, reference: str) -> tuple[float, str | None]:
    """How much a docstring's citation of `reference` by `decl` counts in a suggestion (1, or
    less when it is a possibly stale lead), and why it counts less."""
    if not numbering:
        return 1.0, None
    for o in numbering["references"]:
        if o["source"].get("declaration") == decl and o["reference"] == reference \
                and o.get("stale_lead"):
            return 0.4, (f"a possibly stale number: its statement reads closer to "
                         f"{o['content']['closer']['number']}")
    if numbering["pattern"]["drift"]:
        return 0.4, ("a possibly stale number: the Lean's references appear to follow another "
                     "version of the paper")
    return 1.0, None
