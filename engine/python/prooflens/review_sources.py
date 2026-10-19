"""The paper text a review marker was made against.

A review reads a claim's source passage beside a Lean declaration. A marker records, for each
claim whose passage was shown to the reviewer, the digest of that passage as read:
`source=<claim id>@<sha256>`, one attribute per claim, the digest being the claim's pin
(`source_sha256`, scheme `tex-region-v1` for a line-located claim). A proposition's review reads
the claims whose clauses state it; a definition's review reads the definition claims that name
it. A declaration no claim names (a definition only in a closure) has no passage, and its marker
records none.

A reading counts for a claim only while the digest it records for that claim is the claim's
current pin: a changed text, or a claim the marker does not record, reopens the review for that
claim.

A marker written before this attribute existed records no digests. It counts for a claim only
while the claim's pin is shown unchanged since the marker was written: Git gives the commit that
wrote the marker's line, and every version of the inventory from that commit to the working tree
must keep the claim's passage (the same digest under the same scheme, or a legacy pin moved to
`tex-region-v1` at the same paper revision and file). When the history cannot show it (no Git
repository, a shallow clone, a claim without a pin at that commit), the marker is "reviewed
before source pins were recorded" and does not count. `python -m prooflens.review_sources
--config FILE --write` adds the digests of the claims whose passages are shown unchanged, and
nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from .source_regions import SCHEME, same_revision

SOURCE = re.compile(r"(?:^|\s)source=([^\s@]+)@([0-9a-f]{64})(?=\s|$)")


# -- what a review reads ------------------------------------------------------------------------

def reading_claims(inventory: dict, target: str, name: str) -> list[dict]:
    """The claims whose passage a review of the declaration `name` reads."""
    out = []
    for c in inventory.get("claims", []):
        for cl in c.get("clauses") or []:
            if (target == "spec" and cl.get("spec") == name) or \
                    (target == "def" and name in (cl.get("defs") or [])):
                out.append(c)
                break
    return out


def digests(inventory: dict, target: str, name: str) -> dict[str, str]:
    """The digests a current review of `name` records: claim id to the claim's source pin, for
    the pinned claims it reads."""
    return {c["id"]: c["source_sha256"] for c in reading_claims(inventory, target, name)
            if c.get("source_sha256")}


def attribute(values: dict[str, str]) -> str:
    """The marker attributes recording `values` (empty when there is no passage)."""
    return " ".join(f"source={cid}@{sha}" for cid, sha in sorted(values.items()))


def parse(attrs: str) -> dict[str, str] | None:
    """The digests recorded by a marker's attributes, by claim; None when it records none."""
    found = SOURCE.findall(attrs or "")
    return dict(found) if found else None


# -- markers written before the attribute -------------------------------------------------------

def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _file_of(location: str | None) -> str:
    head, _, tail = (location or "").rpartition(":")
    return head if head and tail.isdigit() else (location or "")


def _revision(claim: dict, inventory: dict) -> str:
    pin = claim.get("commit") or ((inventory.get("papers") or {}).get(claim.get("paper"), {})
                                  .get("commit"))
    return str(pin or "").removeprefix("arxiv:")


def _same_revision(a: str, b: str) -> bool:
    return bool(a and b) and (same_revision(a, b) or same_revision(b, a))


def same_passage(old: dict, old_inv: dict, new: dict, new_inv: dict) -> bool:
    """Whether two pins of one claim hold the same text: the same digest under the same scheme,
    or a legacy pin moved to `tex-region-v1` at the same paper revision and in the same file
    (the pin of the same text, rehashed at its original revision)."""
    so, sn = old.get("source_hash_scheme"), new.get("source_hash_scheme")
    if so == sn:
        return old.get("source_sha256") == new.get("source_sha256")
    return (so is None and sn == SCHEME
            and _same_revision(_revision(old, old_inv), _revision(new, new_inv))
            and _file_of(old.get("location")) == _file_of(new.get("location")))


