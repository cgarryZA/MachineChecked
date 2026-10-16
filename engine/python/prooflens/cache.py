"""Save and restore a Lean project's build output as GitHub release assets
(`machinechecked cache save|publish|restore`).

A project's build can take hours; a restore takes minutes. `save` builds the project, refuses a
checkout whose Lean inputs have uncommitted changes (here or in a path dependency), and archives
the build output (`tar.zst`):

* the project's `.lake/build`;
* the build of every package in `.lake/packages` that Mathlib's cache does not supply (Mathlib
  and its own dependencies come from `lake exe cache get`);
* the build of every path dependency (`../Other`).

Beside the archive it writes a manifest (`<name>.json`): the repository and commit, the
toolchain, the platform, the `lake-manifest.json` SHA-256, the path dependencies' commits, the
targets, and the archive's SHA-256; an archive over GitHub's 2 GiB asset limit is split into
parts, each with its own SHA-256. `<name>` is `<project>-<os>-<arch>-<commit>`.

`publish` attaches them to the single prerelease `build-cache` of a repository (created once;
uploads make no tag), with the project's licence and notice files: a cache of someone else's
project is a redistribution of it. `restore` keeps the archives whose manifest matches this
checkout (toolchain, lake manifest, platform, path dependencies) and whose commit is an ancestor
of HEAD, takes the nearest, checks every SHA-256 (against the manifest and against GitHub's
recorded digest), and unpacks it; with `--build` it then runs `lake build --rehash`, which
recomputes every input's hash instead of trusting the saved ones, so Lake rebuilds exactly what
changed. `--from DIR` restores from a directory of saved assets instead of a release.

A restored build is trusted as built: Lake does not re-check the proofs in it. That the build
output corresponds to the sources is Lake's trace check and the checks above; re-checking the
proofs is the job of a kernel replay (Comparator).

The token is read from MACHINECHECKED_GH_TOKEN (then PROOFLENS_GH_TOKEN, GITHUB_TOKEN). It is
given to curl on its standard input, so it is never on a command line or on disk. Restoring
from a public repository needs no token.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

RELEASE = "build-cache"
LEAN_INPUTS = ("*.lean", "lakefile.toml", "lakefile.lean", "lake-manifest.json", "lean-toolchain")
LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "NOTICE", "NOTICE.md",
                 "NOTICE.txt")
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
PART = 1900 * 1024 * 1024  # under GitHub's 2 GiB limit per release asset


class CacheError(RuntimeError):
    pass


def _sh(cmd, cwd=None) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise CacheError(f"{' '.join(map(str, cmd))} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def token() -> str | None:
    return (os.environ.get("MACHINECHECKED_GH_TOKEN") or os.environ.get("PROOFLENS_GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN"))


def curl(args: list[str], auth: bool = True,
         accept: str = "application/vnd.github+json") -> subprocess.CompletedProcess:
    """curl with GitHub's headers. The token goes in a header read from standard input
    (`--config -`), never in the arguments, which any local user could read."""
    hdr = ["-H", f"Accept: {accept}", "-H", "X-GitHub-Api-Version: 2022-11-28"]
    tok = token() if auth else None
    config = f'header = "Authorization: Bearer {tok}"\n' if tok else ""
    return subprocess.run(["curl", "-sS", "-L", "--fail-with-body", "--config", "-", *hdr, *args],
                          input=config.encode(), capture_output=True)


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
        "path_dependencies": {d.name: _sh(["git", "rev-parse", "HEAD"], cwd=d)
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


def asset_prefix(project: Path) -> str:
    return f"{project.name.lower()}-{platform.system().lower()}-{platform.machine().lower()}-"


def repository(project: Path) -> str | None:
    """The project's GitHub repository (`owner/repo`), from its `origin` remote."""
    from .audit import github_repository
    return github_repository(project)


def dirty_lean_inputs(repo: Path) -> list[str]:
    out = _sh(["git", "status", "--porcelain", "--", *LEAN_INPUTS], cwd=repo)
    return [l for l in out.splitlines() if l.strip()]


def _split(arc: Path, size: int = PART) -> list[dict]:
    """Split an archive into parts of at most `size` bytes; the archive is removed."""
    parts = []
    with open(arc, "rb") as f:
        for i in range(10_000):
            chunk = f.read(size)
            if not chunk:
                break
            p = arc.with_name(f"{arc.name}.part{i:03d}")
            p.write_bytes(chunk)
            parts.append({"name": p.name, "sha256": hashlib.sha256(chunk).hexdigest(),
                          "size": len(chunk)})
    arc.unlink()
    return parts


