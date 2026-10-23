"""Zero-configuration mode: a paper and the Lean project it sits in, nothing else.

`prooflens view` finds the Lake project and the paper, takes the claims from the compiled paper,
indexes the declarations of the project's own built modules, suggests links, and shows what is
linked. Links the reader confirms are kept in `prooflens.links.json` at the project root, the
only file this mode writes into the repository.

A link says that someone associated a printed claim with a Lean declaration; it is never shown as
a check that the two say the same thing. A suggestion is shown as a suggestion.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
from importlib import resources
from pathlib import Path

from .config import STANDARD_AXIOMS, Config, Paper, Publish
from .review_sources import marker_safe, report_digests
from .probe import ProbeError, by_library, fingerprint, lean_session, lean_source, lib_names
from .sources import acquire
from .moddocs import stale_doc_names
from . import numbering as nb
from .tex import DEFAULT_ENVS, TexError, anchors_for, theorem_envs
from . import formalization as fz
from . import steps
from .util import content_id, git_head, prepare_work_dir, read_json, sha256_file, write_json

LINKS = "machinechecked.links.json"
OLD_LINKS = "prooflens.links.json"
SKIP_DIRS = {".lake", ".git", ".prooflens", "node_modules", "build", "_build", ".venv"}
DEFINITION_ENVS = {"definition", "assumption", "convention", "hypothesis", "notation"}
ENV_WORDS = {"thm", "theorem", "lem", "lemma", "prop", "proposition", "cor", "corollary",
             "def", "definition", "rem", "remark", "ex", "example", "eq", "ass", "assumption"}


from .status import fields, source_evidence

class ViewError(RuntimeError):
    """A failure the view reports. `deterministic` (for a failed Lean session) as in
    `probe.ProbeError`: true only for an error Lean reported in its input."""

    def __init__(self, message: str = "", deterministic: bool = False):
        super().__init__(message)
        self.deterministic = deterministic


# -- discovery -------------------------------------------------------------------------------

def find_lake_root(start: Path) -> Path | None:
    for d in [start, *start.parents]:
        if (d / "lakefile.toml").exists() or (d / "lakefile.lean").exists():
            return d
    return None


def built_modules(root: Path, libs: list[str]) -> tuple[list[str], list[str]]:
    """(built, unbuilt) modules of the project's libraries: a module is built when Lake has
    written its `.olean`. Modules are found from the source tree, so modules outside the import
    graph of a library's root are found too."""
    olean = root / ".lake" / "build" / "lib" / "lean"
    if not olean.exists():
        olean = root / ".lake" / "build" / "lib"
    built, unbuilt = [], []
    for lib in libs:
        base = lib.split(".")[0]
        sources = [root / f"{base}.lean"] + sorted((root / base).rglob("*.lean")) \
            if (root / base).is_dir() else [root / f"{base}.lean"]
        for src in sources:
            if not src.exists():
                continue
            mod = ".".join(src.relative_to(root).with_suffix("").parts)
            (built if (olean / src.relative_to(root).with_suffix(".olean")).exists()
             else unbuilt).append(mod)
    return built, unbuilt


def find_papers(root: Path) -> list[Path]:
    """LaTeX roots (files with \\documentclass) of the repository, else its PDFs."""
    tex, pdf = [], []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            p = Path(dirpath) / f
            if f.endswith(".tex"):
                try:
                    if re.search(r"^[^%\n]*\\documentclass", p.read_text(errors="replace"), re.M):
                        tex.append(p)
                except OSError:
                    pass
            elif f.endswith(".pdf"):
                pdf.append(p)
    # A leanblueprint keeps the plasTeX input `web.tex` beside the LaTeX root `print.tex`.
    tex = [p for p in tex if not (p.name == "web.tex" and (p.parent / "print.tex") in tex)]
    return sorted(tex) or sorted(pdf)


# -- claims from the paper -------------------------------------------------------------------

def anchor_key(a: dict) -> str:
    """The key a statement environment's claim has in zero configuration: its label, its
    environment and number, or its environment and place; made safe for a review marker to
    record (`review_sources.marker_safe`)."""
    num = a.get("number")
    return marker_safe(a.get("label") or (f"{a['env']}-{num}" if num
                                          else f"{a['env']}@{a['file']}:{a['line']}"))


def claims_from_anchors(pid: str, anchors: list[dict], snap: Path) -> list[dict]:
    claims = []
    for a in anchors:
        env = a["env"]
        num = a.get("number")
        key = anchor_key(a)
        title, tags = a.get("title") or "", []
        if a.get("file"):
            try:
                lines = (snap / a["file"]).read_text(encoding="utf-8",
                                                     errors="replace").split("\n")
                tags = source_tags(lines, a["line"], env)
            except OSError:
                pass
        claims.append({
            "id": f"{pid}:{key}", "key": key, "paper": pid, "kind": env,
            "number": f"{env.capitalize()} {num}" if num else env.capitalize(), "title": title,
            "label": a.get("label"), "location": a["file"], "line": a.get("line"),
            "source_sha256": a["source_sha256"], "statement": a.get("statement") or "",
            "scope": "definition" if env in DEFINITION_ENVS else "formal",
            "scope_note": "", "scope_reviewed": True, "clauses": [], "tags": tags})
    return claims


STEPS_VERSION = "steps-1"


def proof_steps(pid: str, anchors: list[dict], snap: Path, numbers: dict[str, str]) -> list[dict]:
    """The numbered equations inside the paper's proofs, as claims of their own
    (`steps.step_claims`), each under the statement whose proof holds it."""
    statements = claims_from_anchors(pid, anchors, snap)
    files = sorted({a["file"] for a in anchors if a.get("file")})
    return steps.step_claims(pid, statements, snap, files, numbers)


def source_tags(lines: list[str], line: int, env: str) -> list[str]:
    """The arguments of the `\\lean{…}` tags in the environment `env` opening on `line`, with
    TeX comments removed (a commented-out tag is no tag)."""
    out, depth = [], 0
    pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
    for l in lines[line - 1:]:
        l = re.sub(r"(?<!\\)%.*", "", l)
        out += re.findall(r"\\lean\{([^}]*)\}", l)
        for m in pat.finditer(l):
            depth += 1 if m.group(1) == "begin" else -1
        if depth <= 0:
            break
    return out


# -- suggestions -----------------------------------------------------------------------------

