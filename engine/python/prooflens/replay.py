"""A kernel replay with Comparator, recorded for the full assessment
(`machinechecked replay CONFIG`).

Comparator (github.com/leanprover/comparator) re-checks a project's proofs of a challenge's
statements in a fresh kernel, from the exported terms, apart from the build. This runs it in the
Lean project (`lake env comparator CONFIG`) and writes a record the assessment can trust: the
commit it ran on (a tree with uncommitted changes is refused, since a commit would not describe
it), the Lean version and the Lake manifest's hash it ran with, whether it passed, and the
theorems its configuration names (`theorem_names`), as replayed only when it passed. The
assessment counts the replay for a proof only when the record's commit and environment are the
audited project's (`assess.Assessor.replay`).
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .util import git_head, run, sha256_file, write_json

SCHEMA = "machinechecked/replay@1"


class ReplayError(RuntimeError):
    pass


LEAN_INPUT = (".lean", "lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain")


def lean_changes(lean_root: Path) -> list[str]:
    """Lean inputs (sources, lakefile, manifest, toolchain) that differ from the commit, changed
    or new. Other files (the replay record itself, say) do not change what is checked."""
    import subprocess
    r = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all"],
                       cwd=lean_root, capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        path = line[3:].split(" -> ")[-1]
        if path.endswith(LEAN_INPUT):
            out.append(path)
    return out


def unchanged_since(lean_root: Path, commit: str, head: str) -> str | None:
    """Why a replay made at `commit` does not cover `head`, or None when it does: `commit` is an
    ancestor of `head` and no Lean input of the project differs between them. (Committing the
    replay record makes a new commit; that alone changes nothing the replay checked.)"""
    import subprocess

    def git(*args):
        return subprocess.run(["git", *args], cwd=lean_root, capture_output=True, text=True)
    if git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return (f"commit {commit[:12]} is not in this clone's history (fetch more history to "
                "check that no Lean input changed since)")
    if git("merge-base", "--is-ancestor", commit, head).returncode != 0:
        return f"commit {commit[:12]} is not an ancestor of this one"
    d = git("diff", "--name-only", commit, head, "--", ".")
    if d.returncode != 0:
        return f"could not compare commit {commit[:12]} with this one"
    changed = [p for p in d.stdout.splitlines() if p.endswith(LEAN_INPUT)]
    if changed:
        return (f"Lean inputs changed since commit {commit[:12]} (" + ", ".join(changed[:3])
                + (", …" if len(changed) > 3 else "") + ")")
    return None


def replay(lean_root: Path, config: Path, out: Path, comparator: str = "comparator",
           lake: str = "lake", timeout: int = 6 * 3600) -> dict:
    """Run Comparator on `config` in the project at `lean_root` and write its record to `out`."""
    commit = git_head(lean_root)
    if commit is None:
        raise ReplayError(f"{lean_root} is not a Git repository: a replay is bound to a commit")
    changed = lean_changes(lean_root)
    if changed:
        raise ReplayError("the project's Lean inputs have uncommitted changes (" +
                          ", ".join(changed[:5]) + "): commit them first, so the replay is "
                          "bound to a commit that describes what it checked")
    try:
        conf = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ReplayError(f"{config}: not a Comparator configuration ({e})") from None
    names = conf.get("theorem_names")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ReplayError(f"{config}: no `theorem_names` list")
    r = run([lake, "env", comparator, str(config.resolve())], cwd=lean_root, timeout=timeout)
    passed = r.returncode == 0
    tc, lm = lean_root / "lean-toolchain", lean_root / "lake-manifest.json"
    rec = {"schema": SCHEMA, "checker": "comparator", "commit": commit, "dirty": False,
           "toolchain": tc.read_text().strip() if tc.exists() else None,
           "lake_manifest_sha256": sha256_file(lm) if lm.exists() else None,
           "config": str(config), "config_sha256": sha256_file(config),
           "passed": passed, "replayed": names if passed else [],
           "kernels": ["lean"] + (["nanoda"] if conf.get("enable_nanoda") else []),
           "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
           "output_tail": (r.stdout + r.stderr)[-4000:]}
    write_json(out, rec)
    return rec
