"""Regenerate web/tests/fixtures/structure/data: the reader data the engine writes for the
synthetic project tests/fixtures/structure (zero configuration). Needs elan and a TeX
distribution with latexmk (any: what the TeX build decides is not compared).

    python3 web/tests/fixtures/make_structure.py

Run it after changing the fixture or what the engine writes for it, and commit the result:
`tests/simple/test_structure.py` makes the data again and fails when the committed copy differs
(`differences`).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "tests" / "fixtures" / "structure"
OUT = Path(__file__).resolve().parent / "structure" / "data"

# The date every copied file is given (2026-01-01, UTC). A paper read from a folder is compiled
# dated by its files' latest modification time, so a fixed date gives the same PDF, and so the
# same release, from every checkout.
EPOCH = 1767225600


def copy_fixture(dest: Path) -> Path:
    """A copy of the fixture at `dest`, every file dated `EPOCH`."""
    shutil.copytree(SRC, dest)
    for p in [dest, *dest.rglob("*")]:
        os.utime(p, (EPOCH, EPOCH))
    return dest


def write_data(work: Path, out: Path) -> None:
    """Build the site of the copy `work` (its Lean already built) beside it, and put the site's
    data at `out`."""
    site = work.parent / "site"
    subprocess.run([sys.executable, "-m", "prooflens", "build", "--site", str(site)], cwd=work,
                   check=True)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(site / "data", out)


# What depends on the TeX installation that compiled the paper, not on the fixture or the engine:
# the PDF's bytes (its banner names the TeX build), its hash, the coordinates of the anchors on its
# pages, and the release and evidence ids made from them. Compared, it would tie the copy to one
# TeX build.
TEX_MADE = ("pdf_sha256", "release", "evidence")


def _without_tex(v, in_anchor: bool = False):
    """`v` with what the TeX installation decides replaced by a placeholder: the values of the
    keys `TEX_MADE`, and the coordinates (numbers that are not whole) inside an anchor. An
    anchor's page, line and label stay compared."""
    if isinstance(v, dict):
        return {k: "<tex>" if k in TEX_MADE and isinstance(x, str)
                else _without_tex(x, in_anchor or k == "anchor") for k, x in v.items()}
    if isinstance(v, list):
        return [_without_tex(x, in_anchor) for x in v]
    if in_anchor and isinstance(v, float):
        return "<coordinate>"
    return v


def _comparable(p: Path) -> bytes:
    """A file's content as the check compares it: without the time of the build that wrote it
    (the index's `created`) or what the TeX installation decides (`_without_tex`); a PDF is
    compared by its presence only."""
    if p.suffix == ".pdf":
        return b""
    data = p.read_bytes()
    if p.suffix != ".json":
        return data
    v = json.loads(data)
    if p.name == "index.json" and p.parent.name == "data":
        v.pop("created", None)
    return json.dumps(_without_tex(v), sort_keys=True).encode()


def differences(made: Path, committed: Path) -> list[str]:
    """How the data `made` and the data `committed` differ: the files only one of them has, and
    those whose content is not the same (`_comparable`)."""
    def files(d):
        return {p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()}
    a, b = files(made), files(committed)
    return ([f"{f}: not committed" for f in sorted(a - b)]
            + [f"{f}: committed, no longer made" for f in sorted(b - a)]
            + [f"{f}: differs" for f in sorted(a & b)
               if _comparable(made / f) != _comparable(committed / f)])


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        work = copy_fixture(Path(tmp) / "structure")
        subprocess.run(["lake", "build"], cwd=work, check=True)
        write_data(work, OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
