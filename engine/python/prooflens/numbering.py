"""References to the paper's numbered statements in the Lean, checked against the paper (#127).

A formalisation written against an earlier version of a paper keeps that version's numbers in
its docstrings, names and comments: `/-- Theorem 2.1: … -/`, `theorem lemma_3_4`, `-- by Lemma
2.2`. This module finds each such reference (with its exact text, its declaration or module,
file and line) and compares it with the numbering of the paper at the revision the audit reads:

- `exact`: the paper has a statement of that kind and number;
- `other-kind`: the number exists, under another kind (the docstring says Lemma 2.3, the
  paper's 2.3 is a Proposition);
- `absent`: the paper, whose numbering is completely known, has no statement with that number;
- `unchecked`: the paper's numbering is not completely known in this build (a PDF read by its
  headings, a paper that did not compile), so the reference is neither confirmed nor refuted;
- `other-source`: the reference is to another work (`Theorem 3 of [AB]`, `Gauss's Lemma 4.22`,
  `Hardy–Wright, *An Introduction*, Ch. IV, Prop. 4.7`) or sits in a namespace the project
  maps to another paper; it says nothing about this paper.

A number whose digits run together in a name (`lem41_bound`, or `Assumption22` written as an
identifier in a docstring) is read in every way the paper could mean it (`4.1`, `41`): the
paper's numbering decides which, and the reference disagrees with the paper only when no
reading names a statement of its kind. A number written out in prose (`Lemma 41`) is read as
written.

A reference names either what its declaration states (a declaration's name, a docstring's
opening citation) or something the statement relies on (`under Assumption 2.2` later in the
docstring). An exact reference of the first sort whose declaration's statement reads much
closer to another statement of the paper (`retrieval.py`) keeps its status and is marked as a
possibly stale lead, with the closer statement named; a reference of the second sort is checked
only for the existence and kind of the statement it cites.

An ordinary comment (`--` or `/- … -/`) belongs to the declaration whose source it lies in,
or that starts on the line after it ends, and otherwise to its module. A comment just before
a declaration that opens with a reference names what the declaration states, as a docstring's
opening citation does; any other reference in a comment names something cited.

When several references disagree with the paper, in number, in proportion and in more than one
declaration or module, the project-level pattern says the Lean appears to follow another
version of the paper; one stray reference, or one place holding several, is reported alone and
never read as a version change. An explicit map between
two versions of the paper resolves a renumbered reference when it names one current statement,
and keeps every candidate when it names several.

With several papers in one configuration, each reference is attributed to one paper
(`attribute`) and checked against that paper's numbering; one that cannot be attributed is
`unchecked`, with the reason (`combine` gathers the papers' references and patterns).

A suggestion's cited number rests on these references (`citation`): a docstring's number that
names another work, a section or a statement of another kind is no lead to the claim, and one
that is a possibly stale lead counts less and says so. This changes what suggestions say and
how much a cited number counts; it never creates a link or changes a status.
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
                 r"Subsection|Section|Sec|§)(\.?[ \t~]*)(\d+(?:\.\d+)*)(?![\w]|\.\d)", re.I)
NAME_REF = re.compile(r"(?:^|_)(theorem|thm|lemma|lem|proposition|prop|corollary|cor|"
                      r"definition|defn|def|section|sec)_?(\d+(?:_\d+)*)(?=_|$)")
# Just after a number, a bracket or `\cite` (and `\citet`, `\citep`, …) cites another work
# (`Lemma 9 [AB]`, `Lemma 9~\cite{AB}`); other citations follow "of", "in" or "from"
# (`_AFTER_WORD`).
_BRACKET_AFTER = re.compile(r"[\s~]*(?:\[|\\cite)")
_AFTER_WORD = re.compile(r"\s*(?:,\s*)?(?:of|in|from)[\s~]+")
# What, after that word, cites a work by itself: a bracket, `\cite`, an arXiv identifier, a
# reference word with its label (`ref. [3]`, `Refs. 3, 4`, `reference \cite{AB}`; `in refined
# form` and `in reference to Lemma 2` cite none), or an emphasised or quoted title (`of *An
# Introduction*`, `of \emph{Elements}`).
_TITLE = r"[*_“\"]|\\(?:emph|textit)\s*\{"
_CITATION = re.compile(r"\[|\\cite|arXiv|[Rr]ef(?:s|erences?)?\b\.?[\s~]*(?:\[|\\cite|\d)|"
                       + _TITLE)
# After that word, a capitalised word (group 1), with "the" before it or not: a part of this
# paper or of its formalisation (`in Section 7`, `_OWN_PARTS`), this paper or another one (`of
# the Paper`, `of Paper B`), the first of a work's authors (`in Hardy and Wright`), or the start
# of a mathematical term (`in Hilbert spaces`).
_CAPITALISED = re.compile(r"(?:the\s+)?([A-Z][\w\-–]*)")
# Another author's name after one (`Hardy and Wright`, `Hardy, Littlewood and Pólya`,
# `Revuz & Yor`), as group 1.
_MORE_NAMES = re.compile(r"\s*(?:,\s*(?:and\s+)?|and\s+|&\s*)([A-Z][\w\-–]*)")
# What follows authors' names in a citation: `et al.`, a year (`(1979)`, `, 1979`), a bracket
# or `\cite`, a title after a comma, a colon or the possessive (`Hardy, *An Introduction*`,
# `Serre's *A Course in Arithmetic*`), or the possessive of a work (`Serre's book`).
_AUTHORS_THEN = re.compile(
    r"\s*,?\s*(?:et\s+al\b|\(?(?:1[5-9]|20)\d\d[a-z]?\b|\[|\\cite)"
    rf"|(?:['’]s)?\s*[,:]?\s*(?:{_TITLE})"
    r"|['’]s\s+(?:book|monograph|notes|lectures|paper|article|survey|thesis|treatise|text"
    r"|textbook)\b")
# The label or labels of a part after its word (`Section 7.2`, `Appendix A`, `Part II`,
# `Lean 4`, `Sections 4 and 5`, `Eq. (4)`).
_LABEL = r"(?:[IVXLCDM]+|[A-Z]|\d+)(?:\.\d+)*\b"
_ONE_LABEL = rf"(?:{_LABEL}|\(\s*{_LABEL}\s*\))"
_PART_LABEL = re.compile(rf"\.?[ \t~]*(?:{_ONE_LABEL}(?:\s*(?:,|and|or|–|--?)\s*{_ONE_LABEL})*)?")
# Just before a number: an open citation bracket (`[AB, Lemma 9`), `et al.`, or the possessive
# of a bracketed citation or of `et al.` (`[AB]'s Lemma 9`, `Smith et al.'s Theorem 3`).
_ELSEWHERE_BEFORE = re.compile(r"\[[^\]]*$|\bet al\.?\s*,?\s*$"
                               r"|(?:\bet al\.?|\])['’]s[\s~*_]*$")
# The bracketed citation just before a number, with its key (group 1): the bracket it is cited
# in (`[U, Lemma 2.1]`, or `[A, Lemma 3; U, Lemma 2.1]` for the second) or its possessive
# (`[U]'s Lemma 2.1`).
_KEY_BEFORE = re.compile(r"\[(?:[^\]]*;)?\s*([^\[\],;]+?)\s*(?:,[^\];]*|\]['’]s[\s~*_]*)$")
# A `\cite` command (`\cite`, `\citet`, `\citep`, …) with its notes and its keys (group 1):
# `\cite{U}`, `\cite[Lemma 2.1]{U}`, `\cite[see][Lemma 2.1]{U}`.
_CITE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\s*\[[^\]]*\])*\s*\{([^}]*)\}")
# An author's possessive just before the number (`Gauss's Lemma 4.22`, `Revuz–Yor's`,
# `Gauss' Lemma`): a capitalised word of at least two letters, not one naming this paper, a
# part of it or its formalisation (`Lean's Theorem 2.1`).
_POSSESSIVE = re.compile(r"(?<![\w'’.\-–])([^\W\d_][\w\-–]+)(?:['’]s|(?<=s)['’])[\s~*_]*$")
# Words naming a part of this paper or of its formalisation, its statements among them: after a
# number they name no other work (`Lemma 7.7 in Section 7`, `Theorem 9.9 in Lean`, `Theorem 2.1
# in Lemma 3.2`, `Theorem 9.9 in Figure 2`, `in Proof of Lemma 3`).
_OWN_PARTS = set(KINDS) | {"sections", "chapter", "chapters", "ch", "chap", "appendix",
                           "appendices", "app", "supplement", "part", "parts", "step", "lean",
                           "mathlib", "figure", "figures", "fig", "figs", "table", "tables", "tab",
                           "equation", "equations", "eq", "eqs", "proof", "proofs", "case",
                           "cases", "footnote"}
# Words naming a paper or its authors. After a number, one with a label names another paper
# (`Theorem 2.1 of Paper B`), one without names this one (`of the Paper`).
_PAPER_WORDS = {"paper", "article", "manuscript", "note", "preprint", "thesis", "author",
                "authors"}
# A possessive of any of these words is no author's (`the paper's Lemma 2.1`, `Lean's Theorem
# 2.1`).
_OWN_WORDS = _OWN_PARTS | _PAPER_WORDS
# A chapter after a comma just before the number, as a citation of a book gives it
# (`Hardy–Wright, *An Introduction*, Ch. IV, Prop. 4.7`); a chapter in prose (`In Chapter 4,
# Lemma 4.2`) is not one.
_CHAPTER = re.compile(r",[\s~*_]*(?:Ch|Chap|Chapter)\b\.?[\s~]*(?:[IVXLCDM]+|\d+(?:\.\d+)*)\b"
                      r"[\s~*_]*[,;:]?\s*$")

DRIFT_MIN = 3           # disagreeing references needed before a pattern is reported
DRIFT_SHARE = 0.3       # ... and their share of the references checked
DRIFT_PLACES = 2        # ... and the declarations or modules they are in
STALE_FACTOR = 0.4      # how much a possibly stale lead counts in a suggestion
CLOSER_MIN = 0.4        # an exact reference reads elsewhere when another statement is at
CLOSER_MARGIN = 0.15    # least this similar to the declaration, and this much more than the cited
RUN_MAX = 4             # run-together digits read in every split up to this many digits
# What may precede a docstring's opening citation: whitespace and Markdown emphasis.
_OPENING = re.compile(r"[\s*_#>`]*")


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


def comment_blocks(root: Path | None, modules, index=()) -> list[dict]:
    """The ordinary comments (`-- …`, `/- … -/`) of the project's modules, each with its file,
    the line it begins on and the declaration it belongs to (`_owner`); consecutive lines that
    hold only a `--` comment are one comment. Doc comments and module docstrings are read
    elsewhere; a string or character literal holds no comment."""
    out = []
    if root is None:
        return out
    spans: dict[str, list[tuple[int, int, str]]] = {}
    for d in index:
        r = d.get("range") or {}
        if d.get("module") and r.get("line"):
            spans.setdefault(d["module"], []).append(
                (r["line"], r.get("end_line") or r["line"], d["name"]))
    for m in sorted(set(modules)):
        rel = m.replace(".", "/") + ".lean"
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        merged: list[dict] = []
        pos, line = 0, 1
        for kind, start, body, end in _comments(text):
            line += text.count("\n", pos, start)
            pos = start
            last = line + text.count("\n", start, end)
            alone = kind == "line" and not text[text.rfind("\n", 0, start) + 1:start].strip()
            prev = merged[-1] if merged else None
            if alone and prev and prev["alone"] and prev["end"] == line - 1:
                prev["text"] += "\n" + text[body:end]
                prev["end"] = line
                continue
            merged.append({"text": text[body:end], "line": line, "end": last, "alone": alone})
        for c in merged:
            decl, before = _owner(spans.get(m, []), c["line"], c["end"])
            out.append({"module": m, "file": rel, "line": c["line"], "text": c["text"],
                        "where": "comment", "declaration": decl, "before": before})
    return out


# A string, a character literal, a line comment or the start of a block comment.
_LEX = re.compile(r"\"|'|--|/-")
_STRING = re.compile(r"\"(?:\\.|[^\"\\])*\"", re.S)
_CHAR = re.compile(r"'(?:\\(?:u\{[0-9a-fA-F]+\}|x[0-9a-fA-F]{2}|.)|[^\\'\n])'")
_BLOCK = re.compile(r"/-|-/")


def _comments(text: str):
    """The comments of a Lean source other than doc comments (`/--`) and module docstrings
    (`/-!`): `(kind, start, body start, body end)` for each `--` line comment and each
    outermost `/- … -/` block comment, block comments nesting as Lean's do."""
    i, n = 0, len(text)
    while (m := _LEX.search(text, i)) is not None:
        t, s = m.group(), m.start()
        if t == '"':
            e = _STRING.match(text, s)
            i = e.end() if e else n
        elif t == "'":
            # A prime ends an identifier (`h'`); elsewhere it opens a character literal.
            prev = text[s - 1] if s else ""
            c = None if prev.isalnum() or prev in "_'!?" else _CHAR.match(text, s)
            i = c.end() if c else s + 1
        elif t == "--":
            e = text.find("\n", s)
            i = n if e < 0 else e
            yield "line", s, s + 2, i
        else:
            depth, i = 0, n
            for b in _BLOCK.finditer(text, s):
                depth += 1 if b.group() == "/-" else -1
                if depth == 0:
                    i = b.end()
                    break
            if text[s + 2:s + 3] not in ("-", "!"):
                yield "block", s, s + 2, max(s + 2, i - 2 if depth == 0 else n)


