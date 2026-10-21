"""Bounded manuscript regions and fingerprints, independent of their PDF placement.

Hash the original text, not a whitespace-normalised rendering: a newline can terminate a TeX
comment. The scanner recognises literal environments and explicit spans, not arbitrary TeX.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEME = "tex-region-v1"
DISPLAYS = {"equation", "align", "gather", "multline", "eqnarray", "flalign", "alignat"}
ENV = re.compile(r"\\(begin|end)\s*\{([A-Za-z][A-Za-z0-9*_.-]*)\}")
COMMAND = re.compile(r"\\[A-Za-z@]+|\\.", re.S)


class RegionError(ValueError):
    pass


def location(claim: dict) -> tuple[str, int] | None:
    path, _, line = (claim.get("location") or "").rpartition(":")
    if not path or not line.isdigit():
        return None
    if int(line) < 1:
        raise RegionError("source line must be positive")
    return path, int(line)


def source_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise RegionError("source path leaves the manuscript snapshot")
    return path


def environments(text: str, start: int):
    """Literal begin/end tokens outside comments, escaped backslashes and inline verbatim."""
    i = start
    while i < len(text):
        if text[i] == "%":
            end = text.find("\n", i)
            i = end + 1 if end >= 0 else len(text)
        elif text[i] == "\\":
            env = ENV.match(text, i)
            if env:
                yield env.group(1), env.group(2), env.start(), env.end()
                i = env.end()
                continue
            cmd = COMMAND.match(text, i)
            if not cmd:
                i += 1
                continue
            i = cmd.end()
            if cmd.group() == r"\verb":
                if i < len(text) and text[i] == "*":
                    i += 1
                if i >= len(text) or text[i].isspace():
                    raise RegionError("invalid inline verbatim delimiter")
                end = text.find(text[i], i + 1)
                if end < 0 or "\n" in text[i:end]:
                    raise RegionError("unterminated inline verbatim")
                i = end + 1
        else:
            i += 1


@dataclass(frozen=True)
class Region:
    file: str
    start_line: int
    end_line: int
    start_column: int
    end_column: int
    kind: str
    text: str
    lines: tuple[str, ...] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def line_sha256(self) -> list[str]:
        """One digest per source line the passage spans (the whole line, raw, without its line
        terminator), so that a change can be located, a passage that only moved can be told
        from a changed one, and any checker can verify the pins from the file's lines alone."""
        return [hashlib.sha256(line.encode("utf-8")).hexdigest() for line in self.lines]

    def record(self) -> dict:
        # The evidence needs bounds and digests, not an additional public copy of the text.
        return {"file": self.file, "start_line": self.start_line, "end_line": self.end_line,
                "start_column": self.start_column, "end_column": self.end_column,
                "kind": self.kind, "scheme": SCHEME, "sha256": self.sha256,
                "line_sha256": self.line_sha256}


def positive(value, name: str) -> int:
    if type(value) is not int or value < 1:
        raise RegionError(f"{name} must be a positive integer")
    return value


def _span(lines: list[str], first: int, last: int) -> tuple[str, ...]:
    return tuple(l.rstrip("\r\n") for l in lines[first - 1:last])