class History:
    """The Git history of the review files and the inventory, read once per assessment."""

    def __init__(self, root: Path | None, inventory: Path | None, current: dict):
        self.root, self.current = Path(root or "."), current
        # Without a project root and inventory file there is no history to read.
        top = _git(self.root, "rev-parse", "--show-toplevel") if root and inventory else None
        self.top = Path(top.strip()) if top else None
        self.inv_rel = None
        self.head = None
        self.shallow: set[str] = set()
        if self.top:
            try:
                self.inv_rel = Path(inventory).resolve().relative_to(self.top.resolve()).as_posix()
            except ValueError:
                self.top = None
        if self.top:
            head = _git(self.top, "rev-parse", "--verify", "-q", "HEAD")
            self.head = head.strip() if head else None
            sh = _git(self.top, "rev-parse", "--git-path", "shallow")
            if sh:
                p = Path(sh.strip())
                p = p if p.is_absolute() else self.top / p
                if p.exists():
                    self.shallow = set(p.read_text().split())
        self._blame: dict[str, dict[int, str] | None] = {}
        self._inv: dict[str, dict | None] = {}
        self._since: dict[str, list[str] | None] = {}

    def commit_of(self, file: str, line: int) -> str | None:
        """The commit that wrote line `line` of the review file `file` (relative to the project
        root), following moved and copied lines; HEAD for a line not yet committed."""
        if self.top is None or self.head is None:
            return None
        if file not in self._blame:
            path = (self.root / file).resolve()
            out = _git(self.top, "blame", "--porcelain", "-w", "-M", "-C", "--",
                       os.path.relpath(path, self.top))
            lines = None
            if out is not None:
                lines = {}
                for row in out.split("\n"):
                    m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", row)
                    if m:
                        lines[int(m.group(2))] = m.group(1)
            self._blame[file] = lines
        lines = self._blame[file]
        sha = lines.get(line) if lines else None
        if sha is None or sha in self.shallow:
            return None
        return self.head if set(sha) == {"0"} else sha

    def inventory_at(self, commit: str) -> dict | None:
        if commit not in self._inv:
            out = _git(self.top, "show", f"{commit}:{self.inv_rel}")
            try:
                self._inv[commit] = json.loads(out) if out is not None else None
            except ValueError:
                self._inv[commit] = None
        return self._inv[commit]

    def since(self, commit: str) -> list[str] | None:
        """The commits after `commit` up to HEAD that changed the inventory, oldest first."""
        if commit not in self._since:
            out = _git(self.top, "rev-list", "--topo-order", "--reverse", f"{commit}..HEAD",
                       "--", self.inv_rel)
            self._since[commit] = out.split() if out is not None else None
        return self._since[commit]

    def state(self, file: str, line: int, cid: str) -> str:
        """Whether the passage of claim `cid` is unchanged since the marker at `file:line` was
        written: `current`, `changed` or `unrecorded`."""
        commit = self.commit_of(file, line)
        if commit is None:
            return "unrecorded"
        later = self.since(commit)
        if self.inventory_at(commit) is None or later is None:
            return "unrecorded"
        versions = [self.inventory_at(commit)] + [self.inventory_at(c) for c in later] + \
            [self.current]
        if any(inv is None for inv in versions[1:-1]):
            return "unrecorded"
        chain = [(inv, next((c for c in inv.get("claims", []) if c["id"] == cid), None))
                 for inv in versions]
        first = chain[0][1]
        if first is None or not first.get("source_sha256"):
            return "unrecorded"
        for (pi, p), (qi, q) in zip(chain, chain[1:]):
            # A claim removed from the inventory, or unpinned, and restored later is a changed
            # passage.
            if q is None or not q.get("source_sha256") or not same_passage(p, pi, q, qi):
                return "changed"
        return "current"


# -- the migration ------------------------------------------------------------------------------

def migration(cfg, inventory: dict | None = None) -> tuple[list[dict], list[dict]]:
    """For each marker without digests, the digests of the claims whose passages are shown
    unchanged since it was written (the attributes to add), and the claims left out, with why."""
    from .reviews import load_reviews
    inv = inventory if inventory is not None else json.loads(
        cfg.inventory.read_text(encoding="utf-8"))
    reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
    hist = History(cfg.root, cfg.inventory, inv)
    add, keep = [], []
    for r in reviews:
        if r.source is not None:
            continue
        want = digests(inv, r.target, r.name)
        row = {"file": r.file, "line": r.line, "target": r.target, "name": r.name, "by": r.by}
        shown = {}
        for cid, sha in want.items():
            state = hist.state(r.file, r.line, cid)
            if state == "current":
                shown[cid] = sha
            else:
                keep.append({**row, "claim": cid, "state": state, "reason": (
                    f"the source text of {cid} changed since the reading" if state == "changed"
                    else "reviewed before source pins were recorded: the history does not show "
                         "the passage unchanged")})
        if shown:
            add.append({**row, "claims": sorted(shown), "attribute": attribute(shown)})
    return add, keep


def apply(cfg, add: list[dict]) -> None:
    """Add each attribute to its marker, in place."""
    by_file: dict[str, list[dict]] = {}
    for a in add:
        by_file.setdefault(a["file"], []).append(a)
    for rel, rows in by_file.items():
        path = cfg.root / rel
        lines = path.read_text(encoding="utf-8").split("\n")
        for a in rows:
            i = a["line"] - 1
            pat = re.compile(r"(<!--\s*" + a["target"] + r"-review:\s*" + re.escape(a["name"])
                             + r"\s[^>]*?)(\s*-->)")
            m = pat.search(lines[i])
            if not m or " source=" in m.group(1):
                raise RuntimeError(f"{rel}:{a['line']}: the marker of {a['name']} is not there")
            lines[i] = lines[i][:m.end(1)] + " " + a["attribute"] + lines[i][m.end(1):]
        path.write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Add the source digests to review markers written without them, where the "
                    "history shows the passage unchanged since the marker was written")
    parser.add_argument("--config", required=True)
    parser.add_argument("--write", action="store_true", help="edit the review files (default: "
                        "dry run)")
    args = parser.parse_args(argv)
    from .config import load
    cfg = load(args.config)
    add, keep = migration(cfg)
    if args.write and add:
        apply(cfg, add)
    print(json.dumps({"applied": args.write, "added": add, "left": keep}, indent=2,
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