def _owner(spans: list[tuple[int, int, str]], line: int, end: int) -> tuple[str | None, bool]:
    """The declaration a comment on lines `line`–`end` belongs to: the innermost whose source
    holds it, else the one starting on the next line (with True); None when neither is."""
    inside = [s for s in spans if s[0] <= line and end <= s[1]]
    if inside:
        return min(inside, key=lambda s: (s[1] - s[0], s[2]))[2], False
    after = [s for s in spans if s[0] == end + 1]
    if after:
        return min(after, key=lambda s: (s[1] - s[0], s[2]))[2], True
    return None, False


ANOTHER_WORK = "it refers to another work"


def _elsewhere(text: str, start: int, end: int) -> str | None:
    before = text[max(0, start - 60):start]
    if _cited_after(text[end:end + 60]) or _ELSEWHERE_BEFORE.search(before) \
            or _CHAPTER.search(before) or _authors(before):
        return ANOTHER_WORK
    return None


def _cited_after(after: str) -> bool:
    """Whether the text just after a number cites another work: a bracket or `\\cite`, or,
    after "of", "in" or "from", a citation, a title, another paper (`of Paper B`) or a work's
    authors (`_by_authors`). A part of this paper or of its formalisation (`in Section 7`, `in
    Figure 2`, `in Lean`), or any part given by its label (`in Volume 2`), does not, unless a
    citation follows it (`in Section 4 of [AB]`, `in Volume 2 of [B]`); nor does this paper
    (`of the Paper`) or a mathematical term (`in Hilbert spaces`)."""
    while not _BRACKET_AFTER.match(after):
        m = _AFTER_WORD.match(after)
        if not m:
            return False
        after = after[m.end():]
        if _CITATION.match(after):
            return True
        w = _CAPITALISED.match(after)
        if not w:
            return False
        word, after = w.group(1), after[w.end():]
        if word.lower() in _PAPER_WORDS:
            return re.match(rf"[ \t~]+{_LABEL}", after) is not None
        if word.lower() not in _OWN_PARTS:
            if _by_authors(word, after):
                return True
            if not re.match(rf"\.?[ \t~]+{_ONE_LABEL}", after):
                return False
        after = after[_PART_LABEL.match(after).end():]
    return True