def extract(root: Path, claim: dict) -> Region:
    loc = location(claim)
    if loc is None:
        raise RegionError("a source region needs a file:line location")
    name, line = loc
    text = source_file(root, name).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not 1 <= line <= len(lines):
        raise RegionError("source line is outside the file")
    starts = [0]
    for part in lines:
        starts.append(starts[-1] + len(part))
    first = lines[line - 1].rstrip("\r\n")
    span = claim.get("source_region")
    if span is not None:
        if not isinstance(span, dict) or set(span) - {"end_line", "start_column", "end_column"}:
            raise RegionError("source_region needs end_line and optional column bounds")
        end_line = positive(span.get("end_line"), "end_line")
        if not line <= end_line <= len(lines):
            raise RegionError("source end line is before the start or outside the file")
        last = lines[end_line - 1].rstrip("\r\n")
        start_col = positive(span.get("start_column", 1), "start_column")
        end_col = positive(span.get("end_column", len(last) + 1), "end_column")
        if start_col > len(first) + 1 or end_col > len(last) + 1:
            raise RegionError("source column is outside the line")
        start = starts[line - 1] + start_col - 1
        end = starts[end_line - 1] + end_col - 1
        if start >= end or not text[start:end].strip():
            raise RegionError("source region is empty or reversed")
        return Region(name, line, end_line, start_col, end_col, "span", text[start:end],
                      _span(lines, line, end_line))
    start = starts[line - 1] + len(first) - len(first.lstrip())
    opening = ENV.match(text, start)
    if opening and opening.group(1) == "begin" and opening.group(2).rstrip("*") in DISPLAYS:
        stack = []
        for op, env, _, end in environments(text, start):
            if op == "begin":
                stack.append(env)
            elif not stack or stack.pop() != env:
                raise RegionError("mismatched source environment")
            if not stack:
                end_line = text.count("\n", 0, end) + 1
                end_column = end - (text.rfind("\n", 0, end) + 1) + 1
                return Region(name, line, end_line, start - starts[line - 1] + 1,
                              end_column, "environment", text[start:end],
                              _span(lines, line, end_line))
        raise RegionError("source environment has no matching end")
    if first.lstrip().startswith(r"\begin"):
        raise RegionError("unsupported or malformed environment; select an explicit source region")
    if not first.strip() or first.lstrip().startswith("%"):
        raise RegionError("source line is blank or a comment; select the actual passage")
    return Region(name, line, line, 1, len(first) + 1, "line", first, (first,))


# Commands that carry no text of a claim: a label, a heading, the start of the appendix.
SECTIONING = r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?"
_STRUCTURE = re.compile(r"\\label\s*\{[^{}]*\}|" + SECTIONING
                        + r"\s*(?:\[[^\]]*\])?\s*\{(?:[^{}]|\{[^{}]*\})*\}|\\appendix\b")
_SECTION = re.compile(SECTIONING + r"(?![A-Za-z])|\\appendix\b")
# A line after which a new sentence starts: one that ends a sentence, or a line of LaTeX
# structure (an environment's begin or end, a display's end, an item, a heading).
_ENDS = re.compile(r"[.!?][\s'\")\]}$]*$")
_BOUNDARY = re.compile(r"^\s*(?:\\(?:begin|end|item|label|\]|\[|par\b|noindent|medskip|"
                       r"bigskip|smallskip|appendix|part|chapter|section|subsection|"
                       r"subsubsection|paragraph|subparagraph)|\$\$)"
                       r"|(?:\\end\s*\{[^{}]*\}|\\\]|\$\$|\\\\)\s*$")


def _code(line: str) -> str:
    """A source line without its comment."""
    return re.sub(r"(?<!\\)%.*", "", line)


def _blank(line: str) -> bool:
    return not _code(line).strip()


def _bare(line: str) -> bool:
    """Whether a line holds nothing of a claim's text: only labels, headings, comments."""
    return not _STRUCTURE.sub("", _code(line)).strip()


def _paragraph(lines: list[str], first: int, last: int) -> tuple[int, int]:
    """The paragraph around lines `first`..`last` (1-based): out to the nearest blank line or
    line of structure on each side."""
    a, b = first, last
    while a > 1 and not _blank(lines[a - 2]) and not _BOUNDARY.search(_code(lines[a - 2])):
        a -= 1
    while b < len(lines) and not _blank(lines[b]) and not _BOUNDARY.search(_code(lines[b])):
        b += 1
    return a, b