def save(project: Path, out: Path, targets: list[str], pin_file: str | None = None,
         lake: str = "lake", part_size: int = PART, log=print) -> dict:
    """Build `targets` (the default ones when empty) and archive the build output in `out`."""
    commit = _sh(["git", "rev-parse", "HEAD"], cwd=project)
    for repo in [project, *path_deps(project)]:
        d = dirty_lean_inputs(repo)
        if d:
            raise CacheError(f"{repo.name} has uncommitted Lean inputs; commit them first:\n  "
                             + "\n  ".join(d))
    if pin_file:
        pin = [l.strip() for l in (project / pin_file).read_text().splitlines()
               if l.strip() and not l.lstrip().startswith("#")][-1]
        deps = {d.name: _sh(["git", "rev-parse", "HEAD"], cwd=d) for d in path_deps(project)}
        if pin not in deps.values():
            raise CacheError(f"no path dependency is checked out at the pin {pin}: {deps}")
    t0 = time.time()
    if subprocess.run([lake, "build", *targets], cwd=project).returncode != 0:
        raise CacheError("lake build failed; nothing saved")
    out.mkdir(parents=True, exist_ok=True)
    name = asset_prefix(project) + commit
    dirs = build_dirs(project)
    arc = out / f"{name}.tar.zst"
    _sh(["tar", "-C", str(project.parent), "-I", "zstd -T0 -6", "-cf", str(arc), *dirs])
    digest, size = sha256(arc), arc.stat().st_size
    parts = _split(arc, part_size) if size > part_size else None
    if parts is None:
        (out / f"{name}.tar.zst.sha256").write_text(f"{digest}  {arc.name}\n")
    licences = [f for f in LICENCE_FILES if (project / f).is_file()]
    manifest = {"commit": commit, "project": project.name, "repository": repository(project),
                "targets": targets or ["(default)"], "dirs": dirs, "sha256": digest,
                "size": size, "parts": parts, "licence_files": licences,
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **fingerprint(project)}
    (out / f"{name}.json").write_text(json.dumps(manifest, indent=1) + "\n")
    log(f"saved {name}: {len(dirs)} build directories, {size / 1e6:.0f} MB"
        + (f" in {len(parts)} parts" if parts else "") + f", sha256 {digest} "
        f"({time.time() - t0:.0f}s)")
    return manifest


def _release(repo: str) -> dict:
    """The `build-cache` prerelease, created once at the default branch."""
    r = curl([f"{API}/repos/{repo}/releases/tags/{RELEASE}"])
    if r.returncode == 0:
        return json.loads(r.stdout)
    body = json.dumps({"tag_name": RELEASE, "name": "Lean build cache", "prerelease": True,
                       "make_latest": "false",
                       "body": "Archives of Lean build output, one per commit, made by "
                               "`machinechecked cache save`. Each archive's `.json` manifest "
                               "names the repository and commit it was built from; the build is "
                               "distributed under that repository's licence, attached here. "
                               "Restored builds are trusted as built: proofs are re-checked "
                               "only by a kernel replay."})
    r = curl(["-X", "POST", "-H", "Content-Type: application/json",
              f"{API}/repos/{repo}/releases", "-d", body])
    if r.returncode != 0:
        raise CacheError(f"release creation failed: {r.stdout.decode()} {r.stderr.decode()}")
    return json.loads(r.stdout)


def publish(project: Path, out: Path, repo: str, log=print) -> None:
    """Upload the saved archive of the current commit, its manifest and the project's licence
    files to the `build-cache` release of `repo`."""
    if not token():
        raise CacheError("no token: set MACHINECHECKED_GH_TOKEN to publish")
    commit = _sh(["git", "rev-parse", "HEAD"], cwd=project)
    name = asset_prefix(project) + commit
    manifest = json.loads((out / f"{name}.json").read_text())
    files = [(out / p["name"], p["sha256"]) for p in manifest["parts"]] if manifest.get("parts") \
        else [(out / f"{name}.tar.zst", manifest["sha256"]),
              (out / f"{name}.tar.zst.sha256", None)]
    for f, want in files:
        if want and sha256(f) != want:
            raise CacheError(f"{f.name} does not match its manifest")
    files.append((out / f"{name}.json", None))
    files += [(project / f, None) for f in manifest.get("licence_files", [])]
    rel = _release(repo)
    have = {x["name"]: x for x in rel.get("assets", [])}
    for f, want in files:
        if f.name in have:
            log(f"{RELEASE}: {f.name} already published")
            continue
        ctype = "application/octet-stream" if want else "text/plain"
        t0 = time.time()
        r = curl(["-X", "POST", "-H", f"Content-Type: {ctype}", "--data-binary", f"@{f}",
                  f"{UPLOADS}/repos/{repo}/releases/{rel['id']}/assets?name={f.name}"])
        if r.returncode != 0:
            raise CacheError(f"upload of {f.name} failed: {r.stdout.decode()[:500]} "
                             f"{r.stderr.decode()}")
        asset = json.loads(r.stdout)
        if want and asset.get("digest") and asset["digest"] != f"sha256:{want}":
            raise CacheError(f"GitHub's digest {asset['digest']} for {f.name} differs from "
                             "the local sha256")
        log(f"{RELEASE}: published {f.name} ({time.time() - t0:.0f}s)")