def _tokens(s: str) -> set[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    return {t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if len(t) > 1}


class SuggestContext:
    """What suggestions need to know about the whole index, computed once per view: how common
    each name word is, the modules' own docstrings (`/-! … -/` in their sources), the
    namespaces only other papers use (`formalization.foreign_roots`), the content index of
    every declaration (`retrieval.Retrieval`) and, when given, the project's references to the
    paper's numbers (`numbering.analyse`)."""

    def __init__(self, index: list[dict], root: Path | None = None,
                 foreign: set[str] = frozenset(), retrieval=None, numbering: dict | None = None):
        from .retrieval import Retrieval
        self.retrieval = retrieval if retrieval is not None else Retrieval.build(index)
        self.numbering = numbering
        self.foreign = set(foreign)
        self.df: dict[str, int] = {}
        for d in index:
            for t in _tokens(d["name"].rsplit(".", 1)[-1]):
                self.df[t] = self.df.get(t, 0) + 1
        # A word is rare when few declaration names use it; a shared title word must be rare.
        self.rare = max(3, len(index) // 500)
        self.module_docs: dict[str, str] = {}
        if root is not None:
            for m in sorted({d.get("module") for d in index if d.get("module")}):
                p = root / (m.replace(".", "/") + ".lean")
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                docs = re.findall(r"/-!(.*?)-/", text, re.S)
                if docs:
                    self.module_docs[m] = "\n".join(docs)

    def is_foreign(self, d: dict) -> bool:
        roots = {d["name"].split(".")[0], str(d.get("module") or "").split(".")[0]}
        return bool(self.foreign & roots)


def claim_text(claim: dict) -> str:
    """What a claim's content search reads: its title and its printed statement."""
    return " ".join(x for x in (claim.get("title"), claim.get("statement")
                                 or claim.get("statement_tex")) if x)


# How the signals of a suggestion combine: the statement's content counts most; a cited number,
# and a name resembling the label or the title, count less, so that together they cannot
# outrank a declaration whose content matches the claim half as well again.
W_CONTENT, W_NUMBER, W_NAME = 0.7, 0.2, 0.1
CONTENT_FULL = 0.6       # content scores are compared with the best one, or this when it is less
CONTENT_MIN = 0.4        # a declaration is suggested on content alone from this score
EXPLAIN_LIMIT = 50       # content candidates considered per claim


def suggest(claim: dict, index: list[dict], limit: int = 3,
            ctx: SuggestContext | None = None) -> list[dict]:
    """Candidate declarations for a claim, best first, each with the reasons it is suggested.

    Three signals are combined (`W_CONTENT`, `W_NUMBER`, `W_NAME`). The content signal is the
    share of the claim's printed statement and title that a declaration's complete statement,
    docstring, name and used definitions carry (`retrieval.py`), including a wrapper reached
    through a close match it uses. The number signal is a docstring citing the claim's number:
    for a declaration of the claim's own sort (theorems for a theorem, definitions for a
    definition) above one of the other sort; a theorem whose statement is such a cited
    definition above both; a module docstring citing it suggests the module's last declaration
    of the claim's sort. A citation that is a possibly stale lead (`numbering.reliability`)
    counts less and says so. The name signal is resemblance to the claim's label, or title words
    shared with a name, one of them rare among the project's names. A declaration is suggested
    when its content score reaches `CONTENT_MIN` or another signal names it. A candidate from a
    namespace only another paper of the project uses is ranked low and says so. Ties are broken
    by name, never by index order."""
    from .numbering import claim_ref, printed, reliability
    from .retrieval import paper_quantifiers
    ctx = ctx or SuggestContext(index)
    out: dict[str, dict] = {}
    names = {d["name"]: d for d in index}
    ref = claim_ref(claim)
    ref = printed(*ref) if ref else None

    def entry(name):
        d = names.get(name)
        if d is None:
            return None
        if name not in out:
            out[name] = {"name": name, "kind": d["kind"], "content": 0.0, "number": 0.0,
                         "lexical": 0.0, "reasons": {}}
        return out[name]

    def add(name, signal, value, why, extra=None):
        e = entry(name)
        if e is None or e[signal] >= value:
            return
        e[signal] = value
        e["reasons"][signal] = {"signal": signal, "text": why, **(extra or {})}

    def cite(name, value, why):
        factor, stale = reliability(ctx.numbering, name, ref) if ref else (1.0, None)
        add(name, "number", value * factor, why + (f" ({stale})" if stale else ""),
            {"reference": claim["number"], "basis": "a possibly stale lead" if stale
             else "a lead"})

    wants_def = claim["kind"] in DEFINITION_ENVS

    def sort_ok(d):
        return d["kind"] != "theorem" if wants_def else d["kind"] == "theorem"

    number = claim["number"]
    num_re = re.compile(r"\b" + re.escape(number) + r"\b", re.I)
    label = set(_tokens(claim.get("label") or "")) - ENV_WORDS
    words = _tokens(claim.get("title") or "")
    cited_defs = set()
    for d in index:
        doc = d.get("doc") or ""
        if doc and num_re.search(doc):
            if sort_ok(d):
                cite(d["name"], 0.9, f"its docstring cites {number}")
            else:
                cite(d["name"], 0.6, f"its docstring cites {number}")
                if d["kind"] != "theorem":
                    cited_defs.add(d["name"])
        if not sort_ok(d):
            continue
        short = d["name"].rsplit(".", 1)[-1]
        nt = _tokens(short)
        if label and nt:
            j = len(label & nt) / len(label | nt)
            if j >= 0.5:
                add(d["name"], "lexical", 0.5 + 0.5 * j, "its name resembles the label")
        shared = words & nt
        if len(shared) >= 2 and any(ctx.df.get(t, 0) <= ctx.rare for t in shared):
            add(d["name"], "lexical", 0.45, "its name shares words with the title")
    # A theorem whose statement is a cited definition proves what that definition states.
    if cited_defs and not wants_def:
        for d in index:
            ty = (d.get("type") or "").strip()
            if d["kind"] == "theorem" and ty and any(c == ty or c.endswith("." + ty)
                                                     for c in cited_defs):
                cite(d["name"], 0.95, f"it proves {ty}, whose docstring cites {number}")
    for m, doc in ctx.module_docs.items():
        if num_re.search(doc):
            mine = [d for d in index if d.get("module") == m and sort_ok(d)]
            if mine:
                last = max(mine, key=lambda d: ((d.get("range") or {}).get("line") or 0, d["name"]))
                cite(last["name"], 0.3, f"its module's docstring cites {number} (the module's "
                     f"last {last['kind']})")
    # The claim's content, over every declaration of its sort.
    text = claim_text(claim)
    if text.strip():
        found = ctx.retrieval.search(text, kinds=lambda k: k != "theorem" if wants_def
                                     else k == "theorem", limit=EXPLAIN_LIMIT,
                                     paper_order=paper_quantifiers(text))
        for r in found["results"]:
            e = entry(r["name"])
            if e is None:
                continue
            e["content"] = r["score"]
            for x in r["reasons"]:
                e["reasons"][x["signal"]] = x
    best = max([e["content"] for e in out.values()] + [CONTENT_FULL])
    ranked = []
    for e in out.values():
        if not (e["content"] >= CONTENT_MIN or e["number"] or e["lexical"]):
            continue
        score = (W_CONTENT * e["content"] / best + W_NUMBER * e["number"]
                 + W_NAME * e["lexical"])
        reasons = [e["reasons"][k] for k in ("content", "uses", "number", "lexical",
                                             "structure") if k in e["reasons"]]
        why = "; ".join(x["text"] for x in reasons)
        if ctx.is_foreign(names[e["name"]]):
            score *= 0.4
            why += " (in a namespace this project maps to another paper)"
        ranked.append({"name": e["name"], "score": round(score, 3), "why": why,
                       "reasons": reasons, "kind": e["kind"],
                       "signals": {k: round(e[k], 3) for k in ("content", "number", "lexical")}})
    return sorted(ranked, key=lambda x: (-x["score"], x["name"]))[:limit]


def tagged_names(claim: dict) -> list[str]:
    """The declarations a claim's `\\lean{…}` tags name, in order."""
    out = []
    for tag in claim.get("tags", []):
        for n in (t.strip() for t in tag.split(",")):
            if n and n not in out:
                out.append(n)
    return out


def linked_names(claim: dict, entry: dict) -> list[str]:
    """The declarations a claim is linked to: those confirmed in the reader (the links file
    holds the whole list, possibly empty), else those its `\\lean{…}` tags and the project's
    formalization.yaml name, less the ones rejected in the reader. A tag is a link its author
    wrote into the paper's source; a formalization.yaml mapping, one the project declared."""
    if "lean" in entry:
        return list(entry["lean"])
    names = tagged_names(claim) + [n for n in claim.get("declared", [])
                                   if n not in tagged_names(claim)]
    return [n for n in names if n not in entry.get("rejected", [])]


# A correspondence reading has two separate parts: `coverage`, how far the paper's claim and the
# linked declarations agree mathematically, and `basis`, how that relation is supported: a
# declaration that states it (`direct`), the auditor's argument combining the declarations
# (`reviewed_composition`), or a theorem whose type Lean checks is exactly a target proposition
# the auditor read against the paper (`checked_bridge`). Neither is an input to a status.
COVERAGE = ("full", "partial", "changed", "related", "unresolved")
BASIS = ("direct", "reviewed_composition", "checked_bridge")
CONFIDENCE = ("high", "medium", "low")
NOTE_CHARS = 2000
ARGUMENT_CHARS = 8000
# A reviewed composition is the auditor's argument, which Lean has not checked; what would make
# it a Lean result is shown beside it.
COMPOSITION_NEXT_STEP = "State the combination as one Lean result."
# The keys of a links-file entry that describe its declarations; linking others removes them.
READING_KEYS = ("note", "coverage", "confidence", "basis", "argument", "refs", "bridge",
                "question", "would_decide")


def _reading_text(v, limit: int = NOTE_CHARS) -> str:
    return v.strip()[:limit] if isinstance(v, str) else ""


def bridge_names(entry: dict) -> tuple[str, str] | None:
    """The (theorem, target) of an entry's checked bridge, when its basis names one and the
    theorem is one of the entry's linked declarations."""
    b = entry.get("bridge")
    if entry.get("basis") != "checked_bridge" or not isinstance(b, dict):
        return None
    thm, target = b.get("theorem"), b.get("target")
    if not (isinstance(thm, str) and isinstance(target, str) and thm and target):
        return None
    lean = entry.get("lean")
    return (thm, target) if isinstance(lean, list) and thm in lean else None


def target_fingerprint(rec: dict | None, decls: dict) -> str | None:
    """A digest of a bridge target as Lean has it: the target's own fingerprint and those of the
    project definitions its statement uses, so that a change to any of them changes it."""
    if not rec or "missing" in (rec.get("errors") or []):
        return None
    own = rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint")
    if not own:
        return None
    parts = [[rec["name"], own]] + [[n, (decls.get(n) or {}).get("fingerprint")]
                                    for n in sorted(set(rec.get("closure") or []) - {rec["name"]})]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16]


ACCEPT_ERRORS = {"missing": "Lean finds no such theorem",
                 "not-a-theorem": "it is not a theorem",
                 "type-not-spec": "its type is not exactly the target"}


def bridge_evidence(claim: dict, entry: dict, accept: dict | None, target: dict | None,
                    decls: dict) -> dict:
    """What Lean establishes about an entry's checked bridge, and whether the auditor's reading
    of its target is current. `state` is `checked` (the theorem's type is exactly the target, a
    proposition stated as a definition, with no `sorry` and only allowed axioms, and the target
    and the paper's passage are the versions the auditor read), `stale` (checked, but the target
    or the passage is not the version the auditor read, or no version is recorded), or
    `unchecked`. `reasons` says why it is not `checked`."""
    b = entry.get("bridge") if isinstance(entry.get("bridge"), dict) else {}
    pinned = {"target_fingerprint": b.get("target_fingerprint") or None,
              "source_sha256": b.get("source_sha256") or None}
    current = {"target_fingerprint": target_fingerprint(target, decls),
               "source_sha256": claim.get("source_sha256")}
    out = {"theorem": b.get("theorem") if isinstance(b.get("theorem"), str) else None,
           "target": b.get("target") if isinstance(b.get("target"), str) else None,
           "state": "unchecked", "reasons": [], "pinned": pinned, "current": current}
    why = out["reasons"]
    if bridge_names(entry) is None:
        why.append("the bridge theorem is not one of the claim's linked declarations"
                   if out["theorem"] and out["target"]
                   else "no bridge theorem and target are recorded")
    elif accept is None:
        why.append("Lean did not check the bridge (its module is not built or not loaded)")
    else:
        for e in accept.get("errors") or []:
            why.append(ACCEPT_ERRORS.get(e) or ("its axioms are not all allowed"
                                                if e.startswith("axioms=") else e))
        if accept.get("sorry"):
            why.append("its proof uses sorry")
        if target is None or "missing" in (target.get("errors") or []):
            why.append("Lean finds no such target")
        elif target.get("kind") != "def" or \
                ((target.get("decl") or {}).get("signature") or {}).get("text") != "Prop":
            why.append("the target is not a proposition stated as a definition")
    if why:
        return out
    if pinned["target_fingerprint"] != current["target_fingerprint"]:
        why.append("the target is not the version the auditor read" if pinned["target_fingerprint"]
                   else "no reviewed version of the target is recorded")
    if pinned["source_sha256"] != current["source_sha256"]:
        why.append("the paper's passage is not the version the auditor read"
                   if pinned["source_sha256"]
                   else "no reviewed version of the paper's passage is recorded")
    out["state"] = "stale" if why else "checked"
    return out


def correspondence(claim: dict, entry: dict, bridge: dict | None = None) -> dict | None:
    """The mapper's reading of how far a claim's linked declarations state it: the auditor's,
    from the links file, else the notes of the project's formalization.yaml rows. It is shown
    beside the links and changes no status.

    The auditor's reading has its `coverage` and, separately, its `basis` with the references
    it rests on: the linked declarations it cites (`refs`, all of them unless the entry names
    some), the auditor's argument for a reviewed composition, and the bridge's evidence
    (`bridge`, from `bridge_evidence`) for a checked bridge. An unresolved reading keeps its open
    question and what would decide it. A value outside the supported ones is dropped, never
    guessed, and a basis not given stays unspecified (`None`). A stored `composed` coverage reads
    as `full` with basis `reviewed_composition`, its note as the argument when none is given. A
    reviewed composition carries `next_step`, stating the combination as one Lean result."""
    if "lean" in entry:
        note = _reading_text(entry.get("note"))
        cov = entry.get("coverage") if entry.get("coverage") in COVERAGE else None
        argument = _reading_text(entry.get("argument"), ARGUMENT_CHARS)
        if entry.get("coverage") == "composed":
            # The earlier single value for full coverage by the auditor's composition, whose
            # note held the argument.
            cov, basis = "full", "reviewed_composition"
            if not argument:
                argument, note = note, ""
        else:
            basis = entry.get("basis") if cov and entry.get("basis") in BASIS else None
        if not (note or cov):
            return None
        linked = entry["lean"] if isinstance(entry["lean"], list) else []
        refs = entry.get("refs")
        refs = [n for n in refs if n in linked] if isinstance(refs, list) else list(linked)
        if basis == "checked_bridge":
            refs = [bridge["theorem"]] if bridge and bridge.get("theorem") in linked else []
        unresolved = cov == "unresolved"
        return {"source": "confirmed", "coverage": cov, "basis": basis,
                "refs": refs if basis else [],
                "argument": (argument or None) if basis == "reviewed_composition" else None,
                "next_step": COMPOSITION_NEXT_STEP if basis == "reviewed_composition" else None,
                "bridge": bridge if basis == "checked_bridge" else None,
                "question": (_reading_text(entry.get("question")) or None) if unresolved else None,
                "would_decide": (_reading_text(entry.get("would_decide")) or None) if unresolved
                else None,
                "confidence": entry.get("confidence") if entry.get("confidence") in CONFIDENCE
                else None,
                "note": note,
                "by": entry["by"] if isinstance(entry.get("by"), str) else None}
    notes = claim.get("declared_notes") or []
    if not notes:
        return None
    return {"source": "formalization.yaml", "coverage": None, "basis": None, "refs": [],
            "argument": None, "next_step": None, "bridge": None, "question": None,
            "would_decide": None, "confidence": None, "note": " ".join(notes)[:NOTE_CHARS], "by": None}


REVIEWS_DIR = "machinechecked-reviews"
REVIEW_TEXT_CHARS = 20000


def load_review_reports(root: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """The review reports exported by the reader's Review page and kept in the project's
    `machinechecked-reviews/` folder, by review unit (`link:<claim key>`), and a note for each
    file that could not be read. A report's text is the reviewer's and is shown as text."""
    out: dict[str, list[dict]] = {}
    notes: list[str] = []
    seen = set()
    d = root / REVIEWS_DIR
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            reports = data["reports"] if data.get("schema") == "prooflens/review-reports@1" else None
            if not isinstance(reports, list):
                raise ValueError("not a review export")
        except (OSError, ValueError, KeyError, AttributeError) as e:
            notes.append(f"{REVIEWS_DIR}/{f.name} was skipped: {e}")
            continue
        for r in reports:
            if not isinstance(r, dict) or r.get("schema") != "prooflens/review-report@1":
                continue
            unit = (r.get("unit") or {}).get("id")
            key = (unit, (r.get("reviewer") or {}).get("id"), r.get("submitted_at"))
            if not isinstance(unit, str) or key in seen:
                continue
            seen.add(key)
            # A report made before claim keys were made safe for markers names the key as it
            # was (`anchor_key`).
            kind, _, rest = unit.partition(":")
            if kind in ("link", "step"):
                unit = f"{kind}:{marker_safe(rest)}"
            out.setdefault(unit, []).append(r)
    return out, notes


def _text(x) -> str:
    return x[:REVIEW_TEXT_CHARS] if isinstance(x, str) else ""


def review_view(r: dict, links: list[dict], claim: dict) -> dict:
    """A report as the reader shows it, and whether it is current: it read the claim's passage
    as the paper now prints it (the digest it pinned is the claim's `source_sha256`) and
    reviewed exactly the claim's linked declarations, with the statements they have now
    (`None` when the passage is unchanged but the Lean was not checked, so their statements are
    unknown). A report that is not current says why (`why`): `declarations`, `source-changed`
    (it read another text of the passage) or `source-unrecorded` (it pinned no text)."""
    pins = r.get("pins") or {}
    fps = pins.get("fingerprints") or {}
    now = {}
    for l in links:
        rec = l.get("record") or {}
        now[l["name"]] = rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint")
    read = (report_digests(r) or {}).get(claim["id"])
    why = None
    if not links or any(v is None for v in now.values()):
        current = None
    elif set(fps) != set(now) or any(fps[n] != now[n] for n in now):
        current, why = False, "declarations"
    else:
        current = True
    if why is None and (read is None or read != claim.get("source_sha256")):
        current, why = False, "source-unrecorded" if read is None else "source-changed"
    rv, verdict = r.get("reviewer") or {}, r.get("verdict") or {}
    return {"reviewer": {k: rv.get(k) for k in ("id", "kind", "name", "model", "identity",
                                                 "same_family_as_author")},
            "verdict": {"group": verdict.get("group"), "value": verdict.get("value"),
                        "detail": _text(verdict.get("detail"))},
            "reading": _text((r.get("reading") or {}).get("text")),
            "comparison": _text((r.get("comparison") or {}).get("text")),
            "checklist": (r.get("comparison") or {}).get("checklist") or {},
            "locked_at": (r.get("reading") or {}).get("locked_at"),
            "submitted_at": r.get("submitted_at"),
            "reviewed": sorted(fps), "release": pins.get("release"),
            "project_commit": pins.get("project_commit"), "current": current,
            "correspondence": report_coverage(r, claim, current),
            **({"why": why} if why else {})}


def report_coverage(r: dict, claim: dict, current) -> dict | None:
    """A report's coverage (its `correspondence`, recorded with the verdict) as the reader shows
    it, in the form of a claim's reading (`correspondence`): `{coverage, basis, refs, argument,
    next_step, bridge, question, would_decide}`. None when the report records no supported
    coverage: an older report's coverage is not recorded, never guessed. Values outside the
    supported ones are dropped. The open question of an unresolved coverage is the verdict's
    detail. A checked bridge reads as one only while the report is current, the claim's links
    record the same bridge, Lean checks it, and the target is the version the reviewer read
    (`target_fingerprint`); otherwise it reads as the reviewer's composition, with what it was
    recorded as (`recorded_basis`) and why (`basis_reason`)."""
    cor = r.get("correspondence")
    if not isinstance(cor, dict) or cor.get("coverage") not in COVERAGE:
        return None
    cov = cor["coverage"]
    basis = cor.get("basis") if cor.get("basis") in BASIS else None
    lean = (r.get("unit") or {}).get("lean")
    reviewed = [n for n in lean if isinstance(n, str)] if isinstance(lean, list) else []
    out = {"coverage": cov, "basis": basis, "refs": reviewed if basis else [], "argument": None,
           "next_step": None, "bridge": None, "question": None, "would_decide": None}
    if basis == "checked_bridge":
        b = cor.get("bridge") if isinstance(cor.get("bridge"), dict) else {}
        names = (b.get("theorem"), b.get("target"))
        own = (claim.get("correspondence") or {}).get("bridge") or {}
        why = []
        if not all(isinstance(n, str) and n for n in names):
            why.append("no bridge theorem and target are recorded")
        elif (own.get("theorem"), own.get("target")) != names:
            why.append("the claim's links record no such bridge, so Lean does not check it")
        elif own.get("state") not in ("checked", "stale"):
            why += own.get("reasons") or ["Lean does not check the bridge"]
        if not why:
            pin, now = b.get("target_fingerprint"), (own.get("current") or {}).get(
                "target_fingerprint")
            if current is not True:
                why.append("the report was made for other paper text or other declarations")
            if not pin:
                why.append("no reviewed version of the target is recorded")
            elif pin != now:
                why.append("the target is not the version the reviewer read")
        if why:
            out.update(basis="reviewed_composition", recorded_basis="checked_bridge",
                       basis_reason=why, bridge={"theorem": names[0], "target": names[1]})
        else:
            out.update(refs=[names[0]], bridge={
                "theorem": names[0], "target": names[1], "state": "checked", "reasons": [],
                "pinned": {"target_fingerprint": b.get("target_fingerprint"),
                           "source_sha256": (report_digests(r) or {}).get(claim["id"])},
                "current": own.get("current")})
    if out["basis"] == "reviewed_composition":
        out["next_step"] = COMPOSITION_NEXT_STEP
        if basis == "reviewed_composition":
            out["argument"] = _reading_text(cor.get("argument"), ARGUMENT_CHARS) or None
    if cov == "unresolved":
        out["question"] = _reading_text((r.get("verdict") or {}).get("detail")) or None
        out["would_decide"] = _reading_text(cor.get("would_decide")) or None
    return out


def route_link_names(claim: dict, entry: dict) -> list[str]:
    """The declarations of the different formal route a proof step records: those confirmed in
    the reader (the links file's `route`), else those formalization.yaml names."""
    if not steps.is_step(claim):
        return []
    if "route" in entry:
        return steps.route_names(entry)
    return list(claim.get("declared_route") or [])


COVERAGE_WORDS = {"full": "every clause", "partial": "part of the claim",
                  "changed": "stated differently", "related": "a related result, not this claim",
                  "unresolved": "unresolved"}
BASIS_WORDS = {"direct": "in one Lean statement", "reviewed_composition":
               "by the auditor's composition", "checked_bridge": "through a bridge"}


def reading_text(cor: dict | None) -> str:
    """A correspondence reading (`correspondence`) for the terminal: its coverage and basis,
    note, the composition's argument with what Lean has not checked and the next step, a
    bridge's state, and an unresolved reading's question. Empty when nothing is recorded."""
    cor = cor or {}
    if not (cor.get("note") or cor.get("coverage")):
        return ""
    head = COVERAGE_WORDS.get(cor.get("coverage"), "")
    if head and cor.get("basis") in BASIS_WORDS:
        head += ", " + BASIS_WORDS[cor["basis"]]
    lines = [head.capitalize()] if head else []
    if cor.get("note"):
        lines.append(cor["note"])
    if cor.get("basis") == "reviewed_composition":
        lines.append("The auditor's argument: " + (cor.get("argument") or "not written."))
        lines.append("Lean has not checked this combination. Next step: "
                     + (cor.get("next_step") or COMPOSITION_NEXT_STEP))
    b = cor.get("bridge") or {}
    if cor.get("basis") == "checked_bridge" and b:
        lines.append(f"Bridge {b.get('theorem')} to target {b.get('target')}: "
                     + {"checked": "Lean checks it", "stale": "out of date: "
                        + "; ".join(b.get("reasons") or [])}.get(b.get("state"), "not checked: "
                        + "; ".join(b.get("reasons") or [])))
    if cor.get("coverage") == "unresolved":
        lines.append("Open question: " + (cor.get("question") or "not stated."))
        if cor.get("would_decide"):
            lines.append("Would decide it: " + cor["would_decide"])
    return "\n".join(lines)


def link_source(claim: dict, entry: dict, name: str) -> str:
    if "lean" in entry:
        return "confirmed"
    return "paper" if name in tagged_names(claim) else "formalization.yaml"


# -- links file ------------------------------------------------------------------------------

def links_file(root: Path) -> Path:
    """The project's links file: `machinechecked.links.json`, or the older
    `prooflens.links.json` where only that one exists."""
    new, old = root / LINKS, root / OLD_LINKS
    return old if old.exists() and not new.exists() else new


def links_key(root: Path, paper_path: Path) -> str:
    """The key of a paper in the links file: its path in the project, or for a paper fetched by
    URL, its URL (the same in every clone)."""
    key = str(paper_path.relative_to(root))
    side = paper_path.with_suffix(".json")
    if paper_path.suffix == ".pdf" and side.exists():
        key = json.loads(side.read_text()).get("url") or key
    return key


def load_links(root: Path) -> dict:
    """The links file, its claims keyed as `anchor_key` now keys them: a key written before keys
    were made safe for markers is read as its safe form, unless that form is there too."""
    p = links_file(root)
    if not p.exists():
        return {"version": 1, "papers": {}}
    data = read_json(p)
    for paper, links in (data.get("papers") or {}).items():
        if isinstance(links, dict) and any(marker_safe(k) != k for k in links):
            data["papers"][paper] = {
                (k if marker_safe(k) in links else marker_safe(k)): v for k, v in links.items()}
    return data


def save_link(root: Path, paper: str, key: str, lean: list[str] | None, rejected: list[str]
              | None = None, by: str = "") -> dict:
    """Record (or with `lean=None`, remove) the link of claim `key` of `paper`."""
    data = load_links(root)
    links = data.setdefault("papers", {}).setdefault(paper, {})
    if lean is None and not rejected:
        links.pop(key, None)
    else:
        entry = links.setdefault(key, {})
        if lean is not None:
            if entry.get("lean") != lean:
                # A note describes the declarations it was written for: it is kept, no longer
                # shown, under `earlier_notes`.
                old = {k: entry.pop(k) for k in READING_KEYS if k in entry}
                if old:
                    entry.setdefault("earlier_notes", []).append(
                        {**old, "lean": entry.get("lean"), "by": entry.get("by")})
            entry["lean"] = lean
            entry["at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
            if by:
                entry["by"] = by
        if rejected is not None:
            entry["rejected"] = sorted(set(entry.get("rejected", [])) | set(rejected))
    write_json(links_file(root), data)
    return data


def save_route(root: Path, paper: str, key: str, lean: list[str] | None, note: str = "",
               by: str = "") -> dict:
    """Record (or with `lean=None`, remove) the different formal route of the proof step `key`
    of `paper`: the declarations that reach its enclosing result by another argument. A note
    describes the declarations it was written for."""
    data = load_links(root)
    links = data.setdefault("papers", {}).setdefault(paper, {})
    entry = links.setdefault(key, {})
    if lean is None:
        entry.pop("route", None)
    else:
        old = entry.get("route") or {}
        route = {"lean": lean}
        n = note.strip()[:NOTE_CHARS] or (old.get("note") if old.get("lean") == lean else "")
        if n:
            route["note"] = n
        if by or old.get("by"):
            route["by"] = by or old["by"]
        route["at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        entry["route"] = route
    if not entry:
        links.pop(key, None)
    write_json(links_file(root), data)
    return data


def save_settings(root: Path, issues: str | None = None, site_url: str | None = None,
                  author: str | None = None, repository_private: bool | None = None) -> dict:
    """Record where the reader's Report issue opens reports (`owner/repo`), the public address
    of the published reader, and the name the audit is published under, in the links file."""
    data = load_links(root)
    if issues:
        data["issues"] = issues
    if site_url:
        data["site_url"] = site_url
    if author:
        data["author"] = author
    if repository_private is not None:
        data["repository_private"] = repository_private
    write_json(links_file(root), data)
    return data


# -- the Lean side ---------------------------------------------------------------------------

# What an index preview keeps: the reader lists a declaration's statement only to this length,
# and suggestions read a docstring only for the statement numbers it cites. The facts store
# keeps the whole record.
INDEX_TYPE_CHARS, INDEX_DOC_CHARS = 300, 4000


def lean_index_entry(d: dict) -> dict:
    """A declaration as the reader's list of declarations shows it (`data/lean-index.json`),
    from its preview: the complete statement is in the content index (`retrieval.py`)."""
    return {"name": d["name"], "kind": d["kind"], "module": d["module"],
            "type": (d.get("type") or "")[:INDEX_TYPE_CHARS],
            "type_complete": d.get("type_complete", True),
            "doc": (d.get("doc") or "")[:INDEX_TYPE_CHARS]}


def index_preview(rec: dict) -> dict:
    """The short form of an index record that the view uses."""
    return {"record": "index", "name": rec["name"], "kind": rec["kind"],
            "module": rec.get("module"), "range": rec.get("range"),
            "type": (rec.get("type") or "")[:INDEX_TYPE_CHARS],
            "type_complete": len(rec.get("type") or "") <= INDEX_TYPE_CHARS,
            "doc": (rec.get("doc") or "")[:INDEX_DOC_CHARS] or None}


def _record(line: str) -> dict:
    """One probe record, as kept in memory: an index record with what is used (its complete
    statement and docstring, and the project constants its statement and value use), any other
    with its canonical form replaced by its fingerprint."""
    rec = json.loads(line)
    if rec.get("record") == "index":
        return {"record": "index", "name": rec["name"], "kind": rec["kind"],
                "module": rec.get("module"), "range": rec.get("range"),
                "type": rec.get("type") or "", "doc": rec.get("doc") or None,
                "uses": rec.get("uses") or [], "value_uses": rec.get("value_uses") or []}
    for d in [rec, rec.get("decl")]:
        if isinstance(d, dict) and "canon" in d:
            d["fingerprint"] = fingerprint(d.pop("canon"))
    return rec


def run_simple_probe(root: Path, modules: list[str], libs: list[str], requests: list[dict],
                     lake: str = "lake", timeout: int = 3600,
                     work: Path | None = None, log=None, label: str = "",
                     extra: dict | None = None) -> list[dict]:
    """Run the Lean probe on `modules` in one session (`probe.lean_session`), keeping each
    record as `_record` trims it. `extra` adds fields to the query (a request's limits)."""
    query = {"scope_roots": [l.split(".")[0] for l in libs], "spec_prefix": "",
             "accept_prefix": "", "allowed_axioms": STANDARD_AXIOMS, "requests": requests,
             **(extra or {})}
    def read(lines):
        out = []
        for line in lines:
            rec = _record(line)
            for d in [rec, rec.get("decl")]:
                if isinstance(d, dict) and d.get("record", "decl") == "decl" and "fingerprint" in d:
                    d["lean_source"] = lean_source(root, d)
            out.append(rec)
        return out
    try:
        recs = lean_session(root, modules, query, read,
                            lake, timeout, work, log, label)
    except ProbeError as e:
        raise ViewError(str(e), deterministic=e.deterministic) from None
    if not any(r.get("record") == "done" for r in recs):
        raise ViewError("the Lean session ended before it finished (its output has no `done` "
                        "record)")
    return recs


def stale_docs_note(found: list[dict]) -> str:
    shown = ", ".join(f"{d['name']} ({d['file']}:{d['line']})" for d in found[:5])
    return (f"{len(found)} name(s) in module docstrings are not declared in the project or its "
            f"dependencies: {shown}" + (", …" if len(found) > 5 else ""))


def probe_modules(root: Path, modules: list[str], libs: list[str], requests: list[dict],
                  lake: str = "lake", log=print, work: Path | None = None,
                  sessions: dict[str, list[str]] | None = None,
                  retry: set[str] | None = None, extra: dict | None = None,
                  split: dict[str, dict] | None = None
                  ) -> tuple[list[dict], dict[str, str]]:
    """Probe the built modules without assuming they can all be imported into one Lean session.

    A project may build modules that do not belong together: two libraries declaring the same
    name, for instance a statement left as a challenge and its solution. Lean may load both and
    silently keep one, so each library is probed in its own session, always; a library that
    fails to load is split in halves, down to single modules. Each record is tagged with the
    group it came from, and a name found in several groups is ambiguous until its module is
    given. Returns the records and the modules that could not be loaded, with the reason;
    `sessions`, when given, receives the modules of each session started, by its label, and
    `retry` the failed modules whose failure was not an error Lean reported in them (out of
    memory, a timeout, a killed or unfinished session): another attempt may load them. A module
    fails only in a session of its own; `split`, when given, receives each failed module that
    was loaded on its own because the session of its library's modules failed: that library
    (`library`) and how many of its modules that session loaded (`modules`)."""
    recs, failed = [], {}

    def run(group: list[str], label: str, whole: dict | None = None):
        if sessions is not None:
            sessions[label] = list(group)
        try:
            out = run_simple_probe(root, group, libs, requests, lake, work=work, log=log,
                                   label=label, extra=extra)
        except ViewError as e:
            if len(group) == 1:
                failed[group[0]] = kept_failure(str(e))
                if retry is not None and not getattr(e, "deterministic", False):
                    retry.add(group[0])
                if split is not None and whole is not None:
                    split[group[0]] = dict(whole)
                return
            errors = [l.strip() for l in str(e).splitlines() if "error" in l]
            reason = errors[0].split("error:", 1)[-1].strip()[:200] if errors else "no error message"
            log(f"lean: {label} could not be loaded in one session ({reason}); splitting it")
            whole = whole or {"library": label, "modules": len(group)}
            half = len(group) // 2
            run(group[:half], label + "/a", whole)
            run(group[half:], label + "/b", whole)
            return
        for r in out:
            r["probe_group"] = label
        recs.extend(out)

    for lib, ms in by_library(sorted(modules), libs):
        run(ms, lib)
    return recs, failed


DECL_KEYWORDS = r"(?:theorem|lemma|def|abbrev|instance|structure|inductive|class|opaque|axiom)"


def declared_names(text: str) -> set[str]:
    """The full names a Lean source declares, as far as its text shows: each declaration's
    identifier inside the `namespace` blocks around it."""
    names, stack = set(), []
    decl = re.compile(rf"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|"
                      rf"partial|unsafe)\s+)*{DECL_KEYWORDS}\s+([\w.'«»]+)")
    for line in text.splitlines():
        m = re.match(r"\s*(namespace|section)\b\s*([\w.'«»]*)", line)
        if m:
            stack.append((m.group(1), m.group(2)))
            continue
        m = re.match(r"\s*end\b\s*([\w.'«»]*)", line)
        if m and stack:
            stack.pop()
            continue
        m = decl.match(line)
        if m:
            ident = m.group(1)
            if ident.startswith("_root_."):
                names.add(ident[len("_root_."):])
            else:
                ns = [n for kind, n in stack if kind == "namespace" and n]
                names.add(".".join(ns + [ident]))
    return names


def declaring_modules(root: Path, modules: list[str], name: str) -> list[str]:
    """Modules among `modules` whose source declares `name`, as far as its text shows. Used only
    to explain a declaration that no probed module holds; it never makes a link read as
    checked."""
    out = []
    for m in modules:
        p = root / (m.replace(".", "/") + ".lean")
        try:
            if p.is_file() and name in declared_names(p.read_text(encoding="utf-8", errors="replace")):
                out.append(m)
        except OSError:
            continue
    return out


def kept_failure(text: str, size: int = 600) -> str:
    """What is kept of a failed session's message: all of it when it is short, else its first
    and its last `size` characters, cut at whole lines where it has them: Lean's first errors,
    and what its end says (a resource that ran out, the free space left)."""
    if len(text) <= 2 * size:
        return text
    head, tail = text[:size], text[-size:]
    head = head.rsplit("\n", 1)[0] if "\n" in head else head
    tail = tail.split("\n", 1)[-1] if "\n" in tail else tail
    return f"{head}\n…\n{tail}"


PROBE_POSITION = re.compile(r"^(?:\S*prooflens-probe-[^/\\\s]*[/\\])?Probe\.lean:\d+:\d+:\s*")
LEAN_ERROR = re.compile(r"\berror\b", re.I)
SESSION_FAILED = re.compile(r"^the Lean probe failed \(-?\d+\):$")


def loading_error(reason: str, root: Path | None = None, lines: int = 3,
                  width: int = 160) -> str:
    """What a session reported when it could not load a module, on one line, from the failure
    `probe_modules` stored: its first lines that report an error (each without the position in
    the probe's own file and the word `error:`), else those naming a resource it ran out of,
    else its first lines; at most `lines` of them, each cut to `width` characters, and "…" when
    there were more. Paths in the project are given from its root, and the home folder as `~`,
    so that a published site does not show where the project was built."""
    from .probe import RESOURCE_SIGNS
    text = str(reason)
    for path, short in [(root, ""), (Path.home(), "~/")]:
        path = Path(path).resolve() if path is not None else None
        if path is not None and len(path.parts) > 1:
            text = text.replace(str(path) + os.sep, short)
    rows = [PROBE_POSITION.sub("", l.strip()) for l in text.splitlines()
            if l.strip() and l.strip() != "…"]
    errors = [l.split("error:", 1)[-1].strip() if "error:" in l else l
              for l in rows if LEAN_ERROR.search(l)]
    picked = (errors or [l for l in rows if any(s in l.lower() for s in RESOURCE_SIGNS)]
              or [l for l in rows if not SESSION_FAILED.match(l)] or rows)
    picked = [l.rstrip(":").strip() for l in picked if l.rstrip(":").strip()]
    shown = [l if len(l) <= width else l[:width - 1].rstrip() + "…" for l in picked[:lines]]
    return "; ".join(shown + (["…"] if len(picked) > len(shown) else []))


def module_failed_detail(module: str, reason: str, split: dict | None = None,
                         root: Path | None = None) -> str:
    """The detail of a link whose module could not be loaded: the module, how it was loaded (on
    its own, after the session of its library's modules failed when `split` says so) and what
    that session reported (`loading_error`)."""
    how = (f", after {split['modules']} modules of {split['library']} could not be loaded in one "
           f"Lean session" if split and split.get("library") and split.get("modules") else "")
    error = loading_error(reason, root)
    return f"Module {module} could not be loaded on its own{how}" + (f": {error}" if error
                                                                     else ".")


def resolve_link(name: str, records: list[dict], module: str | None, root: Path,
                 unbuilt: list[str], failed: dict[str, str],
                 split: dict[str, dict] | None = None) -> tuple[dict | None, dict | None]:
    """The probe record a link means, or why there is none.

    A declaration is identified by its name and its module: when several loaded modules declare
    the name, the module the project gave (formalization.yaml's `module`) decides, and without
    one the link is ambiguous rather than guessed. With no record, the source says whether the
    declaration's module is unbuilt or could not be loaded: only a declaration absent from the
    modules that were inspected reads as not found. A module that could not be loaded is named
    with what Lean reported (`module_failed_detail`; `split` as `probe_modules` gives it)."""
    found = [r for r in records if "missing" not in r.get("errors", [])]
    mod_of = lambda r: (r.get("decl") or {}).get("module") or r.get("module")
    not_loaded = lambda m: fields("link.module-failed", module_failed_detail(
        m, failed[m], (split or {}).get(m), root))
    if module:
        mine = [r for r in found if mod_of(r) == module]
        if mine:
            return mine[0], None
        if module in unbuilt:
            return None, fields("link.module-unbuilt", f"Module {module} is not built.")
        if module in failed:
            return None, not_loaded(module)
    elif len({mod_of(r) for r in found}) > 1:
        mods = ", ".join(sorted({str(mod_of(r)) for r in found}))
        return None, fields("link.ambiguous", f"Declared in {mods}.")
    elif found:
        return found[0], None
    for m in declaring_modules(root, unbuilt, name):
        return None, fields("link.module-unbuilt", f"Module {m} is not built.")
    for m in declaring_modules(root, list(failed), name):
        return None, not_loaded(m)
    return None, None


def _one(records: list[dict]) -> dict | None:
    """The one record Lean gave for a name, or None when it found none or several modules
    declare it."""
    found = [r for r in records if "missing" not in (r.get("errors") or [])]
    mods = {r.get("module") or (r.get("decl") or {}).get("module") for r in found}
    return found[0] if len(mods) == 1 else None


def link_state(rec: dict | None) -> dict:
    """The structured status of a confirmed link from its probe record."""
    if rec is None or "missing" in rec.get("errors", []):
        return fields("link.missing")
    if rec.get("kind") != "theorem":
        return fields("link.definition")
    if rec.get("sorry"):
        return fields("link.incomplete")
    if rec.get("errors"):
        return fields("link.axioms")
    return fields("link.checked")


# -- extracted Lean facts, reused between builds ---------------------------------------------

class StaleLean(ViewError):
    """The stored Lean facts do not cover the build and reuse alone was asked for
    (`build --reuse-lean`). The message says what must be extracted."""


def _reasons(why: dict[str, str]) -> str:
    """A short account of why entries must be extracted, most common reason first."""
    count: dict[str, int] = {}
    for r in why.values():
        count[r] = count.get(r, 0) + 1
    parts = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))
    return "; ".join(f"{r} ({n})" for r, n in parts[:3]) + ("; …" if len(parts) > 3 else "")


def _session_key(modules: list[str]) -> str:
    return "session:" + hashlib.sha256("\n".join(sorted(modules)).encode()).hexdigest()


REFRESHED = "a refresh was asked"


# A source that defines commands, builds declarations in a quotation or runs code that adds them
# can make declarations of any name, in its own library or in any library that uses it.
MAKES_COMMANDS = re.compile(
    r":\s*command\b|`\(\s*(?:\$\S+\s+)*(?:command\||@\[|"
    r"(?:(?:private|protected|noncomputable)\s+)*"
    r"(?:def|theorem|lemma|abbrev|instance|structure|inductive|class|axiom|opaque)\b)"
    r"|\b(?:run_cmd|run_elab|run_meta|command_elab|initialize|builtin_initialize)\b"
    r"|\b(?:addDecl|addAndCompile|elabCommand|mkAux)\w*|CommandElab")
# Attributes that make a declaration under a translated name (`mul_comm` to `add_comm`).
RENAMES = re.compile(r"\bto_(?:additive|dual)\w*")
# An identifier word: what lies between dots, spaces, brackets and other symbols.
WORD = re.compile(r"[\w'!?]+")


def _source_words(text: str) -> set[str]:
    """The identifier words of a source, in lower case: a dotted name gives each component."""
    return {w.lower() for w in WORD.findall(text)}


def name_words(name: str) -> set[str] | None:
    """The words one of which a module's source must contain for the module to hold `name`:
    each component of the name in lower case, and each of its beginnings at an underscore, with
    and without trailing primes. A name Lean generates extends one a source declares (a
    projection, constructor, recursor, equation lemma or auxiliary definition carries the
    declaration's name or a namespace the source enters; `simps`, `mk_iff` or `irreducible_def`
    append to a name), so its source has one of these words. The name is split into words as a
    source is (`_source_words`), so a component written in `«»` or with symbols is matched the
    same way in both.

    None when any module may hold the name: a component starts with `inst` (Lean names an
    instance itself, `deriving` included, from words a source need not contain, and the
    instance's own fields, `instReprFoo.repr`, extend that name), or the name is written in
    `«»` or has a component with no word."""
    if "«" in name:
        return None
    words: set[str] = set()
    for part in name.split("."):
        found = WORD.findall(part)
        if not found or any(w.startswith("inst") for w in found):
            return None
        for w in found:
            for p in {w.lower(), w.lower().rstrip("'")}:
                pieces = p.split("_")
                words |= {"_".join(pieces[:i]) for i in range(1, len(pieces) + 1)}
    words.discard("")
    return words


def index_scope(root: Path, libs: list[str], built: list[str], foreign: set[str],
                linked: set[str], modules: set[str]) -> tuple[list[str], list[str], list[str]]:
    """The built modules a paper's build indexes, the libraries it leaves out and their modules
    it does not index. A library is left out when formalization.yaml maps its namespace only to
    other papers (`formalization.foreign_roots`). A module of such a library is indexed all the
    same when it could hold a linked name, so that a link into another paper's library is
    checked there and a name two libraries declare is found in both:

    * the project names it as the module of a linked declaration (`modules`);
    * its source contains, as a whole word, one of the linked name's words (`name_words`): a
      component of the name or of one of its prefixes, or a beginning of one at an underscore,
      in any case;
    * its source uses an attribute that translates names (`to_additive`, `to_dual`).

    Every module is indexed when a linked name has a component starting with `inst` (an
    instance Lean named, or one of its fields), or when a source of the project defines
    commands, builds declarations in a quotation or runs code that adds them
    (`MAKES_COMMANDS`): either may make a declaration of any name. A module whose source cannot
    be read is indexed. Including a module costs only time; leaving out one that holds a linked
    name could hide that the name is ambiguous. Only sources are read, so the scope is the same
    whatever the facts store holds."""
    from .probe import library_of
    out = {lib for lib in libs if lib.split(".")[0] in foreign}
    if not out:
        return list(built), [], []
    wanted = [name_words(n) for n in linked]
    if any(w is None for w in wanted):
        return list(built), [], []
    words = set().union(*wanted) if wanted else set()
    texts: dict[str, str | None] = {}
    for m in built:
        try:
            texts[m] = (root / (m.replace(".", "/") + ".lean")).read_text(encoding="utf-8",
                                                                          errors="replace")
        except OSError:
            texts[m] = None
    if any(t is not None and MAKES_COMMANDS.search(t) for t in texts.values()):
        return list(built), [], []
    keep, rest = [], []
    for m in built:
        t = texts[m]
        if library_of(m, libs) not in out or m in modules or t is None or RENAMES.search(t) \
                or words & _source_words(t):
            keep.append(m)
        else:
            rest.append(m)
    left = sorted({library_of(m, libs) for m in rest})
    return keep, left, rest


def sources_declare(root: Path, modules: list[str]) -> set[str]:
    """The names the sources of `modules` declare, as far as their text shows."""
    out: set[str] = set()
    for m in modules:
        try:
            out |= declared_names((root / (m.replace(".", "/") + ".lean"))
                                  .read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def doc_forms(d: dict) -> set[str]:
    """The full names a `moddoc` record's name may stand for: as written, and inside each
    namespace its module declares into, enters or opens (`scopes`)."""
    return {d["name"], *(f"{ns}.{d['name']}" for ns in d.get("scopes", ()) if ns)}


def project_index(root: Path, lake: str = "lake", log=None) -> tuple[list[dict], dict[str, str]]:
    """The complete index records of every built module of the project at `root`, whatever
    paper maps them, and the modules that could not be loaded: from the facts store, extracting
    what it does not hold current (a search of every library, `compare --query search
    --all-libraries`)."""
    from .config import work_dir_name
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    if not built:
        raise ViewError("the Lean project is not built (run `lake build`)")
    quiet = log or (lambda m: None)
    lean = LeanFacts(root, libs, built, unbuilt, root / work_dir_name(root) / "build", lake,
                     quiet)
    with lean.store.lock(log):
        return lean.index(set())


def scope_note(left_out: list[str], modules: int) -> str:
    return (f"{modules} built module(s) of {', '.join(left_out)}, which formalization.yaml maps "
            "only to other papers, are not indexed for this paper: its suggestions, search and "
            "paper-number checks leave them out. `machinechecked inspect NAME` reaches any "
            "declaration, and `machinechecked compare --query search TEXT --all-libraries` "
            "searches every library")


class LeanFacts:
    """The Lean facts a view needs, from the facts store (`facts.Store`) where it holds them
    current, else from the probe, which then stores them. A module's index is stored per module,
    a linked or suggested declaration's record per declaration and module (with the records of
    its closure, each stored once), so an edit outside Lean starts no Lean session and an edit to
    a module reopens only what that module's importers extracted. With `reuse_only`, nothing is
    extracted: a build that would need Lean stops with `StaleLean`. With `refresh`, nothing
    stored is used: every fact the build reads is extracted again and stored in place of the old
    one, and the entries it does not read are kept.

    A module that fails to load is stored as failed only when Lean reported an error in it (it
    does not import or elaborate), a failure the same inputs repeat. A failure of resources or of
    the session (out of memory, a timeout, a heartbeat budget, a killed or unfinished session) is
    stored only as an attempt: the next build loads the module again and says that the earlier
    attempt failed. A stored failure keeps what the session reported and, for a module loaded
    on its own after its library's session failed, that library (`split`), for the detail of
    the links into it.

    A checked bridge (`bridges`, pairs of a theorem and its target) is checked by an `accept`
    request asked with the theorem's record. Its answer is stored like a link record, per pair
    and the theorem's module, with the environment of the theorem's module and the target's
    module (and everything they import), so it is reused while those are unchanged; after a
    build, `acceptrecs` holds the answers by pair."""

    def __init__(self, root: Path, libs: list[str], built: list[str], unbuilt: list[str],
                 work: Path, lake: str = "lake", log=print, reuse_only: bool = False,
                 bridges=frozenset(), refresh: bool = False, scope: list[str] | None = None):
        from . import facts
        self.root, self.libs, self.built, self.unbuilt = root, libs, built, unbuilt
        self.work, self.lake, self.log, self.reuse_only = work, lake, log, reuse_only
        self.store = facts.Store(root, libs, work, STANDARD_AXIOMS)
        # The modules to index: every built module unless a paper's build leaves some out
        # (`index_scope`). A name the index does not hold, and no indexed library declares, is
        # looked for in the others.
        self.scope = list(built) if scope is None else list(scope)
        # With `refresh`, a stored entry is used only if this build wrote it: every fact the
        # build reads is extracted again and replaces the stored one.
        self.refresh = refresh
        self.written: set[tuple[str, str]] = set()
        self.sessions = 0
        self.fresh: dict[str, list[dict]] = {}       # link records extracted in this build
        self.fresh_decls: dict[str, dict] = {}
        self.fresh_index: dict[str, list[dict]] = {}
        self.retry: set[str] = set()                 # failures of this build to try again
        self.split: dict[str, dict] = {}             # failed modules loaded apart from their library
        self.bridges: set[tuple[str, str]] = set(bridges)
        self.fresh_accepts: dict[tuple[str, str], list[dict]] = {}
        self.acceptrecs: dict[tuple[str, str], list[dict]] = {}
        self.declared: dict[str, set[str]] = {}      # the index's modules for each name
        self.fresh_docs: dict[str, list[dict]] = {}
        self.docs: dict[str, list[dict]] = {}        # `moddoc` records, by module
        self.fresh_refs: dict[str, list[dict]] = {}
        self.refs: dict[str, list[dict]] = {}        # `refs` records (reverse uses), by module
        self.loaded: set[str] = set()                # modules this build's index sessions loaded

    def _accept_requests(self, names) -> list[dict]:
        """The `accept` requests of the bridges whose theorem is among `names`."""
        return [{"kind": "accept", "name": t, "spec": s} for t, s in sorted(self.bridges)
                if t in names]

    # -- probing and storing ----------------------------------------------------------------

    def _need(self, what: str) -> None:
        if self.reuse_only:
            raise StaleLean(f"the stored Lean facts do not cover this build: {what}; run "
                            "`machinechecked build` without `--reuse-lean`")

    def _get(self, kind: str, key: str) -> tuple[dict | None, str | None]:
        """A stored entry this build may use, as `facts.Store.get`; with `refresh`, only one
        this build wrote."""
        if self.refresh and (kind, key) not in self.written:
            return None, REFRESHED
        return self.store.get(kind, key)

    def _put(self, kind: str, key: str, env: dict[str, str], **data) -> dict:
        self.written.add((kind, key))
        return self.store.put(kind, key, env, **data)

    def _run(self, modules: list[str], requests: list[dict]) -> dict[str, str]:
        sessions: dict[str, list[str]] = {}
        recs, failed = probe_modules(self.root, modules, self.libs,
                                     requests + [{"kind": "modules", "name": ""}], self.lake,
                                     self.log, self.work, sessions=sessions, retry=self.retry,
                                     split=self.split)
        self.sessions += len(sessions)
        self._store(recs, sessions, failed, any(r["kind"] == "index" for r in requests))
        for r in recs:
            r.pop("probe_group", None)
            if r["record"] == "link":
                self.fresh.setdefault(r["name"], []).append(r)
            elif r["record"] == "decl":
                self.fresh_decls.setdefault(r["name"], r)
            elif r["record"] == "index":
                self.fresh_index.setdefault(r["module"], []).append(r)
            elif r["record"] == "moddoc":
                self.fresh_docs.setdefault(r["module"], []).append(r)
            elif r["record"] == "refs":
                self.fresh_refs.setdefault(r["module"], []).append(r)
            elif r["record"] == "accept":
                self.fresh_accepts.setdefault((r["name"], r.get("spec")), []).append(r)
        return failed

    def _store(self, recs: list[dict], sessions: dict[str, list[str]], failed: dict[str, str],
               indexed: bool) -> None:
        """Store what each complete session extracted, with the environment it came from. A
        session that did not finish stores nothing; a request that failed is not stored, so it
        is asked again."""
        from .facts import graphs
        st = self.store
        graph_of = graphs(recs)
        by_label: dict[str, list[dict]] = {}
        for r in recs:
            by_label.setdefault(r.get("probe_group", ""), []).append(r)
        built = set(self.built)
        for label, mods in sessions.items():
            rs = by_label.get(label, [])
            graph = graph_of.get(label)
            if not graph or not any(r["record"] == "done" for r in rs):
                continue
            for m in mods:
                st.remove("attempt", m)
                st.remove("failed", m)
            if indexed:
                per_mod: dict[str, list[dict]] = {}
                docs: dict[str, list[dict]] = {}
                refs: dict[str, list[dict]] = {}
                for r in rs:
                    if r["record"] == "index":
                        per_mod.setdefault(r["module"], []).append(_clean(r))
                    elif r["record"] == "moddoc":
                        docs.setdefault(r["module"], []).append(_clean(r))
                    elif r["record"] == "refs":
                        refs.setdefault(r["module"], []).append(_clean(r))
                for m in graph:
                    if m in built:
                        self._put("index", m, st.environment([m], graph),
                                  records=per_mod.get(m, []), moddocs=docs.get(m, []),
                                  refs=_dedup(refs.get(m, [])))
            decls = {r["name"]: r for r in rs if r["record"] == "decl"}
            whole = st.environment(mods, graph)
            for r in rs:
                if r["record"] != "link":
                    continue
                errors = r.get("errors", [])
                if any(str(e).startswith("probe-error") for e in errors):
                    continue
                members = r.get("closure", [])
                if any(n not in decls for n in members):
                    continue
                answer = {"record": _clean(r),
                          "decls": [st.put_object(_clean(decls[n])) for n in members]}
                self._put("link", f"{r['name']}\0{_session_key(mods)}", whole, **answer)
                m = (r.get("decl") or {}).get("module")
                if "missing" not in errors and m and st.own(m) is not None:
                    self._put("link", f"{r['name']}\0module:{m}", st.environment([m], graph),
                              **answer)
            for r in rs:
                if r["record"] != "accept":
                    continue
                errors = r.get("errors", [])
                if any(str(e).startswith("probe-error") for e in errors):
                    continue
                spec = r.get("spec") or ""
                # The target's module: as this session's record of the target, or the index,
                # gives it. A change to it, or to anything it imports, reopens the answer.
                targets = {(l.get("decl") or {}).get("module") for l in rs
                           if l["record"] == "link" and l["name"] == spec}
                targets |= {x["module"] for x in rs if x["record"] == "index"
                            and x["name"] == spec}
                targets |= self.declared.get(spec, set())
                targets = sorted(t for t in targets if t)
                self._put("accept", f"{r['name']}\0{spec}\0{_session_key(mods)}",
                          st.environment(list(mods) + targets, graph), record=_clean(r))
                m = r.get("module")
                if "missing" not in errors and m and st.own(m) is not None:
                    self._put("accept", f"{r['name']}\0{spec}\0module:{m}",
                              st.environment([m] + targets, graph), record=_clean(r))
        if failed:
            project = {m: d for m in self.built if (d := st.own(m)) is not None}
            for m, reason in failed.items():
                if m in self.retry:
                    self._put("attempt", m, {}, reason=reason)
                    st.remove("failed", m)
                else:
                    how = {"split": self.split[m]} if m in self.split else {}
                    self._put("failed", m, project, reason=reason, **how)
                    st.remove("attempt", m)

    def _answers(self, name: str, where: dict[str, set[str]], groups: list[list[str]],
                 wider: list[list[str]] = ()) -> tuple[list[dict] | None, str | None]:
        """The stored answers for `name`: one for each module that holds it (`where`, from the
        index and the `refs` records), or, for a name no module holds, one for each library's
        session; and when no such session finds it, one for each session of the libraries the
        index leaves out (`wider`)."""
        if name in where:
            return self._stored([f"{name}\0module:{m}" for m in sorted(where[name])])
        out, why = self._stored([f"{name}\0{_session_key(g)}" for g in groups])
        if out is not None and wider and all(_missing(a["record"]) for a in out):
            more, why = self._stored([f"{name}\0{_session_key(g)}" for g in wider])
            out = None if more is None else out + more
        return (out, None) if out is not None else (None, why)

    def _stored(self, keys: list[str]) -> tuple[list[dict] | None, str | None]:
        """The stored link answers of `keys`, or None and why when one is not stored current."""
        out = []
        for k in keys:
            e, why = self._get("link", k)
            if e is None:
                return None, why
            objs = [self.store.get_object(o) for o in e.get("decls", [])]
            if any(o is None for o in objs):
                return None, "not extracted yet"
            out.append({"record": e["record"], "decls": objs})
        return out, None

    def _unfound(self, name: str, groups: list[list[str]]) -> bool:
        """Whether no session of `groups` found `name`, by the answers stored or extracted in
        this build."""
        got, _ = self._stored([f"{name}\0{_session_key(g)}" for g in groups])
        recs = [a["record"] for a in got] if got is not None else self.fresh.get(name, [])
        return all(_missing(r) for r in recs)

    def module_docs(self, index: list[dict]) -> list[dict]:
        """The `moddoc` records of the indexed modules: the backticked names in a module's
        docstrings that the environment it was indexed in does not know. A module indexed with
        only some of the project loaded may report a name another project module declares, so
        a name the project's index holds, or that the `refs` records of the indexed modules list
        (every constant, those Lean generates included), is left out: as written, or inside a
        namespace the module declares into, enters or opens, as the probe tries it
        (`scopes`)."""
        names = {r["name"] for r in index} | {r["name"] for rs in self.refs.values() for r in rs}
        spaces: dict[str, set[str]] = {}
        for r in index:
            parts = r["name"].split(".")
            spaces.setdefault(r.get("module"), set()).update(
                ".".join(parts[:i]) for i in range(1, len(parts)))
        return [d for m in sorted(self.docs) for d in self.docs[m]
                if d["name"] not in names
                and not any(f"{ns}.{d['name']}" in names
                            for ns in spaces.get(m, set()) | set(d.get("scopes", ())))]

    def held(self, modules: list[str]) -> set[str]:
        """The names of every constant of `modules`, built modules the index leaves out, as
        their index and `refs` records list them (those Lean generates included): from the
        store where it holds a module's index current, else from Lean, which then stores it as
        any module's index. A module that cannot be loaded gives none."""
        out: set[str] = set()
        stale: dict[str, str] = {}
        for m in modules:
            e, why = self._get("index", m)
            if e is not None:
                out |= {r["name"] for r in e["records"] + e.get("refs", [])}
            elif self._get("failed", m)[0] is None:
                stale[m] = why
        if stale:
            self._need(f"{len(stale)} module(s) to index ({_reasons(stale)})")
            self.log(f"lean: indexing {len(stale)} built module(s) the index leaves out, for "
                     f"names in module docstrings ({_reasons(stale)})")
            failed = self._run(sorted(stale), [{"kind": "index", "name": ""},
                                               {"kind": "refs", "name": ""}])
            for m in stale:
                if m not in failed:
                    out |= {r["name"] for r in self.fresh_index.get(m, [])
                            + self.fresh_refs.get(m, [])}
        return out

    def _accept_answers(self, name: str, where: dict[str, set[str]], groups: list[list[str]]
                        ) -> tuple[dict | None, str | None]:
        """The stored `accept` answers of the bridges whose theorem is `name`, by pair, keyed
        like its link records; None and why when one is not stored current."""
        out = {}
        for t, spec in sorted(self.bridges):
            if t != name:
                continue
            keys = [f"{t}\0{spec}\0module:{m}" for m in sorted(where[t])] if t in where \
                else [f"{t}\0{spec}\0{_session_key(g)}" for g in groups]
            recs = []
            for k in keys:
                e, why = self._get("accept", k)
                if e is None:
                    return None, why
                recs.append(e["record"])
            out[(t, spec)] = recs
        return out, None

    # -- the two phases ---------------------------------------------------------------------

    def index(self, linked: set[str]) -> tuple[list[dict], dict[str, str]]:
        """The index of the built modules in scope and the modules that could not be loaded.
        The linked names without a stored answer are asked in the same sessions, so the modules
        load once."""
        st = self.store
        by_mod: dict[str, list[dict]] = {}
        failed: dict[str, str] = {}
        stale: dict[str, str] = {}
        for m in self.scope:
            e, why = self._get("index", m)
            if e is not None:
                by_mod[m] = e["records"]
                self.docs[m] = e.get("moddocs", [])
                self.refs[m] = e.get("refs", [])
                continue
            f, _ = self._get("failed", m)
            if f is not None:
                failed[m] = f["reason"]
                if f.get("split"):
                    self.split[m] = f["split"]
                continue
            earlier = None if self.refresh else st.peek("attempt", m)
            stale[m] = f"an earlier attempt failed: {_first_line(earlier['reason'])}" \
                if earlier else why
        self.declared = _where({r["name"] for rs in by_mod.values() for r in rs},
                               by_mod.values(), self.built)
        if stale:
            self._need(f"{len(stale)} module(s) to index ({_reasons(stale)})")
            where = _where(linked, [*by_mod.values(), *(self.refs[m] for m in by_mod)],
                           self.built)
            ask = sorted(n for n in linked
                         if not (n in where and self._answers(n, where, [])[0] is not None
                                 and self._accept_answers(n, where, [])[0] is not None)
                         and (n in where or not declaring_modules(self.root, self.unbuilt, n)))
            self.log(f"lean: indexing {len(stale)} of {len(self.scope)} built module(s) "
                     f"({_reasons(stale)})"
                     + (f" and checking {len(ask)} linked declaration(s)" if ask else ""))
            # The reverse references of every declaration (what the reader's "Used by" shows)
            # are read in the same sessions.
            more = self._run(sorted(stale), [{"kind": "index", "name": ""},
                                             {"kind": "refs", "name": ""}]
                             + [{"kind": "link", "name": n} for n in ask]
                             + self._accept_requests(ask))
            failed.update(more)
            self.loaded = {m for m in stale if m not in failed}
            for m in stale:
                if m in failed:
                    continue
                e, _ = self._get("index", m)
                by_mod[m] = e["records"] if e is not None else self.fresh_index.get(m, [])
                self.docs[m] = e.get("moddocs", []) if e is not None else \
                    _dedup(self.fresh_docs.get(m, []))
                self.refs[m] = e.get("refs", []) if e is not None else \
                    _dedup(self.fresh_refs.get(m, []))
        else:
            self.log(f"lean: reusing the stored index of {len(self.scope)} built module(s)")
        index = sorted((r for m in by_mod for r in by_mod[m]),
                       key=lambda r: (r.get("module") or "", (r.get("range") or {}).get("line")
                                      or 0, r["name"]))
        self.declared = _where({r["name"] for r in index}, [index], self.built)
        return index, failed

    def links(self, wanted: set[str], index: list[dict], failed: dict[str, str]
              ) -> tuple[dict[str, list[dict]], dict[str, dict]]:
        """The records of the linked and suggested names, and of the declarations in their
        closures. A name is held by the modules whose index records declare it or whose `refs`
        records list it: those name every constant of a module, the ones Lean generates
        (constructors, recursors, equation lemmas, instances, projections) included, so a name
        one library declares by hand and another generates is answered in both. Only the
        modules that hold a name without a stored answer are loaded (with what they import); a
        name no module in scope holds (from a dependency, say) is looked for in every loadable
        module in scope, and when none declares it, in the built modules the index leaves out,
        unless its source shows it in a module that is not built."""
        loadable = [m for m in self.scope if m not in failed]
        held = [r for m in loadable for r in self.refs.get(m, [])]
        where = _where(wanted, [index, held], loadable)
        groups = [g for _, g in by_library(sorted(loadable), self.libs)]
        in_scope = set(self.scope)
        others = [m for m in self.built if m not in in_scope and m not in failed
                  and self._get("failed", m)[0] is None]
        wider = [g for _, g in by_library(sorted(others), self.libs)]
        linkrecs: dict[str, list[dict]] = {}
        decls: dict[str, dict] = {}
        need: dict[str, str] = {}

        def take(n, answers):
            linkrecs[n] = [a["record"] for a in answers]
            for a in answers:
                for d in a["decls"]:
                    decls.setdefault(d["name"], d)

        def settle(n, last: bool = False) -> bool:
            # A name is settled when its record and the answers of its bridges are stored
            # current; after this build's extraction, what it extracted serves instead.
            got, why = self._answers(n, where, groups, wider)
            acc, why_acc = self._accept_answers(n, where, groups)
            if got is not None and acc is not None:
                take(n, got)
                self.acceptrecs.update(acc)
                return True
            if last:
                if got is not None:
                    take(n, got)
                elif n in self.fresh:
                    take(n, [{"record": r, "decls": [self.fresh_decls[m] for m in
                                                     r.get("closure", [])
                                                     if m in self.fresh_decls]}
                             for r in self.fresh[n]])
                for pair in self.bridges:
                    if pair[0] == n:
                        got_pair = (acc or {}).get(pair) or self.fresh_accepts.get(pair)
                        if got_pair:
                            self.acceptrecs[pair] = got_pair
                return True
            need[n] = why or why_acc
            return False

        for n in sorted(wanted):
            if n not in where and declaring_modules(self.root, self.unbuilt, n):
                continue
            # A name the index sessions of this build answered needs no second session when
            # they loaded every module that holds it (every loadable module, for a name none in
            # scope holds), unless none of them found it and the index leaves libraries out.
            covered = where[n] <= self.loaded if n in where else set(loadable) <= self.loaded
            if n in self.fresh and covered and all(p in self.fresh_accepts for p in self.bridges
                                                   if p[0] == n) \
                    and not (wider and n not in where and self._unfound(n, groups)):
                settle(n, last=True)
                continue
            settle(n)
        if need:
            self._need(f"{len(need)} declaration(s) to check ({_reasons(need)})")
            self.log(f"lean: checking {len(need)} linked or suggested declaration(s) "
                     f"({_reasons(need)})")
            # A name is asked in the modules that hold it without a stored answer, and in all of
            # them when its bridges' answers are missing.
            mine = {n: where[n] if self._accept_answers(n, where, groups)[0] is None
                    else {m for m in where[n] if self._stored([f"{n}\0module:{m}"])[0] is None}
                    for n in need if n in where}
            elsewhere = sorted(n for n in need if n not in where)
            runs = [(sorted(set().union(*mine.values())), sorted(mine))] if mine else []
            keys = lambda n, gs: [f"{n}\0{_session_key(g)}" for g in gs]
            first = [n for n in elsewhere if self._stored(keys(n, groups))[0] is None
                     or self._accept_answers(n, where, groups)[0] is None]
            if first:
                runs.append((loadable, first))
            for mods, names in runs:
                failed.update(self._run(mods, [{"kind": "link", "name": n} for n in names]
                                        + self._accept_requests(names)))
            # A name no library in scope declares is looked for in those the index leaves out.
            wide = [n for n in elsewhere if wider and self._unfound(n, groups)
                    and self._stored(keys(n, wider))[0] is None]
            if wide:
                self.log(f"lean: looking for {len(wide)} declaration(s) in the "
                         f"{len(others)} built module(s) the index leaves out")
                failed.update(self._run(others, [{"kind": "link", "name": n} for n in wide]))
            for n in sorted(need):
                del need[n]
                settle(n, last=True)
        elif wanted:
            self.log(f"lean: reusing the stored records of {len(linkrecs)} linked or suggested "
                     f"declaration(s)")
        return linkrecs, decls


def _first_line(reason: str) -> str:
    """The line of a failure's text that names it: a sign of running out of a resource where
    there is one, else its first line."""
    from .probe import RESOURCE_SIGNS
    lines = [l.strip() for l in str(reason).splitlines() if l.strip()]
    for l in lines:
        if any(sign in l.lower() for sign in RESOURCE_SIGNS):
            return l[:160]
    return (lines[0] if lines else "no message")[:160].rstrip(":")


def _dedup(recs: list[dict]) -> list[dict]:
    out = []
    for r in recs:
        r = _clean(r)
        if r not in out:
            out.append(r)
    return out


def _clean(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "probe_group"}


def _missing(rec: dict) -> bool:
    return "missing" in (rec.get("errors") or [])


def _where(names, record_lists, modules) -> dict[str, set[str]]:
    """The modules among `modules` that the index records say declare each of `names`."""
    mods = set(modules)
    out: dict[str, set[str]] = {}
    for recs in record_lists:
        for r in recs:
            if r["name"] in names and r.get("module") in mods:
                out.setdefault(r["name"], set()).add(r["module"])
    return out


# -- the whole view --------------------------------------------------------------------------

def tex_machinery_digest() -> str:
    """The digest of what turns LaTeX into anchors: a change to it invalidates cached anchors."""
    h = hashlib.sha256()
    for f in ("data/prooflens.sty", "tex.py"):
        h.update(resources.files("prooflens").joinpath(f).read_bytes())
    return h.hexdigest()[:16]


def tree_digest(d: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        h.update(str(f.relative_to(d)).encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def view_config(root: Path, paper_path: Path, out_dir: Path, libs: list[str]) -> Config:
    rel = paper_path.relative_to(root)
    source = {"path": str(rel.parent)}
    paper = Paper(id="P", title=paper_title(paper_path), source=source,
                  root=rel.name if paper_path.suffix == ".tex" else None,
                  pdf=rel.name if paper_path.suffix == ".pdf" else None,
                  publish=Publish(pdf=True, source_text=True, lean=True, reviews=True))
    return Config(path=root / "prooflens.toml", name=root.name, lean_root=root,
                  modules=[], scope_roots=[l.split(".")[0] for l in libs], spec_prefix="",
                  accept_prefix="", allowed_axioms=STANDARD_AXIOMS, inventory=links_file(root),
                  reviews=[], statement_authors=[], ai_reviewers=[], dismissals=None,
                  comparator_log=None, papers=[paper], out_dir=out_dir)


def view_excerpts(snap, cwd: Path, anchors: list[dict], envs: list[str]) -> dict:
    """The passage of each statement environment, typeset from the source when it can be
    typeset whole (excerpt.py), by the key its claim has here."""
    from .excerpt import excerpt_for, read_aux
    aux = read_aux(cwd, Path(snap.root).stem)
    out = {}
    for a in anchors:
        rec = excerpt_for(snap.dir, snap.root, aux, snap.revision, set(envs), a, None, None)
        if rec is not None:
            out[anchor_key(a)] = rec
    return out


def paper_title(p: Path) -> str:
    side = p.with_suffix(".json")
    if p.suffix == ".pdf" and side.exists():
        try:
            t = json.loads(side.read_text()).get("title")
            if t:
                return t
        except ValueError:
            pass
    if p.suffix == ".tex":
        m = re.search(r"\\title\{([^}]*)\}", p.read_text(errors="replace"))
        if m:
            return re.sub(r"\\\\|\s+", " ", m.group(1)).strip()
    return p.stem


def build_view(root: Path, paper_path: Path, out_dir: Path, lake: str = "lake",
               log=print, reuse_only: bool = False, refresh: bool = False) -> dict:
    """Everything the reader shows for `paper_path` in the Lean project at `root`. With
    `reuse_only`, the Lean facts come from the facts store alone, and a build they do not cover
    stops with `StaleLean`; with `refresh`, every Lean fact the build reads is extracted again
    and replaces the stored one. The libraries formalization.yaml maps only to other papers are
    left out of the index (`index_scope`)."""
    prepare_work_dir(out_dir)
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    cfg = view_config(root, paper_path, out_dir, libs)
    paper = cfg.papers[0]
    notes = []

    # The paper.
    snap = acquire(cfg, paper, out_dir / "sources" / paper.id)
    tex, pdf, claims, aux = {"mode": snap.mode}, None, [], None
    if snap.mode == "latex":
        envs = sorted(set(DEFAULT_ENVS) | set(theorem_envs(snap.dir)))
        # The compiled paper is reused while its sources are unchanged (a link changes nothing
        # in the paper).
        cache = out_dir / "build" / "tex-cache.json"
        digest = tree_digest(snap.dir) + ":" + tex_machinery_digest() + ":" + STEPS_VERSION
        cached = read_json(cache) if cache.exists() else {}
        try:
            if cached.get("digest") == digest and Path(cached.get("pdf", "")).exists():
                t = {"page_size": cached["page_size"], "anchors": cached["anchors"],
                     "pdf": Path(cached["pdf"]), "numbers": cached.get("numbers") or {},
                     "step_anchors": cached.get("step_anchors") or {}}
            else:
                r = anchors_for(snap, out_dir / "build" / paper.id, envs)
                t = {"page_size": r["page_size"], "anchors": [a.to_json() for a in r["anchors"]],
                     "pdf": r["pdf"]}
                # The printed numbers of the labels, and where the proof equations are placed,
                # are read while the compiled paper is at hand.
                aux = Path(r["pdf"]).with_suffix(".aux")
                t["numbers"] = steps.aux_numbers(aux.read_text(errors="replace")) \
                    if aux.exists() else {}
                found = proof_steps(paper.id, t["anchors"], snap.dir, t["numbers"])
                t["step_anchors"] = r["line_anchors"]([c["location"] for c in found]) \
                    if found else {}
                write_json(cache, {"digest": digest, "page_size": t["page_size"],
                                   "anchors": t["anchors"], "pdf": str(t["pdf"]),
                                   "numbers": t["numbers"], "step_anchors": t["step_anchors"]},
                           indent=None)
            anchors = t["anchors"]
            tex.update(page_size=t["page_size"], anchors=anchors, envs=envs,
                       excerpts=view_excerpts(snap, Path(t["pdf"]).parent, anchors, envs))
            pdf = t["pdf"]
            aux = Path(t["pdf"]).parent / (Path(snap.root).stem + ".aux")
            claims = claims_from_anchors(paper.id, anchors, snap.dir)
            for c in proof_steps(paper.id, anchors, snap.dir, t["numbers"]):
                c["line_anchor"] = t["step_anchors"].get(c["location"])
                claims.append(c)
        except TexError as e:
            notes.append("the paper did not compile, so its claims are not listed: "
                         + str(e).splitlines()[0])
            tex["mode"] = "pdf"
    if pdf is None and snap.pdf:
        pdf = snap.dir / snap.pdf
    if not claims and pdf is not None:
        # A paper that is only a PDF: its numbered statements are found by their bold heads.
        from .pdfclaims import claims_from_pdf
        anchors, size = claims_from_pdf(pdf)
        tex.update(mode="pdf", anchors=anchors, page_size=size)
        claims = claims_from_anchors(paper.id, anchors, snap.dir)
        if anchors:
            notes.append("the paper is a PDF: its statements were found by their bold headings, "
                         "and where each one ends is estimated")
    paper_key = links_key(root, paper_path)

    # The Lean project.
    fy = fz.load(root)
    if fy and "error" in fy:
        notes.append(fy["error"])
    index, linkrecs, decls, acceptrecs, module_docs = [], {}, {}, {}, []
    failed, split, facts_used, refs = {}, {}, {"sessions": 0}, []
    retrieval, numbering, index_scope_info = None, None, None
    if fy and "error" not in fy:
        for c in claims:
            rows = fz.links_for(fy, c["kind"], c["number"], paper.title)
            # A proof step's row may name the different formal route used instead of it.
            route = [st for st in rows if st.get("route") and steps.is_step(c)]
            rows = [st for st in rows if st not in route]
            c["declared"] = [n for st in rows for n in st["lean"]]
            c["declared_modules"] = {n: st["module"] for st in rows + route for n in st["lean"]
                                     if st.get("module")}
            c["declared_notes"] = [st["note"] for st in rows if st.get("note")]
            if route:
                c["declared_route"] = [n for st in route for n in st["lean"]]
                c["declared_route_notes"] = [st["note"] for st in route if st.get("note")]
    links = load_links(root).get("papers", {}).get(paper_key, {})
    reports, review_notes = load_review_reports(root)
    notes += review_notes
    if not libs:
        notes.append("no Lean library found in the lakefile")
    elif not built:
        notes.append("the Lean project is not built (run `lake build`); Lean information is "
                     "not shown")
    else:
        if unbuilt:
            notes.append(f"{len(unbuilt)} module(s) of the project are not built and are not "
                         f"indexed")
        # The names linked before any suggestion (confirmed links, \lean tags, formalization.yaml),
        # less those whose module is known not to be built: Lean cannot answer for those.
        for c in claims:
            c["link_names"] = linked_names(c, links.get(c["key"], {}))
        unbuilt_set = set(unbuilt)
        linked = {n for c in claims for n in c["link_names"] + route_link_names(
                      c, links.get(c["key"], {}))
                  if c.get("declared_modules", {}).get(n) not in unbuilt_set}
        # A checked bridge's theorem is checked against its target, whose own record gives the
        # version of the target the auditor's reading is compared with.
        bridge_pairs = {b for c in claims if (b := bridge_names(links.get(c["key"], {})))}
        linked |= {t for _, t in bridge_pairs}
        work = out_dir / "build"
        (work / "index-cache.json").unlink(missing_ok=True)  # the store replaces it
        # The libraries mapped only to other papers are not indexed for this one.
        foreign = fz.foreign_roots(fy, paper.title)
        named = {m for c in claims for n, m in (c.get("declared_modules") or {}).items()
                 if n in linked}
        scope, left_out, rest = index_scope(root, libs, built, foreign, linked, named)
        if left_out:
            index_scope_info = {"left_out": left_out, "modules": len(rest)}
            notes.append(scope_note(left_out, len(rest)))
            log(f"lean: leaving {len(rest)} built module(s) of {', '.join(left_out)} out of "
                "this paper's index (formalization.yaml maps them only to other papers)")
        if refresh:
            log("lean: refreshing: every Lean fact this build reads is extracted again")
        lean = LeanFacts(root, libs, built, unbuilt, work, lake, log, reuse_only,
                         bridges=bridge_pairs, refresh=refresh, scope=scope)
        with lean.store.lock(log):
            full, failed = lean.index(linked)
            index = [index_preview(r) for r in full]
            docs = lean.module_docs(index)
            if rest:
                # A name the sources of the libraries left out declare is not indexed here,
                # and not stale.
                elsewhere = sources_declare(root, rest)
                docs = [d for d in docs if not any(
                    (f"{ns}.{d['name']}" if ns else d["name"]) in elsewhere
                    for ns in {"", *d.get("scopes", ())})]
            module_docs = stale_doc_names(docs, root)
            if rest and module_docs:
                # A name a library left out generates (a projection, constructor or instance)
                # is declared by no source: it is looked for among the constants of the modules
                # of that library whose sources could hold it (`index_scope`'s rule for a
                # linked name), indexed for this question and not for the paper.
                key = lambda d: (d["module"], d["line"], d["name"])
                listed = {key(d) for d in module_docs if d["kind"] == "none"}
                asked = [d for d in docs if key(d) in listed]
                forms = {f for d in asked for f in doc_forms(d)}
                left = set(rest)
                held = lean.held([m for m in index_scope(root, libs, built, foreign, forms,
                                                         set())[0] if m in left])
                found = {key(d) for d in asked if doc_forms(d) & held}
                module_docs = [d for d in module_docs if key(d) not in found]
            if module_docs:
                notes.append(stale_docs_note(module_docs))
            wanted = set(linked)
            # Content search and the paper's numbers read the complete records.
            from .retrieval import Retrieval
            retrieval = Retrieval.build(full)
            numbering = paper_numbering(root, full, claims, tex, aux, foreign, retrieval)
            note = nb.drift_note(numbering["pattern"], numbering["references"])
            if note:
                notes.append(note)
            ctx = SuggestContext(index, root, foreign, retrieval, numbering)
            for c in claims:
                entry = links.get(c["key"], {})
                if steps.is_step(c):
                    # A proof step is linked by someone who read it; nothing is suggested for it.
                    c["suggestions"] = []
                    continue
                c["suggestions"] = [s for s in suggest(c, index, ctx=ctx)
                                    if s["name"] not in entry.get("rejected", [])
                                    and s["name"] not in c["link_names"]]
                # Every suggestion shown is checked by Lean, not only the first.
                wanted |= {s["name"] for s in c["suggestions"] if s.get("kind")}
            linkrecs, decls = lean.links(wanted, index, failed)
            acceptrecs = lean.acceptrecs
        facts_used = {"sessions": lean.sessions, **lean.store.stats}
        refs = [r for m in sorted(lean.refs) for r in lean.refs[m]]
        split = lean.split
        again = sorted(m for m in failed if m in lean.retry)
        kept = sorted(m for m in failed if m not in lean.retry)
        if kept:
            notes.append(f"{len(kept)} built module(s) could not be loaded by MachineChecked "
                         f"and are not indexed: {failed_modules(kept, failed, root)}")
        if again:
            notes.append(f"{len(again)} built module(s) could not be loaded this time (out of "
                         "memory, a time limit or an interrupted Lean session) and are not "
                         f"indexed; the next build tries them again: "
                         f"{failed_modules(again, failed, root)}")

    # Statuses.
    def checked(c, n, source):
        rec = None
        if not built:
            state = fields("link.unbuilt")
        else:
            rec, why = resolve_link(n, linkrecs.get(n, []), c.get("declared_modules", {}).get(n),
                                    root, unbuilt, failed, split)
            state = why or link_state(rec)
        return {"name": n, **state, "source": source, "record": rec}

    for c in claims:
        entry = links.get(c["key"], {})
        c["links"] = [checked(c, n, link_source(c, entry, n))
                      for n in c.pop("link_names", None) or linked_names(c, entry)]
        if steps.is_step(c):
            c["route_links"] = [checked(c, n, "confirmed" if "route" in entry
                                        else "formalization.yaml")
                                for n in route_link_names(c, entry)]
            c["route_note"] = steps.route_note(entry, "confirmed") if "route" in entry else (
                {"source": "formalization.yaml",
                 "note": " ".join(c.get("declared_route_notes") or [])[:NOTE_CHARS], "by": None}
                if c.get("declared_route") else None)
            c["step_reports"] = reports.get(steps.unit_id(c["id"]), [])
        for s in c.get("suggestions", []):
            found = [r for r in linkrecs.get(s["name"], []) if "missing" not in r.get("errors", [])]
            s["record"] = found[0] if len({((r.get("decl") or {}).get("module")) for r in found}) == 1 else None
        bridge = None
        if entry.get("basis") == "checked_bridge":
            thm, target = bridge_names(entry) or (None, None)
            recs = acceptrecs.get((thm, target), [])
            accept = _one(recs) or ({"errors": ["missing"]} if recs and all(
                "missing" in (r.get("errors") or []) for r in recs) else None)
            bridge = bridge_evidence(c, entry, accept, _one(linkrecs.get(target, [])), decls)
        c["correspondence"] = correspondence(c, entry, bridge) if c["links"] else None
        c["reviews"] = [review_view(r, c["links"], c) for r in reports.get("link:" + c["key"], [])]
        c["references"] = claim_references(c, numbering)
        if c["links"]:
            worst = max(c["links"], key=lambda l: ["proved", "unspecified", "open", "malformed"]
                        .index(l["class"]))
            c.update(fields(worst["status_code"], worst.get("status_detail")))
        elif c.get("route_links"):
            c.update(fields("link.other-route"))
        elif c.get("suggestions"):
            c.update(fields("link.suggested"))
        else:
            c.update(fields("link.none"))

    body = {"mode": "simple", "paper": paper_key, "title": paper.title, "notes": notes,
            "project": {"name": root.name, "libs": libs, "built": len(built),
                        "unbuilt": len(unbuilt)},
            "links_sha256": sha256_file(links_file(root)) if links_file(root).exists()
            else None,
            "commit": git_head(root), "issues": load_links(root).get("issues"),
            "formalization": fz.summary(fy),
            "site_url": load_links(root).get("site_url"),
            "author": load_links(root).get("author"),
            "pdf_sha256": sha256_file(pdf) if pdf else None, "tex": tex,
            "claims": claims, "index": index, "decls": decls, "module_docs": module_docs,
            "numbering": numbering}
    if index_scope_info:
        # What the index leaves out, so that a declaration there is not taken for absent.
        body["index_scope"] = index_scope_info
    from .uses import site_index
    return {"body": body, "pdf": pdf, "cfg": cfg, "lean": facts_used, "retrieval": retrieval,
            "uses": site_index(refs) if refs else None}


def failed_modules(modules: list[str], failed: dict[str, str], root: Path) -> str:
    """The first five of `modules` that could not be loaded, each with the first line of what
    its session reported (`loading_error`), for the build's notes."""
    shown = []
    for m in modules[:5]:
        error = loading_error(failed.get(m, ""), root, lines=1, width=120)
        shown.append(f"{m} ({error})" if error else m)
    return ", ".join(shown) + ("…" if len(modules) > 5 else "")


def paper_numbering(root: Path, index: list[dict], claims: list[dict], tex: dict,
                    aux: Path | None, foreign, retrieval) -> dict:
    """The project's references to the paper's numbers, checked against the paper read here
    (`numbering.analyse`). The numbering is complete when the paper's LaTeX compiled; a PDF's
    statements are found by their headings, so some may be missed."""
    if tex.get("mode") == "latex" and claims:
        complete, reason = True, ""
    elif tex.get("mode") == "pdf" and claims:
        complete, reason = False, ("the paper is a PDF whose statements were found by their "
                                   "headings, so its numbering may be incomplete")
    else:
        complete, reason = False, "the paper's statements could not be read in this build"
    inv = nb.inventory(claims, complete, reason,
                       nb.sections_from_aux(aux) if aux is not None else None)
    blocks = nb.module_doc_blocks(root, {d.get("module") for d in index if d.get("module")})
    return nb.analyse(index, claims, inv, blocks, foreign, retrieval, claim_text)


def claim_references(c: dict, numbering: dict | None) -> list[dict]:
    """The references that concern a claim: those citing its number, and those in the
    docstrings and names of its linked and suggested declarations."""
    if not numbering:
        return []
    names = {l["name"] for l in c.get("links", [])} | {s["name"] for s in c.get("suggestions", [])}
    return [o for o in numbering["references"]
            if c["id"] in (o.get("paper") or {}).get("claims", [])
            or o["source"].get("declaration") in names]


def source_info(root: Path | None, libs: list[str]) -> dict:
    """The project's source repository, for the reader's Lean source links."""
    from . import audit
    if root is None:
        return {}
    links = load_links(root)
    return audit.source_info(root, libs, links.get("repository"),
                             links.get("repository_private", False))


def view_release(body: dict) -> str:
    """The release a view's evidence is: its content's identifier, so it changes when the paper,
    the links or the Lean change."""
    return f"v-{content_id(body)[:12]}"


def view_summary(body: dict) -> dict[str, int]:
    """How many claims have each status."""
    out: dict[str, int] = {}
    for c in body["claims"]:
        out[c["status"]] = out.get(c["status"], 0) + 1
    return out


def write_view_site(view: dict, site: Path, web_dist: Path | None,
                    root: Path | None = None) -> dict:
    """The site of a view: the same app as the full reader, in its simple mode, with its audit
    descriptor (`audit.json`). `root` is the Lean project, for the descriptor's repository."""
    from . import manifest as mf
    body = view["body"]
    eid = content_id(body)
    release = view_release(body)
    store = {}
    keys = {}
    for n, d in body["decls"].items():
        rec = {k: v for k, v in d.items() if k != "record"}
        k = mf.record_key(rec)
        keys[n], store[k] = k, rec
    index_claims, chunks = [], {}
    by_id = {c["id"]: c for c in body["claims"]}
    for c in body["claims"]:
        anchor = next((a for a in body["tex"].get("anchors", [])
                       if anchor_key(a) == c["key"]), None)
        fname = mf.claim_file(c["id"])
        akind = "approximate" if anchor and anchor.get("kind") == "pdf" else "exact"
        la = c.get("line_anchor")
        if anchor is None and la and la.get("kind") == "approximate":
            # A proof equation is placed by SyncTeX: approximately.
            path, _, line = c["location"].rpartition(":")
            anchor, akind = {"file": path, "line": int(line), "begin": [la["page"], 0, la["y0"]],
                             "end": [la["page"], 0, la["y1"]]}, "approximate"
        index_claims.append({
            "id": c["id"], "paper": c["paper"], "number": c["number"], "title": c["title"],
            "heading": c["title"] or None, "kind": c["kind"], "scope": c["scope"],
            "unit": steps.unit_of(c), "parent": c.get("parent"),
            **fields(c["status_code"], c.get("status_detail")),
            "anchor": mf.index_anchor(anchor, akind),
            "counts": {}, "file": fname, "linked": len(c["links"]),
            "suggested": len(c.get("suggestions", []))})
        names = set()
        for l in c["links"] + c.get("suggestions", []) + c.get("route_links", []):
            rec = l.get("record") or {}
            names |= set(rec.get("closure", []))
        chunks[fname] = {
            "schema": mf.SCHEMA, "mode": "simple", "release": release,
            "id": c["id"], "key": c["key"], "paper": c["paper"], "number": c["number"],
            "title": c["title"], "heading": c["title"] or None, "kind": c["kind"], "scope": c["scope"], "scope_note": "",
            "scope_reviewed": True, "location": c["location"],
            "source_sha256": c["source_sha256"], **fields(c["status_code"], c.get("status_detail")),
            "anchor": {**anchor, "kind": akind} if anchor else None, "source_matches": None,
            "statement_tex": (anchor or {}).get("statement") if akind == "exact"
            else c.get("statement_tex"),
            "excerpt": (body["tex"].get("excerpts") or {}).get(c["key"]) if akind == "exact"
            else None,
            "source_evidence": source_evidence({"kind": akind} if anchor else None, body["tex"]["mode"], paper=body["tex"]),
            "blockers": [],
            "links": [_link_view(l, root) for l in c["links"]],
            "correspondence": c.get("correspondence"), "reviews": c.get("reviews", []),
            "suggestions": [_link_view(s, root) for s in c.get("suggestions", [])],
            "clauses": [], "decls": {n: keys[n] for n in sorted(names) if n in keys},
            "findings": [], "references": c.get("references", []),
            "unit": steps.unit_of(c), "parent": c.get("parent")}
        if steps.is_step(c):
            chunks[fname].update(
                context_tex=c.get("context_tex"),
                step=steps.block(c, _parent_row(by_id.get(c.get("parent") or "")),
                                 [_link_view(l, root) for l in c["links"]],
                                 [_link_view(l, root) for l in c.get("route_links", [])],
                                 c.get("correspondence"), c.get("route_note"),
                                 steps.review(c.get("step_reports", []), c["source_sha256"])))
    steps.attach_parents(index_claims, chunks)
    summary = {}
    for c in index_claims:
        summary[c["status"]] = summary.get(c["status"], 0) + 1
    classes = {c["status"]: c["class"] for c in index_claims}
    index = {"schema": mf.SCHEMA, "mode": "simple", "release": release,
             "evidence": eid, "created": _dt.datetime.now(_dt.timezone.utc)
             .isoformat(timespec="seconds"),
             "project": {"name": body["project"]["name"], "commit": body.get("commit"),
                         **source_info(root, body["project"]["libs"])},
             "tool": {"name": "machinechecked"},
             "issues": body.get("issues"), "site_url": body.get("site_url"),
             "formalization": body.get("formalization"),
             "lean": None, "notes": body["notes"],
             "papers": [{"id": "P", "title": body["title"], "mode": body["tex"]["mode"],
                         "revision": body.get("commit"),
                         **_paper_version(body),
                         "pdf": "papers/P.pdf" if view["pdf"] else None,
                         "pdf_sha256": body.get("pdf_sha256") if view["pdf"] else None,
                         "page_size": body["tex"].get("page_size"), "note": ""}],
             "summary": {"P": summary}, "units": steps.unit_counts(index_claims),
             "classes": classes,
             "findings": {"total": {}, "general": []}, "gates": {}, "claims": index_claims,
             "search": "data/search.json", "lean_index": "data/lean-index.json",
             **({"uses": "data/uses.json"} if view.get("uses") else {}),
             "retrieval": "data/retrieval.json" if view.get("retrieval") is not None else None,
             "numbering": (body.get("numbering") or {}).get("pattern"),
             **({"index_scope": body["index_scope"]} if body.get("index_scope") else {}),
             "editable": False}
    from .pipeline import write_preview
    from .review_queue import prioritise, simple_queue
    write_preview(site, index, chunks, store, {"P": view["pdf"]} if view["pdf"] else {},
                  web_dist, prioritise(simple_queue(index, chunks), uses=view.get("uses"),
                                       unbuilt=body["project"]["unbuilt"]))
    index["review_queue"] = "data/review-queue.json"
    from . import audit
    key = body.get("paper") or ""
    write_json(site / audit.NAME, audit.descriptor(
        index, root, author=body.get("author"),
        paper_url=key if key.startswith(("http://", "https://")) else None))
    if view.get("uses"):
        write_json(site / "data" / "uses.json", view["uses"], indent=None)
    write_json(site / "data" / "lean-index.json",
               [lean_index_entry(d) for d in body["index"]], indent=None)
    # The content index is built from complete records (`build_view`); the view's previews
    # are not complete statements, so without it no content index is written.
    retrieval = view.get("retrieval")
    if retrieval is not None:
        write_json(site / "data" / "retrieval.json", retrieval.export(), indent=None)
    write_json(site / "data" / "numbering.json",
               body.get("numbering") or {"references": [], "pattern": None}, indent=None)
    return index


def _parent_row(c: dict | None) -> dict | None:
    from . import manifest as mf
    return {"id": c["id"], "number": c["number"], "heading": c["title"] or None,
            "title": c["title"], "file": mf.claim_file(c["id"])} if c else None


def _paper_version(body: dict) -> dict:
    """The version of the paper the view reads: the arXiv version its URL names, else the
    project's commit (the paper is a file of the project). Its claims are read from that
    version itself, so the version is checked."""
    from . import versions
    from .audit import arxiv_id
    key = body.get("paper") or ""
    ax = arxiv_id(key) if key.startswith(("http://", "https://")) else None
    if ax and ax[1]:
        return {"paper_version": {**versions.published_version(f"arXiv:{ax[0][6:]}{ax[1]}"),
                                  "checked": True}}
    commit = body.get("commit") or ""
    if versions.COMMIT.fullmatch(commit) and len(commit) == 40:
        return {"paper_version": {**versions.manuscript_record(commit), "checked": True}}
    return {}


def _link_view(l: dict, root: Path | None = None) -> dict:
    """A link or suggestion as the reader shows it; `path` is its file in the project's
    repository, for a link to its source, when the project is known."""
    from . import audit
    rec = l.get("record") or {}
    module = (rec.get("decl") or {}).get("module")
    return {"path": audit.source_path(root, module) if root else None,"name": l["name"], **fields(l.get("status_code", "link.suggested"), l.get("status_detail")),
            "why": l.get("why"), "reasons": l.get("reasons"), "source": l.get("source"),
            "fingerprint": rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint"),
            "kind": rec.get("kind") or l.get("kind"),
            "axioms": rec.get("axioms"), "sorry": rec.get("sorry"),
            "errors": rec.get("errors"),
            "statement": {"binders": rec.get("binders", []), "conclusion": rec.get("conclusion"),
                          "exact": rec.get("exact") or (rec.get("decl") or {}).get("signature"),
                          "closure": rec.get("closure", []), "direct": []} if rec else None,
            "range": (rec.get("decl") or {}).get("range"),
            "module": (rec.get("decl") or {}).get("module"),
            "doc": (rec.get("decl") or {}).get("doc"),
            # A linked definition: what it says (its body or equations, and its source).
            "definition": _definition(rec["decl"]) if "defined_by" in (rec.get("decl") or {})
            else None}


def _definition(decl: dict) -> dict:
    """The fields of a definition's record that the reader shows as its content."""
    from .export import DECL_KEYS_LEAN
    return {k: decl[k] for k in DECL_KEYS_LEAN if k in decl}