def advice(lines: list[str], region: Region) -> list[dict]:
    """Where a line-located region may not hold the claim's text (#180): a region of only a
    label or heading (`label-only`, naming the paragraph that follows), a region that begins
    or ends inside a sentence (`starts-mid-sentence`, `ends-mid-sentence`, naming the
    paragraph around it), and one that runs into another section (`spans-section`). Each is
    advice: the region is what the inventory pins, and a reviewer decides its extent. A
    display environment and a region bounded inside a line are judged on their lines only for
    a heading after their first line."""
    first, last = region.start_line, region.end_line
    body = lines[first - 1:last]
    out = []

    def where(a: int, b: int) -> dict:
        return {"file": region.file, "line": a, "end_line": b}

    if all(_bare(l) for l in body):
        a = last + 1
        while a <= len(lines) and (_blank(lines[a - 1]) or _bare(lines[a - 1])):
            a += 1
        if a <= len(lines) and not _SECTION.search(_code(lines[a - 1])):
            b = _paragraph(lines, a, a)[1]
            out.append({"kind": "label-only", "suggested": where(a, b)})
        else:
            out.append({"kind": "label-only"})
        return out
    for i, l in enumerate(body[1:], first + 1):
        if _SECTION.search(_code(l)):
            out.append({"kind": "spans-section", "at": i})
            break
    whole = region.kind in ("line", "span") and region.start_column == 1 and \
        region.end_column == len(lines[last - 1].rstrip("\r\n")) + 1
    if not whole:
        return out
    para = where(*_paragraph(lines, first, last))
    prev = lines[first - 2] if first > 1 else ""
    if not _blank(prev) and not _BOUNDARY.search(_code(prev)) \
            and not _ENDS.search(_code(prev).rstrip()):
        out.append({"kind": "starts-mid-sentence", "suggested": para})
    after = lines[last] if last < len(lines) else ""
    end = _code(body[-1]).rstrip()
    if not _blank(after) and not _BOUNDARY.search(_code(after)) and \
            not _BOUNDARY.search(end) and not _ENDS.search(end):
        out.append({"kind": "ends-mid-sentence", "suggested": para})
    return out


def advice_message(claim_id: str, region: dict, a: dict) -> str:
    """What an advice says, for a finding or the repin plan."""
    at = f"{region.get('file')}:{region.get('start_line')}"
    if region.get("end_line", region.get("start_line")) != region.get("start_line"):
        at += f"-{region.get('end_line')}"
    s = a.get("suggested")
    hint = (f"; pin lines {s['line']}-{s['end_line']} of {s['file']} instead (location "
            f"{s['file']}:{s['line']} with source_region end_line {s['end_line']})"
            if s else "")
    what = {"label-only": "holds only a label or heading, so it pins none of the claim's text",
            "starts-mid-sentence": "begins inside a sentence that starts before it",
            "ends-mid-sentence": "ends inside a sentence that continues after it",
            "spans-section": f"runs past a heading on line {a.get('at')} into another "
                             "section"}[a["kind"]]
    return f"the source region of {claim_id} at {at} {what}{hint}"


def region_advice(root: Path, region: Region) -> list[dict]:
    """`advice` for a region of the snapshot at `root`."""
    try:
        text = source_file(root, region.file).read_text(encoding="utf-8")
    except (RegionError, OSError, UnicodeError):
        return []
    return advice(text.splitlines(), region)


def collect(inventory: dict, paper: str, root: Path) -> dict:
    """One record per claim, including extraction errors; shared start lines do not collide.
    A record carries `advice` when its region may not hold the claim's text."""
    out = {}
    for claim in inventory["claims"]:
        if claim["paper"] != paper:
            continue
        try:
            if location(claim) is None:
                continue
            region = extract(root, claim)
            out[claim["id"]] = region.record()
            adv = region_advice(root, region)
            if adv:
                out[claim["id"]]["advice"] = adv
        except (RegionError, OSError, UnicodeError) as error:
            out[claim["id"]] = {"scheme": SCHEME, "error": str(error)}
    return out


def matches(claim: dict, tex: dict) -> bool:
    rec = (tex.get("regions") or {}).get(claim["id"], {})
    return bool(claim.get("source_sha256") and not rec.get("error")
                and claim.get("source_hash_scheme") == SCHEME == rec.get("scheme")
                and claim["source_sha256"] == rec.get("sha256"))


def same_revision(pin: str, revision: str) -> bool:
    """Whether an inventory's pin names the snapshot's revision: the same value, or an
    abbreviated commit hash (at least 7 hexadecimal digits) of it."""
    return pin == revision or bool(re.fullmatch(r"[0-9a-f]{7,40}", pin)
                                   and re.fullmatch(r"[0-9a-f]{40}", revision)
                                   and revision.startswith(pin))


