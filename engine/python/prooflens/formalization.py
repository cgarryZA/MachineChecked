"""Reading a project's `formalization.yaml` (the mathlib-initiative standard).

The file is the project's own account of itself: its sources, its main results, how it was made,
its review status, and an `alignment` between the source's statements and Lean declarations. The
alignment is free-form in the standard; the shape read here is its suggested one,
`statements: [{source, lean, module, status}]`, with `lean` a name or a list of names.

A mapping read from the file is a link the project's authors declared, shown as such; the
file's review status is the project's own description of its review, shown as such. Neither
changes what Lean is checked to establish.
"""

from __future__ import annotations

import re
from pathlib import Path

NAMES = ("formalization.yaml", "formalization.yml")
KINDS = ("theorem", "lemma", "proposition", "corollary", "definition", "remark", "example",
         "conjecture", "claim", "assumption", "hypothesis", "convention")
REF = re.compile(r"\b(" + "|".join(KINDS) + r")\s+((?:[A-Z](?:\.\d+)+|[A-Z]?\d+(?:\.\d+)*)[a-z]?)",
                 re.I)


def find(root: Path) -> Path | None:
    return next((root / n for n in NAMES if (root / n).is_file()), None)


def load(root: Path) -> dict | None:
    """The project's formalization.yaml, parsed, or None. A file that cannot be read is
    reported as `{"error": ...}`."""
    p = find(root)
    if p is None:
        return None
    try:
        import yaml
    except ImportError:
        return {"error": "formalization.yaml found, but PyYAML is not installed"}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:  # malformed YAML is the file's problem, not a crash
        return {"error": f"formalization.yaml could not be read: {e}"}
    return data if isinstance(data, dict) else {"error": "formalization.yaml is not a mapping"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^\w]+", (s or "").lower()) if len(t) > 2}


def statements(fy: dict) -> list[dict]:
    """The alignment's statements in the suggested shape: each with the claim it names
    (`kind`, `number`), the words that say which source it is in, and its Lean names."""
    al = fy.get("alignment") if isinstance(fy, dict) else None
    rows = al.get("statements") if isinstance(al, dict) else al if isinstance(al, list) else None
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        lean = r.get("lean") or r.get("declaration") or r.get("declarations")
        names = [lean] if isinstance(lean, str) else [n for n in lean or [] if isinstance(n, str)]
        src = str(r.get("source") or "")
        m = REF.search(src)
        if not names or not m:
            continue
        rest = src[m.end():]
        module = r.get("module") if isinstance(r.get("module"), str) else None
        out.append({"source": src, "kind": m.group(1).lower(), "number": m.group(2),
                    "hint": _tokens(rest), "lean": names, "status": r.get("status"),
                    "module": module})
    return out


def formalized_sources(fy: dict) -> list[dict]:
    return [s for s in fy.get("sources") or [] if isinstance(s, dict)
            and s.get("relationship", "formalizes") == "formalizes"]


def links_for(fy: dict, claim_kind: str, claim_number: str, paper_title: str) -> list[dict]:
    """The alignment's statements that name this claim of this paper. When the file formalizes
    several sources, the paper is the source whose title it shares most words with, and a
    statement must name it by a word only that source's title has ("(Euler)")."""
    num = claim_number.split()[-1] if claim_number else ""
    rows = [st for st in statements(fy) if st["kind"] == claim_kind.lower()
            and st["number"] == num]
    srcs = [_tokens(s.get("title", "")) for s in formalized_sources(fy)]
    if len(srcs) <= 1 or not rows:
        return rows
    title = _tokens(paper_title)
    best = max(range(len(srcs)), key=lambda i: len(srcs[i] & title))
    if not srcs[best] & title:
        return []
    own = srcs[best] - set().union(*(t for i, t in enumerate(srcs) if i != best))
    return [st for st in rows if st["hint"] & own]


def summary(fy: dict | None) -> dict | None:
    """What the reader shows about the file: the project's own review status and methods."""
    if not fy:
        return None
    if "error" in fy:
        return {"error": fy["error"]}
    rv = fy.get("review") if isinstance(fy.get("review"), dict) else {}
    auto = fy.get("automation") if isinstance(fy.get("automation"), dict) else {}
    return {"review_status": rv.get("status"), "reviewers": rv.get("reviewers") or [],
            "methods": [m.get("method") for m in auto.get("methods") or []
                        if isinstance(m, dict) and m.get("method")],
            "sources": [{"title": s.get("title"), "id": s.get("id")}
                        for s in formalized_sources(fy)],
            "version": fy.get("version")}