def _by_authors(first: str, after: str) -> bool:
    """Whether a capitalised word after "of", "in" or "from", with the text `after` it, names a
    work by its authors: names followed by `et al.`, a year, a citation or a title (`Hardy
    (1940)`, `Serre's book`), or several names that no lowercase word follows (`Hardy and
    Wright`, `Hardy–Wright`). One name alone (`in Rudin`) is not enough, and a lowercase word
    after the names makes them a mathematical term (`in Hilbert spaces`, `in Hilbert and
    Banach spaces`, `in Navier–Stokes equations`)."""
    several = re.search(r"[\-–][A-Z]", first) is not None
    while (m := _MORE_NAMES.match(after)) and m.group(1).lower() not in _OWN_WORDS:
        several, after = True, after[m.end():]
    if _AUTHORS_THEN.match(after):
        return True
    return several and not re.match(r"[\s~]+[a-z]", after)


def _authors(before: str) -> bool:
    """Whether the text just before a number ends with an author's possessive."""
    m = _POSSESSIVE.search(before)
    return bool(m) and m.group(1)[0].isupper() and m.group(1).lower() not in _OWN_WORDS


def readings(digits: str) -> list[str]:
    """Every number that run-together digits could mean, the most dotted first: `41` gives
    `4.1` and `41`; `312` gives `3.1.2`, `3.12`, `31.2` and `312`."""
    if len(digits) < 2 or len(digits) > RUN_MAX or not digits.isdigit():
        return [digits]
    out = []
    for mask in range(2 ** (len(digits) - 1) - 1, -1, -1):
        n = digits[0]
        for i, ch in enumerate(digits[1:]):
            n += ("." if mask >> (len(digits) - 2 - i) & 1 else "") + ch
        out.append(n)
    return sorted(out, key=lambda n: -n.count("."))


