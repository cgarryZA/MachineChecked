"""In the full assessment, a name a module docstring lists that nothing declares is a warning
(#107): it names the module, the file and the line, never changes a status or a gate, and an
auditor can dismiss it with a written reason, as any warning."""

import json

from conftest import build, edit, findings, needs_lean, needs_tex
from prooflens import cli

DOC = ("## Main definitions\n\n"
       "* `Toy.IsEven` — evenness (declared).\n"
       "* `Toy.gone_lemma` — deleted since.\n"
       "* `L` — notation, not a declaration.\n\n")


def outcome(index, body):
    """Everything the assessment decides apart from the new warning."""
    return ({c["id"]: (c["status"], c["status_code"]) for c in index["claims"]},
            body["assessment"]["gates"],
            sorted(f["id"] for f in body["assessment"]["findings"]
                   if f["code"] != "module-doc-name"))


@needs_lean
@needs_tex
def test_a_stale_docstring_name_is_a_dismissable_warning(toy, monkeypatch, capsys):
    index, body, cfg = build(toy)
    assert not findings(body, "module-doc-name")
    before = outcome(index, body)
    warnings = index["findings"]["total"].get("warning", 0)

    edit(toy / "lean/Toy/Defs.lean", "The objects the statements of", DOC + "The objects the "
         "statements of")
    index, body, cfg = build(toy)
    (f,) = findings(body, "module-doc-name")
    lines = (toy / "lean/Toy/Defs.lean").read_text().splitlines()
    assert f["tier"] == "warning" and f["subject"] == "Toy.Defs" and f["trigger"] == "Toy.gone_lemma"
    assert f["file"] == "Toy/Defs.lean" and "`Toy.gone_lemma`" in lines[f["line"] - 1]
    assert f["message"] == (f"Toy/Defs.lean:{f['line']}: module docstring names Toy.gone_lemma, "
                            "which is not declared")
    # Statuses, gates and every other finding are as before; the warning is counted and listed
    # with the audit's general findings.
    assert outcome(index, body) == before
    assert index["findings"]["total"]["warning"] == warnings + 1
    assert [g["id"] for g in index["findings"]["general"]
            if g["code"] == "module-doc-name"] == [f["id"]]

    # `check` lists it with its file and line; `check --json` gives its details.
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check"])
    except SystemExit:
        pass
    assert f"  warning  {f['message']}" in capsys.readouterr().out
    try:
        cli.main(["check", "--json"])
    except SystemExit:
        pass
    doc = json.loads(capsys.readouterr().out)
    (d,) = [x for x in doc["finding_details"] if x["code"] == "module-doc-name"]
    assert (d["file"], d["line"], d["trigger"]) == ("Toy/Defs.lean", f["line"], "Toy.gone_lemma")

    # A dismissal with a written reason closes it; nothing else changes.
    path = toy / "reviews/dismissals.json"
    path.write_text(json.dumps(json.loads(path.read_text()) + [
        {"code": "module-doc-name", "subject": "Toy.Defs", "trigger": "Toy.gone_lemma",
         "fingerprint": f["fingerprint"], "rationale": "kept as a pointer to the old proof",
         "by": "auditor"}]))
    index, body, cfg = build(toy, reuse_lean=True)
    (f,) = findings(body, "module-doc-name")
    assert f["dismissed"] == {"rationale": "kept as a pointer to the old proof", "by": "auditor"}
    assert index["findings"]["total"].get("warning", 0) == warnings
    assert outcome(index, body) == before
