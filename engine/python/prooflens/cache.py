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
    """The build output to archive, relative to the project's parent (as recorded in the
    manifest's `dirs`, for reading)."""
    parent = project.parent
    return [str(src.relative_to(parent)) if src.is_relative_to(parent) else str(src)
            for src, _ in _members(project)]


def _members(project: Path) -> list[tuple[Path, str]]:
    """Each build directory to archive and its name in the archive: `project/<path>` for the
    project's own build and its packages' (relative to the project), `path/<name>/.lake/build`
    for a path dependency's (found again by its name on restore, wherever it is checked out)."""
    out = []
    skip = cache_supplied(project)
    rels = [".lake/build"]
    pk = project / ".lake" / "packages"
    if pk.exists():
        rels += [f".lake/packages/{p.name}/.lake/build" for p in sorted(pk.iterdir())
                 if p.name not in skip]
    out += [(project / r, f"project/{r}") for r in rels]
    out += [(d / ".lake" / "build", f"path/{d.name}/.lake/build") for d in path_deps(project)]
    return [(src, name) for src, name in out if src.is_dir()]


def package_name(project: Path) -> str:
    """The Lake package's name, which every clone shares (its folder's name need not)."""
    t = project / "lakefile.toml"
    if t.exists():
        import tomllib
        name = tomllib.loads(t.read_text(encoding="utf-8")).get("name")
        if name:
            return str(name)
    l = project / "lakefile.lean"
    if l.exists():
        import re
        m = re.search(r"^\s*package\s+«?([\w.'-]+)»?", l.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1)
    return project.name


def _prefix(name: str) -> str:
    return f"{name.lower()}-{platform.system().lower()}-{platform.machine().lower()}-"


def asset_prefix(project: Path) -> str:
    return _prefix(package_name(project))


def inputs_digest(project: Path) -> str | None:
    """A digest of the project's tracked Lean inputs (their Git blob hashes): equal for any clone
    of the same sources, shallow or not, whatever its history."""
    r = subprocess.run(["git", "ls-files", "-s", "--", *LEAN_INPUTS], cwd=project,
                       capture_output=True, text=True)
    return hashlib.sha256(r.stdout.encode()).hexdigest() if r.returncode == 0 else None


def _pack(arc: Path, members: list[tuple[Path, str]]) -> None:
    """Write the members to a zstd-compressed tar archive."""
    import tarfile
    z = subprocess.Popen(["zstd", "-T0", "-6", "-q", "-f", "-o", str(arc)],
                         stdin=subprocess.PIPE)
    with tarfile.open(fileobj=z.stdin, mode="w|") as tf:
        for src, name in members:
            tf.add(src, arcname=name)
    z.stdin.close()
    if z.wait() != 0:
        raise CacheError("zstd failed while writing the archive")


def _unpacked_size(members: list[tuple[Path, str]]) -> int:
    """The bytes of the files the archive holds, unpacked."""
    total = 0
    for src, _ in members:
        for f in src.rglob("*"):
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
    return total


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB"


def check_space(project: Path, tmp: Path, man: dict) -> None:
    """Refuse a restore that cannot fit, before anything is downloaded: the archive needs its
    size in `tmp`, and its unpacked build (recorded by `save`; four times the archive for an
    older manifest) next to the project."""
    size = int(man.get("size") or 0)
    unpacked = int(man.get("unpacked_size") or 4 * size)
    lake = project / ".lake"
    where = lake if lake.exists() else project
    need = {where: unpacked}
    if os.stat(tmp).st_dev == os.stat(where).st_dev:
        need[where] += size
    else:
        need[tmp] = size
    for path, n in need.items():
        free = shutil.disk_usage(path).free
        if free < n:
            raise CacheError(
                f"not enough disk space to restore: {_gb(n)} needed under {path}, {_gb(free)} "
                "free. Free some space (for example a second copy of a dependency at the same "
                "revision, or old build output) and restore again; nothing was changed")


