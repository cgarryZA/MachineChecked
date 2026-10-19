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

Comparator's own trust model also asks for isolation: `landrun` sandboxes the solution's build,
and the whole run goes under `systemd-run --user --property=RestrictAddressFamilies=~AF_UNIX`,
in an environment where the solution was not compiled before. This module does not start that
guard; the record says how the run went (`conditions`): whether the process could open a Unix
socket (the guard forbids it, for Comparator too, which inherits the restriction), the systemd
unit it ran in, the Landlock ABI of the kernel, and where `comparator`, `landrun`,
`lean4export` and, when enabled, `nanoda_bin` were, with their SHA-256 (and Comparator's commit
when it was built in a Git checkout).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
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


GUARD = "RestrictAddressFamilies=~AF_UNIX"


def af_unix_blocked() -> bool:
    """Whether this process may not open a Unix socket, as under Comparator's guard."""
    import errno
    import socket
    if not hasattr(socket, "AF_UNIX"):
        return False
    try:
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
    except OSError as e:
        return e.errno in (errno.EAFNOSUPPORT, errno.EPERM, errno.EACCES)
    return False


def systemd_unit() -> str | None:
    """The systemd unit this process runs in (`run-u12.service` under `systemd-run`), if any."""
    try:
        text = Path("/proc/self/cgroup").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        path = line.split(":", 2)[-1]
        units = [p for p in path.split("/") if re.search(r"\.(service|scope)$", p)]
        if units:
            return units[-1]
    return None


def landlock_abi() -> int | None:
    """The Landlock ABI version of the running kernel (what `landrun` sandboxes with), or None
    when it has none."""
    import platform
    if platform.system() != "Linux":
        return None
    try:
        import ctypes
        # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION)
        v = ctypes.CDLL(None, use_errno=True).syscall(444, None, 0, 1)
    except (OSError, AttributeError):
        return None
    return v if v > 0 else None


def program(name: str | None, env_var: str | None = None,
            cwd: Path | None = None) -> dict | None:
    """Where a program is (the environment variable Comparator reads first, else `PATH`; a
    relative path from `cwd`), with its SHA-256 and, for one built in the Git checkout of a
    Lake project (as Comparator is), that checkout's commit."""
    import subprocess
    name = (os.environ.get(env_var) if env_var else None) or name
    if name and cwd is not None and os.sep in name and not os.path.isabs(name):
        name = str(cwd / name)
    path = shutil.which(name) if name else None
    if path is None:
        return None
    path = os.path.realpath(path)
    r = subprocess.run(["git", "rev-parse", "--show-toplevel", "HEAD"],
                       cwd=os.path.dirname(path), capture_output=True, text=True)
    top, _, head = r.stdout.strip().partition("\n")
    lake = r.returncode == 0 and any((Path(top) / f).is_file()
                                     for f in ("lakefile.toml", "lakefile.lean"))
    return {"path": path, "sha256": sha256_file(Path(path)), "commit": head if lake else None}


def conditions(comparator: str, conf: dict, cwd: Path) -> dict:
    """How a replay in `cwd` runs: the guard observed on this process, and the programs used."""
    blocked = af_unix_blocked()
    out = {"guard": GUARD if blocked else "none", "af_unix_blocked": blocked,
           "systemd_unit": systemd_unit(), "landlock_abi": landlock_abi(),
           "comparator": program(comparator, cwd=cwd),
           "landrun": program("landrun", "COMPARATOR_LANDRUN"),
           "lean4export": program("lean4export", "COMPARATOR_LEAN4EXPORT")}
    if conf.get("enable_nanoda"):
        out["nanoda"] = program("nanoda_bin", "COMPARATOR_NANODA")
    kernels = conf.get("external_kernels")
    if isinstance(kernels, dict):
        out["external_kernels"] = {k: program(v[0], cwd=cwd) if isinstance(v, list) and v
                                   and isinstance(v[0], str) else None
                                   for k, v in kernels.items()}
    return out


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
    how = conditions(comparator, conf, lean_root)
    r = run([lake, "env", comparator, str(config.resolve())], cwd=lean_root, timeout=timeout)
    passed = r.returncode == 0
    tc, lm = lean_root / "lean-toolchain", lean_root / "lake-manifest.json"
    rec = {"schema": SCHEMA, "checker": "comparator", "commit": commit, "dirty": False,
           "toolchain": tc.read_text().strip() if tc.exists() else None,
           "lake_manifest_sha256": sha256_file(lm) if lm.exists() else None,
           "config": str(config), "config_sha256": sha256_file(config),
           "passed": passed, "replayed": names if passed else [],
           "kernels": ["lean"] + (["nanoda"] if conf.get("enable_nanoda") else []),
           "conditions": how,
           "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
           "output_tail": (r.stdout + r.stderr)[-4000:]}
    write_json(out, rec)
    return rec