def _context(text: str, start: int, end: int) -> tuple[str, int]:
    """The text around a reference, with its whitespace collapsed, and where the reference
    starts in it."""
    a, b = max(0, start - 60), min(len(text), end + 60)
    lead = ("…" if a else "") + re.sub(r"\s+", " ", text[a:start]).lstrip()
    return (("…" if a else "") + re.sub(r"\s+", " ", text[a:b]).strip()
            + ("…" if b < len(text) else "")), len(lead)


def find_references(index: list[dict], blocks: list[dict], foreign=frozenset()) -> list[dict]:
    """Every reference to a numbered statement or section in the project's declaration
    docstrings, declaration names, module docstrings and comments (`blocks`: those of
    `module_doc_blocks` and `comment_blocks`), with its source, its context, where its text
    starts in the context (`at`) and an id that no other reference has."""
    out = []
    foreign = set(foreign)
    seen: dict[str, int] = {}

    def obs(kind_word, number, exact, context, source, scope_note, role, run=False):
        kind = canonical(kind_word)
        key = "\n".join([source.get("declaration") or "", source.get("file") or "",
                         str(source.get("line")), source["where"], exact])
        # The same text again in the same place (`Lemma 7.7, and again Lemma 7.7.`) is told
        # apart by which occurrence it is; the first keeps the id it would have alone.
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key += f"\n{seen[key]}"
        o = {"id": "ref:" + hashlib.sha256(key.encode()).hexdigest()[:12],
             "reference": printed(kind, number), "kind": kind, "number": number,
             "text": exact, "context": context[0], "at": context[1], "source": source,
             "role": role}
        if run and len(readings(number)) > 1:
            o["readings"] = readings(number)
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
        for i, m in enumerate(REF.finditer(doc)):
            # The docstring's opening citation names what the declaration states; a later one
            # names something the statement relies on.
            opening = i == 0 and _OPENING.fullmatch(doc[:m.start()]) is not None
            obs(m.group(1), m.group(3), m.group(0), _context(doc, m.start(), m.end()),
                {"declaration": d["name"], "module": d.get("module"), "file": file,
                 "line": line, "where": "docstring"},
                mapped or _elsewhere(doc, m.start(), m.end()),
                "statement" if opening else "cited", run=not m.group(2))
        at = 0
        for comp in d["name"].split("."):
            for m in NAME_REF.finditer(comp.lower()):
                obs(m.group(1), m.group(2).replace("_", "."), comp, (d["name"], at),
                    {"declaration": d["name"], "module": d.get("module"), "file": file,
                     "line": line, "where": "name"}, mapped, "statement", run=True)
            at += len(comp) + 1
    for b in blocks:
        if b.get("where") == "comment":
            _comment_references(b, foreign, obs)
            continue
        mapped = ("its module is in a namespace the project maps to another paper"
                  if b["module"].split(".")[0] in foreign else None)
        for m in REF.finditer(b["text"]):
            obs(m.group(1), m.group(3), m.group(0), _context(b["text"], m.start(), m.end()),
                {"declaration": None, "module": b["module"], "file": b["file"],
                 "line": b["line"] + b["text"].count("\n", 0, m.start()),
                 "where": "module docstring"},
                mapped or _elsewhere(b["text"], m.start(), m.end()), "cited",
                run=not m.group(2))
    return out