def changed_line(claim: dict, rec: dict) -> str | None:
    """Where a passage differs from its pins, from the line digests both sides keep: the first
    changed line, by its place in the passage and in the file, or a change in its length."""
    old, new = claim.get("source_line_sha256"), rec.get("line_sha256")
    if not old or not new:
        return None
    for i, (a, b) in enumerate(zip(old, new)):
        if a != b:
            return (f"line {i + 1} of the passage (line {rec['start_line'] + i} of "
                    f"{rec['file']}) changed")
    if len(old) != len(new):
        return (f"the passage has {len(new)} lines, not {len(old)}: lines were "
                + ("added" if len(new) > len(old) else "removed") + " at its end")
    return None


def migration_plan(inventory: dict, paper: str, root: Path, revision: str) -> tuple[dict, list]:
    """Rehash only the original frozen snapshot; never edit a review or a paper revision."""
    result = deepcopy(inventory)
    changes = []
    for claim in result["claims"]:
        if claim["paper"] != paper or location(claim) is None:
            continue
        pin = claim.get("commit") or inventory.get("papers", {}).get(paper, {}).get("commit")
        if not pin or not same_revision(str(pin).removeprefix("arxiv:"), revision):
            raise RegionError(f"{claim['id']}: original paper revision must match {revision}")
        scheme = claim.get("source_hash_scheme")
        if scheme not in (None, SCHEME):
            raise RegionError(f"{claim['id']}: unknown source hash scheme {scheme!r}")
        region = extract(root, claim)
        expected = claim.get("source_sha256")
        if scheme == SCHEME:
            if expected != region.sha256:
                raise RegionError(f"{claim['id']}: region differs from its frozen hash")
            if claim.get("source_line_sha256") != region.line_sha256:
                # The same passage: add the line digests it was pinned without.
                claim["source_line_sha256"] = region.line_sha256
                changes.append({"claim": claim["id"], "old_sha256": expected,
                                "lines_added": True, **region.record()})
            continue
        name, line = location(claim)
        original = source_file(root, name).read_text(encoding="utf-8").split("\n")[line - 1]
        legacy = hashlib.sha256(" ".join(original.split()).encode("utf-8")).hexdigest()
        if not expected or expected != legacy:
            raise RegionError(f"{claim['id']}: legacy hash does not match the original snapshot")
        claim.update(source_sha256=region.sha256, source_hash_scheme=SCHEME,
                     source_line_sha256=region.line_sha256)
        changes.append({"claim": claim["id"], "old_sha256": expected, **region.record()})
    if not any(c["paper"] == paper for c in inventory["claims"]):
        raise RegionError(f"no claims for paper {paper}")
    return result, changes


def _indent(raw: bytes) -> int:
    """The indentation of a JSON file, so that a rewrite changes only the fields it updates."""
    m = re.search(rb"\n( +)\S", raw)
    return len(m.group(1)) if m else 2


