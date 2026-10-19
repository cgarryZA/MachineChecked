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
from .probe import ProbeError, by_library, fingerprint, lean_session, lib_names
from .sources import acquire
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
    pass


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
    """The key a statement environment's claim has in zero configuration."""
    num = a.get("number")
    return a.get("label") or (f"{a['env']}-{num}" if num else f"{a['env']}@{a['file']}:{a['line']}")


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
            "source_sha256": a["source_sha256"],
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
    each name word is, the modules' own docstrings (`/-! … -/` in their sources), and the
    namespaces only other papers use (`formalization.foreign_roots`)."""

    def __init__(self, index: list[dict], root: Path | None = None,
                 foreign: set[str] = frozenset()):
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


def suggest(claim: dict, index: list[dict], limit: int = 3,
            ctx: SuggestContext | None = None) -> list[dict]:
    """Candidate declarations for a claim, best first, each with the reason it is suggested.

    A docstring that cites the claim's number is the strongest sign, for a declaration of the
    claim's own sort (theorems for a theorem, definitions for a definition) above one of the
    other sort; a theorem whose statement is such a cited definition ranks above both. A module
    docstring that cites it suggests the module's last declaration of the claim's sort. Name
    resemblance to the claim's label, and title words shared with a name (one of them rare
    among the project's names), come after. A citation from a namespace only another paper of
    the project uses is ranked low and says so. Ties are broken by name, never by index order."""
    ctx = ctx or SuggestContext(index)
    out: dict[str, dict] = {}
    names = {d["name"]: d for d in index}

    def add(name, score, why):
        d = names.get(name)
        if d is None:
            return
        if ctx.is_foreign(d):
            score, why = score * 0.4, why + " (in a namespace this project maps to another paper)"
        if name not in out or out[name]["score"] < score:
            out[name] = {"name": name, "score": round(score, 3), "why": why, "kind": d["kind"]}

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
                add(d["name"], 0.9, f"its docstring cites {number}")
            else:
                add(d["name"], 0.6, f"its docstring cites {number}")
                if d["kind"] != "theorem":
                    cited_defs.add(d["name"])
        if not sort_ok(d):
            continue
        short = d["name"].rsplit(".", 1)[-1]
        nt = _tokens(short)
        if label and nt:
            j = len(label & nt) / len(label | nt)
            if j >= 0.5:
                add(d["name"], 0.4 + 0.4 * j, "its name resembles the label")
        shared = words & nt
        if len(shared) >= 2 and any(ctx.df.get(t, 0) <= ctx.rare for t in shared):
            add(d["name"], 0.35, "its name shares words with the title")
    # A theorem whose statement is a cited definition proves what that definition states.
    if cited_defs and not wants_def:
        for d in index:
            ty = (d.get("type") or "").strip()
            if d["kind"] == "theorem" and ty and any(c == ty or c.endswith("." + ty)
                                                     for c in cited_defs):
                add(d["name"], 0.95, f"it proves {ty}, whose docstring cites {number}")
    for m, doc in ctx.module_docs.items():
        if num_re.search(doc):
            mine = [d for d in index if d.get("module") == m and sort_ok(d)]
            if mine:
                last = max(mine, key=lambda d: ((d.get("range") or {}).get("line") or 0, d["name"]))
                add(last["name"], 0.3, f"its module's docstring cites {number} (the module's "
                    f"last {last['kind']})")
    return sorted(out.values(), key=lambda x: (-x["score"], x["name"]))[:limit]


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


COVERAGE = ("full", "composed", "partial", "changed", "related", "unresolved")
CONFIDENCE = ("high", "medium", "low")
NOTE_CHARS = 2000


def correspondence(claim: dict, entry: dict) -> dict | None:
    """The mapper's note on how far a claim's linked declarations state it: the auditor's, from
    the links file (with its coverage and confidence when given), else the notes of the
    project's formalization.yaml rows. It is a reading shown beside the links and changes no
    status."""
    if steps.is_step(claim):
        if "lean" in entry:
            return steps.correspondence(entry, "confirmed")
        notes = claim.get("declared_notes") or []
        return {"source": "formalization.yaml", "coverage": None, "basis": None,
                "confidence": None, "note": " ".join(notes)[:NOTE_CHARS], "by": None} \
            if notes else None
    if "lean" in entry:
        note = entry["note"].strip() if isinstance(entry.get("note"), str) else ""
        cov = entry.get("coverage") if entry.get("coverage") in COVERAGE else None
        if not (note or cov):
            return None
        return {"source": "confirmed", "coverage": cov,
                "confidence": entry.get("confidence") if entry.get("confidence") in CONFIDENCE
                else None,
                "note": note[:NOTE_CHARS],
                "by": entry["by"] if isinstance(entry.get("by"), str) else None}
    notes = claim.get("declared_notes") or []
    if not notes:
        return None
    return {"source": "formalization.yaml", "coverage": None, "confidence": None,
            "note": " ".join(notes)[:NOTE_CHARS], "by": None}


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
            out.setdefault(unit, []).append(r)
    return out, notes


def _text(x) -> str:
    return x[:REVIEW_TEXT_CHARS] if isinstance(x, str) else ""


def review_view(r: dict, links: list[dict]) -> dict:
    """A report as the reader shows it, and whether it is current: it reviewed exactly the
    claim's linked declarations, with the statements they have now (`None` when the Lean was
    not checked, so their statements are unknown)."""
    pins = r.get("pins") or {}
    fps = pins.get("fingerprints") or {}
    now = {}
    for l in links:
        rec = l.get("record") or {}
        now[l["name"]] = rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint")
    if not links or any(v is None for v in now.values()):
        current = None
    else:
        current = set(fps) == set(now) and all(fps[n] == now[n] for n in now)
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
            "project_commit": pins.get("project_commit"), "current": current}


def route_link_names(claim: dict, entry: dict) -> list[str]:
    """The declarations of the different formal route a proof step records: those confirmed in
    the reader (the links file's `route`), else those formalization.yaml names."""
    if not steps.is_step(claim):
        return []
    if "route" in entry:
        return steps.route_names(entry)
    return list(claim.get("declared_route") or [])


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
    p = links_file(root)
    if not p.exists():
        return {"version": 1, "papers": {}}
    return read_json(p)


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
                old = {k: entry.pop(k) for k in ("note", "coverage", "confidence") if k in entry}
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
    """Record where the reader's Raise issue opens reports (`owner/repo`), the public address
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

# What an index record keeps: the reader lists a declaration's statement only to this length,
# and suggestions read a docstring only for the statement numbers it cites.
INDEX_TYPE_CHARS, INDEX_DOC_CHARS = 300, 4000


def _record(line: str) -> dict:
    """One probe record, as kept in memory: an index record trimmed to what is used, any other
    with its canonical form replaced by its fingerprint."""
    rec = json.loads(line)
    if rec.get("record") == "index":
        return {"record": "index", "name": rec["name"], "kind": rec["kind"],
                "module": rec.get("module"), "range": rec.get("range"),
                "type": (rec.get("type") or "")[:INDEX_TYPE_CHARS],
                "doc": (rec.get("doc") or "")[:INDEX_DOC_CHARS] or None}
    for d in [rec, rec.get("decl")]:
        if isinstance(d, dict) and "canon" in d:
            d["fingerprint"] = fingerprint(d.pop("canon"))
    return rec


def run_simple_probe(root: Path, modules: list[str], libs: list[str], requests: list[dict],
                     lake: str = "lake", timeout: int = 3600,
                     work: Path | None = None, log=None, label: str = "") -> list[dict]:
    """Run the Lean probe on `modules` in one session (`probe.lean_session`), keeping each
    record as `_record` trims it."""
    query = {"scope_roots": [l.split(".")[0] for l in libs], "spec_prefix": "",
             "accept_prefix": "", "allowed_axioms": STANDARD_AXIOMS, "requests": requests}
    try:
        return lean_session(root, modules, query, lambda lines: [_record(l) for l in lines],
                            lake, timeout, work, log, label)
    except ProbeError as e:
        raise ViewError(str(e)) from None


def probe_modules(root: Path, modules: list[str], libs: list[str], requests: list[dict],
                  lake: str = "lake", log=print,
                  work: Path | None = None) -> tuple[list[dict], dict[str, str]]:
    """Probe the built modules without assuming they can all be imported into one Lean session.

    A project may build modules that do not belong together: two libraries declaring the same
    name, for instance a statement left as a challenge and its solution. Lean may load both and
    silently keep one, so each library is probed in its own session, always; a library that
    fails to load is split in halves, down to single modules. Each record is tagged with the
    group it came from, and a name found in several groups is ambiguous until its module is
    given. Returns the records and the modules that could not be loaded, with the reason."""
    recs, failed = [], {}

    def run(group: list[str], label: str):
        try:
            out = run_simple_probe(root, group, libs, requests, lake, work=work, log=log,
                                   label=label)
        except ViewError as e:
            if len(group) == 1:
                failed[group[0]] = str(e)[-600:]
                return
            errors = [l.strip() for l in str(e).splitlines() if "error" in l]
            reason = errors[0].split("error:", 1)[-1].strip()[:200] if errors else "no error message"
            log(f"lean: {label} could not be loaded in one session ({reason}); splitting it")
            half = len(group) // 2
            run(group[:half], label + "/a")
            run(group[half:], label + "/b")
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


def resolve_link(name: str, records: list[dict], module: str | None, root: Path,
                 unbuilt: list[str], failed: dict[str, str]) -> tuple[dict | None, dict | None]:
    """The probe record a link means, or why there is none.

    A declaration is identified by its name and its module: when several loaded modules declare
    the name, the module the project gave (formalization.yaml's `module`) decides, and without
    one the link is ambiguous rather than guessed. With no record, the source says whether the
    declaration's module is unbuilt or could not be loaded: only a declaration absent from the
    modules that were inspected reads as not found."""
    found = [r for r in records if "missing" not in r.get("errors", [])]
    mod_of = lambda r: (r.get("decl") or {}).get("module") or r.get("module")
    if module:
        mine = [r for r in found if mod_of(r) == module]
        if mine:
            return mine[0], None
        if module in unbuilt:
            return None, fields("link.module-unbuilt", f"Module {module} is not built.")
        if module in failed:
            return None, fields("link.module-failed", f"Module {module} could not be loaded.")
    elif len({mod_of(r) for r in found}) > 1:
        mods = ", ".join(sorted(str(mod_of(r)) for r in found))
        return None, fields("link.ambiguous", f"Declared in {mods}.")
    elif found:
        return found[0], None
    for m in declaring_modules(root, unbuilt, name):
        return None, fields("link.module-unbuilt", f"Module {m} is not built.")
    for m in declaring_modules(root, list(failed), name):
        return None, fields("link.module-failed", f"Module {m} could not be loaded.")
    return None, None


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


def lean_digest(root: Path) -> str:
    """The content of every Lean input of the project and its path dependencies, and whether
    each module is built."""
    import hashlib
    from .pipeline import lean_inputs_digest
    h = hashlib.sha256()
    for f in sorted((root / ".lake" / "build").rglob("*.olean")) if (root / ".lake").exists() \
            else []:
        h.update(str(f.relative_to(root)).encode())
        h.update(str(f.stat().st_mtime_ns).encode())
    fake = type("C", (), {"lean_root": root})()
    h.update(lean_inputs_digest(fake).encode())
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
               log=print) -> dict:
    """Everything the reader shows for `paper_path` in the Lean project at `root`."""
    prepare_work_dir(out_dir)
    libs = lib_names(root)
    built, unbuilt = built_modules(root, libs) if libs else ([], [])
    cfg = view_config(root, paper_path, out_dir, libs)
    paper = cfg.papers[0]
    notes = []

    # The paper.
    snap = acquire(cfg, paper, out_dir / "sources" / paper.id)
    tex, pdf, claims = {"mode": snap.mode}, None, []
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
    index, linkrecs, decls = [], {}, {}
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
        work = out_dir / "build"

        def take(recs):
            for r in recs:
                if r["record"] == "link":
                    linkrecs.setdefault(r["name"], []).append(r)
                elif r["record"] == "decl":
                    decls.setdefault(r["name"], r)

        # The index is reused while no Lean input of the project changed. Built afresh, it is
        # made in the same sessions as the linked names' records, so the modules load once.
        icache = work / "index-cache.json"
        idigest = lean_digest(root)
        cached = read_json(icache) if icache.exists() else {}
        failed = {}
        if cached.get("digest") == idigest:
            index, failed = cached["index"], cached.get("failed", {})
        else:
            log(f"lean: indexing {len(built)} built module(s)"
                + (f" and checking {len(linked)} linked declaration(s)" if linked else ""))
            recs, failed = probe_modules(root, built, libs, [{"kind": "index", "name": ""}]
                                         + [{"kind": "link", "name": n} for n in sorted(linked)],
                                         lake, log, work)
            index = [r for r in recs if r["record"] == "index"]
            take(recs)
            write_json(icache, {"digest": idigest, "index": index, "failed": failed},
                       indent=None)
        wanted = set(linked)
        ctx = SuggestContext(index, root, fz.foreign_roots(fy, paper.title))
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
        wanted -= set(linkrecs)
        if wanted:
            # Only the modules that declare the names are loaded (with what they import). A name
            # the index does not hold (from a dependency, say) is looked for in every loadable
            # module, unless its source shows it in a module that is not built.
            log(f"lean: checking {len(wanted)} linked or suggested declaration(s)")
            loadable = [m for m in built if m not in failed]
            where: dict[str, set[str]] = {}
            for r in index:
                if r["name"] in wanted and r.get("module") in loadable:
                    where.setdefault(r["name"], set()).add(r["module"])
            elsewhere = sorted(n for n in wanted if n not in where
                               and not declaring_modules(root, unbuilt, n))
            groups = [(sorted(set().union(*where.values())), sorted(where))] if where else []
            if elsewhere:
                groups.append((loadable, elsewhere))
            for mods, names in groups:
                recs, more = probe_modules(root, mods, libs,
                                           [{"kind": "link", "name": n} for n in names],
                                           lake, log, work)
                failed.update(more)
                take(recs)
        if failed:
            notes.append(f"{len(failed)} built module(s) could not be loaded by MachineChecked "
                         f"and are not indexed: {', '.join(sorted(failed)[:5])}"
                         + ("…" if len(failed) > 5 else ""))

    # Statuses.
    def checked(c, n, source):
        rec = None
        if not built:
            state = fields("link.unbuilt")
        else:
            rec, why = resolve_link(n, linkrecs.get(n, []), c.get("declared_modules", {}).get(n),
                                    root, unbuilt, failed)
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
        c["correspondence"] = correspondence(c, entry) if c["links"] else None
        c["reviews"] = [review_view(r, c["links"]) for r in reports.get("link:" + c["key"], [])]
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
            "claims": claims, "index": index, "decls": decls}
    return {"body": body, "pdf": pdf, "cfg": cfg}


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
                       if (a.get("label") or f"{a['env']}-{a.get('number')}") == c["key"]), None)
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
            "findings": [], "unit": steps.unit_of(c), "parent": c.get("parent")}
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
             "editable": False}
    from .pipeline import write_preview
    from .review_queue import simple_queue
    write_preview(site, index, chunks, store, {"P": view["pdf"]} if view["pdf"] else {},
                  web_dist, simple_queue(index, chunks))
    index["review_queue"] = "data/review-queue.json"
    from . import audit
    key = body.get("paper") or ""
    write_json(site / audit.NAME, audit.descriptor(
        index, root, author=body.get("author"),
        paper_url=key if key.startswith(("http://", "https://")) else None))
    write_json(site / "data" / "lean-index.json",
               [{"name": d["name"], "kind": d["kind"], "module": d["module"],
                 "type": d["type"][:300], "doc": (d.get("doc") or "")[:300]}
                for d in body["index"]], indent=None)
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
            "why": l.get("why"), "source": l.get("source"),
            "fingerprint": rec.get("fingerprint") or (rec.get("decl") or {}).get("fingerprint"),
            "kind": rec.get("kind") or l.get("kind"),
            "axioms": rec.get("axioms"), "sorry": rec.get("sorry"),
            "errors": rec.get("errors"),
            "statement": {"binders": rec.get("binders", []), "conclusion": rec.get("conclusion"),
                          "exact": rec.get("exact") or (rec.get("decl") or {}).get("signature"),
                          "closure": rec.get("closure", []), "direct": []} if rec else None,
            "range": (rec.get("decl") or {}).get("range"),
            "module": (rec.get("decl") or {}).get("module"),
            "doc": (rec.get("decl") or {}).get("doc")}