def _comment_references(b: dict, foreign: set[str], obs) -> None:
    """The references of one comment (`comment_blocks`), given to `obs`. A kind written
    against its number (`lemma21`) is code, not a reference, in a comment."""
    decl = b.get("declaration")
    roots = {b["module"].split(".")[0]} | ({decl.split(".")[0]} if decl else set())
    mapped = (f"its {'declaration' if decl else 'module'} is in a namespace the project maps "
              "to another paper" if foreign & roots else None)
    text = b["text"]
    first = True
    for m in REF.finditer(text):
        if not m.group(2):
            continue
        # A comment just before a declaration that opens with a reference names what the
        # declaration states, as a docstring's opening citation does.
        opening = first and b.get("before") and _OPENING.fullmatch(text[:m.start()]) is not None
        first = False
        obs(m.group(1), m.group(3), m.group(0), _context(text, m.start(), m.end()),
            {"declaration": decl, "module": b["module"], "file": b["file"],
             "line": b["line"] + text.count("\n", 0, m.start()), "where": "comment"},
            mapped or _elsewhere(text, m.start(), m.end()),
            "statement" if opening else "cited")


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
    return printed(canonical(m.group(1)), m.group(3)) if m else None


def analyse(index: list[dict], claims: list[dict], inv: dict, blocks: list[dict] = (),
            foreign=frozenset(), retrieval=None, claim_text=None,
            version_map: dict | None = None, refs: list[dict] | None = None) -> dict:
    """The references of the project to the paper, each with its status, and the project-level
    pattern. `retrieval` (a `retrieval.Retrieval` of `index`) and `claim_text` (a claim's
    printed statement) let an exact reference be compared with the content it cites.
    `version_map` (`{"source": …, "entries": [{"old": "Theorem 2.1", "new": ["Theorem 3.1"]}]}`)
    maps references of an earlier version of the paper to this one. `refs`, when given, are the
    references to check (those `attribute` gives this paper), instead of all of the project's."""
    if refs is None:
        refs = find_references(index, list(blocks), foreign)
    st = inv["statements"]
    by_number: dict[str, list[tuple[str, str]]] = {}
    for (k, n) in st:
        by_number.setdefault(n, []).append((k, n))
    claim_by_id = {c["id"]: c for c in claims}
    for o in refs:
        if o.get("status"):
            continue
        if o.get("readings"):
            _check_readings(o, inv, by_number)
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
            # The paper may print one number twice (its numbering restarts in a part, say):
            # the reference names one of them, and does not say which.
            o["detail"] = (f"the paper has {printed(k, n)}" if len(ids) == 1 else
                           f"the paper has {len(ids)} statements printed {printed(k, n)}, and "
                           "the reference does not say which")
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


def _either(ns: list[str]) -> str:
    return ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " or " + ns[-1]


def _check_readings(o: dict, inv: dict, by_number: dict) -> None:
    """The status of a reference whose digits run together (`lem41`): the reading the paper
    has a statement of its kind for, when there is exactly one."""
    k, rs, st = o["kind"], o["readings"], inv["statements"]
    shown, digits = _either(rs), o["number"]
    if k == "section":
        secs = inv.get("sections")
        if secs is None:
            o["status"], o["detail"] = "unchecked", ("the paper's section numbers are not "
                                                     "known in this build")
            return
        hits = [r for r in rs if r in secs]
    else:
        hits = [r for r in rs if (k, r) in st]
    if len(hits) == 1:
        o["number"], o["reference"] = hits[0], printed(k, hits[0])
        o["status"] = "exact"
        if k != "section":
            o["paper"] = {"claims": st[(k, hits[0])], "reference": o["reference"]}
        o["detail"] = (f"the paper has {o['reference']} (the run-together {digits} could mean "
                       f"{shown}; the paper has only {hits[0]})")
        return
    if hits:
        o["status"] = "unchecked"
        o["detail"] = (f"the run-together {digits} could mean "
                       f"{_either([printed(k, r) for r in hits])}, all of which the paper has")
        return
    others = [] if k == "section" else [r for r in rs if r in by_number]
    if others:
        names = [printed(kk, nn) for r in others for kk, nn in by_number[r]]
        if len(others) == 1:
            o["number"] = others[0]
            o["reference"] = printed(k, others[0])
        o["status"] = "other-kind"
        o["paper"] = {"claims": [i for r in others for x in by_number[r] for i in st[x]],
                      "reference": ", ".join(names)}
        o["detail"] = (f"the run-together {digits} could mean {shown}; the paper's "
                       f"{_either(others)} is {' and '.join(names)}, not "
                       f"{'an' if k[0] in 'aeiou' else 'a'} {k}")
    elif not inv["complete"]:
        o["status"], o["detail"] = "unchecked", inv["reason"]
    elif k == "section":
        o["status"] = "absent"
        o["detail"] = f"this version of the paper has no Section {shown}"
    else:
        o["status"] = "absent"
        o["detail"] = f"this version of the paper has no statement numbered {shown}"


