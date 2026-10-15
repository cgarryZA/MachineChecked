"""Hashing, canonical JSON and process helpers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def sha256_file(p: str | Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj) -> str:
    """JSON with sorted keys and no insignificant whitespace: the form that is hashed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_id(obj) -> str:
    return sha256_text(canonical_json(obj))


def norm_ws(text: str) -> str:
    """Whitespace normalisation of manuscript source: runs of whitespace become one space."""
    return re.sub(r"\s+", " ", text).strip()


def run(cmd: list[str], cwd: str | Path, env: dict | None = None, timeout: int = 3600):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout)


def git_head(path: str | Path) -> str | None:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def git_dirty(path: str | Path) -> bool | None:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=path, capture_output=True,
                       text=True)
    return bool(r.stdout.strip()) if r.returncode == 0 else None


def write_json(path: str | Path, obj, indent: int | None = 1) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=indent, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")


def read_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