class _Source:
    """Where cached assets come from: a release (`owner/repo`) or a local directory."""

    def __init__(self, repo: str | None, local: Path | None):
        self.local = local
        if local is not None:
            self.assets = {p.name: {"name": p.name} for p in local.iterdir() if p.is_file()}
            return
        r = curl([f"{API}/repos/{repo}/releases/tags/{RELEASE}"], auth=bool(token()))
        self.assets = ({x["name"]: x for x in json.loads(r.stdout).get("assets", [])}
                       if r.returncode == 0 else {})

    def fetch(self, name: str, dest: Path) -> None:
        if self.local is not None:
            shutil.copyfile(self.local / name, dest)
            return
        r = curl(["-o", str(dest), self.assets[name]["url"]], auth=bool(token()),
                 accept="application/octet-stream")
        if r.returncode != 0:
            raise CacheError(f"download of {name} failed: {r.stderr.decode()}")

    def digest(self, name: str) -> str | None:
        return self.assets[name].get("digest")


def restore(project: Path, repo: str | None = None, local: Path | None = None,
            build: bool = False, lake: str = "lake", log=print) -> dict:
    """Restore the nearest compatible cached build of `project` from the `build-cache`
    release of `repo`, or from the directory `local`."""
    here = fingerprint(project)
    src = _Source(repo, local)
    prefix = asset_prefix(project)
    best = None
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in sorted(src.assets):
            if not (name.startswith(prefix) and name.endswith(".json")):
                continue
            stem = name[:-5]
            src.fetch(name, tmp / name)
            man = json.loads((tmp / name).read_text())
            wanted = [p["name"] for p in man["parts"]] if man.get("parts") else [f"{stem}.tar.zst"]
            if any(w not in src.assets for w in wanted):
                continue
            mismatch = [k for k in here if man.get(k) != here[k]]
            if mismatch:
                log(f"skip {stem}: differs in {', '.join(mismatch)}")
                continue
            if subprocess.run(["git", "merge-base", "--is-ancestor", man["commit"], "HEAD"],
                              cwd=project, capture_output=True).returncode != 0:
                log(f"skip {stem}: not an ancestor of HEAD")
                continue
            dist = int(_sh(["git", "rev-list", "--count", f"{man['commit']}..HEAD"], cwd=project))
            if best is None or dist < best[0]:
                best = (dist, stem, man)
        if best is None:
            raise CacheError("no compatible cached build; build from source")
        dist, stem, man = best
        t0 = time.time()
        arc = tmp / f"{stem}.tar.zst"
        pieces = man["parts"] if man.get("parts") else [{"name": arc.name, "sha256": man["sha256"]}]
        with open(arc, "wb") as whole:
            for p in pieces:
                f = tmp / f"download-{p['name']}"
                src.fetch(p["name"], f)
                got = sha256(f)
                if got != p["sha256"]:
                    raise CacheError(f"{p['name']}: sha256 {got} is not the manifest's "
                                     f"{p['sha256']}; build from source")
                gh = src.digest(p["name"])
                if gh and gh != f"sha256:{got}":
                    raise CacheError(f"{p['name']}: sha256 differs from GitHub's recorded "
                                     f"digest {gh}; build from source")
                with open(f, "rb") as part:
                    shutil.copyfileobj(part, whole)
                f.unlink()
        got = sha256(arc)
        if got != man["sha256"]:
            raise CacheError(f"sha256 {got} is not the manifest's {man['sha256']}; "
                             "build from source")
        _sh(["tar", "-C", str(project.parent), "-I", "zstd -T0", "-xf", str(arc)])
    log(f"restored {stem} ({dist} commits behind HEAD, sha256 {got[:16]}…) "
        f"in {time.time() - t0:.0f}s")
    record = {"asset": stem, "commit": man["commit"], "sha256": got, "commits_behind": dist,
              "targets": man.get("targets")}
    (project / ".lake" / "lean-cache-restored.json").write_text(json.dumps(record, indent=1)
                                                                + "\n")
    if build:
        targets = [t for t in man.get("targets", []) if t != "(default)"]
        if subprocess.run([lake, "build", "--rehash", *targets], cwd=project).returncode != 0:
            raise CacheError("lake build after the restore failed")
    return record
