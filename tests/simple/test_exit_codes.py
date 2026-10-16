"""Exit codes of the command: 1 means the check ran and found a problem, 2 means it could not run."""

import pytest

from prooflens import cli


def test_missing_lake_exits_2_not_1(monkeypatch):
    def no_lake(a):
        raise FileNotFoundError(2, "No such file or directory", "lake")

    monkeypatch.setattr(cli, "cmd_check", no_lake)
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--json", "paper.tex"])
    assert exc.value.code == 2