def _unpack(arc: Path, project: Path, older: bool = False) -> None:
    """Unpack an archive written by `_pack` into the project and its path dependencies, with the
    tar `data` filter (no absolute paths, no `..`, no links out of the destination). Everything
    is unpacked into a staging folder first and moved into place only once the whole archive
    has been read, so a failure (a full disk, a corrupt archive) leaves the build as it was.

    An archive in the older layout (`older`) holds paths from the checkout's parent, under the
    folder names of the checkout it was made in; each top folder is mapped onto the project or a
    path dependency whose folder has that name in any case, and any other path is refused."""
    import tarfile
    deps = {d.name: d for d in path_deps(project)}
    folded = {d.name.lower(): d for d in deps.values()}
    stage = Path(tempfile.mkdtemp(prefix=".lean-cache-restore-", dir=project))
    try:
        bases: dict[str, Path] = {}
        z = subprocess.Popen(["zstd", "-d", "-q", "-c", str(arc)], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=z.stdout, mode="r|") as tf:
            for m in tf:
                head, _, rest = m.name.partition("/")
                if older and not rest.strip("/") and m.isdir():
                    continue  # the top folder itself
                if older and rest and head.lower() == project.name.lower():
                    key, base, m.name = "project", project, rest
                elif older and rest and head.lower() in folded:
                    base = folded[head.lower()]
                    key, m.name = f"path-{base.name}", rest
                elif older:
                    raise CacheError(f"the archive's path {m.name} is not in this project or a "
                                     "path dependency of it; build from source")
                elif head == "project" and rest:
                    key, base, m.name = "project", project, rest
                elif head == "path" and rest.partition("/")[0] in deps:
                    name, _, m.name = rest.partition("/")
                    key, base = f"path-{name}", deps[name]
                else:
                    raise CacheError(f"unexpected path in the archive: {m.name}")
                bases[key] = base
                tf.extract(m, stage / key, filter="data")
        if z.wait() != 0:
            raise CacheError("zstd failed while reading the archive")
        for key, base in bases.items():
            root = stage / key
            for f in sorted(root.rglob("*")):
                if f.is_dir() and not f.is_symlink():
                    continue
                dest = base / f.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
    except OSError as e:
        raise CacheError(f"the restore failed ({e}); the build was left as it was") from e
    finally:
        shutil.rmtree(stage, ignore_errors=True)


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
    _pack(arc, _members(project))
    digest, size = sha256(arc), arc.stat().st_size
    parts = _split(arc, part_size) if size > part_size else None
    if parts is None:
        (out / f"{name}.tar.zst.sha256").write_text(f"{digest}  {arc.name}\n")
    licences = [f for f in LICENCE_FILES if (project / f).is_file()]
    manifest = {"commit": commit, "project": package_name(project), "layout": 2,
                "inputs_digest": inputs_digest(project), "repository": repository(project),
                "targets": targets or ["(default)"], "dirs": dirs, "sha256": digest,
                "size": size, "unpacked_size": _unpacked_size(_members(project)),
                "parts": parts, "licence_files": licences,
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
    digest = inputs_digest(project)
    src = _Source(repo, local)
    # Archives are named after the Lake package; older ones after the checkout's folder.
    prefixes = (asset_prefix(project), _prefix(project.name))
    best, no_history = None, False
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in sorted(src.assets):
            if not (name.startswith(prefixes) and name.endswith(".json")):
                continue
            stem = name[:-5]
            src.fetch(name, tmp / name)
            man = json.loads((tmp / name).read_text())
            if not man.get("layout") and not name.startswith(_prefix(project.name)):
                continue  # an archive in the older layout is named after the checkout's folder
            wanted = [p["name"] for p in man["parts"]] if man.get("parts") else [f"{stem}.tar.zst"]
            if any(w not in src.assets for w in wanted):
                continue
            mismatch = [k for k in here if man.get(k) != here[k]]
            if mismatch:
                log(f"skip {stem}: differs in {', '.join(mismatch)}")
                continue
            # The same Lean inputs: usable whatever the history (a shallow clone, a rewrite).
            if digest and man.get("inputs_digest") == digest:
                key = (0, 0)
            elif subprocess.run(["git", "merge-base", "--is-ancestor", man["commit"], "HEAD"],
                                cwd=project, capture_output=True).returncode == 0:
                key = (1, int(_sh(["git", "rev-list", "--count", f"{man['commit']}..HEAD"],
                                  cwd=project)))
            else:
                no_history = no_history or subprocess.run(
                    ["git", "rev-parse", "--is-shallow-repository"], cwd=project,
                    capture_output=True, text=True).stdout.strip() == "true"
                log(f"skip {stem}: not an ancestor of HEAD, and its Lean inputs differ")
                continue
            if best is None or key < best[0]:
                best = (key, stem, man)
        if best is None:
            raise CacheError("no compatible cached build; build from source"
                             + (" (this clone is shallow: with its history, `fetch-depth: 0` "
                                "in actions/checkout, a build of an earlier commit can be used)"
                                if no_history else ""))
        key, stem, man = best
        dist = key[1]
        check_space(project, tmp, man)
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
        _unpack(arc, project, older=man.get("layout") != 2)
    log(f"restored {stem} ("
        + ("the same Lean inputs" if key[0] == 0 else f"{dist} commits behind HEAD")
        + f", sha256 {got[:16]}…) "
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


def prune_plan(manifests: dict[str, dict], keep: int) -> list[str]:
    """The archives to delete: all but the newest `keep` of each package, platform and Lean
    version (an older build is useful only as the nearest one to recent work)."""
    groups: dict[tuple, list[tuple[str, str]]] = {}
    for stem, man in manifests.items():
        key = (man.get("project"), man.get("platform"), man.get("toolchain"))
        groups.setdefault(key, []).append((man.get("created") or "", stem))
    drop = []
    for items in groups.values():
        items.sort(reverse=True)
        drop += [stem for _, stem in items[keep:]]
    return sorted(drop)


def _files_of(stem: str, man: dict) -> list[str]:
    if man.get("parts"):
        return [p["name"] for p in man["parts"]] + [f"{stem}.json"]
    return [f"{stem}.tar.zst", f"{stem}.tar.zst.sha256", f"{stem}.json"]


def prune(repo: str, keep: int, log=print) -> list[str]:
    """Delete from the `build-cache` release of `repo` every archive (with its companions) but
    the newest `keep` of each package, platform and Lean version. Licence files stay."""
    if keep < 1:
        raise CacheError("keep at least one archive")
    if not token():
        raise CacheError("no token: set MACHINECHECKED_GH_TOKEN to prune")
    src = _Source(repo, None)
    manifests = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name in sorted(src.assets):
            if name.endswith(".json"):
                src.fetch(name, Path(tmp) / name)
                manifests[name[:-5]] = json.loads((Path(tmp) / name).read_text())
    drop = prune_plan(manifests, keep)
    for stem in drop:
        for f in _files_of(stem, manifests[stem]):
            if f in src.assets:
                r = curl(["-X", "DELETE", f"{API}/repos/{repo}/releases/assets/"
                          f"{src.assets[f]['id']}"])
                if r.returncode != 0:
                    raise CacheError(f"deleting {f} failed: {r.stderr.decode()}")
        log(f"{RELEASE}: deleted {stem}")
    log(f"{RELEASE}: kept {len(manifests) - len(drop)} archive(s), deleted {len(drop)}")
    return drop