def _content_check(refs, claims, claim_by_id, retrieval, claim_text):
    queries = {}
    for o in refs:
        # Only a reference that names what its declaration states is compared with the
        # declaration's content: a docstring's citation of what the statement relies on is not.
        if o["status"] != "exact" or not o["source"].get("declaration") or "paper" not in o \
                or o.get("role") == "cited":
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
    """Give each reference that disagrees with the paper the counterpart the map names for its
    number: `reference` for one, `ambiguous` for several, or `none` when the map's only entries
    for it name no counterpart (a claim the later version does not have). An entry's `match`
    (the map's class and basis, `version_map.numbers`) is kept as `matches`."""
    targets: dict[str, list[str]] = {}
    matches: dict[str, list[dict]] = {}
    for e in version_map.get("entries") or []:
        old = _norm_ref(str(e.get("old") or ""))
        new = e.get("new")
        new = [new] if isinstance(new, str) else list(new or [])
        if old:
            targets.setdefault(old, [])
            if e.get("match"):
                matches.setdefault(old, []).append(e["match"])
            for n in new:
                nn = _norm_ref(str(n))
                if nn and nn not in targets[old]:
                    targets[old].append(nn)
    src = version_map.get("source")
    for o in refs:
        if o["status"] not in ("absent", "other-kind") and not o.get("stale_lead"):
            continue
        if o["reference"] not in targets:
            continue
        new = targets[o["reference"]]
        why = {"matches": matches[o["reference"]]} if o["reference"] in matches else {}
        if len(new) == 1:
            k, n = new[0].rsplit(" ", 1)
            ids = st.get((canonical(k), n), [])
            o["current"] = {"reference": new[0], "claims": ids, "source": src, **why}
            # A counterpart the map only proposes (its claim is ambiguous) is said to be one.
            if why and all(m.get("class") == "ambiguous" for m in why["matches"]):
                o["current"]["proposed"] = True
        elif new:
            o["current"] = {"ambiguous": new, "source": src, **why}
        elif why:
            o["current"] = {"none": True, "source": src, **why}


def resolve(refs: list[dict], version_map: dict, statements: dict) -> list[dict]:
    """The references with the counterpart a version map names for each one that disagrees
    with the paper (`_apply_map`), and their messages again. `statements` is the paper's
    numbering (`inventory(...)["statements"]`). The references keep their statuses."""
    _apply_map(refs, version_map, statements)
    for o in refs:
        o["message"] = message(o)
    return refs


def suspect(o: dict) -> bool:
    return o.get("status") in ("absent", "other-kind") or bool(o.get("stale_lead"))


def place(o: dict) -> tuple:
    """The declaration a reference is in (its docstring, name or a comment on it), or else its
    module (the module's docstring or a comment in it)."""
    s = o["source"]
    return ("declaration", s["declaration"]) if s.get("declaration") else ("module", s.get("module"))


def pattern(refs: list[dict], inv: dict) -> dict:
    """Counts of the references by status, and whether they show a pattern of numbering drift:
    at least `DRIFT_MIN` references that disagree with the paper, making at least `DRIFT_SHARE`
    of those checked, in at least `DRIFT_PLACES` declarations or modules (`places`). The
    examples are the first disagreeing reference of each place, then the others."""
    count = lambda f: sum(1 for o in refs if f(o))
    checked = [o for o in refs if o["status"] in ("exact", "other-kind", "absent")]
    bad = [o for o in refs if suspect(o)]
    places = {place(o) for o in bad}
    drift = len(bad) >= DRIFT_MIN and len(bad) >= DRIFT_SHARE * max(1, len(checked)) \
        and len(places) >= DRIFT_PLACES
    seen, firsts = set(), []
    for o in bad:
        if place(o) not in seen:
            seen.add(place(o))
            firsts.append(o)
    shown = {id(o) for o in firsts}
    examples = firsts + [o for o in bad if id(o) not in shown]
    return {"references": len(refs), "checked": len(checked), "places": len(places),
            "exact": count(lambda o: o["status"] == "exact" and not o.get("stale_lead")),
            "reads_elsewhere": count(lambda o: o.get("stale_lead")),
            "other_kind": count(lambda o: o["status"] == "other-kind"),
            "absent": count(lambda o: o["status"] == "absent"),
            "unchecked": count(lambda o: o["status"] == "unchecked"),
            "other_source": count(lambda o: o["status"] == "other-source"),
            "drift": drift, "examples": [o["id"] for o in examples[:5]],
            "inventory": {"complete": inv["complete"], "reason": inv["reason"],
                          "statements": len(inv["statements"]),
                          "sections": len(inv["sections"]) if inv.get("sections") is not None
                          else None}}


def where(o: dict) -> str:
    s = o["source"]
    loc = f"{s['file']}:{s['line']}" if s.get("file") and s.get("line") else (s.get("file") or "")
    what = {"docstring": f"the docstring of {s.get('declaration')}",
            "name": f"the name {s.get('declaration')}",
            "module docstring": f"the docstring of module {s.get('module')}",
            "comment": f"a comment on {s.get('declaration')}" if s.get("declaration")
            else f"a comment in module {s.get('module')}"}[s["where"]]
    return f"{what} ({loc})" if loc else what


