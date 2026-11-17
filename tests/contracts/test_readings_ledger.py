"""A readings ledger's rows name declarations and the revision they were read at; `check` warns
about the rows those declarations' changes made stale, and changes no status (#686)."""

from __future__ import annotations

import json
import subprocess

from conftest import build, edit, needs_lean, needs_tex
from prooflens import cli


def git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def ledger_repo(toy, rows):
    """The toy as a Git repository with a ledger of `rows` (each given its `read_at` by the
    caller with `{rev}`), committed; the revision."""
    (toy / "audit").mkdir()
    edit(toy / "machinechecked.toml", 'inventory = "claims.json"',
         'inventory = "claims.json"\nreadings_ledger = "audit/readings.json"')
    git(toy, "init", "-q")
    git(toy, "-c", "user.name=t", "-c", "user.email=t@example.org", "add", "-A")
    git(toy, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "start")
    rev = git(toy, "rev-parse", "HEAD")
    (toy / "audit" / "readings.json").write_text(json.dumps(
        {"rows": [{**r, **({"read_at": r["read_at"].format(rev=rev[:10])}
                            if "read_at" in r else {})} for r in rows]}))
    return rev


def check_json(toy, monkeypatch, capsys) -> dict:
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check", "--json"])
    except SystemExit:
        pass
    return json.loads(capsys.readouterr().out)


def ledger_warnings(doc) -> dict:
    return {w.get("row"): w for w in doc.get("warnings", []) if w["kind"] == "readings-ledger"}


@needs_lean
@needs_tex
def test_stale_rows_are_listed_and_change_no_status(toy, monkeypatch, capsys):
    ledger_repo(toy, [
        {"id": "R1", "text": "no bound on triangle numbers is proved",
         "declarations": ["Toy.triangle"], "read_at": "{rev}"},
        {"id": "R2", "text": "evenness is the paper's",
         "declarations": ["Toy.PaperSpec.thm_even_add"], "read_at": "{rev}"},
        {"id": "R3", "text": "an old lemma", "declarations": ["Toy.gone_lemma"],
         "read_at": "{rev}"},
        {"id": "R4", "declarations": ["Toy.IsEven"], "read_at": "not-a-revision"},
        {"id": "R5", "declarations": ["Toy.IsEven"]},
    ])
    before, _, _ = build(toy)

    # Nothing changed since the rows were read: only the missing name and the rows without a
    # usable revision are reported.
    w = ledger_warnings(check_json(toy, monkeypatch, capsys))
    assert set(w) == {"R3", "R4", "R5"}
    assert w["R3"]["missing"] == ["Toy.gone_lemma"]
    assert "not a revision" in w["R4"]["message"]
    assert "records no revision" in w["R5"]["message"]

    # A new theorem in the namespace of `Toy.triangle`: its row is stale, with the theorem's
    # statement; `Toy.triangle` itself is unchanged.
    defs = toy / "lean" / "Toy" / "Defs.lean"
    edit(defs, "end Toy", "/-- A bound. -/\ntheorem triangle_le (n : Nat) : triangle n ≤ n * n := "
                          "by\n  sorry\n\nend Toy")
    doc = check_json(toy, monkeypatch, capsys)
    w = ledger_warnings(doc)
    assert set(w) == {"R1", "R3", "R4", "R5"}
    (new,) = w["R1"]["new"]
    statement = "∀ (n : Nat), Toy.triangle n ≤ n * n"
    assert new["name"] == "Toy.triangle_le" and new["statement"] == statement
    assert w["R1"]["changed"] == []
    assert f"Toy.triangle_le : {statement}" in w["R1"]["message"]
    assert "Read the row again" in w["R1"]["message"]

    # The warnings change no status.
    assert {c["id"]: c["status"] for c in doc["claims"]} == \
        {c["id"]: c["status"] for c in before["claims"]}

    # An edit of a named declaration makes its row stale; the ledger is never rewritten.
    text = (toy / "audit" / "readings.json").read_text()
    edit(toy / "lean" / "Toy" / "PaperSpec.lean", "def thm_even_add : Prop :=",
         "def thm_even_add : Prop :=\n ")
    w = ledger_warnings(check_json(toy, monkeypatch, capsys))
    assert [e["name"] for e in w["R2"]["changed"]] == ["Toy.PaperSpec.thm_even_add"]
    assert (toy / "audit" / "readings.json").read_text() == text

    # `check` prints the same warnings.
    capsys.readouterr()
    try:
        cli.main(["check"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert any("readings ledger audit/readings.json row R1" in l and "Toy.triangle_le" in l
               for l in out.splitlines())


def test_a_ledger_outside_git_or_unreadable_is_reported(tmp_path):
    from types import SimpleNamespace

    from prooflens.ledger import stale_rows
    cfg = SimpleNamespace(readings_ledger=tmp_path / "readings.json", root=tmp_path,
                          lean_root=tmp_path)
    content = {"retrieval": {"docs": []}}
    (w,) = stale_rows(cfg, content)
    assert "does not exist" in w["message"]
    (tmp_path / "readings.json").write_text("[]")
    assert "not in a Git repository" in stale_rows(cfg, content)[0]["message"]
    assert stale_rows(SimpleNamespace(readings_ledger=None), content) == []
