#!/usr/bin/env python3
"""Save and restore the Lean build output of a project as a GitHub Release asset.

    lean_cache.py save    PROJECT [--target T ...] [--pin-file F]   build, then archive the build
    lean_cache.py publish PROJECT REPO                              upload the saved archive
    lean_cache.py restore PROJECT REPO [--build]                    fetch a compatible ancestor

PROJECT is the Lean project directory (e.g. ../MyProject); REPO is `owner/name` of the GitHub
repository whose Releases hold the archives. The archive holds, relative to PROJECT's parent:

* PROJECT/.lake/build;
* the build of every package in PROJECT/.lake/packages that Mathlib's cache does not supply
  (Mathlib and its own dependencies come from `lake exe cache get`);
* the build of every sibling path dependency (e.g. ../LevyStochCalc).

`save` refuses a checkout whose Lean inputs have uncommitted changes (here or in a path
dependency) or whose path dependency differs from the pin file, runs `lake build` on the targets
and archives only after it succeeds. It writes `<name>.tar.zst`, `<name>.tar.zst.sha256` and
`<name>.json` (commit, toolchain, lake-manifest hash, platform, path-dependency commits, targets,
digest), with `<name>` = `<project>-<os>-<arch>-<commit>`. `publish` attaches them to the single
prerelease `build-cache` of REPO (created once; later uploads create no tag). `restore` keeps the
archives whose manifest matches this checkout (toolchain, lake manifest, platform, path-dependency
commits) and whose commit is an ancestor of HEAD, takes the nearest, verifies its SHA-256 against
the manifest and against GitHub's recorded digest, and unpacks it; `--build` then runs
`lake build --rehash`, which recomputes every input hash instead of trusting saved ones, so Lake
rebuilds exactly what changed.

A restored build is trusted as built: Lake does not re-check the proofs in it. That the build
output corresponds to the sources is Lake's trace check (with --rehash) and the pin checks;
re-checking the proofs is the job of a kernel replay (Comparator).

The token is read from PROOFLENS_GH_TOKEN (then GITHUB_TOKEN); it is passed to curl in a header
and never written to disk. Public repositories need no token to restore.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RELEASE = "build-cache"
LEAN_INPUTS = ("*.lean", "lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain")
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def sh(cmd, cwd=None, check=True, capture=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        sys.exit(f"{' '.join(map(str, cmd))} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip() if capture else ""


def token() -> str | None:
    return os.environ.get("PROOFLENS_GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def curl(args: list[str], auth: bool = True,
         accept: str = "application/vnd.github+json") -> subprocess.CompletedProcess:
    hdr = ["-H", f"Accept: {accept}", "-H", "X-GitHub-Api-Version: 2022-11-28"]
    tok = token() if auth else None
    if tok:
        hdr += ["-H", f"Authorization: Bearer {tok}"]
    return subprocess.run(["curl", "-sS", "-L", "--fail-with-body", *hdr, *args],
                          capture_output=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_supplied(project: Path) -> set[str]:
    """Mathlib and the packages of Mathlib's own manifest: `lake exe cache get` supplies them."""
    m = project / ".lake" / "packages" / "mathlib" / "lake-manifest.json"
    names = {"mathlib"}
    if m.exists():
        names |= {p["name"] for p in json.loads(m.read_text())["packages"]}
    return names


def path_deps(project: Path) -> list[Path]:
    man = json.loads((project / "lake-manifest.json").read_text())
    return [(project / p["dir"]).resolve() for p in man["packages"] if p.get("type") == "path"]


def fingerprint(project: Path) -> dict:
    """What a cached build must agree with to be used here."""
    return {
        "toolchain": (project / "lean-toolchain").read_text().strip(),
        "lake_manifest_sha256": sha256(project / "lake-manifest.json"),
        "platform": f"{platform.system()}-{platform.machine()}",
        "path_dependencies": {d.name: sh(["git", "rev-parse", "HEAD"], cwd=d)
                              for d in path_deps(project)},
    }


def build_dirs(project: Path) -> list[str]:
    parent = project.parent
    out = [project / ".lake" / "build"]
    skip = cache_supplied(project)
    pk = project / ".lake" / "packages"
    if pk.exists():
        out += [p / ".lake" / "build" for p in sorted(pk.iterdir()) if p.name not in skip]
    out += [d / ".lake" / "build" for d in path_deps(project)]
    return [str(p.relative_to(parent)) for p in out if p.is_dir()]