def message(o: dict) -> str:
    """One line for the terminal."""
    of = f" of paper {o['attributed']}" if o.get("attributed") else ""
    out = f"{where(o)} cites {o['reference']}{of}: {o['detail']}"
    cur = o.get("current")
    if cur:
        out += (f"; the version map proposes {cur['reference']}, a match not resolved"
                if cur.get("proposed")
                else f"; the version map gives {cur['reference']}" if cur.get("reference")
                else f"; the version map gives several: {', '.join(cur['ambiguous'])}"
                if cur.get("ambiguous")
                else "; the version map finds no counterpart of it in this version")
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
    by_id = {o["id"]: o for o in refs}
    bad = [by_id[i] for i in p["examples"] if i in by_id]
    ex = "; ".join(f"{o['reference']} in {where(o)}" for o in bad[:3])
    places = f", in {p['places']} declarations or modules" if p.get("places") else ""
    return (f"the Lean's references to the paper appear to follow another version of it: "
            f"{p['absent'] + p['other_kind'] + p['reads_elsewhere']} of the {p['checked']} "
            f"references checked disagree with this version ({', '.join(x for x in parts if x)})"
            f"{places}, for example {ex}."
            + (" Suggestions rank statement content above these numbers, and label each cited "
               "number a possibly stale lead." if suggestions else ""))


def reliability(numbering: dict | None, decl: str, reference: str) -> tuple[float, str | None]:
    """How much a docstring's citation of `reference` by `decl` counts in a suggestion (1, or
    less when it is a possibly stale lead), and why it counts less."""
    if not numbering:
        return 1.0, None
    for o in numbering["references"]:
        if o["source"].get("declaration") == decl and o["reference"] == reference \
                and o.get("stale_lead"):
            return STALE_FACTOR, (f"a possibly stale number: its statement reads closer to "
                                  f"{o['content']['closer']['number']}")
    if numbering["pattern"]["drift"]:
        return STALE_FACTOR, ("a possibly stale number: the Lean's references appear to follow "
                              "another version of the paper")
    return 1.0, None


def citation(numbering: dict | None, claim: dict, declaration: str | None = None,
             module: str | None = None) -> tuple[float, str | None, list[str]] | None:
    """What a docstring citing `claim`'s number is worth as a lead to the claim in a
    suggestion: the docstring of `declaration`, or else the module docstring of `module`.
    Gives `(factor, why, ids)`: how much the citation counts (1, or `STALE_FACTOR` for a
    possibly stale lead, `reliability`), why it counts less, and the ids of the references
    with the claim's number it rests on. None when every such reference names something other
    than the claim: another work, a section, or a statement of another kind that the paper
    also numbers so. Without the project's references, or when the docstring has none with
    the claim's number, the citation counts as `reliability` says."""
    ref = claim_ref(claim)
    shown = printed(*ref) if ref else claim.get("number") or ""
    factor, why = reliability(numbering, declaration, shown)
    if not numbering or ref is None:
        return factor, why, []
    where_ = "docstring" if declaration else "module docstring"
    obs = [o for o in numbering["references"]
           if o["source"]["where"] == where_
           and (o["source"].get("declaration") == declaration if declaration
                else o["source"].get("module") == module)
           and ref[1] in (o["number"], *o.get("readings", ()))]
    own = [o for o in obs if claim.get("id") in (o.get("paper") or {}).get("claims", ())]
    # A namespace the project maps to another paper is ranked low by the suggestion itself.
    mapped = [o for o in obs if o.get("status") == "other-source"
              and o.get("detail") != ANOTHER_WORK]
    if obs and not own and not mapped:
        return None
    kind = next((o for o in own if o["status"] == "other-kind"), None)
    if kind is not None and factor == 1.0 and not any(o["status"] == "exact" for o in own):
        factor, why = STALE_FACTOR, (f"a possibly stale number: the docstring names "
                                     f"{kind['reference']}, and the paper's {ref[1]} is "
                                     f"{shown}")
    return factor, why, [o["id"] for o in own + mapped]


# -- several papers -----------------------------------------------------------------------------

def owners(names_by_paper: dict[str, set[str]], index: list[dict],
           stated_by_paper: dict[str, set[str]] | None = None) -> dict[str, dict]:
    """For each paper, the declarations its claims (and the project's alignment) name, and the
    places that the declarations stating its claims lie in (`stated_by_paper`, by default all
    of them): their namespaces and modules. Definitions, which papers often share, are named
    declarations but give no place."""
    module = {d["name"]: d.get("module") for d in index}
    out = {}
    for pid, names in names_by_paper.items():
        places = set()
        for n in (stated_by_paper or names_by_paper).get(pid, ()):
            if "." in n:
                places.add(n.rsplit(".", 1)[0])
            if module.get(n):
                places.add(module[n])
        out[pid] = {"names": set(names), "places": places}
    return out


def _depth(name: str, places: set[str]) -> int:
    """The number of leading components of `name` that form a place of `places` (0 if none)."""
    parts = name.split(".")
    return next((i for i in range(len(parts), 0, -1) if ".".join(parts[:i]) in places), 0)


