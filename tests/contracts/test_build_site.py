"""`build --site DIR` in a full-assessment project writes the audit's public export to DIR, and
refuses a directory it would destroy (#50)."""

import json

import pytest

from conftest import needs_lean, needs_tex
from prooflens import cli


@needs_lean
@needs_tex
def test_build_site_writes_the_export_there(toy, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(toy)
    out = tmp_path / "published"
    cli.main(["build", "--site", str(out)])
    assert (out / "audit.json").exists() and (out / "data" / "index.json").exists()
    assert json.loads((out / "data" / "index.json").read_text())["claims"]
    assert f"wrote the audit to {out}" in capsys.readouterr().out
    # A previous site is replaced; a directory holding anything else is refused untouched.
    cli.main(["build", "--site", str(out), "--reuse-lean"])
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("keep")
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--site", str(other), "--reuse-lean"])
    assert e.value.code == 2 and "not empty and not a previous site" in capsys.readouterr().err
    assert (other / "notes.txt").read_text() == "keep"
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--site", str(toy), "--reuse-lean"])
    assert e.value.code == 2 and "not the project" in capsys.readouterr().err