def asset_name(project: Path, commit: str) -> str:
    return (f"{project.name.lower()}-{platform.system().lower()}-{platform.machine().lower()}-"
            f"{commit}")


def dirty_lean_inputs(repo: Path) -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *LEAN_INPUTS], cwd=repo)
    return [l for l in out.splitlines() if l.strip()]


def save(a):
    project = Path(a.project).resolve()
    commit = sh(["git", "rev-parse", "HEAD"], cwd=project)
    for repo in [project, *path_deps(project)]:
        d = dirty_lean_inputs(repo)
        if d:
            sys.exit(f"{repo.name} has uncommitted Lean inputs; commit them first:\n  "
                     + "\n  ".join(d))
    if a.pin_file:
        pin = [l.strip() for l in (project / a.pin_file).read_text().splitlines()
               if l.strip() and not l.lstrip().startswith("#")][-1]
        deps = {d.name: sh(["git", "rev-parse", "HEAD"], cwd=d) for d in path_deps(project)}
        if pin not in deps.values():
            sys.exit(f"no path dependency is checked out at the pin {pin}: {deps}")
    t0 = time.time()
    r = subprocess.run(["lake", "build", *a.target], cwd=project)
    if r.returncode != 0:
        sys.exit("lake build failed; nothing saved")
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    name = asset_name(project, commit)
    dirs = build_dirs(project)
    arc = out / f"{name}.tar.zst"
    sh(["tar", "-C", str(project.parent), "-I", "zstd -T0 -6", "-cf", str(arc), *dirs])
    digest = sha256(arc)
    (out / f"{name}.tar.zst.sha256").write_text(f"{digest}  {arc.name}\n")
    manifest = {"commit": commit, "project": project.name, "targets": a.target or ["(default)"],
                "dirs": dirs, "sha256": digest, "size": arc.stat().st_size,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **fingerprint(project)}
    (out / f"{name}.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"saved {name}: {len(dirs)} build directories, {arc.stat().st_size / 1e6:.0f} MB, "
          f"sha256 {digest} ({time.time() - t0:.0f}s)")


def release(repo: str, project: Path) -> dict:
    """The `build-cache` prerelease, created once at the default branch."""
    r = curl([f"{API}/repos/{repo}/releases/tags/{RELEASE}"])
    if r.returncode == 0:
        return json.loads(r.stdout)
    body = json.dumps({"tag_name": RELEASE, "name": "Lean build cache", "prerelease": True,
                       "make_latest": "false",
                       "body": "Archives of Lean build output, one per commit "
                               "(scripts/lean_cache.py of ProofLens). Restored builds are "
                               "trusted as built; proofs are re-checked only by a kernel "
                               "replay."})
    r = curl(["-X", "POST", "-H", "Content-Type: application/json",
              f"{API}/repos/{repo}/releases", "-d", body])
    if r.returncode != 0:
        sys.exit(f"release creation failed: {r.stdout.decode()} {r.stderr.decode()}")
    return json.loads(r.stdout)


def publish(a):
    project = Path(a.project).resolve()
    if not token():
        sys.exit("no token: set PROOFLENS_GH_TOKEN to publish")
    commit = sh(["git", "rev-parse", "HEAD"], cwd=project)
    out = Path(a.out).resolve()
    name = asset_name(project, commit)
    manifest = json.loads((out / f"{name}.json").read_text())
    if sha256(out / f"{name}.tar.zst") != manifest["sha256"]:
        sys.exit("the saved archive does not match its manifest")
    rel = release(a.repo, project)
    have = {x["name"]: x for x in rel.get("assets", [])}
    for fname in (f"{name}.tar.zst", f"{name}.tar.zst.sha256", f"{name}.json"):
        if fname in have:
            print(f"{RELEASE}: {fname} already published")
            continue
        ctype = "application/zstd" if fname.endswith(".zst") else "text/plain"
        t0 = time.time()
        r = curl(["-X", "POST", "-H", f"Content-Type: {ctype}", "--data-binary",
                  f"@{out / fname}",
                  f"{UPLOADS}/repos/{a.repo}/releases/{rel['id']}/assets?name={fname}"])
        if r.returncode != 0:
            sys.exit(f"upload of {fname} failed: {r.stdout.decode()[:500]} {r.stderr.decode()}")
        asset = json.loads(r.stdout)
        if fname.endswith(".zst") and asset.get("digest") and \
                asset["digest"] != f"sha256:{manifest['sha256']}":
            sys.exit(f"GitHub's digest {asset['digest']} differs from the local sha256")
        print(f"{RELEASE}: published {fname} ({time.time() - t0:.0f}s)"
              + (f", GitHub digest {asset['digest']}" if asset.get("digest") else ""))


