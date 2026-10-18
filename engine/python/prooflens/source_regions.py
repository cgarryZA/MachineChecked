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

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def record(self) -> dict:
        # The evidence needs bounds and a digest, not an additional public copy of the text.
        return {"file": self.file, "start_line": self.start_line, "end_line": self.end_line,
                "start_column": self.start_column, "end_column": self.end_column,
                "kind": self.kind, "scheme": SCHEME, "sha256": self.sha256}


def positive(value, name: str) -> int:
    if type(value) is not int or value < 1:
        raise RegionError(f"{name} must be a positive integer")
    return value


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
        return Region(name, line, end_line, start_col, end_col, "span", text[start:end])
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
                              end_column, "environment", text[start:end])
        raise RegionError("source environment has no matching end")
    if first.lstrip().startswith(r"\begin"):
        raise RegionError("unsupported or malformed environment; select an explicit source region")
    if not first.strip() or first.lstrip().startswith("%"):
        raise RegionError("source line is blank or a comment; select the actual passage")
    return Region(name, line, line, 1, len(first) + 1, "line", first)


def collect(inventory: dict, paper: str, root: Path) -> dict:
    """One record per claim, including extraction errors; shared start lines do not collide."""
    out = {}
    for claim in inventory["claims"]:
        if claim["paper"] != paper:
            continue
        try:
            if location(claim) is None:
                continue
            out[claim["id"]] = extract(root, claim).record()
        except (RegionError, OSError, UnicodeError) as error:
            out[claim["id"]] = {"scheme": SCHEME, "error": str(error)}
    return out


def matches(claim: dict, tex: dict) -> bool:
    rec = (tex.get("regions") or {}).get(claim["id"], {})
    return bool(claim.get("source_sha256") and not rec.get("error")
                and claim.get("source_hash_scheme") == SCHEME == rec.get("scheme")
                and claim["source_sha256"] == rec.get("sha256"))


def migration_plan(inventory: dict, paper: str, root: Path, revision: str) -> tuple[dict, list]:
    """Rehash only the original frozen snapshot; never edit a review or a paper revision."""
    result = deepcopy(inventory)
    changes = []
    for claim in result["claims"]:
        if claim["paper"] != paper or location(claim) is None:
            continue
        pin = claim.get("commit") or inventory.get("papers", {}).get(paper, {}).get("commit")
        if not pin or str(pin).removeprefix("arxiv:") != revision:
            raise RegionError(f"{claim['id']}: original paper revision must match {revision}")
        scheme = claim.get("source_hash_scheme")
        if scheme not in (None, SCHEME):
            raise RegionError(f"{claim['id']}: unknown source hash scheme {scheme!r}")
        region = extract(root, claim)
        expected = claim.get("source_sha256")
        if scheme == SCHEME:
            if expected != region.sha256:
                raise RegionError(f"{claim['id']}: region differs from its frozen hash")
            continue
        name, line = location(claim)
        original = source_file(root, name).read_text(encoding="utf-8").split("\n")[line - 1]
        legacy = hashlib.sha256(" ".join(original.split()).encode("utf-8")).hexdigest()
        if not expected or expected != legacy:
            raise RegionError(f"{claim['id']}: legacy hash does not match the original snapshot")
        claim.update(source_sha256=region.sha256, source_hash_scheme=SCHEME)
        changes.append({"claim": claim["id"], "old_sha256": expected, **region.record()})
    if not any(c["paper"] == paper for c in inventory["claims"]):
        raise RegionError(f"no claims for paper {paper}")
    return result, changes


def write_plan(path: Path, before: bytes, result: dict) -> None:
    """Atomically replace the inventory only if it is still the one that was planned."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".source-regions-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(result, handle, ensure_ascii=False, indent=2)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Hash source regions at their original pinned revision")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--write", action="store_true", help="apply the verified plan (default: dry run)")
    args = parser.parse_args(argv)
    from .config import load
    from .sources import acquire
    try:
        cfg = load(args.config)
        paper = cfg.paper(args.paper)
        if "git" in paper.source:
            if not re.fullmatch(r"[0-9a-f]{40}", str(paper.source.get("rev", ""))):
                raise RegionError("migration needs the original full Git commit, not a branch or tag")
        elif "arxiv" not in paper.source:
            raise RegionError("migration needs the original pinned Git/arXiv source, not a working folder")
        before = cfg.inventory.read_bytes()
        inventory = json.loads(before)
        with tempfile.TemporaryDirectory(prefix="machinechecked-source-regions-") as temp:
            snap = acquire(cfg, paper, Path(temp) / paper.id)
            if not snap.revision or snap.mode != "latex":
                raise RegionError("migration needs a pinned LaTeX source snapshot")
            result, changes = migration_plan(inventory, paper.id, snap.dir, snap.revision)
        if args.write and changes:
            write_plan(cfg.inventory, before, result)
        print(json.dumps({"applied": args.write, "paper": paper.id, "changes": changes}, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"source regions: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