def write_plan(path: Path, before: bytes, result: dict) -> None:
    """Atomically replace the inventory only if it is still the one that was planned, in its
    own indentation."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".source-regions-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=_indent(before))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(path.stat().st_mode & 0o777)
        if path.read_bytes() != before:
            raise RegionError("inventory changed while planning; rerun without --write")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


REVISION = re.compile(r"(?:arxiv:)?(?:[0-9a-f]{7,40}|[A-Za-z0-9./-]+v\d+)")


def folder(cfg, paper, spec: str, dest: Path) -> Path:
    """A copy, at `dest`, of the manuscript named by `spec`: a folder, or `git:REV`, the folder
    the configuration reads the paper from (`source = { path = ... }`) as committed at revision
    REV of the repository that holds it."""
    import dataclasses
    import io
    import subprocess
    import tarfile
    from .sources import acquire
    if spec.startswith("git:"):
        rev = spec[len("git:"):]
        if "path" not in paper.source:
            raise RegionError(f"{spec}: git:REV names a revision of the folder the paper is "
                              "read from, and this paper's source is not a folder")
        base = (cfg.root / paper.source["path"]).resolve()
        top = subprocess.run(["git", "-C", str(base), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True)
        if top.returncode != 0:
            raise RegionError(f"{spec}: {base} is not in a Git repository")
        rel = base.relative_to(Path(top.stdout.strip()).resolve()).as_posix()
        tree = f"{rev}:{rel}" if rel != "." else f"{rev}:"
        arch = subprocess.run(["git", "-C", top.stdout.strip(), "archive", "--format=tar",
                               tree], capture_output=True)
        if arch.returncode != 0:
            raise RegionError(f"{spec}: the folder {rel} cannot be read at revision {rev}: "
                              + arch.stderr.decode(errors="replace").strip())
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(arch.stdout)) as t:
            t.extractall(dest, filter="data")
        return dest
    path = Path(spec).resolve()
    if not path.is_dir():
        raise RegionError(f"{spec} is not a folder")
    snap = acquire(cfg, dataclasses.replace(paper, source={"path": str(path)}), dest)
    if snap.mode != "latex":
        raise RegionError(f"{spec} holds no LaTeX source")
    return snap.dir


def baseline(cfg, paper, inventory: dict, dest: Path, source: str | None = None,
             rev: str | None = None) -> tuple[Path, str]:
    """The manuscript at the revision the inventory was pinned at, and that revision.

    A Git or arXiv source is acquired at the configuration's pin. A folder (`source`, or a
    configuration that reads the paper from a folder, as a manuscript vendored into the
    project) has no revision of its own: it is the revision `rev`, else the one the
    configuration records for the folder (`source = { path = ..., rev = ... }`), else the one
    the inventory records under `papers`. Either way the claims' pins are verified against the snapshot
    before anything is planned, so a folder that does not hold that revision is refused."""
    from .sources import acquire
    recorded = ((inventory.get("papers") or {}).get(paper.id) or {}).get("commit")
    if source is None and "path" in paper.source:
        source = str((cfg.root / paper.source["path"]).resolve())
    if source is not None:
        revision = rev or (paper.source.get("rev") if "path" in paper.source else None) \
            or recorded
        if not revision:
            raise RegionError(
                f"the revision of {source} is not recorded: pass --rev REV, or record it as "
                f"papers.{paper.id}.commit in the inventory")
        if not REVISION.fullmatch(str(revision)):
            raise RegionError(f"{revision!r} is not a commit or a versioned arXiv identifier")
        return folder(cfg, paper, source, dest), str(revision).removeprefix("arxiv:")
    if rev is not None:
        raise RegionError("--rev names the revision of a folder given with --source")
    if "git" in paper.source:
        if not re.fullmatch(r"[0-9a-f]{40}", str(paper.source.get("rev", ""))):
            raise RegionError("the original revision must be a full Git commit, not a branch "
                              "or tag")
    snap = acquire(cfg, paper, dest)
    if not snap.revision or snap.mode != "latex":
        raise RegionError("needs a pinned LaTeX source snapshot")
    return snap.dir, snap.revision


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hash source regions at their original pinned revision")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--source", help="the manuscript at its pinned revision: a folder, or "
                        "git:REV for the configured folder as committed at REV (default: the "
                        "configured source)")
    parser.add_argument("--rev", help="the paper revision --source (or a configured folder) "
                        "holds (default: the inventory's papers.PAPER.commit)")
    parser.add_argument("--write", action="store_true", help="apply the verified plan (default: dry run)")
    args = parser.parse_args(argv)
    from .config import load
    try:
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        before = cfg.inventory.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-source-regions-") as temp:
            root, revision = baseline(cfg, paper, inventory, Path(temp) / paper.id,
                                      args.source, args.rev)
            result, changes = migration_plan(inventory, paper.id, root, revision)
        if args.write and changes:
            write_plan(cfg.inventory, before, result)
        print(json.dumps({"applied": args.write, "paper": paper.id, "changes": changes}, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"source regions: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