def cache_assets(repo: str) -> dict:
    r = curl([f"{API}/repos/{repo}/releases/tags/{RELEASE}"], auth=bool(token()))
    if r.returncode != 0:
        return {}
    return {x["name"]: x for x in json.loads(r.stdout).get("assets", [])}


def download(asset: dict, dest: Path):
    r = curl(["-o", str(dest), asset["url"]], auth=bool(token()), accept="application/octet-stream")
    if r.returncode != 0:
        sys.exit(f"download of {asset['name']} failed: {r.stderr.decode()}")


def restore(a):
    project = Path(a.project).resolve()
    here = fingerprint(project)
    assets = cache_assets(a.repo)
    prefix = f"{project.name.lower()}-{platform.system().lower()}-{platform.machine().lower()}-"
    best = None
    with tempfile.TemporaryDirectory() as tmp:
        for name, asset in sorted(assets.items()):
            if not (name.startswith(prefix) and name.endswith(".json")):
                continue
            stem = name[:-5]
            if f"{stem}.tar.zst" not in assets:
                continue
            download(asset, Path(tmp) / name)
            man = json.loads((Path(tmp) / name).read_text())
            mismatch = [k for k in here if man.get(k) != here[k]]
            if mismatch:
                print(f"skip {stem}: differs in {', '.join(mismatch)}")
                continue
            if subprocess.run(["git", "merge-base", "--is-ancestor", man["commit"], "HEAD"],
                              cwd=project).returncode != 0:
                print(f"skip {stem}: not an ancestor of HEAD")
                continue
            dist = int(sh(["git", "rev-list", "--count", f"{man['commit']}..HEAD"], cwd=project))
            if best is None or dist < best[0]:
                best = (dist, stem, man)
        if best is None:
            sys.exit("no compatible cached build; build from source")
        dist, stem, man = best
        arc = Path(tmp) / f"{stem}.tar.zst"
        t0 = time.time()
        download(assets[f"{stem}.tar.zst"], arc)
        got = sha256(arc)
        if got != man["sha256"]:
            sys.exit(f"sha256 mismatch: {got} != {man['sha256']}; build from source")
        gh = assets[f"{stem}.tar.zst"].get("digest")
        if gh and gh != f"sha256:{got}":
            sys.exit(f"sha256 differs from GitHub's recorded digest {gh}; build from source")
        sh(["tar", "-C", str(project.parent), "-I", "zstd -T0", "-xf", str(arc)])
    print(f"restored {stem} ({dist} commits behind HEAD, sha256 {got[:16]}…) "
          f"in {time.time() - t0:.0f}s")
    (project / ".lake" / "lean-cache-restored.json").write_text(json.dumps(
        {"asset": stem, "commit": man["commit"], "sha256": got, "commits_behind": dist,
         "targets": man.get("targets")}, indent=1) + "\n")
    if a.build:
        targets = [t for t in man.get("targets", []) if t != "(default)"]
        subprocess.run(["lake", "build", "--rehash", *targets], cwd=project, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("project")
    s.add_argument("--target", action="append", default=[])
    s.add_argument("--pin-file")
    s.add_argument("--out", default=".lean-cache")
    s.set_defaults(func=save)
    u = sub.add_parser("publish")
    u.add_argument("project")
    u.add_argument("repo")
    u.add_argument("--out", default=".lean-cache")
    u.set_defaults(func=publish)
    r = sub.add_parser("restore")
    r.add_argument("project")
    r.add_argument("repo")
    r.add_argument("--build", action="store_true")
    r.set_defaults(func=restore)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