def _named_paper(o: dict, papers: list[tuple[str, str]]) -> str | None:
    """The paper a reference to another work names, read from the reference's own place in its
    context: the key of the `\\cite` whose note holds it (`\\cite[Lemma 2.1]{U}`) or of the
    bracketed citation just before its number (`[U, Lemma 2.1]`, `[U]'s Lemma 2.1`) when there
    is one; else the one paper named after it and before the next reference outside a `\\cite`
    (`Lemma 2.1 of [U]`, `of \\cite{U}`, `of [U, Section 3]`, `of \\cite[Section 3]{U}`, or the
    paper's title), if exactly one is named. A `\\cite` names a paper when the paper is its only
    key (`\\cite{A,U}` names neither)."""
    ctx, at = o.get("context") or "", o["at"]
    ids = {pid for pid, _ in papers}

    def keyed(keys: str) -> str | None:
        k = [x.strip() for x in keys.split(",")]
        return k[0] if len(k) == 1 and k[0] in ids else None

    cites = [(m.start(), m.end(), keyed(m.group(1))) for m in _CITE.finditer(ctx)]
    held = next((c for c in cites if c[0] < at < c[1]), None)
    if held:
        return held[2]
    key = _KEY_BEFORE.search(ctx[:at])
    if key:
        return next((pid for pid, _ in papers if pid == key.group(1)), None)
    end = at + len(re.sub(r"\s+", " ", o["text"]))
    nxt = next((r for r in REF.finditer(ctx, end)
                if not any(s < r.start() < e for s, e, _ in cites)), None)
    after = ctx[end:nxt.start() if nxt else len(ctx)][:80]
    hits = [pid for pid, title in papers
            if re.search(r"\[" + re.escape(pid) + r"\s*[\],]", after)
            or any(end <= s < end + len(after) and named == pid for s, _, named in cites)
            or (title and re.sub(r"\s+", " ", title).lower() in after.lower())]
    return hits[0] if len(hits) == 1 else None


def attribute(o: dict, own: dict[str, dict], papers: list[tuple[str, str]]) \
        -> tuple[str | None, str]:
    """The paper of the configuration a reference cites, or None with the reason: the paper
    its citation names (`Theorem 2.1 of [U]`, `[U, Theorem 2.1]`) or whose title follows it
    (`Theorem 2.1 of Odd squares`); else the paper whose claims name its declaration; else the
    paper owning the longest namespace or module that contains its declaration or module, when
    one paper owns it."""
    if o.get("status") == "other-source":
        pid = _named_paper(o, papers)
        return (pid, "") if pid else (None, "")
    pid = _titled(o, papers)
    if pid:
        return pid, ""
    src = o["source"]
    decl = src.get("declaration")
    if decl:
        named = sorted(p for p, w in own.items() if decl in w["names"])
        if len(named) == 1:
            return named[0], ""
        if named:
            return None, f"its declaration is named by claims of papers {' and '.join(named)}"
    spots = [s for s in (decl.rsplit(".", 1)[0] if decl and "." in decl else None,
                         src.get("module")) if s]
    depth = {p: max((_depth(s, w["places"]) for s in spots), default=0) for p, w in own.items()}
    top = max(depth.values(), default=0)
    best = sorted(p for p, d in depth.items() if d == top)
    if top == 0:
        return None, "no claim of any paper names a declaration in its namespace or module"
    if len(best) > 1:
        return None, f"its namespace or module holds claims of papers {' and '.join(best)}"
    return best[0], ""


def _titled(o: dict, papers: list[tuple[str, str]]) -> str | None:
    """The paper whose title follows "of", "in" or "from" just after a reference's number
    (`Lemma 2.1 of Odd squares`, `in the Odd squares`), when exactly one paper's does. A title
    is no citation (`_cited_after`), but it names one of the configuration's papers."""
    ctx = o.get("context") or ""
    m = _AFTER_WORD.match(ctx, o["at"] + len(re.sub(r"\s+", " ", o["text"])))
    if not m:
        return None
    rest = ctx[m.end():].lower()
    starts = (rest, re.sub(r"^the\s+", "", rest))
    hits = [pid for pid, title in papers
            if title and any(s.startswith(re.sub(r"\s+", " ", title).lower()) for s in starts)]
    return hits[0] if len(hits) == 1 else None


def combine(per: dict[str, dict], invs: dict[str, dict], refs: list[dict]) -> dict:
    """One numbering for a configuration with several papers: every reference (each checked
    against the paper it is attributed to, `attributed`, or unchecked), the counts over all of
    them, and each paper's own pattern."""
    inv = {"complete": all(i["complete"] for i in invs.values()),
           "reason": "; ".join(f"paper {p}: {i['reason']}" for p, i in invs.items()
                               if i["reason"]),
           "statements": {}, "sections": None}
    p = pattern(refs, inv)
    p["drift"] = any(n["pattern"]["drift"] for n in per.values())
    p["inventory"]["statements"] = sum(len(i["statements"]) for i in invs.values())
    return {"references": refs, "pattern": p,
            "papers": {pid: n["pattern"] for pid, n in per.items()}}


def paper_view(numbering: dict, pid: str) -> dict:
    """One paper's references and pattern, from a numbering of several papers."""
    return {"references": [o for o in numbering["references"] if o.get("attributed") == pid],
            "pattern": numbering["papers"][pid]}
